"""Extra context variables for the new UI blocks.
Registered in settings.TEMPLATES[0]['OPTIONS']['context_processors'].
All queries are cheap and wrapped in try/except so templates never break.
"""
from django.utils import timezone
from datetime import timedelta

def _safe(fn, default=None):
    try: return fn()
    except Exception: return default

def ui_extras(request):
    data = {
        "ui_watchlist": [],
        "ui_metrics": {},
        "ui_headband": [],
    }
    # ── Watchlist (with live quotes joined) ────────────────
    try:
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        qs = Instrument.objects.filter(is_watchlist=True, is_active=True)[:40]
        items = []
        for inst in qs:
            q = _safe(lambda: inst.live_quote, None)
            items.append({
                "symbol": inst.symbol,
                "name": inst.name,
                "asset_class": inst.asset_class,
                "last": float(q.last) if q and q.last is not None else None,
                "change_pct": float(q.change_pct) if q and q.change_pct is not None else 0.0,
                "bid": float(q.bid) if q and q.bid is not None else None,
                "ask": float(q.ask) if q and q.ask is not None else None,
                "volume": int(q.volume) if q else 0,
                "updated_at": q.updated_at.isoformat() if q and q.updated_at else None,
            })
        data["ui_watchlist"] = items
    except Exception:
        pass

    # ── Aggregate market metrics ───────────────────────────
    try:
        from market_data.models import LiveQuote
        from signals.models import Signal
        now = timezone.now()
        day_ago = now - timedelta(hours=24)
        quotes = LiveQuote.objects.select_related("instrument").all()[:400]
        gainers = losers = 0
        top_gain = top_loss = None
        total_vol = 0
        for q in quotes:
            try:
                cp = float(q.change_pct or 0)
                total_vol += int(q.volume or 0)
                if cp > 0:
                    gainers += 1
                    if not top_gain or cp > top_gain["cp"]:
                        top_gain = {"symbol": q.instrument.symbol, "cp": cp, "last": float(q.last)}
                elif cp < 0:
                    losers += 1
                    if not top_loss or cp < top_loss["cp"]:
                        top_loss = {"symbol": q.instrument.symbol, "cp": cp, "last": float(q.last)}
            except Exception:
                continue
        sig_recent = Signal.objects.filter(created_at__gte=day_ago)
        sig_bull = sig_recent.filter(direction__icontains="bull").count()
        sig_bear = sig_recent.filter(direction__icontains="bear").count()
        data["ui_metrics"] = {
            "gainers": gainers, "losers": losers,
            "top_gain": top_gain, "top_loss": top_loss,
            "total_volume": total_vol,
            "sig_bull": sig_bull, "sig_bear": sig_bear,
            "breadth": round((gainers - losers) / max(1, gainers + losers), 2),
        }
    except Exception:
        pass

    # ── Dashboard headband metrics ─────────────────────────
    try:
        from market_data.models import LiveQuote
        tracked = ["SPX", "NDX", "DXY", "VIX", "BTCUSD", "ETHUSD",
                   "XAUUSD", "XAGUSD", "CL", "US10Y", "EURUSD", "GBPUSD"]
        band = []
        for sym in tracked:
            q = LiveQuote.objects.filter(instrument__symbol__iexact=sym).first()
            if q:
                from django.utils.timesince import timesince
                band.append({
                    "symbol": sym,
                    "last": float(q.last or 0),
                    "change_pct": float(q.change_pct or 0),
                    "name": q.instrument.name or sym,
                    "asset_class": q.instrument.asset_class or "",
                    "volume": int(q.volume or 0),
                    "bid": float(q.bid) if q.bid else None,
                    "ask": float(q.ask) if q.ask else None,
                    "source": q.source or "",
                    "updated": q.updated_at.isoformat() if q.updated_at else "",
                    "updated_human": (timesince(q.updated_at) + " ago") if q.updated_at else "—",
                })
            else:
                band.append({"symbol": sym, "last": None, "change_pct": 0,
                             "name": sym, "asset_class": "", "volume": 0, "updated": ""})
        data["ui_headband"] = band
    except Exception:
        pass

    return data
