"""THE DRAWDOWN GOVERNOR STANDS DOWN ONLY FOR WHAT A PLAN CUT (Gap 3,
2026-10-24).

The posture's drawdown_scale (bot_program/posture.py) multiplies a real
bot entry by share_allocator.governor_for (1.0 down to 0.4 between 5% and
20% under the high-water mark) while crisis_mode is ON. It stood down to
1.0 as soon as share_allocator_mode_live or capital_desk_mode_live was ON
— a switch that only PERMITS an apply, or governs the desk's budget —
whether or not any plan had cut the pool. Now it credits only what an
APPLIED share plan, still in force on this config, cut this config's pool
by, and never more than that plan's own governor took (M2: under shared
capital an automatic follower is 100% before its first plan, so a cut of
the conversion is not the governor's); the rest of the governor binds.
The desk's switch carries nothing to entries.

Every read that fails gives the full governor. With the share switch OFF
the answer is today's, unchanged.

Run with:  python manage.py test tests.test_posture_governor
"""
import inspect
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from tests.test_aragorn import _switch
from tests.test_risk_limits_bind import _config

SHARE_SWITCH = "share_allocator_mode_live"


def _dd(pct):
    return {"drawdown_pct": pct, "n": 10, "stale": False}


class _Gov(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("gov_u",
                                                         password="x")
        # a pad config first, so this config's pk is not the user's: a
        # plan read by the wrong key would otherwise still be found
        _config(self.user, symbols=["ETHUSD"], mode="live", name="pad")
        self.cfg = _config(self.user, symbols=["BTCUSD"], mode="live")
        self.assertNotEqual(self.cfg.pk, self.user.pk)
        self.dd = 0.15                          # governor_for: 0.6

    def _share(self, pct, cfg=None):
        cfg = cfg or self.cfg
        cfg.extras = dict(cfg.extras or {}, account_share_pct=pct)
        cfg.save(update_fields=["extras"])

    def _plan(self, state="applied", *, before=30.0, target=18.0,
              governor=0.6, prev="same", minutes_ago=60, rb_minutes_ago=None,
              cfg=None):
        from bot_program.share_models import SharePlan
        cfg = cfg or self.cfg
        k = str(cfg.pk)
        now = timezone.now()
        applied = state in ("applied", "rolled_back")
        return SharePlan.objects.create(
            user=self.user, state=state, governor=governor,
            applied_at=(now - timedelta(minutes=minutes_ago)
                        if applied else None),
            rolled_back_at=(now - timedelta(minutes=rb_minutes_ago)
                            if rb_minutes_ago is not None else None),
            targets={k: target}, current_shares={k: before},
            previous_shares={k: before if prev == "same" else prev}
            if applied else {})

    def _scale(self, cfg="self"):
        from bot_program.posture import drawdown_scale
        cfg = self.cfg if cfg == "self" else cfg
        with patch("bot_program.capital_truth.equity_drawdown",
                   return_value=_dd(self.dd)):
            return drawdown_scale(self.user, cfg)


class TheSwitchesTests(_Gov):

    def test_both_live_switches_off_the_governor_binds(self):
        scale, why = self._scale()
        self.assertAlmostEqual(scale, 0.6)
        self.assertIn("15.0% under its high-water mark", why)

    def test_the_share_switch_alone_carries_nothing(self):
        _switch(SHARE_SWITCH)
        self.assertAlmostEqual(self._scale()[0], 0.6, msg="today: 1.0")

    def test_the_desk_switch_never_stands_the_governor_down(self):
        _switch("capital_desk_mode_live")
        self.assertAlmostEqual(self._scale()[0], 0.6, msg="today: 1.0")

    def test_switch_off_with_an_old_applied_plan_keeps_the_full_governor(self):
        self._share(18.0)
        self._plan()
        self.assertAlmostEqual(self._scale()[0], 0.6,
                         msg="the switch OFF keeps today's answer")


class ThePlansTests(_Gov):

    def setUp(self):
        super().setUp()
        _switch(SHARE_SWITCH)

    def test_a_proposal_a_rejection_or_an_expiry_carries_nothing(self):
        self._share(18.0)
        for state in ("proposed", "rejected", "expired"):
            with self.subTest(state=state):
                p = self._plan(state)
                self.assertAlmostEqual(self._scale()[0], 0.6)
                p.delete()

    def test_a_plan_that_cut_this_pool_by_the_governor_stands_it_down(self):
        """A regression pin, not a change: with the switch ON and a plan
        whose cut is the governor's, today's answer is 1.0 too. No double
        governing."""
        self._share(18.0)
        self._plan(before=30.0, target=18.0, governor=0.6)
        self.assertEqual(self._scale(), (1.0, ""))

    def test_only_the_residual_binds_when_the_drawdown_deepened(self):
        self._share(24.0)
        self._plan(before=30.0, target=24.0, governor=0.8)
        scale, why = self._scale()
        self.assertAlmostEqual(scale, 0.75)
        self.assertAlmostEqual(24.0 * scale, 30.0 * 0.6)
        self.assertIn("an applied share plan already cut this pool to x0.80",
                      why)

    def test_a_plan_that_did_not_cut_this_pool_carries_nothing_for_it(self):
        self._share(30.0)
        self._plan(before=30.0, target=30.0)
        self.assertAlmostEqual(self._scale()[0], 0.6, msg="held, not cut")
        other = _config(self.user, symbols=["ETHUSD"], mode="live",
                        name="other")
        self.assertAlmostEqual(self._scale(cfg=other)[0], 0.6, msg="not in its targets")
        self.assertAlmostEqual(self._scale(cfg=None)[0], 0.6, msg="no config")

    def test_a_rollback_after_the_apply_carries_nothing(self):
        self._share(18.0)
        self._plan("rolled_back", minutes_ago=90, rb_minutes_ago=5)
        self.assertAlmostEqual(self._scale()[0], 0.6)

    def test_an_out_of_order_rollback_is_the_newest_touch(self):
        # A applied, B applied, then A rolled back: the newest touch is
        # the rollback, whatever B cut
        self._share(18.0)
        self._plan("rolled_back", minutes_ago=120, rb_minutes_ago=5)
        self._plan("applied", minutes_ago=60)
        self.assertAlmostEqual(self._scale()[0], 0.6)

    def test_a_hand_edit_since_the_apply_carries_nothing(self):
        self._share(20.0)
        self._plan(before=30.0, target=18.0)
        self.assertAlmostEqual(self._scale()[0], 0.6)

    def test_a_previous_share_written_as_text_is_read(self):
        """N5: the apply snapshots extras as found, which may be text; the
        share before the plan is that text read as a number, not the
        proposal's figure."""
        self.dd = 0.20                                  # g 0.4
        self._share(18.0)
        self._plan(before=99.0, target=18.0, governor=0.4, prev="30")
        self.assertAlmostEqual(self._scale()[0], 0.4 / 0.6)

    def test_an_automatic_follower_made_explicit_under_shared_capital_keeps_the_governor(self):
        """M2: under shared capital an automatic follower is 100% before
        its first plan (previous None, current 100); a cut to 25 is the
        conversion, not the governor's, so only the plan's own governor is
        credited."""
        _switch("shared_capital_live")
        self._share(25.0)
        self._plan(before=100.0, target=25.0, governor=1.0, prev=None)
        self.assertAlmostEqual(self._scale()[0], 0.6, msg="the plan's rule gave 1.0")
        from bot_program.share_models import SharePlan
        SharePlan.objects.update(governor=0.8)
        self.assertAlmostEqual(self._scale()[0], 0.75)


class NothingUnreadStandsItDownTests(_Gov):

    def setUp(self):
        super().setUp()
        _switch(SHARE_SWITCH)
        self._share(18.0)
        self._plan(before=30.0, target=18.0, governor=0.6)

    def test_an_unreadable_plan_is_not_an_applied_one(self):
        self.assertEqual(self._scale()[0], 1.0, "the plan carries it")
        with patch("bot_program.share_models.SharePlan.objects.filter",
                   side_effect=RuntimeError("db gone")):
            self.assertAlmostEqual(self._scale()[0], 0.6)
        with patch("bot_program.share_allocator.carried_cut",
                   side_effect=ImportError("gone")):
            self.assertAlmostEqual(self._scale()[0], 0.6)
        with patch("bot_program.share_allocator.is_live_mode",
                   side_effect=RuntimeError("switch unread")):
            self.assertAlmostEqual(self._scale()[0], 0.6)


class TheInvariantGridTests(_Gov):
    """M3: every cell calls drawdown_scale on a seeded plan. The pool sizes
    an entry at target x scale: never above the switch-OFF size on the
    share before the plan, never above what the plan's own governor left
    to take, never below the double-governed target x g, never above
    target."""

    def test_never_larger_than_the_switch_off_size(self):
        from bot_program.share_allocator import governor_for
        from bot_program.share_models import SharePlan
        _switch(SHARE_SWITCH)
        cells = 0
        for before in (30.0, 100.0):
            for target in (10.0, 18.0, 24.0, 29.0, 30.0):
                for g_plan in (1.0, 0.8, 0.6, 0.4):
                    for dd in (0.04, 0.10, 0.15, 0.20, 0.30):
                        SharePlan.objects.all().delete()
                        self._share(target)
                        self._plan(before=before, target=target,
                                   governor=g_plan)
                        self.dd = dd
                        g = governor_for(dd)
                        scale = self._scale()[0]
                        with self.subTest(before=before, target=target,
                                          g_plan=g_plan, dd=dd):
                            self.assertLessEqual(scale, 1.0)
                            self.assertLessEqual(target * scale,
                                                 before * g + 1e-9)
                            self.assertLessEqual(scale, g / g_plan + 1e-9)
                            self.assertGreaterEqual(target * scale,
                                                    target * g - 1e-9)
                        cells += 1
        self.assertEqual(cells, 200)


class TheEntryTests(_Gov):

    def test_the_bot_sizes_a_real_entry_with_the_governor(self):
        from bot_program.asset_engine.base import make_bot
        from bot_program.market_stress import set_override
        _switch("crisis_mode")
        _switch(SHARE_SWITCH)
        set_override("calm", by="t")
        bot = make_bot(self.cfg)
        stage = {"may_trade": True, "force_paper": False,
                 "live_size_factor": 1.0, "stage": "live_full", "reason": ""}
        dec = SimpleNamespace(rule_name="golden_cross", direction="BUY")
        with patch("bot_program.capital_truth.equity_drawdown",
                   return_value=_dd(0.15)):
            stage, meta = bot._aragorn_and_posture("BTCUSD", dec, stage)
        self.assertAlmostEqual(stage["live_size_factor"], 0.6)
        self.assertIn("under its high-water mark", meta["posture"]["why"])

    def test_the_bot_entry_reads_its_own_configs_plan(self):
        """End to end with an applied plan that cut this pool by the
        governor: the bot's posture hook passes its config, so the
        governor stands down for this entry (no double governing); a
        config the plan did not cut keeps the full governor."""
        from bot_program.asset_engine.base import make_bot
        from bot_program.market_stress import set_override
        _switch("crisis_mode")
        _switch(SHARE_SWITCH)
        set_override("calm", by="t")
        self._share(18.0)
        self._plan(before=30.0, target=18.0, governor=0.6)
        dec = SimpleNamespace(rule_name="golden_cross", direction="BUY")
        pad = _config(self.user, symbols=["SOLUSD"], mode="live",
                      name="uncut")
        for cfg, want in ((self.cfg, 1.0), (pad, 0.6)):
            with self.subTest(cfg=cfg.name):
                stage = {"may_trade": True, "force_paper": False,
                         "live_size_factor": 1.0, "stage": "live_full",
                         "reason": ""}
                with patch("bot_program.capital_truth.equity_drawdown",
                           return_value=_dd(0.15)):
                    stage, _meta = make_bot(cfg)._aragorn_and_posture(
                        "BTCUSD", dec, stage)
                self.assertAlmostEqual(stage["live_size_factor"], want)

    def test_the_council_says_the_size_the_bot_uses(self):
        """The council's posture line reads the sitting's config the same
        way: with the plan, this entry's size is x1, not x0.6."""
        from ai_agents.agents import council
        from bot_program.market_stress import set_override
        _switch("crisis_mode")
        _switch(SHARE_SWITCH)
        set_override("calm", by="t")
        self._share(18.0)
        self._plan(before=30.0, target=18.0, governor=0.6)
        session = SimpleNamespace(
            user=self.user, user_id=self.user.pk, origin="bot",
            symbol="BTCUSD", asset_class="crypto", side="BUY",
            config_id=self.cfg.pk, config=self.cfg)
        with patch("bot_program.capital_truth.equity_drawdown",
                   return_value=_dd(0.15)), \
                patch("brain.strategist.measured_posture",
                      return_value={"title_word": "calm", "note": "t",
                                    "crisis_mode_on": True}):
            text = council.war_text(session)
        line = [ln for ln in text.splitlines()
                if ln.startswith("  posture:")][0]
        self.assertIn("size x1", line)
        self.assertNotIn("size x0.6", line)

    def test_the_hooks_pass_the_config(self):
        from ai_agents.agents import council
        from bot_program.asset_engine.base import AssetBot
        self.assertIn("cfg=self.cfg",
                      inspect.getsource(AssetBot._aragorn_and_posture))
        self.assertIn("cfg=_config_for(session)",
                      inspect.getsource(council.war_text))
