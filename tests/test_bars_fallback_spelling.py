"""The public-feed fallback asks Binance in Binance's spelling (2026-10-03).

paper_readiness, Saturday morning: "CRYPTO is OPEN and 9 symbol(s) have a
4h bar up to 94.7h old ... AAVEUSD, ADAUSD, ATOMUSD, AVAXUSD, DOGEUSD,
DOTUSD, MATICUSD, NEARUSD, UNIUSD". Those are the pairs the live venue
(eToro) serves no candles for, so the feed fell back to Binance — and
asked it for AAVEUSD, the catalogue's spelling, which Binance answers with
nothing. The primary path one branch up translated correctly
(test_bot_bars: "binance is asked for its own spelling"); the fallback
did not.

Run with:  python manage.py test tests.test_bars_fallback_spelling
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from tests.test_bot_bars import _cfg, _instrument, _klines, _user


class TheFallbackSpellingTests(TestCase):

    def setUp(self):
        self.user = _user("fb_u")
        for s in ("AAVEUSD", "MATICUSD"):
            _instrument(s, asset_class="crypto")
        self.cfg = _cfg(self.user, asset_class="crypto",
                        symbols=("AAVEUSD", "MATICUSD"), name="FB")

    def _feed(self):
        from bot_program.engine.binance_client import BinanceClient
        feed = BinanceClient("", "", testnet=False)
        feed._sv_public_feed = True
        feed.klines = MagicMock(return_value=_klines(2))
        return feed

    def test_a_mute_venue_s_fallback_asks_binance_for_its_own_spelling(self):
        from market_data.bot_bars import refresh_bot_bars
        from market_data.models import PriceData
        venue = MagicMock()                     # eToro: no candles for alts
        venue._sv_public_feed = False           # a venue, not the keyless feed
        venue.klines = MagicMock(return_value=[])
        feed = self._feed()
        with patch("market_data.bot_bars._client_for", return_value=venue), \
                patch("market_data.bot_bars._public_market_data_client",
                      return_value=feed):
            out = refresh_bot_bars()
        asked = {c.args[0] for c in feed.klines.call_args_list}
        self.assertEqual(asked, {"AAVEUSDT", "POLUSDT"},
                         "the catalogue's AAVEUSD and the renamed MATIC")
        self.assertEqual(out["fallback"], 4)   # 2 symbols x 2 intervals
        self.assertEqual(PriceData.objects.filter(
            instrument__symbol="AAVEUSD").count(), 4)
        self.assertEqual(PriceData.objects.filter(
            instrument__symbol="MATICUSD").count(), 4)

    def test_a_feed_that_maps_its_own_symbols_is_left_alone(self):
        from market_data.bot_bars import _fallback_rows
        feed = MagicMock()                      # Yahoo takes AAPL as AAPL
        feed.klines = MagicMock(return_value=_klines(1))
        with patch("market_data.bot_bars._public_market_data_client",
                   return_value=feed):
            rows, _src = _fallback_rows(self.cfg, "AAPL", "4h", 200)
        self.assertEqual(feed.klines.call_args.args[0], "AAPL")
        self.assertEqual(len(rows), 1)
