"""Position correlation analysis."""
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


def calculate_correlation_matrix(symbols, period_days=60):
    """Calculate correlation matrix between instruments using price data."""
    from market_data.models import PriceData
    from django.utils import timezone
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(days=period_days)

    # Build price series for each symbol
    series = {}
    for symbol in symbols:
        prices = PriceData.objects.filter(
            instrument__symbol=symbol,
            timeframe="1d",
            timestamp__gte=cutoff,
        ).order_by("timestamp").values_list("close", flat=True)

        if len(prices) > 10:
            series[symbol] = [float(p) for p in prices]

    if len(series) < 2:
        return {"matrix": {}, "pairs": []}

    # Align series to same length
    min_len = min(len(v) for v in series.values())
    df = pd.DataFrame({k: v[-min_len:] for k, v in series.items()})

    # Calculate returns
    returns = df.pct_change().dropna()
    if returns.empty:
        return {"matrix": {}, "pairs": []}

    # Correlation matrix
    corr = returns.corr()

    # Extract notable pairs
    pairs = []
    symbols_list = list(corr.columns)
    for i in range(len(symbols_list)):
        for j in range(i + 1, len(symbols_list)):
            val = corr.iloc[i, j]
            if not np.isnan(val):
                pairs.append({
                    "pair": f"{symbols_list[i]}/{symbols_list[j]}",
                    "correlation": round(val, 3),
                    "strength": "strong" if abs(val) > 0.7 else "moderate" if abs(val) > 0.4 else "weak",
                })

    pairs.sort(key=lambda x: abs(x["correlation"]), reverse=True)

    return {
        "matrix": {k: {k2: round(v2, 3) for k2, v2 in v.items()} for k, v in corr.to_dict().items()},
        "pairs": pairs[:20],
    }
