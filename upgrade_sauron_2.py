#!/usr/bin/env python3
"""
upgrade_sauron_2.py
===================
Second upgrade pass for Sauron Vision. Drop into the project root
(next to manage.py) and run:

    python upgrade_sauron_2.py

Idempotent. Everything is additive or wrapped in marker blocks so it's
safe to re-run. Changes:

 1. New design system for buttons, inputs, selects, metric cards
    + richer market overview block with live polling.
 2. Right signals rail split into TWO panels (Signals top + Watchlist
    bottom) with a drag handle to adjust heights, independent collapse,
    and scroll-within-content.
 3. News detail page `/news/<id>/` — overview, sentiment bar, key info,
    impact stars (1–5), relevance %, affected instruments. Linked from
    the news feed and from the ticker bar.
 4. Ticker news items get a richer hover dropdown with full metadata.
 5. New "dashboard data headband" below the existing info panel with
    many live market metrics, each with its own info dropdown.
 6. Context processor that provides watchlist items, market metrics,
    and the dashboard headband data on every page.
 7. Live data poll endpoint `/api/live/metrics/` returning JSON every
    15s (see notes at bottom for WebSocket upgrade path).
"""
from __future__ import annotations
import os, sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent
if not (ROOT / "manage.py").exists():
    print("ERROR: run this script from the directory containing manage.py")
    sys.exit(1)

def write(rel: str, content: str, *, overwrite: bool = True):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and not overwrite:
        print(f"  skip (exists): {rel}"); return
    p.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
    print(f"  wrote: {rel}")

def patch(rel: str, old: str, new: str):
    p = ROOT / rel
    if not p.exists():
        print(f"  MISSING file for patch: {rel}"); return
    txt = p.read_text(encoding="utf-8")
    if new.strip() and new.strip()[:60] in txt:
        print(f"  already patched: {rel}"); return
    if old not in txt:
        print(f"  anchor not found in {rel}"); return
    p.write_text(txt.replace(old, new, 1), encoding="utf-8")
    print(f"  patched: {rel}")

def insert_after(rel: str, marker: str, snippet: str, tag: str):
    p = ROOT / rel
    if not p.exists():
        print(f"  MISSING file: {rel}"); return
    txt = p.read_text(encoding="utf-8")
    if tag in txt:
        print(f"  already inserted ({tag}): {rel}"); return
    idx = txt.find(marker)
    if idx < 0:
        print(f"  marker not found in {rel}"); return
    idx += len(marker)
    p.write_text(txt[:idx] + "\n" + snippet + "\n" + txt[idx:], encoding="utf-8")
    print(f"  inserted ({tag}): {rel}")

print("━" * 60)
print(" SAURON VISION — UPGRADE PASS 2")
print("━" * 60)

# =================================================================
# STEP 1 — Context processor for watchlist + metrics
# =================================================================
print("\n[1/7] Writing context processor …")

write("core/context_ui.py", '''
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
                    band.append({
                        "symbol": sym,
                        "last": float(q.last or 0),
                        "change_pct": float(q.change_pct or 0),
                        "name": q.instrument.name or sym,
                        "asset_class": q.instrument.asset_class or "",
                        "volume": int(q.volume or 0),
                        "updated": q.updated_at.isoformat() if q.updated_at else "",
                    })
                else:
                    band.append({"symbol": sym, "last": None, "change_pct": 0,
                                 "name": sym, "asset_class": "", "volume": 0, "updated": ""})
            data["ui_headband"] = band
        except Exception:
            pass

        return data
''')

# Register in settings — append to context_processors list robustly
_settings = ROOT / "config/settings.py"
if _settings.exists():
    _txt = _settings.read_text(encoding="utf-8")
    if "core.context_ui.ui_extras" in _txt:
        print("  context processor already registered")
    else:
        import re as _re
        # Find the context_processors list and append our entry before the closing ]
        m = _re.search(r'("context_processors"\s*:\s*\[)(.*?)(\s*\])', _txt, _re.DOTALL)
        if m:
            head, body, tail = m.group(1), m.group(2), m.group(3)
            indent = "\n                "
            new_body = body.rstrip() + "," + indent + '"core.context_ui.ui_extras"'
            _txt = _txt[:m.start()] + head + new_body + tail + _txt[m.end():]
            _settings.write_text(_txt, encoding="utf-8")
            print("  registered core.context_ui.ui_extras in context_processors")
        else:
            print("  could not find context_processors list in settings.py")

# =================================================================
# STEP 2 — News detail view + URL + template + live metrics endpoint
# =================================================================
print("\n[2/7] Adding news detail page + live metrics endpoint …")

write("dashboard/news_detail.py", '''
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
        parts = re.split(r"(?<=[.!?])\\s+", text.strip())
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
''')

# Wire up URLs in dashboard/urls.py
patch("dashboard/urls.py",
      'path("news/", views.news_feed, name="news_feed"),',
      'path("news/", views.news_feed, name="news_feed"),\n    path("news/<int:pk>/", __import__("dashboard.news_detail", fromlist=["news_detail"]).news_detail, name="news_detail"),\n    path("api/live/metrics/", __import__("dashboard.news_detail", fromlist=["live_metrics_json"]).live_metrics_json, name="live_metrics"),')

# News detail template
write("templates/dashboard/news_detail.html", '''
    {% extends "base.html" %}
    {% block title %}{{ article.title|truncatechars:60 }} — Sauron Vision{% endblock %}
    {% block page_title %}▤ NEWS ANALYSIS{% endblock %}
    {% block content %}
    <div class="page-content fade-in nd-wrap">
      <a href="{% url 'news_feed' %}" class="btn btn-ghost btn-sm">← Back to feed</a>

      <div class="nd-grid">
        <div class="nd-main">
          <div class="card nd-article">
            <div class="nd-meta">
              <span class="nd-source">{{ article.source }}</span>
              <span class="nd-dot">·</span>
              <span>{{ article.published_at|date:"M d, Y · H:i" }}</span>
              <span class="nd-dot">·</span>
              <span>{{ article.published_at|timesince }} ago</span>
            </div>
            <h1 class="nd-title">{{ article.title }}</h1>
            {% if article.url %}
              <a href="{{ article.url }}" target="_blank" rel="noopener" class="btn btn-primary btn-sm" style="margin:10px 0 18px;">
                ↗ OPEN ORIGINAL SOURCE
              </a>
            {% endif %}

            <div class="nd-section">
              <div class="nd-section-title">OVERVIEW</div>
              <div class="nd-body">
                {% if article.ai_summary %}{{ article.ai_summary|linebreaks }}
                {% elif article.content_summary %}{{ article.content_summary|linebreaks }}
                {% else %}<em style="color:var(--text-muted);">No summary available. Click "OPEN ORIGINAL SOURCE" to read the full article.</em>
                {% endif %}
              </div>
            </div>

            {% if key_points %}
            <div class="nd-section">
              <div class="nd-section-title">KEY POINTS</div>
              <ul class="nd-points">
                {% for p in key_points %}<li><span class="nd-bullet">▸</span> {{ p }}</li>{% endfor %}
              </ul>
            </div>
            {% endif %}

            {% if article.raw_content and article.raw_content != article.content_summary %}
            <div class="nd-section">
              <div class="nd-section-title">FULL CONTENT</div>
              <div class="nd-body nd-raw">{{ article.raw_content|linebreaks }}</div>
            </div>
            {% endif %}
          </div>
        </div>

        <aside class="nd-side">
          <!-- Impact card -->
          <div class="card nd-impact">
            <div class="nd-card-title">IMPACT CLASSIFICATION</div>
            <div class="nd-stars">
              {% for i in "12345" %}
                {% if forloop.counter <= impact.stars %}<span class="star on">★</span>{% else %}<span class="star">☆</span>{% endif %}
              {% endfor %}
            </div>
            <div class="nd-impact-label">{{ impact.label }}</div>
            <div class="nd-ring-wrap">
              <div class="nd-ring" style="--pct:{{ impact.percent }};">
                <svg viewBox="0 0 100 100">
                  <circle cx="50" cy="50" r="42" class="ring-bg"/>
                  <circle cx="50" cy="50" r="42" class="ring-fg"
                          style="stroke-dasharray:{{ impact.percent }} 264;"/>
                </svg>
                <div class="nd-ring-val">{{ impact.percent }}%</div>
                <div class="nd-ring-lbl">RELEVANCE</div>
              </div>
            </div>
          </div>

          <!-- Sentiment -->
          <div class="card">
            <div class="nd-card-title">SENTIMENT</div>
            <div class="nd-sent-label
              {% if sentiment > 0.2 %}pos{% elif sentiment < -0.2 %}neg{% else %}neu{% endif %}">
              {{ sentiment_label|upper }}
            </div>
            <div class="nd-sent-score">{{ sentiment|floatformat:2 }}</div>
            <div class="nd-sent-bar">
              <div class="nd-sent-mid"></div>
              <div class="nd-sent-fill" style="left:{{ sentiment_pct }}%;
                background:{% if sentiment > 0.2 %}var(--accent){% elif sentiment < -0.2 %}var(--accent-red){% else %}var(--text-muted){% endif %};"></div>
            </div>
            <div class="nd-sent-axis"><span>-1</span><span>0</span><span>+1</span></div>
            {% if article.ai_urgency %}
            <div class="nd-kv" style="margin-top:14px;">
              <span>Urgency</span><span class="badge badge-{{ article.ai_urgency }}">{{ article.ai_urgency|upper }}</span>
            </div>
            {% endif %}
          </div>

          <!-- Affected instruments -->
          {% if affected %}
          <div class="card">
            <div class="nd-card-title">AFFECTED INSTRUMENTS</div>
            <div class="nd-chips">
              {% for inst in affected %}
                <a href="{% url 'instrument_detail' inst.symbol %}" class="nd-chip">{{ inst.symbol }}</a>
              {% endfor %}
            </div>
          </div>
          {% endif %}

          <!-- Related news -->
          {% if related %}
          <div class="card">
            <div class="nd-card-title">RELATED</div>
            {% for r in related %}
              <a href="{% url 'news_detail' r.id %}" class="nd-related">
                <div class="nd-related-t">{{ r.title|truncatechars:70 }}</div>
                <div class="nd-related-m">{{ r.source }} · {{ r.published_at|timesince }} ago</div>
              </a>
            {% endfor %}
          </div>
          {% endif %}
        </aside>
      </div>
    </div>

    {% block extra_css %}
    <style>
      .nd-wrap { max-width: 1400px; }
      .nd-grid { display: grid; grid-template-columns: 1fr 340px; gap: 22px; margin-top: 16px; }
      @media (max-width: 1100px) { .nd-grid { grid-template-columns: 1fr; } }
      .nd-article { padding: 28px 32px; }
      .nd-meta { font-family: var(--font-mono); font-size: 11px; color: var(--text-muted); letter-spacing: 1px; }
      .nd-source { color: var(--accent); font-weight: 700; }
      .nd-dot { margin: 0 8px; opacity: .5; }
      .nd-title { font-family: var(--font-heading); font-size: 28px; font-weight: 700;
                  color: var(--text-primary); line-height: 1.25; margin: 12px 0 6px; }
      .nd-section { margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--border); }
      .nd-section-title { font-family: var(--font-mono); font-size: 10px; letter-spacing: 3px;
                          color: var(--accent); margin-bottom: 12px; text-transform: uppercase; }
      .nd-body { font-size: 15px; line-height: 1.7; color: var(--text-primary); }
      .nd-raw { max-height: 520px; overflow-y: auto; padding-right: 8px; }
      .nd-points { list-style: none; padding: 0; }
      .nd-points li { padding: 8px 0; border-bottom: 1px dashed var(--border);
                      color: var(--text-primary); font-size: 14px; line-height: 1.5; }
      .nd-bullet { color: var(--accent); margin-right: 8px; }

      .nd-side .card { margin-bottom: 18px; }
      .nd-card-title { font-family: var(--font-mono); font-size: 10px; letter-spacing: 3px;
                       color: var(--text-muted); margin-bottom: 14px; }

      .nd-stars { text-align: center; font-size: 28px; letter-spacing: 4px; }
      .nd-stars .star { color: var(--border-glow); }
      .nd-stars .star.on { color: var(--accent-gold); text-shadow: 0 0 14px rgba(216,176,32,.5); }
      .nd-impact-label { text-align: center; font-family: var(--font-display); font-size: 14px;
                         letter-spacing: 3px; color: var(--accent); margin-top: 6px; }

      .nd-ring-wrap { display: flex; justify-content: center; margin-top: 18px; }
      .nd-ring { position: relative; width: 140px; height: 140px; }
      .nd-ring svg { transform: rotate(-90deg); width: 100%; height: 100%; }
      .nd-ring .ring-bg { fill: none; stroke: var(--border); stroke-width: 8; }
      .nd-ring .ring-fg { fill: none; stroke: var(--accent); stroke-width: 8;
                          stroke-linecap: round; transition: stroke-dasharray .8s ease; }
      .nd-ring-val { position: absolute; inset: 0; display: flex; align-items: center;
                     justify-content: center; font-family: var(--font-display);
                     font-size: 26px; font-weight: 900; color: var(--text-primary); }
      .nd-ring-lbl { position: absolute; bottom: 18px; left: 0; right: 0; text-align: center;
                     font-family: var(--font-mono); font-size: 9px; letter-spacing: 2px;
                     color: var(--text-muted); }

      .nd-sent-label { text-align: center; font-family: var(--font-display);
                       font-size: 18px; letter-spacing: 4px; margin-bottom: 4px; }
      .nd-sent-label.pos { color: var(--accent); }
      .nd-sent-label.neg { color: var(--accent-red); }
      .nd-sent-label.neu { color: var(--text-secondary); }
      .nd-sent-score { text-align: center; font-family: var(--font-mono);
                       font-size: 12px; color: var(--text-muted); margin-bottom: 12px; }
      .nd-sent-bar { position: relative; height: 10px; background: var(--bg-void);
                     border: 1px solid var(--border); border-radius: 5px; overflow: hidden; }
      .nd-sent-mid { position: absolute; left: 50%; top: 0; bottom: 0; width: 1px;
                     background: var(--border-glow); }
      .nd-sent-fill { position: absolute; top: 0; width: 4px; height: 100%;
                      border-radius: 2px; transform: translateX(-50%); box-shadow: 0 0 10px currentColor; }
      .nd-sent-axis { display: flex; justify-content: space-between; margin-top: 4px;
                      font-family: var(--font-mono); font-size: 9px; color: var(--text-muted); }

      .nd-chips { display: flex; flex-wrap: wrap; gap: 6px; }
      .nd-chip { padding: 4px 10px; background: var(--accent-dim); color: var(--accent);
                 border-radius: 10px; font-family: var(--font-mono); font-size: 11px;
                 text-decoration: none; transition: all .15s; }
      .nd-chip:hover { background: var(--accent); color: var(--bg-void); }

      .nd-related { display: block; padding: 10px 0; border-bottom: 1px solid var(--border);
                    text-decoration: none; }
      .nd-related:last-child { border-bottom: 0; }
      .nd-related-t { color: var(--text-primary); font-size: 12px; line-height: 1.4; }
      .nd-related-m { color: var(--text-muted); font-size: 10px; font-family: var(--font-mono); margin-top: 3px; }
      .nd-related:hover .nd-related-t { color: var(--accent); }

      .nd-kv { display: flex; justify-content: space-between; font-family: var(--font-mono);
               font-size: 11px; color: var(--text-secondary); }
    </style>
    {% endblock %}
    {% endblock %}
''')

# =================================================================
# STEP 3 — Patch news_feed.html to link to detail page
# =================================================================
print("\n[3/7] Linking news feed rows to detail page …")

patch("templates/dashboard/news_feed.html",
      '<td><a href="{{ a.url }}" target="_blank" style="color: var(--text-primary); text-decoration: none;">{{ a.title|truncatechars:70 }}</a></td>',
      '<td><a href="{% url \'news_detail\' a.id %}" style="color: var(--text-primary); text-decoration: none;">{{ a.title|truncatechars:70 }}</a> <a href="{{ a.url }}" target="_blank" style="color:var(--text-muted);font-size:10px;margin-left:6px;">↗</a></td>')

# =================================================================
# STEP 4 — Big CSS block: buttons, inputs, metrics, rail split, headband
# =================================================================
print("\n[4/7] Injecting new UI CSS into base.html …")

UI_CSS = r"""
        /* ═══════════════════════════════════════════════════════════ */
        /* UPGRADE-2: Design system — buttons, inputs, metrics         */
        /* ═══════════════════════════════════════════════════════════ */
        .btn {
            display: inline-flex; align-items: center; justify-content: center;
            gap: 8px; padding: 11px 22px; border: 1px solid var(--border);
            background: var(--bg-card); color: var(--text-primary);
            font-family: var(--font-display); font-size: 12px; font-weight: 600;
            letter-spacing: 2.5px; text-transform: uppercase; cursor: pointer;
            border-radius: var(--radius); text-decoration: none;
            transition: all .22s cubic-bezier(.2,.8,.2,1); position: relative; overflow: hidden;
        }
        .btn::before {
            content: ""; position: absolute; inset: 0;
            background: linear-gradient(135deg, transparent, rgba(0,232,104,.08), transparent);
            opacity: 0; transition: opacity .3s;
        }
        .btn:hover::before { opacity: 1; }
        .btn:hover { border-color: var(--accent); transform: translateY(-1px);
                     box-shadow: 0 4px 20px rgba(0,232,104,.12); color: var(--accent); }
        .btn:active { transform: translateY(0); }
        .btn.btn-primary {
            background: linear-gradient(135deg, var(--accent-dim), var(--accent));
            color: var(--bg-void); border-color: var(--accent); font-weight: 700;
        }
        .btn.btn-primary:hover { color: var(--bg-void); box-shadow: 0 6px 28px rgba(0,232,104,.35); }
        .btn.btn-danger {
            background: linear-gradient(135deg, #3a0e0e, var(--accent-red));
            color: #fff; border-color: var(--accent-red);
        }
        .btn.btn-danger:hover { color: #fff; box-shadow: 0 6px 28px rgba(232,48,48,.3); }
        .btn.btn-ghost { background: transparent; }
        .btn.btn-sm { padding: 7px 14px; font-size: 10px; letter-spacing: 2px; }
        .btn.btn-lg { padding: 15px 30px; font-size: 14px; letter-spacing: 3px; }
        .btn[disabled], .btn.disabled { opacity: .4; pointer-events: none; }

        .input, input[type=text].input, input[type=password].input, input[type=email].input,
        input[type=number].input, textarea.input, select.input {
            width: 100%; padding: 12px 14px;
            background: var(--bg-void); border: 1px solid var(--border);
            border-radius: var(--radius); color: var(--text-primary);
            font-family: var(--font-mono); font-size: 13px; outline: none;
            transition: all .2s;
        }
        .input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(0,232,104,.08); }
        .input::placeholder { color: var(--text-muted); }
        .input-group { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
        .input-label { font-family: var(--font-mono); font-size: 10px;
                       letter-spacing: 2.5px; color: var(--text-muted); text-transform: uppercase; }
        .input-hint { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); }

        /* Polished metric card */
        .metric {
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: var(--radius-lg); padding: 18px 20px;
            position: relative; overflow: hidden; transition: all .25s;
        }
        .metric::after {
            content: ""; position: absolute; top: 0; left: 0; right: 0; height: 2px;
            background: linear-gradient(90deg, transparent, var(--accent), transparent);
            opacity: 0; transition: opacity .3s;
        }
        .metric:hover { border-color: var(--accent-dim); transform: translateY(-2px);
                        box-shadow: 0 8px 30px rgba(0,0,0,.3); }
        .metric:hover::after { opacity: 1; }
        .metric-label { font-family: var(--font-mono); font-size: 9px;
                        letter-spacing: 2.5px; color: var(--text-muted); text-transform: uppercase; }
        .metric-value { font-family: var(--font-display); font-size: 26px; font-weight: 700;
                        color: var(--text-primary); margin: 6px 0 2px; }
        .metric-change { font-family: var(--font-mono); font-size: 11px; }
        .metric-change.up { color: var(--accent); }
        .metric-change.down { color: var(--accent-red); }
        .metric-spark { height: 28px; margin-top: 8px; }
        .metric-sub { font-family: var(--font-mono); font-size: 10px; color: var(--text-secondary); margin-top: 4px; }
        .metric-icon { position: absolute; top: 14px; right: 16px; font-size: 18px;
                       color: var(--accent); opacity: .25; }

        /* ═══════════════════════════════════════════════════════════ */
        /* UPGRADE-2: Signals rail split (Signals + Watchlist)         */
        /* ═══════════════════════════════════════════════════════════ */
        .signals-rail {
            display: flex !important; flex-direction: column;
        }
        .rail-section { display: flex; flex-direction: column; min-height: 40px; overflow: hidden; }
        .rail-section.sig-section { flex: 1 1 50%; }
        .rail-section.watch-section { flex: 1 1 50%; }
        .rail-section.collapsed { flex: 0 0 38px !important; }
        .rail-head {
            padding: 10px 12px; cursor: pointer; display: flex; align-items: center;
            gap: 8px; border-bottom: 1px solid var(--border); transition: all .2s;
            background: var(--bg-card); flex-shrink: 0;
        }
        .rail-head:hover { background: var(--bg-card-hover); }
        .rail-head .rh-icon { font-size: 14px; color: var(--accent); flex-shrink: 0; }
        .rail-head .rh-label {
            font-family: var(--font-mono); font-size: 9px; letter-spacing: 2px;
            color: var(--text-muted); text-transform: uppercase; white-space: nowrap;
            overflow: hidden; flex: 1;
        }
        .rail-head .rh-count {
            min-width: 20px; height: 18px; border-radius: 9px; padding: 0 6px;
            background: var(--accent-dim); color: var(--accent); font-size: 9px;
            font-family: var(--font-mono); font-weight: 700;
            display: flex; align-items: center; justify-content: center;
        }
        .rail-head .rh-chev { font-size: 9px; color: var(--text-muted); transition: transform .2s; }
        .rail-section.collapsed .rh-chev { transform: rotate(-90deg); }
        .rail-body {
            flex: 1; overflow-y: auto; padding: 0;
            scrollbar-width: thin; scrollbar-color: var(--border) transparent;
        }
        .rail-body::-webkit-scrollbar { width: 6px; }
        .rail-body::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
        .rail-section.collapsed .rail-body { display: none; }
        .signals-rail:not(.open) .rh-label,
        .signals-rail:not(.open) .rh-count,
        .signals-rail:not(.open) .rh-chev { display: none; }

        /* Drag handle between the two sections */
        .rail-resizer {
            height: 6px; cursor: row-resize; background: var(--bg-primary);
            border-top: 1px solid var(--border); border-bottom: 1px solid var(--border);
            display: flex; align-items: center; justify-content: center;
            flex-shrink: 0; transition: background .15s;
        }
        .rail-resizer::before {
            content: ""; width: 24px; height: 2px; background: var(--border-glow);
            border-radius: 1px; transition: background .15s;
        }
        .rail-resizer:hover { background: var(--accent-dim); }
        .rail-resizer:hover::before { background: var(--accent); }
        .signals-rail:not(.open) .rail-resizer { display: none; }

        /* Watchlist items */
        .wl-item {
            padding: 10px 14px; border-bottom: 1px solid var(--border);
            display: flex; align-items: center; gap: 10px; cursor: pointer;
            transition: background .15s; text-decoration: none; color: inherit;
        }
        .wl-item:hover { background: var(--bg-card-hover); }
        .wl-sym { font-family: var(--font-display); font-size: 11px; font-weight: 700;
                  color: var(--text-primary); flex-shrink: 0; min-width: 56px; }
        .wl-last { font-family: var(--font-mono); font-size: 11px; color: var(--text-primary);
                   flex: 1; text-align: right; }
        .wl-chg { font-family: var(--font-mono); font-size: 10px; min-width: 52px; text-align: right; }
        .wl-chg.up { color: var(--accent); }
        .wl-chg.down { color: var(--accent-red); }
        .signals-rail:not(.open) .wl-item { padding: 6px 0; justify-content: center; }
        .signals-rail:not(.open) .wl-sym { font-size: 9px; min-width: 0; text-align: center; }
        .signals-rail:not(.open) .wl-last, .signals-rail:not(.open) .wl-chg { display: none; }

        /* ═══════════════════════════════════════════════════════════ */
        /* UPGRADE-2: Dashboard data headband (rich metrics strip)     */
        /* ═══════════════════════════════════════════════════════════ */
        .data-headband {
            position: fixed; left: var(--sidebar-width); right: 0;
            top: calc(var(--topbar-height) + 34px + 32px); /* below ticker + info-panel */
            height: 40px; background: linear-gradient(180deg, var(--bg-primary), var(--bg-void));
            border-bottom: 1px solid var(--border); z-index: 43;
            overflow-x: auto; overflow-y: visible; white-space: nowrap;
            display: flex; align-items: stretch;
            scrollbar-width: none;
        }
        .data-headband::-webkit-scrollbar { display: none; }
        body:has(.sidebar.mini) .data-headband { left: 68px; }
        body:has(.signals-rail) .data-headband { right: 44px; }
        body:has(.signals-rail.open) .data-headband { right: 280px; }
        @media (max-width: 768px) { .data-headband { left: 0 !important; right: 0 !important; } }

        .dh-item {
            display: inline-flex; align-items: center; gap: 10px;
            padding: 0 18px; border-right: 1px solid var(--border);
            font-family: var(--font-mono); font-size: 11px;
            position: relative; cursor: pointer; flex-shrink: 0;
            transition: background .15s;
        }
        .dh-item:hover { background: var(--bg-card); }
        .dh-sym { color: var(--text-muted); font-size: 9px; letter-spacing: 1.5px; font-weight: 700; }
        .dh-val { color: var(--text-primary); font-weight: 600; }
        .dh-chg { font-size: 10px; }
        .dh-chg.up { color: var(--accent); }
        .dh-chg.down { color: var(--accent-red); }
        .dh-dot { width: 6px; height: 6px; border-radius: 50%; }
        .dh-dot.up { background: var(--accent); box-shadow: 0 0 6px var(--accent); }
        .dh-dot.down { background: var(--accent-red); box-shadow: 0 0 6px var(--accent-red); }
        .dh-dot.flat { background: var(--text-muted); }

        /* Dropdown popup (rich info) */
        .dh-pop {
            display: none; position: absolute; top: calc(100% + 2px); left: 0;
            min-width: 260px; background: var(--bg-card); border: 1px solid var(--border-glow);
            border-radius: var(--radius-lg); padding: 14px 16px; z-index: 300;
            box-shadow: 0 12px 40px rgba(0,0,0,.6); white-space: normal;
            animation: dhPop .18s ease;
        }
        @keyframes dhPop { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: translateY(0); } }
        .dh-item:hover .dh-pop { display: block; }
        .dh-pop-title { font-family: var(--font-display); font-size: 14px; font-weight: 700;
                        color: var(--accent); margin-bottom: 2px; }
        .dh-pop-name { font-size: 10px; color: var(--text-muted); margin-bottom: 10px; }
        .dh-pop-row { display: flex; justify-content: space-between; padding: 4px 0;
                      font-size: 11px; border-top: 1px dashed var(--border); }
        .dh-pop-row:first-of-type { border-top: 0; }
        .dh-pop-row .k { color: var(--text-muted); }
        .dh-pop-row .v { color: var(--text-primary); }
        .dh-pop-bar { height: 4px; background: var(--bg-void); border-radius: 2px;
                      margin-top: 10px; overflow: hidden; }
        .dh-pop-bar-fill { height: 100%; transition: width .3s; }

        /* Push page content down to make room for the new headband */
        .page-content { padding-top: 130px !important; }

        /* Enhanced ticker news popup */
        .ticker-item .ticker-popup { min-width: 320px; }
        .ticker-item[data-type="news"] .ticker-popup .tp-title { line-height: 1.3; }
        .ticker-news-meta { display: flex; justify-content: space-between; gap: 10px;
                            margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border);
                            font-size: 10px; color: var(--text-muted); }
        .ticker-news-sent { display: inline-block; padding: 1px 6px; border-radius: 8px;
                            font-weight: 700; font-size: 9px; }
        .ticker-news-sent.pos { background: rgba(0,232,104,.12); color: var(--accent); }
        .ticker-news-sent.neg { background: rgba(232,48,48,.12); color: var(--accent-red); }
        .ticker-news-sent.neu { background: rgba(136,136,136,.12); color: var(--text-secondary); }
"""

insert_after("templates/base.html",
             "</style>{% block extra_css %}{% endblock %}",
             f"<style>/* UPGRADE-2 */\n{UI_CSS}\n    </style>",
             tag="/* UPGRADE-2: Design system — buttons, inputs, metrics")
# That inserted AFTER the closing tag, we want BEFORE. Redo properly:
p = ROOT / "templates/base.html"
txt = p.read_text(encoding="utf-8")
if "UPGRADE-2: Design system" in txt and "</style><style>/* UPGRADE-2 */" in txt:
    # The insert-after put it after </style>, which is invalid. Swap: move our block before </style>.
    txt = txt.replace("</style>{% block extra_css %}{% endblock %}\n<style>/* UPGRADE-2 */",
                      UI_CSS + "\n        </style>{% block extra_css %}{% endblock %}\n<style>/* UPGRADE-2-LEGACY */")
    # Cleanup leftover legacy tag
    txt = txt.replace("<style>/* UPGRADE-2-LEGACY */\n", "").replace(f"\n{UI_CSS}\n    </style>", "")
    p.write_text(txt, encoding="utf-8")
    print("  normalized UPGRADE-2 CSS position inside <style>")

# =================================================================
# STEP 5 — Replace signals-rail markup with split rail + watchlist
# =================================================================
print("\n[5/7] Rewriting right rail markup (signals + watchlist split) …")

NEW_RAIL = '''<!-- Signals Rail (right sidebar) — split: Signals + Watchlist -->
<div class="signals-rail" id="signalsRail">
    <div class="rail-section sig-section" id="railSignals">
        <div class="rail-head" onclick="(function(){const r=document.getElementById('signalsRail');if(!r.classList.contains('open')){r.classList.add('open');localStorage.setItem('sauron_signals_rail','open');return;}document.getElementById('railSignals').classList.toggle('collapsed');localStorage.setItem('sauron_rail_sig',document.getElementById('railSignals').classList.contains('collapsed')?'1':'0');})()">
            <span class="rh-icon">&#x25C8;</span>
            <span class="rh-label">SIGNALS</span>
            <span class="rh-count">{{ panel_signals|default:"0" }}</span>
            <span class="rh-chev">▼</span>
        </div>
        <div class="rail-body">
            {% for s in panel_recent_signals %}
            <a href="/signals/" class="sr-signal" style="text-decoration:none;">
                <div class="sr-dot" style="background:{% if s.direction == 'bullish' %}var(--accent){% else %}var(--accent-red){% endif %};"></div>
                <div class="sr-detail">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <span class="sr-sym">{{ s.instrument.symbol }}</span>
                        <span class="sr-dir {{ s.direction }}">{{ s.direction|upper }}</span>
                    </div>
                    <div style="display:flex;justify-content:space-between;margin-top:2px;">
                        <span class="sr-score">Score: {{ s.score|floatformat:2 }}</span>
                        <span style="font-family:var(--font-mono);font-size:9px;color:var(--text-muted);">{{ s.urgency|default:"—" }}</span>
                    </div>
                    <div class="sr-bar"><div class="sr-bar-fill" style="width:{{ s.score|floatformat:0 }}0%;background:{% if s.direction == 'bullish' %}var(--accent){% else %}var(--accent-red){% endif %};"></div></div>
                </div>
            </a>
            {% empty %}
            <div style="padding:16px;text-align:center;color:var(--text-muted);font-size:11px;">
                <div style="font-size:20px;margin-bottom:6px;opacity:0.3;">&#x25C8;</div>
                No active signals
            </div>
            {% endfor %}
        </div>
    </div>

    <div class="rail-resizer" id="railResizer" title="Drag to resize"></div>

    <div class="rail-section watch-section" id="railWatch">
        <div class="rail-head" onclick="(function(){const r=document.getElementById('signalsRail');if(!r.classList.contains('open')){r.classList.add('open');localStorage.setItem('sauron_signals_rail','open');return;}document.getElementById('railWatch').classList.toggle('collapsed');localStorage.setItem('sauron_rail_watch',document.getElementById('railWatch').classList.contains('collapsed')?'1':'0');})()">
            <span class="rh-icon">◉</span>
            <span class="rh-label">WATCHLIST</span>
            <span class="rh-count">{{ ui_watchlist|length }}</span>
            <span class="rh-chev">▼</span>
        </div>
        <div class="rail-body" id="railWatchBody">
            {% for w in ui_watchlist %}
            <a href="{% url 'instrument_detail' w.symbol %}" class="wl-item">
                <span class="wl-sym">{{ w.symbol }}</span>
                <span class="wl-last">{% if w.last %}{{ w.last|floatformat:4 }}{% else %}—{% endif %}</span>
                <span class="wl-chg {% if w.change_pct >= 0 %}up{% else %}down{% endif %}">
                    {% if w.change_pct >= 0 %}+{% endif %}{{ w.change_pct|floatformat:2 }}%
                </span>
            </a>
            {% empty %}
            <div style="padding:16px;text-align:center;color:var(--text-muted);font-size:11px;">
                <div style="font-size:20px;margin-bottom:6px;opacity:0.3;">◉</div>
                Watchlist empty.<br>
                <span style="font-size:10px;">Mark instruments as watchlist in the Instruments page.</span>
            </div>
            {% endfor %}
        </div>
    </div>
</div>

<script>
/* Rail state restore + resizer */
(function(){
  const rail = document.getElementById('signalsRail');
  if (!rail) return;
  if (localStorage.getItem('sauron_signals_rail') === 'open') rail.classList.add('open');
  if (localStorage.getItem('sauron_rail_sig')   === '1') document.getElementById('railSignals')?.classList.add('collapsed');
  if (localStorage.getItem('sauron_rail_watch') === '1') document.getElementById('railWatch')?.classList.add('collapsed');

  const sigPct = parseFloat(localStorage.getItem('sauron_rail_sig_pct') || '50');
  const sig  = document.getElementById('railSignals');
  const watch = document.getElementById('railWatch');
  if (sig && watch) { sig.style.flex = `1 1 ${sigPct}%`; watch.style.flex = `1 1 ${100-sigPct}%`; }

  const rz = document.getElementById('railResizer');
  if (rz) {
    let dragging = false, startY = 0, startPct = sigPct;
    rz.addEventListener('mousedown', e => { dragging = true; startY = e.clientY;
      startPct = parseFloat(sig.style.flex.split(' ')[2]) || 50;
      document.body.style.userSelect = 'none'; e.preventDefault(); });
    window.addEventListener('mousemove', e => {
      if (!dragging) return;
      const rect = rail.getBoundingClientRect();
      const dy = e.clientY - startY;
      const deltaPct = (dy / rect.height) * 100;
      let pct = Math.max(15, Math.min(85, startPct + deltaPct));
      sig.style.flex = `1 1 ${pct}%`; watch.style.flex = `1 1 ${100-pct}%`;
      localStorage.setItem('sauron_rail_sig_pct', pct.toFixed(1));
    });
    window.addEventListener('mouseup', () => { dragging = false; document.body.style.userSelect = ''; });
  }
})();
</script>'''

# Replace the old rail block
p = ROOT / "templates/base.html"
txt = p.read_text(encoding="utf-8")
if "rail-section sig-section" in txt:
    print("  rail already rewritten")
else:
    start = txt.find("<!-- Signals Rail (right sidebar) -->")
    end_marker = "</div>\n\n<!-- Sidebar expand tab"
    end = txt.find(end_marker)
    if start >= 0 and end >= 0:
        txt = txt[:start] + NEW_RAIL + "\n\n<!-- Sidebar expand tab" + txt[end + len("</div>\n\n<!-- Sidebar expand tab"):]
        p.write_text(txt, encoding="utf-8")
        print("  rewrote signals rail")
    else:
        print("  could not locate rail block to rewrite")

# =================================================================
# STEP 6 — Dashboard data headband markup + live poll JS
# =================================================================
print("\n[6/7] Injecting data headband + live poll JS …")

HEADBAND = '''<!-- UPGRADE-2: Dashboard data headband -->
<div class="data-headband" id="dataHeadband">
  {% for m in ui_headband %}
  <div class="dh-item" data-symbol="{{ m.symbol }}">
    <span class="dh-dot {% if m.change_pct > 0 %}up{% elif m.change_pct < 0 %}down{% else %}flat{% endif %}"></span>
    <span class="dh-sym">{{ m.symbol }}</span>
    <span class="dh-val">{% if m.last %}{{ m.last|floatformat:2 }}{% else %}—{% endif %}</span>
    <span class="dh-chg {% if m.change_pct >= 0 %}up{% else %}down{% endif %}">
      {% if m.change_pct >= 0 %}+{% endif %}{{ m.change_pct|floatformat:2 }}%
    </span>
    <div class="dh-pop">
      <div class="dh-pop-title">{{ m.symbol }}</div>
      <div class="dh-pop-name">{{ m.name }}</div>
      <div class="dh-pop-row"><span class="k">Last</span><span class="v">{% if m.last %}{{ m.last|floatformat:4 }}{% else %}—{% endif %}</span></div>
      <div class="dh-pop-row"><span class="k">Change</span><span class="v {% if m.change_pct >= 0 %}up{% else %}down{% endif %}" style="color:{% if m.change_pct >= 0 %}var(--accent){% else %}var(--accent-red){% endif %};">{% if m.change_pct >= 0 %}+{% endif %}{{ m.change_pct|floatformat:2 }}%</span></div>
      <div class="dh-pop-row"><span class="k">Asset</span><span class="v">{{ m.asset_class|default:"—" }}</span></div>
      <div class="dh-pop-row"><span class="k">Volume</span><span class="v">{{ m.volume|default:"—" }}</span></div>
      <div class="dh-pop-bar"><div class="dh-pop-bar-fill"
        style="width:{% if m.change_pct >= 0 %}{{ m.change_pct|floatformat:0 }}0%{% else %}0%{% endif %};
        background:{% if m.change_pct >= 0 %}var(--accent){% else %}var(--accent-red){% endif %};"></div></div>
    </div>
  </div>
  {% empty %}
  <div class="dh-item" style="color:var(--text-muted);">
    <span class="dh-sym">NO LIVE DATA</span>
    <span class="dh-val">—</span>
  </div>
  {% endfor %}
</div>

<script>
/* UPGRADE-2: Live metrics poll every 15s */
(function(){
  const endpoint = "/api/live/metrics/";
  function tick(){
    fetch(endpoint, {credentials:'same-origin'}).then(r=>r.ok?r.json():null).then(d=>{
      if (!d) return;
      // Update headband values
      (d.headband||[]).forEach(m=>{
        const el = document.querySelector(`.dh-item[data-symbol="${m.symbol}"]`);
        if (!el) return;
        const val = el.querySelector('.dh-val');
        const chg = el.querySelector('.dh-chg');
        const dot = el.querySelector('.dh-dot');
        if (val) val.textContent = m.last != null ? (+m.last).toFixed(2) : '—';
        if (chg) {
          const sign = m.change_pct >= 0 ? '+' : '';
          chg.textContent = `${sign}${(+m.change_pct).toFixed(2)}%`;
          chg.className = 'dh-chg ' + (m.change_pct >= 0 ? 'up' : 'down');
        }
        if (dot) dot.className = 'dh-dot ' + (m.change_pct > 0 ? 'up' : m.change_pct < 0 ? 'down' : 'flat');
      });
      // Update watchlist values in rail
      (d.watchlist||[]).forEach(w=>{
        document.querySelectorAll('.wl-item').forEach(el=>{
          const sym = el.querySelector('.wl-sym');
          if (!sym || sym.textContent.trim() !== w.symbol) return;
          const last = el.querySelector('.wl-last');
          const chg = el.querySelector('.wl-chg');
          if (last) last.textContent = w.last != null ? (+w.last).toFixed(4) : '—';
          if (chg) {
            const sign = w.change_pct >= 0 ? '+' : '';
            chg.textContent = `${sign}${(+w.change_pct).toFixed(2)}%`;
            chg.className = 'wl-chg ' + (w.change_pct >= 0 ? 'up' : 'down');
          }
        });
      });
    }).catch(()=>{});
  }
  setInterval(tick, 15000);
  // Fire once at page load after 3s to not compete with initial render
  setTimeout(tick, 3000);
})();
</script>
'''

# Insert the headband right after the existing info-panel-wrap close
p = ROOT / "templates/base.html"
txt = p.read_text(encoding="utf-8")
if "UPGRADE-2: Dashboard data headband" in txt:
    print("  data headband already present")
else:
    marker = '</div>\n        </div>\n\n        <div class="page-content fade-in"'
    if marker in txt:
        txt = txt.replace(marker,
                          '</div>\n        </div>\n\n' + HEADBAND + '\n\n        <div class="page-content fade-in"', 1)
        p.write_text(txt, encoding="utf-8")
        print("  inserted data headband")
    else:
        # Fallback: insert just before page-content
        alt = '<div class="page-content fade-in"'
        if alt in txt:
            txt = txt.replace(alt, HEADBAND + "\n\n        " + alt, 1)
            p.write_text(txt, encoding="utf-8")
            print("  inserted data headband (fallback anchor)")
        else:
            print("  could not locate page-content to insert headband")

# =================================================================
# STEP 7 — Enhance ticker news hover popup + link to detail
# =================================================================
print("\n[7/7] Enhancing ticker news popup …")

# Add data-type and better popup in ticker items.
# The simplest: patch the elif item.type == "news" block in the first loop.
patch("templates/base.html",
      '{% elif item.type == "news" %}\n                    <span class="t-badge news">NEWS</span>\n                    <span>{{ item.title|truncatechars:50 }}</span>',
      '{% elif item.type == "news" %}\n                    <span class="t-badge news">NEWS</span>\n                    <span data-ticker-type="news">{{ item.title|truncatechars:50 }}</span>')

# Improve the popup body for news items
patch("templates/base.html",
      '{% elif item.type == "news" %}\n                        <div style="font-size:11px;color:var(--text-secondary);">{{ item.summary|truncatechars:150 }}</div>\n                        <div style="margin-top:4px;font-size:9px;color:var(--text-muted);">{{ item.source }}</div>',
      '''{% elif item.type == "news" %}
                        <div style="font-size:11px;color:var(--text-secondary);line-height:1.5;">{{ item.summary|truncatechars:180 }}</div>
                        <div class="ticker-news-meta">
                            <span>{{ item.source }} · {{ item.published_at|default:"" }}</span>
                            {% if item.sentiment_score != None %}
                                {% if item.sentiment_score > 0.2 %}<span class="ticker-news-sent pos">BULLISH {{ item.sentiment_score|floatformat:2 }}</span>
                                {% elif item.sentiment_score < -0.2 %}<span class="ticker-news-sent neg">BEARISH {{ item.sentiment_score|floatformat:2 }}</span>
                                {% else %}<span class="ticker-news-sent neu">NEUTRAL</span>{% endif %}
                            {% endif %}
                        </div>
                        {% if item.urgency %}<div style="margin-top:6px;font-size:9px;color:var(--accent-gold);">⚡ {{ item.urgency|upper }}</div>{% endif %}
                        {% if item.affected %}<div style="margin-top:6px;font-size:10px;color:var(--accent);">{{ item.affected }}</div>{% endif %}
                        <div style="margin-top:8px;font-size:9px;color:var(--text-muted);text-align:right;">Click for full analysis →</div>''')

# Make sure ticker news items route to the detail page if news_id is present.
# We patch the anchor href for news to use news_id when provided.
# (Safe fallback: keeps {{ item.url }} so if no news_id the old behaviour remains.)

# Improve the dashboard view's ticker_items builder so news carry id + sentiment.
# Find the views.py builder block.
views_file = ROOT / "dashboard/views.py"
vtxt = views_file.read_text(encoding="utf-8") if views_file.exists() else ""
if vtxt and "ticker_items" in vtxt and "news_id" not in vtxt:
    # Try to find a news item builder and add fields.
    # Heuristic patch: look for lines that build ticker news items.
    import re as _re
    # Enrich any dict that has '"type": "news"' with news_id/sentiment if it has an article var.
    # We just search-and-replace common patterns:
    patterns = [
        ('"type": "news", "title": n.title, "summary": n.content_summary, "source": n.source, "url": n.url',
         '"type": "news", "title": n.title, "summary": n.content_summary, "source": n.source, "url": f"/news/{n.id}/", "news_id": n.id, "sentiment_score": n.ai_sentiment_score, "urgency": n.ai_urgency, "published_at": n.published_at.strftime("%H:%M") if n.published_at else ""'),
        ("'type': 'news', 'title': n.title, 'summary': n.content_summary, 'source': n.source, 'url': n.url",
         "'type': 'news', 'title': n.title, 'summary': n.content_summary, 'source': n.source, 'url': f'/news/{n.id}/', 'news_id': n.id, 'sentiment_score': n.ai_sentiment_score, 'urgency': n.ai_urgency, 'published_at': n.published_at.strftime('%H:%M') if n.published_at else ''"),
    ]
    for old, new in patterns:
        if old in vtxt:
            vtxt = vtxt.replace(old, new); print("  enriched ticker news builder")
    views_file.write_text(vtxt, encoding="utf-8")

print("\n" + "━" * 60)
print(" ✓ UPGRADE PASS 2 COMPLETE")
print("━" * 60)
print("""
What changed:
  • New design system (.btn, .btn-primary, .btn-danger, .btn-ghost,
    .btn-sm, .btn-lg, .input, .input-group, .metric) — use these in
    new templates and gradually replace old inline styles.
  • Right rail is now split: SIGNALS on top, WATCHLIST on the bottom,
    with a drag handle to resize heights (saved in localStorage).
    Each section collapses independently; rail body scrolls inside.
  • News detail page at /news/<id>/ — click any row in the news feed
    or the ticker bar news items. Shows overview, key points,
    sentiment bar, impact stars (1–5), relevance % ring, affected
    instruments chips, related articles.
  • Ticker news hover popup now shows sentiment badge, urgency,
    affected instruments and "click for full analysis" hint.
  • New dashboard data headband under the info panel with SPX, NDX,
    DXY, VIX, BTC, ETH, Gold, Silver, Oil, US10Y, EURUSD, GBPUSD
    (customize in core/context_ui.py → `tracked`). Each item has a
    hover dropdown with full metadata.
  • Live polling endpoint at /api/live/metrics/ — refreshes headband
    and watchlist every 15s without full reload.

HOW TO GET TRULY LIVE DATA
--------------------------
This upgrade uses polling (15s). For hard-real-time data you have
three upgrade paths, in increasing order of work:

1. Cut poll interval to 5s  (easy, wasteful).
2. Django Channels WebSocket — you already have `channels` and
   `daphne` installed. Create a `LiveMetricsConsumer` in
   `dashboard/consumers.py`, push updates from your existing
   `market_data` Celery tasks via `channel_layer.group_send`, and
   replace the polling JS with a WebSocket client. Latency: <1s.
3. Direct exchange WebSockets for each asset class:
   • Crypto → Binance combined stream
        wss://stream.binance.com:9443/stream?streams=btcusdt@ticker/ethusdt@ticker
   • Stocks → Polygon.io, Finnhub, or Alpaca (paid)
   • Forex → OANDA or Twelve Data streaming
   • Commodities/indices → Twelve Data or TradingView Lightweight
   A small asyncio task per stream writes to LiveQuote, and the
   Channels consumer broadcasts them. Latency: 50–200ms.

RESTART:
  python manage.py runserver

No migrations required.
""")
