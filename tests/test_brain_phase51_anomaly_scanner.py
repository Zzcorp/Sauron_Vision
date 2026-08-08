"""Tests for Phase 51 — proactive anomaly scanner.

Covers:
  - detect_brain_regime_flip: emits anomaly when latest != prior; no flip → empty
  - detect_rvol_spikes: emits anomaly when an instrument has high RVOL
  - detect_narrative_price_divergence: emits when held symbol has news vs price gap
  - dedupe: same (detector, key) within DEDUPE_MINUTES is skipped
  - scan_anomalies_now: aggregates across detectors + emits observations
  - intelligence hub renders the anomalies section when anomalies exist
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _instrument(symbol="ANOM", asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _seed_bars(instrument, bars: list, end=None):
    from market_data.models import PriceData
    end = end or timezone.now()
    rows = []
    for i, b in enumerate(bars):
        o, h, lo, c, v = b
        ts = end - timedelta(days=len(bars) - i)
        rows.append(PriceData(
            instrument=instrument, timeframe="1d", timestamp=ts,
            open=Decimal(str(o)), high=Decimal(str(h)), low=Decimal(str(lo)),
            close=Decimal(str(c)), volume=int(v), source="test",
        ))
    PriceData.objects.bulk_create(rows)


# ── Detector: brain regime flip ──────────────────────────────────────────

class DetectBrainRegimeFlipTests(TestCase):
    def test_emits_anomaly_on_flip(self):
        from brain.models import BrainReport
        from brain.anomaly_scanner import detect_brain_regime_flip
        # Prior report: trending. Latest: risk_off.
        BrainReport.objects.create(regime_label="trending",
                                      regime_confidence=0.7)
        BrainReport.objects.create(regime_label="risk_off",
                                      regime_confidence=0.8)
        anoms = detect_brain_regime_flip()
        self.assertEqual(len(anoms), 1)
        a = anoms[0]
        self.assertEqual(a["from_regime"], "trending")
        self.assertEqual(a["to_regime"], "risk_off")

    def test_no_flip_no_anomaly(self):
        from brain.models import BrainReport
        from brain.anomaly_scanner import detect_brain_regime_flip
        BrainReport.objects.create(regime_label="trending", regime_confidence=0.7)
        BrainReport.objects.create(regime_label="trending", regime_confidence=0.75)
        self.assertEqual(detect_brain_regime_flip(), [])

    def test_only_one_report_no_anomaly(self):
        from brain.models import BrainReport
        from brain.anomaly_scanner import detect_brain_regime_flip
        BrainReport.objects.create(regime_label="trending", regime_confidence=0.7)
        self.assertEqual(detect_brain_regime_flip(), [])


# ── Detector: RVOL spike ─────────────────────────────────────────────────

class DetectRvolSpikesTests(TestCase):
    def test_emits_anomaly_for_high_rvol(self):
        from brain.anomaly_scanner import detect_rvol_spikes
        inst = _instrument("HVOL")
        # 20 baseline bars vol=1000, last bar vol=5000 → RVOL=5x
        bars = [(100, 100, 100, 100, 1000)] * 20 + [(100, 100, 100, 100, 5000)]
        _seed_bars(inst, bars)
        anoms = detect_rvol_spikes(threshold=2.0, period=20)
        match = [a for a in anoms if a["symbol"] == "HVOL"]
        self.assertEqual(len(match), 1)
        self.assertGreaterEqual(match[0]["ratio"], 2.0)

    def test_normal_volume_no_anomaly(self):
        from brain.anomaly_scanner import detect_rvol_spikes
        inst = _instrument("NORM")
        bars = [(100, 100, 100, 100, 1000)] * 21
        _seed_bars(inst, bars)
        anoms = detect_rvol_spikes(threshold=3.0, period=20)
        self.assertEqual([a for a in anoms if a["symbol"] == "NORM"], [])


# ── Detector: narrative-vs-price divergence ─────────────────────────────

class DetectNarrativeDivergenceTests(TestCase):
    def _hold(self, symbol):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        u, _ = User.objects.get_or_create(username="div_t",
                                            defaults={"password": "x"})
        cfg, _ = AssetBotConfig.objects.get_or_create(
            user=u, asset_class="stock", name="div_cfg",
            defaults=dict(
                enabled=True, mode="paper", symbols=[symbol],
                capital=Decimal("10000"), base_currency="USD",
                position_size_pct=2.0, max_concurrent_positions=5,
                max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
                entry_score_min=0.6, min_signals_for_entry=1,
            ),
        )
        AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol=symbol, side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"),
            stop_loss=Decimal("99"), take_profit=Decimal("103"),
            rule_name="r", paper=True, status="OPEN",
        )

    def test_bullish_news_bearish_price_emits_anomaly(self):
        from scraping.models import NewsArticle
        from brain.anomaly_scanner import detect_narrative_price_divergence
        inst = _instrument("DIVG")
        self._hold("DIVG")
        # Price flat (no movement).
        _seed_bars(inst, [(100, 100, 100, 100, 1000)] * 4)
        # 5 strongly bullish articles for DIVG.
        for i in range(5):
            NewsArticle.objects.create(
                title=f"DIVG earnings beat estimates {i}",
                source="test", url=f"http://example.com/divg/{i}",
                published_at=timezone.now() - timedelta(hours=i + 1),
                content_summary=f"Great news for DIVG",
                ai_sentiment_score=0.6,
            )
        anoms = detect_narrative_price_divergence()
        match = [a for a in anoms if a["symbol"] == "DIVG"]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["direction"], "bullish_news_bearish_price")

    def test_no_holdings_no_scan(self):
        from brain.anomaly_scanner import detect_narrative_price_divergence
        # No holdings — empty.
        self.assertEqual(detect_narrative_price_divergence(), [])


# ── Dedupe + emission ─────────────────────────────────────────────────────

class DedupeTests(TestCase):
    def test_same_key_within_window_skipped(self):
        from brain.anomaly_scanner import _emit_anomalies
        from brain.models import BrainObservation
        anom = {"detector": "test_det", "key": "k1", "text": "x"}
        n1 = _emit_anomalies([anom])
        # Re-emit immediately — should be deduped.
        n2 = _emit_anomalies([dict(anom)])
        self.assertEqual(n1, 1)
        self.assertEqual(n2, 0)
        self.assertEqual(BrainObservation.objects.filter(
            kind="anomaly_detected").count(), 1)

    def test_different_keys_both_emitted(self):
        from brain.anomaly_scanner import _emit_anomalies
        from brain.models import BrainObservation
        n = _emit_anomalies([
            {"detector": "d", "key": "k1", "text": "a"},
            {"detector": "d", "key": "k2", "text": "b"},
        ])
        self.assertEqual(n, 2)
        self.assertEqual(BrainObservation.objects.filter(
            kind="anomaly_detected").count(), 2)

    def test_missing_detector_or_key_skipped(self):
        from brain.anomaly_scanner import _emit_anomalies
        n = _emit_anomalies([
            {"detector": "", "key": "k1"},
            {"detector": "d", "key": ""},
            {"detector": "d", "key": "ok"},
        ])
        self.assertEqual(n, 1)


# ── Top-level scan ───────────────────────────────────────────────────────

class ScanAnomaliesNowTests(TestCase):
    def test_aggregates_across_detectors(self):
        from brain.models import BrainReport, BrainObservation
        from brain.anomaly_scanner import scan_anomalies_now
        # Force a regime flip so brain_regime_flip emits.
        BrainReport.objects.create(regime_label="trending", regime_confidence=0.7)
        BrainReport.objects.create(regime_label="risk_off", regime_confidence=0.8)
        result = scan_anomalies_now()
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["n_emitted"], 1)
        self.assertGreaterEqual(
            BrainObservation.objects.filter(kind="anomaly_detected").count(), 1)

    def test_no_anomalies_clean_summary(self):
        from brain.anomaly_scanner import scan_anomalies_now
        result = scan_anomalies_now()
        self.assertTrue(result["ok"])
        self.assertEqual(result["n_emitted"], 0)
        self.assertEqual(result["n_deduped"], 0)


# ── Intelligence hub surfaces anomalies ───────────────────────────────────

class IntelligenceHubAnomaliesTests(TestCase):
    def test_anomalies_section_renders(self):
        from brain.observations import record_observation
        u = User.objects.create_user(username="ih_anom", password="x")
        self.client.force_login(u)
        record_observation(
            kind="anomaly_detected",
            payload={"detector": "rvol_spike", "key": "AAPL_X",
                      "symbol": "AAPL", "text": "AAPL RVOL 4.2x spike"},
            source="anomaly_scanner",
        )
        r = self.client.get("/intelligence/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("Anomalies detected", body)
        self.assertIn("rvol_spike", body)
        self.assertIn("AAPL RVOL 4.2x spike", body)

    def test_no_anomalies_no_section(self):
        u = User.objects.create_user(username="ih_clean", password="x")
        self.client.force_login(u)
        r = self.client.get("/intelligence/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertNotIn("Anomalies detected", body)
