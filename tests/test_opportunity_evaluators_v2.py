"""Phase-10.2 evaluator additions: macro_trend, news source filter,
institutional_filings.

Run with:  python manage.py test tests.test_opportunity_evaluators_v2
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


# ── macro_trend ─────────────────────────────────────────────────────────────

class MacroTrendTests(TestCase):
    def _make_indicator_with_obs(self, series_id, observations):
        """observations: list of (date, value) tuples, oldest first."""
        from market_data.models import MacroIndicator, MacroObservation
        ind = MacroIndicator.objects.create(
            series_id=series_id, name=series_id, category="rate", frequency="d",
            last_value=Decimal(str(observations[-1][1])),
            last_date=observations[-1][0],
        )
        for d, v in observations:
            MacroObservation.objects.create(indicator=ind, date=d, value=Decimal(str(v)))
        return ind

    def test_rising_with_min_change_matches(self):
        from signals.opportunity_scanner import _eval_macro_trend
        # 10Y from 3.5 → 4.2 (Δ=0.7) over 30 days
        today = timezone.now().date()
        obs = [(today - timedelta(days=30 - i * 5), 3.5 + i * 0.14) for i in range(6)]
        self._make_indicator_with_obs("MT_DGS10", obs)
        result = _eval_macro_trend(
            {"series_id": "MT_DGS10", "lookback_days": 30,
             "direction": "rising", "min_change": 0.5},
            _instrument("MT1"), timezone.now(),
        )
        self.assertTrue(result["matched"])
        self.assertAlmostEqual(result["details"]["delta"], 0.7, places=2)

    def test_rising_below_min_change_no_match(self):
        from signals.opportunity_scanner import _eval_macro_trend
        today = timezone.now().date()
        obs = [(today - timedelta(days=30 - i * 5), 3.5 + i * 0.02) for i in range(6)]
        self._make_indicator_with_obs("MT_SMALL", obs)
        result = _eval_macro_trend(
            {"series_id": "MT_SMALL", "lookback_days": 30,
             "direction": "rising", "min_change": 0.5},
            _instrument("MT2"), timezone.now(),
        )
        self.assertFalse(result["matched"])

    def test_wrong_direction_no_match(self):
        from signals.opportunity_scanner import _eval_macro_trend
        today = timezone.now().date()
        # Falling indicator
        obs = [(today - timedelta(days=30 - i * 5), 5.0 - i * 0.2) for i in range(6)]
        self._make_indicator_with_obs("MT_FALL", obs)
        result = _eval_macro_trend(
            {"series_id": "MT_FALL", "lookback_days": 30, "direction": "rising"},
            _instrument("MT3"), timezone.now(),
        )
        self.assertFalse(result["matched"])

    def test_falling_with_pct_change_matches(self):
        from signals.opportunity_scanner import _eval_macro_trend
        today = timezone.now().date()
        # VIX from 30 → 18 (Δ ≈ -40%)
        obs = [(today - timedelta(days=30 - i * 5), 30 - i * 2.4) for i in range(6)]
        self._make_indicator_with_obs("MT_VIX", obs)
        result = _eval_macro_trend(
            {"series_id": "MT_VIX", "lookback_days": 30,
             "direction": "falling", "min_change_pct": 30.0},
            _instrument("MT4"), timezone.now(),
        )
        self.assertTrue(result["matched"])

    def test_insufficient_observations_no_match(self):
        from signals.opportunity_scanner import _eval_macro_trend
        from market_data.models import MacroIndicator
        MacroIndicator.objects.create(
            series_id="MT_THIN", name="x", category="x", frequency="d",
            last_value=Decimal("1"), last_date=timezone.now().date(),
        )
        result = _eval_macro_trend(
            {"series_id": "MT_THIN", "lookback_days": 30, "direction": "rising"},
            _instrument("MT5"), timezone.now(),
        )
        self.assertFalse(result["matched"])

    def test_missing_indicator_no_match(self):
        from signals.opportunity_scanner import _eval_macro_trend
        result = _eval_macro_trend(
            {"series_id": "GHOST", "lookback_days": 30, "direction": "rising"},
            _instrument("MT6"), timezone.now(),
        )
        self.assertFalse(result["matched"])


# ── News source filter (existing evaluators) ───────────────────────────────

def _seed_news(symbol, count, sentiment=0.6, source="reddit"):
    from scraping.models import NewsArticle
    rows = []
    for i in range(count):
        rows.append(NewsArticle(
            title=f"{symbol} news {i}",
            source=source,
            url=f"http://example.com/{symbol}/{source}/{i}",
            published_at=timezone.now() - timedelta(hours=i + 1),
            content_summary=f"About {symbol}",
            ai_sentiment_score=sentiment,
        ))
    from scraping.models import NewsArticle as NA
    NA.objects.bulk_create(rows)


class NewsSourcesFilterTests(TestCase):
    def test_volume_with_sources_filter_only_counts_matching_sources(self):
        from signals.opportunity_scanner import _eval_news_volume
        _seed_news("NSF1", count=4, source="reddit")
        _seed_news("NSF1", count=4, source="bloomberg")
        # Total = 8; restricted to bloomberg = 4.
        result = _eval_news_volume(
            {"keywords": ["NSF1"], "min_count": 6, "lookback_days": 2,
             "sources": ["bloomberg"]},
            _instrument("NSF1"), timezone.now(),
        )
        # Only 4 bloomberg articles; min_count=6 → no match.
        self.assertFalse(result["matched"])
        self.assertEqual(result["details"]["n"], 4)

    def test_volume_with_sources_matches_when_count_sufficient(self):
        from signals.opportunity_scanner import _eval_news_volume
        _seed_news("NSF2", count=5, source="bloomberg")
        _seed_news("NSF2", count=10, source="reddit")
        result = _eval_news_volume(
            {"keywords": ["NSF2"], "min_count": 3, "lookback_days": 2,
             "sources": ["bloomberg"]},
            _instrument("NSF2"), timezone.now(),
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["details"]["n"], 5)
        self.assertEqual(result["details"]["sources"], ["bloomberg"])

    def test_sentiment_with_sources_filter(self):
        from signals.opportunity_scanner import _eval_news_sentiment
        # Bloomberg = 0.8 (above threshold), Reddit = 0.1 (below)
        _seed_news("NSF3", count=4, sentiment=0.8, source="bloomberg")
        _seed_news("NSF3", count=10, sentiment=0.1, source="reddit")
        # Without filter: avg includes both, ~0.3
        no_filter = _eval_news_sentiment(
            {"keywords": ["NSF3"], "direction": "above",
             "threshold": 0.5, "min_count": 3, "lookback_days": 2},
            _instrument("NSF3"), timezone.now(),
        )
        # With filter to bloomberg: avg = 0.8 → matched
        with_filter = _eval_news_sentiment(
            {"keywords": ["NSF3"], "direction": "above",
             "threshold": 0.5, "min_count": 3, "lookback_days": 2,
             "sources": ["bloomberg"]},
            _instrument("NSF3"), timezone.now(),
        )
        self.assertFalse(no_filter["matched"])
        self.assertTrue(with_filter["matched"])
        self.assertAlmostEqual(with_filter["details"]["avg_sentiment"], 0.8, places=2)

    def test_no_sources_filter_keeps_default_behavior(self):
        from signals.opportunity_scanner import _eval_news_volume
        _seed_news("NSF4", count=3, source="anywhere")
        result = _eval_news_volume(
            {"keywords": ["NSF4"], "min_count": 2, "lookback_days": 2},
            _instrument("NSF4"), timezone.now(),
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["details"]["sources"], "any")


# ── institutional_filings ──────────────────────────────────────────────────

class InstitutionalFilingsTests(TestCase):
    def test_increase_filings_matches_with_min_count(self):
        from signals.opportunity_scanner import _eval_institutional_filings
        from scraping.models import InstitutionalFiling
        inst = _instrument("IF1")
        for i in range(5):
            InstitutionalFiling.objects.create(
                filing_type="13F", filer_name=f"Fund{i}",
                instrument=inst,
                filing_date=date.today() - timedelta(days=i),
                shares=10000, value=Decimal("1000000"),
                change_type="increase", change_pct=20.0,
            )
        result = _eval_institutional_filings(
            {"change_type": "increase", "min_count": 3, "lookback_days": 30},
            inst, timezone.now(),
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["details"]["n"], 5)

    def test_decrease_filings_filtered_out_when_change_type_increase(self):
        from signals.opportunity_scanner import _eval_institutional_filings
        from scraping.models import InstitutionalFiling
        inst = _instrument("IF2")
        # Only DECREASE filings exist; asking for INCREASE should no-match.
        for i in range(5):
            InstitutionalFiling.objects.create(
                filing_type="13F", filer_name=f"Fund{i}",
                instrument=inst, filing_date=date.today() - timedelta(days=i),
                shares=10000, value=Decimal("1000000"),
                change_type="decrease", change_pct=-15.0,
            )
        result = _eval_institutional_filings(
            {"change_type": "increase", "min_count": 1, "lookback_days": 30},
            inst, timezone.now(),
        )
        self.assertFalse(result["matched"])

    def test_min_value_usd_filter_excludes_small_filings(self):
        from signals.opportunity_scanner import _eval_institutional_filings
        from scraping.models import InstitutionalFiling
        inst = _instrument("IF3")
        for i in range(3):
            InstitutionalFiling.objects.create(
                filing_type="13F", filer_name=f"Small{i}",
                instrument=inst, filing_date=date.today() - timedelta(days=i),
                shares=100, value=Decimal("10000"),
                change_type="new",
            )
        # 3 small filings exist, but min_value_usd=100k excludes them all.
        result = _eval_institutional_filings(
            {"change_type": "new", "min_count": 1, "lookback_days": 30,
             "min_value_usd": 100000.0},
            inst, timezone.now(),
        )
        self.assertFalse(result["matched"])
        self.assertEqual(result["details"]["n"], 0)

    def test_outside_lookback_excluded(self):
        from signals.opportunity_scanner import _eval_institutional_filings
        from scraping.models import InstitutionalFiling
        inst = _instrument("IF4")
        InstitutionalFiling.objects.create(
            filing_type="13F", filer_name="OldFund",
            instrument=inst, filing_date=date.today() - timedelta(days=120),
            shares=10000, value=Decimal("1000000"),
            change_type="new",
        )
        result = _eval_institutional_filings(
            {"change_type": "new", "min_count": 1, "lookback_days": 30},
            inst, timezone.now(),
        )
        self.assertFalse(result["matched"])

    def test_no_change_type_filter_counts_all(self):
        from signals.opportunity_scanner import _eval_institutional_filings
        from scraping.models import InstitutionalFiling
        inst = _instrument("IF5")
        InstitutionalFiling.objects.create(
            filing_type="13F", filer_name="A", instrument=inst,
            filing_date=date.today(), shares=1000, value=Decimal("100000"),
            change_type="new",
        )
        InstitutionalFiling.objects.create(
            filing_type="13F", filer_name="B", instrument=inst,
            filing_date=date.today(), shares=1000, value=Decimal("100000"),
            change_type="increase",
        )
        result = _eval_institutional_filings(
            {"min_count": 2, "lookback_days": 30},
            inst, timezone.now(),
        )
        self.assertTrue(result["matched"])


# ── Registry coverage ─────────────────────────────────────────────────────

class RegistryCoverageV2Tests(TestCase):
    def test_phase_10_2_kinds_registered(self):
        from signals.opportunity_scanner import has_kind
        for kind in ("macro_trend", "institutional_filings"):
            self.assertTrue(has_kind(kind), f"{kind} not registered")
