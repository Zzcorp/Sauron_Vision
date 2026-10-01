"""One account, one pool: shared capital (2026-10-01).

The operator: "votre système d'allocation de capitaux par bot est
restrictif ... il devrait être 100% mobile". Each live bot and manual lane
carried its own envelope (forex 1,100, commodity 1,100, crypto 200, stock
1,609, a bot at 10% of the account, another at 20%), so a ticket on one
lane was refused while the money sat idle on another. He chose the shared
pool: every follower may draw on the WHOLE account, first come first
served, and only the account's limits bind — MAX ACCOUNT PLEDGED, the
daily loss, the per-position caps.

The switch is shared_capital_live, OFF by default, a live-money switch the
"all on" button never arms. Pinned here: the rule (every follower 1.0, an
explicit share is that pool's own ceiling, nothing refused), the switch
read (off when absent or unreadable), the sync writing the whole base to
each follower, and the two places that ADD pools together counting the
shared ones once — Morgul's daily stop and the preflight's armed total —
because summed, seven followers of one account read seven accounts.

Run with:  python manage.py test tests.test_shared_capital
"""
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_pools_are_shares_of_the_account import _acct, _cfg, _pool, _user


def _switch(on=True):
    from core.platform_control import PlatformComponent
    PlatformComponent.objects.update_or_create(
        key="shared_capital_live",
        defaults={"name": "Shared Capital (one pool)", "category": "system",
                  "is_enabled": on})


class TheRuleTests(SimpleTestCase):

    def _alloc(self, *pools, **kw):
        from bot_program.capital_truth import allocate_shares
        kw.setdefault("shared", True)
        return allocate_shares(list(pools), **kw)

    def test_every_automatic_follower_draws_on_the_whole_account(self):
        out = self._alloc(_pool(1), _pool(2), _pool(3))
        self.assertTrue(out["ok"])
        self.assertTrue(out["shared"])
        self.assertEqual(out["plan"], {1: 1.0, 2: 1.0, 3: 1.0})

    def test_an_explicit_share_is_that_pools_own_ceiling(self):
        out = self._alloc(_pool(1, account_share_pct=30), _pool(2))
        self.assertAlmostEqual(out["plan"][1], 0.30)
        self.assertEqual(out["plan"][2], 1.0)

    def test_shares_past_one_account_are_not_refused(self):
        """The slices refuse 60% + 50%; one pool does not."""
        out = self._alloc(_pool(1, account_share_pct=60),
                          _pool(2, account_share_pct=50),
                          _pool(3, account_share_pct=100), _pool(4))
        self.assertTrue(out["ok"], out["reason"])
        self.assertEqual(out["plan"], {1: 0.6, 2: 0.5, 3: 1.0, 4: 1.0})

    def test_off_the_slices_are_unchanged(self):
        out = self._alloc(_pool(1), _pool(2), shared=False)
        self.assertFalse(out["shared"])
        self.assertEqual(out["plan"], {1: 0.5, 2: 0.5})
        self.assertFalse(self._alloc(_pool(1, account_share_pct=60),
                                     _pool(2, account_share_pct=50),
                                     shared=False)["ok"])

    def test_the_what_if_override_reads_the_same_rule(self):
        out = self._alloc(_pool(1, account_share_pct=30), _pool(2),
                          shares={2: 80})
        self.assertEqual(out["plan"], {1: 0.3, 2: 0.8})


class TheCombinedCapitalTests(SimpleTestCase):

    def _c(self, capital, *, tracks=False, mode="live"):
        extras = {"capital_tracks_broker": True} if tracks else {}
        return SimpleNamespace(capital=capital, extras=extras, mode=mode)

    def test_shared_followers_are_one_pool_counted_once(self):
        from bot_program.capital_truth import combined_capital
        pools = [self._c(2240, tracks=True), self._c(2240, tracks=True),
                 self._c(672, tracks=True), self._c(300)]
        self.assertEqual(combined_capital(pools, shared=True), 2540.0)

    def test_without_the_switch_they_are_summed_as_before(self):
        from bot_program.capital_truth import combined_capital
        pools = [self._c(2240, tracks=True), self._c(2240, tracks=True),
                 self._c(300)]
        self.assertEqual(combined_capital(pools, shared=False), 4780.0)

    def test_a_paper_pool_is_never_part_of_the_shared_one(self):
        from bot_program.capital_truth import combined_capital
        pools = [self._c(2240, tracks=True), self._c(5000, tracks=True,
                                                     mode="paper")]
        self.assertEqual(combined_capital(pools, shared=True), 7240.0)


class TheSwitchTests(TestCase):

    def test_absent_is_off(self):
        from bot_program.capital_truth import allocate_shares, shared_capital
        self.assertFalse(shared_capital())
        self.assertFalse(allocate_shares([_pool(1), _pool(2)])["shared"])

    def test_on_is_read(self):
        from bot_program.capital_truth import allocate_shares, shared_capital
        _switch(True)
        self.assertTrue(shared_capital())
        self.assertEqual(allocate_shares([_pool(1), _pool(2)])["plan"],
                         {1: 1.0, 2: 1.0})

    def test_unreadable_is_off_and_says_so(self):
        from bot_program.capital_truth import shared_capital
        _switch(True)
        with patch("core.platform_control.is_component_enabled",
                   side_effect=RuntimeError("db gone")), \
                self.assertLogs("bot_program.capital_truth", "WARNING"):
            self.assertFalse(shared_capital())

    def test_it_is_a_live_money_switch_the_all_on_button_never_arms(self):
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           DEFAULT_COMPONENTS,
                                           LIVE_MONEY_SWITCHES)
        self.assertIn("shared_capital_live", LIVE_MONEY_SWITCHES)
        self.assertIn("shared_capital_live", BULK_ENABLE_EXEMPT)
        row = next(c for c in DEFAULT_COMPONENTS
                   if c["key"] == "shared_capital_live")
        self.assertEqual(row["category"], "system")
        self.assertLessEqual(len(row["description"]), 300)

    def test_seeding_registers_it_off(self):
        from core.platform_control import PlatformComponent, seed_components
        seed_components()
        self.assertFalse(PlatformComponent.objects.get(
            key="shared_capital_live").is_enabled)


class TheSyncTests(TestCase):

    def test_every_follower_is_written_the_whole_account(self):
        """The live box: two manual lanes (no symbols) and two bots, one of
        them with a share it keeps as its ceiling."""
        _switch(True)
        u = _user()
        forex = _cfg(u, name="manual", asset_class="forex", tracks=True,
                     capital="1100", symbols=())
        crypto = _cfg(u, name="manual", asset_class="crypto", tracks=True,
                      capital="200", symbols=())
        etf = _cfg(u, name="commodity_etf", tracks=True, capital="448")
        capped = _cfg(u, name="capped", tracks=True, share=30)
        typed = _cfg(u, name="typed", capital="150")
        from bot_program.tasks import _follow_the_account
        _follow_the_account(u, 2240.0, "USD")
        for row in (forex, crypto, etf, capped, typed):
            row.refresh_from_db()
        self.assertEqual(float(forex.capital), 2240.0)
        self.assertEqual(float(crypto.capital), 2240.0)
        self.assertEqual(float(etf.capital), 2240.0)
        self.assertEqual(float(capped.capital), 672.0)
        self.assertEqual(float(typed.capital), 150.0)   # not a follower

    def test_shares_past_one_account_are_retuned_and_nobody_alerted(self):
        _switch(True)
        u = _user()
        a = _cfg(u, name="a", tracks=True, share=60, capital="1")
        b = _cfg(u, name="b", tracks=True, share=50, capital="1")
        from bot_program.tasks import _follow_the_account
        with patch("bot_program.notifications.notify_staff") as alert:
            _follow_the_account(u, 500.0, "EUR")
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((float(a.capital), float(b.capital)), (300.0, 250.0))
        alert.assert_not_called()

    def test_switched_off_the_followers_go_back_to_slices(self):
        _switch(True)
        u = _user()
        a = _cfg(u, name="a", tracks=True)
        b = _cfg(u, name="b", tracks=True)
        from bot_program.tasks import _follow_the_account
        _follow_the_account(u, 500.0, "EUR")
        _switch(False)
        _follow_the_account(u, 500.0, "EUR")
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((float(a.capital), float(b.capital)), (250.0, 250.0))


class ThePreflightTests(TestCase):

    def _run(self):
        out = StringIO()
        call_command("preflight_live", stdout=out)
        return out.getvalue()

    def test_it_says_the_pool_is_shared_and_what_binds(self):
        _switch(True)
        u = _user()
        _acct(u)
        _cfg(u, name="a", tracks=True, capital="500")
        _cfg(u, name="b", tracks=True, capital="500")
        out = self._run()
        self.assertIn("SHARED CAPITAL (shared_capital_live ON): these 2 "
                      "pool(s) each draw on the whole account", out)
        self.assertIn("MAX ACCOUNT PLEDGED", out)
        self.assertIn("follows the account · auto 100%", out)
        self.assertNotIn("more than one account", out)
        self.assertNotIn("together they can deploy", out)

    def test_a_typed_pool_beside_the_shared_one_is_still_counted(self):
        _switch(True)
        u = _user()
        _acct(u)
        _cfg(u, name="a", tracks=True, capital="500")
        _cfg(u, name="b", tracks=True, capital="500")
        _cfg(u, name="typed", capital="500")
        self.assertIn("together they can deploy 2.0x the money", self._run())


class MorgulsDailyStopTests(TestCase):
    """G7 takes the smallest daily stop on the COMBINED capital. Summed,
    two followers of one shared account doubled the stop."""

    def setUp(self):
        from tests.test_morgul import _cfg as _mcfg
        from tests.test_morgul import _staff
        self.now = timezone.now()
        self.user = _staff()
        self.a = _mcfg(self.user, "Forex live", "forex", mode="live",
                       capital="1000", extras={"capital_tracks_broker": True})
        self.b = _mcfg(self.user, "Stock live", "stock", mode="live",
                       capital="1000", extras={"capital_tracks_broker": True})

    def _lose(self, pnl):
        from tests.test_morgul import _trade
        _trade(self.a, "EURUSD", paper=False, status="CLOSED",
               exit_price="1.6000", pnl=pnl,
               opened=self.now - timedelta(hours=3),
               closed=self.now - timedelta(hours=1))

    def test_shared_the_stop_is_taken_on_the_account_once(self):
        from tests.test_morgul import _check
        _switch(True)
        self._lose("-25")      # past 2% of 1,000; inside 2% of 2,000
        found = _check("daily_loss", self.now)[1]
        self.assertEqual(len(found), 1)
        self.assertIn("Daily stop used: 2.0% of 1,000.00 USD = 20.00 USD",
                      found[0].facts)

    def test_without_the_switch_the_pools_are_summed_as_before(self):
        from tests.test_morgul import _check
        _switch(False)
        self._lose("-25")
        self.assertEqual(_check("daily_loss", self.now)[1], [])
