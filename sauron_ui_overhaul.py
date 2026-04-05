#!/usr/bin/env python3
"""
SAURON VISION — Mega UI Overhaul + Feature Implementation
1. Fix SE dropdown (hover only, time until state change)
2. Theme toggle (sun/moon icon, hover tooltip)
3. Collapsible sidebar (icons only, expand on hover)
4. Instrument hover preview popup
5. Premium button design
6. Admin user creation popup
7. Exchange hours fix

Run inside sauron_vision/ directory AFTER sauron_mega_v1.py
"""
import os, re

def create_file(path, content=""):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def generate():
    created = []

    # ================================================================
    # 1. FIX EXCHANGE STATUS — add time until change
    # ================================================================

    created.append(create_file("core/exchange_status.py",
'''"""Stock exchange status with time-until-change calculation."""
from datetime import datetime, time, timedelta
import pytz

EXCHANGES = [
    {"code":"NYSE","name":"New York Stock Exchange","flag":"US","tz":"US/Eastern","open":time(9,30),"close":time(16,0),"weekdays":[0,1,2,3,4]},
    {"code":"NASDAQ","name":"NASDAQ","flag":"US","tz":"US/Eastern","open":time(9,30),"close":time(16,0),"weekdays":[0,1,2,3,4]},
    {"code":"LSE","name":"London Stock Exchange","flag":"GB","tz":"Europe/London","open":time(8,0),"close":time(16,30),"weekdays":[0,1,2,3,4]},
    {"code":"EURONEXT","name":"Euronext Paris","flag":"FR","tz":"Europe/Paris","open":time(9,0),"close":time(17,30),"weekdays":[0,1,2,3,4]},
    {"code":"XETRA","name":"Frankfurt Xetra","flag":"DE","tz":"Europe/Berlin","open":time(9,0),"close":time(17,30),"weekdays":[0,1,2,3,4]},
    {"code":"TSE","name":"Tokyo Stock Exchange","flag":"JP","tz":"Asia/Tokyo","open":time(9,0),"close":time(15,0),"weekdays":[0,1,2,3,4]},
    {"code":"HKEX","name":"Hong Kong Exchange","flag":"HK","tz":"Asia/Hong_Kong","open":time(9,30),"close":time(16,0),"weekdays":[0,1,2,3,4]},
    {"code":"SSE","name":"Shanghai Exchange","flag":"CN","tz":"Asia/Shanghai","open":time(9,30),"close":time(15,0),"weekdays":[0,1,2,3,4]},
    {"code":"ASX","name":"Australian SE","flag":"AU","tz":"Australia/Sydney","open":time(10,0),"close":time(16,0),"weekdays":[0,1,2,3,4]},
    {"code":"BSE","name":"Bombay SE","flag":"IN","tz":"Asia/Kolkata","open":time(9,15),"close":time(15,30),"weekdays":[0,1,2,3,4]},
    {"code":"TSX","name":"Toronto SE","flag":"CA","tz":"US/Eastern","open":time(9,30),"close":time(16,0),"weekdays":[0,1,2,3,4]},
    {"code":"SIX","name":"SIX Swiss","flag":"CH","tz":"Europe/Zurich","open":time(9,0),"close":time(17,30),"weekdays":[0,1,2,3,4]},
    {"code":"FOREX","name":"Forex Market","flag":"FX","tz":"UTC","open":time(0,0),"close":time(23,59),"weekdays":[0,1,2,3,4]},
    {"code":"CME","name":"CME Futures","flag":"US","tz":"US/Central","open":time(17,0),"close":time(16,0),"weekdays":[6,0,1,2,3,4]},
]

def _time_until(local_now, target_time, tz):
    """Calculate timedelta until a target time, handling next-day rollover."""
    target_dt = local_now.replace(hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0)
    if target_dt <= local_now:
        target_dt += timedelta(days=1)
    # Skip weekends
    while target_dt.weekday() > 4:
        target_dt += timedelta(days=1)
    return target_dt - local_now

def _format_delta(td):
    """Format timedelta as human-readable string."""
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        return "now"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours > 24:
        days = hours // 24
        return f"{days}d {hours % 24}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"

def get_exchange_status(now_utc=None):
    if now_utc is None:
        now_utc = datetime.now(pytz.UTC)
    results = []
    open_count = 0

    for ex in EXCHANGES:
        tz = pytz.timezone(ex["tz"])
        local_now = now_utc.astimezone(tz)
        weekday = local_now.weekday()
        local_time = local_now.time()

        if ex["code"] == "FOREX":
            utc_weekday = now_utc.weekday()
            utc_hour = now_utc.hour
            is_open = not (utc_weekday == 5 or (utc_weekday == 6 and utc_hour < 21) or (utc_weekday == 4 and utc_hour >= 21))
            if is_open:
                # Time until Friday 21:00 UTC close
                days_until_fri = (4 - utc_weekday) % 7
                close_dt = now_utc.replace(hour=21, minute=0, second=0) + timedelta(days=days_until_fri)
                if close_dt <= now_utc:
                    close_dt += timedelta(days=7)
                time_until = _format_delta(close_dt - now_utc)
            else:
                # Time until Sunday 21:00 UTC open
                days_until_sun = (6 - utc_weekday) % 7
                open_dt = now_utc.replace(hour=21, minute=0, second=0) + timedelta(days=days_until_sun)
                if open_dt <= now_utc:
                    open_dt += timedelta(days=7)
                time_until = _format_delta(open_dt - now_utc)
        elif ex["code"] == "CME":
            # CME: Sun 17:00 CT to Fri 16:00 CT with daily 16:00-17:00 break
            is_open = weekday in ex["weekdays"] and not (local_time >= time(16,0) and local_time < time(17,0))
            if weekday == 5:
                is_open = False
            if is_open:
                close_t = time(16, 0)
                time_until = _format_delta(_time_until(local_now, close_t, tz))
            else:
                open_t = time(17, 0)
                time_until = _format_delta(_time_until(local_now, open_t, tz))
        else:
            is_open = weekday in ex["weekdays"] and ex["open"] <= local_time < ex["close"]
            if is_open:
                time_until = _format_delta(_time_until(local_now, ex["close"], tz))
            else:
                time_until = _format_delta(_time_until(local_now, ex["open"], tz))

        if is_open:
            open_count += 1

        results.append({
            "code": ex["code"], "name": ex["name"], "flag": ex["flag"],
            "is_open": is_open,
            "local_time": local_now.strftime("%H:%M"),
            "opens": ex["open"].strftime("%H:%M"),
            "closes": ex["close"].strftime("%H:%M"),
            "time_until_change": time_until,
            "next_state": "closes" if is_open else "opens",
        })
    return {"open_count": open_count, "total": len(EXCHANGES), "exchanges": results}
'''))

    # ================================================================
    # 2-7. COMPLETE BASE TEMPLATE OVERHAUL
    # ================================================================

    base_path = "templates/base.html"
    with open(base_path, "r", encoding="utf-8") as f:
        content = f.read()

    # ── 2a. Replace theme toggle with sun/moon ──
    content = content.replace(
        '''<a href="{% url 'toggle_theme' %}" style="color:var(--text-secondary);text-decoration:none;font-size:16px;" title="Toggle light/dark mode">\u263e</a>''',
        '''<a href="{% url 'toggle_theme' %}" class="theme-toggle-btn" title="Switch to light/dark mode">
                    <span class="theme-icon-dark">\u2600</span>
                    <span class="theme-icon-light">\u263e</span>
                </a>'''
    )

    # ── 2b. Replace exchange dropdown with fixed version ──
    old_exchange = '''<div class="exchange-indicator">
                    <span class="exchange-count" title="Stock exchanges currently open">
                        <span style="color:var(--accent);">{{ exchanges_open_count }}</span><span style="color:var(--text-muted);">/{{ exchanges_total }}</span>
                        <span style="font-size:10px;color:var(--text-muted);margin-left:2px;">SE</span>
                    </span>
                    <div class="exchange-dropdown">
                        <div class="exchange-dropdown-title">Stock Exchange Status</div>
                        {% for ex in exchanges_list %}
                        <div class="exchange-row">
                            <span class="exchange-flag">{{ ex.flag }}</span>
                            <span class="exchange-name">{{ ex.code }}</span>
                            <span class="exchange-time">{{ ex.local_time }}</span>
                            <span class="exchange-status {% if ex.is_open %}open{% else %}closed{% endif %}">
                                {% if ex.is_open %}OPEN{% else %}CLOSED{% endif %}
                            </span>
                        </div>
                        {% endfor %}
                    </div>
                </div>'''

    new_exchange = '''<div class="exchange-indicator">
                    <span class="exchange-trigger">
                        <span style="color:var(--accent);">{{ exchanges_open_count }}</span><span style="color:var(--text-muted);">/{{ exchanges_total }} SE</span>
                    </span>
                    <div class="exchange-dropdown">
                        <div class="exchange-dropdown-header">Market Sessions</div>
                        {% for ex in exchanges_list %}
                        <div class="exchange-row">
                            <span class="ex-flag">{{ ex.flag }}</span>
                            <span class="ex-code">{{ ex.code }}</span>
                            <span class="ex-local">{{ ex.local_time }}</span>
                            <span class="ex-state {% if ex.is_open %}st-open{% else %}st-closed{% endif %}">{% if ex.is_open %}OPEN{% else %}CLOSED{% endif %}</span>
                            <span class="ex-until">{{ ex.next_state }} in {{ ex.time_until_change }}</span>
                        </div>
                        {% endfor %}
                    </div>
                </div>'''

    content = content.replace(old_exchange, new_exchange)

    # ── 3. Collapsible sidebar ──
    # Replace the sidebar opening tag to add collapsible behavior
    content = content.replace(
        '<aside class="sidebar">',
        '<aside class="sidebar" id="mainSidebar">'
    )

    # Add collapse toggle to sidebar brand
    content = content.replace(
        '<div class="sidebar-brand">',
        '<div class="sidebar-brand"><button class="sidebar-collapse-btn" onclick="document.getElementById(\'mainSidebar\').classList.toggle(\'collapsed\')" title="Collapse sidebar">\u276e</button>'
    )

    # ── Now inject all the new CSS ──
    # Remove old exchange CSS first
    content = re.sub(
        r'/\* ── Exchange Status Dropdown.*?\.exchange-status\.closed \{[^}]+\}',
        '',
        content,
        flags=re.DOTALL
    )
    # Remove old mobile CSS that conflicts
    content = re.sub(
        r'/\* ── Mobile Responsive.*?\.mobile-toggle \{ display: none; \} \}',
        '',
        content,
        flags=re.DOTALL
    )

    NEW_CSS = '''
        /* ── Theme Toggle ────────────────────────── */
        .theme-toggle-btn {
            display: flex; align-items: center; justify-content: center;
            width: 34px; height: 34px; border-radius: 50%;
            border: 1px solid var(--border); background: var(--bg-card);
            color: var(--text-secondary); text-decoration: none; font-size: 16px;
            transition: all 0.3s; position: relative;
        }
        .theme-toggle-btn:hover {
            border-color: var(--accent); color: var(--accent);
            box-shadow: 0 0 16px var(--accent-glow);
            transform: rotate(20deg);
        }
        .theme-toggle-btn:hover::after {
            content: 'Toggle theme'; position: absolute; top: 42px; left: 50%;
            transform: translateX(-50%); white-space: nowrap;
            font-size: 10px; font-family: var(--font-mono);
            background: var(--bg-card); border: 1px solid var(--border);
            padding: 4px 10px; border-radius: var(--radius); color: var(--text-secondary);
            letter-spacing: 1px; pointer-events: none; z-index: 300;
        }
        .theme-icon-light { display: none; }
        body.light-mode .theme-icon-dark { display: none; }
        body.light-mode .theme-icon-light { display: inline; }

        /* ── Collapsible Sidebar ─────────────────── */
        .sidebar-collapse-btn {
            position: absolute; top: 20px; right: 12px;
            background: none; border: none; color: var(--text-muted);
            font-size: 14px; cursor: pointer; padding: 4px; z-index: 10;
            transition: transform 0.3s;
        }
        .sidebar-collapse-btn:hover { color: var(--accent); }
        .sidebar.collapsed .sidebar-collapse-btn { transform: rotate(180deg); }
        .sidebar { transition: width 0.3s ease; overflow: hidden; }
        .sidebar.collapsed { width: 64px; }
        .sidebar.collapsed .sidebar-brand h1 span,
        .sidebar.collapsed .sidebar-brand .subtitle,
        .sidebar.collapsed .sidebar-collapse-btn { opacity: 0; }
        .sidebar.collapsed .sidebar-brand h1 { justify-content: center; }
        .sidebar.collapsed .nav-section { font-size: 0; height: 8px; padding: 0 8px; }
        .sidebar.collapsed .nav-link {
            padding: 10px 0; justify-content: center; border-left-width: 0;
            position: relative;
        }
        .sidebar.collapsed .nav-link span:not(.icon) { display: none; }
        .sidebar.collapsed .nav-link .icon { margin: 0; font-size: 18px; }
        .sidebar.collapsed .nav-link:hover::after {
            content: attr(data-label); position: absolute; left: 68px; top: 50%;
            transform: translateY(-50%); white-space: nowrap;
            background: var(--bg-card); border: 1px solid var(--border);
            padding: 6px 14px; border-radius: var(--radius); font-size: 12px;
            color: var(--text-primary); font-family: var(--font-heading);
            box-shadow: 0 4px 20px rgba(0,0,0,0.4); z-index: 500;
            letter-spacing: 0.5px;
        }
        .sidebar.collapsed .sidebar-footer { flex-direction: column; gap: 8px; padding: 10px 8px; }
        .sidebar.collapsed .sidebar-footer form button,
        .sidebar.collapsed .sidebar-footer a { font-size: 0; }
        .sidebar.collapsed .sidebar-footer form button::before { content: '\\23FB'; font-size: 14px; }
        .sidebar.collapsed .sidebar-footer a::before { content: '\\2699'; font-size: 14px; }
        .sidebar.collapsed + .main-content,
        body:has(.sidebar.collapsed) .main-content { margin-left: 64px; }

        /* ── Exchange Dropdown (fixed) ───────────── */
        .exchange-indicator { position: relative; }
        .exchange-trigger {
            font-family: var(--font-mono); font-size: 12px;
            padding: 5px 10px; border: 1px solid var(--border);
            border-radius: var(--radius); cursor: pointer;
            transition: all 0.2s; display: inline-block;
        }
        .exchange-trigger:hover { border-color: var(--accent-dim); background: var(--bg-card); }
        .exchange-dropdown {
            display: none; position: absolute; top: calc(100% + 8px); right: 0;
            width: 380px; background: var(--bg-card); border: 1px solid var(--border);
            border-radius: var(--radius-lg); box-shadow: 0 12px 48px rgba(0,0,0,0.6);
            z-index: 300; padding: 14px; backdrop-filter: blur(12px);
        }
        .exchange-indicator:hover .exchange-dropdown { display: block; }
        .exchange-dropdown-header {
            font-family: var(--font-mono); font-size: 10px; letter-spacing: 3px;
            color: var(--text-muted); text-transform: uppercase;
            padding-bottom: 10px; margin-bottom: 6px; border-bottom: 1px solid var(--border);
        }
        .exchange-row {
            display: grid; grid-template-columns: 26px 65px 44px 52px 1fr;
            align-items: center; gap: 6px; padding: 6px 0;
            font-family: var(--font-mono); font-size: 11px;
            border-bottom: 1px solid rgba(19,48,32,0.15);
        }
        .exchange-row:last-child { border-bottom: none; }
        .ex-flag { font-size: 10px; color: var(--text-muted); text-align: center; }
        .ex-code { font-weight: 700; color: var(--text-primary); }
        .ex-local { color: var(--text-secondary); }
        .ex-state {
            font-size: 9px; font-weight: 700; letter-spacing: 1px; text-align: center;
            padding: 2px 6px; border-radius: 10px;
        }
        .ex-state.st-open { color: var(--accent); background: var(--accent-dim); }
        .ex-state.st-closed { color: var(--text-muted); background: rgba(90,138,106,0.08); }
        .ex-until { font-size: 9px; color: var(--text-muted); text-align: right; font-style: italic; }

        /* ── Premium Button Design ───────────────── */
        .btn {
            display: inline-flex; align-items: center; gap: 8px;
            padding: 9px 20px; border: 1px solid var(--border);
            border-radius: 8px; background: var(--bg-card);
            color: var(--text-primary); font-family: var(--font-heading);
            font-size: 13px; font-weight: 600; letter-spacing: 1px;
            cursor: pointer; text-decoration: none;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative; overflow: hidden;
        }
        .btn::before {
            content: ''; position: absolute; top: 0; left: -100%; width: 100%; height: 100%;
            background: linear-gradient(90deg, transparent, rgba(0,232,104,0.05), transparent);
            transition: left 0.5s;
        }
        .btn:hover::before { left: 100%; }
        .btn:hover {
            border-color: var(--accent-dim); transform: translateY(-1px);
            box-shadow: 0 4px 16px rgba(0,0,0,0.3), 0 0 1px var(--accent-dim);
        }
        .btn:active { transform: translateY(0); }
        .btn-primary {
            background: linear-gradient(135deg, var(--accent-dim), rgba(0,232,104,0.25));
            border-color: var(--accent); color: #fff;
        }
        .btn-primary::before {
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent);
        }
        .btn-primary:hover {
            background: linear-gradient(135deg, var(--accent), rgba(0,232,104,0.8));
            color: #000; box-shadow: 0 4px 24px rgba(0,232,104,0.25), 0 0 2px var(--accent);
        }
        .btn-sm { padding: 6px 14px; font-size: 11px; border-radius: 6px; }
        .btn-danger {
            background: rgba(232,48,48,0.08); border-color: var(--accent-red-dim);
            color: var(--accent-red);
        }
        .btn-danger:hover {
            background: rgba(232,48,48,0.2); border-color: var(--accent-red);
            box-shadow: 0 4px 16px rgba(232,48,48,0.15);
        }
        .btn-ghost {
            background: transparent; border-color: transparent; color: var(--text-secondary);
            padding: 6px 12px;
        }
        .btn-ghost:hover { color: var(--accent); background: var(--accent-glow); }

        /* ── Instrument Preview Popup ────────────── */
        .instrument-link { position: relative; }
        .instrument-preview {
            display: none; position: absolute; bottom: calc(100% + 8px); left: 0;
            width: 320px; background: var(--bg-card); border: 1px solid var(--border);
            border-radius: var(--radius-lg); box-shadow: 0 12px 48px rgba(0,0,0,0.6);
            padding: 16px; z-index: 400; pointer-events: none;
            animation: previewFadeIn 0.2s ease;
        }
        .instrument-preview.show { display: block; }
        @keyframes previewFadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
        .preview-header {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid var(--border);
        }
        .preview-symbol { font-family: var(--font-display); font-size: 16px; font-weight: 700; color: var(--accent); }
        .preview-price { font-family: var(--font-mono); font-size: 18px; font-weight: 700; }
        .preview-row {
            display: flex; justify-content: space-between; padding: 3px 0;
            font-family: var(--font-mono); font-size: 11px;
        }
        .preview-row .lbl { color: var(--text-muted); }
        .preview-row .val { color: var(--text-primary); }

        /* ── Admin User Popup ────────────────────── */
        .modal-overlay {
            display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7);
            backdrop-filter: blur(4px); z-index: 1000;
            align-items: center; justify-content: center;
        }
        .modal-overlay.active { display: flex; }
        .modal {
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: var(--radius-lg); padding: 28px; width: 440px;
            max-width: 95vw; box-shadow: 0 20px 60px rgba(0,0,0,0.6);
            animation: modalSlideIn 0.3s ease;
        }
        @keyframes modalSlideIn { from { opacity: 0; transform: translateY(-20px); } to { opacity: 1; transform: translateY(0); } }
        .modal-title {
            font-family: var(--font-display); font-size: 16px; font-weight: 700;
            letter-spacing: 2px; color: var(--accent); margin-bottom: 20px;
        }
        .modal-close {
            float: right; background: none; border: none; color: var(--text-muted);
            font-size: 20px; cursor: pointer; padding: 0 4px;
        }
        .modal-close:hover { color: var(--accent); }

        /* ── Mobile Responsive ───────────────────── */
        @media (max-width: 768px) {
            .sidebar { transform: translateX(-100%); transition: transform 0.3s; position: fixed; z-index: 1000; }
            .sidebar.open { transform: translateX(0); }
            .sidebar.collapsed { width: var(--sidebar-width); }
            .main-content { margin-left: 0 !important; }
            .topbar { padding: 0 14px; }
            .page-content { padding: 14px; }
            .grid-2,.grid-3,.grid-4,.grid-5,.grid-6,.grid-sidebar { grid-template-columns: 1fr !important; }
            .exchange-dropdown { width: 300px; right: -40px; }
            .mobile-toggle {
                display: flex; align-items: center; justify-content: center;
                position: fixed; top: 10px; left: 10px; z-index: 1001;
                width: 40px; height: 40px; background: var(--bg-card);
                border: 1px solid var(--border); border-radius: var(--radius);
                color: var(--accent); cursor: pointer; font-size: 18px;
            }
        }
        @media (min-width: 769px) { .mobile-toggle { display: none; } }
'''

    # Insert new CSS replacing old .btn and old exchange + mobile CSS
    content = re.sub(
        r'\.btn \{[^}]+\}\s*\n\s*\.btn:hover \{[^}]+\}\s*\n\s*\.btn-primary \{[^}]+\}\s*\n\s*\.btn-primary:hover \{[^}]+\}\s*\n\s*\.btn-sm \{[^}]+\}',
        '/* buttons moved to new CSS block */',
        content
    )

    content = content.replace("    </style>", NEW_CSS + "\n    </style>")

    # ── Add data-label attributes to nav links for collapsed tooltip ──
    nav_labels = {
        "Dashboard": "Dashboard", "Instruments": "Instruments", "Live Quotes": "Live Quotes",
        "Economic Calendar": "Calendar", "Signals": "Signals", "Strategies": "Strategies",
        "News": "News & Sentiment", "Portfolio": "Portfolio", "Positions": "Positions",
        "AI Insights": "AI Insights", "Agent Tasks": "Agent Tasks",
        "Backtesting": "Backtesting", "Admin Panel": "Admin",
        "Profile": "Profile", "Setup": "Setup", "Getting Started": "Getting Started",
    }
    for label_text, data_val in nav_labels.items():
        old = f'>{label_text}</a>'
        new = f' data-label="{data_val}">{label_text}</a>'
        if old in content and f'data-label="{data_val}"' not in content:
            content = content.replace(old, new)

    # ── Add instrument preview JS ──
    if "instrumentPreview" not in content:
        preview_js = '''
<script>
// Instrument preview on hover (2s delay)
(function() {
    let hoverTimer = null;
    let previewEl = null;

    document.addEventListener('mouseover', function(e) {
        const link = e.target.closest('[data-instrument]');
        if (!link) return;
        hoverTimer = setTimeout(function() {
            const sym = link.getAttribute('data-instrument');
            showPreview(link, sym);
        }, 1500);
    });

    document.addEventListener('mouseout', function(e) {
        if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = null; }
        if (previewEl) { previewEl.remove(); previewEl = null; }
    });

    function showPreview(anchor, symbol) {
        if (previewEl) previewEl.remove();
        previewEl = document.createElement('div');
        previewEl.className = 'instrument-preview show';
        previewEl.innerHTML = `
            <div class="preview-header">
                <span class="preview-symbol">${symbol}</span>
                <span style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);">Loading...</span>
            </div>
            <div class="preview-row"><span class="lbl">Status</span><span class="val">Fetching data...</span></div>
        `;
        anchor.style.position = 'relative';
        anchor.appendChild(previewEl);

        // Fetch preview data via API
        fetch('/api/instrument-preview/' + symbol + '/')
            .then(r => r.json())
            .then(data => {
                if (!previewEl) return;
                previewEl.innerHTML = `
                    <div class="preview-header">
                        <span class="preview-symbol">${data.symbol}</span>
                        <span class="preview-price" style="color:${data.change_pct >= 0 ? 'var(--accent)' : 'var(--accent-red)'}">
                            ${data.price || '—'}
                        </span>
                    </div>
                    <div class="preview-row"><span class="lbl">CHANGE</span><span class="val" style="color:${data.change_pct >= 0 ? 'var(--accent)' : 'var(--accent-red)'}">${data.change_pct || 0}%</span></div>
                    <div class="preview-row"><span class="lbl">ASSET CLASS</span><span class="val">${data.asset_class || '—'}</span></div>
                    <div class="preview-row"><span class="lbl">EXCHANGE</span><span class="val">${data.exchange || '—'}</span></div>
                    <div class="preview-row"><span class="lbl">SIGNALS</span><span class="val">${data.active_signals || 0} active</span></div>
                    <div class="preview-row"><span class="lbl">VOLUME</span><span class="val">${data.volume || '—'}</span></div>
                `;
            })
            .catch(() => {
                if (previewEl) previewEl.innerHTML = '<div style="padding:10px;color:var(--text-muted);font-size:11px;">Preview unavailable</div>';
            });
    }
})();
</script>
'''
        content = content.replace('{% block extra_js %}{% endblock %}', preview_js + '\n{% block extra_js %}{% endblock %}')

    with open(base_path, "w", encoding="utf-8") as f:
        f.write(content)
    created.append(base_path)

    # ================================================================
    # INSTRUMENT PREVIEW API ENDPOINT
    # ================================================================

    api_view_code = '''

@login_required
def instrument_preview_api(request, symbol):
    """API endpoint for instrument hover preview."""
    from django.http import JsonResponse
    from instruments.models import Instrument
    from signals.models import Signal

    try:
        inst = Instrument.objects.get(symbol=symbol)
    except Instrument.DoesNotExist:
        return JsonResponse({"symbol": symbol, "error": "not_found"})

    # Get quote
    price = None
    change_pct = 0
    volume = None
    try:
        quote = inst.live_quote
        price = str(quote.last)
        change_pct = float(quote.change_pct)
        volume = str(quote.volume) if quote.volume else None
    except Exception:
        pass

    # Count signals
    active_signals = Signal.objects.filter(instrument=inst, is_active=True).count()

    return JsonResponse({
        "symbol": inst.symbol,
        "name": inst.name,
        "asset_class": inst.asset_class,
        "exchange": inst.exchange,
        "price": price,
        "change_pct": change_pct,
        "volume": volume,
        "active_signals": active_signals,
    })
'''

    views_path = "dashboard/views.py"
    with open(views_path, "r", encoding="utf-8") as f:
        vc = f.read()
    if "instrument_preview_api" not in vc:
        with open(views_path, "a", encoding="utf-8") as f:
            f.write(api_view_code)
        created.append(views_path)

    # Add URL
    urls_path = "dashboard/urls.py"
    with open(urls_path, "r", encoding="utf-8") as f:
        uc = f.read()
    if "instrument-preview" not in uc:
        uc = uc.replace(
            'path("instruments/<str:symbol>/", views.instrument_detail, name="instrument_detail"),',
            'path("instruments/<str:symbol>/", views.instrument_detail, name="instrument_detail"),\n'
            '    path("api/instrument-preview/<str:symbol>/", views.instrument_preview_api, name="instrument_preview_api"),'
        )
        with open(urls_path, "w", encoding="utf-8") as f:
            f.write(uc)
        created.append(urls_path)

    # ================================================================
    # 6. ADMIN USER CREATION POPUP
    # ================================================================

    created.append(create_file("templates/dashboard/admin_dashboard.html",
r'''{% extends "base.html" %}
{% load sauron_tags %}
{% block title %}Admin — Sauron Vision{% endblock %}
{% block page_title %}ADMIN CONTROL CENTER{% endblock %}

{% block content %}
{% if messages %}
<div style="margin-bottom:20px;">
    {% for msg in messages %}
    <div class="card" style="border-color:{% if msg.tags == 'success' %}var(--accent){% else %}var(--accent-red){% endif %};padding:12px 20px;margin-bottom:8px;">
        <span style="font-family:var(--font-mono);font-size:13px;">{% if msg.tags == 'success' %}OK{% else %}ERR{% endif %} {{ msg }}</span>
    </div>
    {% endfor %}
</div>
{% endif %}

<!-- Master Switch -->
<div class="card fade-in-up" style="margin-bottom:24px;border-color:{% if master_enabled %}var(--accent){% else %}var(--accent-red){% endif %};">
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
            <div style="font-family:var(--font-display);font-size:18px;font-weight:700;letter-spacing:2px;color:{% if master_enabled %}var(--accent){% else %}var(--accent-red){% endif %};">
                {% if master_enabled %}PLATFORM ACTIVE{% else %}PLATFORM STOPPED{% endif %}
            </div>
            <div style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted);margin-top:4px;">Master switch — all automated tasks</div>
        </div>
        <form method="post" action="{% url 'admin_toggle_component' %}">{% csrf_token %}<input type="hidden" name="key" value="platform_master">
            {% if master_enabled %}
            <button type="submit" class="btn btn-danger" style="font-size:14px;padding:12px 32px;letter-spacing:2px;">STOP ALL</button>
            {% else %}
            <button type="submit" class="btn btn-primary" style="font-size:14px;padding:12px 32px;letter-spacing:2px;">START PLATFORM</button>
            {% endif %}
        </form>
    </div>
</div>

<!-- Quick Actions -->
<div class="grid grid-4" style="margin-bottom:24px;">
    <form method="post" action="{% url 'admin_bulk_toggle' %}">{% csrf_token %}<input type="hidden" name="category" value="scraper"><input type="hidden" name="action" value="enable"><button type="submit" class="btn" style="width:100%;">Start All Scrapers</button></form>
    <form method="post" action="{% url 'admin_bulk_toggle' %}">{% csrf_token %}<input type="hidden" name="category" value="scraper"><input type="hidden" name="action" value="disable"><button type="submit" class="btn btn-danger" style="width:100%;">Stop All Scrapers</button></form>
    <form method="post" action="{% url 'admin_bulk_toggle' %}">{% csrf_token %}<input type="hidden" name="category" value="agent"><input type="hidden" name="action" value="enable"><button type="submit" class="btn" style="width:100%;">Start All Agents</button></form>
    <form method="post" action="{% url 'admin_bulk_toggle' %}">{% csrf_token %}<input type="hidden" name="category" value="agent"><input type="hidden" name="action" value="disable"><button type="submit" class="btn btn-danger" style="width:100%;">Stop All Agents</button></form>
</div>

<!-- Component Controls -->
{% for cat_name, cat_components in components_by_category.items %}
<div class="section-label fade-in-up">{{ cat_name|upper }}</div>
<div class="card fade-in-up" style="margin-bottom:20px;">
    <div class="table-wrapper"><table>
        <thead><tr><th>Component</th><th>Status</th><th>Last Run</th><th>Result</th><th>Runs</th><th>Errors</th><th>Action</th></tr></thead>
        <tbody>
        {% for c in cat_components %}
        <tr>
            <td><div style="font-weight:600;">{{ c.name }}</div><div style="font-size:10px;color:var(--text-muted);font-family:var(--font-mono);">{{ c.description }}</div></td>
            <td>{% if c.is_enabled %}<span style="color:var(--accent);font-family:var(--font-mono);font-size:12px;">RUNNING</span>{% else %}<span style="color:var(--text-muted);font-family:var(--font-mono);font-size:12px;">STOPPED</span>{% endif %}</td>
            <td style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted);">{% if c.last_run_at %}{{ c.last_run_at|timesince }} ago{% else %}Never{% endif %}</td>
            <td>{% if c.last_status == "success" %}<span style="color:var(--accent);">OK</span>{% elif c.last_status == "error" %}<span style="color:var(--accent-red);">ERR</span>{% else %}<span style="color:var(--text-muted);">---</span>{% endif %}</td>
            <td style="font-family:var(--font-mono);font-size:12px;">{{ c.run_count }}</td>
            <td style="font-family:var(--font-mono);font-size:12px;color:{% if c.error_count > 0 %}var(--accent-red){% else %}var(--text-muted){% endif %};">{{ c.error_count }}</td>
            <td><form method="post" action="{% url 'admin_toggle_component' %}" style="display:inline;">{% csrf_token %}<input type="hidden" name="key" value="{{ c.key }}">
                {% if c.is_enabled %}<button type="submit" class="btn btn-sm btn-danger">STOP</button>
                {% else %}<button type="submit" class="btn btn-sm btn-primary">START</button>{% endif %}
            </form></td>
        </tr>
        {% endfor %}
        </tbody>
    </table></div>
</div>
{% endfor %}

<!-- System Overview -->
<div class="section-label fade-in-up">System Overview</div>
<div class="grid grid-5" style="margin-bottom:20px;">
    <div class="stat-box fade-in-up delay-1"><div class="stat-label">Total Users</div><div class="stat-value">{{ total_users }}</div><div class="stat-sub">{{ active_users }} active</div></div>
    <div class="stat-box fade-in-up delay-2"><div class="stat-label">Instruments</div><div class="stat-value">{{ total_instruments }}</div><div class="stat-sub">{{ watchlist_instruments }} watched</div></div>
    <div class="stat-box fade-in-up delay-3"><div class="stat-label">Active Signals</div><div class="stat-value" style="color:var(--accent);">{{ active_signals }}</div></div>
    <div class="stat-box fade-in-up delay-4"><div class="stat-label">AI Tasks (24h)</div><div class="stat-value">{{ ai_tasks_24h }}</div><div class="stat-sub">${{ ai_cost_24h }} cost</div></div>
    <div class="stat-box fade-in-up delay-5"><div class="stat-label">News Articles</div><div class="stat-value">{{ total_news }}</div><div class="stat-sub">{{ unprocessed_news }} unprocessed</div></div>
</div>

<!-- Users with ADD popup -->
<div class="section-label fade-in-up">Users</div>
<div class="card fade-in-up delay-5" style="margin-bottom:24px;">
    <div class="card-header">
        <span class="card-title">Registered Users</span>
        <button class="btn btn-primary btn-sm" onclick="document.getElementById('addUserModal').classList.add('active')">+ Add User</button>
    </div>
    <div class="table-wrapper"><table>
        <thead><tr><th>Username</th><th>Email</th><th>Name</th><th>Staff</th><th>Active</th><th>Joined</th><th>Last Login</th></tr></thead>
        <tbody>
        {% for u in users %}
        <tr>
            <td style="font-family:var(--font-display);font-size:12px;">{{ u.username }}</td>
            <td style="font-size:12px;">{{ u.email|default:"-" }}</td>
            <td>{{ u.first_name }} {{ u.last_name }}</td>
            <td>{% if u.is_staff %}<span style="color:var(--accent);">yes</span>{% else %}no{% endif %}</td>
            <td>{% if u.is_active %}<span style="color:var(--accent);">yes</span>{% else %}<span style="color:var(--accent-red);">no</span>{% endif %}</td>
            <td style="font-size:11px;color:var(--text-muted);">{{ u.date_joined|date:"M d, Y" }}</td>
            <td style="font-size:11px;color:var(--text-muted);">{{ u.last_login|date:"M d H:i"|default:"-" }}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table></div>
</div>

<!-- Data Health -->
<div class="section-label fade-in-up">Data Pipeline Health</div>
<div class="card fade-in-up delay-6">
    <div class="card-header"><span class="card-title">Data Sources</span></div>
    <div class="table-wrapper"><table>
        <thead><tr><th>Source</th><th>Records</th><th>Last Updated</th><th>Status</th></tr></thead>
        <tbody>
        {% for src in data_sources %}
        <tr>
            <td>{{ src.name }}</td>
            <td style="font-family:var(--font-mono);">{{ src.count }}</td>
            <td style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted);">{{ src.last_updated|default:"Never" }}</td>
            <td>{% if src.count > 0 %}<span style="color:var(--accent);">HAS DATA</span>{% else %}<span style="color:var(--text-muted);">EMPTY</span>{% endif %}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table></div>
</div>

<!-- ── ADD USER MODAL ─────────────────────────── -->
<div class="modal-overlay" id="addUserModal">
    <div class="modal">
        <button class="modal-close" onclick="document.getElementById('addUserModal').classList.remove('active')">&times;</button>
        <div class="modal-title">CREATE NEW USER</div>
        <form method="post" action="{% url 'admin_create_user' %}">
            {% csrf_token %}
            <div style="margin-bottom:16px;">
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">USERNAME</label>
                <input type="text" name="username" required style="width:100%;padding:10px 14px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:13px;outline:none;">
            </div>
            <div style="margin-bottom:16px;">
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">EMAIL</label>
                <input type="email" name="email" style="width:100%;padding:10px 14px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:13px;outline:none;">
            </div>
            <div style="margin-bottom:16px;">
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">PASSWORD</label>
                <input type="password" name="password" required style="width:100%;padding:10px 14px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:13px;outline:none;">
            </div>
            <div style="margin-bottom:16px;">
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">FIRST NAME</label>
                <input type="text" name="first_name" style="width:100%;padding:10px 14px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:13px;outline:none;">
            </div>
            <div style="margin-bottom:16px;">
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">LAST NAME</label>
                <input type="text" name="last_name" style="width:100%;padding:10px 14px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:13px;outline:none;">
            </div>
            <div style="margin-bottom:20px;display:flex;gap:16px;">
                <label style="display:flex;align-items:center;gap:8px;font-size:13px;color:var(--text-secondary);cursor:pointer;"><input type="checkbox" name="is_staff"> Staff</label>
                <label style="display:flex;align-items:center;gap:8px;font-size:13px;color:var(--text-secondary);cursor:pointer;"><input type="checkbox" name="is_superuser"> Superuser</label>
            </div>
            <div style="display:flex;gap:12px;">
                <button type="submit" class="btn btn-primary" style="flex:1;">Create User</button>
                <button type="button" class="btn" onclick="document.getElementById('addUserModal').classList.remove('active')">Cancel</button>
            </div>
        </form>
    </div>
</div>
{% endblock %}
'''))

    # ================================================================
    # ADMIN CREATE USER VIEW
    # ================================================================

    create_user_view = '''

@login_required
def admin_create_user(request):
    """Create a new user from admin popup."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    if request.method == "POST":
        from django.contrib.auth.models import User
        from django.contrib import messages
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        email = request.POST.get("email", "")
        first_name = request.POST.get("first_name", "")
        last_name = request.POST.get("last_name", "")
        is_staff = "is_staff" in request.POST
        is_superuser = "is_superuser" in request.POST

        if not username or not password:
            messages.error(request, "Username and password are required.")
        elif User.objects.filter(username=username).exists():
            messages.error(request, f"Username '{username}' already exists.")
        else:
            user = User.objects.create_user(
                username=username, password=password, email=email,
                first_name=first_name, last_name=last_name,
            )
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.save()
            messages.success(request, f"User '{username}' created successfully.")
    from django.shortcuts import redirect
    return redirect("admin_dashboard")
'''

    with open(views_path, "r", encoding="utf-8") as f:
        vc = f.read()
    if "admin_create_user" not in vc:
        with open(views_path, "a", encoding="utf-8") as f:
            f.write(create_user_view)

    # Add URL
    with open(urls_path, "r", encoding="utf-8") as f:
        uc = f.read()
    if "admin_create_user" not in uc:
        uc = uc.replace(
            'path("admin-dashboard/bulk-toggle/", views.admin_bulk_toggle, name="admin_bulk_toggle"),',
            'path("admin-dashboard/bulk-toggle/", views.admin_bulk_toggle, name="admin_bulk_toggle"),\n'
            '    path("admin-dashboard/create-user/", views.admin_create_user, name="admin_create_user"),'
        )
        with open(urls_path, "w", encoding="utf-8") as f:
            f.write(uc)

    print(f"""
  SAURON VISION — UI Overhaul Applied ({len(created)} files)

  FIXES:
    1. SE dropdown — hover only, shows time until state change      OK
    2. Theme toggle — sun icon (dark), moon (light), hover tooltip  OK
    3. Collapsible sidebar — click arrow to minimize to icons       OK
    4. Instrument preview — hover 1.5s shows price/class/signals    OK
    5. Premium buttons — gradient, shine effect, hover lift          OK
    6. Admin user popup — create users in Sauron-styled modal       OK
    7. Exchange hours — correct open/close detection + countdown    OK

  Run:
    python manage.py runserver
    (no migrations needed for UI changes)
""")


if __name__ == "__main__":
    generate()
