"""Smoke tests for SMC detectors using synthetic OHLCV.

Run with:  python manage.py test tests.test_smc_detectors
"""
from django.test import SimpleTestCase


class SmcDetectorSmokeTests(SimpleTestCase):
    def test_synthetic_data_loads(self):
        from signals.smc.dataframe import synthetic_ohlcv
        df = synthetic_ohlcv(bars=300)
        self.assertEqual(len(df), 300)
        self.assertIn("close", df.columns)
        self.assertIn("high", df.columns)

    def test_pivots_classify(self):
        from signals.smc.dataframe import synthetic_ohlcv
        from signals.smc.pivots import get_swings, classify_swings
        df = synthetic_ohlcv(bars=300)
        swings = classify_swings(get_swings(df))
        self.assertGreater(len(swings), 0)
        for s in swings:
            self.assertIn("label", s)
            self.assertIn(s["type"], ("H", "L"))

    def test_msb_detection(self):
        from signals.smc.dataframe import synthetic_ohlcv
        from signals.smc.pivots import get_swings, classify_swings
        from signals.smc.structure import detect_market_structure_breaks
        df = synthetic_ohlcv(bars=300)
        swings = classify_swings(get_swings(df))
        breaks = detect_market_structure_breaks(df, swings)
        for b in breaks:
            self.assertIn(b["type"], ("BOS_UP", "BOS_DOWN"))
            self.assertIn("choch", b)

    def test_full_scan_no_db(self):
        from signals.smc.dataframe import synthetic_ohlcv
        from signals.rules.smc_rules import scan_symbol
        df = synthetic_ohlcv(bars=300)
        cards = scan_symbol("TESTUSDT", "4h", df=df)
        # Detectors run end-to-end without errors; setup hits depend on the
        # random walk, so we only assert no exceptions and valid shape.
        for c in cards:
            self.assertIn("headline", c)
            self.assertIn("entry", c)
            self.assertIn("conviction", c)
            self.assertIn(c["direction"], ("LONG", "SHORT"))
