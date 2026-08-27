"""One sane-stop band for every market, calibrated for one of them.

The brain's own briefing named this the cheapest thing on the board to fix:
"the manual_take forex exit geometry". The geometry is the band.

`MIN_STOP_FRACTION = 0.002` is 0.2% of the entry price, which is a sensible
floor on a share. On EURUSD a 1.5xATR stop is about 0.30% of price in an
ordinary session and about 0.15% in a quiet one — so the quiet half of the
week fell straight THROUGH the floor and the pair silently took the
percentage fallback instead. `stop_loss_pct` defaults to 1.5%: 163 pips on
EURUSD, five times the stop the setup was built around, on a trade the
operator was told was volatility-normalised. The low-volatility crosses sat
under the floor most of the time. And the same floor refused an operator's
own 20-pip stop — the most ordinary stop in that market — as "spread and
noise".

Run with:  python manage.py test tests.test_forex_stop_geometry
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase


class TheBandBelongsToTheAssetClassTests(SimpleTestCase):

    def test_forex_has_its_own_band(self):
        from bot_program.asset_engine.risk_levels import stop_band
        lo, hi = stop_band("forex")
        self.assertLess(lo, 0.002, "the equity floor still applies to forex")
        self.assertLess(hi, 0.25, "a 25% stop is not a stop on a major")

    def test_every_other_class_keeps_todays_numbers(self):
        """A correction, not a re-tune. Nothing was wrong with these."""
        from bot_program.asset_engine.risk_levels import (
            MAX_STOP_FRACTION, MIN_STOP_FRACTION, stop_band,
        )
        for cls in ("stock", "crypto", "commodity", "options", ""):
            self.assertEqual(stop_band(cls),
                             (MIN_STOP_FRACTION, MAX_STOP_FRACTION), cls)

    def test_an_ordinary_forex_stop_is_inside_it(self):
        """20 pips on EURUSD at 1.0850 is 0.18% — under the old floor."""
        from bot_program.asset_engine.risk_levels import stop_band
        lo, hi = stop_band("forex")
        self.assertTrue(lo <= (0.0020 / 1.0850) <= hi)

    def test_a_quiet_session_atr_stop_is_inside_it(self):
        """A 1.5xATR stop on a 0.0011 four-hour ATR is 0.152% of price. It
        used to fall through the floor and become a 1.5% percentage stop."""
        from bot_program.asset_engine.risk_levels import stop_band
        lo, hi = stop_band("forex")
        self.assertTrue(lo <= (0.0011 * 1.5 / 1.0850) <= hi)

    def test_a_stop_inside_the_spread_is_still_refused(self):
        """The floor still has to do its job — one pip is not a level."""
        from bot_program.asset_engine.risk_levels import stop_band
        lo, _hi = stop_band("forex")
        self.assertGreater(lo, 0.0001 / 1.0850)

    def test_a_stop_that_is_really_a_conviction_is_still_refused(self):
        """1000 pips out, a major is not being stopped, it is being held."""
        from bot_program.asset_engine.risk_levels import stop_band
        _lo, hi = stop_band("forex")
        self.assertLess(hi, 0.10 / 1.0850)


class TheOperatorsOwnStopIsJudgedByTheirMarketTests(TestCase):

    def setUp(self):
        from bot_program.models import AssetBotConfig
        self.user = User.objects.create_user("fxgeo_u", password="x")
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="forex", name="FX", mode="paper",
            symbols=["EURUSD"], capital=Decimal("10000"), enabled=True)

    def test_a_twenty_pip_stop_on_eurusd_is_accepted(self):
        from bot_program.manual_trade import validate_stop_override
        stop, why = validate_stop_override(
            self.cfg, asset_class="forex", raw=1.0830, entry=1.0850,
            side="BUY")
        self.assertIsNone(why, why)
        self.assertAlmostEqual(stop, 1.0830)

    def test_a_sub_pip_stop_is_still_refused(self):
        from bot_program.manual_trade import validate_stop_override
        stop, why = validate_stop_override(
            self.cfg, asset_class="forex", raw=1.08499, entry=1.0850,
            side="BUY")
        self.assertIsNone(stop)
        self.assertIn("spread and noise", why)

    def test_the_refusal_names_the_market_it_applies_to(self):
        """A floor quoted as "this platform's" when it is really the equity
        one is how an operator concludes the platform cannot trade forex."""
        from bot_program.manual_trade import validate_stop_override
        _stop, why = validate_stop_override(
            self.cfg, asset_class="forex", raw=1.08499, entry=1.0850,
            side="BUY")
        self.assertIn("forex", why)

    def test_a_stock_stop_is_judged_exactly_as_before(self):
        from bot_program.asset_engine.risk_levels import MIN_STOP_FRACTION
        from bot_program.manual_trade import validate_stop_override
        _stop, why = validate_stop_override(
            self.cfg, asset_class="stock", raw=99.95, entry=100.0,
            side="BUY")
        self.assertIsNotNone(why)
        self.assertIn("stock", why)
        self.assertGreater(MIN_STOP_FRACTION, 0.05 / 100.0)


class APercentageStopSaysSoTests(TestCase):
    """A percentage stop and an ATR stop look identical on the ticket — two
    numbers — and they are not the same promise. One is this instrument's own
    volatility; the other is a default that was never asked whether it suits
    this instrument."""

    def _cfg(self, name):
        from bot_program.models import AssetBotConfig
        user = User.objects.create_user(f"fx_{name}", password="x")
        return AssetBotConfig.objects.create(
            user=user, asset_class="forex", name=name, mode="paper",
            symbols=["EURUSD"], capital=Decimal("10000"), enabled=True)

    def test_the_fallback_records_why_it_fired(self):
        from unittest.mock import patch

        from bot_program.asset_engine.risk_levels import stop_and_target
        cfg = self._cfg("FX2")
        # An ATR so large it is outside even the widened forex ceiling.
        with patch("bot_program.asset_engine.risk_levels.atr_for",
                   return_value=0.5):
            _stop, _target, meta = stop_and_target(cfg, "EURUSD", 1.0850,
                                                   "BUY")
        self.assertEqual(meta["levels_source"], "pct")
        self.assertEqual(meta["levels_fallback_reason"], "atr_out_of_band")
        self.assertIn("stop_band", meta)

    def test_an_in_band_atr_still_produces_atr_levels(self):
        from unittest.mock import patch

        from bot_program.asset_engine.risk_levels import stop_and_target
        cfg = self._cfg("FX3")
        # The quiet-session ATR that used to fall through the floor.
        with patch("bot_program.asset_engine.risk_levels.atr_for",
                   return_value=0.0011):
            stop, target, meta = stop_and_target(cfg, "EURUSD", 1.0850, "BUY")
        self.assertEqual(meta["levels_source"], "atr")
        self.assertAlmostEqual(stop, 1.0850 - 0.0011 * 1.5, places=6)
        self.assertAlmostEqual(target, 1.0850 + 0.0011 * 3.0, places=6)

    def test_the_ticket_carries_the_note(self):
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "bot_program" / "manual_trade.py"
               ).read_text(encoding="utf-8")
        self.assertIn('"levels_note": levels_note', src)
