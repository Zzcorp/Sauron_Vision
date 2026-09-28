"""IBKR's 2,000 USD floor is read before the order, not after.

The second real order this deployment sent — a plain long on GLDM, an
87-dollar ETF, from a 500 EUR account — came back:

    Error 201: YOUR ORDER IS NOT ACCEPTED. MINIMUM OF 2000 USD (OR
    EQUIVALENT IN OTHER CURRENCIES) IS REQUIRED IN ORDER TO PURCHASE ON
    MARGIN, SELL SHORT, TRADE CURRENCY OR FUTURE.

Nothing about the order was leveraged. The account held EUR, the ETF is
quoted in USD, and a EUR balance buying a USD instrument is a USD loan —
which is margin, which the floor forbids. Below the floor an account buys
stocks and ETFs with settled cash in the instrument's own currency, and
does nothing else: no shorts, no currency, no futures, no CFDs.

The preflight now says so on the page an operator reads with a finger over
the arming button: which live configs are margin products the account
cannot trade at all, and which symbols need a currency converted first.

Run with:  python manage.py test tests.test_preflight_ibkr_floor
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _run():
    out = StringIO()
    call_command("preflight_live", stdout=out)
    return out.getvalue()


def _user(name="floor_u"):
    return User.objects.create_user(name, password="x")


def _acct(user, *, equity, currency, port=4003):
    from bot_program.models import IBKRAccount
    acct = IBKRAccount.objects.create(user=user, port=port,
                                      is_primary_for_stocks=True,
                                      is_primary_for_forex=True)
    acct.set_credentials("U1234567")
    acct.username_enc, acct.password_enc = "x", "y"
    acct.last_equity = Decimal(str(equity))
    acct.last_equity_currency = currency
    acct.last_equity_at = timezone.now() - timedelta(minutes=5)
    acct.save()
    return acct


def _cfg(user, *, asset_class, symbols, mode="live", base_currency="EUR",
         enabled=True, name=None):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name or f"c_{asset_class}",
        mode=mode, symbols=list(symbols), capital=Decimal("150"),
        base_currency=base_currency, enabled=enabled)


def _instrument(symbol, asset_class, currency):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "currency": currency, "is_active": True})
    if inst.currency != currency:
        inst.currency = currency
        inst.save(update_fields=["currency"])
    return inst


class TheFloorArithmeticTests(SimpleTestCase):

    def _floor(self, value, ccy):
        from bot_program.management.commands.preflight_live import _ibkr_floor
        return _ibkr_floor(value, ccy)

    def test_the_deployment_that_met_the_rule(self):
        self.assertEqual(self._floor(500, "EUR"), "below")

    def test_clearly_above_in_dollars(self):
        self.assertEqual(self._floor(5000, "USD"), "above")

    def test_a_band_straddling_the_floor_is_unsure_not_guessed(self):
        """1,800 EUR is 2,000 USD at one rate and not at another; the
        platform converts nothing and says so instead of picking one."""
        self.assertEqual(self._floor(1800, "EUR"), "unsure")

    def test_an_unknown_currency_is_unsure(self):
        self.assertEqual(self._floor(500, "XYZ"), "unsure")
        self.assertEqual(self._floor("garbage", "EUR"), "unsure")


class TheFloorOnThePageTests(TestCase):

    def test_a_small_account_is_told_what_it_can_and_cannot_do(self):
        u = _user()
        _acct(u, equity=500, currency="EUR")
        out = _run()
        self.assertIn("BELOW 2,000 USD", out)
        self.assertIn("cash purchases only", out)

    def test_an_armed_live_forex_config_is_a_blocker_under_the_floor(self):
        u = _user()
        _acct(u, equity=500, currency="EUR")
        _instrument("EURUSD", "forex", "USD")
        cfg = _cfg(u, asset_class="forex", symbols=("EURUSD",))
        out = _run()
        self.assertIn(f"config {cfg.id}", out)
        self.assertIn("margin product IBKR refuses", out)
        self.assertIn("Error 201", out)

    def test_a_usd_etf_on_a_eur_account_needs_a_conversion_first(self):
        """The GLDM case, named before the click — as WORTH READING, not
        a blocker: the equity reading is the base currency and cannot see
        USD cash the operator may already have converted."""
        u = _user()
        _acct(u, equity=500, currency="EUR")
        _instrument("GLDM", "etf", "USD")
        _cfg(u, asset_class="stock", symbols=("GLDM",))
        out = _run()
        self.assertIn("GLDM (USD)", out)
        self.assertIn("Convert EUR", out)
        self.assertIn("cannot see cash by currency", out)
        worth = out.split("WORTH READING:")[1] if "WORTH READING:" in out else ""
        self.assertIn("GLDM (USD)", worth)

    def test_same_currency_cash_buying_is_not_flagged(self):
        u = _user()
        _acct(u, equity=500, currency="USD")
        _instrument("GLDM", "etf", "USD")
        _cfg(u, asset_class="stock", symbols=("GLDM",), base_currency="USD")
        out = _run()
        self.assertIn("BELOW 2,000 USD", out)
        self.assertNotIn("Convert", out)
        self.assertNotIn("margin product IBKR refuses", out)

    def test_a_paper_forex_config_is_left_alone(self):
        u = _user()
        _acct(u, equity=500, currency="EUR")
        _cfg(u, asset_class="forex", symbols=("EURUSD",), mode="paper")
        out = _run()
        self.assertNotIn("margin product IBKR refuses", out)

    def test_above_the_floor_nothing_is_said_beyond_the_fact(self):
        u = _user()
        _acct(u, equity=5000, currency="USD")
        _instrument("EURUSD", "forex", "USD")
        _cfg(u, asset_class="forex", symbols=("EURUSD",), base_currency="USD")
        out = _run()
        self.assertIn("above 2,000 USD", out)
        self.assertNotIn("margin product IBKR refuses", out)

    def test_near_the_floor_is_a_warning_not_a_verdict(self):
        u = _user()
        _acct(u, equity=1800, currency="EUR")
        out = _run()
        self.assertIn("NEAR 2,000 USD", out)
        self.assertNotIn("margin product IBKR refuses", out)
