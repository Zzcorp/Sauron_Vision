"""Market regime detection — trending/ranging/volatile classification."""
import numpy as np
import logging

logger = logging.getLogger(__name__)


class RegimeDetector:
    """Classify current market regime for strategy selection."""

    REGIMES = ['trending_up', 'trending_down', 'ranging', 'volatile', 'low_volatility']

    def detect(self, instrument=None, lookback_days=60):
        """Detect current market regime for an instrument or the overall market.

        Returns dict with:
            regime: str (one of REGIMES)
            confidence: float 0-1
            details: dict with supporting metrics
            recommended_strategies: list of strategy types
        """
        prices = self._get_prices(instrument, lookback_days)
        if len(prices) < 20:
            return {'regime': 'unknown', 'confidence': 0, 'details': {}}

        returns = np.diff(prices) / prices[:-1]

        # Metrics
        trend_strength = self._calculate_trend_strength(prices)
        volatility = np.std(returns) * np.sqrt(252)
        mean_vol = self._historical_avg_volatility(instrument)
        vol_ratio = volatility / mean_vol if mean_vol > 0 else 1.0

        # ADX-like trend detection
        directional_ratio = self._directional_ratio(prices)

        # Hurst exponent approximation (>0.5 = trending, <0.5 = mean-reverting)
        hurst = self._hurst_exponent(prices)

        # Classify
        regime, confidence = self._classify(
            trend_strength, vol_ratio, directional_ratio, hurst, returns
        )

        strategies = self._recommend_strategies(regime)

        return {
            'regime': regime,
            'confidence': round(confidence, 3),
            'details': {
                'trend_strength': round(trend_strength, 4),
                'volatility_annualized': round(volatility, 4),
                'vol_ratio_vs_avg': round(vol_ratio, 4),
                'directional_ratio': round(directional_ratio, 4),
                'hurst_exponent': round(hurst, 4),
                'mean_daily_return': round(float(np.mean(returns)), 6),
            },
            'recommended_strategies': strategies,
        }

    def _calculate_trend_strength(self, prices):
        """Linear regression slope normalized by price."""
        x = np.arange(len(prices))
        slope = np.polyfit(x, prices, 1)[0]
        return slope / np.mean(prices)

    def _directional_ratio(self, prices):
        """Ratio of net move to total path length (0=choppy, 1=straight line)."""
        net_move = abs(prices[-1] - prices[0])
        total_path = sum(abs(prices[i + 1] - prices[i]) for i in range(len(prices) - 1))
        return net_move / total_path if total_path > 0 else 0

    def _hurst_exponent(self, prices, max_lag=20):
        """Simplified Hurst exponent via R/S analysis."""
        lags = range(2, min(max_lag, len(prices) // 2))
        tau = []
        rs_values = []

        for lag in lags:
            returns = np.diff(prices[:lag * 2])
            if len(returns) == 0:
                continue
            mean_r = np.mean(returns)
            deviations = np.cumsum(returns - mean_r)
            r = np.max(deviations) - np.min(deviations)
            s = np.std(returns)
            if s > 0:
                rs_values.append(r / s)
                tau.append(lag)

        if len(tau) < 3:
            return 0.5  # Default to random walk

        log_tau = np.log(tau)
        log_rs = np.log(rs_values)
        hurst = np.polyfit(log_tau, log_rs, 1)[0]
        return max(0, min(1, hurst))

    def _historical_avg_volatility(self, instrument, lookback=252):
        """Get historical average volatility."""
        prices = self._get_prices(instrument, lookback)
        if len(prices) < 30:
            return 0.2  # Default 20% vol
        returns = np.diff(prices) / prices[:-1]
        return float(np.std(returns) * np.sqrt(252))

    def _classify(self, trend, vol_ratio, directional, hurst, returns):
        """Classify regime based on metrics."""
        scores = {}

        # Trending up
        if trend > 0.001 and directional > 0.3 and hurst > 0.55:
            scores['trending_up'] = (
                directional * 0.4
                + (hurst - 0.5) * 2 * 0.3
                + min(trend * 100, 1) * 0.3
            )

        # Trending down
        if trend < -0.001 and directional > 0.3 and hurst > 0.55:
            scores['trending_down'] = (
                directional * 0.4
                + (hurst - 0.5) * 2 * 0.3
                + min(abs(trend) * 100, 1) * 0.3
            )

        # Volatile
        if vol_ratio > 1.5:
            scores['volatile'] = min((vol_ratio - 1) / 2, 1) * 0.7 + (1 - directional) * 0.3

        # Low volatility
        if vol_ratio < 0.7:
            scores['low_volatility'] = (1 - vol_ratio) * 0.7 + (1 - directional) * 0.3

        # Ranging (mean-reverting)
        if hurst < 0.45 and directional < 0.3:
            scores['ranging'] = (0.5 - hurst) * 2 * 0.5 + (1 - directional) * 0.5

        if not scores:
            return 'ranging', 0.3

        best = max(scores, key=scores.get)
        return best, min(scores[best], 1.0)

    def _recommend_strategies(self, regime):
        """Recommend strategy types for current regime."""
        recommendations = {
            'trending_up': ['swing', 'position', 'momentum'],
            'trending_down': ['swing', 'position', 'hedging'],
            'ranging': ['scalp', 'intraday', 'mean_reversion'],
            'volatile': ['scalp', 'options', 'hedging'],
            'low_volatility': ['position', 'carry', 'yield'],
        }
        return recommendations.get(regime, ['swing'])

    def _get_prices(self, instrument, lookback_days):
        """Get closing prices."""
        from market_data.models import PriceData
        from django.utils import timezone
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(days=lookback_days)

        if instrument:
            qs = PriceData.objects.filter(
                instrument=instrument, timeframe='1d', timestamp__gte=cutoff
            ).order_by('timestamp').values_list('close', flat=True)
        else:
            # Use SPY/S&P 500 as market proxy
            from instruments.models import Instrument
            proxy = Instrument.objects.filter(symbol__in=['SPY', 'SPX', '^GSPC']).first()
            if not proxy:
                return np.array([])
            qs = PriceData.objects.filter(
                instrument=proxy, timeframe='1d', timestamp__gte=cutoff
            ).order_by('timestamp').values_list('close', flat=True)

        return np.array([float(p) for p in qs])
