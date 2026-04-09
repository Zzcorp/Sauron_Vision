"""Portfolio analysis — exposure, correlation matrix, drawdown."""
import math
import logging

logger = logging.getLogger(__name__)


def analyze_exposure(portfolio):
    """Analyze portfolio exposure by asset class, sector, currency.

    Returns dict with breakdowns. Tolerant to missing fields.
    """
    try:
        from portfolio.models import Position
        positions = Position.objects.filter(portfolio=portfolio, is_open=True).select_related("instrument")
    except Exception:
        return {}

    by_asset = {}
    by_sector = {}
    by_currency = {}
    total_value = 0.0
    long_value = 0.0
    short_value = 0.0

    for p in positions:
        mv = float(getattr(p, "market_value", 0) or 0)
        if mv == 0:
            continue
        total_value += abs(mv)
        if getattr(p, "side", "") in ("long", "BUY"):
            long_value += mv
        else:
            short_value += abs(mv)

        ac = getattr(p.instrument, "asset_class", "unknown")
        sec = getattr(p.instrument, "sector", "unknown") or "unknown"
        cur = getattr(p.instrument, "currency", "USD") or "USD"
        by_asset[ac] = by_asset.get(ac, 0) + abs(mv)
        by_sector[sec] = by_sector.get(sec, 0) + abs(mv)
        by_currency[cur] = by_currency.get(cur, 0) + abs(mv)

    if total_value == 0:
        return {"total": 0, "by_asset_class": {}, "by_sector": {}, "by_currency": {}}

    return {
        "total": round(total_value, 2),
        "gross": round(long_value + short_value, 2),
        "net": round(long_value - short_value, 2),
        "long_value": round(long_value, 2),
        "short_value": round(short_value, 2),
        "by_asset_class": {k: round(v / total_value, 4) for k, v in by_asset.items()},
        "by_sector": {k: round(v / total_value, 4) for k, v in by_sector.items()},
        "by_currency": {k: round(v / total_value, 4) for k, v in by_currency.items()},
    }


def calculate_correlation_matrix(portfolio, lookback_days=60):
    """Pairwise correlation matrix between open positions."""
    try:
        from portfolio.models import Position
        from signals.smc.dataframe import load_ohlcv
    except Exception:
        return {}
    try:
        positions = Position.objects.filter(portfolio=portfolio, is_open=True).select_related("instrument")
    except Exception:
        return {}

    series = {}
    for p in positions:
        sym = getattr(p.instrument, "symbol", None)
        if not sym:
            continue
        df = load_ohlcv(sym, "1d", bars=lookback_days + 5)
        if df is None or len(df) < lookback_days // 2:
            continue
        rets = df["close"].pct_change().dropna().tolist()
        if rets:
            series[sym] = rets[-lookback_days:]

    symbols = list(series.keys())
    matrix = {}
    for a in symbols:
        matrix[a] = {}
        for b in symbols:
            n = min(len(series[a]), len(series[b]))
            if n < 10:
                matrix[a][b] = None
                continue
            xa = series[a][-n:]
            xb = series[b][-n:]
            ma = sum(xa) / n
            mb = sum(xb) / n
            cov = sum((xa[i] - ma) * (xb[i] - mb) for i in range(n)) / n
            va = sum((x - ma) ** 2 for x in xa) / n
            vb = sum((x - mb) ** 2 for x in xb) / n
            if va <= 0 or vb <= 0:
                matrix[a][b] = None
            else:
                matrix[a][b] = round(cov / math.sqrt(va * vb), 3)
    return matrix


def calculate_max_drawdown(snapshots):
    """Max drawdown from a list of portfolio snapshots."""
    if not snapshots:
        return 0.0
    values = [float(getattr(s, "total_value", 0) or 0) for s in snapshots]
    if not values:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            dd = (peak - v) / peak * 100
            max_dd = max(max_dd, dd)
    return round(max_dd, 4)
