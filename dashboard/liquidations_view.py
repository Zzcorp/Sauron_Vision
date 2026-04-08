"""Liquidation heatmap page — aggregates LiquidationEvent rows into
price buckets for visualisation."""
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache

WINDOWS = {"1h": 1, "4h": 4, "24h": 24, "7d": 168}
BUCKETS = 60

def _aggregate(symbol: str, hours: int):
    from market_data.models import LiquidationEvent
    qs = LiquidationEvent.objects.filter(
        symbol=symbol, timestamp__gte=timezone.now() - timedelta(hours=hours))
    events = list(qs.values("side","price","qty","notional_usd","timestamp"))
    if not events:
        return {"buckets": [], "stats": {"long": 0, "short": 0, "biggest": 0,
                                         "count": 0, "net": 0}}
    prices = [float(e["price"]) for e in events]
    lo, hi = min(prices), max(prices)
    if lo == hi: hi = lo + 1
    step = (hi - lo) / BUCKETS
    buckets = [{"price": lo + i*step, "long": 0.0, "short": 0.0, "count": 0}
               for i in range(BUCKETS)]
    long_tot = short_tot = biggest = 0
    for e in events:
        idx = min(BUCKETS-1, max(0, int((float(e["price"]) - lo) / step)))
        notional = float(e["notional_usd"] or 0)
        if e["side"] == "LONG":
            buckets[idx]["long"] += notional; long_tot += notional
        else:
            buckets[idx]["short"] += notional; short_tot += notional
        buckets[idx]["count"] += 1
        if notional > biggest: biggest = notional
    return {"buckets": buckets, "stats": {
        "long": round(long_tot, 2), "short": round(short_tot, 2),
        "biggest": round(biggest, 2), "count": len(events),
        "net": round(long_tot - short_tot, 2), "lo": lo, "hi": hi}}

@login_required
def liquidations_page(request):
    from market_data.models import LiquidationEvent, FundingRate
    symbol = (request.GET.get("symbol") or "BTCUSDT").upper()
    window = request.GET.get("window", "24h")
    hours = WINDOWS.get(window, 24)
    agg = _aggregate(symbol, hours)
    symbols = list(LiquidationEvent.objects.filter(
        timestamp__gte=timezone.now() - timedelta(days=7)
    ).values_list("symbol", flat=True).distinct()[:30])
    if symbol not in symbols: symbols.insert(0, symbol)
    recent = list(LiquidationEvent.objects.filter(symbol=symbol).values(
        "side","price","qty","notional_usd","timestamp")[:30])

    # Funding panel data — top symbols by recent funding activity
    funding_symbols = list(FundingRate.objects.filter(
        timestamp__gte=timezone.now() - timedelta(hours=24)
    ).values_list("symbol", flat=True).distinct()[:8])
    funding_data = []
    for sym in funding_symbols:
        rows = list(FundingRate.objects.filter(
            symbol=sym, timestamp__gte=timezone.now() - timedelta(hours=24)
        ).order_by("timestamp").values("funding_rate","mark_price","timestamp")[:200])
        if not rows: continue
        rates = [float(r["funding_rate"] or 0) for r in rows]
        cur = rates[-1]
        avg = sum(rates) / len(rates) if rates else 0
        extreme = abs(cur) >= 0.001
        sign_flips = sum(1 for i in range(1, len(rates)) if rates[i]*rates[i-1] < 0)
        funding_data.append({
            "symbol": sym,
            "current": cur,
            "current_pct": cur * 100,
            "avg_pct": avg * 100,
            "mark": float(rows[-1]["mark_price"] or 0),
            "extreme": extreme,
            "sign_flips": sign_flips,
            "spark": rates[-60:],
            "samples": len(rates),
        })
    funding_data.sort(key=lambda x: abs(x["current"]), reverse=True)

    return render(request, "dashboard/liquidations.html", {
        "page_id": "liquidations", "symbol": symbol, "window": window,
        "hours": hours, "agg": agg, "symbols": symbols, "recent": recent,
        "windows": list(WINDOWS.keys()),
        "funding_data": funding_data,
    })

@never_cache
@login_required
def liquidations_json(request):
    symbol = (request.GET.get("symbol") or "BTCUSDT").upper()
    window = request.GET.get("window", "24h")
    hours = WINDOWS.get(window, 24)
    return JsonResponse(_aggregate(symbol, hours))
