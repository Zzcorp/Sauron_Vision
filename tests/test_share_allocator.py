"""The share allocator — a shadow proposal, an admin's apply, a grade.

The 2026-09-10 deployment had one lane on the whole account and pools
typed by hand; the ask was that Sauron compute the shares continuously
and intelligently. This is the service under that ask, and these tests
pin what keeps it safe:

  * Nothing is proposed without a FRESH reading, and a proposal writes
    nothing anywhere but its own row.
  * The arithmetic: raw shares normalise to 100 × governor; floors and
    ceilings hold by water-fill; the move is smoothed, capped per day
    (counting what applied plans already moved), and HELD exactly when
    it is under the hysteresis; a reader that raises costs a factor, not
    a plan; the rule that refuses over-allocation refuses here too.
  * Apply: refused in shadow mode with one fixed sentence; in LIVE it
    writes every follower's explicit share, re-splits capital through
    the sync's own arithmetic, snapshots the previous shares exactly,
    skips a follower that stood down and says so, and stops at the
    daily cap. Rollback restores exactly — the key removed where the
    follower was automatic. Reject writes nothing.
  * The grade: positive when the plan leaned toward what then paid;
    ungradeable when nothing closed, which is not wrong.

Run with:  python manage.py test tests.test_share_allocator
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

User = get_user_model()


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
         capital="100", tracks=False, share=None, symbols=("AAPL",),
         **extras):
    from bot_program.models import AssetBotConfig
    ex = dict(extras)
    if tracks:
        ex["capital_tracks_broker"] = True
    if share is not None:
        ex["account_share_pct"] = share
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode=mode,
        enabled=enabled, symbols=list(symbols), capital=Decimal(capital),
        extras=ex)


def _fill(cfg, r, *, paper=False, rule="r1", days_ago=1.0, hours_ago=None):
    from bot_program.models import AssetBotTrade
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol="AAPL", side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"),
        exit_price=Decimal("101"), status="CLOSED", pnl=Decimal("1"),
        rule_name=rule, paper=paper, realized_r=r, outcome="hit_target")
    when = (timezone.now() - timedelta(hours=hours_ago) if hours_ago is not None
            else timezone.now() - timedelta(days=days_ago))
    AssetBotTrade.objects.filter(pk=t.pk).update(closed_at=when)
    return t


def _set_live(enabled: bool):
    from core.platform_control import PlatformComponent
    c, _ = PlatformComponent.objects.get_or_create(
        key="share_allocator_mode_live",
        defaults={"name": "Share Allocator Live Mode", "category": "system"})
    c.is_enabled = enabled
    c.save()


def _reading(acct, value, *, days_ago, currency="EUR"):
    from bot_program.models import BrokerEquityReading
    return BrokerEquityReading.objects.create(
        account=acct, value=Decimal(str(value)), currency=currency, env="live",
        at=timezone.now() - timedelta(days=days_ago))


def _capital(cfg) -> float:
    """The pool as the row holds it now — the sync's write, not the
    in-memory copy."""
    cfg.refresh_from_db()
    return float(cfg.capital)


def _applied(user, targets, previous, current=None, *, hours_ago=1.0):
    """An APPLIED plan on the books, as apply_share_plan would leave it."""
    from bot_program.share_models import SharePlan
    p = SharePlan.objects.create(
        user=user, state=SharePlan.STATE_APPLIED,
        targets={str(k): v for k, v in targets.items()},
        previous_shares={str(k): v for k, v in previous.items()},
        current_shares={str(k): v for k, v in (current or previous).items()},
        applied_at=timezone.now() - timedelta(hours=hours_ago))
    return p


class ThePureArithmeticTests(SimpleTestCase):

    def test_the_governor_curve(self):
        from bot_program.share_allocator import (DD_FLOOR, governor_for)
        self.assertEqual(governor_for(0.0), 1.0)
        self.assertEqual(governor_for(0.05), 1.0)
        self.assertAlmostEqual(governor_for(0.125), 0.7)      # halfway
        self.assertEqual(governor_for(0.20), DD_FLOOR)
        self.assertEqual(governor_for(0.50), DD_FLOOR)         # never below

    def test_water_fill_sums_to_the_total_inside_the_bounds(self):
        from bot_program.share_allocator import water_fill
        b = {1: (2.0, 60.0), 2: (2.0, 60.0), 3: (2.0, 60.0)}
        out = water_fill({1: 90.0, 2: 5.0, 3: 5.0}, b, 100.0)
        self.assertAlmostEqual(sum(out.values()), 100.0)
        self.assertAlmostEqual(out[1], 60.0)                   # ceiling
        self.assertAlmostEqual(out[2], 20.0)                   # re-shared
        self.assertAlmostEqual(out[3], 20.0)

    def test_water_fill_lifts_a_starved_key_to_its_floor(self):
        from bot_program.share_allocator import water_fill
        b = {1: (2.0, 60.0), 2: (5.0, 60.0)}
        out = water_fill({1: 100.0, 2: 0.0}, b, 50.0)
        self.assertAlmostEqual(out[2], 5.0)
        self.assertAlmostEqual(out[1], 45.0)
        self.assertAlmostEqual(sum(out.values()), 50.0)

    def test_water_fill_leaves_cash_when_ceilings_cannot_hold_the_total(self):
        from bot_program.share_allocator import water_fill
        b = {1: (2.0, 30.0), 2: (2.0, 30.0)}
        out = water_fill({1: 1.0, 2: 1.0}, b, 100.0)
        self.assertEqual(out, {1: 30.0, 2: 30.0})

    def test_water_fill_shares_evenly_when_nothing_has_weight(self):
        from bot_program.share_allocator import water_fill
        b = {1: (2.0, 60.0), 2: (2.0, 60.0)}
        self.assertEqual(water_fill({1: 0.0, 2: 0.0}, b, 80.0),
                         {1: 40.0, 2: 40.0})

    def test_water_fill_does_not_lose_mass_when_both_bounds_bind_at_once(self):
        """Regression (2026-09-12): fixing the overflowing key at its
        ceiling and the two starved keys at their floors in the SAME pass
        came back 60/2/2 — 36% of the account parked in cash that two
        pools had room for. The starved keys share what the ceiling
        released."""
        from bot_program.share_allocator import water_fill
        b = {1: (2.0, 60.0), 2: (2.0, 60.0), 3: (2.0, 60.0)}
        out = water_fill({1: 90.0, 2: 0.5, 3: 0.5}, b, 100.0)
        self.assertAlmostEqual(out[1], 60.0)
        self.assertAlmostEqual(out[2], 20.0)
        self.assertAlmostEqual(out[3], 20.0)
        self.assertAlmostEqual(sum(out.values()), 100.0)

    def test_water_fill_never_deploys_past_the_total(self):
        """Regression (2026-09-12): a floor above what the ceilings left
        came back 55 + 50 = 105% of one account — the direction in which
        every limit is looser than it reads. The key at its ceiling must
        give way to the floor: 50 + 50."""
        from bot_program.share_allocator import water_fill
        b = {1: (2.0, 55.0), 2: (50.0, 100.0)}
        out = water_fill({1: 60.0, 2: 40.0}, b, 100.0)
        self.assertAlmostEqual(out[1], 50.0)
        self.assertAlmostEqual(out[2], 50.0)
        self.assertAlmostEqual(sum(out.values()), 100.0)
        # And a weightless key sits at its floor whatever the scale.
        out = water_fill({1: 10.0, 2: 0.0}, {1: (2.0, 60.0), 2: (5.0, 60.0)},
                         100.0)
        self.assertEqual(out, {1: 60.0, 2: 5.0})

    def test_shave_takes_from_moved_targets_first_and_always_terminates(self):
        from bot_program.share_allocator import _shave_to_100
        b = {1: (2.0, 60.0), 2: (2.0, 60.0), 3: (2.0, 60.0)}
        third = 100.0 / 3.0
        # Two held thirds and one rounded third sum 0.0067 past 100: the
        # rounded one gives, the held ones stay exact.
        t = {1: 33.34, 2: third, 3: third}
        cuts = _shave_to_100(t, b, {2, 3})
        self.assertEqual(set(cuts), {1})
        self.assertEqual(t[1], 33.33)
        self.assertEqual(t[2], third)
        self.assertLessEqual(sum(t.values()), 100.0 + 1e-6)
        # A held target gives only when nothing else has room, never
        # below its floor; a sub-cent cut rounding would eat becomes a
        # cent, so the loop cannot spin on 55.00 - 0.004 == 55.00.
        t = {1: 60.0, 2: 40.003}
        cuts = _shave_to_100(t, b, {1, 2})
        self.assertEqual(t, {1: 59.99, 2: 40.003})
        self.assertAlmostEqual(cuts[1], 0.01)
        t = {1: 2.0, 2: 99.0}
        cuts = _shave_to_100(t, b, {2})
        self.assertEqual(t, {1: 2.0, 2: 98.0})
        # Nothing to cut: untouched.
        t = {1: 55.0, 2: 45.0}
        self.assertEqual(_shave_to_100(t, b, set()), {})
        self.assertEqual(t, {1: 55.0, 2: 45.0})

    def test_the_factor_maps(self):
        from bot_program.share_allocator import news_factor, opportunity_factor
        self.assertEqual(opportunity_factor(0.0, False), 1.0)
        self.assertAlmostEqual(opportunity_factor(0.0, True), 0.8)
        self.assertAlmostEqual(opportunity_factor(0.125, True), 1.0)
        self.assertAlmostEqual(opportunity_factor(0.9, True), 1.2)
        self.assertEqual(news_factor({"blind": True, "avg_sent": -1.0,
                                      "n_graded": 9, "events_24h": 3}), 1.0)
        self.assertAlmostEqual(news_factor({"blind": False, "avg_sent": -0.5,
                                            "n_graded": 3, "events_24h": 0}),
                               0.85)
        self.assertAlmostEqual(news_factor({"blind": False, "avg_sent": 0.5,
                                            "n_graded": 3, "events_24h": 1}),
                               0.9)
        self.assertEqual(news_factor({"blind": False, "avg_sent": -1.0,
                                      "n_graded": 2, "events_24h": 0}), 1.0)
        self.assertAlmostEqual(news_factor({"blind": False, "avg_sent": -1.0,
                                            "n_graded": 5, "events_24h": 2}),
                               0.6)                                 # floored

    def test_bounds_come_from_extras_when_sane(self):
        from types import SimpleNamespace

        from bot_program.share_allocator import (DEFAULT_CEILING_PCT,
                                                 DEFAULT_FLOOR_PCT, bounds_for)
        ok = bounds_for(SimpleNamespace(extras={"share_floor_pct": 5,
                                                "share_ceiling_pct": "40"}))
        self.assertEqual(ok[:2], (5.0, 40.0))
        bad = bounds_for(SimpleNamespace(extras={"share_floor_pct": 50,
                                                 "share_ceiling_pct": 40}))
        self.assertEqual(bad[:2], (DEFAULT_FLOOR_PCT, DEFAULT_CEILING_PCT))
        self.assertIn("defaults", bad[2])
        nan = bounds_for(SimpleNamespace(extras={"share_ceiling_pct": "x"}))
        self.assertEqual(nan[:2], (DEFAULT_FLOOR_PCT, DEFAULT_CEILING_PCT))


class ProposeTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("sa_u", password="x")
        self.acct = _acct(self.user)

    def test_a_stale_reading_proposes_nothing(self):
        from bot_program.capital_truth import TRACKING_FRESH_SECONDS
        from bot_program.share_allocator import propose_share_plan_with_reason
        from bot_program.share_models import SharePlan
        self.acct.last_equity_at = timezone.now() - timedelta(
            seconds=TRACKING_FRESH_SECONDS + 5)
        self.acct.save()
        _cfg(self.user, name="a", tracks=True, share=50)
        plan, reason = propose_share_plan_with_reason(self.user)
        self.assertIsNone(plan)
        self.assertIn("no fresh reading", reason)
        self.assertEqual(SharePlan.objects.count(), 0)

    def test_no_followers_proposes_nothing(self):
        from bot_program.share_allocator import propose_share_plan
        _cfg(self.user, name="typed")                    # not a follower
        _cfg(self.user, name="paper", mode="paper", tracks=True)
        self.assertIsNone(propose_share_plan(self.user))

    def test_a_proposal_writes_only_its_own_row(self):
        from bot_program.share_allocator import propose_share_plan
        from bot_program.share_models import SharePlan
        a = _cfg(self.user, name="a", tracks=True, share=50, capital="1000")
        b = _cfg(self.user, name="b", tracks=True, share=50, capital="1000")
        plan = propose_share_plan(self.user)
        self.assertEqual(plan.state, SharePlan.STATE_PROPOSED)
        self.assertEqual(float(plan.reading_value), 2000.0)
        self.assertEqual(plan.reading_currency, "EUR")
        self.assertEqual(plan.configs_considered, 2)
        self.assertIn("hwm from 1 reading", plan.notes)
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual(a.extras["account_share_pct"], 50)
        self.assertEqual(float(a.capital), 1000.0)
        self.assertEqual(float(b.capital), 1000.0)
        row = plan.inputs[str(a.pk)]
        for key in ("name", "asset_class", "mode", "current", "target",
                    "floor", "ceiling", "raw", "capped", "smoothed", "held",
                    "evidence", "regime", "opportunity", "news", "why"):
            self.assertIn(key, row)
        self.assertIn("evidence 1.00", row["why"])
        self.assertIn("→", row["why"])
        self.assertIn("news 1.00 (blind)", row["why"])

    def test_neutral_inputs_hold_every_share_exactly(self):
        from bot_program.share_allocator import propose_share_plan
        a = _cfg(self.user, name="a", tracks=True, share=40)
        b = _cfg(self.user, name="b", tracks=True, share=60)
        plan = propose_share_plan(self.user)
        self.assertEqual(plan.targets[str(a.pk)], 40.0)
        self.assertEqual(plan.targets[str(b.pk)], 60.0)
        self.assertTrue(plan.inputs[str(a.pk)]["held"])
        self.assertTrue(plan.inputs[str(b.pk)]["held"])
        self.assertIn("held", plan.inputs[str(a.pk)]["why"])

    def test_held_automatic_shares_repeat_the_current_exactly(self):
        """Regression (2026-09-12): three automatic followers hold
        33.333…% each; a held target rounded to 33.33 left 0.01% of the
        account unclaimed and re-sized every pool by a few cents on a
        plan that said "held". Held means the sync writes nothing."""
        from bot_program.share_allocator import (apply_share_plan,
                                                 propose_share_plan)
        from bot_program.tasks import _follow_the_account
        cfgs = [_cfg(self.user, name=f"c{i}", tracks=True) for i in range(3)]
        _follow_the_account(self.user, 2000.0, "EUR")
        before = {c.pk: _capital(c) for c in cfgs}
        plan = propose_share_plan(self.user)
        for c in cfgs:
            k = str(c.pk)
            self.assertTrue(plan.inputs[k]["held"])
            self.assertEqual(plan.targets[k], plan.current_shares[k])
            self.assertAlmostEqual(plan.targets[k], 100.0 / 3.0, places=9)
            self.assertNotEqual(plan.targets[k], 33.33)       # not rounded
        self.assertAlmostEqual(sum(plan.targets.values()), 100.0, places=9)
        _set_live(True)
        apply_share_plan(plan.pk, None)
        for c in cfgs:
            self.assertEqual(_capital(c), before[c.pk])
            self.assertEqual(_capital(c), 666.67)

    def test_a_follower_below_its_floor_is_lifted_not_held(self):
        """a was typed at 1% under a 2% floor. Smoothing halves the gap
        (1.5) and hysteresis would hold it at 1% for ever; once the gap
        is under the hysteresis the floor wins, and the point comes off
        b even though b's own move was under the hysteresis. A share
        further under its floor keeps the smoothed path — that case is
        test_ceilings_and_floors_hold (50 → 52.5 under a 55% floor)."""
        from bot_program.share_allocator import propose_share_plan
        a = _cfg(self.user, name="a", tracks=True, share=1)
        b = _cfg(self.user, name="b", tracks=True, share=99,
                 share_ceiling_pct=100)
        plan = propose_share_plan(self.user)
        ia, ib = plan.inputs[str(a.pk)], plan.inputs[str(b.pk)]
        self.assertEqual(plan.targets[str(a.pk)], 2.0)
        self.assertFalse(ia["held"])
        self.assertEqual(plan.targets[str(b.pk)], 98.0)
        self.assertFalse(ib["held"])
        self.assertIn("shaved to fit 100%", ib["why"])
        self.assertIn("a: below its floor — lifted to 2%", plan.notes)
        self.assertAlmostEqual(sum(plan.targets.values()), 100.0)

    def test_a_new_follower_in_an_over_allocated_fleet_gets_its_floor(self):
        """Two explicit halves and a third pool that just opted in: the
        rule refuses the current split (no current share for c), so c
        enters at its floor and the plan still fits in 100%."""
        from bot_program.share_allocator import propose_share_plan
        a = _cfg(self.user, name="a", tracks=True, share=50)
        b = _cfg(self.user, name="b", tracks=True, share=50)
        c = _cfg(self.user, name="c", tracks=True)
        plan = propose_share_plan(self.user)
        self.assertIsNotNone(plan)
        self.assertIsNone(plan.current_shares[str(c.pk)])
        self.assertEqual(plan.targets[str(c.pk)], 2.0)
        self.assertIn("current shares do not fit", plan.notes)
        self.assertIn("c: below its floor — lifted to 2%", plan.notes)
        self.assertEqual(sorted([plan.targets[str(a.pk)],
                                 plan.targets[str(b.pk)]]), [48.0, 50.0])
        self.assertAlmostEqual(sum(plan.targets.values()), 100.0)

    def test_an_automatic_follower_gets_its_computed_current_share(self):
        from bot_program.share_allocator import propose_share_plan
        a = _cfg(self.user, name="a", tracks=True, share=40)
        b = _cfg(self.user, name="b", tracks=True)             # auto = 60
        plan = propose_share_plan(self.user)
        self.assertEqual(plan.current_shares[str(b.pk)], 60.0)
        self.assertEqual(plan.targets[str(b.pk)], 60.0)
        self.assertEqual(plan.targets[str(a.pk)], 40.0)

    def test_evidence_moves_the_share_smoothed_and_normalised(self):
        """a: 10 live wins of +1R → score 1.5; b (forex, so the fleet
        lane does not lend it a's fills): unmeasured 1.0.
        raw 75/50 → normalised 60/40 → smoothed halfway: 55/45."""
        from bot_program.share_allocator import propose_share_plan
        a = _cfg(self.user, name="a", tracks=True, share=50)
        b = _cfg(self.user, name="b", tracks=True, share=50,
                 asset_class="forex", symbols=["EURUSD"])
        for _ in range(10):
            _fill(a, 1.0)
        plan = propose_share_plan(self.user)
        ia, ib = plan.inputs[str(a.pk)], plan.inputs[str(b.pk)]
        self.assertEqual(ia["evidence"]["lane"], "live")
        self.assertAlmostEqual(ia["evidence"]["score"], 1.5)
        self.assertAlmostEqual(ia["capped"], 60.0, places=3)
        self.assertAlmostEqual(ib["capped"], 40.0, places=3)
        self.assertAlmostEqual(ia["capped"] + ib["capped"], 100.0, places=3)
        self.assertEqual(plan.targets[str(a.pk)], 55.0)
        self.assertEqual(plan.targets[str(b.pk)], 45.0)
        self.assertFalse(ia["held"])
        self.assertIn("evidence 1.50 (live, n=10", ia["why"])

    def test_the_governor_leaves_the_drawdown_in_cash(self):
        """20% under the 90-day high → governor 0.4 → capped shares sum
        to 40; the move down is then capped at 10 points per day."""
        from bot_program.share_allocator import propose_share_plan
        _reading(self.acct, 2500, days_ago=10)
        a = _cfg(self.user, name="a", tracks=True, share=50)
        b = _cfg(self.user, name="b", tracks=True, share=50)
        plan = propose_share_plan(self.user)
        self.assertAlmostEqual(plan.drawdown_pct, 0.2)
        self.assertAlmostEqual(plan.governor, 0.4)
        self.assertEqual(float(plan.hwm), 2500.0)
        ia, ib = plan.inputs[str(a.pk)], plan.inputs[str(b.pk)]
        self.assertAlmostEqual(ia["capped"] + ib["capped"], 40.0, places=3)
        self.assertEqual(plan.targets[str(a.pk)], 40.0)     # 50 - 10
        self.assertEqual(plan.targets[str(b.pk)], 40.0)
        self.assertIn("governor 0.40", plan.notes)

    def test_ceilings_and_floors_hold(self):
        from bot_program.share_allocator import propose_share_plan
        a = _cfg(self.user, name="a", tracks=True, share=50,
                 share_ceiling_pct=45)
        b = _cfg(self.user, name="b", tracks=True, share=50,
                 share_floor_pct=55, share_ceiling_pct=100)
        plan = propose_share_plan(self.user)
        ia, ib = plan.inputs[str(a.pk)], plan.inputs[str(b.pk)]
        self.assertEqual((ia["floor"], ia["ceiling"]), (2.0, 45.0))
        self.assertEqual((ib["floor"], ib["ceiling"]), (55.0, 100.0))
        self.assertAlmostEqual(ia["capped"], 45.0, places=3)
        self.assertAlmostEqual(ib["capped"], 55.0, places=3)
        self.assertEqual(plan.targets[str(a.pk)], 47.5)
        self.assertEqual(plan.targets[str(b.pk)], 52.5)

    def test_floors_that_do_not_fit_skip_the_user(self):
        from bot_program.share_allocator import propose_share_plan_with_reason
        _reading(self.acct, 4000, days_ago=3)              # dd 50% → g 0.4
        _cfg(self.user, name="a", tracks=True, share=50, share_floor_pct=30)
        _cfg(self.user, name="b", tracks=True, share=50, share_floor_pct=30)
        plan, reason = propose_share_plan_with_reason(self.user)
        self.assertIsNone(plan)
        self.assertIn("floors sum to 60.0%", reason)

    def test_the_per_day_cap_counts_what_was_applied_today(self):
        from bot_program.share_allocator import propose_share_plan
        a = _cfg(self.user, name="a", tracks=True, share=50)
        b = _cfg(self.user, name="b", tracks=True, share=50,
                 asset_class="forex", symbols=["EURUSD"])
        for _ in range(10):
            _fill(a, 1.0)
        # An applied plan 3h ago already moved a by 8 points (42 → 50).
        _applied(self.user, {a.pk: 50, b.pk: 50}, {a.pk: 42, b.pk: 58},
                 hours_ago=3)
        plan = propose_share_plan(self.user)
        self.assertEqual(plan.targets[str(a.pk)], 52.0)     # 2 points left
        self.assertEqual(plan.targets[str(b.pk)], 48.0)
        _applied(self.user, {a.pk: 50, b.pk: 50}, {a.pk: 42, b.pk: 58},
                 hours_ago=25)                             # yesterday
        # ... and yesterday's does not count: with only the 3h-old one
        # the allowance is still 2, so nothing changes.
        plan2 = propose_share_plan(self.user)
        self.assertEqual(plan2.targets[str(a.pk)], 52.0)

    def test_an_automatic_previous_share_counts_from_the_plans_current(self):
        from bot_program.share_allocator import propose_share_plan
        a = _cfg(self.user, name="a", tracks=True, share=50)
        b = _cfg(self.user, name="b", tracks=True, share=50,
                 asset_class="forex", symbols=["EURUSD"])
        for _ in range(10):
            _fill(a, 1.0)
        _applied(self.user, {a.pk: 50, b.pk: 50}, {a.pk: None, b.pk: None},
                 current={a.pk: 41, b.pk: 59}, hours_ago=2)   # moved 9
        plan = propose_share_plan(self.user)
        self.assertEqual(plan.targets[str(a.pk)], 51.0)

    def test_a_reader_that_raises_costs_a_factor_not_the_plan(self):
        from bot_program.share_allocator import propose_share_plan
        a = _cfg(self.user, name="a", tracks=True, share=50)
        _cfg(self.user, name="b", tracks=True, share=50)
        with patch("bot_program.evidence.config_evidence",
                   side_effect=RuntimeError("ledger down")), \
             patch("signals.opportunity_density.opportunity_density",
                   side_effect=RuntimeError("scanner down")), \
             patch("bot_program.news_risk.news_risk_by_class",
                   side_effect=RuntimeError("analyst down")), \
             patch("brain.context.get_brain_context",
                   side_effect=RuntimeError("brain down")):
            plan = propose_share_plan(self.user)
        self.assertIsNotNone(plan)
        row = plan.inputs[str(a.pk)]
        self.assertEqual(row["evidence"]["score"], 1.0)
        self.assertIn("evidence reader failed: ledger down",
                      row["evidence"]["reason"])
        self.assertEqual(row["opportunity"]["factor"], 1.0)
        self.assertIn("scanner down", row["opportunity"]["reason"])
        self.assertEqual(row["news"]["factor"], 1.0)
        self.assertIn("analyst down", row["news"]["reason"])
        self.assertEqual(row["regime"]["factor"], 1.0)
        self.assertIn("brain context unreadable", plan.notes)
        self.assertEqual(plan.targets[str(a.pk)], 50.0)

    def test_a_refusal_from_the_share_rule_skips_the_user(self):
        from bot_program import capital_truth
        from bot_program.share_allocator import propose_share_plan_with_reason
        from bot_program.share_models import SharePlan
        _cfg(self.user, name="a", tracks=True, share=50)
        _cfg(self.user, name="b", tracks=True, share=50)
        real = capital_truth.allocate_shares

        def refuse_targets(followers, *, shares=None):
            if shares:
                return {"ok": False, "plan": {}, "reason": "boom"}
            return real(followers, shares=shares)

        with patch("bot_program.capital_truth.allocate_shares",
                   side_effect=refuse_targets):
            plan, reason = propose_share_plan_with_reason(self.user)
        self.assertIsNone(plan)
        self.assertIn("boom", reason)
        self.assertEqual(SharePlan.objects.count(), 0)

    def test_a_new_proposal_expires_the_older_ones(self):
        from bot_program.share_allocator import propose_share_plan
        from bot_program.share_models import SharePlan
        _cfg(self.user, name="a", tracks=True, share=50)
        _cfg(self.user, name="b", tracks=True, share=50)
        first = propose_share_plan(self.user)
        second = propose_share_plan(self.user)
        first.refresh_from_db()
        self.assertEqual(first.state, SharePlan.STATE_EXPIRED)
        self.assertIn(f"superseded by #{second.pk}", first.notes)
        self.assertEqual(second.state, SharePlan.STATE_PROPOSED)

    def test_another_users_proposal_is_left_alone(self):
        from bot_program.share_allocator import propose_share_plan
        from bot_program.share_models import SharePlan
        other = User.objects.create_user("sa_o", password="x")
        _acct(other)
        _cfg(other, name="o", tracks=True, share=50)
        theirs = propose_share_plan(other)
        _cfg(self.user, name="a", tracks=True, share=50)
        propose_share_plan(self.user)
        theirs.refresh_from_db()
        self.assertEqual(theirs.state, SharePlan.STATE_PROPOSED)

    def test_the_opportunity_class_follows_the_instruments(self):
        """A 'stock' config holding GLDM holds an ETF: the density it is
        scored on is the etf class's."""
        from core.platform_control import PlatformComponent
        from instruments.models import Instrument
        from bot_program.share_allocator import propose_share_plan
        c, _ = PlatformComponent.objects.get_or_create(
            key="pipeline_opportunity_scanner",
            defaults={"name": "Opportunity Scanner", "category": "pipeline"})
        c.is_enabled = True
        c.save()
        Instrument.objects.create(symbol="GLDM", name="g", asset_class="etf")
        a = _cfg(self.user, name="a", tracks=True, share=50, symbols=["GLDM"])
        _cfg(self.user, name="b", tracks=True, share=50)   # AAPL: unknown row
        plan = propose_share_plan(self.user)
        opp = plan.inputs[str(a.pk)]["opportunity"]
        self.assertIn("etf", opp["classes"])
        self.assertTrue(opp["measured"])
        self.assertAlmostEqual(opp["factor"], 0.8)          # measured, empty


class ApplyTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("sa_apply", password="x")
        self.admin = User.objects.create_superuser("sa_admin", "a@x", "x")
        self.acct = _acct(self.user)
        self.a = _cfg(self.user, name="a", tracks=True, share=50,
                      capital="1000")
        self.b = _cfg(self.user, name="b", tracks=True, capital="1000",
                      asset_class="forex", symbols=["EURUSD"])       # auto
        for _ in range(10):
            _fill(self.a, 1.0)
        from bot_program.share_allocator import propose_share_plan
        self.plan = propose_share_plan(self.user)
        # a: score 1.5 → raw 75/50 → 60/40 → smoothed 55/45
        self.assertEqual(self.plan.targets[str(self.a.pk)], 55.0)
        self.assertEqual(self.plan.targets[str(self.b.pk)], 45.0)

    def test_shadow_mode_refuses_with_one_sentence(self):
        from bot_program.share_allocator import (ShareAllocatorError,
                                                 apply_share_plan)
        _set_live(False)
        with self.assertRaises(ShareAllocatorError) as ctx:
            apply_share_plan(self.plan.pk, self.admin)
        self.assertEqual(str(ctx.exception),
                         "Share allocator is in shadow mode — apply is disabled.")
        self.a.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)
        self.assertEqual(float(self.a.capital), 1000.0)

    def test_live_writes_every_share_and_re_splits_the_capital(self):
        from bot_program.models import AuditLogEntry
        from bot_program.share_allocator import apply_share_plan
        from bot_program.share_models import SharePlan
        _set_live(True)
        plan = apply_share_plan(self.plan.pk, self.admin)
        self.assertEqual(plan.state, SharePlan.STATE_APPLIED)
        self.assertIsNotNone(plan.applied_at)
        self.assertEqual(plan.confirmed_by, self.admin)
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 55.0)
        self.assertEqual(self.b.extras["account_share_pct"], 45.0)
        self.assertTrue(self.b.extras["capital_tracks_broker"])
        self.assertEqual(float(self.a.capital), 1100.0)    # 55% of 2000
        self.assertEqual(float(self.b.capital), 900.0)
        # The snapshot is exact: b was automatic, so None.
        self.assertEqual(plan.previous_shares,
                         {str(self.a.pk): 50, str(self.b.pk): None})
        row = AuditLogEntry.objects.filter(kind="share_plan").last()
        self.assertIsNotNone(row)
        self.assertEqual(row.data["decision"], "applied")
        self.assertEqual(row.data["plan_id"], plan.pk)
        self.assertEqual(row.user, self.admin)

    def test_a_follower_that_stood_down_is_skipped_and_noted(self):
        from bot_program.models import AssetBotConfig
        from bot_program.share_allocator import apply_share_plan
        _set_live(True)
        # A queryset update, not b.save(): the in-memory row's extras are
        # stale and a whole-object save would write them back over the
        # share on disk — the very hazard the merge-write exists for.
        AssetBotConfig.objects.filter(pk=self.b.pk).update(enabled=False)
        plan = apply_share_plan(self.plan.pk, self.admin)
        self.assertEqual(plan.configs_skipped, 1)
        self.assertIn(f"#{self.b.pk} b", plan.notes)
        self.assertIn("no longer a follower", plan.notes)
        self.b.refresh_from_db()
        self.assertNotIn("account_share_pct", self.b.extras)
        self.assertEqual(plan.previous_shares, {str(self.a.pk): 50})
        self.a.refresh_from_db()
        self.assertEqual(float(self.a.capital), 1100.0)

    def test_the_daily_cap(self):
        from bot_program.share_allocator import (MAX_APPLIES_PER_DAY,
                                                 ShareAllocatorError,
                                                 apply_share_plan)
        _set_live(True)
        for _ in range(MAX_APPLIES_PER_DAY):
            _applied(self.user, {self.a.pk: 50}, {self.a.pk: 50}, hours_ago=2)
        with self.assertRaises(ShareAllocatorError) as ctx:
            apply_share_plan(self.plan.pk, self.admin)
        self.assertIn("Daily cap", str(ctx.exception))
        self.a.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)

    def test_a_stale_reading_refuses_the_apply(self):
        from bot_program.capital_truth import TRACKING_FRESH_SECONDS
        from bot_program.share_allocator import (ShareAllocatorError,
                                                 apply_share_plan)
        _set_live(True)
        self.acct.last_equity_at = timezone.now() - timedelta(
            seconds=TRACKING_FRESH_SECONDS + 3600)
        self.acct.save()
        with self.assertRaises(ShareAllocatorError) as ctx:
            apply_share_plan(self.plan.pk, self.admin)
        self.assertIn("h old", str(ctx.exception))

    def test_only_a_proposed_plan_applies(self):
        from bot_program.share_allocator import (ShareAllocatorError,
                                                 apply_share_plan,
                                                 reject_share_plan)
        _set_live(True)
        reject_share_plan(self.plan.pk, self.admin)
        with self.assertRaises(ShareAllocatorError) as ctx:
            apply_share_plan(self.plan.pk, self.admin)
        self.assertIn("rejected, not proposed", str(ctx.exception))
        with self.assertRaises(ShareAllocatorError):
            apply_share_plan(999999, self.admin)

    def test_a_shell_caller_without_an_account_is_not_linked(self):
        from bot_program.share_allocator import apply_share_plan
        _set_live(True)
        plan = apply_share_plan(self.plan.pk, None)
        self.assertIsNone(plan.confirmed_by)


class RollbackAndRejectTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("sa_rb", password="x")
        self.admin = User.objects.create_superuser("sa_rb_admin", "a@x", "x")
        self.acct = _acct(self.user)
        self.a = _cfg(self.user, name="a", tracks=True, share=50,
                      capital="1000")
        self.b = _cfg(self.user, name="b", tracks=True, capital="1000",
                      asset_class="forex", symbols=["EURUSD"])
        for _ in range(10):
            _fill(self.a, 1.0)
        from bot_program.share_allocator import propose_share_plan
        self.plan = propose_share_plan(self.user)

    def test_rollback_restores_exactly_and_pops_the_automatic_key(self):
        from bot_program.models import AuditLogEntry
        from bot_program.share_allocator import (apply_share_plan,
                                                 rollback_share_plan)
        from bot_program.share_models import SharePlan
        _set_live(True)
        apply_share_plan(self.plan.pk, self.admin)
        plan = rollback_share_plan(self.plan.pk, self.admin)
        self.assertEqual(plan.state, SharePlan.STATE_ROLLED_BACK)
        self.assertIsNotNone(plan.rolled_back_at)
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)
        self.assertNotIn("account_share_pct", self.b.extras)
        self.assertTrue(self.b.extras["capital_tracks_broker"])
        self.assertEqual(float(self.a.capital), 1000.0)
        self.assertEqual(float(self.b.capital), 1000.0)
        self.assertEqual(AuditLogEntry.objects.filter(kind="share_plan")
                         .last().data["decision"], "rolled_back")

    def test_rollback_skips_a_follower_that_stood_down(self):
        from bot_program.models import AssetBotConfig
        from bot_program.share_allocator import (apply_share_plan,
                                                 rollback_share_plan)
        _set_live(True)
        apply_share_plan(self.plan.pk, self.admin)
        # A queryset update, not b.save(): the in-memory row's extras are
        # stale and a whole-object save would write them back over the
        # share on disk — the very hazard the merge-write exists for.
        AssetBotConfig.objects.filter(pk=self.b.pk).update(enabled=False)
        plan = rollback_share_plan(self.plan.pk, self.admin)
        self.assertIn(f"#{self.b.pk} b", plan.notes)
        self.b.refresh_from_db()
        self.assertEqual(self.b.extras["account_share_pct"], 45.0)  # untouched
        self.a.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)

    def test_only_an_applied_plan_rolls_back(self):
        from bot_program.share_allocator import (ShareAllocatorError,
                                                 rollback_share_plan)
        with self.assertRaises(ShareAllocatorError) as ctx:
            rollback_share_plan(self.plan.pk, self.admin)
        self.assertIn("proposed, not applied", str(ctx.exception))

    def test_reject_writes_nothing_and_needs_no_mode(self):
        from bot_program.models import AuditLogEntry
        from bot_program.share_allocator import (ShareAllocatorError,
                                                 reject_share_plan)
        from bot_program.share_models import SharePlan
        _set_live(False)
        plan = reject_share_plan(self.plan.pk, self.admin)
        self.assertEqual(plan.state, SharePlan.STATE_REJECTED)
        self.assertIsNotNone(plan.rejected_at)
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual(self.a.extras["account_share_pct"], 50)
        self.assertNotIn("account_share_pct", self.b.extras)
        self.assertEqual(float(self.a.capital), 1000.0)
        self.assertEqual(AuditLogEntry.objects.filter(kind="share_plan")
                         .last().data["decision"], "rejected")
        with self.assertRaises(ShareAllocatorError):
            reject_share_plan(self.plan.pk, self.admin)


class ExpiryAndGradeTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("sa_gr", password="x")
        self.acct = _acct(self.user)
        self.a = _cfg(self.user, name="a", tracks=True, share=50)
        self.b = _cfg(self.user, name="b", tracks=True, share=50)

    def _plan(self, *, hours_ago, targets, current, state="proposed"):
        from bot_program.share_models import SharePlan
        p = SharePlan.objects.create(
            user=self.user, state=state,
            targets={str(k): v for k, v in targets.items()},
            current_shares={str(k): v for k, v in current.items()})
        SharePlan.objects.filter(pk=p.pk).update(
            proposed_at=timezone.now() - timedelta(hours=hours_ago))
        p.refresh_from_db()
        return p

    def test_stale_proposals_expire(self):
        from bot_program.share_allocator import (PROPOSAL_TTL_HOURS,
                                                 expire_stale_plans)
        from bot_program.share_models import SharePlan
        old = self._plan(hours_ago=PROPOSAL_TTL_HOURS + 1,
                         targets={self.a.pk: 50}, current={self.a.pk: 50})
        fresh = self._plan(hours_ago=1, targets={self.a.pk: 50},
                           current={self.a.pk: 50})
        self.assertEqual(expire_stale_plans(), 1)
        old.refresh_from_db(); fresh.refresh_from_db()
        self.assertEqual(old.state, SharePlan.STATE_EXPIRED)
        self.assertIn("expired after", old.notes)
        self.assertEqual(fresh.state, SharePlan.STATE_PROPOSED)
        self.assertEqual(expire_stale_plans(), 0)

    def test_the_grade_leans_toward_what_paid(self):
        """a: +10 points and +2R in the window; b: -10 points and -1R.
        score = 0.10 × 2 + (-0.10) × (-1) = 0.3."""
        from bot_program.share_allocator import grade_plans
        plan = self._plan(hours_ago=30, targets={self.a.pk: 60, self.b.pk: 40},
                          current={self.a.pk: 50, self.b.pk: 50},
                          state="applied")
        _fill(self.a, 1.5, hours_ago=20)
        _fill(self.a, 0.5, hours_ago=10)
        _fill(self.b, -1.0, hours_ago=12)
        _fill(self.a, 9.0, hours_ago=31)               # before the window
        _fill(self.a, 9.0, hours_ago=5)                # after the window
        _fill(self.a, 9.0, hours_ago=15, paper=True)   # paper never grades
        _fill(self.b, None, hours_ago=15)              # unpriced: excluded
        self.assertEqual(grade_plans(), 1)
        plan.refresh_from_db()
        self.assertAlmostEqual(plan.grade_score, 0.3)
        self.assertIsNotNone(plan.graded_at)
        d = plan.grade_detail
        self.assertEqual(d["n_graded_configs"], 2)
        self.assertAlmostEqual(d[str(self.a.pk)]["r"], 2.0)
        self.assertAlmostEqual(d[str(self.a.pk)]["delta"], 10.0)
        self.assertAlmostEqual(d[str(self.b.pk)]["r"], -1.0)
        self.assertEqual(grade_plans(), 0)              # graded once

    def test_a_plan_with_no_live_close_is_ungradeable_not_wrong(self):
        from bot_program.share_allocator import grade_plans
        plan = self._plan(hours_ago=25, targets={self.a.pk: 60},
                          current={self.a.pk: 50}, state="expired")
        self.assertEqual(grade_plans(), 1)
        plan.refresh_from_db()
        self.assertIsNone(plan.grade_score)
        self.assertIsNotNone(plan.graded_at)
        self.assertEqual(plan.grade_detail["reason"],
                         "no live closes in the window")

    def test_young_and_rejected_plans_are_not_graded(self):
        from bot_program.share_allocator import grade_plans
        young = self._plan(hours_ago=23, targets={self.a.pk: 60},
                           current={self.a.pk: 50}, state="applied")
        rejected = self._plan(hours_ago=30, targets={self.a.pk: 60},
                              current={self.a.pk: 50}, state="rejected")
        self.assertEqual(grade_plans(), 0)
        young.refresh_from_db(); rejected.refresh_from_db()
        self.assertIsNone(young.graded_at)
        self.assertIsNone(rejected.graded_at)


# ── The beat task and its wiring ────────────────────────────────────────

def _enable(*keys):
    from core.platform_control import PlatformComponent, seed_components
    seed_components()
    PlatformComponent.objects.filter(
        key__in=("platform_master",) + keys).update(is_enabled=True)


class WiringTests(SimpleTestCase):
    """The registry, the beat, the topology and the mode flag must all
    name the same thing, or the task skips on every beat (no component
    row), the health page judges it at 48h (no cadence), or the map draws
    the live switch as a broken box (no MODE_FLAGS entry)."""

    def test_both_components_are_registered_honestly(self):
        from core.platform_control import DEFAULT_COMPONENTS
        by_key = {c["key"]: c for c in DEFAULT_COMPONENTS}
        prop = by_key["pipeline_share_allocator"]
        self.assertEqual(prop["category"], "pipeline")
        self.assertIn("SHADOW", prop["description"].upper())
        self.assertIn("PIN", prop["description"])
        live = by_key["share_allocator_mode_live"]
        self.assertEqual(live["category"], "system")
        self.assertIn("Off (default)", live["description"])
        self.assertIn("shadow", live["description"])

    def test_the_beat_entry(self):
        from celery.schedules import crontab

        from config.celery import app
        entry = app.conf.beat_schedule["propose-share-plans"]
        self.assertEqual(entry["task"], "bot_program.tasks.propose_share_plans")
        self.assertIsInstance(entry["schedule"], crontab)
        self.assertEqual(entry["schedule"]._orig_minute, 5)
        self.assertEqual(entry["schedule"]._orig_hour, "*/4")

    def test_the_wiring_names_a_scheduled_task_and_its_cadence(self):
        from config.celery import app
        from dashboard.views_topology import WIRING, _expected_cadence
        w = WIRING["pipeline_share_allocator"]
        scheduled = {e.get("task") for e in app.conf.beat_schedule.values()}
        self.assertIn(w["task"], scheduled)
        self.assertEqual(w["cadence"], 14400)
        self.assertEqual(_expected_cadence("pipeline_share_allocator"), 14400.0)
        self.assertEqual(w["layer"], "learn")
        self.assertIn("SharePlan", w["writes"])
        self.assertIn("AssetBotConfig.extras.account_share_pct", w["writes"])
        self.assertIn("broker_account_sync", w["feeds"])
        self.assertIn("execute_bots", w["feeds"])
        self.assertEqual(w["pages"], ["/shares/"])

    def test_the_mode_flag_folds_into_its_proposer(self):
        from dashboard.views_topology import MODE_FLAGS, WIRING
        self.assertEqual(MODE_FLAGS["share_allocator_mode_live"],
                         "pipeline_share_allocator")
        self.assertIn(MODE_FLAGS["share_allocator_mode_live"], WIRING)

    def test_the_sync_declares_the_history_table_it_writes(self):
        from dashboard.views_topology import WIRING
        self.assertIn("BrokerEquityReading",
                      WIRING["broker_account_sync"]["writes"])


class TaskTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("sa_task", password="x")
        self.acct = _acct(self.user)
        self.a = _cfg(self.user, name="a", tracks=True, share=50,
                      capital="1000")
        self.b = _cfg(self.user, name="b", tracks=True, capital="1000",
                      asset_class="forex", symbols=["EURUSD"])

    def test_the_gate_skips_when_the_component_is_off(self):
        from bot_program.share_models import SharePlan
        from bot_program.tasks import propose_share_plans
        _enable()                       # master on, the allocator off
        out = propose_share_plans()
        self.assertEqual(out, {"status": "skipped",
                               "reason": "pipeline_share_allocator_disabled"})
        self.assertFalse(SharePlan.objects.exists())

    def test_the_return_dict_has_the_counts_and_no_gate_trap_keys(self):
        """judge_result reads a truthy top-level `skipped` as "not
        configured" and a zero `stored` as "produced nothing"; a user
        with a stale reading is neither, so those keys must not appear."""
        from bot_program.share_models import SharePlan
        from bot_program.tasks import propose_share_plans
        from core.platform_control import PlatformComponent
        from core.task_gate import judge_result
        _enable("pipeline_share_allocator")
        out = propose_share_plans()
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["users"], 1)
        self.assertEqual(out["proposals"], 1)
        self.assertEqual(out["not_proposed"], 0)
        self.assertEqual(out["graded"], 0)
        self.assertEqual(out["expired"], 0)
        for trap in ("skipped", "parsed", "attempted", "stored", "written",
                     "saved", "fetched"):
            self.assertNotIn(trap, out)
        self.assertEqual(judge_result(out), ("success", "ok"))
        self.assertEqual(SharePlan.objects.filter(
            user=self.user, state=SharePlan.STATE_PROPOSED).count(), 1)
        comp = PlatformComponent.objects.get(key="pipeline_share_allocator")
        self.assertEqual(comp.last_status, "success")

    def test_a_stale_reading_is_counted_not_invented(self):
        from bot_program.share_models import SharePlan
        from bot_program.tasks import propose_share_plans
        _enable("pipeline_share_allocator")
        self.acct.last_equity_at = timezone.now() - timedelta(hours=3)
        self.acct.save(update_fields=["last_equity_at"])
        out = propose_share_plans()
        self.assertEqual(out["status"], "ok")
        self.assertEqual((out["users"], out["proposals"], out["not_proposed"]),
                         (1, 0, 1))
        self.assertFalse(SharePlan.objects.exists())

    def test_a_user_without_an_interfaced_account_is_not_counted(self):
        from bot_program.tasks import propose_share_plans
        from bot_program.models import IBKRAccount
        _enable("pipeline_share_allocator")
        other = User.objects.create_user("sa_task_other", password="x")
        IBKRAccount.objects.create(user=other, port=4003)      # no account id
        out = propose_share_plans()
        self.assertEqual(out["users"], 1)

    def test_the_task_expires_and_grades_before_proposing(self):
        from bot_program.share_models import SharePlan
        from bot_program.tasks import propose_share_plans
        _enable("pipeline_share_allocator")
        stale = SharePlan.objects.create(user=self.user,
                                         state=SharePlan.STATE_PROPOSED,
                                         targets={str(self.a.pk): 50})
        SharePlan.objects.filter(pk=stale.pk).update(
            proposed_at=timezone.now() - timedelta(hours=30))
        _fill(self.a, 1.0, hours_ago=20)
        out = propose_share_plans()
        self.assertEqual(out["expired"], 1)
        self.assertEqual(out["graded"], 1)
        self.assertEqual(out["proposals"], 1)
        stale.refresh_from_db()
        self.assertEqual(stale.state, SharePlan.STATE_EXPIRED)
        self.assertIsNotNone(stale.graded_at)

    def test_one_users_failure_does_not_pass_as_ok(self):
        from bot_program.tasks import propose_share_plans
        from core.task_gate import judge_result
        _enable("pipeline_share_allocator")
        with patch("bot_program.share_allocator.propose_share_plan_with_reason",
                   side_effect=RuntimeError("boom")):
            out = propose_share_plans()
        self.assertEqual(out["status"], "error")
        self.assertEqual(out["errors"], 1)
        self.assertIn("boom", out["error"])
        self.assertEqual(judge_result(out)[0], "error")
