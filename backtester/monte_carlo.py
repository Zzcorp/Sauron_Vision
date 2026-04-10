"""Monte Carlo simulation for strategy outcome distribution."""
import numpy as np
import logging

logger = logging.getLogger(__name__)


def run_monte_carlo(trades, initial_capital=10000, n_simulations=10000, n_periods=252):
    """Run Monte Carlo simulation on a strategy's trade history.

    Args:
        trades: list of dicts with 'pnl_pct' key (return per trade)
        initial_capital: starting capital
        n_simulations: number of simulation paths
        n_periods: number of periods (trading days) to simulate

    Returns dict with:
        - percentiles: {5th, 25th, 50th, 75th, 95th} final values
        - probability_of_profit: % of simulations ending positive
        - probability_of_ruin: % of simulations losing >50%
        - expected_return: mean final value
        - worst_case: minimum final value
        - best_case: maximum final value
        - equity_curves: sample of 20 paths for visualization
    """
    if not trades:
        return {'error': 'no trades to simulate'}

    returns = np.array([t.get('pnl_pct', 0) / 100 for t in trades])

    if len(returns) < 5:
        return {'error': 'insufficient trades for simulation'}

    mean_return = np.mean(returns)
    std_return = np.std(returns)
    trade_frequency = min(len(returns) / 252, 1)  # trades per day

    # Generate random paths
    random_returns = np.random.choice(returns, size=(n_simulations, n_periods), replace=True)

    # Calculate equity curves
    equity_curves = initial_capital * np.cumprod(1 + random_returns, axis=1)
    final_values = equity_curves[:, -1]

    # Statistics
    percentiles = {
        'p5': round(float(np.percentile(final_values, 5)), 2),
        'p25': round(float(np.percentile(final_values, 25)), 2),
        'p50': round(float(np.percentile(final_values, 50)), 2),
        'p75': round(float(np.percentile(final_values, 75)), 2),
        'p95': round(float(np.percentile(final_values, 95)), 2),
    }

    profit_count = np.sum(final_values > initial_capital)
    ruin_count = np.sum(final_values < initial_capital * 0.5)

    # Sample paths for visualization
    sample_indices = np.random.choice(n_simulations, size=min(20, n_simulations), replace=False)
    sample_curves = []
    for idx in sample_indices:
        curve = equity_curves[idx]
        # Downsample to ~50 points for JSON
        step = max(1, len(curve) // 50)
        sample_curves.append([round(float(v), 2) for v in curve[::step]])

    return {
        'n_simulations': n_simulations,
        'n_periods': n_periods,
        'initial_capital': initial_capital,
        'percentiles': percentiles,
        'expected_return_pct': round(float((np.mean(final_values) / initial_capital - 1) * 100), 2),
        'probability_of_profit': round(float(profit_count / n_simulations * 100), 2),
        'probability_of_ruin': round(float(ruin_count / n_simulations * 100), 2),
        'worst_case': round(float(np.min(final_values)), 2),
        'best_case': round(float(np.max(final_values)), 2),
        'mean_final_value': round(float(np.mean(final_values)), 2),
        'std_final_value': round(float(np.std(final_values)), 2),
        'sample_curves': sample_curves,
        'trade_stats': {
            'mean_return_pct': round(float(mean_return * 100), 4),
            'std_return_pct': round(float(std_return * 100), 4),
            'n_trades_used': len(returns),
        }
    }
