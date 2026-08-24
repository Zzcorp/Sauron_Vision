"""Risk engine — VaR, stress testing, and risk metrics."""
import numpy as np
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


class RiskEngine:
    """Portfolio risk calculations."""

    def __init__(self, portfolio):
        self.portfolio = portfolio
        # calculate_risk_metrics and calculate_var both ask for the same
        # 252-day weighted return series; without this memo one page
        # render executed the identical multi-month PriceData scan twice.
        self._returns_cache = {}

    def calculate_var(self, confidence=0.95, horizon_days=1, method="historical"):
        """Calculate Value-at-Risk.

        Methods: 'historical', 'parametric', 'monte_carlo'
        Returns dict with var_amount, var_pct, method, confidence, horizon
        """
        positions = self._get_positions()
        if not positions:
            return {"var_amount": 0, "var_pct": 0, "method": method}

        returns = self._get_position_returns(positions, lookback_days=252)
        if len(returns) < 30:
            return {
                "var_amount": 0,
                "var_pct": 0,
                "method": method,
                "note": "insufficient data",
            }

        portfolio_value = float(self.portfolio.current_value)

        if method == "historical":
            var_pct = self._historical_var(returns, confidence, horizon_days)
        elif method == "parametric":
            var_pct = self._parametric_var(returns, confidence, horizon_days)
        elif method == "monte_carlo":
            var_pct = self._monte_carlo_var(returns, confidence, horizon_days)
        else:
            var_pct = self._historical_var(returns, confidence, horizon_days)

        return {
            "var_amount": round(portfolio_value * abs(var_pct), 2),
            "var_pct": round(var_pct * 100, 4),
            "method": method,
            "confidence": confidence,
            "horizon_days": horizon_days,
        }

    def _historical_var(self, returns, confidence, horizon):
        """Historical simulation VaR."""
        sorted_returns = np.sort(returns)
        index = int((1 - confidence) * len(sorted_returns))
        daily_var = sorted_returns[max(index, 0)]
        return daily_var * np.sqrt(horizon)

    def _parametric_var(self, returns, confidence, horizon):
        """Parametric (Gaussian) VaR."""
        from scipy.stats import norm
        mean = np.mean(returns)
        std = np.std(returns)
        z_score = norm.ppf(1 - confidence)
        daily_var = mean + z_score * std
        return daily_var * np.sqrt(horizon)

    def _monte_carlo_var(self, returns, confidence, horizon, n_simulations=10000):
        """Monte Carlo VaR."""
        mean = np.mean(returns)
        std = np.std(returns)
        simulated = np.random.normal(mean, std, (n_simulations, horizon))
        portfolio_returns = np.sum(simulated, axis=1)
        sorted_returns = np.sort(portfolio_returns)
        index = int((1 - confidence) * n_simulations)
        return sorted_returns[max(index, 0)]

    def stress_test(self, scenarios=None):
        """Run portfolio through historical crisis scenarios.

        Returns list of {scenario, impact_pct, impact_amount, details}
        """
        if scenarios is None:
            scenarios = self._default_scenarios()

        positions = self._get_positions()
        portfolio_value = float(self.portfolio.current_value)
        results = []

        for scenario in scenarios:
            impact = self._apply_scenario(positions, scenario)
            results.append({
                "name": scenario["name"],
                "description": scenario.get("description", ""),
                "impact_pct": round(impact * 100, 2),
                "impact_amount": round(portfolio_value * impact, 2),
                "portfolio_after": round(portfolio_value * (1 + impact), 2),
            })

        return results

    def _apply_scenario(self, positions, scenario):
        """Apply a stress scenario to positions."""
        total_impact = 0
        portfolio_value = float(self.portfolio.current_value)
        if portfolio_value == 0:
            return 0

        for pos in positions:
            asset_class = pos.instrument.asset_class if pos.instrument else "stock"
            shock = scenario.get("shocks", {}).get(asset_class, 0)
            position_value = float(pos.quantity * pos.current_price)

            if pos.direction.lower() in ("short",):
                position_impact = -position_value * shock / portfolio_value
            else:
                position_impact = position_value * shock / portfolio_value

            total_impact += position_impact

        return total_impact

    def _default_scenarios(self):
        """Historical crisis scenarios with asset class shocks."""
        return [
            {
                "name": "2008 Financial Crisis",
                "description": "Lehman collapse, credit freeze",
                "shocks": {
                    "stock": -0.40, "forex": -0.05, "commodity": -0.30,
                    "crypto": 0, "bond": 0.10, "index": -0.38,
                },
            },
            {
                "name": "COVID-19 Crash (Mar 2020)",
                "description": "Pandemic market crash",
                "shocks": {
                    "stock": -0.34, "forex": -0.03, "commodity": -0.25,
                    "crypto": -0.50, "bond": 0.08, "index": -0.30,
                },
            },
            {
                "name": "Dot-com Bust (2000-2002)",
                "description": "Tech bubble burst",
                "shocks": {
                    "stock": -0.49, "forex": -0.02, "commodity": 0.10,
                    "crypto": 0, "bond": 0.15, "index": -0.45,
                },
            },
            {
                "name": "Flash Crash (2010)",
                "description": "Sudden market crash and recovery",
                "shocks": {
                    "stock": -0.09, "forex": -0.01, "commodity": -0.05,
                    "crypto": 0, "bond": 0.02, "index": -0.09,
                },
            },
            {
                "name": "Rate Hike Shock",
                "description": "Aggressive Fed tightening (+200bps)",
                "shocks": {
                    "stock": -0.15, "forex": 0.05, "commodity": -0.10,
                    "crypto": -0.25, "bond": -0.12, "index": -0.15,
                },
            },
            {
                "name": "Crypto Winter",
                "description": "Crypto market collapse",
                "shocks": {
                    "stock": -0.05, "forex": 0, "commodity": -0.02,
                    "crypto": -0.80, "bond": 0.02, "index": -0.03,
                },
            },
        ]

    def calculate_risk_metrics(self):
        """Calculate comprehensive risk metrics suite."""
        positions = self._get_positions()
        returns = self._get_position_returns(positions, lookback_days=252)

        if len(returns) < 10:
            return {"note": "insufficient data for risk metrics"}

        # Calculate metrics
        daily_mean = np.mean(returns)
        daily_std = np.std(returns)
        annualized_return = daily_mean * 252
        annualized_vol = daily_std * np.sqrt(252)

        # Sharpe
        risk_free = 0.04 / 252  # ~4% annual risk-free
        sharpe = (
            (daily_mean - risk_free) / daily_std * np.sqrt(252)
            if daily_std > 0 else 0
        )

        # Sortino (downside deviation)
        downside = returns[returns < 0]
        downside_std = np.std(downside) if len(downside) > 0 else daily_std
        sortino = (
            (daily_mean - risk_free) / downside_std * np.sqrt(252)
            if downside_std > 0 else 0
        )

        # Max drawdown
        cumulative = np.cumprod(1 + returns)
        peak = np.maximum.accumulate(cumulative)
        drawdowns = (cumulative - peak) / peak
        max_dd = np.min(drawdowns)

        # Calmar
        calmar = annualized_return / abs(max_dd) if max_dd != 0 else 0

        # Omega ratio (threshold = 0)
        gains = returns[returns > 0].sum()
        losses = abs(returns[returns < 0].sum())
        omega = gains / losses if losses > 0 else float("inf")

        return {
            "sharpe_ratio": round(sharpe, 4),
            "sortino_ratio": round(sortino, 4),
            "calmar_ratio": round(calmar, 4),
            "omega_ratio": round(omega, 4),
            "max_drawdown_pct": round(max_dd * 100, 4),
            "annualized_return_pct": round(annualized_return * 100, 4),
            "annualized_volatility_pct": round(annualized_vol * 100, 4),
            "daily_mean_return_pct": round(daily_mean * 100, 6),
            "daily_std_pct": round(daily_std * 100, 6),
        }

    def _get_positions(self):
        """Get open positions."""
        from portfolio.models import Position
        return list(
            Position.objects.filter(
                portfolio=self.portfolio, closed_at__isnull=True
            ).select_related("instrument")
        )

    def _get_position_returns(self, positions, lookback_days=252):
        """Get historical daily returns for portfolio positions."""
        from market_data.models import PriceData
        from django.utils import timezone
        from datetime import timedelta

        key = (tuple(sorted(p.id for p in positions)), lookback_days)
        if key in self._returns_cache:
            return self._returns_cache[key]

        cutoff = timezone.now() - timedelta(days=lookback_days)
        all_returns = []

        for pos in positions:
            prices = PriceData.objects.filter(
                instrument=pos.instrument,
                timeframe="1d",
                timestamp__gte=cutoff,
            ).order_by("timestamp").values_list("close", flat=True)

            prices = [float(p) for p in prices]
            if len(prices) >= 2:
                returns = np.diff(prices) / prices[:-1]
                weight = float(pos.quantity * pos.current_price) / max(
                    float(self.portfolio.current_value), 1
                )
                all_returns.append(returns * weight)

        if not all_returns:
            self._returns_cache[key] = np.array([])
            return self._returns_cache[key]

        # Align lengths and sum weighted returns
        min_len = min(len(r) for r in all_returns)
        portfolio_returns = np.sum([r[-min_len:] for r in all_returns], axis=0)
        self._returns_cache[key] = portfolio_returns
        return portfolio_returns
