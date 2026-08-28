"""One energy bet wearing three tickets.

From the 2026-08-28 briefing: "8 of 11 positions are commodities, 6 long,
and BRN/WTI/NG is one energy bet wearing three tickets... a single dollar
or growth print resolves the whole shelf at once."

That is precisely the EUR problem `theme_state` was written for — six of
twelve open positions EUR crosses, one ECB headline marking five at once —
occurring in the one asset class the gate declined to cover. Every leg
cleared every money limit, because every money limit judges a SYMBOL and a
complex is not a symbol.

The gate's stated reason for excluding everything but forex was that
"pretending a ticker names its theme would make this gate lie". That is
exactly right for equities: AAPL does not say technology. It is exactly
wrong for commodities, where BRNUSD, WTIUSD and NGUSD each name their
complex as plainly as EURUSD names its currencies — and the map is not
inferred, it is the same grouping `seed_bots.py` already uses.

Run with:  python manage.py test tests.test_commodity_themes
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


class TheComplexMapIsEnumeratedNotGuessedTests(SimpleTestCase):

    def test_the_energy_shelf_is_one_theme(self):
        from portfolio.risk_gate import COMMODITY_THEMES
        for sym in ("BRNUSD", "WTIUSD", "NGUSD"):
            self.assertEqual(COMMODITY_THEMES[sym], "energy", sym)

    def test_the_metals_split_precious_from_industrial(self):
        """Gold and copper do not move together, and pretending they do
        would refuse a legitimately diversified metals book."""
        from portfolio.risk_gate import COMMODITY_THEMES
        self.assertEqual(COMMODITY_THEMES["XAUUSD"], "precious")
        self.assertEqual(COMMODITY_THEMES["XAGUSD"], "precious")
        self.assertEqual(COMMODITY_THEMES["HGUSD"], "industrial_metals")

    def test_grains_and_softs_are_separate(self):
        from portfolio.risk_gate import COMMODITY_THEMES
        self.assertEqual(COMMODITY_THEMES["WHEATUSD"], "grains")
        self.assertEqual(COMMODITY_THEMES["COFFEEUSD"], "softs")

    def test_an_unmapped_symbol_does_not_participate(self):
        """Not guessed at. A symbol whose complex is not written down
        simply does not join a crowd, which keeps the gate honest about
        what it knows."""
        from portfolio.risk_gate import _commodity_legs
        self.assertEqual(_commodity_legs("MADEUPUSD", "BUY"), {})

    def test_a_long_commodity_expresses_one_leg_not_two(self):
        """Unlike a currency pair: a long Brent is long energy and nothing
        else, where a long EURUSD is long EUR AND short USD."""
        from portfolio.risk_gate import _commodity_legs
        self.assertEqual(_commodity_legs("BRNUSD", "BUY"), {"energy": 1})
        self.assertEqual(_commodity_legs("BRNUSD", "SELL"), {"energy": -1})


class TheBriefingsFindingIsNowRefusableTests(TestCase):

    def setUp(self):
        from bot_program.models import AssetBotConfig
        from portfolio.risk_gate import limits_book
        self.user = User.objects.create_user("theme_c_u", password="x")
        self.book = limits_book()
        self.book.max_theme_legs = 2
        self.book.save()
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="commodity", name="C", mode="paper",
            symbols=["BRNUSD"], capital=Decimal("100000"), enabled=True)

    def _open(self, symbol, side="BUY", asset_class="commodity"):
        from bot_program.models import AssetBotTrade
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class=asset_class, symbol=symbol,
            side=side, qty=Decimal("1"), entry_price=Decimal("100"),
            status="OPEN", paper=True, opened_at=timezone.now())

    def test_a_third_energy_leg_is_refused(self):
        """The briefing's headline, as a gate."""
        from portfolio.risk_gate import theme_state
        self._open("BRNUSD")
        self._open("WTIUSD")
        state = theme_state(self.user, symbol="NGUSD", side="BUY",
                            asset_class="commodity")
        self.assertFalse(state["ok"])
        self.assertIn("energy", state["reason"])
        self.assertIn("BRNUSD", state["reason"])
        self.assertIn("WTIUSD", state["reason"])

    def test_a_second_one_is_not(self):
        from portfolio.risk_gate import theme_state
        self._open("BRNUSD")
        state = theme_state(self.user, symbol="WTIUSD", side="BUY",
                            asset_class="commodity")
        self.assertTrue(state["ok"], state["reason"])
        self.assertEqual(state["n"], 1)

    def test_a_short_does_not_crowd_a_long(self):
        """Long Brent and short Nat Gas are not one bet — they are two
        halves of a spread, and refusing the second would refuse the
        hedge."""
        from portfolio.risk_gate import theme_state
        self._open("BRNUSD", side="BUY")
        self._open("WTIUSD", side="BUY")
        state = theme_state(self.user, symbol="NGUSD", side="SELL",
                            asset_class="commodity")
        self.assertTrue(state["ok"], state["reason"])

    def test_metals_do_not_crowd_energy(self):
        from portfolio.risk_gate import theme_state
        self._open("BRNUSD")
        self._open("WTIUSD")
        state = theme_state(self.user, symbol="XAUUSD", side="BUY",
                            asset_class="commodity")
        self.assertTrue(state["ok"], state["reason"])

    def test_a_forex_leg_does_not_crowd_a_commodity_one(self):
        """A long EUR leg and a long energy leg are not the same crowd, and
        counting them together would refuse a diversified book."""
        from bot_program.models import AssetBotConfig
        from portfolio.risk_gate import theme_state
        fx = AssetBotConfig.objects.create(
            user=self.user, asset_class="forex", name="FX", mode="paper",
            symbols=["EURUSD"], capital=Decimal("100000"), enabled=True)
        from bot_program.models import AssetBotTrade
        for sym in ("EURUSD", "EURJPY"):
            AssetBotTrade.objects.create(
                config=fx, asset_class="forex", symbol=sym, side="BUY",
                qty=Decimal("1000"), entry_price=Decimal("1.1"),
                status="OPEN", paper=True, opened_at=timezone.now())
        state = theme_state(self.user, symbol="BRNUSD", side="BUY",
                            asset_class="commodity")
        self.assertTrue(state["ok"], state["reason"])


class ForexStillWorksExactlyAsBeforeTests(TestCase):
    """The extension must not move the gate it was built for."""

    def setUp(self):
        from bot_program.models import AssetBotConfig
        from portfolio.risk_gate import limits_book
        self.user = User.objects.create_user("theme_fx_u", password="x")
        book = limits_book()
        book.max_theme_legs = 2
        book.save()
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="forex", name="FX", mode="paper",
            symbols=["EURUSD"], capital=Decimal("100000"), enabled=True)

    def _open(self, symbol, side="BUY"):
        from bot_program.models import AssetBotTrade
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class="forex", symbol=symbol, side=side,
            qty=Decimal("1000"), entry_price=Decimal("1.1"), status="OPEN",
            paper=True, opened_at=timezone.now())

    def test_a_third_long_eur_leg_is_still_refused(self):
        from portfolio.risk_gate import theme_state
        self._open("EURUSD")
        self._open("EURJPY")
        state = theme_state(self.user, symbol="EURGBP", side="BUY",
                            asset_class="forex")
        self.assertFalse(state["ok"])
        self.assertIn("EUR", state["reason"])
        self.assertIn("currency", state["reason"])

    def test_a_disagreeing_pair_still_does_not_stack(self):
        """Long EURUSD and long USDJPY disagree about USD."""
        from portfolio.risk_gate import theme_state
        self._open("EURUSD")
        state = theme_state(self.user, symbol="USDJPY", side="BUY",
                            asset_class="forex")
        self.assertTrue(state["ok"], state["reason"])


class EquitiesAreStillExcludedTests(TestCase):
    """AAPL does not say technology. Pretending a ticker names its sector
    would make the gate lie, which is worse than not covering it."""

    def test_a_stock_gets_no_theme_verdict(self):
        from portfolio.risk_gate import theme_state
        user = User.objects.create_user("theme_eq_u", password="x")
        state = theme_state(user, symbol="AAPL", side="BUY",
                            asset_class="stock")
        self.assertTrue(state["ok"])
        self.assertIn("does not name its sector", state["reason"])
