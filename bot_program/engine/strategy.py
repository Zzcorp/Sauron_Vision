"""Composite bot signal engine. Merges multiple signal sources into a
single score in [-1, +1] and a confidence in [0, 1]."""
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Iterable
from .indicators import ema, rsi, macd, vwap, atr, volatility

_log = logging.getLogger(__name__)

# Articles below this count damp the leg proportionally. The raw score is a
# normalised balance — (pos - |neg|) / (pos + |neg|) — which reaches ±1.00 on
# ONE article, so a single graded headline would have swung this leg to full
# scale. That was harmless while the leg was dead; it is not harmless now
# that it computes. Three is the point where a direction is a reading rather
# than an anecdote, and below it the leg says a fraction of what it found.
NEWS_FULL_WEIGHT_ARTICLES = 3

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

def _news_names(text: str, base: str) -> bool:
    """Does this article actually name the asset?

    A bare `base in text` was a three-letter substring test. For ETHUSDT the
    needle is "eth", which occurs in whether, together, something, method
    and ethics — so a macro headline reading "Fed weighs whether to cut
    again" scored as ETH news. The leg had returned a flat 0 for its whole
    life (it imported a model that never existed), so nothing had ever
    exercised this; waking it up made every English article a match.

    Word boundaries, and the ticker's own spelling as well as its base: an
    article says BTC or bitcoin, rarely "btcusdt".
    """
    import re
    words = {base}
    words |= _NEWS_ALIASES.get(base, set())
    for w in words:
        if len(w) < 2:
            continue
        if re.search(r"\b" + re.escape(w) + r"\b", text):
            return True
    return False


#: The names a market actually uses, beside the ticker. Bare tickers alone
#: match almost nothing an editor writes; bare three-letter bases match
#: almost everything.
_NEWS_ALIASES = {
    "btc": {"bitcoin"},
    "eth": {"ethereum", "ether"},
    "sol": {"solana"},
    "xrp": {"ripple"},
    "ada": {"cardano"},
    "doge": {"dogecoin"},
    "bnb": {"binance coin"},
}


def _score_news(symbol: str, as_of=None) -> tuple[float, list[str]]:
    """Sentiment of the last 12h of news that names this symbol.

    The model is `NewsArticle` with `ai_sentiment_score`, written by the
    news-analyst agent. This asked for `scraping.models.NewsItem`, which has
    never existed: the ImportError went straight into the except below and
    the leg returned a flat 0 for every symbol on every bar, silently — so a
    config that authored 0.3 of its weight to news was in fact damping its
    composite by that whole 0.3 toward zero and taking fewer entries than it
    was configured for. The backtester runs the same function, so a backtest
    could not reveal it either.
    """
    try:
        from scraping.models import NewsArticle
        from django.utils import timezone
        from datetime import timedelta
        # `as_of` is the bar being decided. The backtester drives this exact
        # function bar by bar over historical data, and without a bound the
        # window is "the last 12 hours" measured from the machine clock — so
        # every bar of a 2024 backtest was scored against TODAY's headlines.
        # That is not an inaccuracy, it is lookahead: the backtest knows
        # things the trade could not have.
        end = as_of or timezone.now()
        recent = NewsArticle.objects.filter(
            published_at__gte=end - timedelta(hours=12),
            published_at__lte=end,
        ).order_by("-published_at")[:20]
        pos, neg = 0, 0
        graded = 0
        base = symbol.replace("USDT","").lower()
        for n in recent:
            text = (f"{getattr(n, 'title', '')} "
                    f"{getattr(n, 'ai_summary', '')} "
                    f"{getattr(n, 'content_summary', '')}").lower()
            if not _news_names(text, base): continue
            # None means the analyst has not graded this article yet, which
            # is not the same as neutral — an ungraded article contributes
            # nothing rather than pulling the score toward 0.
            sent = getattr(n, "ai_sentiment_score", None)
            if sent is None: continue
            sent = float(sent)
            if sent > 0.1: pos += sent; graded += 1
            elif sent < -0.1: neg += sent; graded += 1
            # A graded-but-neutral article counts as evidence of NOTHING.
            # Counting it toward the damping denominator was the wrong sign
            # of wrong: three neutral articles plus one strong opinion
            # reached full conviction on that single opinion, which is the
            # exact saturation the damping exists to prevent.
        total = pos + abs(neg)
        if total == 0: return (0, [])
        s = (pos - abs(neg)) / total
        # Damped by how much there was to read. Waking this leg up after it
        # had returned 0 forever is already a live change to every composite
        # config's behaviour; letting one headline arrive at full conviction
        # would make that change larger than the evidence behind it.
        confidence = min(1.0, graded / float(NEWS_FULL_WEIGHT_ARTICLES))
        s = max(-1, min(1, s)) * confidence
        note = f"news sent {s:+.2f}"
        if confidence < 1.0:
            note += f" ({graded} article{'s' if graded != 1 else ''})"
        return (s, [note])
    except Exception as e:
        # Loud, because the failure this hides is invisible in the output:
        # a leg that returns 0 looks exactly like neutral news.
        _log.warning("news leg failed for %s: %s", symbol, e)
        return (0, [])

def _score_macro() -> tuple:
    """Unimplemented. Returns None — "did not look" — not 0.

    0.0 means "looked, and it is neutral", and these two legs returning it
    kept 15% of the normalized weight in the denominator while contributing
    nothing to the numerator. An operator who set entry_score_min = 0.60
    got a bot that in fact required 0.706 of full saturation, silently and
    permanently, on a path that places real market orders.
    """
    return (None, [])

def _score_sentiment(symbol: str) -> tuple:
    """Unimplemented. See _score_macro."""
    return (None, [])

# ── Compose ─────────────────────────────────────────────────
def decide(symbol: str, ohlcv: list[list], order_book: dict, weights: dict,
           entry_min: float, exit_max: float, atr_mult_sl: float = 1.5,
           atr_mult_tp: float = 3.0, as_of=None) -> Decision:
    """One composite score for one bar.

    `as_of` is the moment being decided. The live runner leaves it None and
    everything reads "now"; a backtester MUST pass the bar's timestamp, or
    the news leg scores 2024 bars against today's headlines.
    """
    closes = [c[3] for c in ohlcv]
    reasons: list[str] = []
    parts = {}
    parts["technical"], r = _score_technical(closes, ohlcv); reasons += r
    parts["liquidity"], r = _score_liquidity(order_book, symbol); reasons += r
    parts["sauron_sig"], r = _score_sauron_signals(symbol);   reasons += r
    parts["news"], r       = _score_news(symbol, as_of);      reasons += r
    parts["macro"], r      = _score_macro();                  reasons += r
    parts["sentiment"], r  = _score_sentiment(symbol);        reasons += r

    # Only the legs that REPORTED are weighted, and the denominator shrinks
    # with them. A leg returning None did not look; its weight leaves with
    # it, so the composite is a score out of what was actually measured and
    # `entry_score_min` means what the operator set it to.
    reported = {k: v for k, v in parts.items() if v is not None}
    live_weight = sum(weights.get(k, 0) for k in reported)
    composite = (sum(reported[k] * weights.get(k, 0) for k in reported)
                 / live_weight) if live_weight > 0 else 0.0
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
