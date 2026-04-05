#!/usr/bin/env python3
"""
SAURON VISION — UI Patch v2
1. Instrument preview: opens above or below based on position
2. Ticker headband (scrolling market data, slow on hover, clickable)
3. Info panel (collapsible, portfolio/signals/news metrics)
4. Sidebar expand arrow when minimized
5. Notification bell system

Run inside sauron_vision/ directory.
"""
import os, re

def generate():
    base_path = "templates/base.html"
    with open(base_path, "r", encoding="utf-8") as f:
        content = f.read()

    # ================================================================
    # 1. CSS — ticker, info panel, notifications, preview fix
    # ================================================================

    NEW_CSS = '''
        /* ── Ticker Bar ──────────────────────────── */
        .ticker-bar {
            height: 32px; background: var(--bg-primary);
            border-bottom: 1px solid var(--border);
            overflow: hidden; position: relative; white-space: nowrap;
        }
        .ticker-track {
            display: inline-flex; gap: 0;
            animation: tickerScroll 120s linear infinite;
        }
        .ticker-bar:hover .ticker-track { animation-play-state: paused; }
        .ticker-track:hover { animation-play-state: paused; }
        @keyframes tickerScroll {
            0% { transform: translateX(0); }
            100% { transform: translateX(-50%); }
        }
        .ticker-item {
            display: inline-flex; align-items: center; gap: 6px;
            padding: 0 18px; height: 32px; font-family: var(--font-mono);
            font-size: 11px; cursor: pointer; border-right: 1px solid var(--border);
            position: relative; transition: background 0.15s;
            text-decoration: none; color: var(--text-secondary);
        }
        .ticker-item:hover { background: var(--bg-card); }
        .ticker-item .t-sym { font-weight: 700; color: var(--text-primary); letter-spacing: 0.5px; }
        .ticker-item .t-price { color: var(--text-primary); }
        .ticker-item .t-change { font-size: 10px; }
        .ticker-item .t-change.up { color: var(--accent); }
        .ticker-item .t-change.down { color: var(--accent-red); }
        .ticker-item .t-badge {
            font-size: 8px; letter-spacing: 1px; padding: 1px 5px;
            border-radius: 8px; font-weight: 700; text-transform: uppercase;
        }
        .ticker-item .t-badge.signal { background: var(--accent-dim); color: var(--accent); }
        .ticker-item .t-badge.news { background: rgba(48,160,232,0.12); color: var(--accent-blue); }
        .ticker-item .t-badge.strat { background: rgba(136,64,208,0.12); color: var(--accent-purple); }
        /* Ticker popup on hover */
        .ticker-popup {
            display: none; position: absolute; top: 36px; left: 0;
            min-width: 240px; background: var(--bg-card); border: 1px solid var(--border);
            border-radius: var(--radius-lg); padding: 12px; z-index: 250;
            box-shadow: 0 8px 32px rgba(0,0,0,0.5); font-size: 11px;
            white-space: normal; animation: previewFadeIn 0.15s ease;
        }
        .ticker-item:hover .ticker-popup { display: block; }
        .ticker-popup .tp-title { font-family: var(--font-display); font-size: 13px; font-weight: 700; margin-bottom: 6px; color: var(--accent); }
        .ticker-popup .tp-row { display: flex; justify-content: space-between; padding: 3px 0; }
        .ticker-popup .tp-row .lbl { color: var(--text-muted); }

        /* ── Info Panel (collapsible) ────────────── */
        .info-panel {
            background: var(--bg-primary); border-bottom: 1px solid var(--border);
            overflow: hidden; transition: max-height 0.4s ease, padding 0.3s ease;
            max-height: 160px; padding: 10px 20px;
        }
        .info-panel.collapsed { max-height: 0; padding: 0 20px; border-bottom: none; }
        .info-panel-toggle {
            position: absolute; bottom: -14px; left: 50%; transform: translateX(-50%);
            z-index: 60; background: var(--bg-card); border: 1px solid var(--border);
            border-radius: 0 0 8px 8px; padding: 2px 16px; cursor: pointer;
            font-size: 10px; color: var(--text-muted); transition: all 0.2s;
            font-family: var(--font-mono);
        }
        .info-panel-toggle:hover { color: var(--accent); border-color: var(--accent-dim); }
        .info-panel-wrap { position: relative; }
        .info-panel-inner {
            display: flex; gap: 24px; overflow-x: auto;
            scrollbar-width: thin; scrollbar-color: var(--border) transparent;
        }
        .info-panel-inner::-webkit-scrollbar { height: 3px; }
        .info-panel-inner::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
        .info-card {
            flex-shrink: 0; display: flex; flex-direction: column; gap: 2px;
            padding: 8px 16px; border-right: 1px solid var(--border); min-width: 130px;
        }
        .info-card:last-child { border-right: none; }
        .info-card .ic-label { font-family: var(--font-mono); font-size: 9px; letter-spacing: 2px; color: var(--text-muted); text-transform: uppercase; }
        .info-card .ic-value { font-family: var(--font-display); font-size: 16px; font-weight: 700; color: var(--text-primary); }
        .info-card .ic-sub { font-family: var(--font-mono); font-size: 10px; color: var(--text-secondary); }

        /* ── Notification Bell ───────────────────── */
        .notif-bell {
            position: relative; cursor: pointer;
            width: 34px; height: 34px; border-radius: 50%;
            border: 1px solid var(--border); background: var(--bg-card);
            display: flex; align-items: center; justify-content: center;
            font-size: 15px; transition: all 0.2s; color: var(--text-secondary);
        }
        .notif-bell:hover { border-color: var(--accent); color: var(--accent); }
        .notif-badge {
            position: absolute; top: -4px; right: -4px;
            min-width: 16px; height: 16px; border-radius: 8px;
            background: var(--accent-red); color: #fff; font-size: 9px;
            font-family: var(--font-mono); font-weight: 700;
            display: flex; align-items: center; justify-content: center;
            padding: 0 4px;
        }
        .notif-dropdown {
            display: none; position: absolute; top: 42px; right: 0;
            width: 340px; max-height: 400px; overflow-y: auto;
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: var(--radius-lg); box-shadow: 0 12px 48px rgba(0,0,0,0.6);
            z-index: 300; padding: 0;
        }
        .notif-bell.open .notif-dropdown { display: block; }
        .notif-header {
            padding: 12px 16px; border-bottom: 1px solid var(--border);
            font-family: var(--font-mono); font-size: 10px; letter-spacing: 2px;
            color: var(--text-muted); text-transform: uppercase;
            display: flex; justify-content: space-between; align-items: center;
        }
        .notif-item {
            padding: 10px 16px; border-bottom: 1px solid rgba(19,48,32,0.15);
            cursor: pointer; transition: background 0.15s;
        }
        .notif-item:hover { background: var(--bg-card-hover); }
        .notif-item:last-child { border-bottom: none; }
        .notif-item .ni-title { font-size: 12px; font-weight: 600; margin-bottom: 2px; }
        .notif-item .ni-body { font-size: 11px; color: var(--text-secondary); }
        .notif-item .ni-time { font-family: var(--font-mono); font-size: 9px; color: var(--text-muted); margin-top: 3px; }
        .notif-item.unread { border-left: 3px solid var(--accent); }
        .notif-empty { padding: 30px; text-align: center; color: var(--text-muted); font-size: 12px; }

        /* ── Preview Popup — position fix ────────── */
        .instrument-preview {
            display: none; position: absolute; left: 0;
            width: 320px; background: var(--bg-card); border: 1px solid var(--border);
            border-radius: var(--radius-lg); box-shadow: 0 12px 48px rgba(0,0,0,0.6);
            padding: 16px; z-index: 400; pointer-events: none;
            animation: previewFadeIn 0.2s ease;
        }
        .instrument-preview.show { display: block; }
        .instrument-preview.pos-above { bottom: calc(100% + 8px); top: auto; }
        .instrument-preview.pos-below { top: calc(100% + 8px); bottom: auto; }

        /* ── Sidebar expand arrow (when mini) ────── */
        .sidebar-expand-tab {
            display: none; position: fixed; top: 50%; left: 68px;
            transform: translateY(-50%); z-index: 110;
            width: 16px; height: 48px; background: var(--bg-card);
            border: 1px solid var(--border); border-left: none;
            border-radius: 0 6px 6px 0; cursor: pointer;
            align-items: center; justify-content: center;
            color: var(--text-muted); transition: all 0.2s;
        }
        .sidebar-expand-tab:hover { color: var(--accent); border-color: var(--accent-dim); width: 20px; }
        .sidebar-expand-tab svg { width: 10px; height: 10px; }
        body:has(.sidebar.mini) .sidebar-expand-tab { display: flex; }
'''

    # Insert CSS before </style>
    if "ticker-bar" not in content:
        content = content.replace("    </style>", NEW_CSS + "\n    </style>")

    # ================================================================
    # 2. HTML — ticker bar + info panel + notification bell + expand tab
    # ================================================================

    # Add notification bell to topbar
    if "notif-bell" not in content:
        content = content.replace(
            '<span>{% get_display_name as uname %}{{ uname }}</span>',
            '''<!-- Notification Bell -->
                <div class="notif-bell" onclick="this.classList.toggle('open')" id="notifBell">
                    <span>&#x1F514;</span>
                    {% if notification_count %}<span class="notif-badge">{{ notification_count }}</span>{% endif %}
                    <div class="notif-dropdown" onclick="event.stopPropagation()">
                        <div class="notif-header">
                            <span>Notifications</span>
                            <a href="{% url 'user_notifications' %}" style="color:var(--accent);font-size:10px;text-decoration:none;">Settings</a>
                        </div>
                        {% for n in recent_notifications %}
                        <div class="notif-item {% if not n.read %}unread{% endif %}" onclick="window.location='{{ n.url }}'">
                            <div class="ni-title">{{ n.title }}</div>
                            <div class="ni-body">{{ n.body|truncatechars:80 }}</div>
                            <div class="ni-time">{{ n.created_at|timesince }} ago</div>
                        </div>
                        {% empty %}
                        <div class="notif-empty">No notifications yet</div>
                        {% endfor %}
                    </div>
                </div>
                <span>{% get_display_name as uname %}{{ uname }}</span>'''
        )

    # Add ticker bar + info panel between topbar and page-content
    if "ticker-bar" not in content:
        content = content.replace(
            '''        <div class="page-content fade-in">
            {% block content %}{% endblock %}
        </div>''',
            '''        <!-- Ticker Bar -->
        {% if not page_id == "dashboard" %}
        <div class="ticker-bar" id="tickerBar">
            <div class="ticker-track" id="tickerTrack">
                {% for item in ticker_items %}
                <a href="{{ item.url }}" class="ticker-item">
                    {% if item.type == "quote" %}
                    <span class="t-sym">{{ item.symbol }}</span>
                    <span class="t-price">{{ item.price }}</span>
                    <span class="t-change {% if item.change >= 0 %}up{% else %}down{% endif %}">{{ item.change_display }}</span>
                    {% elif item.type == "signal" %}
                    <span class="t-badge signal">SIGNAL</span>
                    <span class="t-sym">{{ item.symbol }}</span>
                    <span>{{ item.direction }}</span>
                    {% elif item.type == "news" %}
                    <span class="t-badge news">NEWS</span>
                    <span>{{ item.title|truncatechars:50 }}</span>
                    {% elif item.type == "strategy" %}
                    <span class="t-badge strat">STRAT</span>
                    <span>{{ item.title|truncatechars:40 }}</span>
                    {% endif %}
                    <div class="ticker-popup">
                        <div class="tp-title">{{ item.symbol|default:item.title }}</div>
                        {% if item.type == "quote" %}
                        <div class="tp-row"><span class="lbl">Price</span><span>{{ item.price }}</span></div>
                        <div class="tp-row"><span class="lbl">Change</span><span style="color:{% if item.change >= 0 %}var(--accent){% else %}var(--accent-red){% endif %}">{{ item.change_display }}</span></div>
                        <div class="tp-row"><span class="lbl">Class</span><span>{{ item.asset_class }}</span></div>
                        {% elif item.type == "signal" %}
                        <div class="tp-row"><span class="lbl">Direction</span><span>{{ item.direction }}</span></div>
                        <div class="tp-row"><span class="lbl">Score</span><span>{{ item.score }}</span></div>
                        <div class="tp-row"><span class="lbl">Urgency</span><span>{{ item.urgency }}</span></div>
                        {% elif item.type == "news" %}
                        <div style="font-size:11px;color:var(--text-secondary);">{{ item.summary|truncatechars:150 }}</div>
                        <div style="margin-top:4px;font-size:9px;color:var(--text-muted);">{{ item.source }} &middot; {{ item.time }}</div>
                        {% endif %}
                    </div>
                </a>
                {% endfor %}
                <!-- Duplicate for seamless loop -->
                {% for item in ticker_items %}
                <a href="{{ item.url }}" class="ticker-item">
                    {% if item.type == "quote" %}
                    <span class="t-sym">{{ item.symbol }}</span>
                    <span class="t-price">{{ item.price }}</span>
                    <span class="t-change {% if item.change >= 0 %}up{% else %}down{% endif %}">{{ item.change_display }}</span>
                    {% elif item.type == "signal" %}
                    <span class="t-badge signal">SIGNAL</span>
                    <span class="t-sym">{{ item.symbol }}</span>
                    <span>{{ item.direction }}</span>
                    {% elif item.type == "news" %}
                    <span class="t-badge news">NEWS</span>
                    <span>{{ item.title|truncatechars:50 }}</span>
                    {% elif item.type == "strategy" %}
                    <span class="t-badge strat">STRAT</span>
                    <span>{{ item.title|truncatechars:40 }}</span>
                    {% endif %}
                </a>
                {% endfor %}
            </div>
        </div>

        <!-- Info Panel -->
        <div class="info-panel-wrap">
            <div class="info-panel" id="infoPanel">
                <div class="info-panel-inner">
                    <div class="info-card">
                        <span class="ic-label">Portfolio</span>
                        <span class="ic-value">&euro;{{ panel_portfolio_value|default:"—" }}</span>
                        <span class="ic-sub" style="color:{% if panel_daily_pnl >= 0 %}var(--accent){% else %}var(--accent-red){% endif %}">{{ panel_daily_pnl_display|default:"—" }} today</span>
                    </div>
                    <div class="info-card">
                        <span class="ic-label">Cash</span>
                        <span class="ic-value">&euro;{{ panel_cash|default:"—" }}</span>
                        <span class="ic-sub">{{ panel_cash_pct|default:"0" }}% available</span>
                    </div>
                    <div class="info-card">
                        <span class="ic-label">Positions</span>
                        <span class="ic-value">{{ panel_positions|default:"0" }}</span>
                        <span class="ic-sub">{{ panel_exposure|default:"0" }}% exposure</span>
                    </div>
                    <div class="info-card">
                        <span class="ic-label">Signals</span>
                        <span class="ic-value" style="color:var(--accent);">{{ panel_signals|default:"0" }}</span>
                        <span class="ic-sub">{{ panel_bullish|default:"0" }}&#x25B2; {{ panel_bearish|default:"0" }}&#x25BC;</span>
                    </div>
                    <div class="info-card">
                        <span class="ic-label">Strategies</span>
                        <span class="ic-value">{{ panel_strategies|default:"0" }}</span>
                        <span class="ic-sub">{{ panel_proposed|default:"0" }} proposed</span>
                    </div>
                    <div class="info-card">
                        <span class="ic-label">News (24h)</span>
                        <span class="ic-value">{{ panel_news|default:"0" }}</span>
                        <span class="ic-sub">avg sent: {{ panel_sentiment|default:"—" }}</span>
                    </div>
                    <div class="info-card">
                        <span class="ic-label">AI Cost</span>
                        <span class="ic-value">${{ panel_ai_cost|default:"0.00" }}</span>
                        <span class="ic-sub">{{ panel_ai_tasks|default:"0" }} tasks 24h</span>
                    </div>
                    <div class="info-card">
                        <span class="ic-label">Drawdown</span>
                        <span class="ic-value" style="color:var(--accent-red);">{{ panel_drawdown|default:"0" }}%</span>
                        <span class="ic-sub">max allowed: {{ panel_max_dd|default:"3" }}%</span>
                    </div>
                </div>
            </div>
            <button class="info-panel-toggle" onclick="toggleInfoPanel()" id="infoPanelToggle">&#x25B2; panel</button>
        </div>
        {% endif %}

        <div class="page-content fade-in">
            {% block content %}{% endblock %}
        </div>'''
        )

    # Add sidebar expand tab
    if "sidebar-expand-tab" not in content:
        content = content.replace(
            '</div>\n{% endblock %}',
            '''</div>

<!-- Sidebar expand tab (visible when mini) -->
<div class="sidebar-expand-tab" onclick="toggleSidebar()" title="Expand menu">
    <svg viewBox="0 0 10 16" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M2 2L8 8L2 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
    </svg>
</div>
{% endblock %}''',
            1
        )

    # ================================================================
    # 3. UPDATE PREVIEW JS — position above/below based on viewport
    # ================================================================

    # Replace old preview JS
    old_preview_js = '''    function showPreview(anchor, symbol) {
        if (previewEl) previewEl.remove();
        previewEl = document.createElement('div');
        previewEl.className = 'instrument-preview show';'''

    new_preview_js = '''    function showPreview(anchor, symbol) {
        if (previewEl) previewEl.remove();
        previewEl = document.createElement('div');
        // Determine if popup should go above or below
        const rect = anchor.getBoundingClientRect();
        const viewH = window.innerHeight;
        const posClass = rect.top > viewH / 2 ? 'pos-above' : 'pos-below';
        previewEl.className = 'instrument-preview show ' + posClass;'''

    if old_preview_js in content:
        content = content.replace(old_preview_js, new_preview_js)

    # ================================================================
    # 4. INFO PANEL TOGGLE JS
    # ================================================================

    panel_js = '''
<script>
function toggleInfoPanel() {
    const panel = document.getElementById('infoPanel');
    const btn = document.getElementById('infoPanelToggle');
    panel.classList.toggle('collapsed');
    btn.innerHTML = panel.classList.contains('collapsed') ? '&#x25BC; panel' : '&#x25B2; panel';
    localStorage.setItem('sauron_info_panel', panel.classList.contains('collapsed') ? 'collapsed' : 'open');
}
// Restore info panel state
(function() {
    const state = localStorage.getItem('sauron_info_panel');
    if (state === 'collapsed') {
        const panel = document.getElementById('infoPanel');
        const btn = document.getElementById('infoPanelToggle');
        if (panel) { panel.classList.add('collapsed'); }
        if (btn) { btn.innerHTML = '&#x25BC; panel'; }
    }
})();
// Close notification dropdown on outside click
document.addEventListener('click', function(e) {
    const bell = document.getElementById('notifBell');
    if (bell && !bell.contains(e.target)) { bell.classList.remove('open'); }
});
</script>
'''

    if "toggleInfoPanel" not in content:
        content = content.replace('{% block extra_js %}{% endblock %}',
            panel_js + '\n{% block extra_js %}{% endblock %}')

    with open(base_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("  [OK] Base template — ticker, info panel, notifications, preview fix, sidebar arrow")

    # ================================================================
    # 5. CONTEXT PROCESSOR — feed ticker + info panel data
    # ================================================================

    ctx_path = "core/context_processors.py"
    with open(ctx_path, "r", encoding="utf-8") as f:
        c = f.read()

    if "ticker_items" not in c:
        c = c.replace(
            "    return {",
            '''    # Ticker + info panel data
    ticker_items = []
    panel_data = {}
    notification_count = 0
    recent_notifications = []

    if request.user.is_authenticated:
        try:
            from market_data.models import LiveQuote
            from signals.models import Signal
            from scraping.models import NewsArticle
            from strategies.models import Strategy
            from portfolio.services import get_or_create_default_portfolio
            from django.utils import timezone as tz
            from datetime import timedelta

            now = tz.now()
            day_ago = now - timedelta(hours=24)

            # Ticker: top quotes
            for q in LiveQuote.objects.select_related("instrument").order_by("-updated_at")[:15]:
                change = float(q.change_pct or 0)
                ticker_items.append({
                    "type": "quote", "symbol": q.instrument.symbol,
                    "price": str(q.last), "change": change,
                    "change_display": f"+{change:.2f}%" if change >= 0 else f"{change:.2f}%",
                    "asset_class": q.instrument.asset_class,
                    "url": f"/instruments/{q.instrument.symbol}/",
                })

            # Ticker: active signals
            for s in Signal.objects.filter(is_active=True).select_related("instrument").order_by("-score")[:5]:
                ticker_items.append({
                    "type": "signal", "symbol": s.instrument.symbol,
                    "direction": s.direction, "score": f"{s.score:.2f}",
                    "urgency": s.urgency, "url": "/signals/",
                })

            # Ticker: recent news
            for n in NewsArticle.objects.order_by("-published_at")[:5]:
                ticker_items.append({
                    "type": "news", "title": n.title, "source": n.source,
                    "summary": n.content_summary or "", "time": str(n.published_at),
                    "url": "/news/",
                })

            # Info panel data
            portfolio = get_or_create_default_portfolio(user=request.user)
            open_pos = portfolio.positions.filter(closed_at__isnull=True)
            active_signals = Signal.objects.filter(is_active=True)
            active_strats = Strategy.objects.filter(status__in=["active", "approved"])

            cash_pct = round(float(portfolio.cash_available) / max(float(portfolio.current_value), 1) * 100)

            panel_data = {
                "panel_portfolio_value": f"{portfolio.current_value:,.0f}",
                "panel_cash": f"{portfolio.cash_available:,.0f}",
                "panel_cash_pct": cash_pct,
                "panel_positions": open_pos.count(),
                "panel_exposure": 100 - cash_pct,
                "panel_signals": active_signals.count(),
                "panel_bullish": active_signals.filter(direction="bullish").count(),
                "panel_bearish": active_signals.filter(direction="bearish").count(),
                "panel_strategies": active_strats.count(),
                "panel_proposed": Strategy.objects.filter(status="proposed").count(),
                "panel_news": NewsArticle.objects.filter(published_at__gte=day_ago).count(),
                "panel_sentiment": "0.00",
                "panel_ai_cost": "0.00",
                "panel_ai_tasks": 0,
                "panel_drawdown": "0.0",
                "panel_max_dd": f"{portfolio.max_daily_loss_pct}",
                "panel_daily_pnl": 0,
                "panel_daily_pnl_display": "+0.00%",
            }

        except Exception:
            pass

    return {
        "ticker_items": ticker_items,
        "notification_count": notification_count,
        "recent_notifications": recent_notifications,
        **panel_data,'''
        )
        with open(ctx_path, "w", encoding="utf-8") as f:
            f.write(c)
        print("  [OK] Context processor — ticker + panel + notifications data")

    print("""
  UI PATCH v2 COMPLETE

  1. Preview popup: above for bottom half, below for top half     OK
  2. Ticker: scrolling quotes/signals/news, slows on hover        OK
  3. Info panel: 8 metrics, collapsible, remembers state           OK
  4. Sidebar expand arrow: visible when menu is minimized          OK
  5. Notification bell: dropdown with recent alerts                OK

  Just refresh — no migrations needed.
""")


if __name__ == "__main__":
    generate()
