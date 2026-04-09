"""Composite bot signal engine. Merges multiple signal sources into a
single score in [-1, +1] and a confidence in [0, 1]."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from .indicators import ema, rsi, macd, vwap, atr, volatility

@dataclass
class Decision:
    symbol: str
    score: float      # -1 bearish … +1 bullish
    confidence: float # 0..1
    direction: str    # "BUY","SELL","HOLD"
    reasons: list[str]
    sl_pct: float
    tp_pct: float

# ── Individual analysers ────────────────────────────────────
def _score_technical(closes: list[float], ohlcv: list[list]) -> tuple[float, list[str]]:
    reasons = []
    if len(closes) < 60: return (0, ["insufficient bars"])
    ef = ema(closes, 20); es = ema(closes, 50)
    cross = ef[-1] - es[-1] if ef and es else 0
    r = rsi(closes)
    m, s, h = macd(closes)
    vw = vwap(ohlcv[-60:]) if ohlcv else 0

    score = 0.0
    if cross > 0: score += 0.35; reasons.append("EMA20>EMA50")
    else:         score -= 0.35; reasons.append("EMA20<EMA50")
    if r < 30:    score += 0.25; reasons.append(f"RSI oversold {r:.0f}")
    elif r > 70:  score -= 0.25; reasons.append(f"RSI overbought {r:.0f}")
    if h > 0:     score += 0.20; reasons.append("MACD hist +")
    else:         score -= 0.20; reasons.append("MACD hist −")
    if vw and closes[-1] > vw: score += 0.20; reasons.append("price>VWAP")
    elif vw:                   score -= 0.20; reasons.append("price<VWAP")
    return (max(-1, min(1, score)), reasons)

def _score_liquidity(order_book: dict, symbol: str = "") -> tuple[float, list[str]]:
    """Order book pressure.

    Priority:
      1. Fresh L2 snapshot from DB (depth-weighted, <30s old).
      2. Fall back to REST order book passed in.
    """
    # 1. Try the live L2 snapshot from stream_binance_depth
    try:
        from market_data.models import OrderBookSnapshot
        from django.utils import timezone
        from datetime import timedelta
        snap = (OrderBookSnapshot.objects
                .filter(symbol__iexact=symbol,
                        timestamp__gte=timezone.now() - timedelta(seconds=30))
                .order_by("-timestamp").first())
        if snap:
            return (float(snap.depth_score),
                    [f"L2 depth {snap.depth_score:+.2f} (imb {snap.imbalance:+.2f})"])
    except Exception:
        pass
    # 2. Fallback to REST order book
    try:
        bids = sum(float(q) for _, q in order_book.get("bids", [])[:20])
        asks = sum(float(q) for _, q in order_book.get("asks", [])[:20])
        total = bids + asks
        if not total: return (0, [])
        imb = (bids - asks) / total
        return (imb, [f"REST imbalance {imb:+.2f}"])
    except Exception:
        return (0, [])

def _score_sauron_signals(symbol: str) -> tuple[float, list[str]]:
    """Pull latest signals from Sauron signals engine."""
    try:
        from signals.models import Signal
        from django.utils import timezone
        from datetime import timedelta
        recent = Signal.objects.filter(
            instrument__symbol__icontains=symbol.replace("USDT",""),
            created_at__gte=timezone.now() - timedelta(hours=6),
        ).order_by("-created_at")[:10]
        if not recent: return (0, [])
        agg = 0.0
        for s in recent:
            direction = getattr(s, "direction", "") or ""
            score = float(getattr(s, "score", 0) or 0)
            agg += (score if "bull" in direction.lower() else -score)
        agg = max(-1, min(1, agg / max(1, len(recent))))
        legacy_score = agg
        legacy_reasons = [f"sauron sig avg {agg:+.2f} ({len(recent)})"]
        try:
            from signals.bot_bridge import smc_score_for_symbol
            smc_score, smc_reasons = smc_score_for_symbol(symbol)
            blended = (legacy_score + smc_score) / 2 if smc_score != 0 else legacy_score
            return (blended, legacy_reasons + smc_reasons)
        except Exception:
            return (legacy_score, legacy_reasons)
    except Exception:
        return (0, [])

def _score_news(symbol: str) -> tuple[float, list[str]]:
    try:
        from scraping.models import NewsItem  # if exists
        from django.utils import timezone
        from datetime import timedelta
        recent = NewsItem.objects.filter(
            published_at__gte=timezone.now() - timedelta(hours=12),
        ).order_by("-published_at")[:20]
        pos, neg = 0, 0
        base = symbol.replace("USDT","").lower()
        for n in recent:
            text = f"{getattr(n,'title','')} {getattr(n,'summary','')}".lower()
            if base not in text: continue
            sent = float(getattr(n, "sentiment_score", 0) or 0)
            if sent > 0.1: pos += sent
            elif sent < -0.1: neg += sent
        total = pos + abs(neg)
        if total == 0: return (0, [])
        s = (pos - abs(neg)) / total
        return (max(-1, min(1, s)), [f"news sent {s:+.2f}"])
    except Exception:
        return (0, [])

def _score_macro() -> tuple[float, list[str]]:
    """Placeholder macro regime score from ai_agents memory if any."""
    return (0, [])

def _score_sentiment(symbol: str) -> tuple[float, list[str]]:
    return (0, [])

# ── Compose ─────────────────────────────────────────────────
def decide(symbol: str, ohlcv: list[list], order_book: dict, weights: dict,
           entry_min: float, exit_max: float, atr_mult_sl: float = 1.5,
           atr_mult_tp: float = 3.0) -> Decision:
    closes = [c[3] for c in ohlcv]
    reasons: list[str] = []
    parts = {}
    parts["technical"], r = _score_technical(closes, ohlcv); reasons += r
    parts["liquidity"], r = _score_liquidity(order_book, symbol); reasons += r
    parts["sauron_sig"], r = _score_sauron_signals(symbol);   reasons += r
    parts["news"], r       = _score_news(symbol);             reasons += r
    parts["macro"], r      = _score_macro();                  reasons += r
    parts["sentiment"], r  = _score_sentiment(symbol);        reasons += r

    composite = sum(parts[k] * weights.get(k, 0) for k in parts)
    composite = max(-1, min(1, composite))
    conf = min(1.0, abs(composite) + 0.2)

    direction = "HOLD"
    if composite >= entry_min: direction = "BUY"
    elif composite <= -entry_min: direction = "SELL"

    a = atr(ohlcv)
    last = closes[-1] if closes else 0
    sl_pct = (atr_mult_sl * a / last * 100) if last else 1.5
    tp_pct = (atr_mult_tp * a / last * 100) if last else 3.0

    return Decision(symbol, composite, conf, direction, reasons[:8],
                    max(0.3, min(5.0, sl_pct)),
                    max(0.5, min(10.0, tp_pct)))
