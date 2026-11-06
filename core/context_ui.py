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

#: The watchlist rail's stated ceiling (2026-11-06). It used to slice the
#: starred instruments at 40 without a word; it draws up to this many and
#: says how many more there are.
WATCHLIST_CEILING = 200


def _testing() -> bool:
    import sys
    return "test" in sys.argv or any("pytest" in a for a in sys.argv)


def _spark_fallback(inst_id):
    """The 1h-bar spark of one starred instrument, cached 5 minutes — the
    watchlist draws up to 200 of them and a chart that moves hourly need
    not be re-read on every render (bypassed under the test runner, whose
    rolled-back ids would otherwise share one key)."""
    if _testing():
        return _recent_closes(inst_id)
    from django.core.cache import cache
    key = f"wl:spark:{inst_id}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    closes = _recent_closes(inst_id)
    cache.set(key, closes, 300)
    return closes


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


def _class_index(cls) -> int:
    from dashboard.signal_rail import CLASS_ORDER
    try:
        return CLASS_ORDER.index(cls)
    except ValueError:
        return len(CLASS_ORDER)


def _watch_facts(request, items, total) -> None:
    """held, and the order variables of every watchlist item: --o-sym by
    symbol, --o-cls by class (the vocabulary's order) then the list's own,
    --o-held the held items first."""
    held = {}
    try:
        from dashboard.signal_rail import held_symbols
        held = held_symbols(request)
    except Exception:  # noqa: BLE001 — held is a filter fact
        held = {}
    by_sym = sorted(range(len(items)), key=lambda i: items[i]["symbol"])
    for rank, i in enumerate(by_sym, 1):
        items[i]["o_sym"] = rank
    seen = {}
    held_rank = 0
    for i, item in enumerate(items):
        k = _class_index(item.get("asset_class") or "")
        seen[k] = seen.get(k, 0) + 1
        item["o_cls"] = k * 10000 + seen[k]
        item["held"] = bool(held.get((item["symbol"] or "").upper()))
        item["held_venue"] = held.get((item["symbol"] or "").upper(), "")
    for i, item in enumerate(items):
        if item["held"]:
            held_rank += 1
            item["o_held"] = held_rank
    for i, item in enumerate(items):
        if not item["held"]:
            item["o_held"] = 10000 + i + 1


def _watch_facets(items, total) -> dict:
    """The watchlist's chips: a count per class (every class drawn, a zero
    hidden by CSS), the held count, and how many stars the ceiling left
    out."""
    from dashboard.signal_rail import CLASS_ORDER, CLASS_SHORT
    per = {}
    for item in items:
        per[item.get("asset_class") or ""] = per.get(item.get("asset_class") or "", 0) + 1
    return {"classes": [(k, CLASS_SHORT.get(k, k.upper()), per.get(k, 0))
                        for k in CLASS_ORDER],
            "held": sum(1 for item in items if item.get("held")),
            "n": len(items), "total": total,
            "more": max(0, total - len(items))}


def _watch_groups(items) -> list:
    """One group header per class present, ordered before its items."""
    from dashboard.signal_rail import CLASS_SHORT
    out, seen = [], set()
    for item in items:
        cls = item.get("asset_class") or ""
        if cls in seen:
            continue
        seen.add(cls)
        out.append({"asset_class": cls,
                    "label": CLASS_SHORT.get(cls, (cls or "other").upper()),
                    "o_cls": _class_index(cls) * 10000})
    return out


def ui_extras(request):
    data = {
        "ui_watchlist": [],
        "ui_watch_facets": {},
        "ui_watch_groups": [],
        "ui_metrics": {},
        "ui_headband": [],
        # The handover card (core/passation.py): on every logged-in page
        # from the hour the letter opens, for the length of the watch.
        "passation_card": False,
    }
    try:
        from core import passation
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            data["passation_card"] = passation.card_due()
    except Exception:
        pass
    # ── Watchlist (with live quotes + 12-bar sparkline) ──
    # (2026-11-06) Every star up to a STATED ceiling (WATCHLIST_CEILING),
    # with the quote joined in the same query, and the facts the rail's
    # filters read on each item: held (the operator holds it, the same memo
    # the signal rail reads) and the ranks CSS orders by (symbol, class,
    # held first). The headband WATCHLIST popup lists this same list.
    try:
        from instruments.models import Instrument
        from market_data.models import PriceData
        starred = Instrument.objects.filter(is_watchlist=True, is_active=True)
        qs = list(starred.select_related("live_quote")[:WATCHLIST_CEILING + 1])
        total = len(qs)
        if total > WATCHLIST_CEILING:
            qs = qs[:WATCHLIST_CEILING]
            total = starred.count()
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
                closes = _spark_fallback(inst.id)
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
        _watch_facts(request, items, total)
        data["ui_watchlist"] = items
        data["ui_watch_facets"] = _watch_facets(items, total)
        data["ui_watch_groups"] = _watch_groups(items)
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
                import datetime as _dt
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
                    # The card's "As of" (_partials/dh_item.html): the same
                    # instant as `updated`, on the UTC clock face. The page
                    # re-reads `updated` itself whenever a tick or a sweep
                    # replaces the record.
                    "updated_utc": (q.updated_at.astimezone(_dt.timezone.utc)
                                    .strftime("%H:%M:%S")) if q.updated_at else "",
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
