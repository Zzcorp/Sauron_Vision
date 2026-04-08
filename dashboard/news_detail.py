"""News article detail view with sentiment, key info and impact scoring."""
import re
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache

URGENCY_WEIGHT = {"critical": 5, "high": 4, "medium": 3, "low": 2, "": 1, None: 1}

def _impact_score(article) -> dict:
    """Return dict with stars (0..5), percent (0..100), label."""
    u = (article.ai_urgency or "").lower()
    base = URGENCY_WEIGHT.get(u, 1)                                     # 1..5
    sent = abs(float(article.ai_sentiment_score or 0))                   # 0..1
    try:
        affected = article.ai_affected_instruments.count()
    except Exception:
        affected = 0
    # Composite 0..100
    raw = (base / 5) * 60 + sent * 25 + min(affected, 5) * 3
    pct = int(max(0, min(100, round(raw))))
    stars = max(1, min(5, round(pct / 20)))
    label = {1:"MINOR",2:"LOW",3:"MODERATE",4:"HIGH",5:"CRITICAL"}[stars]
    return {"stars": stars, "percent": pct, "label": label}

def _extract_key_points(text: str, limit: int = 5) -> list[str]:
    if not text: return []
    # Split on sentence boundaries, filter short/noisy ones
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out = []
    for s in parts:
        s = s.strip()
        if 20 <= len(s) <= 240:
            out.append(s)
        if len(out) >= limit: break
    return out

@login_required
def news_detail(request, pk: int):
    from scraping.models import NewsArticle
    article = get_object_or_404(NewsArticle, pk=pk)
    impact = _impact_score(article)
    sentiment = float(article.ai_sentiment_score or 0)
    sentiment_label = ("Bullish" if sentiment > 0.2 else
                       "Bearish" if sentiment < -0.2 else "Neutral")
    sentiment_pct = int(round((sentiment + 1) * 50))  # map -1..+1 → 0..100
    key_points = _extract_key_points(article.ai_summary or article.content_summary or "")
    try:
        affected = list(article.ai_affected_instruments.all()[:20])
    except Exception:
        affected = []
    try:
        from scraping.models import NewsArticle as NA
        related = NA.objects.filter(
            ai_affected_instruments__in=affected
        ).exclude(id=article.id).distinct().order_by("-published_at")[:6] if affected else []
    except Exception:
        related = []
    return render(request, "dashboard/news_detail.html", {
        "page_id": "news", "article": article, "impact": impact,
        "sentiment": sentiment, "sentiment_label": sentiment_label,
        "sentiment_pct": sentiment_pct, "key_points": key_points,
        "affected": affected, "related": related,
    })


@never_cache
@login_required
def live_metrics_json(request):
    """Lightweight polling endpoint. Frontend calls every 15s."""
    from core.context_ui import ui_extras
    ctx = ui_extras(request)
    return JsonResponse({
        "metrics": ctx.get("ui_metrics", {}),
        "headband": ctx.get("ui_headband", []),
        "watchlist": ctx.get("ui_watchlist", []),
    })
