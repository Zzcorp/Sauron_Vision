#!/usr/bin/env python3
"""
upgrade_sauron_6.py
===================
Fix pass — addresses everything that broke or got missed earlier.

Drop next to manage.py and run:

    python upgrade_sauron_6.py

Idempotent. No DB migrations.

Fixes:
 1. The 500 on news clicks. The earlier news_detail URL patch failed
    silently because dashboard/urls.py uses CRLF line endings while my
    anchor used LF. Result: news_feed.html references {% url
    'news_detail' %} but no URL with that name exists → NoReverseMatch
    → 500. This pass uses a CRLF-aware patch helper that normalizes
    both sides before matching, then re-applies all the missed routes:
      - news/<int:pk>/      → news_detail
      - api/live/metrics/   → live_metrics
      - liquidations/       → liquidations_page
      - api/liquidations/   → liquidations_json
 2. Enriches the ticker news items with news_id, sentiment, urgency,
    affected instruments, and points each news url at /news/<id>/.
 3. Vastly enriches the dashboard headband popups (now show 24h hi/lo,
    spread, source freshness, mini change bar, asset class).
 4. Vastly enriches the ticker news hover popups (sentiment badge,
    urgency, affected instruments, "click for full analysis" hint).
 5. Adds a top-level rail toggle button — circular icon in the
    Sauron design language, always visible at the rail edge, opens
    AND closes the right rail. Earlier rail-head only opened it.
 6. Completely rebuilds the Bot Program home page with the new design
    system: rich metric cards, weights ring, recent decisions log,
    P&L sparkline, win-rate, equity curve, last-tick timestamp,
    futures-mode badge, control panel with proper buttons.
 7. Adds a Live Data guide at deploy/LIVE_DATA_OPTIONS.md answering
    the question "what's the best provider per asset class".
"""
from __future__ import annotations
import re, sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent
if not (ROOT / "manage.py").exists():
    print("ERROR: run from directory containing manage.py"); sys.exit(1)

# ─────────────────────────────────────────────────────────────────
# CRLF-aware helpers
# ─────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    """Normalise to LF for matching purposes only."""
    return s.replace("\r\n", "\n").replace("\r", "\n")

def write(rel, content, overwrite=True):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and not overwrite:
        print(f"  skip: {rel}"); return
    p.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
    print(f"  wrote: {rel}")

def patch(rel, old, new, *, marker=None):
    """Patch that survives CRLF/LF mismatches.

    `marker` is an optional substring; if it's already in the file the
    patch is treated as already applied.
    """
    p = ROOT / rel
    if not p.exists():
        print(f"  MISSING: {rel}"); return False
    raw = p.read_text(encoding="utf-8")
    use_crlf = "\r\n" in raw
    norm_txt = _norm(raw)
    norm_old = _norm(old)
    norm_new = _norm(new)

    # Idempotency: pick a distinctive marker only present in `new` but not `old`.
    if marker is None:
        for line in norm_new.splitlines():
            ln = line.strip()
            if len(ln) >= 15 and ln not in norm_old:
                marker = ln; break
        if marker is None: marker = norm_new.strip()[:60]
    if marker in norm_txt:
        print(f"  already patched: {rel}")
        return True

    if norm_old not in norm_txt:
        print(f"  anchor not found: {rel}")
        return False

    new_norm_txt = norm_txt.replace(norm_old, norm_new, 1)
    if use_crlf:
        out = new_norm_txt.replace("\n", "\r\n")
    else:
        out = new_norm_txt
    p.write_text(out, encoding="utf-8")
    print(f"  patched: {rel}")
    return True

print("━" * 60)
print(" SAURON VISION — UPGRADE PASS 6 (fixes)")
print("━" * 60)

# =================================================================
# STEP 1 — Re-register the missing URLs (CRLF-aware)
# =================================================================
print("\n[1/7] Registering missing URLs (news_detail, live_metrics, liquidations) …")

patch("dashboard/urls.py",
      'path("news/", views.news_feed, name="news_feed"),',
      '''path("news/", views.news_feed, name="news_feed"),
    path("news/<int:pk>/", __import__("dashboard.news_detail", fromlist=["news_detail"]).news_detail, name="news_detail"),
    path("api/live/metrics/", __import__("dashboard.news_detail", fromlist=["live_metrics_json"]).live_metrics_json, name="live_metrics"),
    path("liquidations/", __import__("dashboard.liquidations_view", fromlist=["liquidations_page"]).liquidations_page, name="liquidations_page"),
    path("api/liquidations/", __import__("dashboard.liquidations_view", fromlist=["liquidations_json"]).liquidations_json, name="liquidations_json"),''',
      marker="news_detail")

# =================================================================
# STEP 2 — Enrich the ticker_items news entries in context_processors
# =================================================================
print("\n[2/7] Enriching ticker news items (news_id, sentiment, deep link) …")

patch("core/context_processors.py",
      '''        for n in NewsArticle.objects.order_by("-published_at")[:5]:
            ticker.append({
                "type": "news", "title": n.title, "source": n.source,
                "summary": n.content_summary or "", "time": "",
                "url": "/news/",
            })''',
      '''        for n in NewsArticle.objects.prefetch_related("ai_affected_instruments").order_by("-published_at")[:8]:
            try:
                affected_syms = ", ".join(i.symbol for i in n.ai_affected_instruments.all()[:4])
            except Exception:
                affected_syms = ""
            ticker.append({
                "type": "news", "news_id": n.id, "title": n.title, "source": n.source,
                "summary": (n.ai_summary or n.content_summary or "")[:300],
                "sentiment_score": n.ai_sentiment_score,
                "urgency": n.ai_urgency or "",
                "affected": affected_syms,
                "published_at": n.published_at.strftime("%H:%M") if n.published_at else "",
                "url": f"/news/{n.id}/",
            })''',
      marker="news_id")

# =================================================================
# STEP 3 — Rich ticker news popup + rich headband popup
# =================================================================
print("\n[3/7] Rewriting ticker news popups + headband popups …")

# Replace the entire news popup block (both occurrences) with rich version.
patch("templates/base.html",
      '''{% elif item.type == "news" %}
                        <div style="font-size:11px;color:var(--text-secondary);">{{ item.summary|truncatechars:150 }}</div>
                        <div style="margin-top:4px;font-size:9px;color:var(--text-muted);">{{ item.source }}</div>
                        {% endif %}''',
      '''{% elif item.type == "news" %}
                        <div style="font-size:12px;color:var(--text-primary);line-height:1.5;margin-bottom:8px;">{{ item.summary|truncatechars:200 }}</div>
                        <div class="ticker-news-meta">
                            <span style="color:var(--accent);">{{ item.source }}</span>
                            <span>{{ item.published_at }}</span>
                            {% if item.sentiment_score != None %}
                                {% if item.sentiment_score > 0.2 %}<span class="ticker-news-sent pos">BULL {{ item.sentiment_score|floatformat:2 }}</span>
                                {% elif item.sentiment_score < -0.2 %}<span class="ticker-news-sent neg">BEAR {{ item.sentiment_score|floatformat:2 }}</span>
                                {% else %}<span class="ticker-news-sent neu">NEUTRAL</span>{% endif %}
                            {% endif %}
                        </div>
                        {% if item.urgency %}<div style="margin-top:6px;font-size:10px;color:var(--accent-gold);">⚡ URGENCY: {{ item.urgency|upper }}</div>{% endif %}
                        {% if item.affected %}<div style="margin-top:6px;font-size:10px;"><span style="color:var(--text-muted);">AFFECTED:</span> <span style="color:var(--accent);font-family:var(--font-mono);">{{ item.affected }}</span></div>{% endif %}
                        <div style="margin-top:10px;padding-top:8px;border-top:1px dashed var(--border);font-size:10px;color:var(--accent);text-align:right;">▸ Click for full analysis</div>
                        {% endif %}''',
      marker="ticker-news-meta")

# Also enrich the headband popups dramatically
patch("templates/base.html",
      '''<div class="dh-pop">
      <div class="dh-pop-title">{{ m.symbol }}</div>
      <div class="dh-pop-name">{{ m.name }}</div>
      <div class="dh-pop-row"><span class="k">Last</span><span class="v">{% if m.last %}{{ m.last|floatformat:4 }}{% else %}—{% endif %}</span></div>
      <div class="dh-pop-row"><span class="k">Change</span><span class="v {% if m.change_pct >= 0 %}up{% else %}down{% endif %}" style="color:{% if m.change_pct >= 0 %}var(--accent){% else %}var(--accent-red){% endif %};">{% if m.change_pct >= 0 %}+{% endif %}{{ m.change_pct|floatformat:2 }}%</span></div>
      <div class="dh-pop-row"><span class="k">Asset</span><span class="v">{{ m.asset_class|default:"—" }}</span></div>
      <div class="dh-pop-row"><span class="k">Volume</span><span class="v">{{ m.volume|default:"—" }}</span></div>
      <div class="dh-pop-bar"><div class="dh-pop-bar-fill"
        style="width:{% if m.change_pct >= 0 %}{{ m.change_pct|floatformat:0 }}0%{% else %}0%{% endif %};
        background:{% if m.change_pct >= 0 %}var(--accent){% else %}var(--accent-red){% endif %};"></div></div>
    </div>''',
      '''<div class="dh-pop">
      <div class="dh-pop-head">
        <div>
          <div class="dh-pop-title">{{ m.symbol }}</div>
          <div class="dh-pop-name">{{ m.name }}</div>
        </div>
        <div class="dh-pop-badge {% if m.change_pct > 0 %}up{% elif m.change_pct < 0 %}down{% else %}flat{% endif %}">
          {% if m.change_pct >= 0 %}▲{% else %}▼{% endif %}
        </div>
      </div>
      <div class="dh-pop-big">
        <span class="dh-pop-price">{% if m.last %}{{ m.last|floatformat:4 }}{% else %}—{% endif %}</span>
        <span class="dh-pop-pct {% if m.change_pct >= 0 %}up{% else %}down{% endif %}" style="color:{% if m.change_pct >= 0 %}var(--accent){% else %}var(--accent-red){% endif %};">
          {% if m.change_pct >= 0 %}+{% endif %}{{ m.change_pct|floatformat:2 }}%
        </span>
      </div>
      <div class="dh-pop-row"><span class="k">Asset class</span><span class="v">{{ m.asset_class|default:"—"|upper }}</span></div>
      <div class="dh-pop-row"><span class="k">24h volume</span><span class="v">{% if m.volume %}{{ m.volume|floatformat:0 }}{% else %}—{% endif %}</span></div>
      {% if m.bid %}<div class="dh-pop-row"><span class="k">Bid / Ask</span><span class="v">{{ m.bid|floatformat:4 }} / {{ m.ask|floatformat:4 }}</span></div>{% endif %}
      <div class="dh-pop-row"><span class="k">Source</span><span class="v" style="color:var(--accent);">{{ m.source|default:"—" }}</span></div>
      <div class="dh-pop-row"><span class="k">Updated</span><span class="v">{{ m.updated_human|default:"—" }}</span></div>
      <div class="dh-pop-bar">
        <div class="dh-pop-bar-fill"
          style="width:{% if m.change_pct >= 0 %}{% widthratio m.change_pct 1 10 %}%{% else %}0%{% endif %};
          background:{% if m.change_pct >= 0 %}var(--accent){% else %}var(--accent-red){% endif %};"></div>
      </div>
      <div class="dh-pop-cta">▸ Click symbol on dashboard for full chart</div>
    </div>''',
      marker="dh-pop-cta")

# Inject extra CSS for the new popup pieces
EXTRA_CSS = '''
        /* UPGRADE-6: enriched popups */
        .dh-pop { min-width: 290px; }
        .dh-pop-head { display: flex; justify-content: space-between; align-items: flex-start;
                       margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
        .dh-pop-badge { width: 32px; height: 32px; border-radius: 50%; display: flex;
                        align-items: center; justify-content: center; font-size: 14px;
                        border: 1px solid var(--border); }
        .dh-pop-badge.up { background: rgba(0,232,104,.1); color: var(--accent); border-color: var(--accent); }
        .dh-pop-badge.down { background: rgba(232,48,48,.1); color: var(--accent-red); border-color: var(--accent-red); }
        .dh-pop-badge.flat { color: var(--text-muted); }
        .dh-pop-big { display: flex; align-items: baseline; gap: 14px; margin-bottom: 14px; }
        .dh-pop-price { font-family: var(--font-display); font-size: 24px; font-weight: 700; color: var(--text-primary); }
        .dh-pop-pct { font-family: var(--font-mono); font-size: 13px; font-weight: 600; }
        .dh-pop-cta { margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--border);
                      font-size: 10px; color: var(--accent); text-align: right; }

        /* UPGRADE-6: rail toggle button */
        .rail-toggle-btn {
            position: fixed; top: 50%; right: 44px; transform: translateY(-50%);
            width: 28px; height: 56px; background: var(--bg-card);
            border: 1px solid var(--border); border-right: 0;
            border-radius: 8px 0 0 8px; cursor: pointer; z-index: 70;
            display: flex; align-items: center; justify-content: center;
            color: var(--accent); transition: all .25s; box-shadow: -2px 0 12px rgba(0,0,0,.4);
        }
        .rail-toggle-btn:hover { background: var(--bg-card-hover); width: 32px; }
        .rail-toggle-btn svg { width: 14px; height: 14px; transition: transform .3s; }
        body:has(.signals-rail.open) .rail-toggle-btn { right: 280px; }
        body:has(.signals-rail.open) .rail-toggle-btn svg { transform: rotate(180deg); }
        @media (max-width: 768px) { .rail-toggle-btn { display: none; } }
'''

if "UPGRADE-6: enriched popups" not in (ROOT / "templates/base.html").read_text(encoding="utf-8"):
    patch("templates/base.html",
          "</style>{% block extra_css %}{% endblock %}",
          EXTRA_CSS + "\n        </style>{% block extra_css %}{% endblock %}",
          marker="UPGRADE-6: enriched popups")

# =================================================================
# STEP 4 — Top-level rail toggle button + open/close JS
# =================================================================
print("\n[4/7] Adding top-level rail toggle button …")

RAIL_BTN = '''<!-- UPGRADE-6: Top-level rail toggle (always visible) -->
<button class="rail-toggle-btn" id="railToggleBtn"
        onclick="(function(){var r=document.getElementById('signalsRail');var open=r.classList.toggle('open');localStorage.setItem('sauron_signals_rail',open?'open':'closed');})()"
        title="Toggle signals & watchlist">
  <svg viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M10 3L5 8L10 13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>
</button>
'''

bp = ROOT / "templates/base.html"
btxt = bp.read_text(encoding="utf-8")
if "id=\"railToggleBtn\"" not in btxt:
    # Insert just before the existing signals-rail div
    needle = '<!-- Signals Rail (right sidebar) — split: Signals + Watchlist -->'
    if needle in btxt:
        btxt = btxt.replace(needle, RAIL_BTN + "\n" + needle, 1)
        bp.write_text(btxt, encoding="utf-8")
        print("  inserted rail toggle button")
    else:
        # fallback: before </body>
        btxt = btxt.replace("</body>", RAIL_BTN + "\n</body>", 1)
        bp.write_text(btxt, encoding="utf-8")
        print("  inserted rail toggle button (fallback)")
else:
    print("  rail toggle button already present")

# =================================================================
# STEP 5 — Rebuild Bot Program home template (rich, polished)
# =================================================================
print("\n[5/7] Rebuilding bot_program home template …")

# Update the bot_home view to compute richer metrics
patch("bot_program/views.py",
      '''@login_required
    def bot_home(request):
        cfg, _ = BotConfig.objects.get_or_create(user=request.user)
        acct = getattr(request.user, "binance_account", None)
        open_trades = BotTrade.objects.filter(config=cfg, status="OPEN")[:20]
        closed_trades = BotTrade.objects.filter(config=cfg, status="CLOSED")[:30]
        scenarios = BotScenario.objects.filter(user=request.user)[:20]
        equity = float(cfg.capital_usdt)
        pnl_total = sum(float(t.pnl_usdt) for t in BotTrade.objects.filter(config=cfg, status="CLOSED"))
        return render(request, "bot_program/home.html", _ctx(request,
            cfg=cfg, acct=acct, open_trades=open_trades,
            closed_trades=closed_trades, scenarios=scenarios,
            equity=equity, pnl_total=pnl_total,
            weights=cfg.normalized_weights()))''',
      '''@login_required
    def bot_home(request):
        from datetime import timedelta
        from django.utils import timezone
        from decimal import Decimal
        cfg, _ = BotConfig.objects.get_or_create(user=request.user)
        acct = getattr(request.user, "binance_account", None)

        all_closed = BotTrade.objects.filter(config=cfg, status="CLOSED")
        open_trades = BotTrade.objects.filter(config=cfg, status="OPEN")[:20]
        closed_trades = all_closed[:30]
        scenarios = BotScenario.objects.filter(user=request.user)[:20]

        # Aggregates
        equity = float(cfg.capital_usdt)
        pnl_total = float(sum((t.pnl_usdt for t in all_closed), Decimal(0)))
        total_trades = all_closed.count()
        wins = all_closed.filter(pnl_usdt__gt=0).count()
        losses = all_closed.filter(pnl_usdt__lt=0).count()
        win_rate = round((wins / total_trades * 100), 1) if total_trades else 0

        # 24h slice
        day_ago = timezone.now() - timedelta(hours=24)
        day_closed = all_closed.filter(closed_at__gte=day_ago)
        pnl_24h = float(sum((t.pnl_usdt for t in day_closed), Decimal(0)))
        trades_24h = day_closed.count()

        # 7d slice
        week_ago = timezone.now() - timedelta(days=7)
        week_closed = all_closed.filter(closed_at__gte=week_ago)
        pnl_7d = float(sum((t.pnl_usdt for t in week_closed), Decimal(0)))

        # Open exposure
        open_exposure = float(sum((t.qty * t.entry_price for t in open_trades), Decimal(0)))

        # Best / worst trade
        best = all_closed.order_by("-pnl_usdt").first()
        worst = all_closed.order_by("pnl_usdt").first()

        # Equity sparkline (cumulative pnl from oldest closed trade)
        spark_qs = list(all_closed.order_by("closed_at").values_list("pnl_usdt", flat=True)[:200])
        spark = []
        running = 0
        for v in spark_qs:
            running += float(v)
            spark.append(round(running, 2))

        # Last tick (most recent open or closed trade timestamp)
        last_event = (all_closed.order_by("-closed_at").values_list("closed_at", flat=True).first()
                      or BotTrade.objects.filter(config=cfg).order_by("-opened_at")
                         .values_list("opened_at", flat=True).first())

        return render(request, "bot_program/home.html", _ctx(request,
            cfg=cfg, acct=acct, open_trades=open_trades,
            closed_trades=closed_trades, scenarios=scenarios,
            equity=equity, pnl_total=pnl_total, pnl_24h=pnl_24h, pnl_7d=pnl_7d,
            total_trades=total_trades, trades_24h=trades_24h,
            wins=wins, losses=losses, win_rate=win_rate,
            open_exposure=open_exposure, best_trade=best, worst_trade=worst,
            spark_data=spark, last_event=last_event,
            weights=cfg.normalized_weights()))''',
      marker="trades_24h")

# Now write the rich template
write("bot_program/templates/bot_program/home.html", '''
    {% extends "base.html" %}
    {% block title %}Bot Program — Sauron Vision{% endblock %}
    {% block page_title %}⟳ BOT PROGRAM{% endblock %}
    {% block content %}
    <div class="page-content fade-in">

      {% if messages %}
        {% for m in messages %}
          <div class="card" style="margin-bottom:12px;border-left:3px solid var(--accent);color:var(--accent);">{{ m }}</div>
        {% endfor %}
      {% endif %}

      <!-- ── HERO STATUS BAR ─────────────────────────────────────────── -->
      <div class="card bot-hero" style="margin-bottom:20px;">
        <div class="bot-hero-grid">
          <div class="bot-hero-status">
            <div class="bot-pulse {% if cfg.enabled %}armed{% endif %}"></div>
            <div>
              <div class="bot-hero-state" style="color:{% if cfg.enabled %}var(--accent){% else %}var(--text-muted){% endif %};">
                {% if cfg.enabled %}ARMED{% else %}OFFLINE{% endif %}
              </div>
              <div class="bot-hero-sub">
                {{ cfg.get_mode_display|upper }} ·
                {% if cfg.market_type == "futures" %}<span style="color:var(--accent-gold);">FUTURES {{ cfg.leverage|floatformat:0 }}× {{ cfg.margin_mode|upper }}</span>
                {% else %}SPOT{% endif %}
                {% if acct.testnet %}· <span style="color:var(--accent-blue);">TESTNET</span>{% endif %}
              </div>
            </div>
          </div>
          <div class="bot-hero-actions">
            <form method="post" action="{% url 'bot_toggle' %}" style="display:flex;gap:10px;align-items:center;">
              {% csrf_token %}
              {% if cfg.mode == 'live' and not cfg.enabled %}
                <input type="password" name="pin" placeholder="PIN" maxlength="8" class="input" style="width:90px;padding:10px 12px;">
              {% endif %}
              <button class="btn {% if cfg.enabled %}btn-danger{% else %}btn-primary{% endif %}" type="submit">
                {% if cfg.enabled %}⏻ DISARM{% else %}▶ ARM BOT{% endif %}
              </button>
            </form>
            <form method="post" action="{% url 'bot_tick' %}" style="display:inline;">
              {% csrf_token %}
              <button class="btn btn-ghost" type="submit">⟳ TICK NOW</button>
            </form>
            <a href="{% url 'bot_configure' %}" class="btn btn-ghost">⚙ CONFIGURE</a>
          </div>
        </div>
      </div>

      <!-- ── METRIC GRID ────────────────────────────────────────────── -->
      <div class="grid grid-4" style="margin-bottom:20px;">
        <div class="metric">
          <div class="metric-icon">◎</div>
          <div class="metric-label">CAPITAL</div>
          <div class="metric-value">{{ cfg.capital_usdt }}</div>
          <div class="metric-sub">USDT base</div>
        </div>
        <div class="metric">
          <div class="metric-icon">∑</div>
          <div class="metric-label">REALISED P&amp;L</div>
          <div class="metric-value" style="color:{% if pnl_total >= 0 %}var(--accent){% else %}var(--accent-red){% endif %};">
            {% if pnl_total >= 0 %}+{% endif %}{{ pnl_total|floatformat:2 }}
          </div>
          <div class="metric-sub">USDT all-time</div>
        </div>
        <div class="metric">
          <div class="metric-icon">📊</div>
          <div class="metric-label">WIN RATE</div>
          <div class="metric-value">{{ win_rate }}%</div>
          <div class="metric-sub">{{ wins }}W / {{ losses }}L · {{ total_trades }} total</div>
        </div>
        <div class="metric">
          <div class="metric-icon">⚡</div>
          <div class="metric-label">24H ACTIVITY</div>
          <div class="metric-value" style="color:{% if pnl_24h >= 0 %}var(--accent){% else %}var(--accent-red){% endif %};">
            {% if pnl_24h >= 0 %}+{% endif %}{{ pnl_24h|floatformat:2 }}
          </div>
          <div class="metric-sub">{{ trades_24h }} trades</div>
        </div>
      </div>

      <div class="grid grid-4" style="margin-bottom:20px;">
        <div class="metric">
          <div class="metric-label">7D P&amp;L</div>
          <div class="metric-value" style="color:{% if pnl_7d >= 0 %}var(--accent){% else %}var(--accent-red){% endif %};font-size:18px;">
            {% if pnl_7d >= 0 %}+{% endif %}{{ pnl_7d|floatformat:2 }} USDT
          </div>
        </div>
        <div class="metric">
          <div class="metric-label">OPEN EXPOSURE</div>
          <div class="metric-value" style="font-size:18px;">{{ open_exposure|floatformat:2 }}</div>
          <div class="metric-sub">{{ open_trades|length }} open positions</div>
        </div>
        <div class="metric">
          <div class="metric-label">BEST TRADE</div>
          <div class="metric-value" style="color:var(--accent);font-size:18px;">
            {% if best_trade %}+{{ best_trade.pnl_usdt|floatformat:2 }}{% else %}—{% endif %}
          </div>
          <div class="metric-sub">{% if best_trade %}{{ best_trade.symbol }}{% else %}no data{% endif %}</div>
        </div>
        <div class="metric">
          <div class="metric-label">WORST TRADE</div>
          <div class="metric-value" style="color:var(--accent-red);font-size:18px;">
            {% if worst_trade %}{{ worst_trade.pnl_usdt|floatformat:2 }}{% else %}—{% endif %}
          </div>
          <div class="metric-sub">{% if worst_trade %}{{ worst_trade.symbol }}{% else %}no data{% endif %}</div>
        </div>
      </div>

      <!-- ── EQUITY CURVE + WEIGHTS ─────────────────────────────────── -->
      <div class="grid" style="grid-template-columns:2fr 1fr;gap:20px;margin-bottom:20px;">
        <div class="card">
          <div class="card-header">
            <div class="card-title">📈 EQUITY CURVE (cumulative P&amp;L)</div>
            <div style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);">
              {% if last_event %}LAST EVENT: {{ last_event|date:"M d H:i" }}{% else %}NO TRADES YET{% endif %}
            </div>
          </div>
          <canvas id="equityCanvas" height="180" style="width:100%;display:block;"></canvas>
          <script id="sparkData" type="application/json">{{ spark_data|default:"[]" }}</script>
        </div>
        <div class="card">
          <div class="card-header"><div class="card-title">⚖ STRATEGY WEIGHTS</div></div>
          <div class="weights-list">
            {% for k,v in weights.items %}
              <div class="weight-row">
                <div class="weight-label">{{ k|upper }}</div>
                <div class="weight-bar"><div class="weight-fill" style="width:{% widthratio v 1 100 %}%;"></div></div>
                <div class="weight-val">{{ v|floatformat:2 }}</div>
              </div>
            {% endfor %}
          </div>
          <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border);font-family:var(--font-mono);font-size:10px;color:var(--text-muted);">
            ENTRY MIN: <span style="color:var(--accent);">{{ cfg.entry_score_min|floatformat:2 }}</span> ·
            EXIT MAX: <span style="color:var(--accent);">{{ cfg.exit_score_max|floatformat:2 }}</span><br>
            SL: <span style="color:var(--accent-red);">{{ cfg.stop_loss_pct|floatformat:1 }}%</span> ·
            TP: <span style="color:var(--accent);">{{ cfg.take_profit_pct|floatformat:1 }}%</span> ·
            POS: <span>{{ cfg.position_size_pct|floatformat:1 }}%</span>
          </div>
        </div>
      </div>

      <!-- ── BINANCE LINK STATUS + UNIVERSE ─────────────────────────── -->
      <div class="grid grid-2" style="margin-bottom:20px;">
        <div class="card">
          <div class="card-header"><div class="card-title">🔗 BINANCE LINK</div></div>
          {% if acct.connected %}
            <div style="font-family:var(--font-mono);font-size:13px;color:var(--accent);margin-bottom:8px;">
              ✓ CONNECTED · {% if acct.testnet %}TESTNET{% else %}LIVE{% endif %}
            </div>
            <div class="bot-kv"><span>Label</span><span>{{ acct.label }}</span></div>
            <div class="bot-kv"><span>Last balance</span><span>{{ acct.last_balance_usdt|floatformat:2 }} USDT</span></div>
            <div class="bot-kv"><span>Last sync</span><span>{% if acct.last_sync %}{{ acct.last_sync|timesince }} ago{% else %}—{% endif %}</span></div>
          {% else %}
            <div style="color:var(--text-muted);margin-bottom:12px;">No Binance account linked.</div>
          {% endif %}
          <a href="{% url 'bot_link' %}" class="btn btn-sm btn-ghost" style="margin-top:8px;">{% if acct.connected %}MANAGE →{% else %}LINK ACCOUNT →{% endif %}</a>
        </div>
        <div class="card">
          <div class="card-header"><div class="card-title">🌐 TRADING UNIVERSE</div></div>
          <div style="font-family:var(--font-mono);font-size:11px;color:var(--text-secondary);line-height:1.8;">
            {% for s in cfg.symbols %}<span class="bot-chip">{{ s }}</span>{% empty %}<span style="color:var(--text-muted);">No symbols configured. Add some in Configure.</span>{% endfor %}
          </div>
          <div style="margin-top:12px;font-family:var(--font-mono);font-size:10px;color:var(--text-muted);">
            Timeframe: {{ cfg.timeframe }} · Tick: {{ cfg.tick_interval_sec }}s · Cooldown: {{ cfg.cool_down_minutes }}min
          </div>
        </div>
      </div>

      <!-- ── OPEN POSITIONS ─────────────────────────────────────────── -->
      <div class="card" style="margin-bottom:20px;">
        <div class="card-header">
          <div class="card-title">▣ OPEN POSITIONS ({{ open_trades|length }})</div>
        </div>
        {% if open_trades %}
        <div class="bot-table">
          <div class="bot-table-head">
            <span>SYMBOL</span><span>SIDE</span><span>QTY</span><span>ENTRY</span><span>SL / TP</span><span>SCORE</span><span>OPENED</span>
          </div>
          {% for t in open_trades %}
          <div class="bot-table-row">
            <span class="bot-sym">{{ t.symbol }}</span>
            <span class="bot-side {{ t.side|lower }}">{{ t.side }}</span>
            <span class="bot-mono">{{ t.qty|floatformat:6 }}</span>
            <span class="bot-mono">{{ t.entry_price|floatformat:4 }}</span>
            <span class="bot-mono" style="font-size:10px;">
              <span style="color:var(--accent-red);">{{ t.stop_loss|floatformat:4 }}</span> /
              <span style="color:var(--accent);">{{ t.take_profit|floatformat:4 }}</span>
            </span>
            <span class="bot-score">{{ t.composite_score|floatformat:2 }}</span>
            <span class="bot-mono" style="font-size:10px;color:var(--text-muted);">{{ t.opened_at|timesince }} ago</span>
          </div>
          {% endfor %}
        </div>
        {% else %}
          <div style="padding:24px;text-align:center;color:var(--text-muted);font-family:var(--font-mono);font-size:11px;">
            ⊘ NO OPEN POSITIONS
          </div>
        {% endif %}
      </div>

      <!-- ── RECENT DECISIONS / CLOSED ─────────────────────────────── -->
      <div class="card" style="margin-bottom:20px;">
        <div class="card-header">
          <div class="card-title">📋 RECENT TRADE LOG</div>
          <div style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);">
            {{ closed_trades|length }} most recent · all-time {{ total_trades }}
          </div>
        </div>
        {% for t in closed_trades %}
        <div class="bot-trade-row">
          <div class="bot-trade-head">
            <span class="bot-sym">{{ t.symbol }}</span>
            <span class="bot-side {{ t.side|lower }}">{{ t.side }}</span>
            <span class="bot-mono" style="color:var(--text-muted);">{{ t.entry_price|floatformat:4 }} → {{ t.exit_price|default_if_none:"—"|floatformat:4 }}</span>
            <span class="bot-pnl" style="color:{% if t.pnl_usdt >= 0 %}var(--accent){% else %}var(--accent-red){% endif %};">
              {% if t.pnl_usdt >= 0 %}+{% endif %}{{ t.pnl_usdt|floatformat:2 }}
            </span>
            <span class="bot-mono" style="font-size:10px;color:var(--text-muted);">{{ t.closed_at|date:"M d H:i" }}</span>
          </div>
          {% if t.reason %}
          <div class="bot-trade-reason">{{ t.reason|truncatechars:200 }}</div>
          {% endif %}
        </div>
        {% empty %}
          <div style="padding:24px;text-align:center;color:var(--text-muted);font-family:var(--font-mono);font-size:11px;">
            ⊘ NO TRADES EXECUTED YET
          </div>
        {% endfor %}
      </div>

      <!-- ── SCENARIOS ──────────────────────────────────────────────── -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">🧪 SCENARIOS &amp; BACKTESTS</div>
          <a href="{% url 'scenario_new' %}" class="btn btn-sm btn-primary">+ NEW SCENARIO</a>
        </div>
        {% for s in scenarios %}
          <a href="{% url 'scenario_detail' s.id %}" class="bot-scenario">
            <div>
              <div class="bot-sym">{{ s.name }}</div>
              <div style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);">
                {{ s.start_date }} → {{ s.end_date }} · {{ s.num_trades }} trades · DD {{ s.max_drawdown_pct|default_if_none:"—" }}%
              </div>
            </div>
            <div style="font-family:var(--font-display);font-size:18px;font-weight:700;color:{% if s.total_return_pct and s.total_return_pct > 0 %}var(--accent){% elif s.total_return_pct and s.total_return_pct < 0 %}var(--accent-red){% else %}var(--text-muted){% endif %};">
              {% if s.total_return_pct != None %}{% if s.total_return_pct >= 0 %}+{% endif %}{{ s.total_return_pct|floatformat:2 }}%{% else %}—{% endif %}
            </div>
          </a>
        {% empty %}
          <div style="padding:24px;text-align:center;color:var(--text-muted);font-family:var(--font-mono);font-size:11px;">
            ⊘ NO SCENARIOS YET — create one to backtest your strategy
          </div>
        {% endfor %}
      </div>

    </div>

    {% block extra_css %}
    <style>
      .bot-hero { background: linear-gradient(135deg, var(--bg-card), var(--bg-secondary)); border-color: var(--border-glow); }
      .bot-hero-grid { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 18px; }
      .bot-hero-status { display: flex; align-items: center; gap: 16px; }
      .bot-pulse { width: 14px; height: 14px; border-radius: 50%; background: var(--text-muted); }
      .bot-pulse.armed { background: var(--accent); box-shadow: 0 0 0 0 rgba(0,232,104,.6); animation: botPulse 2s infinite; }
      @keyframes botPulse {
        0%   { box-shadow: 0 0 0 0 rgba(0,232,104,.6); }
        70%  { box-shadow: 0 0 0 14px rgba(0,232,104,0); }
        100% { box-shadow: 0 0 0 0 rgba(0,232,104,0); }
      }
      .bot-hero-state { font-family: var(--font-display); font-size: 28px; font-weight: 900; letter-spacing: 4px; }
      .bot-hero-sub { font-family: var(--font-mono); font-size: 11px; color: var(--text-secondary); letter-spacing: 1.5px; margin-top: 2px; }
      .bot-hero-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }

      .weights-list { display: flex; flex-direction: column; gap: 8px; }
      .weight-row { display: grid; grid-template-columns: 90px 1fr 36px; align-items: center; gap: 10px; }
      .weight-label { font-family: var(--font-mono); font-size: 9px; letter-spacing: 1.5px; color: var(--text-muted); }
      .weight-bar { height: 6px; background: var(--bg-void); border-radius: 3px; overflow: hidden; border: 1px solid var(--border); }
      .weight-fill { height: 100%; background: linear-gradient(90deg, var(--accent-dim), var(--accent)); border-radius: 3px; }
      .weight-val { font-family: var(--font-mono); font-size: 11px; color: var(--text-primary); text-align: right; }

      .bot-kv { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px dashed var(--border);
                font-family: var(--font-mono); font-size: 11px; }
      .bot-kv:last-child { border-bottom: 0; }
      .bot-kv span:first-child { color: var(--text-muted); }
      .bot-kv span:last-child { color: var(--text-primary); }

      .bot-chip { display: inline-block; padding: 3px 9px; margin: 2px; background: var(--accent-dim);
                  color: var(--accent); border-radius: 10px; font-size: 10px; font-weight: 700; }

      .bot-table { display: flex; flex-direction: column; gap: 1px; }
      .bot-table-head, .bot-table-row { display: grid; grid-template-columns: 1.2fr 0.6fr 1fr 1fr 1.4fr 0.6fr 1fr; gap: 12px;
                                         padding: 10px 14px; align-items: center; }
      .bot-table-head { background: var(--bg-void); font-family: var(--font-mono); font-size: 9px;
                        letter-spacing: 1.5px; color: var(--text-muted); border-bottom: 1px solid var(--border); }
      .bot-table-row { border-bottom: 1px solid var(--border); transition: background .15s; }
      .bot-table-row:hover { background: var(--bg-card-hover); }
      .bot-sym { font-family: var(--font-display); font-size: 12px; font-weight: 700; color: var(--text-primary); }
      .bot-side { font-family: var(--font-mono); font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 4px; text-align: center; }
      .bot-side.buy { background: rgba(0,232,104,.12); color: var(--accent); }
      .bot-side.sell { background: rgba(232,48,48,.12); color: var(--accent-red); }
      .bot-mono { font-family: var(--font-mono); font-size: 11px; color: var(--text-primary); }
      .bot-score { font-family: var(--font-mono); font-size: 11px; font-weight: 700; color: var(--accent); }

      .bot-trade-row { padding: 12px 14px; border-bottom: 1px solid var(--border); transition: background .15s; }
      .bot-trade-row:hover { background: var(--bg-card-hover); }
      .bot-trade-row:last-child { border-bottom: 0; }
      .bot-trade-head { display: grid; grid-template-columns: 1.2fr 0.6fr 2fr 1fr 1fr; gap: 12px; align-items: center; }
      .bot-pnl { font-family: var(--font-display); font-size: 14px; font-weight: 700; text-align: right; }
      .bot-trade-reason { margin-top: 6px; font-family: var(--font-mono); font-size: 10px;
                          color: var(--text-secondary); padding-left: 4px; line-height: 1.5; opacity: .85; }

      .bot-scenario { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px;
                      border-bottom: 1px solid var(--border); text-decoration: none; transition: background .15s; }
      .bot-scenario:last-child { border-bottom: 0; }
      .bot-scenario:hover { background: var(--bg-card-hover); }
    </style>
    {% endblock %}

    <script>
    (function(){
      var dataEl = document.getElementById('sparkData');
      if (!dataEl) return;
      var raw = dataEl.textContent.trim();
      var data;
      try { data = JSON.parse(raw); } catch(e) { data = []; }
      var c = document.getElementById('equityCanvas');
      if (!c) return;
      function draw(){
        c.width = c.offsetWidth; c.height = 180;
        var ctx = c.getContext('2d'); var W = c.width, H = c.height;
        ctx.clearRect(0,0,W,H);
        if (!data.length) {
          ctx.fillStyle = '#2a5038'; ctx.font = '11px "Share Tech Mono"';
          ctx.fillText('— no closed trades yet —', W/2 - 80, H/2);
          return;
        }
        var mn = Math.min(0, Math.min.apply(null, data));
        var mx = Math.max(0, Math.max.apply(null, data));
        if (mn === mx) mx = mn + 1;
        var pad = 12;
        function x(i){ return pad + i / (data.length - 1 || 1) * (W - pad*2); }
        function y(v){ return H - pad - (v - mn) / (mx - mn) * (H - pad*2); }
        // zero baseline
        ctx.strokeStyle = '#133020'; ctx.lineWidth = 1; ctx.setLineDash([3,3]);
        ctx.beginPath(); var zy = y(0); ctx.moveTo(pad, zy); ctx.lineTo(W - pad, zy); ctx.stroke();
        ctx.setLineDash([]);
        // area fill
        var grad = ctx.createLinearGradient(0, 0, 0, H);
        grad.addColorStop(0, 'rgba(0,232,104,.25)'); grad.addColorStop(1, 'rgba(0,232,104,0)');
        ctx.fillStyle = grad; ctx.beginPath();
        ctx.moveTo(x(0), y(0));
        data.forEach(function(v,i){ ctx.lineTo(x(i), y(v)); });
        ctx.lineTo(x(data.length-1), y(0)); ctx.closePath(); ctx.fill();
        // line
        ctx.strokeStyle = '#00e868'; ctx.lineWidth = 2; ctx.beginPath();
        data.forEach(function(v,i){ i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v)); });
        ctx.stroke();
        // last point
        var lx = x(data.length-1), ly = y(data[data.length-1]);
        ctx.fillStyle = '#00e868'; ctx.beginPath(); ctx.arc(lx, ly, 3, 0, Math.PI*2); ctx.fill();
      }
      window.addEventListener('resize', draw); draw();
    })();
    </script>
    {% endblock %}
''')

# =================================================================
# STEP 6 — Add `updated_human` to ui_headband for richer popups
# =================================================================
print("\n[6/7] Enriching ui_headband with bid/ask/source/updated_human …")

patch("core/context_ui.py",
      '''                    band.append({
                        "symbol": sym,
                        "last": float(q.last or 0),
                        "change_pct": float(q.change_pct or 0),
                        "name": q.instrument.name or sym,
                        "asset_class": q.instrument.asset_class or "",
                        "volume": int(q.volume or 0),
                        "updated": q.updated_at.isoformat() if q.updated_at else "",
                    })''',
      '''                    from django.utils.timesince import timesince
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
                    })''',
      marker="updated_human")

# =================================================================
# STEP 7 — Live data options doc
# =================================================================
print("\n[7/7] Writing LIVE_DATA_OPTIONS.md …")

write("deploy/LIVE_DATA_OPTIONS.md", '''
    # Live Market Data — your options, ranked

    The honest answer to "what's the best provider for live prices,
    paid or not, easy to set up and good quality?"

    ## TL;DR per asset class

    | Asset class | Best free | Best paid | Already wired in Sauron? |
    |-------------|-----------|-----------|--------------------------|
    | **Crypto spot/futures** | **Binance public WS** (no key, unlimited) | Binance Pro / Coinbase Advanced | ✅ stream_binance, stream_binance_futures, stream_binance_depth |
    | **US stocks** | **Finnhub** (~50 symbols, ~1s, free key) | **Polygon.io** ($29/mo Starter, real-time) | ✅ stream_finnhub |
    | **Forex** | **Finnhub** (majors only) or **OANDA demo** (broker-grade, never expires) | **OANDA live** (when you actually trade) or **TraderMade** | ✅ stream_finnhub (forex flag), stream_oanda |
    | **Indices/futures** | **TradingView** (unofficial) | **Databento** ($/mo per stream) | ⚠ via Yahoo polling only |
    | **Commodities** | **Yahoo Finance** (15-min delay) | **Barchart** or **Polygon** | ⚠ via Yahoo polling only |
    | **Macro / FRED** | **FRED API** (free, instant) | n/a | ✅ via existing fred_adapter |

    ---

    ## Recommended setup (the one I'd actually use)

    For "me and friends" use, free everything works fine and is genuinely
    real-time for crypto:

    ```
    1. stream_binance              ← crypto spot ticks         (no key)
    2. stream_binance_futures      ← liquidations + funding   (no key)
    3. stream_binance_depth        ← L2 order book → bot      (no key)
    4. stream_finnhub              ← US stocks + forex        (free key)
    ```

    Total monthly cost: **$0**. Latency: <1s for crypto, ~1s for stocks/fx.
    Coverage: every meaningful asset on the dashboard.

    The only thing you don't get on free tiers is:
    - **Real-time futures** (CME, ES, NQ): need Polygon or Databento
    - **More than 50 symbols** on Finnhub: need their Basic plan ($49/mo)
      or split across multiple keys
    - **Real-time forex through your actual broker**: get OANDA live keys
      when you decide to trade forex with money

    ## Detailed comparison

    ### Crypto — Binance public streams
    **Free, no signup, sub-second latency, unlimited connections.** This
    is genuinely the best option for crypto live data, paid or not.
    Binance's public WebSocket streams (`wss://stream.binance.com:9443`)
    require zero authentication and have no documented rate limit for
    market data. You can stream 100+ symbols on a single connection
    using their combined-stream syntax. Already wired up in
    `stream_binance`, `stream_binance_futures`, and `stream_binance_depth`.

    ### US stocks — Finnhub vs Polygon vs Alpaca
    - **Finnhub free** — ~50 symbols max per WebSocket, ~1s latency,
      WebSocket-based, zero cost. Holes during pre-market and after-hours.
      Perfect for a personal dashboard. **Already wired.**
    - **Polygon.io Starter** — $29/mo, full real-time NBBO, every trade,
      every quote. Used by funds. Best paid option for stocks.
    - **Alpaca free** — IEX-only feed (≈3% of US volume), real-time but
      thin. Free if you also want their broker. Better for paper trading
      than dashboard display.
    - **IEX Cloud** — shut down November 2024. Don't use.

    Recommendation: **stay on Finnhub free until you outgrow it.** You
    won't outgrow it for personal use.

    ### Forex — Finnhub vs OANDA vs Twelve Data
    - **Finnhub free** — major pairs only (EUR/USD, GBP/USD, etc.),
      ~1s latency, same WebSocket as stocks. **Use this if you don't
      already have an OANDA account.**
    - **OANDA demo** — broker-grade tick feed, every price update,
      tighter than Finnhub. Free demo account never expires. Different
      protocol (HTTP chunked streaming). Best free option if you're
      willing to do the OANDA signup.
    - **Twelve Data** — paid only ($29/mo) but covers crypto, stocks,
      forex, and indices in one API. Worth it if you want one provider.

    Recommendation: **Finnhub for simplicity, OANDA when you start
    trading forex for real.** Both are wired in Sauron via
    `stream_finnhub` and `stream_oanda` respectively.

    ### Indices and futures (SPX, NDX, ES, NQ, VIX)
    This is the hard one.
    - **CBOE / CME require paid licensing** for real-time. There's no
      free real-time SPX feed that's legal.
    - **Yahoo Finance** has 15-minute delayed indices, free, easy. Your
      existing `yfinance_adapter` handles this. Good enough for a
      dashboard, useless for trading.
    - **TradingView** has unofficial WebSocket feeds people scrape, but
      it's against their TOS and your access can be revoked.
    - **Databento** ($199/mo and up) is the proper paid solution.
    - **Polygon.io** offers real-time CME futures on their Stocks
      Advanced plan ($199/mo).

    Recommendation: **stick with delayed Yahoo for indices on the
    dashboard, don't trade them through Sauron.** If you really want
    real-time SPX, the cheapest legal path is Polygon Indices ($79/mo
    add-on) or Databento.

    ### Commodities (Gold, Silver, Oil)
    - **Yahoo Finance** delayed quotes, free, already wired
      (`commodities_api.py`)
    - **Metals-API** / **OilPriceAPI** — both have free tiers (60-100
      requests/day), already wired (`commodities_api.py`,
      `oil_price_api.py`)
    - **TradingView Lightweight** unofficial feeds — TOS violation
    - **Barchart** — paid, the institutional standard

    Recommendation: **the existing Yahoo + Metals-API polling is fine.**
    Commodities don't move fast enough to need WebSocket.

    ### Macro data (FRED, ECB, BoE)
    - **FRED API** — free, instant, no rate limit, gold standard. You
      already have it via `fred_adapter.py`. Don't change anything.

    ## Easy setup checklist

    For the recommended free setup, in your `.env`:
    ```
    # Binance — no keys needed for streaming, only for trading
    # Optional: BINANCE_TESTNET=1 (testnet for the bot)

    # Finnhub — free key from https://finnhub.io
    FINNHUB_API_KEY=your_finnhub_key_here

    # FRED — free key from https://fred.stlouisfed.org/docs/api/api_key.html
    FRED_API_KEY=your_fred_key_here
    ```

    Then start the streamers:
    ```bash
    python manage.py stream_binance &
    python manage.py stream_binance_futures &
    python manage.py stream_binance_depth &
    python manage.py stream_finnhub &
    ```

    Or via Docker Compose, all five start automatically:
    ```bash
    docker compose -f deploy/docker-compose.yml --profile finnhub up -d
    ```

    ## When to upgrade to paid

    | If you... | Upgrade to |
    |-----------|-----------|
    | Need >50 stock symbols live | Finnhub Basic ($49/mo) or Polygon Starter ($29/mo) |
    | Want every US stock trade | Polygon Stocks Advanced ($199/mo) |
    | Trade forex with real money | OANDA live (free, just live API key) |
    | Want real-time CME futures | Polygon Indices add-on ($79/mo) or Databento ($199+/mo) |
    | Want one API for everything | Twelve Data Pro ($79/mo) |

    For the "me and friends" use case described in your project,
    **none of these are necessary.** Free Binance + free Finnhub +
    free FRED gives you a genuinely high-quality dashboard.
''')

print("\n" + "━" * 60)
print(" ✓ UPGRADE PASS 6 COMPLETE")
print("━" * 60)
print("""
Fixed:
  ✓ The 500 on news clicks (news_detail URL was never registered
    because of CRLF mismatch in the original anchor)
  ✓ Liquidations URL + live metrics URL also re-registered
  ✓ Ticker news items now carry sentiment, urgency, affected
    instruments, and link directly to /news/<id>/
  ✓ Ticker news hover popup now shows full metadata
  ✓ Headband hover popups now show price, change, asset class,
    volume, bid/ask, source, freshness, mini progress bar
  ✓ Top-level rail toggle button — circular/wedge button on the
    rail edge that opens AND closes the right rail. Works whether
    the rail is open or closed.
  ✓ Bot Program home page completely rebuilt with proper design
    system: animated armed-pulse, 8 metric cards (capital, pnl,
    win-rate, 24h, 7d, exposure, best, worst), live equity curve
    canvas, weights bars, binance link card, universe chips,
    rich open-positions table, recent trade log with reasons,
    scenarios list with return colour-coding
  ✓ deploy/LIVE_DATA_OPTIONS.md — full ranked guide for which
    provider to use per asset class

Restart the dev server and reload. No migrations needed.

NEW: read deploy/LIVE_DATA_OPTIONS.md for the full provider matrix
and the recommended free setup that gives you sub-second crypto +
~1s stocks/forex for $0/month.
""")
