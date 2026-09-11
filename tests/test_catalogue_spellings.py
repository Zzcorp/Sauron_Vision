"""Spellings the first fleet-wide backfill exposed.

A wrong symbol mapping on a keyless feed returns an empty frame, not an
error — "no data found, symbol may be delisted" — which is exactly what a
delisted symbol looks like. Three of 166 symbols came back empty on
2026-09-10 and each was a spelling: BRK.B is BRK-B on Yahoo, Block renamed
SQ to XYZ on 2025-01-21, and Binance renamed MATIC to POL in 2024.

Run with:  python manage.py test tests.test_catalogue_spellings
"""
from django.test import SimpleTestCase


class TheSpellingsTests(SimpleTestCase):

    def test_berkshire_and_block_on_yahoo(self):
        from market_data.public_feed import yf_symbol
        self.assertEqual(yf_symbol("BRK.B", "stock"), "BRK-B")
        self.assertEqual(yf_symbol("SQ", "stock"), "XYZ")

    def test_matic_is_pol_on_binance(self):
        from market_data.management.commands.backfill_bars import venue_symbol
        self.assertEqual(venue_symbol("MATICUSD"), "POLUSDT")
        self.assertEqual(venue_symbol("BTCUSD"), "BTCUSDT")   # unchanged
