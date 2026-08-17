"""Extra context variables for the new UI blocks.
Registered in settings.TEMPLATES[0]['OPTIONS']['context_processors'].
All queries are cheap and wrapped in try/except so templates never break.
"""
from django.utils import timezone
from datetime import timedelta

def _safe(fn, default=None):
    try: return fn()
    except Exception: return default


# Headband symbols, in catalogue spelling — every entry MUST exist in
# seed_instruments' catalogue, because a symbol with no Instrument row can
# only ever render the em-dash and its click 404s. The first version used
# exchange shorthand (SPX, CL, ZC...) plus six bond tickers and BNBUSD,
# none of which any seeder creates; a test now pins membership.
HEADBAND_SYMBOLS = [
    "SPX500", "NSDQ100", "DJ30", "RUSSELL2000",
    "FTSE100", "DAX40", "NIKKEI225", "HANGSENG", "STOXX50",
    "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD",
    "DOGEUSD", "ADAUSD", "AVAXUSD", "LINKUSD", "DOTUSD",
    "DXY", "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
    "AUDUSD", "NZDUSD", "USDCAD", "EURGBP", "EURJPY",
    "XAUUSD", "XAGUSD", "WTIUSD", "NGUSD", "HGUSD",
    "XPTUSD", "XPDUSD", "CORNUSD", "WHEATUSD", "COFFEEUSD",
]

def _recent_closes(inst_id, n=12):
    """Last n closes, oldest-first — daily bars when they exist, 1h bars
    otherwise. The fallback matters: bot bars are written at 1h/4h and the
    watchlist pass mirrors that, so daily-only sparklines were blank for
    exactly the instruments the operator starred."""
    from market_data.models import PriceData
    for tf in ("1d", "1h"):
        rows = list(PriceData.objects.filter(
            instrument_id=inst_id, timeframe=tf)
            .order_by("-timestamp").values_list("close", flat=True)[:n])
        if len(rows) >= 2:
            return [float(c) for c in reversed(rows)]
    return []


def _headband_sparks():
    """{symbol: {"spark": [...], "min": x, "max": y}} for the headband,
    cached for 5 minutes — ~38 symbols x up to 2 bar queries is too much
    to pay on every request for a chart that moves daily."""
    from django.core.cache import cache
    sparks = cache.get("hb:sparks")
    if sparks is not None:
        return sparks
    from instruments.models import Instrument
    sparks = {}
    insts = {i.symbol.upper(): i.id for i in Instrument.objects.filter(
        symbol__in=HEADBAND_SYMBOLS, is_active=True)}
    for sym in HEADBAND_SYMBOLS:
        inst_id = insts.get(sym.upper())
        if inst_id is None:
            continue
        closes = _recent_closes(inst_id)
        if len(closes) >= 2:
            sparks[sym] = {"spark": closes,
                           "min": min(closes), "max": max(closes)}
    cache.set("hb:sparks", sparks, 300)
    return sparks


def ui_extras(request):
    data = {
        "ui_watchlist": [],
        "ui_metrics": {},
        "ui_headband": [],
    }
    # ── Watchlist (with live quotes + 12-bar sparkline) ──
    try:
        from instruments.models import Instrument
        from market_data.models import PriceData
        qs = list(Instrument.objects.filter(is_watchlist=True, is_active=True)[:40])
        # Bulk-fetch last 12 daily closes for all watchlist instruments in
        # one query, then group by instrument id to avoid N+1.
        inst_ids = [i.id for i in qs]
        spark_rows = list(
            PriceData.objects.filter(
                instrument_id__in=inst_ids, timeframe="1d",
            ).order_by("instrument_id", "-timestamp")
            .values("instrument_id", "timestamp", "close")[:len(inst_ids) * 12]
        )
        spark_by_inst: dict = {}
        for r in spark_rows:
            spark_by_inst.setdefault(r["instrument_id"], []).append(float(r["close"]))
        # Reverse so they're oldest-first, cap at 12.
        for k in spark_by_inst:
            spark_by_inst[k] = list(reversed(spark_by_inst[k]))[-12:]
        # 1h fallback for instruments with no (or one) daily bar — starred
        # symbols get 1h/4h bars from the watchlist pass, not daily ones.
        for inst in qs:
            if len(spark_by_inst.get(inst.id, [])) < 2:
                closes = _recent_closes(inst.id)
                if closes:
                    spark_by_inst[inst.id] = closes

        items = []
        for inst in qs:
            q = _safe(lambda: inst.live_quote, None)
            spark = spark_by_inst.get(inst.id, [])
            spark_min = min(spark) if spark else 0
            spark_max = max(spark) if spark else 0
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
                "spark": spark,
                "spark_min": spark_min,
                "spark_max": spark_max,
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
        sparks = _safe(_headband_sparks, {}) or {}
        band = []
        for sym in HEADBAND_SYMBOLS:
            sp = sparks.get(sym) or {}
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
                    "spark": sp.get("spark", []),
                    "spark_min": sp.get("min", 0),
                    "spark_max": sp.get("max", 0),
                })
            else:
                # No quote yet — the spark still renders when bars exist,
                # so a keyless install's popups are not entirely blank.
                band.append({"symbol": sym, "last": None, "change_pct": 0,
                             "name": sym, "asset_class": "", "volume": 0,
                             "updated": "",
                             "spark": sp.get("spark", []),
                             "spark_min": sp.get("min", 0),
                             "spark_max": sp.get("max", 0)})
        data["ui_headband"] = band
    except Exception:
        pass

    return data
