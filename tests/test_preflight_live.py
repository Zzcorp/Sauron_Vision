"""The command an operator runs with a finger over the arming button.

Everything it checks is something that fails QUIETLY and in the expensive
direction. The two that matter most are about the denominator:

`AssetBotConfig.capital` is what the entire per-config risk stack divides by —
sizing divides the risk budget by it, the daily-loss floor is a percentage of
it, the drawdown curve starts at it — and it is a number typed into a form
that arming live never compares to anything. A pool declared LARGER than the
account loosens every limit the operator believes they set: 2% of a declared
100,000 against a real 20,000 is a 10% daily loss.

And `base_currency` on the config defaults to "USD" while a UK ISA is GBP and
the book defaults to EUR. This codebase has no FX conversion anywhere by
design, so three currencies can meet in one risk calculation with nothing
making them disagree out loud.

Run with:  python manage.py test tests.test_preflight_live
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone


def _run(**kw):
    out = StringIO()
    call_command("preflight_live", stdout=out, **kw)
    return out.getvalue()


def _user(name="pf"):
    return User.objects.create_user(name, password="x")


def _acct(user, *, port=4004, account_id="DU1234567", equity=None,
          currency="", equity_age_h=1.0, login=True, **flags):
    from bot_program.models import IBKRAccount
    acct = IBKRAccount.objects.create(user=user, port=port, **flags)
    acct.set_credentials(account_id)
    if login:
        # Truthy is all `has_login` inspects; no need to spend Fernet here.
        acct.username_enc, acct.password_enc = "x", "y"
    if equity is not None:
        acct.last_equity = Decimal(str(equity))
        acct.last_equity_currency = currency
        acct.last_equity_at = timezone.now() - timedelta(hours=equity_age_h)
    acct.save()
    return acct


def _cfg(user, *, mode="live", asset_class="stock", name="starter",
         capital="10000", base_currency="USD", symbols=("AAPL",),
         enabled=True):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode=mode,
        symbols=list(symbols), capital=Decimal(capital),
        base_currency=base_currency, enabled=enabled)


def _pin(user, pin="1234"):
    from django.contrib.auth.hashers import make_password
    from portfolio.trader_profile import TraderProfile
    prof, _ = TraderProfile.objects.get_or_create(user=user)
    prof.access_pin_hash = make_password(pin)
    prof.save(update_fields=["access_pin_hash"])
    return prof


def _bars(symbol="AAPL", *, age_hours=2.0, n=5):
    from instruments.models import Instrument
    from market_data.models import PriceData
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": "stock"})
    newest = timezone.now() - timedelta(hours=age_hours)
    for i in range(n):
        PriceData.objects.update_or_create(
            instrument=inst, timeframe="4h",
            timestamp=newest - timedelta(hours=4 * i),
            defaults={"open": 1, "high": 2, "low": 1, "close": 1,
                      "volume": 10, "source": "test"})
    return inst


class ItWritesNothingTests(TestCase):
    """It runs on a funded box while the operator is nervous. It must not be
    one of the things that can change the situation it is describing — and in
    particular it must make NO broker round trip: a network dependency in
    front of an arming decision is the wrong place for one."""

    def test_it_changes_no_row(self):
        from bot_program.models import AssetBotConfig, IBKRAccount
        u = _user()
        acct = _acct(u, equity=5000, currency="GBP")
        cfg = _cfg(u)
        before = (AssetBotConfig.objects.get(pk=cfg.pk).extras,
                  IBKRAccount.objects.get(pk=acct.pk).last_sync,
                  IBKRAccount.objects.get(pk=acct.pk).last_equity)
        _run()
        after = (AssetBotConfig.objects.get(pk=cfg.pk).extras,
                 IBKRAccount.objects.get(pk=acct.pk).last_sync,
                 IBKRAccount.objects.get(pk=acct.pk).last_equity)
        self.assertEqual(before, after)

    def test_it_makes_no_broker_call(self):
        """`broker_equity` would take a data session and CACHE into extras.
        The preflight reads the columns sync_broker_account already wrote."""
        from unittest.mock import patch

        u = _user()
        _acct(u, equity=5000, currency="GBP")
        _cfg(u)
        with patch("bot_program.engine.ibkr_sessions.acquire_trader") as acq:
            _run()
        acq.assert_not_called()

    def test_it_survives_an_empty_platform(self):
        """No account, no configs, no components — and that is exactly when
        somebody reaches for it."""
        out = _run()
        self.assertIn("PREFLIGHT", out)
        self.assertIn("BLOCKERS", out)


class TheDenominatorIsCheckedAgainstTheAccountTests(TestCase):

    def test_a_pool_larger_than_the_account_is_a_blocker_with_its_multiple(self):
        u = _user()
        _acct(u, equity=2000, currency="USD")
        _cfg(u, capital="10000", base_currency="USD")
        _pin(u)
        _bars()
        out = _run()
        self.assertIn("POOL EXCEEDS THE ACCOUNT", out)
        self.assertIn("5.0x", out)
        self.assertIn("looser than it reads", out)

    def test_a_pool_inside_the_account_is_not_flagged(self):
        u = _user()
        _acct(u, equity=50000, currency="USD")
        _cfg(u, capital="10000", base_currency="USD")
        _pin(u)
        _bars()
        out = _run()
        self.assertNotIn("POOL EXCEEDS", out)

    def test_a_currency_mismatch_is_a_blocker(self):
        """The ISA case: the config's base_currency defaults to USD and the
        account reads in GBP. Nothing in this codebase converts."""
        u = _user()
        _acct(u, equity=50000, currency="GBP")
        _cfg(u, capital="10000", base_currency="USD")
        _pin(u)
        _bars()
        out = _run()
        self.assertIn("CURRENCY MISMATCH", out)
        self.assertIn("nothing here converts", out)

    def test_matching_currencies_are_not_flagged(self):
        u = _user()
        _acct(u, equity=50000, currency="GBP")
        _cfg(u, capital="10000", base_currency="GBP")
        _pin(u)
        _bars()
        out = _run()
        self.assertNotIn("CURRENCY MISMATCH", out)

    def test_an_unlabelled_reading_is_worth_reading_not_a_blocker(self):
        """A currency-less reading cannot prove a mismatch, so it must not
        assert one — but it is exactly the state this platform must not
        silently accept either."""
        u = _user()
        _acct(u, equity=50000, currency="")
        _cfg(u, capital="10000", base_currency="USD")
        _pin(u)
        _bars()
        out = _run()
        self.assertNotIn("CURRENCY MISMATCH", out)
        self.assertIn("carries no", out)

    def test_a_paper_config_is_not_measured_against_the_account(self):
        """Only live configs are the question. A paper pool of any size is a
        simulation and flagging it would train the operator to ignore this."""
        u = _user()
        _acct(u, equity=100, currency="USD")
        _cfg(u, mode="paper", capital="10000", base_currency="USD")
        _pin(u)
        out = _run()
        self.assertNotIn("POOL EXCEEDS", out)
        self.assertIn("every config is in paper mode", out)


class ThePortDecidesAndAnUnknownPortIsNotSafeTests(TestCase):

    def test_a_known_paper_port_is_labelled_paper(self):
        u = _user()
        _acct(u, port=4004)
        out = _run()
        self.assertIn("PAPER", out)

    def test_a_known_live_port_is_labelled_live(self):
        u = _user()
        _acct(u, port=4003)
        out = _run()
        self.assertIn("LIVE", out)

    def test_an_unshipped_port_is_a_blocker_not_a_default_to_paper(self):
        """None is not paper. An operator who typed 7946 for 7496 is in a
        state the platform cannot classify, and a mistake in that direction
        sends a real order to a real account."""
        u = _user()
        _acct(u, port=7946)
        out = _run()
        self.assertIn("UNKNOWN PORT", out)
        self.assertIn("cannot tell paper from live", out)

    def test_a_live_port_that_never_connected_is_a_blocker(self):
        u = _user()
        _acct(u, port=4003)
        out = _run()
        self.assertIn("did not connect", out)


class TheQuietComponentIsNamedTests(TestCase):
    """broker_account_sync does not stop the bot. It stops the bot from ever
    getting an equity reading, and tracking_freeze_reason then refuses every
    entry on an account-following pool — armed, enabled, and frozen, with no
    order and no complaint."""

    def test_a_disabled_broker_sync_is_a_blocker_that_explains_itself(self):
        from core.platform_control import PlatformComponent, seed_components
        seed_components()
        PlatformComponent.objects.filter(key="broker_account_sync").update(
            is_enabled=False)
        u = _user()
        _acct(u)
        out = _run()
        self.assertIn("broker_account_sync is OFF", out)
        self.assertIn("refuse EVERY entry", out)

    def test_a_missing_row_is_still_named(self):
        u = _user()
        _acct(u)
        out = _run()
        self.assertIn("NO ROW", out)
        self.assertIn("seed_components", out)


class ThePinIsRequiredTests(TestCase):

    def test_no_pin_is_a_blocker(self):
        u = _user()
        _acct(u)
        out = _run()
        self.assertIn("NOT SET", out)
        self.assertIn("no trading PIN", out)

    def test_a_pin_that_is_set_is_reported_set(self):
        u = _user()
        _acct(u)
        _pin(u)
        out = _run()
        self.assertIn("TRADING PIN", out)
        self.assertNotIn("no trading PIN", out)


class ArmedConfigsMustHaveFuelTests(TestCase):

    def test_a_symbol_with_no_bars_blocks(self):
        u = _user()
        _acct(u, equity=50000, currency="USD")
        _cfg(u, symbols=("NVDA",), base_currency="USD")
        _pin(u)
        out = _run()
        self.assertIn("has no 4h bars", out)

    def test_bars_are_reported_with_their_age(self):
        u = _user()
        _acct(u, equity=50000, currency="USD")
        _cfg(u, symbols=("AAPL",), base_currency="USD")
        _pin(u)
        _bars("AAPL", age_hours=3.0)
        out = _run()
        self.assertIn("newest 4h bar", out)
        self.assertNotIn("has no 4h bars", out)

    def test_a_disarmed_live_config_is_not_checked_for_fuel(self):
        """It is not going to open anything, so a missing bar is not yet a
        blocker — flagging it would bury the ones that are."""
        u = _user()
        _acct(u, equity=50000, currency="USD")
        _cfg(u, symbols=("NVDA",), base_currency="USD", enabled=False)
        _pin(u)
        out = _run()
        self.assertNotIn("has no 4h bars", out)


class TheRoutingIsCheckedTests(TestCase):

    def test_a_live_config_whose_class_ibkr_does_not_serve_is_flagged(self):
        u = _user()
        _acct(u, equity=50000, currency="USD", is_primary_for_stocks=False)
        _cfg(u, asset_class="stock", base_currency="USD")
        _pin(u)
        _bars()
        out = _run()
        self.assertIn("IBKR is NOT primary for stock", out)

    def test_a_routed_config_is_not_flagged(self):
        u = _user()
        _acct(u, equity=50000, currency="USD", is_primary_for_stocks=True)
        _cfg(u, asset_class="stock", base_currency="USD")
        _pin(u)
        _bars()
        out = _run()
        self.assertNotIn("IBKR is NOT primary for stock", out)


class ACleanVerdictDoesNotClaimSafetyTests(TestCase):
    """The worst thing this command could do is issue an all-clear an
    operator trusts more than it deserves. It reads cached columns; it cannot
    know the Gateway is logged in right now, and it has never watched this
    code place an order at a real broker."""

    def test_a_clean_run_refuses_the_word_safe_as_a_verdict(self):
        from core.platform_control import seed_components
        seed_components()
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.all().update(is_enabled=True)
        u = _user()
        _acct(u, equity=50000, currency="GBP", is_primary_for_stocks=True)
        _cfg(u, capital="1000", base_currency="GBP")
        _pin(u)
        _bars()
        out = _run()
        self.assertIn("NO BLOCKERS FOUND", out)
        self.assertIn("not the same as safe", out)
        self.assertIn("never seen your broker answer an order", out)

    def test_blockers_are_an_ordered_list(self):
        u = _user()
        _acct(u, port=7946)
        out = _run()
        self.assertIn("do not arm until", out)
        self.assertIn("1.", out)

    def test_a_single_user_can_be_targeted(self):
        a, b = _user("pf_a"), _user("pf_b")
        _acct(a)
        _acct(b)
        out = _run(user="pf_a")
        self.assertIn("pf_a", out)
        self.assertNotIn("pf_b", out)
