"""eToro as an opt-in primary broker (2026-09-17).

The router decides which client a symbol's order goes to. Adding a broker
there is the one change that can move real money to a new venue, so the
rule is: NOTHING changes until an operator flips a flag, and when both
IBKR and eToro are flagged for a class, eToro carries it — retiring IBKR is
the stated direction, and the router is where a direction becomes a fact.

WHAT THESE TESTS CONFRONT

  * `client_for_symbol` and `broker_name_for_symbol` must agree. The first
    is what trades; the second is what the dashboard and logs say traded.
    A router that trades on eToro while the page says IBKR is the worst
    shape a wrong answer can take.
  * The flag is read through `EtoroAccount.is_primary_for()` — the same
    method the page reads — never through a second table.
  * Missing credentials fall to PaperTrader, which `asset_engine` refuses to
    trade live against. A paper-mode config never reaches eToro at all.
  * options / cfd stay forced to IBKR: EtoroAccount has no flag for them,
    so the eToro check cannot fire, and the old rule holds unchanged.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from bot_program.engine.broker_router import (broker_name_for_symbol,
                                              client_for_symbol)
from bot_program.models import AssetBotConfig, EtoroAccount, IBKRAccount


def _instrument(symbol, asset_class):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _cfg(user, mode="live", asset_class="stock", symbols=("AAPL",)):
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=f"{mode}_{asset_class}",
        mode=mode, symbols=list(symbols), capital=Decimal("1000"),
        base_currency="EUR", enabled=True)


def _etoro(user, *, creds=True, demo=True, **flags):
    acct = EtoroAccount.objects.create(user=user, demo=demo, **flags)
    if creds:
        acct.set_credentials("k", "u")
    acct.save()
    return acct


def _kind(client) -> str:
    return type(client).__name__


class NothingChangesUntilAFlagIsFlippedTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("rt_u", password="x")
        _instrument("AAPL", "stock")
        self.live = _cfg(self.user)

    def test_keys_alone_route_nowhere_new(self):
        _etoro(self.user)                       # creds, no flags
        client = client_for_symbol(self.user, "AAPL", self.live)
        self.assertNotEqual(_kind(client), "EtoroTrader")
        self.assertNotEqual(broker_name_for_symbol(self.user, "AAPL",
                                                   self.live), "etoro")

    def test_the_flag_routes_a_live_config_to_etoro(self):
        _etoro(self.user, is_primary_for_stocks=True)
        client = client_for_symbol(self.user, "AAPL", self.live)
        self.assertEqual(_kind(client), "EtoroTrader")
        self.assertEqual(broker_name_for_symbol(self.user, "AAPL", self.live),
                         "etoro")

    def test_the_demo_flag_decides_the_world_not_the_config(self):
        """A row flagged Demo goes to eToro's demo even for a live-mode
        config — OANDA practice's rule in shape. Not the keys' rule: one
        pair opens both worlds (measured 2026-09-23), so the flag alone
        picks the world, and unticking it sends the same pair live."""
        _etoro(self.user, is_primary_for_stocks=True, demo=True)
        self.assertEqual(client_for_symbol(self.user, "AAPL", self.live).env,
                         "demo")
        EtoroAccount.objects.filter(user=self.user).update(demo=False)
        self.user = User.objects.get(pk=self.user.pk)   # drop the cached row
        self.assertEqual(client_for_symbol(self.user, "AAPL", self.live).env,
                         "live")

    def test_a_paper_config_never_reaches_etoro(self):
        _etoro(self.user, is_primary_for_stocks=True)
        paper = _cfg(self.user, mode="paper")
        self.assertEqual(_kind(client_for_symbol(self.user, "AAPL", paper)),
                         "PaperTrader")
        self.assertEqual(broker_name_for_symbol(self.user, "AAPL", paper),
                         "paper")


class TheFlagWinsOverIbkrTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("rt_both", password="x")
        _instrument("AAPL", "stock")
        self.live = _cfg(self.user)
        ib = IBKRAccount.objects.create(user=self.user, port=4003,
                                        is_primary_for_stocks=True)
        ib.set_credentials("U1")
        ib.save()

    def test_etoro_beats_ibkr_when_both_are_flagged(self):
        _etoro(self.user, is_primary_for_stocks=True)
        client = client_for_symbol(self.user, "AAPL", self.live)
        self.assertEqual(_kind(client), "EtoroTrader")
        self.assertEqual(broker_name_for_symbol(self.user, "AAPL", self.live),
                         "etoro")

    def test_without_the_etoro_flag_ibkr_still_carries_it(self):
        """The old behaviour, byte for byte: the IBKR override is untouched
        for anyone who has not flipped an eToro flag."""
        _etoro(self.user)                       # creds, no flags
        self.assertEqual(broker_name_for_symbol(self.user, "AAPL", self.live),
                         "ibkr")


class TheSafetyFallbacksHoldTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("rt_safe", password="x")
        _instrument("AAPL", "stock")
        self.live = _cfg(self.user)

    def test_a_flag_without_keys_is_paper_which_the_engine_refuses(self):
        """The flag says 'eToro carries stocks'; the row has no keys. The
        router hands back PaperTrader, and asset_engine refuses to trade a
        live config against a PaperTrader — loudly, as a skip. Money does
        not move on a half-configured broker."""
        _etoro(self.user, creds=False, is_primary_for_stocks=True)
        self.assertEqual(_kind(client_for_symbol(self.user, "AAPL",
                                                 self.live)), "PaperTrader")

    def test_options_and_cfd_still_go_to_ibkr(self):
        """No eToro flag exists for either, so the eToro check cannot fire
        and the forced-IBKR rule stands unchanged."""
        _instrument("SPY_OPT", "options")
        _etoro(self.user, is_primary_for_stocks=True,
               is_primary_for_forex=True, is_primary_for_commodity=True,
               is_primary_for_crypto=True)
        self.assertEqual(broker_name_for_symbol(
            self.user, "SPY_OPT", _cfg(self.user, asset_class="options",
                                       symbols=("SPY_OPT",))), "ibkr")

    def test_is_primary_for_maps_etf_and_index_to_stocks(self):
        acct = _etoro(self.user, is_primary_for_stocks=True)
        for cls in ("stock", "etf", "index"):
            self.assertTrue(acct.is_primary_for(cls), cls)
        for cls in ("forex", "commodity", "crypto", "options", "cfd"):
            self.assertFalse(acct.is_primary_for(cls), cls)


class ThePageShowsWhoCarriesWhatTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("rt_page", password="x")
        self.admin = User.objects.create_superuser("rt_admin", "a@x", "x")

    def test_the_column_reads_the_router_s_own_method(self):
        _etoro(self.user, is_primary_for_stocks=True,
               is_primary_for_crypto=True)
        self.client.force_login(self.user)
        body = self.client.get(reverse("brokers_page")).content.decode()
        self.assertIn("Primary for", body)
        row = body[body.index("eToro"):body.index("Saxo Bank")]
        self.assertIn("stock", row)
        self.assertIn("crypto", row)
        self.assertNotIn(">forex<", row)

    def test_saving_reads_the_four_checkboxes(self):
        from unittest import mock
        self.client.force_login(self.admin)
        with mock.patch("dashboard.views_brokers.etoro_probe",
                        return_value=("ok", "200")):
            self.client.post(reverse("hq_save_etoro"), {
                "target_username": "rt_page", "etoro_api_key": "k",
                "etoro_user_key": "u", "demo": "on",
                "primary_stocks": "on", "primary_crypto": "on"})
        acct = EtoroAccount.objects.get(user=self.user)
        self.assertTrue(acct.is_primary_for_stocks)
        self.assertTrue(acct.is_primary_for_crypto)
        self.assertFalse(acct.is_primary_for_forex)
        self.assertFalse(acct.is_primary_for_commodity)

    def test_an_omitted_checkbox_turns_the_flag_off(self):
        """Unchecked = absent = off. A re-save that omits a flag must clear
        it, or a flag flipped once would be impossible to un-flip from the
        page."""
        from unittest import mock
        _etoro(self.user, is_primary_for_stocks=True)
        self.client.force_login(self.admin)
        with mock.patch("dashboard.views_brokers.etoro_probe",
                        return_value=("ok", "200")):
            self.client.post(reverse("hq_save_etoro"), {
                "target_username": "rt_page", "etoro_api_key": "k",
                "etoro_user_key": "u", "demo": "on"})
        self.assertFalse(EtoroAccount.objects.get(user=self.user)
                         .is_primary_for_stocks)
