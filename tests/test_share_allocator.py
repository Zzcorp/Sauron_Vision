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

    def test_the_manual_lane_has_no_default_ceiling(self):
        """Plan #1 on the live account (2026-09-11): 80% -> 70% on the
        operator's own pool with every lane unmeasured, because the bots'
        60% ceiling was binding on it. The manual lane (the reserved name,
        no symbols) defaults to 100%; an explicit ceiling still holds; a
        config merely NAMED manual with symbols is a bot and keeps 60%."""
        from types import SimpleNamespace

        from bot_program.share_allocator import (DEFAULT_CEILING_PCT,
                                                 DEFAULT_FLOOR_PCT, bounds_for)
        manual = SimpleNamespace(name="manual", symbols=[], extras={})
        self.assertEqual(bounds_for(manual)[:2], (DEFAULT_FLOOR_PCT, 100.0))
        pinned = SimpleNamespace(name="manual", symbols=[],
                                 extras={"share_ceiling_pct": 75})
        self.assertEqual(bounds_for(pinned)[:2], (DEFAULT_FLOOR_PCT, 75.0))
        bot = SimpleNamespace(name="manual", symbols=["AAPL"], extras={})
        self.assertEqual(bounds_for(bot)[:2],
                         (DEFAULT_FLOOR_PCT, DEFAULT_CEILING_PCT))


class ProposeTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("sa_u", password="x")
        self.acct = _acct(self.user)

    def test_no_information_moves_the_operators_pool_only_on_information(self):
        """The same two followers as plan #1 — manual 80% automatic, ETF
        20% — with every reader neutral: nothing binds, both are held.
        With the ETF class alone reading opportunity 1.2, the move is the
        1.6 points that factor earns, not the ten a ceiling forced."""
        from unittest.mock import patch

        from bot_program.share_allocator import propose_share_plan
        manual = _cfg(self.user, name="manual", symbols=[], capital="1600",
                      tracks=True)
        etf = _cfg(self.user, name="commodity_etf", capital="400",
                   tracks=True, share=20)
        neutral = {"lane": "none", "n": 0, "measured": False, "score": 1.0,
                   "reason": "unmeasured"}
        # The readers are imported lazily inside the proposer: patch them
        # at their homes, not on the allocator module.
        with patch("bot_program.evidence.config_evidence",
                   return_value=neutral),                 patch("brain.context.get_brain_context", return_value=None),                 patch("signals.opportunity_density.opportunity_density",
                      return_value={}),                 patch("bot_program.news_risk.news_risk_by_class",
                      return_value={}):
            plan = propose_share_plan(self.user)
        self.assertIsNotNone(plan)
        t = {int(k): v for k, v in plan.targets.items()}
        self.assertAlmostEqual(t[etf.pk], 20.0, places=2)
        self.assertAlmostEqual(t[manual.pk], 80.0, places=2)
        self.assertTrue(plan.inputs[str(manual.pk)]["held"])

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
        to 40. Until 2026-09-12 the move down was then capped at 10
        points per day (50 → 40 → 30 → 20 over three plans); a drawdown
        past the knee is now a SHOCK and the whole move lands in one plan
        — de-risk fast (ResponsiveTests pins the mode itself)."""
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
        self.assertEqual(plan.mode, "shock")
        self.assertEqual(plan.targets[str(a.pk)], 20.0)     # 50 - 30, uncapped
        self.assertEqual(plan.targets[str(b.pk)], 20.0)
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

    def test_the_auto_derisk_switch_is_registered_and_folds_into_its_proposer(self):
        """The third switch: off by default, a system flag on the proposer
        (a node of its own would be a box with no edges), its description
        inside the 300-char column Postgres enforces, and honest about the
        one thing it never does."""
        from core.platform_control import DEFAULT_COMPONENTS
        from dashboard.views_topology import MODE_FLAGS, WIRING
        by_key = {c["key"]: c for c in DEFAULT_COMPONENTS}
        auto = by_key["share_allocator_auto_derisk"]
        self.assertEqual(auto["category"], "system")
        self.assertLessEqual(len(auto["description"]), 300)
        self.assertIn("Off (default)", auto["description"])
        self.assertIn("LIVE", auto["description"])
        self.assertIn("Re-risking is never automatic", auto["description"])
        self.assertEqual(MODE_FLAGS["share_allocator_auto_derisk"],
                         "pipeline_share_allocator")
        self.assertIn("sync", WIRING["pipeline_share_allocator"]["note"])
        self.assertIn("share_allocator_auto_derisk",
                      WIRING["pipeline_share_allocator"]["note"])

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


# ── De-risk fast, re-risk slow ───────────────────────────────────────────

def _set_auto_derisk(enabled: bool):
    from core.platform_control import PlatformComponent
    c, _ = PlatformComponent.objects.get_or_create(
        key="share_allocator_auto_derisk",
        defaults={"name": "Share Allocator Auto De-risk", "category": "system"})
    c.is_enabled = enabled
    c.save()


def _run_sync(reading):
    """The sync task with the socket layer stubbed, as test_equity_history
    runs it: __wrapped__ twice to step past @shared_task and @guarded_task."""
    from unittest.mock import MagicMock

    from bot_program.tasks import sync_broker_account
    trader = MagicMock()
    trader.net_liquidation.return_value = reading
    trader.broker_portfolio.return_value = []
    with patch("bot_program.engine.ibkr_client.is_ibkr_available",
               return_value=True), \
         patch("bot_program.engine.ibkr_client.IBKRTrader",
               return_value=trader):
        return sync_broker_account.__wrapped__.__wrapped__()


class ResponsiveTests(TestCase):
    """The operator's ask (2026-09-12): "the allocation percentages must
    be purely responsive — in a strong rally or a big crash Sauron must
    be able to respond." The symmetric 10-point cap took three plans to
    reach a 20% crash's governor. These pin the three modes: SHOCK is
    de-risk only (down uncapped and unsmoothed, up frozen, released
    mass is cash, floors hold, held exactly below the capped value);
    EXPANSION widens the upward allowance to 20 at the high-water mark
    with measured positive evidence and leaves the downward one at 10;
    NORMAL is the rule as it was. The sync proposes at once on a shock,
    once an hour, never without the component; and the opt-in auto
    de-risk applies only a pure de-risk SHOCK plan, only with both
    switches on, and leaves a refused plan PROPOSED."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = User.objects.create_user("sa_resp", password="x")
        self.acct = _acct(self.user)

    # ── market_state ────────────────────────────────────────────────

    def test_shock_via_the_24h_drop(self):
        """2,100 twelve hours ago, 2,000 now: −4.8% in 24h is a shock
        even though the drawdown (4.8%) is under the governor's knee.
        The same reading 30h ago is outside the window: normal."""
        from bot_program.share_allocator import market_state
        _reading(self.acct, 2100, days_ago=0.5)
        st = market_state(self.user, None)
        self.assertEqual(st["mode"], "shock")
        self.assertAlmostEqual(st["drop_24h_pct"], 100.0 / 2100.0)
        self.assertLess(st["drawdown_pct"], 0.05)
        self.assertEqual(st["reasons"], ["equity −4.8% in 24h"])
        self.assertFalse(st["at_hwm"])
        from bot_program.models import BrokerEquityReading
        BrokerEquityReading.objects.filter(account=self.acct).update(
            at=timezone.now() - timedelta(hours=30))
        st = market_state(self.user, None)
        self.assertEqual(st["mode"], "normal")
        self.assertIsNone(st["drop_24h_pct"])
        self.assertIn("4.8% under the high-water mark", st["reasons"][0])

    def test_shock_via_the_drawdown_past_the_knee(self):
        from bot_program.share_allocator import market_state
        _reading(self.acct, 2200, days_ago=10)         # dd 9.1%, no 24h row
        st = market_state(self.user, None)
        self.assertEqual(st["mode"], "shock")
        self.assertEqual(st["reasons"], ["drawdown 9.1% past the 5% knee"])
        self.assertIsNone(st["drop_24h_pct"])
        # Exactly at the knee is not past it.
        from bot_program.models import BrokerEquityReading
        BrokerEquityReading.objects.filter(account=self.acct).update(
            value=Decimal("2105.26"))                   # dd 5.000%
        self.assertEqual(market_state(self.user, None)["mode"], "normal")

    def test_shock_via_the_regime_and_never_via_unknown(self):
        from bot_program.share_allocator import market_state
        risk_off = {"regime_label": "risk_off", "regime_confidence": 0.71}
        st = market_state(self.user, risk_off)
        self.assertEqual(st["mode"], "shock")
        self.assertEqual(st["reasons"], ["regime risk_off 0.71"])
        self.assertEqual(st["regime"], "risk_off")
        blow = {"regime_label": "blow_off", "regime_confidence": 0.65}
        self.assertEqual(market_state(self.user, blow)["mode"], "shock")
        timid = {"regime_label": "risk_off", "regime_confidence": 0.64}
        self.assertEqual(market_state(self.user, timid)["mode"], "normal")
        unknown = {"regime_label": "unknown", "regime_confidence": 0.99}
        self.assertEqual(market_state(self.user, unknown)["mode"], "normal")
        risk_on = {"regime_label": "risk_on", "regime_confidence": 0.99}
        self.assertEqual(market_state(self.user, risk_on)["mode"], "normal")
        self.assertIsNone(market_state(self.user, None)["regime"])

    def test_the_hold_after_a_shock_plan(self):
        """A shock plan proposed 23h ago keeps the mode at shock with no
        other trigger; one proposed 25h ago does not."""
        from bot_program.share_allocator import market_state
        from bot_program.share_models import SharePlan
        p = SharePlan.objects.create(user=self.user, mode="shock",
                                     state=SharePlan.STATE_EXPIRED)
        SharePlan.objects.filter(pk=p.pk).update(
            proposed_at=timezone.now() - timedelta(hours=23))
        st = market_state(self.user, None)
        self.assertEqual(st["mode"], "shock")
        self.assertEqual(len(st["reasons"]), 1)
        self.assertIn("shock hold until", st["reasons"][0])
        self.assertIn(f"plan #{p.pk}", st["reasons"][0])
        SharePlan.objects.filter(pk=p.pk).update(
            proposed_at=timezone.now() - timedelta(hours=25))
        self.assertEqual(market_state(self.user, None)["mode"], "normal")
        # Another user's shock plan is not this user's hold.
        other = User.objects.create_user("sa_resp_o", password="x")
        SharePlan.objects.create(user=other, mode="shock")
        self.assertEqual(market_state(self.user, None)["mode"], "normal")

    def test_a_plan_proposed_on_the_hold_alone_does_not_restart_the_hold(self):
        """Plan A: a fresh shock 20 h ago (hold until +4 h). Plan B: proposed
        2 h ago on the hold alone. The hold is A's — A's plan number, A's
        clock — and once A is 25 h old the mode is normal although B is
        2 h old. Before 2026-09-12 B re-armed the hold, the 4-hourly beat
        wrote such a plan every 4 h, and the account never re-risked
        again. A plan that carries the hold AND a fresh detection is an
        anchor of its own."""
        from bot_program.share_allocator import market_state
        from bot_program.share_models import SharePlan
        a = SharePlan.objects.create(user=self.user, mode="shock",
                                     state=SharePlan.STATE_EXPIRED,
                                     mode_reasons=["equity −4.8% in 24h"])
        SharePlan.objects.filter(pk=a.pk).update(
            proposed_at=timezone.now() - timedelta(hours=20))
        b = SharePlan.objects.create(
            user=self.user, mode="shock",
            mode_reasons=[f"shock hold until 09-12 10:00 (plan #{a.pk})"])
        SharePlan.objects.filter(pk=b.pk).update(
            proposed_at=timezone.now() - timedelta(hours=2))
        st = market_state(self.user, None)
        self.assertEqual(st["mode"], "shock")
        self.assertEqual(len(st["reasons"]), 1)
        self.assertIn(f"plan #{a.pk}", st["reasons"][0])
        self.assertNotIn(f"plan #{b.pk}", st["reasons"][0])
        SharePlan.objects.filter(pk=a.pk).update(
            proposed_at=timezone.now() - timedelta(hours=25))
        st = market_state(self.user, None)
        self.assertEqual(st["mode"], "normal")
        self.assertNotIn("shock hold", " ".join(st["reasons"]))
        c = SharePlan.objects.create(
            user=self.user, mode="shock",
            mode_reasons=[f"shock hold until 09-12 10:00 (plan #{a.pk})",
                          "drawdown 9.1% past the 5% knee"])
        SharePlan.objects.filter(pk=c.pk).update(
            proposed_at=timezone.now() - timedelta(hours=2))
        st = market_state(self.user, None)
        self.assertEqual(st["mode"], "shock")
        self.assertIn(f"plan #{c.pk}", st["reasons"][0])

    def test_the_beat_inside_the_hold_lets_the_hold_lapse(self):
        """End to end. Plan #1 is a fresh shock (−4.8% in 24 h). Twenty
        hours on, the drop is out of its window and the drawdown (4.8%)
        is under the knee, so plan #2 is a shock on the hold alone — and
        its reasons say only that, anchored on #1. Once #1 is 25 h old the
        hold has lapsed although #2 is seconds old: the next plan is
        NORMAL, with the drawdown as its reason."""
        from bot_program.models import BrokerEquityReading
        from bot_program.share_allocator import (market_state,
                                                 propose_share_plan)
        from bot_program.share_models import SharePlan
        _reading(self.acct, 2100, days_ago=0.5)
        _cfg(self.user, name="a", tracks=True, share=50)
        _cfg(self.user, name="b", tracks=True, share=50, asset_class="forex",
             symbols=["EURUSD"])
        p1 = propose_share_plan(self.user)
        self.assertEqual(p1.mode_reasons, ["equity −4.8% in 24h"])
        BrokerEquityReading.objects.filter(account=self.acct).update(
            at=timezone.now() - timedelta(hours=30))
        SharePlan.objects.filter(pk=p1.pk).update(
            proposed_at=timezone.now() - timedelta(hours=20))
        p2 = propose_share_plan(self.user)
        self.assertEqual(p2.mode, "shock")
        self.assertEqual(len(p2.mode_reasons), 1)
        self.assertTrue(p2.mode_reasons[0].startswith("shock hold until"),
                        p2.mode_reasons)
        self.assertIn(f"plan #{p1.pk}", p2.mode_reasons[0])
        SharePlan.objects.filter(pk=p1.pk).update(
            proposed_at=timezone.now() - timedelta(hours=25))
        self.assertEqual(market_state(self.user, None)["mode"], "normal")
        p3 = propose_share_plan(self.user)
        self.assertEqual(p3.mode, "normal")
        self.assertEqual(p3.mode_reasons, ["4.8% under the high-water mark"])

    def test_expansion_only_at_the_hwm_with_measured_positive_evidence(self):
        from bot_program.share_allocator import MIN_EVIDENCE_N, market_state
        proven = {"a": {"measured": True, "avg_r": 0.4, "n": MIN_EVIDENCE_N,
                        "lane": "live", "score": 1.3}}
        st = market_state(self.user, None, evidence=proven)  # no history: at hwm
        self.assertEqual(st["mode"], "expansion")
        self.assertTrue(st["at_hwm"])
        self.assertEqual(st["reasons"][0], "at the high-water mark")
        self.assertIn("a: avg_r +0.40 over 10 fills", st["reasons"][1])
        thin = {"a": {"measured": True, "avg_r": 0.4, "n": MIN_EVIDENCE_N - 1}}
        self.assertEqual(market_state(self.user, None, evidence=thin)["mode"],
                         "normal")
        losing = {"a": {"measured": True, "avg_r": -0.1, "n": 30}}
        self.assertEqual(market_state(self.user, None, evidence=losing)["mode"],
                         "normal")
        unmeasured = {"a": {"measured": False, "avg_r": None, "n": 0}}
        st = market_state(self.user, None, evidence=unmeasured)
        self.assertEqual(st["mode"], "normal")
        self.assertIn("no measured positive lane", st["reasons"][0])
        # 0.5% under the high-water mark is not AT it.
        _reading(self.acct, 2010, days_ago=3)
        st = market_state(self.user, None, evidence=proven)
        self.assertEqual(st["mode"], "normal")
        self.assertFalse(st["at_hwm"])
        self.assertIn("0.5% under the high-water mark", st["reasons"][0])

    def test_a_reader_failure_is_normal_with_the_reason(self):
        from bot_program.share_allocator import market_state
        with patch("bot_program.capital_truth.equity_drawdown",
                   side_effect=RuntimeError("history down")):
            st = market_state(self.user, {"regime_label": "risk_off",
                                          "regime_confidence": 0.9})
        self.assertEqual(st["mode"], "normal")
        self.assertIn("market state unreadable: history down", st["reasons"][0])
        # No reading at all: normal, and it says so.
        self.acct.last_equity = None
        self.acct.save(update_fields=["last_equity"])
        st = market_state(self.user, None)
        self.assertEqual((st["mode"], st["reasons"]), ("normal", ["no reading"]))

    # ── the SHOCK plan ──────────────────────────────────────────────

    def test_a_shock_plan_drops_the_whole_way_and_floors_hold(self):
        """20% under the high → governor 0.4 → 40 deployable. b's floor is
        25, so the water-fill gives b 25 and a 15: a drops 35 points in
        ONE plan (the cap would have allowed 10), b drops to its floor and
        not under it, the sum is the governor's 40, and the notes and the
        why say SHOCK."""
        from bot_program.share_allocator import propose_share_plan
        _reading(self.acct, 2500, days_ago=10)
        a = _cfg(self.user, name="a", tracks=True, share=50)
        b = _cfg(self.user, name="b", tracks=True, share=50,
                 share_floor_pct=25)
        plan = propose_share_plan(self.user)
        self.assertEqual(plan.mode, "shock")
        self.assertEqual(plan.mode_reasons, ["drawdown 20.0% past the 5% knee"])
        self.assertEqual(plan.targets[str(a.pk)], 15.0)
        self.assertEqual(plan.targets[str(b.pk)], 25.0)
        self.assertAlmostEqual(sum(plan.targets.values()), 40.0)
        ia, ib = plan.inputs[str(a.pk)], plan.inputs[str(b.pk)]
        self.assertEqual((ia["allowance_up"], ia["allowance_down"]), (0.0, 100.0))
        self.assertEqual(ia["mode"], "shock")
        self.assertFalse(ia["held"]); self.assertFalse(ib["held"])
        self.assertIn("SHOCK: de-risk only", ia["why"])
        self.assertIn("SHOCK: de-risk only — drawdown 20.0% past the 5% knee",
                      plan.notes)
        self.assertNotIn("EXPANSION", plan.notes)

    def test_a_shock_plan_holds_a_pool_below_its_capped_value_and_leaves_cash(self):
        """A 24h drop with no drawdown past the knee: governor 1.0, so the
        water-fill says 60/40 (a has ten winning fills). a sits BELOW its
        capped 60 and is held at 50 exactly — up is frozen; b drops the
        whole 10 at once (normal would have smoothed it to 45). The ten
        points b released go nowhere: the sum is 90 < 100 × governor."""
        from bot_program.share_allocator import propose_share_plan
        _reading(self.acct, 2100, days_ago=0.5)
        a = _cfg(self.user, name="a", tracks=True, share=50)
        b = _cfg(self.user, name="b", tracks=True, share=50,
                 asset_class="forex", symbols=["EURUSD"])
        for _ in range(10):
            _fill(a, 1.0)
        plan = propose_share_plan(self.user)
        self.assertEqual(plan.mode, "shock")
        self.assertEqual(plan.mode_reasons, ["equity −4.8% in 24h"])
        self.assertAlmostEqual(plan.governor, 1.0)
        ia, ib = plan.inputs[str(a.pk)], plan.inputs[str(b.pk)]
        self.assertAlmostEqual(ia["capped"], 60.0, places=3)
        self.assertEqual(plan.targets[str(a.pk)], 50.0)
        self.assertTrue(ia["held"])
        self.assertEqual(plan.targets[str(b.pk)], 40.0)
        self.assertFalse(ib["held"])
        self.assertAlmostEqual(sum(plan.targets.values()), 90.0)
        self.assertLess(sum(plan.targets.values()), 100.0 * plan.governor)
        self.assertIn("SHOCK", plan.notes)

    def test_a_shock_plan_holds_a_pool_under_its_floor_exactly(self):
        """10% under the high → governor 0.8, 80 deployable. b's floor is
        40 but its share is 33.3333 (an automatic third, four decimals);
        the water-fill gives b its floor and a the other 40. a drops
        66.67 → 40 uncapped. b sits BELOW its capped value, so it is held
        — exactly, 33.3333, not the 33.33 that rounding made of it: that
        phantom 0.0033 was a move the sync re-sized on and is_pure_derisk
        counted as a de-risk (2026-09-12). Under its floor by 6.67 points
        it is not lifted (the lift closes gaps under the hysteresis)."""
        from bot_program.share_allocator import (is_pure_derisk,
                                                 propose_share_plan)
        _reading(self.acct, 2222.22, days_ago=10)
        a = _cfg(self.user, name="a", tracks=True, share=66.6667)
        b = _cfg(self.user, name="b", tracks=True, share=33.3333,
                 share_floor_pct=40, asset_class="forex", symbols=["EURUSD"])
        plan = propose_share_plan(self.user)
        self.assertEqual(plan.mode, "shock")
        self.assertAlmostEqual(plan.governor, 0.8, places=5)
        ia, ib = plan.inputs[str(a.pk)], plan.inputs[str(b.pk)]
        self.assertAlmostEqual(ib["capped"], 40.0, places=3)
        self.assertEqual(plan.targets[str(b.pk)], 33.3333)
        self.assertTrue(ib["held"])
        self.assertNotIn("b: below its floor", plan.notes)
        self.assertEqual(plan.targets[str(a.pk)], 40.0)
        self.assertFalse(ia["held"])
        self.assertTrue(is_pure_derisk(plan))

    def test_a_shock_plan_lifts_a_new_follower_to_its_floor_only(self):
        """A follower with no share at all enters at its floor even in a
        shock (0 reads as "automatic" to the sync); it never gets more."""
        from bot_program.share_allocator import propose_share_plan
        _reading(self.acct, 2500, days_ago=10)
        a = _cfg(self.user, name="a", tracks=True, share=50)
        b = _cfg(self.user, name="b", tracks=True, share=50)
        c = _cfg(self.user, name="c", tracks=True)
        plan = propose_share_plan(self.user)
        self.assertEqual(plan.mode, "shock")
        self.assertIsNone(plan.current_shares[str(c.pk)])
        self.assertEqual(plan.targets[str(c.pk)], 2.0)
        self.assertIn("c: below its floor — lifted to 2%", plan.notes)
        self.assertLess(plan.targets[str(a.pk)], 50.0)
        self.assertLess(plan.targets[str(b.pk)], 50.0)
        self.assertLessEqual(sum(plan.targets.values()), 40.0 + 1e-6)

    # ── the EXPANSION plan ──────────────────────────────────────────

    def _expansion_fleet(self, score_a):
        """a at 30, b and c at 35 each, at the high-water mark; a's
        evidence is patched to `score_a` (measured, positive, ten fills)
        so the water-fill hands it capped = 100 × 30s / (30s + 70)."""
        a = _cfg(self.user, name="a", tracks=True, share=30,
                 share_ceiling_pct=100)
        b = _cfg(self.user, name="b", tracks=True, share=35,
                 asset_class="forex", symbols=["EURUSD"])
        c = _cfg(self.user, name="c", tracks=True, share=35,
                 asset_class="crypto", symbols=["BTCUSDT"])
        neutral = {"lane": "none", "n": 0, "win_rate": None, "avg_r": None,
                   "measured": False, "score": 1.0, "reason": "unmeasured"}
        proven = {"lane": "live", "n": 10, "win_rate": 0.8, "avg_r": 1.0,
                  "measured": True, "score": score_a, "reason": "live"}

        def evidence(cfg, days=90):
            return dict(proven if cfg.name == "a" else neutral)
        return a, b, c, evidence

    def test_expansion_lets_15_points_pass_and_down_stays_10(self):
        """score 3.5 → a capped 60, smoothed 45: +15 passes under the
        20-point expansion allowance (normal would stop at 40). b and c
        each want −7.5, inside the downward 10."""
        from bot_program.share_allocator import propose_share_plan
        a, b, c, evidence = self._expansion_fleet(3.5)
        with patch("bot_program.evidence.config_evidence", side_effect=evidence):
            plan = propose_share_plan(self.user)
        self.assertEqual(plan.mode, "expansion")
        self.assertEqual(plan.mode_reasons[0], "at the high-water mark")
        self.assertIn("a: avg_r +1.00 over 10 fills", plan.mode_reasons[1])
        ia = plan.inputs[str(a.pk)]
        self.assertAlmostEqual(ia["capped"], 60.0, places=3)
        self.assertEqual(plan.targets[str(a.pk)], 45.0)
        self.assertEqual(plan.targets[str(b.pk)], 27.5)
        self.assertEqual(plan.targets[str(c.pk)], 27.5)
        self.assertEqual((ia["allowance_up"], ia["allowance_down"]), (20.0, 10.0))
        self.assertIn("EXPANSION: up to 20 pt up / 10 pt down today", ia["why"])
        self.assertIn("EXPANSION: up to 20 pt/day up — at the high-water mark",
                      plan.notes)

    def test_expansion_caps_25_at_20_and_the_downward_10_still_binds(self):
        """score 9.333… → a capped 80, smoothed 55: +25 is capped at 20
        (30 → 50). b and c each want −12.5 and stop at −10 (35 → 25)."""
        from bot_program.share_allocator import propose_share_plan
        a, b, c, evidence = self._expansion_fleet(28.0 / 3.0)
        with patch("bot_program.evidence.config_evidence", side_effect=evidence):
            plan = propose_share_plan(self.user)
        self.assertEqual(plan.mode, "expansion")
        ia = plan.inputs[str(a.pk)]
        self.assertAlmostEqual(ia["capped"], 80.0, places=3)
        self.assertEqual(plan.targets[str(a.pk)], 50.0)
        self.assertEqual(plan.targets[str(b.pk)], 25.0)
        self.assertEqual(plan.targets[str(c.pk)], 25.0)
        # ... and what applied plans already moved today comes off the
        # upward allowance too: 8 points used leaves 12.
        _applied(self.user, {a.pk: 30, b.pk: 35, c.pk: 35},
                 {a.pk: 22, b.pk: 39, c.pk: 39}, hours_ago=3)
        with patch("bot_program.evidence.config_evidence", side_effect=evidence):
            plan = propose_share_plan(self.user)
        self.assertEqual(plan.targets[str(a.pk)], 42.0)
        self.assertEqual(plan.inputs[str(a.pk)]["allowance_up"], 12.0)
        self.assertEqual(plan.targets[str(b.pk)], 29.0)          # 10 - 4 = 6 left

    def test_normal_is_the_rule_exactly_as_it_was(self):
        """Not at the high-water mark, no shock: the same +5 the
        ApplyTests fixture has always produced, with a symmetric 10."""
        from bot_program.share_allocator import propose_share_plan
        _reading(self.acct, 2020, days_ago=3)              # dd 1%: not at hwm
        a = _cfg(self.user, name="a", tracks=True, share=50)
        b = _cfg(self.user, name="b", tracks=True, asset_class="forex",
                 symbols=["EURUSD"])
        for _ in range(10):
            _fill(a, 1.0)
        plan = propose_share_plan(self.user)
        self.assertEqual(plan.mode, "normal")
        self.assertEqual(plan.mode_reasons, ["1.0% under the high-water mark"])
        self.assertEqual(plan.targets[str(a.pk)], 55.0)
        self.assertEqual(plan.targets[str(b.pk)], 45.0)
        ia = plan.inputs[str(a.pk)]
        self.assertEqual((ia["allowance_up"], ia["allowance_down"]), (10.0, 10.0))
        self.assertNotIn("SHOCK", ia["why"]); self.assertNotIn("EXPANSION", ia["why"])
        self.assertNotIn("SHOCK", plan.notes); self.assertNotIn("EXPANSION", plan.notes)

    # ── the sync trigger ────────────────────────────────────────────

    def test_the_sync_trigger_proposes_once_per_hour_on_a_shock(self):
        """2,100 twelve hours ago; the sync stores 2,000 → −4.8% → a
        shock plan at once, staff told; the next sync inside the hour
        writes no second plan. A sync that stores no shock never fires."""
        from bot_program.share_models import SharePlan
        _enable("pipeline_share_allocator", "broker_account_sync")
        _reading(self.acct, 2100, days_ago=0.5)
        _cfg(self.user, name="a", tracks=True, share=50, capital="1000")
        _cfg(self.user, name="b", tracks=True, share=50, capital="1000")
        with patch("bot_program.notifications.notify_staff") as notify:
            out = _run_sync((2000.0, "EUR"))
        self.assertEqual(out["stored"], 1)
        plans = list(SharePlan.objects.filter(user=self.user))
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].mode, "shock")
        self.assertEqual(plans[0].state, SharePlan.STATE_PROPOSED)
        self.assertIn("equity −4.8% in 24h", plans[0].mode_reasons)
        notify.assert_called_once()
        self.assertEqual(notify.call_args.kwargs["title"], "⚠ Shock plan proposed")
        self.assertIn("sa_resp: equity −4.8% in 24h", notify.call_args.kwargs["body"])
        self.assertIn("pool(s) to de-risk — open /shares/",
                      notify.call_args.kwargs["body"])
        self.assertEqual(notify.call_args.kwargs["url"], "/shares/")
        self.assertEqual(notify.call_args.kwargs["cooldown_hours"], 1)
        # Inside the cooldown: the reading lands, no second plan.
        with patch("bot_program.notifications.notify_staff") as notify:
            out = _run_sync((1990.0, "EUR"))
        self.assertEqual(out["stored"], 1)
        self.assertEqual(SharePlan.objects.filter(user=self.user).count(), 1)
        notify.assert_not_called()
        # The cooldown key is the gate: cleared, the next shock fires again.
        from django.core.cache import cache
        cache.delete(f"shares:shock:{self.user.pk}")
        with patch("bot_program.notifications.notify_staff") as notify:
            _run_sync((1980.0, "EUR"))
        self.assertEqual(SharePlan.objects.filter(user=self.user).count(), 2)
        notify.assert_called_once()

    def test_the_sync_trigger_never_fires_without_the_component(self):
        from bot_program.share_models import SharePlan
        _enable("broker_account_sync")                  # the allocator off
        _reading(self.acct, 2100, days_ago=0.5)
        _cfg(self.user, name="a", tracks=True, share=50)
        with patch("bot_program.notifications.notify_staff") as notify:
            out = _run_sync((2000.0, "EUR"))
        self.assertEqual(out["stored"], 1)
        self.assertFalse(SharePlan.objects.exists())
        notify.assert_not_called()
        # And with the component on but no shock in the reading: nothing.
        _enable("pipeline_share_allocator")
        with patch("bot_program.notifications.notify_staff") as notify:
            _run_sync((2100.0, "EUR"))                     # back at the high
        self.assertFalse(SharePlan.objects.exists())
        notify.assert_not_called()

    def test_a_failed_shock_proposal_never_fails_the_sync(self):
        _enable("pipeline_share_allocator", "broker_account_sync")
        _reading(self.acct, 2100, days_ago=0.5)
        _cfg(self.user, name="a", tracks=True, share=50)
        with patch("bot_program.share_allocator.propose_share_plan_with_reason",
                   side_effect=RuntimeError("boom")):
            out = _run_sync((2000.0, "EUR"))
        self.assertEqual(out["stored"], 1)
        self.acct.refresh_from_db()
        self.assertEqual(float(self.acct.last_equity), 2000.0)

    # ── automatic de-risking ────────────────────────────────────────

    def _shock_fleet(self):
        _reading(self.acct, 2500, days_ago=10)          # dd 20% → 20/20
        a = _cfg(self.user, name="a", tracks=True, share=50, capital="1000")
        b = _cfg(self.user, name="b", tracks=True, share=50, capital="1000")
        return a, b

    def test_auto_derisk_needs_both_switches_and_a_shock_plan(self):
        from bot_program.share_allocator import propose_share_plan
        from bot_program.share_models import SharePlan
        a, b = self._shock_fleet()
        for live, auto in ((False, False), (True, False), (False, True)):
            _set_live(live); _set_auto_derisk(auto)
            with patch("bot_program.notifications.notify_staff") as notify:
                plan = propose_share_plan(self.user)
            self.assertEqual(plan.mode, "shock")
            self.assertEqual(plan.state, SharePlan.STATE_PROPOSED)
            self.assertNotIn("auto de-risk", plan.notes)
            notify.assert_not_called()
            a.refresh_from_db()
            self.assertEqual(a.extras["account_share_pct"], 50)
            self.assertEqual(float(a.capital), 1000.0)

    def test_auto_derisk_applies_a_pure_derisk_shock_plan_and_tells_staff(self):
        from bot_program.models import AuditLogEntry
        from bot_program.share_allocator import propose_share_plan
        from bot_program.share_models import SharePlan
        a, b = self._shock_fleet()
        _set_live(True); _set_auto_derisk(True)
        with patch("bot_program.notifications.notify_staff") as notify:
            plan = propose_share_plan(self.user)
        self.assertEqual(plan.mode, "shock")
        self.assertEqual(plan.state, SharePlan.STATE_APPLIED)
        self.assertIsNone(plan.confirmed_by)
        self.assertIsNotNone(plan.applied_at)
        self.assertIn("auto de-risk applied", plan.notes)
        self.assertEqual(plan.previous_shares, {str(a.pk): 50, str(b.pk): 50})
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual(a.extras["account_share_pct"], 20.0)
        self.assertEqual(b.extras["account_share_pct"], 20.0)
        self.assertEqual(float(a.capital), 400.0)          # 20% of 2000
        self.assertEqual(float(b.capital), 400.0)
        row = AuditLogEntry.objects.filter(kind="share_plan").last()
        self.assertEqual(row.data["decision"], "auto_derisk")
        self.assertEqual(row.data["plan_id"], plan.pk)
        self.assertIsNone(row.user)
        notify.assert_called_once()
        kw = notify.call_args.kwargs
        self.assertEqual(kw["title"], "⚠ Shares de-risked automatically")
        self.assertIn("a 50% → 20%", kw["body"])
        self.assertIn("b 50% → 20%", kw["body"])
        self.assertEqual((kw["url"], kw["cooldown_hours"]), ("/shares/", 1))
        # Rollback is the same rollback: exact.
        from bot_program.share_allocator import rollback_share_plan
        rollback_share_plan(plan.pk, None)
        a.refresh_from_db()
        self.assertEqual(a.extras["account_share_pct"], 50)
        self.assertEqual(float(a.capital), 1000.0)

    def test_auto_derisk_never_applies_a_plan_with_an_upward_target(self):
        """c just opted in with no share: it enters at its floor, which is
        an UPWARD move, so the plan waits for a human although a and b
        both drop. is_pure_derisk is the rule, pinned on its own too."""
        from bot_program.share_allocator import (is_pure_derisk,
                                                 propose_share_plan)
        from bot_program.share_models import SharePlan
        a, b = self._shock_fleet()
        c = _cfg(self.user, name="c", tracks=True, capital="10")
        _set_live(True); _set_auto_derisk(True)
        with patch("bot_program.notifications.notify_staff") as notify:
            plan = propose_share_plan(self.user)
        self.assertEqual(plan.mode, "shock")
        self.assertEqual(plan.targets[str(c.pk)], 2.0)
        self.assertEqual(plan.state, SharePlan.STATE_PROPOSED)
        self.assertNotIn("auto de-risk", plan.notes)
        notify.assert_not_called()
        a.refresh_from_db()
        self.assertEqual(float(a.capital), 1000.0)
        from types import SimpleNamespace
        self.assertTrue(is_pure_derisk(SimpleNamespace(
            targets={"1": 20.0, "2": 50.0}, current_shares={"1": 50, "2": 50})))
        self.assertFalse(is_pure_derisk(SimpleNamespace(       # one goes up
            targets={"1": 20.0, "2": 50.01}, current_shares={"1": 50, "2": 50})))
        self.assertFalse(is_pure_derisk(SimpleNamespace(       # all held
            targets={"1": 50.0, "2": 50.0}, current_shares={"1": 50, "2": 50})))
        self.assertFalse(is_pure_derisk(SimpleNamespace(       # no current
            targets={"1": 2.0}, current_shares={"1": None})))
        self.assertTrue(is_pure_derisk(SimpleNamespace(        # 1e-9 slack
            targets={"1": 50.0 + 1e-10, "2": 40.0},
            current_shares={"1": 50, "2": 50})))

    def test_auto_derisk_leaves_the_plan_proposed_on_a_daily_cap_refusal(self):
        from bot_program.share_allocator import (MAX_APPLIES_PER_DAY,
                                                 propose_share_plan)
        from bot_program.share_models import SharePlan
        a, b = self._shock_fleet()
        _set_live(True); _set_auto_derisk(True)
        for _ in range(MAX_APPLIES_PER_DAY):
            _applied(self.user, {a.pk: 50}, {a.pk: 50}, hours_ago=2)
        with patch("bot_program.notifications.notify_staff") as notify:
            plan = propose_share_plan(self.user)
        self.assertEqual(plan.mode, "shock")
        self.assertEqual(plan.state, SharePlan.STATE_PROPOSED)
        self.assertNotIn("auto de-risk", plan.notes)
        notify.assert_not_called()
        a.refresh_from_db()
        self.assertEqual(a.extras["account_share_pct"], 50)
        self.assertEqual(float(a.capital), 1000.0)
        # A human can still apply it once the cap frees — the plan is whole.
        self.assertEqual(plan.targets[str(a.pk)], 20.0)

    def test_the_migration_is_present_and_clean(self):
        """0027 adds mode and mode_reasons; makemigrations --check finds
        nothing left to write."""
        from importlib import import_module
        from io import StringIO

        from django.core.management import call_command
        from bot_program.share_models import SharePlan
        mig = import_module("bot_program.migrations.0027_share_plan_mode")
        self.assertEqual({op.name for op in mig.Migration.operations},
                         {"mode", "mode_reasons"})
        self.assertEqual(SharePlan._meta.get_field("mode").max_length, 12)
        self.assertEqual(SharePlan._meta.get_field("mode").default, "normal")
        self.assertTrue(SharePlan._meta.get_field("mode").db_index)
        self.assertEqual(SharePlan._meta.get_field("mode_reasons").default, list)
        out = StringIO()
        try:
            call_command("makemigrations", "bot_program", "--check", "--dry-run",
                         stdout=out, verbosity=0)
        except SystemExit as e:  # --check exits 1 when a migration is missing
            self.fail(f"makemigrations --check found changes: {out.getvalue()} "
                      f"(exit {e.code})")
