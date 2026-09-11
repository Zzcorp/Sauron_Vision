"""Two more admin-page decisions as shell commands.

`follow` is the asset-bots page's Follow form: a live pool becomes a
share of the broker account, through the same `allocate_shares` the
page, the sync and the preflight answer from; it prints the plan for
every follower and writes only with `--yes` (the page asks the PIN).
`bot on|off` is the admin page's toggle, with the page's rule: stopping
is frictionless, arming a live config takes `--yes`.

Run with:  python manage.py test tests.test_follow_and_bot_commands
"""
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


def _acct(user, equity="2000.53", currency="EUR"):
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


def _cfg(user, *, name, asset_class="stock", mode="live", enabled=True,
         capital="100", tracks=False, share=None, symbols=("AAPL",)):
    from bot_program.models import AssetBotConfig
    extras = {}
    if tracks:
        extras["capital_tracks_broker"] = True
    if share is not None:
        extras["account_share_pct"] = share
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode=mode,
        enabled=enabled, symbols=list(symbols), capital=Decimal(capital),
        extras=extras)


class FollowCommandTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("fw_u", password="x")
        _acct(self.user)
        self.manual = _cfg(self.user, name="manual", capital="2000.53",
                           tracks=True)          # automatic share
        self.etf = _cfg(self.user, name="commodity_etf", capital="200")
        self.fx = _cfg(self.user, name="starter_fx_majors",
                       asset_class="forex", capital="150")

    def test_plan_only_writes_nothing(self):
        out = _run("follow", str(self.etf.pk), share=20)
        self.assertIn("account reading: 2000.53 EUR", out)
        self.assertIn("[%d] commodity_etf" % self.etf.pk, out)
        self.assertIn("20%", out)
        self.assertIn("400.11", out)             # 20% of 2000.53
        self.assertIn("auto 80%", out)           # the manual pool's new share
        self.assertIn("1600.42", out)
        self.assertIn("plan only", out)
        self.etf.refresh_from_db()
        self.assertEqual(float(self.etf.capital), 200.0)
        self.assertNotIn("capital_tracks_broker", self.etf.extras)

    def test_yes_writes_the_share_like_the_page(self):
        out = _run("follow", str(self.etf.pk), share=20, yes=True)
        self.assertIn("follows the account at 20%", out)
        self.etf.refresh_from_db()
        self.assertTrue(self.etf.extras["capital_tracks_broker"])
        self.assertEqual(self.etf.extras["account_share_pct"], 20)
        self.assertEqual(float(self.etf.capital), 400.11)
        # And the sync keeps it there: the manual pool re-splits to 80%.
        from bot_program.tasks import _follow_the_account
        _follow_the_account(self.user, 2000.53, "EUR")
        self.manual.refresh_from_db()
        self.assertEqual(float(self.manual.capital), 1600.42)

    def test_over_allocation_is_refused_with_the_reason(self):
        _cfg(self.user, name="big", tracks=True, share=90)
        with self.assertRaises(CommandError) as ctx:
            _run("follow", str(self.etf.pk), share=20, yes=True)
        self.assertIn("over-allocate", str(ctx.exception))
        self.etf.refresh_from_db()
        self.assertNotIn("capital_tracks_broker", self.etf.extras)

    def test_a_paper_pool_follows_nothing(self):
        paper = _cfg(self.user, name="research", mode="paper")
        with self.assertRaises(CommandError) as ctx:
            _run("follow", str(paper.pk), yes=True)
        self.assertIn("paper", str(ctx.exception))

    def test_bad_share_and_missing_config(self):
        with self.assertRaises(CommandError):
            _run("follow", str(self.etf.pk), share=0)
        with self.assertRaises(CommandError):
            _run("follow", str(self.etf.pk), share=101)
        with self.assertRaises(CommandError):
            _run("follow", "999999")

    def test_no_reading_means_run_the_sync(self):
        from bot_program.models import IBKRAccount
        IBKRAccount.objects.all().delete()
        with self.assertRaises(CommandError) as ctx:
            _run("follow", str(self.etf.pk), yes=True)
        self.assertIn("sync_broker_account", str(ctx.exception))

    def test_stop_keeps_the_pool(self):
        _run("follow", str(self.etf.pk), share=20, yes=True)
        out = _run("follow", str(self.etf.pk), stop=True, yes=True)
        self.assertIn("stop following", out)
        self.etf.refresh_from_db()
        self.assertNotIn("capital_tracks_broker", self.etf.extras)
        self.assertNotIn("account_share_pct", self.etf.extras)
        self.assertEqual(float(self.etf.capital), 400.11)
        out = _run("follow", str(self.fx.pk), stop=True, yes=True)
        self.assertIn("nothing to stop", out)

    def test_list_shows_followers_and_fixed_pools(self):
        out = _run("follow")
        self.assertIn("fw_u: account 2000.53 EUR, 1 follower(s)", out)
        self.assertIn("manual", out)
        self.assertIn("auto 100%", out)
        self.assertIn("commodity_etf", out)
        self.assertIn("fixed", out)


class BotCommandTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("bt_u", password="x")
        self.fx = _cfg(self.user, name="starter_fx_majors",
                       asset_class="forex", capital="150")
        self.paper = _cfg(self.user, name="research_stock", mode="paper",
                          enabled=False)

    def test_off_is_frictionless(self):
        out = _run("bot", "off", str(self.fx.pk))
        self.assertIn("DISABLED", out)
        self.fx.refresh_from_db()
        self.assertFalse(self.fx.enabled)
        out = _run("bot", "off", str(self.fx.pk))
        self.assertIn("already OFF", out)

    def test_arming_live_takes_yes(self):
        _run("bot", "off", str(self.fx.pk))
        out = _run("bot", "on", str(self.fx.pk))
        self.assertIn("Add --yes", out)
        self.fx.refresh_from_db()
        self.assertFalse(self.fx.enabled)
        out = _run("bot", "on", str(self.fx.pk), yes=True)
        self.assertIn("ENABLED", out)
        self.fx.refresh_from_db()
        self.assertTrue(self.fx.enabled)

    def test_paper_arms_without_yes(self):
        out = _run("bot", "on", str(self.paper.pk))
        self.assertIn("ENABLED", out)
        self.paper.refresh_from_db()
        self.assertTrue(self.paper.enabled)

    def test_list_and_errors(self):
        out = _run("bot", "list")
        self.assertIn("ON   [%d" % self.fx.pk, out)
        self.assertIn("OFF  [%d" % self.paper.pk, out)
        self.assertIn("forex", out)
        with self.assertRaises(CommandError):
            _run("bot", "off")
        self.assertIn("not found", _run("bot", "off", "999999"))
