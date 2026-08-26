"""Portfolio analysis — exposure, correlation matrix, drawdown."""
import math
import logging

logger = logging.getLogger(__name__)


def _position_value(p) -> float:
    """What one open Position is worth right now, in account currency.

    `current_price` when the re-pricer has been past, entry otherwise —
    the same fallback `portfolio.services` uses, so the concentration panel
    and the book value cannot disagree about what a row is worth.
    """
    px = getattr(p, "current_price", None) or getattr(p, "entry_price", None)
    try:
        return float(px or 0) * float(getattr(p, "quantity", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def analyze_exposure(portfolio):
    """Analyze portfolio exposure by asset class, sector, currency.

    Returns dict with breakdowns. Tolerant to missing fields.

    Reads the same three fields as every other consumer of this table:
    `closed_at IS NULL` for open, `direction` for the side, and
    price x quantity for the value. It previously asked for `is_open`,
    `market_value` and `side`, none of which exist on `Position` — the
    filter raised FieldError into the bare except below and the function
    returned {} on every single call. That empty dict renders as an empty
    chart with no error anywhere on the page, so a book 80% concentrated in
    one sector and the answer "you have no concentration" looked identical.
    """
    try:
        from portfolio.models import Position
        positions = list(
            Position.objects
            .filter(portfolio=portfolio, closed_at__isnull=True)
            .select_related("instrument"))
    except Exception as e:  # noqa: BLE001 — a panel must not 500 the page
        logger.warning("analyze_exposure could not read positions: %s", e)
        return {}

    by_asset = {}
    by_sector = {}
    by_currency = {}
    total_value = 0.0
    long_value = 0.0
    short_value = 0.0

    for p in positions:
        mv = _position_value(p)
        if mv == 0:
            continue
        total_value += abs(mv)
        if str(getattr(p, "direction", "") or "").lower() in ("long", "buy"):
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
        # Same field as above: `is_open` does not exist on Position, so this
        # raised FieldError and returned an empty matrix on every call.
        positions = (Position.objects
                     .filter(portfolio=portfolio, closed_at__isnull=True)
                     .select_related("instrument"))
    except Exception as e:  # noqa: BLE001
        logger.warning("correlation matrix could not read positions: %s", e)
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
