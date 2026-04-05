#!/usr/bin/env python3
"""
SAURON VISION — Patch v2
1. Globe rotates inside static eye structure
2. Logout fix (POST-based)
3. Eye favicon + OG meta for social sharing
4. Enriched dashboard with many more metrics
"""

import os

def create_file(path, content=""):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path

def generate():
    created = []

    # ================================================================
    # 3. FAVICON — eye-shaped SVG
    # ================================================================

    created.append(create_file("static/favicon.svg", '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <path d="M2,32 Q16,8 32,14 Q48,8 62,32 Q48,56 32,50 Q16,56 2,32Z" fill="none" stroke="#00e868" stroke-width="2.5"/>
  <circle cx="32" cy="32" r="12" fill="none" stroke="#00e868" stroke-width="2"/>
  <circle cx="32" cy="32" r="5" fill="#00e868"/>
  <ellipse cx="32" cy="32" rx="4" ry="12" fill="none" stroke="#00e868" stroke-width="0.8" opacity="0.5"/>
  <ellipse cx="32" cy="32" rx="9" ry="12" fill="none" stroke="#00e868" stroke-width="0.5" opacity="0.3"/>
  <line x1="20" y1="28" x2="44" y2="28" stroke="#00e868" stroke-width="0.4" opacity="0.3"/>
  <line x1="20" y1="36" x2="44" y2="36" stroke="#00e868" stroke-width="0.4" opacity="0.3"/>
</svg>
'''))

    # OG image (larger version for social sharing)
    created.append(create_file("static/og-image.svg", '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#030806"/>
  <g transform="translate(600,315)">
    <!-- Eye shape -->
    <path d="M-280,0 Q-140,-160 0,-100 Q140,-160 280,0 Q140,160 0,100 Q-140,160 -280,0Z" fill="none" stroke="#00e868" stroke-width="3" opacity="0.6"/>
    <!-- Iris -->
    <circle cx="0" cy="0" r="80" fill="none" stroke="#00e868" stroke-width="2" opacity="0.5"/>
    <!-- Globe inside -->
    <ellipse cx="0" cy="0" rx="30" ry="80" fill="none" stroke="#00e868" stroke-width="1" opacity="0.4"/>
    <ellipse cx="0" cy="0" rx="60" ry="80" fill="none" stroke="#00e868" stroke-width="0.8" opacity="0.3"/>
    <line x1="-80" y1="-25" x2="80" y2="-25" stroke="#00e868" stroke-width="0.6" opacity="0.25"/>
    <line x1="-80" y1="0" x2="80" y2="0" stroke="#00e868" stroke-width="0.8" opacity="0.3"/>
    <line x1="-80" y1="25" x2="80" y2="25" stroke="#00e868" stroke-width="0.6" opacity="0.25"/>
    <!-- Pupil -->
    <circle cx="0" cy="0" r="28" fill="none" stroke="#00e868" stroke-width="2"/>
    <circle cx="0" cy="0" r="10" fill="#00e868" opacity="0.3"/>
  </g>
  <text x="600" y="480" text-anchor="middle" font-family="sans-serif" font-size="48" font-weight="900" letter-spacing="12" fill="#00e868">SAURON VISION</text>
  <text x="600" y="520" text-anchor="middle" font-family="monospace" font-size="16" letter-spacing="4" fill="#2a5038">TRADING INTELLIGENCE PLATFORM</text>
</svg>
'''))

    # ================================================================
    # 1 + 3. BASE TEMPLATE — static eye with rotating globe + favicon + OG meta
    # ================================================================

    created.append(create_file("templates/base.html", r'''{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Sauron Vision{% endblock %}</title>

    <!-- Favicon -->
    <link rel="icon" type="image/svg+xml" href="{% static 'favicon.svg' %}">
    <link rel="apple-touch-icon" href="{% static 'favicon.svg' %}">

    <!-- Social / OG Meta -->
    <meta property="og:title" content="Sauron Vision — Trading Intelligence">
    <meta property="og:description" content="AI-powered trading platform monitoring Stocks, Commodities & Forex with real-time signals and strategy engine.">
    <meta property="og:image" content="{% static 'og-image.svg' %}">
    <meta property="og:type" content="website">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="Sauron Vision">
    <meta name="twitter:description" content="AI-powered trading intelligence platform.">
    <meta name="twitter:image" content="{% static 'og-image.svg' %}">
    <meta name="theme-color" content="#00e868">

    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@300;400;500;600;700&family=Orbitron:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-void: #030806;
            --bg-primary: #060e0a;
            --bg-secondary: #081410;
            --bg-card: #0a1a14;
            --bg-card-hover: #0e2218;
            --border: #133020;
            --border-glow: #1a4030;
            --text-primary: #c8e8d8;
            --text-secondary: #5a8a6a;
            --text-muted: #2a5038;
            --accent: #00e868;
            --accent-dim: #0a5028;
            --accent-glow: rgba(0, 232, 104, 0.12);
            --accent-bright: #40ff90;
            --accent-red: #e83030;
            --accent-red-dim: #581818;
            --accent-gold: #d8b020;
            --accent-blue: #30a0e8;
            --accent-purple: #8840d0;
            --danger: #d03030;
            --success: #00e868;
            --warning: #d89020;
            --radius: 6px;
            --radius-lg: 12px;
            --shadow-card: 0 2px 20px rgba(0,0,0,0.5);
            --shadow-glow: 0 0 30px rgba(0, 232, 104, 0.06);
            --font-display: 'Orbitron', sans-serif;
            --font-heading: 'Rajdhani', sans-serif;
            --font-mono: 'Share Tech Mono', monospace;
            --font-body: 'Rajdhani', sans-serif;
            --sidebar-width: 260px;
            --topbar-height: 56px;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: var(--bg-void); color: var(--text-primary);
            font-family: var(--font-body); font-size: 15px; font-weight: 400;
            line-height: 1.6; min-height: 100vh; overflow-x: hidden;
        }

        /* ── Globe-Eye: static eye, rotating globe ─── */
        .globe-eye-bg {
            position: fixed; top: 50%; left: 50%;
            transform: translate(-50%, -50%);
            width: 90vmin; height: 90vmin;
            z-index: 0; pointer-events: none; opacity: 0.04;
        }
        .globe-eye-bg .eye-static { }
        .globe-eye-bg .globe-spin {
            transform-origin: 400px 400px;
            animation: globeRotate 90s linear infinite;
        }
        @keyframes globeRotate {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        #particles-canvas {
            position: fixed; top: 0; left: 0;
            width: 100%; height: 100%; z-index: 0; pointer-events: none;
        }
        .app-layout { display: flex; min-height: 100vh; position: relative; z-index: 1; }

        /* ── Sidebar ─────────────────────────────── */
        .sidebar {
            width: var(--sidebar-width);
            background: linear-gradient(180deg, var(--bg-primary) 0%, var(--bg-void) 100%);
            border-right: 1px solid var(--border);
            position: fixed; top: 0; left: 0; bottom: 0;
            display: flex; flex-direction: column; z-index: 100; overflow-y: auto;
        }
        .sidebar-brand { padding: 20px 20px 16px; border-bottom: 1px solid var(--border); }
        .sidebar-brand h1 {
            font-family: var(--font-display); font-size: 15px; font-weight: 700;
            letter-spacing: 4px; color: var(--accent);
            text-shadow: 0 0 20px var(--accent-glow);
            display: flex; align-items: center; gap: 10px;
        }
        .sidebar-brand .brand-eye {
            width: 32px; height: 32px; flex-shrink: 0;
        }
        .sidebar-brand .subtitle {
            font-family: var(--font-mono); font-size: 10px;
            color: var(--text-muted); letter-spacing: 2px; margin-top: 4px;
        }
        .sidebar-nav { padding: 12px 0; flex: 1; }
        .nav-section {
            padding: 8px 20px 4px; font-family: var(--font-mono); font-size: 9px;
            letter-spacing: 3px; color: var(--text-muted); text-transform: uppercase;
        }
        .nav-link {
            display: flex; align-items: center; gap: 12px; padding: 10px 20px;
            color: var(--text-secondary); text-decoration: none;
            font-family: var(--font-heading); font-size: 14px; font-weight: 500;
            letter-spacing: 0.5px; transition: all 0.2s; border-left: 3px solid transparent;
        }
        .nav-link:hover { color: var(--text-primary); background: var(--accent-glow); border-left-color: var(--accent-dim); }
        .nav-link.active { color: var(--accent); background: var(--accent-glow); border-left-color: var(--accent); }
        .nav-link .icon { font-size: 16px; width: 20px; text-align: center; }
        .sidebar-footer {
            padding: 16px 20px; border-top: 1px solid var(--border);
            font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);
            display: flex; align-items: center; gap: 12px;
        }
        .sidebar-footer a { color: var(--text-secondary); text-decoration: none; }
        .sidebar-footer a:hover { color: var(--accent); }
        /* 2. Logout button as POST form */
        .logout-btn {
            background: none; border: none; color: var(--text-secondary);
            font-family: var(--font-mono); font-size: 11px; cursor: pointer;
            padding: 0;
        }
        .logout-btn:hover { color: var(--accent); }

        /* ── Main ────────────────────────────────── */
        .main-content { margin-left: var(--sidebar-width); flex: 1; min-height: 100vh; }
        .topbar {
            height: var(--topbar-height);
            background: rgba(6, 14, 10, 0.85); backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--border);
            display: flex; align-items: center; justify-content: space-between;
            padding: 0 28px; position: sticky; top: 0; z-index: 50;
        }
        .topbar-title { font-family: var(--font-heading); font-size: 18px; font-weight: 600; letter-spacing: 1px; }
        .topbar-right { display: flex; align-items: center; gap: 16px; font-family: var(--font-mono); font-size: 12px; color: var(--text-secondary); }
        .status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
        .status-dot.online { background: var(--accent); box-shadow: 0 0 8px var(--accent); }
        .page-content { padding: 28px; }

        /* ── Cards ────────────────────────────────── */
        .card {
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: var(--radius-lg); padding: 20px;
            box-shadow: var(--shadow-card); transition: all 0.25s;
        }
        .card:hover { border-color: var(--border-glow); box-shadow: var(--shadow-glow); }
        .card-header {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--border);
        }
        .card-title {
            font-family: var(--font-heading); font-size: 15px; font-weight: 600;
            letter-spacing: 1px; color: var(--text-primary); text-transform: uppercase;
        }
        .grid { display: grid; gap: 20px; }
        .grid-2 { grid-template-columns: repeat(2, 1fr); }
        .grid-3 { grid-template-columns: repeat(3, 1fr); }
        .grid-4 { grid-template-columns: repeat(4, 1fr); }
        .grid-5 { grid-template-columns: repeat(5, 1fr); }
        .grid-6 { grid-template-columns: repeat(6, 1fr); }
        .grid-sidebar { grid-template-columns: 2fr 1fr; }
        @media (max-width: 1400px) { .grid-6 { grid-template-columns: repeat(3, 1fr); } .grid-5 { grid-template-columns: repeat(3, 1fr); } }
        @media (max-width: 1200px) { .grid-4, .grid-3 { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 768px) {
            .grid-2,.grid-3,.grid-4,.grid-5,.grid-6,.grid-sidebar { grid-template-columns: 1fr; }
            .sidebar { display: none; } .main-content { margin-left: 0; }
        }
        .stat-box {
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: var(--radius-lg); padding: 16px 18px; transition: all 0.25s;
        }
        .stat-box:hover { border-color: var(--border-glow); transform: translateY(-2px); }
        .stat-label { font-family: var(--font-mono); font-size: 10px; letter-spacing: 2px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 4px; }
        .stat-value { font-family: var(--font-display); font-size: 22px; font-weight: 700; color: var(--text-primary); }
        .stat-sub { font-family: var(--font-mono); font-size: 11px; margin-top: 3px; color: var(--text-secondary); }
        .stat-change { font-family: var(--font-mono); font-size: 12px; margin-top: 3px; }
        .stat-change.positive { color: var(--success); }
        .stat-change.negative { color: var(--accent-red); }

        .table-wrapper { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; font-family: var(--font-mono); font-size: 13px; }
        thead th { text-align: left; padding: 10px 14px; font-size: 10px; letter-spacing: 2px; color: var(--text-muted); text-transform: uppercase; border-bottom: 1px solid var(--border); white-space: nowrap; }
        tbody td { padding: 10px 14px; border-bottom: 1px solid rgba(19,48,32,0.5); white-space: nowrap; }
        tbody tr { transition: background 0.15s; }
        tbody tr:hover { background: var(--bg-card-hover); }

        .badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-family: var(--font-mono); font-size: 10px; letter-spacing: 1px; text-transform: uppercase; font-weight: 600; }
        .badge-bullish { background: var(--accent-dim); color: var(--accent); }
        .badge-bearish { background: var(--accent-red-dim); color: var(--accent-red); }
        .badge-neutral { background: rgba(90,138,106,0.2); color: var(--text-secondary); }
        .badge-critical { background: rgba(232,48,48,0.15); color: var(--accent-red); animation: badgePulse 2s infinite; }
        .badge-high { background: rgba(216,176,32,0.15); color: var(--accent-gold); }
        .badge-medium { background: rgba(48,160,232,0.12); color: var(--accent-blue); }
        .badge-low { background: rgba(90,138,106,0.15); color: var(--text-secondary); }
        .badge-active { background: var(--accent-dim); color: var(--accent); }
        .badge-proposed { background: rgba(136,64,208,0.15); color: var(--accent-purple); }
        .badge-stock { background: rgba(48,160,232,0.12); color: var(--accent-blue); }
        .badge-forex { background: rgba(216,176,32,0.12); color: var(--accent-gold); }
        .badge-commodity { background: rgba(232,48,48,0.12); color: var(--accent-red); }
        @keyframes badgePulse { 0%,100%{opacity:1;} 50%{opacity:0.6;} }

        .btn { display: inline-flex; align-items: center; gap: 8px; padding: 8px 18px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg-card); color: var(--text-primary); font-family: var(--font-heading); font-size: 13px; font-weight: 600; letter-spacing: 1px; cursor: pointer; text-decoration: none; transition: all 0.2s; }
        .btn:hover { background: var(--bg-card-hover); border-color: var(--accent-dim); }
        .btn-primary { background: var(--accent-dim); border-color: var(--accent); color: #fff; }
        .btn-primary:hover { background: var(--accent); color: #000; }
        .btn-sm { padding: 5px 12px; font-size: 11px; }

        .score-bar { height: 6px; background: var(--bg-void); border-radius: 3px; overflow: hidden; margin-top: 6px; }
        .score-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s ease; }

        .signal-item { padding: 14px 16px; border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 10px; transition: all 0.2s; cursor: pointer; }
        .signal-item:hover { border-color: var(--border-glow); background: var(--bg-card-hover); }
        .signal-item .signal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
        .signal-item .signal-symbol { font-family: var(--font-display); font-size: 14px; font-weight: 600; }
        .signal-item .signal-desc { font-size: 13px; color: var(--text-secondary); }

        .empty-state { text-align: center; padding: 60px 20px; color: var(--text-muted); }
        .empty-state .empty-icon { font-size: 48px; margin-bottom: 16px; opacity: 0.3; }
        .empty-state p { font-family: var(--font-mono); font-size: 13px; letter-spacing: 1px; }

        .fade-in { animation: fadeIn 0.4s ease forwards; }
        .fade-in-up { opacity: 0; transform: translateY(12px); animation: fadeInUp 0.5s ease forwards; }
        @keyframes fadeIn { from{opacity:0;} to{opacity:1;} }
        @keyframes fadeInUp { from{opacity:0;transform:translateY(12px);} to{opacity:1;transform:translateY(0);} }
        .delay-1{animation-delay:.05s} .delay-2{animation-delay:.1s} .delay-3{animation-delay:.15s}
        .delay-4{animation-delay:.2s} .delay-5{animation-delay:.25s} .delay-6{animation-delay:.3s}

        ::-webkit-scrollbar{width:6px} ::-webkit-scrollbar-track{background:var(--bg-void)}
        ::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
        ::-webkit-scrollbar-thumb:hover{background:var(--accent-dim)}

        .detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; }
        .detail-header h2 { font-family: var(--font-display); font-size: 20px; font-weight: 700; letter-spacing: 2px; }
        .detail-meta { display: flex; gap: 20px; margin-top: 8px; font-family: var(--font-mono); font-size: 12px; color: var(--text-secondary); }
        .kv-list { list-style: none; }
        .kv-list li { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid rgba(19,48,32,0.4); font-size: 13px; }
        .kv-list li .label { color: var(--text-secondary); font-family: var(--font-mono); font-size: 11px; letter-spacing: 1px; }
        .kv-list li .value { font-family: var(--font-mono); color: var(--text-primary); }

        /* ── Section dividers on dashboard ────── */
        .section-label {
            font-family: var(--font-mono); font-size: 10px; letter-spacing: 3px;
            color: var(--text-muted); text-transform: uppercase;
            margin: 28px 0 12px; padding-bottom: 6px;
            border-bottom: 1px solid var(--border);
        }
    </style>
    {% block extra_css %}{% endblock %}
</head>
<body>

<!-- Globe-Eye: static eye shape, rotating globe inside -->
<svg class="globe-eye-bg" viewBox="0 0 800 800" xmlns="http://www.w3.org/2000/svg">
    <!-- STATIC: eye structure -->
    <g class="eye-static">
        <ellipse cx="400" cy="400" rx="390" ry="240" fill="none" stroke="#00e868" stroke-width="2"/>
        <ellipse cx="400" cy="400" rx="360" ry="210" fill="none" stroke="#00e868" stroke-width="0.5" opacity="0.5"/>
        <path d="M 10,400 Q 200,100 400,160 Q 600,100 790,400" fill="none" stroke="#00e868" stroke-width="1" opacity="0.6"/>
        <path d="M 10,400 Q 200,700 400,640 Q 600,700 790,400" fill="none" stroke="#00e868" stroke-width="1" opacity="0.6"/>
        <circle cx="400" cy="400" r="160" fill="none" stroke="#00e868" stroke-width="1.5"/>
        <circle cx="400" cy="400" r="60" fill="none" stroke="#00e868" stroke-width="2"/>
        <circle cx="400" cy="400" r="20" fill="#00e868" opacity="0.12"/>
        <line x1="10" y1="400" x2="80" y2="400" stroke="#00e868" stroke-width="0.5" opacity="0.3"/>
        <line x1="720" y1="400" x2="790" y2="400" stroke="#00e868" stroke-width="0.5" opacity="0.3"/>
    </g>
    <!-- ROTATING: globe meridians & latitude lines -->
    <g class="globe-spin">
        <ellipse cx="400" cy="400" rx="50" ry="140" fill="none" stroke="#00e868" stroke-width="0.5" opacity="0.4"/>
        <ellipse cx="400" cy="400" rx="100" ry="140" fill="none" stroke="#00e868" stroke-width="0.4" opacity="0.3"/>
        <ellipse cx="400" cy="400" rx="140" ry="50" fill="none" stroke="#00e868" stroke-width="0.4" opacity="0.3"/>
        <ellipse cx="400" cy="400" rx="30" ry="140" fill="none" stroke="#00e868" stroke-width="0.4" opacity="0.25" transform="rotate(25 400 400)"/>
        <ellipse cx="400" cy="400" rx="120" ry="140" fill="none" stroke="#00e868" stroke-width="0.3" opacity="0.2" transform="rotate(-20 400 400)"/>
        <line x1="260" y1="340" x2="540" y2="340" stroke="#00e868" stroke-width="0.4" opacity="0.25"/>
        <line x1="260" y1="400" x2="540" y2="400" stroke="#00e868" stroke-width="0.5" opacity="0.3"/>
        <line x1="260" y1="460" x2="540" y2="460" stroke="#00e868" stroke-width="0.4" opacity="0.25"/>
    </g>
</svg>

<canvas id="particles-canvas"></canvas>

{% block layout %}
<div class="app-layout">
    <aside class="sidebar">
        <div class="sidebar-brand">
            <h1>
                <!-- Inline eye logo in sidebar -->
                <svg class="brand-eye" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
                    <path d="M2,32 Q16,8 32,14 Q48,8 62,32 Q48,56 32,50 Q16,56 2,32Z" fill="none" stroke="#00e868" stroke-width="2.5"/>
                    <circle cx="32" cy="32" r="12" fill="none" stroke="#00e868" stroke-width="2"/>
                    <circle cx="32" cy="32" r="5" fill="#00e868"/>
                    <ellipse cx="32" cy="32" rx="4" ry="12" fill="none" stroke="#00e868" stroke-width="0.8" opacity="0.5"/>
                </svg>
                SAURON
            </h1>
            <div class="subtitle">TRADING INTELLIGENCE</div>
        </div>
        <nav class="sidebar-nav">
            <div class="nav-section">Command Center</div>
            <a href="{% url 'dashboard' %}" class="nav-link {% if page_id == 'dashboard' %}active{% endif %}"><span class="icon">◉</span> Dashboard</a>
            <div class="nav-section">Markets</div>
            <a href="{% url 'instruments_list' %}" class="nav-link {% if page_id == 'instruments' %}active{% endif %}"><span class="icon">◈</span> Instruments</a>
            <a href="{% url 'market_quotes' %}" class="nav-link {% if page_id == 'quotes' %}active{% endif %}"><span class="icon">◆</span> Live Quotes</a>
            <a href="{% url 'economic_calendar' %}" class="nav-link {% if page_id == 'calendar' %}active{% endif %}"><span class="icon">◇</span> Economic Calendar</a>
            <div class="nav-section">Intelligence</div>
            <a href="{% url 'signals_list' %}" class="nav-link {% if page_id == 'signals' %}active{% endif %}"><span class="icon">⚡</span> Signals</a>
            <a href="{% url 'strategies_list' %}" class="nav-link {% if page_id == 'strategies' %}active{% endif %}"><span class="icon">⬡</span> Strategies</a>
            <a href="{% url 'news_feed' %}" class="nav-link {% if page_id == 'news' %}active{% endif %}"><span class="icon">▤</span> News & Sentiment</a>
            <div class="nav-section">Portfolio</div>
            <a href="{% url 'portfolio_overview' %}" class="nav-link {% if page_id == 'portfolio' %}active{% endif %}"><span class="icon">◎</span> Portfolio</a>
            <a href="{% url 'positions_list' %}" class="nav-link {% if page_id == 'positions' %}active{% endif %}"><span class="icon">▣</span> Positions</a>
            <div class="nav-section">AI Agents</div>
            <a href="{% url 'ai_insights' %}" class="nav-link {% if page_id == 'ai' %}active{% endif %}"><span class="icon">◬</span> AI Insights</a>
            <a href="{% url 'ai_tasks_list' %}" class="nav-link {% if page_id == 'ai_tasks' %}active{% endif %}"><span class="icon">▸</span> Agent Tasks</a>
        </nav>
        <div class="sidebar-footer">
            <a href="{% url 'admin:index' %}">⚙ Admin</a>
            <!-- 2. Logout as POST form -->
            <form method="post" action="{% url 'logout' %}" style="display:inline;">
                {% csrf_token %}
                <button type="submit" class="logout-btn">⏻ Logout</button>
            </form>
        </div>
    </aside>

    <main class="main-content">
        <header class="topbar">
            <span class="topbar-title">{% block page_title %}Dashboard{% endblock %}</span>
            <div class="topbar-right">
                <span><span class="status-dot online"></span> LIVE</span>
                <span id="clock"></span>
                <span>{{ request.user.username|upper }}</span>
            </div>
        </header>
        <div class="page-content fade-in">
            {% block content %}{% endblock %}
        </div>
    </main>
</div>
{% endblock %}

<script>
(function() {
    const canvas = document.getElementById('particles-canvas');
    const ctx = canvas.getContext('2d');
    let particles = [];
    function resize() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; }
    resize(); window.addEventListener('resize', resize);
    class Particle {
        constructor() { this.reset(); }
        reset() {
            this.x = Math.random() * canvas.width; this.y = Math.random() * canvas.height;
            this.vx = (Math.random() - 0.5) * 0.3; this.vy = (Math.random() - 0.5) * 0.3;
            this.size = Math.random() * 1.5 + 0.5; this.alpha = Math.random() * 0.25 + 0.05;
        }
        update() { this.x += this.vx; this.y += this.vy; if (this.x<0||this.x>canvas.width||this.y<0||this.y>canvas.height) this.reset(); }
        draw() { ctx.beginPath(); ctx.arc(this.x,this.y,this.size,0,Math.PI*2); ctx.fillStyle=`rgba(0,232,104,${this.alpha})`; ctx.fill(); }
    }
    for (let i=0;i<80;i++) particles.push(new Particle());
    function animate() {
        ctx.clearRect(0,0,canvas.width,canvas.height);
        particles.forEach(p=>{p.update();p.draw();});
        for(let i=0;i<particles.length;i++) for(let j=i+1;j<particles.length;j++){
            const d=Math.hypot(particles[i].x-particles[j].x,particles[i].y-particles[j].y);
            if(d<150){ctx.beginPath();ctx.moveTo(particles[i].x,particles[i].y);ctx.lineTo(particles[j].x,particles[j].y);ctx.strokeStyle=`rgba(0,232,104,${0.04*(1-d/150)})`;ctx.stroke();}
        }
        requestAnimationFrame(animate);
    }
    animate();
    function updateClock(){const el=document.getElementById('clock');if(el){const n=new Date();el.textContent=n.toUTCString().slice(17,25)+' UTC';}}
    setInterval(updateClock,1000);updateClock();
})();
</script>
{% block extra_js %}{% endblock %}
</body>
</html>
'''))

    # ================================================================
    # 1. LOGIN — static eye, rotating globe, same scanner fixes
    # ================================================================

    created.append(create_file("templates/registration/login.html", r'''{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sauron Vision — Access</title>
    <link rel="icon" type="image/svg+xml" href="{% static 'favicon.svg' %}">
    <meta property="og:title" content="Sauron Vision — Trading Intelligence">
    <meta property="og:image" content="{% static 'og-image.svg' %}">
    <meta name="theme-color" content="#00e868">
    <link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700;900&family=Rajdhani:wght@300;400;600&display=swap" rel="stylesheet">
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:#030806;color:#c8e8d8;font-family:'Rajdhani',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;overflow:hidden}
        .grid-bg{position:fixed;top:-50%;left:-50%;width:200%;height:200%;z-index:0;background-image:linear-gradient(rgba(0,232,104,0.04) 1px,transparent 1px),linear-gradient(90deg,rgba(0,232,104,0.04) 1px,transparent 1px);background-size:60px 60px;animation:gridMove 25s linear infinite}
        @keyframes gridMove{0%{transform:translate(0,0)}100%{transform:translate(60px,60px)}}

        /* Globe-eye: static eye, spinning globe */
        .globe-eye-login{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);width:110vmin;height:110vmin;z-index:1;pointer-events:none;opacity:0.035}
        .globe-eye-login .globe-spin{transform-origin:400px 400px;animation:globeSpin 60s linear infinite}
        @keyframes globeSpin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}

        canvas{position:fixed;top:0;left:0;width:100%;height:100%;z-index:2}
        .scan-line{position:fixed;top:0;left:0;bottom:0;width:3px;z-index:3;animation:scanRTL 8s linear infinite}
        .scan-line::before{content:'';position:absolute;top:0;left:-40px;bottom:0;width:80px;background:linear-gradient(90deg,transparent,rgba(0,232,104,0.06),transparent)}
        .scan-line::after{content:'';position:absolute;top:0;left:0;bottom:0;width:3px;background:linear-gradient(180deg,transparent 10%,rgba(0,232,104,0.4) 50%,transparent 90%);box-shadow:0 0 15px rgba(0,232,104,0.3),0 0 40px rgba(0,232,104,0.1)}
        @keyframes scanRTL{0%{left:100%}100%{left:-80px}}

        .login-container{position:relative;z-index:10;width:380px;animation:fadeInUp .8s ease}
        @keyframes fadeInUp{from{opacity:0;transform:translateY(40px)}to{opacity:1;transform:translateY(0)}}
        .login-eye{width:64px;height:64px;margin:0 auto 20px}
        .login-title{font-family:'Orbitron',sans-serif;font-size:24px;font-weight:900;letter-spacing:6px;color:#00e868;text-align:center;margin-bottom:4px;text-shadow:0 0 30px rgba(0,232,104,0.2)}
        .login-subtitle{font-family:'Share Tech Mono',monospace;font-size:11px;letter-spacing:3px;color:#2a5038;text-align:center;margin-bottom:32px}
        .login-card{background:rgba(10,26,20,0.9);border:1px solid #133020;border-radius:12px;padding:32px;backdrop-filter:blur(20px);box-shadow:0 4px 40px rgba(0,0,0,0.5),0 0 60px rgba(0,232,104,0.03)}
        .form-group{margin-bottom:20px}
        .form-group label{display:block;font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:3px;color:#5a8a6a;text-transform:uppercase;margin-bottom:8px}
        .form-group input{width:100%;padding:12px 16px;background:#060e0a;border:1px solid #133020;border-radius:6px;color:#c8e8d8;font-family:'Share Tech Mono',monospace;font-size:14px;outline:none;transition:all .2s}
        .form-group input:focus{border-color:#00e868;box-shadow:0 0 15px rgba(0,232,104,0.1)}
        .btn-login{width:100%;padding:14px;background:linear-gradient(135deg,#0a5028,#00e868);border:none;border-radius:6px;color:#020804;font-family:'Orbitron',sans-serif;font-size:13px;font-weight:700;letter-spacing:4px;cursor:pointer;transition:all .3s;text-transform:uppercase}
        .btn-login:hover{transform:translateY(-2px);box-shadow:0 8px 30px rgba(0,232,104,0.25)}
        .errors{background:rgba(232,48,48,0.08);border:1px solid rgba(232,48,48,0.25);border-radius:6px;padding:12px;margin-bottom:20px;font-family:'Share Tech Mono',monospace;font-size:12px;color:#e83030}
    </style>
</head>
<body>
    <div class="grid-bg"></div>

    <!-- Static eye, rotating globe -->
    <svg class="globe-eye-login" viewBox="0 0 800 800" xmlns="http://www.w3.org/2000/svg">
        <g class="eye-static">
            <ellipse cx="400" cy="400" rx="390" ry="240" fill="none" stroke="#00e868" stroke-width="2"/>
            <ellipse cx="400" cy="400" rx="360" ry="210" fill="none" stroke="#00e868" stroke-width="0.8" opacity="0.4"/>
            <circle cx="400" cy="400" r="160" fill="none" stroke="#00e868" stroke-width="1.5"/>
            <circle cx="400" cy="400" r="60" fill="none" stroke="#00e868" stroke-width="2"/>
            <circle cx="400" cy="400" r="20" fill="#00e868" opacity="0.12"/>
            <path d="M 10,400 Q 200,100 400,160 Q 600,100 790,400" fill="none" stroke="#00e868" stroke-width="1.2" opacity="0.5"/>
            <path d="M 10,400 Q 200,700 400,640 Q 600,700 790,400" fill="none" stroke="#00e868" stroke-width="1.2" opacity="0.5"/>
        </g>
        <g class="globe-spin">
            <ellipse cx="400" cy="400" rx="50" ry="140" fill="none" stroke="#00e868" stroke-width="0.5" opacity="0.35"/>
            <ellipse cx="400" cy="400" rx="100" ry="140" fill="none" stroke="#00e868" stroke-width="0.4" opacity="0.25"/>
            <ellipse cx="400" cy="400" rx="140" ry="50" fill="none" stroke="#00e868" stroke-width="0.4" opacity="0.25"/>
            <line x1="260" y1="340" x2="540" y2="340" stroke="#00e868" stroke-width="0.4" opacity="0.2"/>
            <line x1="260" y1="400" x2="540" y2="400" stroke="#00e868" stroke-width="0.5" opacity="0.3"/>
            <line x1="260" y1="460" x2="540" y2="460" stroke="#00e868" stroke-width="0.4" opacity="0.2"/>
            <ellipse cx="400" cy="400" rx="30" ry="140" fill="none" stroke="#00e868" stroke-width="0.4" opacity="0.2" transform="rotate(25 400 400)"/>
            <ellipse cx="400" cy="400" rx="120" ry="140" fill="none" stroke="#00e868" stroke-width="0.3" opacity="0.15" transform="rotate(-20 400 400)"/>
        </g>
    </svg>

    <canvas id="particles-canvas"></canvas>
    <div class="scan-line"></div>

    <div class="login-container">
        <!-- Eye logo on login -->
        <svg class="login-eye" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
            <path d="M2,32 Q16,8 32,14 Q48,8 62,32 Q48,56 32,50 Q16,56 2,32Z" fill="none" stroke="#00e868" stroke-width="2.5">
                <animate attributeName="stroke-opacity" values="0.4;1;0.4" dur="3s" repeatCount="indefinite"/>
            </path>
            <circle cx="32" cy="32" r="12" fill="none" stroke="#00e868" stroke-width="2"/>
            <circle cx="32" cy="32" r="5" fill="#00e868" opacity="0.8">
                <animate attributeName="r" values="4;6;4" dur="3s" repeatCount="indefinite"/>
            </circle>
            <ellipse cx="32" cy="32" rx="4" ry="12" fill="none" stroke="#00e868" stroke-width="0.8" opacity="0.5">
                <animateTransform attributeName="transform" type="rotate" from="0 32 32" to="360 32 32" dur="30s" repeatCount="indefinite"/>
            </ellipse>
        </svg>
        <h1 class="login-title">SAURON VISION</h1>
        <p class="login-subtitle">AUTHENTICATE TO PROCEED</p>
        <div class="login-card">
            {% if form.errors %}<div class="errors">⚠ AUTHENTICATION FAILED — INVALID CREDENTIALS</div>{% endif %}
            <form method="post" action="{% url 'login' %}">
                {% csrf_token %}
                <div class="form-group"><label for="id_username">Operator ID</label><input type="text" name="username" id="id_username" autofocus autocomplete="username" required></div>
                <div class="form-group"><label for="id_password">Access Key</label><input type="password" name="password" id="id_password" autocomplete="current-password" required></div>
                <input type="hidden" name="next" value="{{ next }}">
                <button type="submit" class="btn-login">Initialize Session</button>
            </form>
        </div>
    </div>

    <script>
    const canvas=document.getElementById('particles-canvas');const ctx=canvas.getContext('2d');let particles=[];
    function resize(){canvas.width=window.innerWidth;canvas.height=window.innerHeight}resize();window.addEventListener('resize',resize);
    class P{constructor(){this.reset()}reset(){this.x=Math.random()*canvas.width;this.y=Math.random()*canvas.height;this.vx=(Math.random()-.5)*.35;this.vy=(Math.random()-.5)*.35;this.s=Math.random()*1.5+.3;this.a=Math.random()*.2+.04}update(){this.x+=this.vx;this.y+=this.vy;if(this.x<0||this.x>canvas.width||this.y<0||this.y>canvas.height)this.reset()}draw(){ctx.beginPath();ctx.arc(this.x,this.y,this.s,0,Math.PI*2);ctx.fillStyle=`rgba(0,232,104,${this.a})`;ctx.fill()}}
    for(let i=0;i<60;i++)particles.push(new P());
    function animate(){ctx.clearRect(0,0,canvas.width,canvas.height);particles.forEach(p=>{p.update();p.draw()});for(let i=0;i<particles.length;i++)for(let j=i+1;j<particles.length;j++){const d=Math.hypot(particles[i].x-particles[j].x,particles[i].y-particles[j].y);if(d<120){ctx.beginPath();ctx.moveTo(particles[i].x,particles[i].y);ctx.lineTo(particles[j].x,particles[j].y);ctx.strokeStyle=`rgba(0,232,104,${.04*(1-d/120)})`;ctx.stroke()}}requestAnimationFrame(animate)}animate();
    </script>
</body>
</html>
'''))

    # ================================================================
    # 4. ENRICHED DASHBOARD — many more metrics
    # ================================================================

    created.append(create_file("templates/dashboard/dashboard.html", r'''{% extends "base.html" %}
{% block title %}Sauron Vision — Dashboard{% endblock %}
{% block page_title %}⬡ COMMAND CENTER{% endblock %}

{% block content %}
<!-- ── Row 1: Portfolio KPIs ──────────────────────────── -->
<div class="section-label fade-in-up">Portfolio Overview</div>
<div class="grid grid-6" style="margin-bottom: 20px;">
    <div class="stat-box fade-in-up delay-1">
        <div class="stat-label">Portfolio Value</div>
        <div class="stat-value">€{{ portfolio.current_value|default:"10,000" }}</div>
        <div class="stat-change positive">▲ {{ daily_pnl_pct|default:"+0.00" }}% today</div>
    </div>
    <div class="stat-box fade-in-up delay-2">
        <div class="stat-label">Cash Available</div>
        <div class="stat-value">€{{ portfolio.cash_available|default:"10,000" }}</div>
        <div class="stat-sub">{{ cash_pct|default:"100" }}% of portfolio</div>
    </div>
    <div class="stat-box fade-in-up delay-3">
        <div class="stat-label">Unrealized P&L</div>
        <div class="stat-value" style="color:{% if total_unrealized_pnl >= 0 %}var(--success){% else %}var(--accent-red){% endif %}">€{{ total_unrealized_pnl|default:"0.00" }}</div>
        <div class="stat-sub">{{ open_positions_count|default:"0" }} open positions</div>
    </div>
    <div class="stat-box fade-in-up delay-4">
        <div class="stat-label">Total Exposure</div>
        <div class="stat-value">{{ total_exposure_pct|default:"0" }}%</div>
        <div class="stat-sub">limit: {{ portfolio.max_total_exposure_pct|default:"100" }}%</div>
    </div>
    <div class="stat-box fade-in-up delay-5">
        <div class="stat-label">Max Drawdown</div>
        <div class="stat-value" style="color: var(--accent-red);">{{ max_drawdown|default:"0.00" }}%</div>
        <div class="stat-sub">limit: {{ portfolio.max_daily_loss_pct|default:"3.0" }}%</div>
    </div>
    <div class="stat-box fade-in-up delay-6">
        <div class="stat-label">Sharpe Ratio</div>
        <div class="stat-value">{{ sharpe_ratio|default:"—" }}</div>
        <div class="stat-sub">risk-adjusted return</div>
    </div>
</div>

<!-- ── Row 2: Market & Intelligence KPIs ─────────────── -->
<div class="section-label fade-in-up">Markets & Intelligence</div>
<div class="grid grid-6" style="margin-bottom: 20px;">
    <div class="stat-box fade-in-up delay-1">
        <div class="stat-label">Instruments</div>
        <div class="stat-value">{{ instruments_count|default:"0" }}</div>
        <div class="stat-sub">{{ watchlist_count|default:"0" }} on watchlist</div>
    </div>
    <div class="stat-box fade-in-up delay-2">
        <div class="stat-label">Active Signals</div>
        <div class="stat-value" style="color: var(--accent);">{{ active_signals_count|default:"0" }}</div>
        <div class="stat-sub">{{ bullish_count|default:"0" }}▲ {{ bearish_count|default:"0" }}▼</div>
    </div>
    <div class="stat-box fade-in-up delay-3">
        <div class="stat-label">Avg Signal Score</div>
        <div class="stat-value">{{ avg_signal_score|default:"—" }}</div>
        <div class="stat-sub">composite confidence</div>
    </div>
    <div class="stat-box fade-in-up delay-4">
        <div class="stat-label">Strategies</div>
        <div class="stat-value">{{ active_strategies_count|default:"0" }}</div>
        <div class="stat-sub">{{ proposed_strategies|default:"0" }} proposed</div>
    </div>
    <div class="stat-box fade-in-up delay-5">
        <div class="stat-label">News (24h)</div>
        <div class="stat-value">{{ news_24h|default:"0" }}</div>
        <div class="stat-sub">avg sentiment: {{ avg_news_sentiment|default:"—" }}</div>
    </div>
    <div class="stat-box fade-in-up delay-6">
        <div class="stat-label">Econ Events</div>
        <div class="stat-value">{{ upcoming_events|default:"0" }}</div>
        <div class="stat-sub">{{ high_impact_events|default:"0" }} high impact</div>
    </div>
</div>

<!-- ── Row 3: AI KPIs ────────────────────────────────── -->
<div class="section-label fade-in-up">AI Agents</div>
<div class="grid grid-5" style="margin-bottom: 24px;">
    <div class="stat-box fade-in-up delay-1">
        <div class="stat-label">AI Tasks (24h)</div>
        <div class="stat-value">{{ ai_tasks_24h|default:"0" }}</div>
        <div class="stat-sub">{{ ai_success_rate|default:"0" }}% success</div>
    </div>
    <div class="stat-box fade-in-up delay-2">
        <div class="stat-label">AI Cost (24h)</div>
        <div class="stat-value">{{ ai_cost_24h|default:"$0.00" }}</div>
        <div class="stat-sub">{{ ai_cost_mtd|default:"$0.00" }} this month</div>
    </div>
    <div class="stat-box fade-in-up delay-3">
        <div class="stat-label">Avg Response</div>
        <div class="stat-value">{{ ai_avg_duration|default:"0.0" }}s</div>
        <div class="stat-sub">avg latency</div>
    </div>
    <div class="stat-box fade-in-up delay-4">
        <div class="stat-label">Tokens (24h)</div>
        <div class="stat-value">{{ ai_tokens_24h|default:"0" }}</div>
        <div class="stat-sub">in + out combined</div>
    </div>
    <div class="stat-box fade-in-up delay-5">
        <div class="stat-label">Last Agent Run</div>
        <div class="stat-value" style="font-size: 14px;">{{ last_agent_name|default:"—" }}</div>
        <div class="stat-sub">{{ last_agent_time|default:"—" }}</div>
    </div>
</div>

<!-- ── Row 4: Exposure Breakdown ─────────────────────── -->
<div class="section-label fade-in-up">Exposure Breakdown</div>
<div class="grid grid-4" style="margin-bottom: 24px;">
    <div class="stat-box fade-in-up delay-1">
        <div class="stat-label">Stocks</div>
        <div class="stat-value" style="color: var(--accent-blue);">{{ exposure.stock|default:"0" }}%</div>
        <div class="score-bar"><div class="score-bar-fill" style="width:{{ exposure.stock|default:0 }}%; background: var(--accent-blue);"></div></div>
    </div>
    <div class="stat-box fade-in-up delay-2">
        <div class="stat-label">Forex</div>
        <div class="stat-value" style="color: var(--accent-gold);">{{ exposure.forex|default:"0" }}%</div>
        <div class="score-bar"><div class="score-bar-fill" style="width:{{ exposure.forex|default:0 }}%; background: var(--accent-gold);"></div></div>
    </div>
    <div class="stat-box fade-in-up delay-3">
        <div class="stat-label">Commodities</div>
        <div class="stat-value" style="color: var(--accent-red);">{{ exposure.commodity|default:"0" }}%</div>
        <div class="score-bar"><div class="score-bar-fill" style="width:{{ exposure.commodity|default:0 }}%; background: var(--accent-red);"></div></div>
    </div>
    <div class="stat-box fade-in-up delay-4">
        <div class="stat-label">Cash</div>
        <div class="stat-value" style="color: var(--accent);">{{ exposure.cash|default:"100" }}%</div>
        <div class="score-bar"><div class="score-bar-fill" style="width:{{ exposure.cash|default:100 }}%; background: var(--accent);"></div></div>
    </div>
</div>

<!-- ── Row 5: Main content grid ──────────────────────── -->
<div class="grid grid-sidebar">
    <div>
        <!-- Active Signals -->
        <div class="card fade-in-up delay-3" style="margin-bottom: 20px;">
            <div class="card-header">
                <span class="card-title">⚡ Active Signals</span>
                <a href="{% url 'signals_list' %}" class="btn btn-sm">View All →</a>
            </div>
            {% if recent_signals %}
                {% for signal in recent_signals %}
                <div class="signal-item">
                    <div class="signal-header">
                        <span>
                            <span class="signal-symbol">{{ signal.instrument.symbol }}</span>
                            <span class="badge badge-{{ signal.direction }}">{{ signal.direction }}</span>
                            <span class="badge badge-{{ signal.urgency }}">{{ signal.urgency }}</span>
                        </span>
                        <span style="font-family:var(--font-display);font-size:13px;">{{ signal.score|floatformat:2 }}</span>
                    </div>
                    <div class="signal-desc">{{ signal.title }}</div>
                </div>
                {% endfor %}
            {% else %}
                <div class="empty-state"><div class="empty-icon">⚡</div><p>NO ACTIVE SIGNALS — MARKETS SCANNING</p></div>
            {% endif %}
        </div>

        <!-- Strategies -->
        <div class="card fade-in-up delay-4">
            <div class="card-header">
                <span class="card-title">⬡ Active Strategies</span>
                <a href="{% url 'strategies_list' %}" class="btn btn-sm">View All →</a>
            </div>
            {% if active_strategies %}
            <div class="table-wrapper"><table>
                <thead><tr><th>Strategy</th><th>Horizon</th><th>Status</th><th>P&L</th></tr></thead>
                <tbody>
                {% for s in active_strategies %}
                <tr>
                    <td>{{ s.name|truncatechars:40 }}</td>
                    <td><span class="badge badge-medium">{{ s.time_horizon }}</span></td>
                    <td><span class="badge badge-active">{{ s.status }}</span></td>
                    <td style="color:{% if s.pnl >= 0 %}var(--success){% else %}var(--accent-red){% endif %}">{{ s.pnl_pct|floatformat:2 }}%</td>
                </tr>
                {% endfor %}
                </tbody>
            </table></div>
            {% else %}
                <div class="empty-state"><div class="empty-icon">⬡</div><p>NO ACTIVE STRATEGIES</p></div>
            {% endif %}
        </div>
    </div>

    <div>
        <!-- News -->
        <div class="card fade-in-up delay-2" style="margin-bottom: 20px;">
            <div class="card-header">
                <span class="card-title">▤ Latest News</span>
                <a href="{% url 'news_feed' %}" class="btn btn-sm">All →</a>
            </div>
            {% if recent_news %}
                {% for article in recent_news %}
                <div style="padding:8px 0;border-bottom:1px solid rgba(19,48,32,0.4);">
                    <div style="font-size:13px;margin-bottom:3px;">{{ article.title|truncatechars:80 }}</div>
                    <div style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);">
                        {{ article.source }} · {{ article.published_at|timesince }} ago
                        {% if article.ai_sentiment_score != None %}
                        · <span style="color:{% if article.ai_sentiment_score > 0 %}var(--success){% elif article.ai_sentiment_score < 0 %}var(--accent-red){% else %}var(--text-secondary){% endif %}">{{ article.ai_sentiment_score|floatformat:2 }}</span>
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <div class="empty-state" style="padding:30px;"><p>NO NEWS YET</p></div>
            {% endif %}
        </div>

        <!-- Recent AI Tasks -->
        <div class="card fade-in-up delay-3" style="margin-bottom: 20px;">
            <div class="card-header">
                <span class="card-title">◬ AI Agents</span>
                <a href="{% url 'ai_insights' %}" class="btn btn-sm">Details →</a>
            </div>
            {% if recent_ai_tasks %}
                {% for task in recent_ai_tasks %}
                <div style="padding:6px 0;border-bottom:1px solid rgba(19,48,32,0.3);font-size:12px;">
                    <span style="color:{% if task.success %}var(--success){% else %}var(--accent-red){% endif %}">●</span>
                    <span style="font-family:var(--font-mono);color:var(--text-secondary);">{{ task.agent }}</span>
                    <span style="float:right;color:var(--text-muted);font-family:var(--font-mono);font-size:10px;">{{ task.created_at|timesince }} ago</span>
                </div>
                {% endfor %}
            {% else %}
                <div class="empty-state" style="padding:30px;"><p>NO AI TASKS YET</p></div>
            {% endif %}
        </div>

        <!-- Market Sessions -->
        <div class="card fade-in-up delay-4">
            <div class="card-header"><span class="card-title">◎ Market Sessions</span></div>
            <ul class="kv-list">
                <li><span class="label">FOREX</span><span class="value" style="color:{% if forex_open %}var(--success){% else %}var(--accent-red){% endif %}">{% if forex_open %}OPEN{% else %}CLOSED{% endif %}</span></li>
                <li><span class="label">US MARKETS</span><span class="value" style="color:{% if us_open %}var(--success){% else %}var(--accent-red){% endif %}">{% if us_open %}OPEN{% else %}CLOSED{% endif %}</span></li>
                <li><span class="label">EU MARKETS</span><span class="value" style="color:{% if eu_open %}var(--success){% else %}var(--accent-red){% endif %}">{% if eu_open %}OPEN{% else %}CLOSED{% endif %}</span></li>
                <li><span class="label">MODE</span><span class="value">{% if is_weekend %}WEEKEND{% else %}LIVE{% endif %}</span></li>
            </ul>
        </div>
    </div>
</div>
{% endblock %}
'''))

    # ================================================================
    # 4. ENRICHED DASHBOARD VIEW
    # ================================================================

    created.append(create_file("dashboard/views.py", '''"""Sauron Vision — Dashboard Views (enriched)."""
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta
from django.db.models import Avg, Sum


@login_required
def dashboard(request):
    from instruments.models import Instrument
    from signals.models import Signal
    from strategies.models import Strategy
    from scraping.models import NewsArticle
    from ai_agents.models import AgentTask
    from market_data.models import EconomicEvent
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import Position, PortfolioSnapshot
    from core.market_calendar import is_forex_open, is_us_market_open, is_eu_market_open, is_weekend

    portfolio = get_or_create_default_portfolio()
    now = timezone.now()
    day_ago = now - timedelta(hours=24)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Portfolio metrics
    open_positions = Position.objects.filter(portfolio=portfolio, closed_at__isnull=True)
    total_unrealized = sum(float(p.unrealized_pnl) for p in open_positions)
    cash_pct = round(float(portfolio.cash_available) / max(float(portfolio.current_value), 1) * 100)

    latest_snapshot = PortfolioSnapshot.objects.filter(portfolio=portfolio).first()

    # Signal metrics
    active_signals = Signal.objects.filter(is_active=True)
    avg_score = active_signals.aggregate(avg=Avg("score"))["avg"]

    # Strategy metrics
    active_strats = Strategy.objects.filter(status__in=["active", "approved"])
    proposed_strats = Strategy.objects.filter(status="proposed")

    # News metrics
    news_24h_qs = NewsArticle.objects.filter(published_at__gte=day_ago)
    avg_sentiment = news_24h_qs.filter(ai_sentiment_score__isnull=False).aggregate(avg=Avg("ai_sentiment_score"))["avg"]

    # Economic calendar
    upcoming = EconomicEvent.objects.filter(datetime__gte=now)
    high_impact = upcoming.filter(impact="high")

    # AI metrics
    ai_24h = AgentTask.objects.filter(created_at__gte=day_ago)
    ai_mtd = AgentTask.objects.filter(created_at__gte=month_start)
    ai_total = ai_24h.count()
    ai_success = ai_24h.filter(success=True).count()
    ai_tokens = sum(t.input_tokens + t.output_tokens for t in ai_24h)
    last_task = AgentTask.objects.order_by("-created_at").first()

    context = {
        "page_id": "dashboard",
        "portfolio": portfolio,

        # Portfolio
        "daily_pnl_pct": "+{:.2f}".format(latest_snapshot.daily_pnl_pct) if latest_snapshot else "+0.00",
        "cash_pct": cash_pct,
        "total_unrealized_pnl": "{:.2f}".format(total_unrealized),
        "open_positions_count": open_positions.count(),
        "total_exposure_pct": 100 - cash_pct,
        "max_drawdown": "{:.2f}".format(latest_snapshot.max_drawdown) if latest_snapshot else "0.00",
        "sharpe_ratio": "{:.2f}".format(latest_snapshot.sharpe_ratio) if latest_snapshot and latest_snapshot.sharpe_ratio else "—",

        # Markets
        "instruments_count": Instrument.objects.filter(is_active=True).count(),
        "watchlist_count": Instrument.objects.filter(is_watchlist=True).count(),
        "active_signals_count": active_signals.count(),
        "bullish_count": active_signals.filter(direction="bullish").count(),
        "bearish_count": active_signals.filter(direction="bearish").count(),
        "avg_signal_score": "{:.2f}".format(avg_score) if avg_score else "—",
        "active_strategies_count": active_strats.count(),
        "proposed_strategies": proposed_strats.count(),

        # News
        "news_24h": news_24h_qs.count(),
        "avg_news_sentiment": "{:.2f}".format(avg_sentiment) if avg_sentiment else "—",

        # Economic calendar
        "upcoming_events": upcoming.count(),
        "high_impact_events": high_impact.count(),

        # AI
        "ai_tasks_24h": ai_total,
        "ai_success_rate": round(ai_success / ai_total * 100) if ai_total > 0 else 0,
        "ai_cost_24h": "${:.2f}".format(sum(float(t.cost_usd) for t in ai_24h)),
        "ai_cost_mtd": "${:.2f}".format(sum(float(t.cost_usd) for t in ai_mtd)),
        "ai_avg_duration": "{:.1f}".format(sum(t.duration_seconds for t in ai_24h) / ai_total if ai_total > 0 else 0),
        "ai_tokens_24h": "{:,}".format(ai_tokens),
        "last_agent_name": last_task.agent if last_task else "—",
        "last_agent_time": "{} ago".format(last_task.created_at.strftime("%H:%M")) if last_task else "—",

        # Exposure
        "exposure": {"stock": 0, "forex": 0, "commodity": 0, "cash": cash_pct},

        # Market sessions
        "forex_open": is_forex_open(),
        "us_open": is_us_market_open(),
        "eu_open": is_eu_market_open(),
        "is_weekend": is_weekend(),

        # Feed data
        "recent_signals": active_signals.select_related("instrument").order_by("-created_at")[:8],
        "active_strategies": active_strats.order_by("-created_at")[:5],
        "recent_news": NewsArticle.objects.order_by("-published_at")[:6],
        "recent_ai_tasks": AgentTask.objects.order_by("-created_at")[:8],
    }
    return render(request, "dashboard/dashboard.html", context)


@login_required
def instruments_list(request):
    from instruments.models import Instrument
    qs = Instrument.objects.filter(is_active=True)
    filter_type = request.GET.get("filter", "")
    if filter_type == "watchlist":
        qs = qs.filter(is_watchlist=True)
    elif filter_type in ["stock", "forex", "commodity"]:
        qs = qs.filter(asset_class=filter_type)
    return render(request, "dashboard/instruments_list.html", {"page_id": "instruments", "instruments": qs.order_by("asset_class", "symbol"), "filter": filter_type})


@login_required
def market_quotes(request):
    from market_data.models import LiveQuote
    return render(request, "dashboard/market_quotes.html", {"page_id": "quotes", "quotes": LiveQuote.objects.select_related("instrument").order_by("instrument__symbol")})


@login_required
def economic_calendar(request):
    from market_data.models import EconomicEvent
    return render(request, "dashboard/economic_calendar.html", {"page_id": "calendar", "events": EconomicEvent.objects.order_by("datetime")[:50]})


@login_required
def signals_list(request):
    from signals.models import Signal
    active_only = request.GET.get("active") == "1"
    qs = Signal.objects.select_related("instrument").order_by("-created_at")
    if active_only:
        qs = qs.filter(is_active=True)
    active_qs = Signal.objects.filter(is_active=True)
    return render(request, "dashboard/signals_list.html", {
        "page_id": "signals", "signals": qs[:100], "active_only": active_only,
        "active_count": active_qs.count(),
        "bullish_count": active_qs.filter(direction="bullish").count(),
        "bearish_count": active_qs.filter(direction="bearish").count(),
        "avg_score": "{:.2f}".format(active_qs.aggregate(avg=Avg("score"))["avg"] or 0),
    })


@login_required
def strategies_list(request):
    from strategies.models import Strategy
    qs = Strategy.objects.prefetch_related("legs").order_by("-created_at")
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)
    return render(request, "dashboard/strategies_list.html", {"page_id": "strategies", "strategies": qs[:50]})


@login_required
def strategy_detail(request, pk):
    from strategies.models import Strategy
    strategy = get_object_or_404(Strategy.objects.prefetch_related("legs__instrument", "adjustments"), pk=pk)
    return render(request, "dashboard/strategy_detail.html", {"page_id": "strategies", "strategy": strategy})


@login_required
def news_feed(request):
    from scraping.models import NewsArticle
    return render(request, "dashboard/news_feed.html", {"page_id": "news", "articles": NewsArticle.objects.prefetch_related("ai_affected_instruments").order_by("-published_at")[:100]})


@login_required
def portfolio_overview(request):
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import PortfolioSnapshot
    portfolio = get_or_create_default_portfolio()
    return render(request, "dashboard/portfolio_overview.html", {
        "page_id": "portfolio", "portfolio": portfolio,
        "snapshots": PortfolioSnapshot.objects.filter(portfolio=portfolio).order_by("-date")[:30],
        "open_positions_count": portfolio.positions.filter(closed_at__isnull=True).count(),
    })


@login_required
def positions_list(request):
    from portfolio.services import get_or_create_default_portfolio
    portfolio = get_or_create_default_portfolio()
    return render(request, "dashboard/positions_list.html", {
        "page_id": "positions",
        "positions": portfolio.positions.filter(closed_at__isnull=True).select_related("instrument", "strategy"),
    })


@login_required
def ai_insights(request):
    from ai_agents.models import AgentTask
    now = timezone.now()
    day_ago = now - timedelta(hours=24)
    tasks_24h_qs = AgentTask.objects.filter(created_at__gte=day_ago)
    total_24h = tasks_24h_qs.count()
    success_24h = tasks_24h_qs.filter(success=True).count()
    return render(request, "dashboard/ai_insights.html", {
        "page_id": "ai",
        "tasks_24h": total_24h,
        "success_rate": round(success_24h / total_24h * 100) if total_24h > 0 else 0,
        "cost_24h": "{:.2f}".format(sum(float(t.cost_usd) for t in tasks_24h_qs)),
        "avg_duration": "{:.1f}".format(sum(t.duration_seconds for t in tasks_24h_qs) / total_24h if total_24h > 0 else 0),
        "latest_briefing": AgentTask.objects.filter(agent__in=["strategy_advisor", "weekly_reviewer"], success=True).first(),
        "recent_tasks": AgentTask.objects.order_by("-created_at")[:20],
    })


@login_required
def ai_tasks_list(request):
    from ai_agents.models import AgentTask
    return render(request, "dashboard/ai_tasks_list.html", {"page_id": "ai_tasks", "tasks": AgentTask.objects.order_by("-created_at")[:200]})
'''))

    # ================================================================
    # 2. FIX CONFIG URLS — logout POST support
    # ================================================================

    created.append(create_file("config/urls.py", '''"""Sauron Vision — Root URL Configuration."""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
    path("", include("dashboard.urls")),
]
'''))

    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║   🟢  SAURON VISION — Patch v2 Applied ({len(created)} files)         ║
╚══════════════════════════════════════════════════════════════════╝

  1. Globe now rotates inside static eye structure ✓
  2. Logout works via POST (Django 5+ compatible)  ✓
  3. Eye favicon + OG social sharing meta tags     ✓
  4. Dashboard: 21 KPI metrics + sessions + feeds  ✓

  Run: python manage.py collectstatic --no-input
  Then refresh your browser. 🟢
""")

if __name__ == "__main__":
    generate()
