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
import os
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
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


def _prefs(user, *, chat="1", bot_alerts=True, quiet=None):
    """The notification-preferences row — the one only the
    /notifications/settings/ form creates in production."""
    from alerts.models import UserNotificationPrefs
    p, _ = UserNotificationPrefs.objects.get_or_create(user=user)
    p.telegram_chat_id = chat
    p.receive_bot_alerts = bot_alerts
    if quiet:
        p.quiet_start, p.quiet_end = quiet
    p.save()
    return p


def _channel(user, channel):
    prof = user.trader_profile
    prof.notify_channel = channel
    prof.save(update_fields=["notify_channel"])


#: os.environ as the senders would see it — set explicitly both ways so a
#: developer's own shell cannot decide a test.
_TOKEN = {"TELEGRAM_BOT_TOKEN": "t", "DISCORD_WEBHOOK_URL": ""}
_NO_TOKEN = {"TELEGRAM_BOT_TOKEN": "", "DISCORD_WEBHOOK_URL": ""}


def _blockers(out):
    if "BLOCKERS — do not arm" not in out:
        return ""
    return out.split("BLOCKERS — do not arm")[1].split("\nWORTH READING")[0]


def _worth(out):
    if "WORTH READING:" not in out:
        return ""
    return out.split("WORTH READING:")[1]


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

    def test_a_live_port_with_no_reading_at_all_is_a_blocker(self):
        u = _user()
        _acct(u, port=4003)
        out = _run()
        self.assertIn("no equity reading has landed", out)
        self.assertIn("at all", out)

    def test_a_live_port_whose_reading_went_stale_is_a_blocker(self):
        from bot_program.management.commands.preflight_live import (
            BROKER_READING_STALE_HOURS)
        u = _user()
        _acct(u, port=4003, equity=500, currency="EUR",
              equity_age_h=BROKER_READING_STALE_HOURS + 3)
        out = _run()
        self.assertIn("no equity reading has landed", out)
        self.assertIn("Is the Gateway logged in?", out)

    def test_a_FRESH_reading_clears_it_even_when_connected_is_False(self):
        """THE BUG THIS COMMAND SHIPPED WITH, pinned.

        `connected` is written only by the TEST IBKR button and a form save,
        so it means "a socket answered once" with no expiry —
        capital_truth.broker_backed refuses to use it for exactly this reason.
        The first version made a stale False into blocker #1 on a Gateway that
        IBC had just logged into live, that `docker ps` called healthy, and
        whose equity reading printed two lines above the blocker was four
        minutes old. A reading that arrived IS the proof the socket answered.
        """
        from bot_program.models import IBKRAccount
        u = _user()
        acct = _acct(u, port=4003, equity=500, currency="EUR",
                     equity_age_h=0.05)
        self.assertFalse(IBKRAccount.objects.get(pk=acct.pk).connected)
        out = _run()
        self.assertNotIn("no equity reading has landed", out)

    def test_the_flag_is_shown_but_labelled_as_not_live_status(self):
        u = _user()
        _acct(u, port=4003, equity=500, currency="EUR", equity_age_h=0.05)
        out = _run()
        self.assertIn("last manual probe", out)
        self.assertIn("not live status", out)

    def test_a_PAPER_port_with_no_reading_is_not_a_blocker(self):
        """Proving the chain on 4004 is the step before arming, not a fault."""
        u = _user()
        _acct(u, port=4004)
        out = _run()
        self.assertNotIn("no equity reading has landed", out)


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


class CanThisPoolEvenPlaceAnOrderTests(TestCase):
    """The pool-vs-account check catches a pool that is too BIG. Nothing
    caught the other end, and the other end fails SILENTLY.

    Sizing multiplies the pool by a risk fraction, divides by the stop
    distance, and a result under one unit becomes zero — `_whole_units` says
    so itself: "int() truncation is why a live $10,000 config at 2% could not
    buy a $201 stock ... a zero qty exits the entry path with no log line."
    And before truncation there is the notional cap: 20% of the pool for
    everything but forex. A 500-unit pool holds at most 100 of notional, which
    forbids ONE share of any megacap.

    So an operator can arm a config, watch it tick forever, and never learn
    the arithmetic settled it in advance. That is the state this deployment
    was in: a 500 EUR account against seven megacaps.
    """

    def _armed(self, *, capital, price, asset_class="stock", symbol="AAPL"):
        u = _user()
        _acct(u, equity=100000, currency="USD",
              **{f"is_primary_for_{'stocks' if asset_class == 'stock' else asset_class}": True})
        _pin(u)
        cfg = _cfg(u, capital=str(capital), base_currency="USD",
                   asset_class=asset_class, symbols=(symbol,))
        inst = _bars(symbol, age_hours=1.0)
        from market_data.models import PriceData
        PriceData.objects.filter(instrument=inst, timeframe="4h").update(
            close=price)
        return u, cfg

    def test_a_pool_too_small_for_one_share_is_a_blocker(self):
        self._armed(capital=500, price=230)      # ceiling 100 < 230
        out = _run()
        self.assertIn("ONE UNIT", out)
        self.assertIn("rounds to zero", out)
        self.assertIn("tick forever", out)

    def test_the_ceiling_and_the_price_are_both_named(self):
        """An operator cannot act on "too small" — they need the two numbers
        to decide whether to fund the account or pick cheaper symbols."""
        self._armed(capital=500, price=230)
        out = _run()
        self.assertIn("230", out)
        self.assertIn("100", out)
        self.assertIn("20%", out)

    def test_a_pool_that_can_afford_a_unit_is_not_flagged(self):
        self._armed(capital=5000, price=230)     # ceiling 1000 > 230
        out = _run()
        self.assertNotIn("ONE UNIT", out)

    def test_forex_is_judged_on_its_own_cap(self):
        """20% notional on an FX major is an economically meaningless
        constraint — sizing sets that cap to 4.0 and this must use the same
        number rather than a second opinion about leverage."""
        self._armed(capital=500, price=1.08, asset_class="forex",
                    symbol="EURUSD")
        out = _run()
        self.assertNotIn("ONE UNIT", out)

    def test_a_disarmed_config_is_not_size_checked(self):
        u = _user()
        _acct(u, equity=100000, currency="USD")
        _pin(u)
        _cfg(u, capital="500", base_currency="USD", symbols=("AAPL",),
             enabled=False)
        _bars("AAPL")
        out = _run()
        self.assertNotIn("ONE UNIT", out)


class TheLeverageIsJudgedBeforeArmingTests(TestCase):
    """Section 4 reads extras['leverage'] with the engine's own rule
    (asset_engine.base.judge_order_leverage) for EVERY live config, enabled
    or not — a blocker when armed, worth reading when not — so the operator
    meets the refusal here and not at 02:00. Absent prints the adapter's
    default and blocks nothing. Section 3 prints the margin cells."""

    def _etoro_row(self, u, *, cash=None, used=0, asset_class="stock"):
        from bot_program.models import EtoroAccount
        acct = EtoroAccount.objects.create(
            user=u, demo=False, label="Main",
            is_primary_for_stocks=(asset_class == "stock"),
            is_primary_for_forex=(asset_class == "forex"))
        acct.set_credentials("k", "u")
        acct.last_equity = Decimal("100000")
        acct.last_equity_currency = "USD"
        acct.last_equity_at = timezone.now()
        if cash is not None:
            acct.last_available_cash = Decimal(str(cash))
            acct.last_used_margin = Decimal(str(used))
            acct.last_margin_at = timezone.now()
        acct.save()
        return acct

    def _own_book(self, u):
        from portfolio.models import Portfolio
        return Portfolio.objects.create(
            name=f"{u.username}_main", initial_capital=Decimal("100000"),
            current_value=Decimal("100000"),
            cash_available=Decimal("100000"), currency="USD")

    def _armed_lev(self, *, extras, cash=None, enabled=True, book=True,
                   asset_class="stock", symbol="AAPL"):
        u = _user()
        self._etoro_row(u, cash=cash, asset_class=asset_class)
        if book:
            self._own_book(u)
        _pin(u)
        cfg = _cfg(u, capital="5000", base_currency="USD",
                   asset_class=asset_class, symbols=(symbol,),
                   enabled=enabled)
        cfg.extras = extras
        cfg.save(update_fields=["extras"])
        _bars(symbol, age_hours=1.0)
        return u, cfg

    def _lev_switch(self, on):
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key="etoro_leverage_live",
            defaults={"name": "t", "category": "system", "is_enabled": on})

    def test_absent_prints_the_default_and_blocks_nothing(self):
        self._armed_lev(extras={})
        out = _run()
        self.assertIn("leverage —  (no extras['leverage']; the adapter "
                      "sends 1)", out)
        self.assertNotIn("leverage_refused", out)
        self.assertIn("margin          NEVER MEASURED", out)

    def test_above_one_with_the_switch_off_is_a_blocker_naming_the_proof(self):
        self._armed_lev(extras={"leverage": 2})
        self._lev_switch(False)
        out = _run()
        self.assertIn("etoro_leverage_live is OFF", _blockers(out))
        self.assertIn("D2b", out)

    def test_a_disabled_config_is_judged_under_worth_reading(self):
        self._armed_lev(extras={"leverage": 2}, enabled=False)
        self._lev_switch(False)
        out = _run()
        self.assertIn("etoro_leverage_live is OFF", _worth(out))
        self.assertNotIn("etoro_leverage_live is OFF", _blockers(out))

    def test_a_null_value_is_a_blocker_not_the_default(self):
        self._armed_lev(extras={"leverage": None})
        out = _run()
        self.assertIn("not a number", _blockers(out))

    def test_past_the_class_ceiling_is_a_blocker_even_with_the_switch_on(self):
        from bot_program.asset_engine.base import ORDER_LEVERAGE_CEILING
        cap = ORDER_LEVERAGE_CEILING["stock"]
        self._armed_lev(extras={"leverage": cap + 1})
        self._lev_switch(True)
        out = _run()
        self.assertIn(f"{cap}x", _blockers(out))

    def test_forex_above_five_is_a_blocker(self):
        """2a (2026-09-26): forex's ceiling is 5 == the platform cap, so 6
        is caught by the platform-cap sentence BEFORE the class table —
        this asserts that sentence. The class-ceiling sentence is pinned
        on crypto 3 in tests/test_etoro_leverage.py TheRuleTests."""
        self._armed_lev(extras={"leverage": 6}, asset_class="forex",
                        symbol="EURUSD")
        self._lev_switch(True)
        out = _run()
        self.assertIn("platform cap of 5x", _blockers(out))
        self.assertIn("not clamped", _blockers(out))

    def test_forex_at_five_is_inside_the_ceiling(self):
        """2a: forex's ceiling is 5 — inside every LIVE forex list
        (2-30; AUD/NZD 20). The class-ceiling sentence itself is pinned
        on crypto 3 in tests/test_etoro_leverage.py TheRuleTests: crypto
        (2 < the cap) is the only class whose ceiling sits under the
        platform cap, and EtoroAccount.is_primary_for carries no crypto
        key, so the preflight cannot route a crypto config to eToro."""
        self._armed_lev(extras={"leverage": 5}, asset_class="forex",
                        symbol="EURUSD", cash=100000)
        self._lev_switch(True)
        out = _run()
        self.assertNotIn("x ceiling", _blockers(out))
        self.assertNotIn("platform cap", _blockers(out))

    def test_section_three_prints_the_world_the_cells_were_read_in(self):
        """[FIX 9] (2026-09-26, round 2): §3 prints the world the sync
        stamped beside the cells' age, and — when that stamp is not this
        LIVE row's world, or was never written — the consequence on the
        same line: the headroom refuses every eToro entry on those cells
        until the sync re-reads. The cells are read, never computed."""
        from bot_program.models import EtoroAccount
        u, _cfg = self._armed_lev(extras={}, cash=1.4)
        out = _run()
        self.assertIn("available cash  1.40", out)
        self.assertIn("world unstamped; this row trades live — every eToro "
                      "entry is refused on these cells until the sync "
                      "re-reads", out)
        EtoroAccount.objects.filter(user=u).update(last_margin_world="demo")
        out = _run()
        self.assertIn("read in demo; this row trades live — every eToro "
                      "entry is refused", out)
        EtoroAccount.objects.filter(user=u).update(last_margin_world="live")
        out = _run()
        self.assertIn("h old, read in live)", out)
        self.assertNotIn("refused on these cells", out)

    def test_no_own_book_is_a_blocker_naming_setup(self):
        self._armed_lev(extras={"leverage": 2}, cash=1000, book=False)
        self._lev_switch(True)
        out = _run()
        self.assertIn("/setup/", _blockers(out))

    def test_inside_the_ceiling_with_the_switch_on_prints_the_venue_cells_and_the_book(self):
        self._armed_lev(extras={"leverage": 2}, cash=1.4)
        self._lev_switch(True)
        out = _run()
        self.assertIn("leverage 2x (extras)", out)
        self.assertIn("venue cash 1.40", out)
        self.assertIn("100,000", out)
        self.assertIn("financing", _worth(out))
        self.assertNotIn("leverage", _blockers(out))
        self.assertIn("notional ceiling", out)
        self.assertIn("available cash  1.40", out)

    def test_armed_with_no_cells_stored_is_a_blocker(self):
        self._armed_lev(extras={"leverage": 2})
        self._lev_switch(True)
        out = _run()
        self.assertIn("never been stored", _blockers(out))

    def test_a_typed_one_prints_recorded_and_blocks_nothing(self):
        self._armed_lev(extras={"leverage": 1})
        out = _run()
        self.assertIn("leverage 1 (extras) — the adapter's default, "
                      "recorded on the row", out)
        self.assertNotIn("leverage", _blockers(out))

    def test_a_config_routed_elsewhere_is_blocked_for_the_carrier(self):
        u = _user()
        _acct(u, port=4003, equity=100000, currency="USD",
              is_primary_for_stocks=True)
        self._own_book(u)
        _pin(u)
        cfg = _cfg(u, capital="5000", base_currency="USD", symbols=("AAPL",))
        cfg.extras = {"leverage": 2}
        cfg.save(update_fields=["extras"])
        _bars("AAPL", age_hours=1.0)
        self._lev_switch(True)
        out = _run()
        self.assertIn("eToro per-order", _blockers(out))


class TheRoutingIsCheckedTests(TestCase):

    def test_a_live_config_whose_class_ibkr_does_not_serve_is_flagged(self):
        u = _user()
        _acct(u, equity=50000, currency="USD", is_primary_for_stocks=False)
        _cfg(u, asset_class="stock", base_currency="USD")
        _pin(u)
        _bars()
        out = _run()
        # It named IBKR because IBKR was all it could see. The question is
        # which broker carries the class, and the answer here is none — so
        # the router falls back to the PaperTrader and the live pool books
        # simulated fills while calling itself live.
        self.assertIn("NO BROKER is primary for stock", out)
        self.assertIn("PaperTrader", out)

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
        # PORT 4003, the docker Gateway's LIVE relay. This fixture used to
        # sit on 4004 — its PAPER twin — so the "clean run" it describes was
        # a live-mode config pointed at a paper account, booking simulated
        # fills as real history. The venue check names that now, correctly,
        # so a fixture that means "nothing is wrong" has to actually be a
        # live account.
        _acct(u, port=4003, equity=50000, currency="GBP",
              is_primary_for_stocks=True)
        _cfg(u, capital="1000", base_currency="GBP")
        _pin(u)
        _bars()
        # 2026-09-23, section 7: "nothing is wrong" now includes an alert
        # that can leave the box — a token in the sender's environment and
        # a chat id on the prefs row — and a staff user for the engine's
        # own failures to reach.
        _prefs(u, chat="1")
        u.is_staff = True
        u.save(update_fields=["is_staff"])
        with mock.patch.dict(os.environ, _TOKEN):
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


class AnAlertMustBeAbleToLeaveTheBox(TestCase):
    """Section 7. Every alert ends in dispatch_notification, which hands
    the title to ONE external sender chosen by TraderProfile.notify_channel;
    the telegram one wants TELEGRAM_BOT_TOKEN in its environment and the
    per-user UserNotificationPrefs.telegram_chat_id — a row only the
    /notifications/settings/ form creates. On 2026-09-23 the operator's
    deployment had neither, every alert it had ever raised lived only in
    the bell, and preflight said nothing. The section never says
    "reachable": it reads its own process, not the workers', and sends
    nothing."""

    def _armed(self, *, enabled=True, staff=False):
        u = _user()
        _acct(u, port=4003, equity=50000, currency="GBP",
              is_primary_for_stocks=True)
        _cfg(u, capital="1000", base_currency="GBP", enabled=enabled)
        _pin(u)
        _bars()
        if staff:
            u.is_staff = True
            u.save(update_fields=["is_staff"])
        return u

    def test_the_operators_state_blocks_and_names_both_halves(self):
        self._armed()
        with mock.patch.dict(os.environ, _NO_TOKEN):
            out = _run()
        b = _blockers(out)
        self.assertIn("TELEGRAM_BOT_TOKEN is not set", b)
        self.assertIn("telegram_chat_id has no row", b)
        self.assertIn("/notifications/settings/", b)
        self.assertIn("--force-recreate worker-fast worker-slow beat web", b)
        # the name the first draft guarded, which the sender never reads
        self.assertNotIn("TELEGRAM_CHAT_ID", out)

    def test_the_same_state_with_nothing_armed_is_worth_reading(self):
        self._armed(enabled=False)
        with mock.patch.dict(os.environ, _NO_TOKEN):
            out = _run()
        self.assertNotIn("TELEGRAM_BOT_TOKEN", _blockers(out))
        self.assertIn("TELEGRAM_BOT_TOKEN is not set", _worth(out))

    def test_the_token_alone_does_not_satisfy_it(self):
        """The remedy the first draft printed — fill .env — leaves the
        sender returning False at its chat-id check."""
        self._armed()
        with mock.patch.dict(os.environ, _TOKEN):
            out = _run()
        b = _blockers(out)
        self.assertNotIn("TELEGRAM_BOT_TOKEN is not set", b)
        self.assertIn("telegram_chat_id has no row", b)

    def test_an_empty_chat_id_on_the_row_is_its_own_state(self):
        u = self._armed()
        _prefs(u, chat="")
        with mock.patch.dict(os.environ, _TOKEN):
            out = _run()
        self.assertIn("telegram_chat_id is empty", _blockers(out))
        self.assertIn("EMPTY on the prefs row", out)

    def test_configured_is_never_called_reachable(self):
        u = self._armed(staff=True)
        _prefs(u, chat="123")
        with mock.patch.dict(os.environ, _TOKEN):
            out = _run()
        self.assertNotIn("alert channel", _blockers(out))
        self.assertIn("configured in this process", out)
        self.assertIn("delivery UNVERIFIED", out)
        self.assertIn("exec worker-fast python manage.py preflight_live", out)
        seven = out.split("7. ALERT CHANNEL")[1].split("7b.")[0]
        self.assertNotIn("reachable", seven)

    def test_bot_alerts_off_blocks_because_it_is_more_silent_than_none(self):
        u = self._armed(staff=True)
        _prefs(u, chat="123", bot_alerts=False)
        with mock.patch.dict(os.environ, _TOKEN):
            out = _run()
        self.assertIn("receive_bot_alerts", _blockers(out))
        self.assertIn("bot_alerts=OFF", out)

    def test_not_staff_is_worth_reading_and_no_staff_at_all_blocks(self):
        u = self._armed(staff=False)
        _prefs(u, chat="123")
        with mock.patch.dict(os.environ, _TOKEN):
            out = _run()
        self.assertIn("is not staff", _worth(out))
        self.assertNotIn("is not staff", _blockers(out))
        self.assertIn("reported to nobody", _blockers(out))
        self.assertIn("active staff: 0", out)

    def test_a_configured_staff_user_is_who_the_engine_tells(self):
        u = self._armed(staff=True)
        _prefs(u, chat="123")
        with mock.patch.dict(os.environ, _TOKEN):
            out = _run()
        self.assertIn("with a configured channel: 1 (pf)", out)
        self.assertNotIn("reported to nobody", out)

    def test_none_blocks_with_its_own_sentence(self):
        u = self._armed(staff=True)
        _channel(u, "none")
        out = _run()
        self.assertIn("notify_channel is none", _blockers(out))
        self.assertNotIn("is not set", _blockers(out))

    @override_settings(
        EMAIL_HOST="smtp.example",
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST_USER="u")
    def test_email_needs_an_address_on_the_account(self):
        u = self._armed(staff=True)
        _channel(u, "email")
        out = _run()
        self.assertIn("user.email is empty", _blockers(out))

    @override_settings(
        EMAIL_HOST="",
        EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
    def test_email_without_a_host_names_the_console_fallback(self):
        u = self._armed(staff=True)
        _channel(u, "email")
        u.email = "a@b.c"
        u.save(update_fields=["email"])
        out = _run()
        self.assertIn("EMAIL_HOST is not set", _blockers(out))

    @override_settings(
        EMAIL_HOST="smtp.example",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_a_host_with_a_non_delivering_backend_names_the_backend(self):
        u = self._armed(staff=True)
        _channel(u, "email")
        u.email = "a@b.c"
        u.save(update_fields=["email"])
        out = _run()
        self.assertIn("EMAIL_BACKEND is django.core.mail.backends.locmem"
                      ".EmailBackend", _blockers(out))

    def test_discord_is_the_env_variable_and_nothing_else(self):
        u = self._armed(staff=True)
        _channel(u, "discord")
        with mock.patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": ""}):
            out = _run()
        self.assertIn("DISCORD_WEBHOOK_URL is not set", _blockers(out))
        with mock.patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://x"}):
            out = _run()
        self.assertNotIn("DISCORD_WEBHOOK_URL", _blockers(out))

    def test_quiet_hours_warn_with_the_window_and_never_block(self):
        from datetime import time
        u = self._armed(staff=True)
        _prefs(u, chat="123", quiet=(time(22, 0), time(7, 0)))
        with mock.patch.dict(os.environ, _TOKEN):
            out = _run()
        self.assertIn("quiet hours 22:00–07:00 UTC", _worth(out))
        self.assertNotIn("quiet hours", _blockers(out))
        self.assertIn("close-refused", _worth(out))
