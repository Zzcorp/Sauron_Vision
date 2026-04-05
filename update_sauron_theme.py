#!/usr/bin/env python3
"""
SAURON VISION — Frontend Theme Update
Green color scheme + Globe-Eye background + Login animations
Run inside your sauron_vision/ project directory.
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
    # BASE TEMPLATE — Green theme + Globe-Eye SVG background
    # ================================================================

    created.append(create_file("templates/base.html", r'''{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Sauron Vision{% endblock %}</title>
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
            background: var(--bg-void);
            color: var(--text-primary);
            font-family: var(--font-body);
            font-size: 15px;
            font-weight: 400;
            line-height: 1.6;
            min-height: 100vh;
            overflow-x: hidden;
        }

        /* ── Globe-Eye Background ─────────────────────── */
        .globe-eye-bg {
            position: fixed;
            top: 50%; left: 50%;
            transform: translate(-50%, -50%);
            width: 90vmin; height: 90vmin;
            z-index: 0;
            pointer-events: none;
            opacity: 0.04;
        }

        /* ── Particle Canvas ──────────────────────────── */
        #particles-canvas {
            position: fixed;
            top: 0; left: 0;
            width: 100%; height: 100%;
            z-index: 0;
            pointer-events: none;
        }

        /* ── Layout ───────────────────────────────────── */
        .app-layout {
            display: flex;
            min-height: 100vh;
            position: relative;
            z-index: 1;
        }

        /* ── Sidebar ──────────────────────────────────── */
        .sidebar {
            width: var(--sidebar-width);
            background: linear-gradient(180deg, var(--bg-primary) 0%, var(--bg-void) 100%);
            border-right: 1px solid var(--border);
            position: fixed;
            top: 0; left: 0; bottom: 0;
            display: flex;
            flex-direction: column;
            z-index: 100;
            overflow-y: auto;
        }

        .sidebar-brand {
            padding: 20px 20px 16px;
            border-bottom: 1px solid var(--border);
        }

        .sidebar-brand h1 {
            font-family: var(--font-display);
            font-size: 16px;
            font-weight: 700;
            letter-spacing: 4px;
            color: var(--accent);
            text-shadow: 0 0 20px var(--accent-glow);
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .sidebar-brand h1 .eye {
            width: 28px; height: 28px;
            background: radial-gradient(circle, var(--accent) 30%, transparent 70%);
            border-radius: 50%;
            animation: eyePulse 3s ease-in-out infinite;
            flex-shrink: 0;
        }

        @keyframes eyePulse {
            0%, 100% { box-shadow: 0 0 10px var(--accent), 0 0 30px var(--accent-glow); }
            50% { box-shadow: 0 0 20px var(--accent), 0 0 60px var(--accent-glow); }
        }

        .sidebar-brand .subtitle {
            font-family: var(--font-mono);
            font-size: 10px;
            color: var(--text-muted);
            letter-spacing: 2px;
            margin-top: 4px;
        }

        .sidebar-nav { padding: 12px 0; flex: 1; }

        .nav-section {
            padding: 8px 20px 4px;
            font-family: var(--font-mono);
            font-size: 9px;
            letter-spacing: 3px;
            color: var(--text-muted);
            text-transform: uppercase;
        }

        .nav-link {
            display: flex; align-items: center; gap: 12px;
            padding: 10px 20px;
            color: var(--text-secondary);
            text-decoration: none;
            font-family: var(--font-heading);
            font-size: 14px; font-weight: 500;
            letter-spacing: 0.5px;
            transition: all 0.2s;
            border-left: 3px solid transparent;
        }

        .nav-link:hover {
            color: var(--text-primary);
            background: var(--accent-glow);
            border-left-color: var(--accent-dim);
        }

        .nav-link.active {
            color: var(--accent);
            background: var(--accent-glow);
            border-left-color: var(--accent);
        }

        .nav-link .icon { font-size: 16px; width: 20px; text-align: center; }

        .sidebar-footer {
            padding: 16px 20px;
            border-top: 1px solid var(--border);
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--text-muted);
        }

        .sidebar-footer a { color: var(--text-secondary); text-decoration: none; }
        .sidebar-footer a:hover { color: var(--accent); }

        /* ── Main Content ─────────────────────────────── */
        .main-content {
            margin-left: var(--sidebar-width);
            flex: 1;
            min-height: 100vh;
        }

        .topbar {
            height: var(--topbar-height);
            background: rgba(6, 14, 10, 0.85);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--border);
            display: flex; align-items: center; justify-content: space-between;
            padding: 0 28px;
            position: sticky; top: 0; z-index: 50;
        }

        .topbar-title {
            font-family: var(--font-heading);
            font-size: 18px; font-weight: 600;
            letter-spacing: 1px;
        }

        .topbar-right {
            display: flex; align-items: center; gap: 16px;
            font-family: var(--font-mono);
            font-size: 12px; color: var(--text-secondary);
        }

        .status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
        .status-dot.online { background: var(--accent); box-shadow: 0 0 8px var(--accent); }
        .status-dot.offline { background: var(--danger); }

        .page-content { padding: 28px; }

        /* ── Cards ────────────────────────────────────── */
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            padding: 20px;
            box-shadow: var(--shadow-card);
            transition: all 0.25s;
        }

        .card:hover { border-color: var(--border-glow); box-shadow: var(--shadow-glow); }

        .card-header {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 16px; padding-bottom: 12px;
            border-bottom: 1px solid var(--border);
        }

        .card-title {
            font-family: var(--font-heading);
            font-size: 15px; font-weight: 600;
            letter-spacing: 1px; color: var(--text-primary);
            text-transform: uppercase;
        }

        /* ── Grid ─────────────────────────────────────── */
        .grid { display: grid; gap: 20px; }
        .grid-2 { grid-template-columns: repeat(2, 1fr); }
        .grid-3 { grid-template-columns: repeat(3, 1fr); }
        .grid-4 { grid-template-columns: repeat(4, 1fr); }
        .grid-sidebar { grid-template-columns: 2fr 1fr; }

        @media (max-width: 1200px) { .grid-4, .grid-3 { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 768px) {
            .grid-2, .grid-3, .grid-4, .grid-sidebar { grid-template-columns: 1fr; }
            .sidebar { display: none; }
            .main-content { margin-left: 0; }
        }

        /* ── Stat Boxes ───────────────────────────────── */
        .stat-box {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            padding: 18px 20px;
            transition: all 0.25s;
        }
        .stat-box:hover { border-color: var(--border-glow); transform: translateY(-2px); }

        .stat-label {
            font-family: var(--font-mono); font-size: 10px;
            letter-spacing: 2px; color: var(--text-muted);
            text-transform: uppercase; margin-bottom: 6px;
        }
        .stat-value {
            font-family: var(--font-display); font-size: 24px;
            font-weight: 700; color: var(--text-primary);
        }
        .stat-change { font-family: var(--font-mono); font-size: 12px; margin-top: 4px; }
        .stat-change.positive { color: var(--success); }
        .stat-change.negative { color: var(--accent-red); }

        /* ── Tables ───────────────────────────────────── */
        .table-wrapper { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; font-family: var(--font-mono); font-size: 13px; }
        thead th {
            text-align: left; padding: 10px 14px; font-size: 10px;
            letter-spacing: 2px; color: var(--text-muted);
            text-transform: uppercase; border-bottom: 1px solid var(--border); white-space: nowrap;
        }
        tbody td { padding: 10px 14px; border-bottom: 1px solid rgba(19, 48, 32, 0.5); white-space: nowrap; }
        tbody tr { transition: background 0.15s; }
        tbody tr:hover { background: var(--bg-card-hover); }

        /* ── Badges ───────────────────────────────────── */
        .badge {
            display: inline-block; padding: 3px 10px; border-radius: 20px;
            font-family: var(--font-mono); font-size: 10px;
            letter-spacing: 1px; text-transform: uppercase; font-weight: 600;
        }
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

        @keyframes badgePulse { 0%,100% { opacity:1; } 50% { opacity:0.6; } }

        /* ── Buttons ──────────────────────────────────── */
        .btn {
            display: inline-flex; align-items: center; gap: 8px;
            padding: 8px 18px; border: 1px solid var(--border);
            border-radius: var(--radius); background: var(--bg-card);
            color: var(--text-primary); font-family: var(--font-heading);
            font-size: 13px; font-weight: 600; letter-spacing: 1px;
            cursor: pointer; text-decoration: none; transition: all 0.2s;
        }
        .btn:hover { background: var(--bg-card-hover); border-color: var(--accent-dim); }
        .btn-primary { background: var(--accent-dim); border-color: var(--accent); color: #fff; }
        .btn-primary:hover { background: var(--accent); color: #000; box-shadow: 0 0 20px var(--accent-glow); }
        .btn-sm { padding: 5px 12px; font-size: 11px; }

        /* ── Score Bars ───────────────────────────────── */
        .score-bar { height: 6px; background: var(--bg-void); border-radius: 3px; overflow: hidden; margin-top: 6px; }
        .score-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s ease; }

        /* ── Signal Items ─────────────────────────────── */
        .signal-item {
            padding: 14px 16px; border: 1px solid var(--border);
            border-radius: var(--radius); margin-bottom: 10px;
            transition: all 0.2s; cursor: pointer;
        }
        .signal-item:hover { border-color: var(--border-glow); background: var(--bg-card-hover); }
        .signal-item .signal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
        .signal-item .signal-symbol { font-family: var(--font-display); font-size: 14px; font-weight: 600; }
        .signal-item .signal-desc { font-size: 13px; color: var(--text-secondary); }

        /* ── Empty States ─────────────────────────────── */
        .empty-state { text-align: center; padding: 60px 20px; color: var(--text-muted); }
        .empty-state .empty-icon { font-size: 48px; margin-bottom: 16px; opacity: 0.3; }
        .empty-state p { font-family: var(--font-mono); font-size: 13px; letter-spacing: 1px; }

        /* ── Animations ───────────────────────────────── */
        .fade-in { animation: fadeIn 0.4s ease forwards; }
        .fade-in-up { opacity: 0; transform: translateY(12px); animation: fadeInUp 0.5s ease forwards; }
        @keyframes fadeIn { from { opacity:0; } to { opacity:1; } }
        @keyframes fadeInUp { from { opacity:0; transform:translateY(12px); } to { opacity:1; transform:translateY(0); } }
        .delay-1 { animation-delay: 0.05s; }
        .delay-2 { animation-delay: 0.1s; }
        .delay-3 { animation-delay: 0.15s; }
        .delay-4 { animation-delay: 0.2s; }
        .delay-5 { animation-delay: 0.25s; }

        /* ── Scrollbar ────────────────────────────────── */
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: var(--bg-void); }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--accent-dim); }

        /* ── Detail Pages ─────────────────────────────── */
        .detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; }
        .detail-header h2 { font-family: var(--font-display); font-size: 20px; font-weight: 700; letter-spacing: 2px; }
        .detail-meta { display: flex; gap: 20px; margin-top: 8px; font-family: var(--font-mono); font-size: 12px; color: var(--text-secondary); }
        .kv-list { list-style: none; }
        .kv-list li { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid rgba(19,48,32,0.4); font-size: 13px; }
        .kv-list li .label { color: var(--text-secondary); font-family: var(--font-mono); font-size: 11px; letter-spacing: 1px; }
        .kv-list li .value { font-family: var(--font-mono); color: var(--text-primary); }
    </style>
    {% block extra_css %}{% endblock %}
</head>
<body>

<!-- Globe-Eye SVG Background -->
<svg class="globe-eye-bg" viewBox="0 0 800 800" xmlns="http://www.w3.org/2000/svg">
    <!-- Outer eye shape -->
    <ellipse cx="400" cy="400" rx="390" ry="240" fill="none" stroke="#00e868" stroke-width="2"/>
    <ellipse cx="400" cy="400" rx="360" ry="210" fill="none" stroke="#00e868" stroke-width="0.5" opacity="0.5"/>
    <!-- Iris -->
    <circle cx="400" cy="400" r="160" fill="none" stroke="#00e868" stroke-width="1.5"/>
    <circle cx="400" cy="400" r="140" fill="none" stroke="#00e868" stroke-width="0.5" opacity="0.4"/>
    <!-- Pupil -->
    <circle cx="400" cy="400" r="60" fill="none" stroke="#00e868" stroke-width="2"/>
    <circle cx="400" cy="400" r="20" fill="#00e868" opacity="0.15"/>
    <!-- Globe meridians inside iris -->
    <ellipse cx="400" cy="400" rx="140" ry="140" fill="none" stroke="#00e868" stroke-width="0.4" opacity="0.3"/>
    <ellipse cx="400" cy="400" rx="50" ry="140" fill="none" stroke="#00e868" stroke-width="0.5" opacity="0.4"/>
    <ellipse cx="400" cy="400" rx="100" ry="140" fill="none" stroke="#00e868" stroke-width="0.4" opacity="0.3"/>
    <ellipse cx="400" cy="400" rx="140" ry="50" fill="none" stroke="#00e868" stroke-width="0.4" opacity="0.3" transform="rotate(0 400 400)"/>
    <!-- Globe latitude lines -->
    <line x1="260" y1="340" x2="540" y2="340" stroke="#00e868" stroke-width="0.4" opacity="0.25"/>
    <line x1="260" y1="400" x2="540" y2="400" stroke="#00e868" stroke-width="0.5" opacity="0.3"/>
    <line x1="260" y1="460" x2="540" y2="460" stroke="#00e868" stroke-width="0.4" opacity="0.25"/>
    <!-- Globe tilted meridian -->
    <ellipse cx="400" cy="400" rx="30" ry="140" fill="none" stroke="#00e868" stroke-width="0.4" opacity="0.25" transform="rotate(30 400 400)"/>
    <ellipse cx="400" cy="400" rx="120" ry="140" fill="none" stroke="#00e868" stroke-width="0.3" opacity="0.2" transform="rotate(-15 400 400)"/>
    <!-- Eyelid curves -->
    <path d="M 10,400 Q 200,100 400,160 Q 600,100 790,400" fill="none" stroke="#00e868" stroke-width="1" opacity="0.6"/>
    <path d="M 10,400 Q 200,700 400,640 Q 600,700 790,400" fill="none" stroke="#00e868" stroke-width="1" opacity="0.6"/>
    <!-- Corner details -->
    <line x1="10" y1="400" x2="80" y2="400" stroke="#00e868" stroke-width="0.5" opacity="0.3"/>
    <line x1="720" y1="400" x2="790" y2="400" stroke="#00e868" stroke-width="0.5" opacity="0.3"/>
</svg>

<canvas id="particles-canvas"></canvas>

{% block layout %}
<div class="app-layout">
    <aside class="sidebar">
        <div class="sidebar-brand">
            <h1><span class="eye"></span>SAURON</h1>
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
            <a href="{% url 'admin:index' %}">⚙ Admin</a> &nbsp;·&nbsp;
            <a href="{% url 'logout' %}">⏻ Logout</a>
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
            this.x = Math.random() * canvas.width;
            this.y = Math.random() * canvas.height;
            this.vx = (Math.random() - 0.5) * 0.3;
            this.vy = (Math.random() - 0.5) * 0.3;
            this.size = Math.random() * 1.5 + 0.5;
            this.alpha = Math.random() * 0.25 + 0.05;
        }
        update() {
            this.x += this.vx; this.y += this.vy;
            if (this.x < 0 || this.x > canvas.width || this.y < 0 || this.y > canvas.height) this.reset();
        }
        draw() {
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(0, 232, 104, ${this.alpha})`;
            ctx.fill();
        }
    }

    for (let i = 0; i < 80; i++) particles.push(new Particle());

    function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => { p.update(); p.draw(); });
        for (let i = 0; i < particles.length; i++) {
            for (let j = i + 1; j < particles.length; j++) {
                const dx = particles[i].x - particles[j].x;
                const dy = particles[i].y - particles[j].y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 150) {
                    ctx.beginPath();
                    ctx.moveTo(particles[i].x, particles[i].y);
                    ctx.lineTo(particles[j].x, particles[j].y);
                    ctx.strokeStyle = `rgba(0, 232, 104, ${0.04 * (1 - dist / 150)})`;
                    ctx.stroke();
                }
            }
        }
        requestAnimationFrame(animate);
    }
    animate();

    function updateClock() {
        const el = document.getElementById('clock');
        if (el) { const now = new Date(); el.textContent = now.toUTCString().slice(17, 25) + ' UTC'; }
    }
    setInterval(updateClock, 1000);
    updateClock();
})();
</script>
{% block extra_js %}{% endblock %}
</body>
</html>
'''))

    # ================================================================
    # LOGIN PAGE — Green, slow RTL scanner, moving grid
    # ================================================================

    created.append(create_file("templates/registration/login.html", r'''{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sauron Vision — Access</title>
    <link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700;900&family=Rajdhani:wght@300;400;600&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            background: #030806;
            color: #c8e8d8;
            font-family: 'Rajdhani', sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }

        /* ── Moving Grid Background ──────────────── */
        .grid-bg {
            position: fixed;
            top: -50%; left: -50%;
            width: 200%; height: 200%;
            z-index: 0;
            background-image:
                linear-gradient(rgba(0, 232, 104, 0.04) 1px, transparent 1px),
                linear-gradient(90deg, rgba(0, 232, 104, 0.04) 1px, transparent 1px);
            background-size: 60px 60px;
            animation: gridMove 25s linear infinite;
        }

        @keyframes gridMove {
            0% { transform: translate(0, 0) rotate(0deg); }
            100% { transform: translate(60px, 60px) rotate(0.5deg); }
        }

        /* ── Globe-Eye Background (large) ────────── */
        .globe-eye-login {
            position: fixed;
            top: 50%; left: 50%;
            transform: translate(-50%, -50%);
            width: 110vmin; height: 110vmin;
            z-index: 1;
            pointer-events: none;
            opacity: 0.035;
            animation: eyeRotate 60s linear infinite;
        }

        @keyframes eyeRotate {
            0% { transform: translate(-50%, -50%) rotate(0deg); }
            100% { transform: translate(-50%, -50%) rotate(360deg); }
        }

        /* ── Particle Canvas ─────────────────────── */
        canvas { position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 2; }

        /* ── Scanner Line (green, slow, right to left) ── */
        .scan-line {
            position: fixed;
            top: 0; left: 0; bottom: 0;
            width: 3px;
            z-index: 3;
            animation: scanRTL 8s linear infinite;
        }

        .scan-line::before {
            content: '';
            position: absolute;
            top: 0; left: -40px; bottom: 0;
            width: 80px;
            background: linear-gradient(90deg, transparent, rgba(0, 232, 104, 0.06), transparent);
        }

        .scan-line::after {
            content: '';
            position: absolute;
            top: 0; left: 0; bottom: 0;
            width: 3px;
            background: linear-gradient(180deg, transparent 10%, rgba(0, 232, 104, 0.4) 50%, transparent 90%);
            box-shadow: 0 0 15px rgba(0, 232, 104, 0.3), 0 0 40px rgba(0, 232, 104, 0.1);
        }

        @keyframes scanRTL {
            0% { left: 100%; }
            100% { left: -80px; }
        }

        /* ── Login Container ─────────────────────── */
        .login-container {
            position: relative;
            z-index: 10;
            width: 380px;
            animation: fadeInUp 0.8s ease;
        }

        @keyframes fadeInUp {
            from { opacity: 0; transform: translateY(40px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .login-eye {
            width: 64px; height: 64px;
            margin: 0 auto 24px;
            position: relative;
        }

        .login-eye .eye-outer {
            width: 64px; height: 64px;
            border-radius: 50%;
            border: 2px solid rgba(0, 232, 104, 0.4);
            display: flex; align-items: center; justify-content: center;
            animation: eyeRingPulse 3s ease-in-out infinite;
        }

        .login-eye .eye-inner {
            width: 28px; height: 28px;
            background: radial-gradient(circle, #00e868 30%, rgba(0,232,104,0.2) 70%, transparent 100%);
            border-radius: 50%;
            box-shadow: 0 0 20px rgba(0,232,104,0.5), 0 0 60px rgba(0,232,104,0.15);
        }

        @keyframes eyeRingPulse {
            0%, 100% { border-color: rgba(0, 232, 104, 0.3); box-shadow: 0 0 20px rgba(0,232,104,0.1); }
            50% { border-color: rgba(0, 232, 104, 0.6); box-shadow: 0 0 40px rgba(0,232,104,0.2); }
        }

        .login-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 24px; font-weight: 900;
            letter-spacing: 6px;
            color: #00e868;
            text-align: center;
            margin-bottom: 4px;
            text-shadow: 0 0 30px rgba(0,232,104,0.2);
        }

        .login-subtitle {
            font-family: 'Share Tech Mono', monospace;
            font-size: 11px; letter-spacing: 3px;
            color: #2a5038;
            text-align: center;
            margin-bottom: 32px;
        }

        .login-card {
            background: rgba(10, 26, 20, 0.9);
            border: 1px solid #133020;
            border-radius: 12px;
            padding: 32px;
            backdrop-filter: blur(20px);
            box-shadow: 0 4px 40px rgba(0,0,0,0.5), 0 0 60px rgba(0,232,104,0.03);
        }

        .form-group { margin-bottom: 20px; }

        .form-group label {
            display: block;
            font-family: 'Share Tech Mono', monospace;
            font-size: 10px; letter-spacing: 3px;
            color: #5a8a6a;
            text-transform: uppercase;
            margin-bottom: 8px;
        }

        .form-group input {
            width: 100%;
            padding: 12px 16px;
            background: #060e0a;
            border: 1px solid #133020;
            border-radius: 6px;
            color: #c8e8d8;
            font-family: 'Share Tech Mono', monospace;
            font-size: 14px;
            outline: none;
            transition: all 0.2s;
        }

        .form-group input:focus {
            border-color: #00e868;
            box-shadow: 0 0 15px rgba(0,232,104,0.1);
        }

        .btn-login {
            width: 100%; padding: 14px;
            background: linear-gradient(135deg, #0a5028, #00e868);
            border: none; border-radius: 6px;
            color: #020804;
            font-family: 'Orbitron', sans-serif;
            font-size: 13px; font-weight: 700;
            letter-spacing: 4px;
            cursor: pointer;
            transition: all 0.3s;
            text-transform: uppercase;
        }

        .btn-login:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(0,232,104,0.25);
        }

        .errors {
            background: rgba(232,48,48,0.08);
            border: 1px solid rgba(232,48,48,0.25);
            border-radius: 6px; padding: 12px; margin-bottom: 20px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 12px; color: #e83030;
        }
    </style>
</head>
<body>

    <!-- Moving Grid -->
    <div class="grid-bg"></div>

    <!-- Globe-Eye (large, behind everything) -->
    <svg class="globe-eye-login" viewBox="0 0 800 800" xmlns="http://www.w3.org/2000/svg">
        <ellipse cx="400" cy="400" rx="390" ry="240" fill="none" stroke="#00e868" stroke-width="2"/>
        <ellipse cx="400" cy="400" rx="360" ry="210" fill="none" stroke="#00e868" stroke-width="0.8" opacity="0.4"/>
        <circle cx="400" cy="400" r="160" fill="none" stroke="#00e868" stroke-width="1.5"/>
        <circle cx="400" cy="400" r="140" fill="none" stroke="#00e868" stroke-width="0.5" opacity="0.4"/>
        <circle cx="400" cy="400" r="60" fill="none" stroke="#00e868" stroke-width="2"/>
        <circle cx="400" cy="400" r="20" fill="#00e868" opacity="0.12"/>
        <ellipse cx="400" cy="400" rx="50" ry="140" fill="none" stroke="#00e868" stroke-width="0.5" opacity="0.35"/>
        <ellipse cx="400" cy="400" rx="100" ry="140" fill="none" stroke="#00e868" stroke-width="0.4" opacity="0.25"/>
        <ellipse cx="400" cy="400" rx="140" ry="50" fill="none" stroke="#00e868" stroke-width="0.4" opacity="0.25"/>
        <line x1="260" y1="340" x2="540" y2="340" stroke="#00e868" stroke-width="0.4" opacity="0.2"/>
        <line x1="260" y1="400" x2="540" y2="400" stroke="#00e868" stroke-width="0.5" opacity="0.3"/>
        <line x1="260" y1="460" x2="540" y2="460" stroke="#00e868" stroke-width="0.4" opacity="0.2"/>
        <ellipse cx="400" cy="400" rx="30" ry="140" fill="none" stroke="#00e868" stroke-width="0.4" opacity="0.2" transform="rotate(25 400 400)"/>
        <ellipse cx="400" cy="400" rx="120" ry="140" fill="none" stroke="#00e868" stroke-width="0.3" opacity="0.15" transform="rotate(-20 400 400)"/>
        <path d="M 10,400 Q 200,100 400,160 Q 600,100 790,400" fill="none" stroke="#00e868" stroke-width="1.2" opacity="0.5"/>
        <path d="M 10,400 Q 200,700 400,640 Q 600,700 790,400" fill="none" stroke="#00e868" stroke-width="1.2" opacity="0.5"/>
    </svg>

    <!-- Particles -->
    <canvas id="particles-canvas"></canvas>

    <!-- Green scanner (slow, right-to-left) -->
    <div class="scan-line"></div>

    <div class="login-container">
        <div class="login-eye">
            <div class="eye-outer"><div class="eye-inner"></div></div>
        </div>
        <h1 class="login-title">SAURON VISION</h1>
        <p class="login-subtitle">AUTHENTICATE TO PROCEED</p>

        <div class="login-card">
            {% if form.errors %}
            <div class="errors">⚠ AUTHENTICATION FAILED — INVALID CREDENTIALS</div>
            {% endif %}

            <form method="post" action="{% url 'login' %}">
                {% csrf_token %}
                <div class="form-group">
                    <label for="id_username">Operator ID</label>
                    <input type="text" name="username" id="id_username" autofocus autocomplete="username" required>
                </div>
                <div class="form-group">
                    <label for="id_password">Access Key</label>
                    <input type="password" name="password" id="id_password" autocomplete="current-password" required>
                </div>
                <input type="hidden" name="next" value="{{ next }}">
                <button type="submit" class="btn-login">Initialize Session</button>
            </form>
        </div>
    </div>

    <script>
    const canvas = document.getElementById('particles-canvas');
    const ctx = canvas.getContext('2d');
    let particles = [];
    function resize() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; }
    resize(); window.addEventListener('resize', resize);
    class P {
        constructor() { this.reset(); }
        reset() {
            this.x = Math.random() * canvas.width;
            this.y = Math.random() * canvas.height;
            this.vx = (Math.random() - 0.5) * 0.35;
            this.vy = (Math.random() - 0.5) * 0.35;
            this.s = Math.random() * 1.5 + 0.3;
            this.a = Math.random() * 0.2 + 0.04;
        }
        update() { this.x += this.vx; this.y += this.vy; if (this.x < 0 || this.x > canvas.width || this.y < 0 || this.y > canvas.height) this.reset(); }
        draw() { ctx.beginPath(); ctx.arc(this.x, this.y, this.s, 0, Math.PI * 2); ctx.fillStyle = `rgba(0,232,104,${this.a})`; ctx.fill(); }
    }
    for (let i = 0; i < 60; i++) particles.push(new P());
    function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => { p.update(); p.draw(); });
        for (let i = 0; i < particles.length; i++)
            for (let j = i + 1; j < particles.length; j++) {
                const d = Math.hypot(particles[i].x - particles[j].x, particles[i].y - particles[j].y);
                if (d < 120) { ctx.beginPath(); ctx.moveTo(particles[i].x, particles[i].y); ctx.lineTo(particles[j].x, particles[j].y); ctx.strokeStyle = `rgba(0,232,104,${0.04*(1-d/120)})`; ctx.stroke(); }
            }
        requestAnimationFrame(animate);
    }
    animate();
    </script>
</body>
</html>
'''))

    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║   🟢  SAURON VISION — Theme Updated ({len(created)} files)            ║
╚══════════════════════════════════════════════════════════════════╝

  Updated:
    templates/base.html              → Green theme + Globe-Eye SVG
    templates/registration/login.html → Green scanner RTL + moving grid

  Refresh your browser to see changes. 🟢
""")


if __name__ == "__main__":
    generate()
