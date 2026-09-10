"""Pools that follow the account take SHARES of it, computed on every sync.

By Thursday 2026-09-10 this deployment had 1,000 of hand-typed pools over
a 500 EUR account: one lane followed the account (the only one allowed),
the bots carried numbers typed once, and together they could deploy twice
the money. The operator's ask: "que Sauron calcule cela en continu" — and
that it be intelligent about it.

The rule, in one place (capital_truth.allocate_shares): a follower takes
an explicit share, or an automatic one — an equal split of what the
explicit followers leave. One follower with no number is the whole
account, the original contract. Shares that do not fit in 100% retune
nothing and raise an alert. The arming path, the sync and the preflight
all ask the same function, so they cannot disagree.

Run with:  python manage.py test tests.test_pools_are_shares_of_the_account
"""
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase
from django.utils import timezone


def _pool(pk, name="p", asset_class="stock", **extras):
    return SimpleNamespace(pk=pk, name=name, asset_class=asset_class,
                           extras=extras)


class TheRuleTests(SimpleTestCase):

    def _alloc(self, *pools, **kw):
        from bot_program.capital_truth import allocate_shares
        return allocate_shares(list(pools), **kw)

    def test_one_follower_with_no_number_is_the_whole_account(self):
        out = self._alloc(_pool(1))
        self.assertTrue(out["ok"])
        self.assertEqual(out["plan"], {1: 1.0})

    def test_two_automatic_followers_split_it_equally(self):
        out = self._alloc(_pool(1), _pool(2))
        self.assertEqual(out["plan"], {1: 0.5, 2: 0.5})

    def test_an_explicit_share_is_taken_and_the_rest_is_split(self):
        out = self._alloc(_pool(1, account_share_pct=30), _pool(2), _pool(3))
        self.assertAlmostEqual(out["plan"][1], 0.30)
        self.assertAlmostEqual(out["plan"][2], 0.35)
        self.assertAlmostEqual(out["plan"][3], 0.35)

    def test_explicit_shares_past_the_account_are_refused(self):
        out = self._alloc(_pool(1, "manual", account_share_pct=60),
                          _pool(2, "etf", account_share_pct=50))
        self.assertFalse(out["ok"])
        self.assertEqual(out["plan"], {})
        self.assertIn("110%", out["reason"])
        self.assertIn("manual (stock) 60%", out["reason"])

    def test_a_full_account_leaves_nothing_for_an_automatic_follower(self):
        out = self._alloc(_pool(1, account_share_pct=100), _pool(2, "etf"))
        self.assertFalse(out["ok"])
        self.assertIn("would get nothing", out["reason"])
        self.assertIn("etf", out["reason"])

    def test_the_what_if_override_answers_before_anything_is_saved(self):
        out = self._alloc(_pool(1, account_share_pct=30), _pool(2),
                          shares={2: 80})
        self.assertFalse(out["ok"])
        out = self._alloc(_pool(1, account_share_pct=30), _pool(2),
                          shares={2: None})
        self.assertAlmostEqual(out["plan"][2], 0.70)

    def test_a_share_that_is_not_a_percentage_reads_as_automatic(self):
        from bot_program.capital_truth import account_share_pct
        self.assertIsNone(account_share_pct(_pool(1, account_share_pct="x")))
        self.assertIsNone(account_share_pct(_pool(1, account_share_pct=150)))
        self.assertIsNone(account_share_pct(_pool(1, account_share_pct=0)))
        self.assertEqual(account_share_pct(_pool(1, account_share_pct="30")),
                         30.0)

    def test_the_label_says_what_the_page_needs(self):
        from bot_program.capital_truth import share_label
        self.assertEqual(share_label(_pool(1, account_share_pct=30)), "30%")
        self.assertEqual(share_label(_pool(2), {2: 0.35}), "auto 35%")
        self.assertEqual(share_label(_pool(3)), "auto")


def _user(name="shares_u", **kw):
    return User.objects.create_user(name, password="x", **kw)


def _cfg(user, *, name, asset_class="stock", mode="live", enabled=True,
         capital="100", tracks=False, share=None):
    from bot_program.models import AssetBotConfig
    extras = {}
    if tracks:
        extras["capital_tracks_broker"] = True
    if share is not None:
        extras["account_share_pct"] = share
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode=mode,
        symbols=["GLDM"], capital=Decimal(capital), base_currency="EUR",
        enabled=enabled, extras=extras)


class TheSyncWritesSharesTests(TestCase):

    def test_every_follower_gets_its_share_of_the_reading(self):
        u = _user()
        manual = _cfg(u, name="manual", tracks=True)
        etf = _cfg(u, name="etf", tracks=True, share=30)
        typed = _cfg(u, name="typed", capital="150")
        from bot_program.tasks import _follow_the_account
        _follow_the_account(u, 500.0, "EUR")
        manual.refresh_from_db(); etf.refresh_from_db(); typed.refresh_from_db()
        self.assertEqual(float(manual.capital), 350.0)
        self.assertEqual(float(etf.capital), 150.0)
        self.assertEqual(float(typed.capital), 150.0)   # not a follower

    def test_it_follows_the_account_down_as_well_as_up(self):
        u = _user()
        manual = _cfg(u, name="manual", tracks=True, capital="500")
        from bot_program.tasks import _follow_the_account
        _follow_the_account(u, 412.5, "EUR")
        manual.refresh_from_db()
        self.assertEqual(float(manual.capital), 412.5)

    def test_over_allocated_followers_are_retuned_not_at_all_and_alerted(self):
        u = _user()
        a = _cfg(u, name="a", tracks=True, share=60, capital="1")
        b = _cfg(u, name="b", tracks=True, share=50, capital="1")
        from bot_program.tasks import _follow_the_account
        with patch("bot_program.notifications.notify_staff") as alert:
            _follow_the_account(u, 500.0, "EUR")
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual((float(a.capital), float(b.capital)), (1.0, 1.0))
        alert.assert_called_once()
        self.assertIn("over-allocated", alert.call_args.kwargs["title"])
        self.assertIn("110%", alert.call_args.kwargs["body"])

    def test_paper_and_disabled_pools_are_not_followers(self):
        u = _user()
        paper = _cfg(u, name="paper", mode="paper", tracks=True)
        off = _cfg(u, name="off", enabled=False, tracks=True)
        live = _cfg(u, name="live", tracks=True)
        from bot_program.tasks import _follow_the_account
        _follow_the_account(u, 500.0, "EUR")
        paper.refresh_from_db(); off.refresh_from_db(); live.refresh_from_db()
        self.assertEqual(float(paper.capital), 100.0)
        self.assertEqual(float(off.capital), 100.0)
        self.assertEqual(float(live.capital), 500.0)   # the whole account


def _acct(user, equity="500.00", currency="EUR"):
    from bot_program.models import IBKRAccount
    acct = IBKRAccount.objects.create(user=user, port=4003,
                                      is_primary_for_stocks=True)
    acct.set_credentials("U1234567")
    acct.username_enc, acct.password_enc = "x", "y"
    acct.last_equity = Decimal(equity)
    acct.last_equity_currency = currency
    acct.last_equity_at = timezone.now()
    acct.save()
    return acct


def _pin(user, pin="1234"):
    from django.contrib.auth.hashers import make_password
    from portfolio.trader_profile import TraderProfile
    prof, _ = TraderProfile.objects.get_or_create(user=user)
    prof.access_pin_hash = make_password(pin)
    prof.save(update_fields=["access_pin_hash"])


class ABotFollowsTheAccountTooTests(TestCase):
    """The manual lane could follow; the bots carried numbers typed once.
    Now a live bot follows from /asset-bots/ with the same rule and the
    same PIN a live arming takes."""

    def setUp(self):
        self.user = _user(is_staff=True, is_superuser=True)
        _acct(self.user)
        _pin(self.user)
        self.client = Client()
        self.client.force_login(self.user)

    def _follow(self, cfg, **fields):
        from django.urls import reverse
        data = {"config_id": cfg.id, "follow": "1", "pin": "1234"}
        data.update(fields)
        return self.client.post(reverse("hq_follow_asset_bot"), data)

    def test_a_live_bot_takes_its_share_on_the_spot(self):
        cfg = _cfg(self.user, name="etf", capital="200")
        self._follow(cfg, share="30")
        cfg.refresh_from_db()
        self.assertTrue(cfg.extras.get("capital_tracks_broker"))
        self.assertEqual(cfg.extras.get("account_share_pct"), 30.0)
        self.assertEqual(float(cfg.capital), 150.0)

    def test_blank_is_automatic(self):
        _cfg(self.user, name="manual", tracks=True, share=40)
        cfg = _cfg(self.user, name="etf", capital="200")
        self._follow(cfg, share="")
        cfg.refresh_from_db()
        self.assertNotIn("account_share_pct", cfg.extras)
        self.assertEqual(float(cfg.capital), 300.0)   # the other 60%

    def test_the_pin_is_required_to_start(self):
        cfg = _cfg(self.user, name="etf", capital="200")
        self._follow(cfg, share="30", pin="0000")
        cfg.refresh_from_db()
        self.assertNotIn("capital_tracks_broker", cfg.extras)
        self.assertEqual(float(cfg.capital), 200.0)

    def test_a_paper_bot_cannot_follow(self):
        cfg = _cfg(self.user, name="etf", mode="paper", capital="200")
        self._follow(cfg, share="30")
        cfg.refresh_from_db()
        self.assertNotIn("capital_tracks_broker", cfg.extras)

    def test_shares_that_do_not_fit_change_nothing(self):
        _cfg(self.user, name="manual", tracks=True, share=80)
        cfg = _cfg(self.user, name="etf", capital="200")
        self._follow(cfg, share="30")
        cfg.refresh_from_db()
        self.assertNotIn("capital_tracks_broker", cfg.extras)
        self.assertEqual(float(cfg.capital), 200.0)

    def test_unfollowing_needs_nothing_and_keeps_the_pool(self):
        cfg = _cfg(self.user, name="etf", tracks=True, share=30,
                   capital="150")
        self._follow(cfg, follow="0", pin="")
        cfg.refresh_from_db()
        self.assertNotIn("capital_tracks_broker", cfg.extras)
        self.assertNotIn("account_share_pct", cfg.extras)
        self.assertEqual(float(cfg.capital), 150.0)

    def test_the_page_shows_the_share(self):
        _cfg(self.user, name="etf", tracks=True, share=30)
        _cfg(self.user, name="oil", tracks=True)
        from django.urls import reverse
        html = self.client.get(reverse("asset_bots_dashboard")).content.decode()
        self.assertIn("follows account · 30%", html)
        self.assertIn("follows account · auto 70%", html)


class ThePreflightSeesTheSharesTests(TestCase):

    def _run(self):
        out = StringIO()
        call_command("preflight_live", stdout=out)
        return out.getvalue()

    def test_followers_and_their_shares_are_listed(self):
        u = _user()
        _acct(u)
        _cfg(u, name="manual", tracks=True)
        _cfg(u, name="etf", tracks=True, share=30)
        out = self._run()
        self.assertIn("follows the account · 30%", out)
        self.assertIn("follows the account · auto 70%", out)

    def test_over_allocation_is_a_blocker(self):
        u = _user()
        _acct(u)
        _cfg(u, name="a", tracks=True, share=60)
        _cfg(u, name="b", tracks=True, share=50)
        out = self._run()
        self.assertIn("more than one account", out)
        self.assertIn("110%", out)

    def test_typed_pools_past_the_account_are_worth_reading(self):
        """The 2026-09-10 state: 1,000 of pools over a 500 account, none
        following it."""
        u = _user()
        _acct(u)
        _cfg(u, name="a", capital="500")
        _cfg(u, name="b", capital="500")
        out = self._run()
        self.assertIn("together they can deploy 2.0x the money", out)
