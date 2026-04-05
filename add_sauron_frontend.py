#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║                     SAURON VISION                                ║
║              Frontend Pages Generator v1.0                       ║
║                                                                  ║
║   Run inside your sauron_vision/ project directory:              ║
║   python add_sauron_frontend.py                                  ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os
import sys

def create_file(path, content=""):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def generate():
    created = []

    # ================================================================
    # BASE TEMPLATE — Dark hacker aesthetic with particle background
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
            --bg-void: #050508;
            --bg-primary: #0a0a10;
            --bg-secondary: #0f0f18;
            --bg-card: #12121e;
            --bg-card-hover: #181828;
            --border: #1e1e35;
            --border-glow: #2a1a1a;
            --text-primary: #d0d0e0;
            --text-secondary: #6a6a8a;
            --text-muted: #3a3a55;
            --accent-red: #e03030;
            --accent-red-dim: #801818;
            --accent-red-glow: rgba(224, 48, 48, 0.15);
            --accent-green: #20d870;
            --accent-green-dim: #105830;
            --accent-gold: #e8a020;
            --accent-blue: #3080e8;
            --accent-purple: #8040d0;
            --danger: #d03030;
            --success: #20c060;
            --warning: #d89020;
            --radius: 6px;
            --radius-lg: 12px;
            --shadow-card: 0 2px 20px rgba(0,0,0,0.4);
            --shadow-glow: 0 0 30px rgba(224, 48, 48, 0.08);
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

        /* ── Particle Background ──────────────────────── */
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
            color: var(--accent-red);
            text-shadow: 0 0 20px var(--accent-red-glow);
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .sidebar-brand h1 .eye {
            width: 28px; height: 28px;
            background: radial-gradient(circle, var(--accent-red) 30%, transparent 70%);
            border-radius: 50%;
            animation: eyePulse 3s ease-in-out infinite;
            flex-shrink: 0;
        }

        @keyframes eyePulse {
            0%, 100% { box-shadow: 0 0 10px var(--accent-red), 0 0 30px var(--accent-red-glow); }
            50% { box-shadow: 0 0 20px var(--accent-red), 0 0 60px var(--accent-red-glow); }
        }

        .sidebar-brand .subtitle {
            font-family: var(--font-mono);
            font-size: 10px;
            color: var(--text-muted);
            letter-spacing: 2px;
            margin-top: 4px;
        }

        .sidebar-nav {
            padding: 12px 0;
            flex: 1;
        }

        .nav-section {
            padding: 8px 20px 4px;
            font-family: var(--font-mono);
            font-size: 9px;
            letter-spacing: 3px;
            color: var(--text-muted);
            text-transform: uppercase;
        }

        .nav-link {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 20px;
            color: var(--text-secondary);
            text-decoration: none;
            font-family: var(--font-heading);
            font-size: 14px;
            font-weight: 500;
            letter-spacing: 0.5px;
            transition: all 0.2s;
            border-left: 3px solid transparent;
        }

        .nav-link:hover {
            color: var(--text-primary);
            background: var(--accent-red-glow);
            border-left-color: var(--accent-red-dim);
        }

        .nav-link.active {
            color: var(--accent-red);
            background: var(--accent-red-glow);
            border-left-color: var(--accent-red);
        }

        .nav-link .icon { font-size: 16px; width: 20px; text-align: center; }

        .sidebar-footer {
            padding: 16px 20px;
            border-top: 1px solid var(--border);
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--text-muted);
        }

        .sidebar-footer a {
            color: var(--text-secondary);
            text-decoration: none;
        }

        .sidebar-footer a:hover { color: var(--accent-red); }

        /* ── Main Content ─────────────────────────────── */
        .main-content {
            margin-left: var(--sidebar-width);
            flex: 1;
            min-height: 100vh;
        }

        .topbar {
            height: var(--topbar-height);
            background: rgba(10, 10, 16, 0.8);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 28px;
            position: sticky;
            top: 0;
            z-index: 50;
        }

        .topbar-title {
            font-family: var(--font-heading);
            font-size: 18px;
            font-weight: 600;
            letter-spacing: 1px;
        }

        .topbar-right {
            display: flex;
            align-items: center;
            gap: 16px;
            font-family: var(--font-mono);
            font-size: 12px;
            color: var(--text-secondary);
        }

        .status-dot {
            width: 8px; height: 8px;
            border-radius: 50%;
            display: inline-block;
        }

        .status-dot.online { background: var(--accent-green); box-shadow: 0 0 8px var(--accent-green); }
        .status-dot.offline { background: var(--danger); }

        .page-content {
            padding: 28px;
        }

        /* ── Cards ────────────────────────────────────── */
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            padding: 20px;
            box-shadow: var(--shadow-card);
            transition: all 0.25s;
        }

        .card:hover {
            border-color: var(--border-glow);
            box-shadow: var(--shadow-glow);
        }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid var(--border);
        }

        .card-title {
            font-family: var(--font-heading);
            font-size: 15px;
            font-weight: 600;
            letter-spacing: 1px;
            color: var(--text-primary);
            text-transform: uppercase;
        }

        /* ── Grid ─────────────────────────────────────── */
        .grid { display: grid; gap: 20px; }
        .grid-2 { grid-template-columns: repeat(2, 1fr); }
        .grid-3 { grid-template-columns: repeat(3, 1fr); }
        .grid-4 { grid-template-columns: repeat(4, 1fr); }
        .grid-sidebar { grid-template-columns: 2fr 1fr; }

        @media (max-width: 1200px) {
            .grid-4 { grid-template-columns: repeat(2, 1fr); }
            .grid-3 { grid-template-columns: repeat(2, 1fr); }
        }

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

        .stat-box:hover {
            border-color: var(--border-glow);
            transform: translateY(-2px);
        }

        .stat-label {
            font-family: var(--font-mono);
            font-size: 10px;
            letter-spacing: 2px;
            color: var(--text-muted);
            text-transform: uppercase;
            margin-bottom: 6px;
        }

        .stat-value {
            font-family: var(--font-display);
            font-size: 24px;
            font-weight: 700;
            color: var(--text-primary);
        }

        .stat-change {
            font-family: var(--font-mono);
            font-size: 12px;
            margin-top: 4px;
        }

        .stat-change.positive { color: var(--accent-green); }
        .stat-change.negative { color: var(--accent-red); }

        /* ── Tables ───────────────────────────────────── */
        .table-wrapper { overflow-x: auto; }

        table {
            width: 100%;
            border-collapse: collapse;
            font-family: var(--font-mono);
            font-size: 13px;
        }

        thead th {
            text-align: left;
            padding: 10px 14px;
            font-size: 10px;
            letter-spacing: 2px;
            color: var(--text-muted);
            text-transform: uppercase;
            border-bottom: 1px solid var(--border);
            white-space: nowrap;
        }

        tbody td {
            padding: 10px 14px;
            border-bottom: 1px solid rgba(30, 30, 53, 0.5);
            white-space: nowrap;
        }

        tbody tr { transition: background 0.15s; }
        tbody tr:hover { background: var(--bg-card-hover); }

        /* ── Badges & Pills ───────────────────────────── */
        .badge {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 20px;
            font-family: var(--font-mono);
            font-size: 10px;
            letter-spacing: 1px;
            text-transform: uppercase;
            font-weight: 600;
        }

        .badge-bullish { background: var(--accent-green-dim); color: var(--accent-green); }
        .badge-bearish { background: var(--accent-red-dim); color: var(--accent-red); }
        .badge-neutral { background: rgba(100,100,140,0.2); color: var(--text-secondary); }
        .badge-critical { background: var(--accent-red-dim); color: var(--accent-red); animation: badgePulse 2s infinite; }
        .badge-high { background: rgba(216,144,32,0.2); color: var(--accent-gold); }
        .badge-medium { background: rgba(48,128,232,0.15); color: var(--accent-blue); }
        .badge-low { background: rgba(100,100,140,0.15); color: var(--text-secondary); }
        .badge-active { background: var(--accent-green-dim); color: var(--accent-green); }
        .badge-proposed { background: rgba(128,64,208,0.2); color: var(--accent-purple); }
        .badge-stock { background: rgba(48,128,232,0.15); color: var(--accent-blue); }
        .badge-forex { background: rgba(216,144,32,0.15); color: var(--accent-gold); }
        .badge-commodity { background: rgba(224,48,48,0.15); color: var(--accent-red); }

        @keyframes badgePulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }

        /* ── Buttons ──────────────────────────────────── */
        .btn {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 18px;
            border: 1px solid var(--border);
            border-radius: var(--radius);
            background: var(--bg-card);
            color: var(--text-primary);
            font-family: var(--font-heading);
            font-size: 13px;
            font-weight: 600;
            letter-spacing: 1px;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.2s;
        }

        .btn:hover {
            background: var(--bg-card-hover);
            border-color: var(--accent-red-dim);
        }

        .btn-primary {
            background: var(--accent-red-dim);
            border-color: var(--accent-red);
            color: #fff;
        }

        .btn-primary:hover {
            background: var(--accent-red);
            box-shadow: 0 0 20px var(--accent-red-glow);
        }

        .btn-sm { padding: 5px 12px; font-size: 11px; }

        /* ── Score Bars ───────────────────────────────── */
        .score-bar {
            height: 6px;
            background: var(--bg-void);
            border-radius: 3px;
            overflow: hidden;
            margin-top: 6px;
        }

        .score-bar-fill {
            height: 100%;
            border-radius: 3px;
            transition: width 0.5s ease;
        }

        /* ── Signal Feed Items ────────────────────────── */
        .signal-item {
            padding: 14px 16px;
            border: 1px solid var(--border);
            border-radius: var(--radius);
            margin-bottom: 10px;
            transition: all 0.2s;
            cursor: pointer;
        }

        .signal-item:hover {
            border-color: var(--border-glow);
            background: var(--bg-card-hover);
        }

        .signal-item .signal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }

        .signal-item .signal-symbol {
            font-family: var(--font-display);
            font-size: 14px;
            font-weight: 600;
        }

        .signal-item .signal-desc {
            font-size: 13px;
            color: var(--text-secondary);
        }

        /* ── Empty States ─────────────────────────────── */
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: var(--text-muted);
        }

        .empty-state .empty-icon {
            font-size: 48px;
            margin-bottom: 16px;
            opacity: 0.3;
        }

        .empty-state p {
            font-family: var(--font-mono);
            font-size: 13px;
            letter-spacing: 1px;
        }

        /* ── Page Animations ──────────────────────────── */
        .fade-in {
            animation: fadeIn 0.4s ease forwards;
        }

        .fade-in-up {
            opacity: 0;
            transform: translateY(12px);
            animation: fadeInUp 0.5s ease forwards;
        }

        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes fadeInUp {
            from { opacity: 0; transform: translateY(12px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .delay-1 { animation-delay: 0.05s; }
        .delay-2 { animation-delay: 0.1s; }
        .delay-3 { animation-delay: 0.15s; }
        .delay-4 { animation-delay: 0.2s; }
        .delay-5 { animation-delay: 0.25s; }

        /* ── Scrollbar ────────────────────────────────── */
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: var(--bg-void); }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--accent-red-dim); }

        /* ── Detail Pages ─────────────────────────────── */
        .detail-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 24px;
        }

        .detail-header h2 {
            font-family: var(--font-display);
            font-size: 20px;
            font-weight: 700;
            letter-spacing: 2px;
        }

        .detail-meta {
            display: flex;
            gap: 20px;
            margin-top: 8px;
            font-family: var(--font-mono);
            font-size: 12px;
            color: var(--text-secondary);
        }

        .kv-list { list-style: none; }
        .kv-list li {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid rgba(30,30,53,0.4);
            font-size: 13px;
        }
        .kv-list li .label { color: var(--text-secondary); font-family: var(--font-mono); font-size: 11px; letter-spacing: 1px; }
        .kv-list li .value { font-family: var(--font-mono); color: var(--text-primary); }
    </style>
    {% block extra_css %}{% endblock %}
</head>
<body>

<!-- Particle Canvas -->
<canvas id="particles-canvas"></canvas>

{% block layout %}
<div class="app-layout">
    <!-- Sidebar -->
    <aside class="sidebar">
        <div class="sidebar-brand">
            <h1><span class="eye"></span>SAURON</h1>
            <div class="subtitle">TRADING INTELLIGENCE</div>
        </div>

        <nav class="sidebar-nav">
            <div class="nav-section">Command Center</div>
            <a href="{% url 'dashboard' %}" class="nav-link {% if page_id == 'dashboard' %}active{% endif %}">
                <span class="icon">◉</span> Dashboard
            </a>

            <div class="nav-section">Markets</div>
            <a href="{% url 'instruments_list' %}" class="nav-link {% if page_id == 'instruments' %}active{% endif %}">
                <span class="icon">◈</span> Instruments
            </a>
            <a href="{% url 'market_quotes' %}" class="nav-link {% if page_id == 'quotes' %}active{% endif %}">
                <span class="icon">◆</span> Live Quotes
            </a>
            <a href="{% url 'economic_calendar' %}" class="nav-link {% if page_id == 'calendar' %}active{% endif %}">
                <span class="icon">◇</span> Economic Calendar
            </a>

            <div class="nav-section">Intelligence</div>
            <a href="{% url 'signals_list' %}" class="nav-link {% if page_id == 'signals' %}active{% endif %}">
                <span class="icon">⚡</span> Signals
            </a>
            <a href="{% url 'strategies_list' %}" class="nav-link {% if page_id == 'strategies' %}active{% endif %}">
                <span class="icon">⬡</span> Strategies
            </a>
            <a href="{% url 'news_feed' %}" class="nav-link {% if page_id == 'news' %}active{% endif %}">
                <span class="icon">▤</span> News & Sentiment
            </a>

            <div class="nav-section">Portfolio</div>
            <a href="{% url 'portfolio_overview' %}" class="nav-link {% if page_id == 'portfolio' %}active{% endif %}">
                <span class="icon">◎</span> Portfolio
            </a>
            <a href="{% url 'positions_list' %}" class="nav-link {% if page_id == 'positions' %}active{% endif %}">
                <span class="icon">▣</span> Positions
            </a>

            <div class="nav-section">AI Agents</div>
            <a href="{% url 'ai_insights' %}" class="nav-link {% if page_id == 'ai' %}active{% endif %}">
                <span class="icon">◬</span> AI Insights
            </a>
            <a href="{% url 'ai_tasks_list' %}" class="nav-link {% if page_id == 'ai_tasks' %}active{% endif %}">
                <span class="icon">▸</span> Agent Tasks
            </a>
        </nav>

        <div class="sidebar-footer">
            <a href="{% url 'admin:index' %}">⚙ Admin</a> &nbsp;·&nbsp;
            <a href="{% url 'logout' %}">⏻ Logout</a>
        </div>
    </aside>

    <!-- Main Content -->
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

<!-- Particle Animation -->
<script>
(function() {
    const canvas = document.getElementById('particles-canvas');
    const ctx = canvas.getContext('2d');
    let particles = [];

    function resize() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener('resize', resize);

    class Particle {
        constructor() { this.reset(); }
        reset() {
            this.x = Math.random() * canvas.width;
            this.y = Math.random() * canvas.height;
            this.vx = (Math.random() - 0.5) * 0.3;
            this.vy = (Math.random() - 0.5) * 0.3;
            this.size = Math.random() * 1.5 + 0.5;
            this.alpha = Math.random() * 0.3 + 0.05;
        }
        update() {
            this.x += this.vx;
            this.y += this.vy;
            if (this.x < 0 || this.x > canvas.width || this.y < 0 || this.y > canvas.height) this.reset();
        }
        draw() {
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(224, 48, 48, ${this.alpha})`;
            ctx.fill();
        }
    }

    for (let i = 0; i < 80; i++) particles.push(new Particle());

    function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => { p.update(); p.draw(); });

        // Draw connections
        for (let i = 0; i < particles.length; i++) {
            for (let j = i + 1; j < particles.length; j++) {
                const dx = particles[i].x - particles[j].x;
                const dy = particles[i].y - particles[j].y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 150) {
                    ctx.beginPath();
                    ctx.moveTo(particles[i].x, particles[i].y);
                    ctx.lineTo(particles[j].x, particles[j].y);
                    ctx.strokeStyle = `rgba(224, 48, 48, ${0.04 * (1 - dist / 150)})`;
                    ctx.stroke();
                }
            }
        }
        requestAnimationFrame(animate);
    }
    animate();

    // Clock
    function updateClock() {
        const el = document.getElementById('clock');
        if (el) {
            const now = new Date();
            el.textContent = now.toUTCString().slice(17, 25) + ' UTC';
        }
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
    # LOGIN PAGE
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
            background: #050508;
            color: #d0d0e0;
            font-family: 'Rajdhani', sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }
        canvas { position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 0; }

        .login-container {
            position: relative;
            z-index: 1;
            width: 380px;
            animation: fadeInUp 0.6s ease;
        }

        @keyframes fadeInUp {
            from { opacity: 0; transform: translateY(30px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .login-eye {
            width: 60px; height: 60px;
            margin: 0 auto 24px;
            background: radial-gradient(circle, #e03030 25%, transparent 70%);
            border-radius: 50%;
            animation: eyePulse 3s ease-in-out infinite;
        }

        @keyframes eyePulse {
            0%, 100% { box-shadow: 0 0 20px #e03030, 0 0 60px rgba(224,48,48,0.2); }
            50% { box-shadow: 0 0 40px #e03030, 0 0 100px rgba(224,48,48,0.3); }
        }

        .login-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 24px;
            font-weight: 900;
            letter-spacing: 6px;
            color: #e03030;
            text-align: center;
            margin-bottom: 4px;
        }

        .login-subtitle {
            font-family: 'Share Tech Mono', monospace;
            font-size: 11px;
            letter-spacing: 3px;
            color: #3a3a55;
            text-align: center;
            margin-bottom: 32px;
        }

        .login-card {
            background: rgba(18, 18, 30, 0.9);
            border: 1px solid #1e1e35;
            border-radius: 12px;
            padding: 32px;
            backdrop-filter: blur(20px);
            box-shadow: 0 4px 40px rgba(0,0,0,0.5), 0 0 40px rgba(224,48,48,0.05);
        }

        .form-group { margin-bottom: 20px; }

        .form-group label {
            display: block;
            font-family: 'Share Tech Mono', monospace;
            font-size: 10px;
            letter-spacing: 3px;
            color: #6a6a8a;
            text-transform: uppercase;
            margin-bottom: 8px;
        }

        .form-group input {
            width: 100%;
            padding: 12px 16px;
            background: #0a0a10;
            border: 1px solid #1e1e35;
            border-radius: 6px;
            color: #d0d0e0;
            font-family: 'Share Tech Mono', monospace;
            font-size: 14px;
            outline: none;
            transition: all 0.2s;
        }

        .form-group input:focus {
            border-color: #e03030;
            box-shadow: 0 0 15px rgba(224,48,48,0.1);
        }

        .btn-login {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #801818, #e03030);
            border: none;
            border-radius: 6px;
            color: #fff;
            font-family: 'Orbitron', sans-serif;
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 4px;
            cursor: pointer;
            transition: all 0.3s;
            text-transform: uppercase;
        }

        .btn-login:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(224,48,48,0.3);
        }

        .errors {
            background: rgba(208,48,48,0.1);
            border: 1px solid rgba(208,48,48,0.3);
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 20px;
            font-family: 'Share Tech Mono', monospace;
            font-size: 12px;
            color: #e03030;
        }

        .scan-line {
            position: fixed;
            top: 0; left: 0; right: 0;
            height: 2px;
            background: linear-gradient(90deg, transparent, rgba(224,48,48,0.3), transparent);
            animation: scanMove 4s linear infinite;
            z-index: 2;
        }

        @keyframes scanMove {
            0% { transform: translateY(0); }
            100% { transform: translateY(100vh); }
        }
    </style>
</head>
<body>
    <canvas id="particles-canvas"></canvas>
    <div class="scan-line"></div>

    <div class="login-container">
        <div class="login-eye"></div>
        <h1 class="login-title">SAURON VISION</h1>
        <p class="login-subtitle">AUTHENTICATE TO PROCEED</p>

        <div class="login-card">
            {% if form.errors %}
            <div class="errors">
                ⚠ AUTHENTICATION FAILED — INVALID CREDENTIALS
            </div>
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
            this.vx = (Math.random() - 0.5) * 0.4;
            this.vy = (Math.random() - 0.5) * 0.4;
            this.s = Math.random() * 1.5 + 0.3;
            this.a = Math.random() * 0.25 + 0.05;
        }
        update() { this.x += this.vx; this.y += this.vy; if (this.x < 0 || this.x > canvas.width || this.y < 0 || this.y > canvas.height) this.reset(); }
        draw() { ctx.beginPath(); ctx.arc(this.x, this.y, this.s, 0, Math.PI * 2); ctx.fillStyle = `rgba(224,48,48,${this.a})`; ctx.fill(); }
    }
    for (let i = 0; i < 60; i++) particles.push(new P());
    function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => { p.update(); p.draw(); });
        for (let i = 0; i < particles.length; i++)
            for (let j = i + 1; j < particles.length; j++) {
                const d = Math.hypot(particles[i].x - particles[j].x, particles[i].y - particles[j].y);
                if (d < 120) { ctx.beginPath(); ctx.moveTo(particles[i].x, particles[i].y); ctx.lineTo(particles[j].x, particles[j].y); ctx.strokeStyle = `rgba(224,48,48,${0.05*(1-d/120)})`; ctx.stroke(); }
            }
        requestAnimationFrame(animate);
    }
    animate();
    </script>
</body>
</html>
'''))

    # ================================================================
    # DASHBOARD PAGE
    # ================================================================

    created.append(create_file("templates/dashboard/dashboard.html", r'''{% extends "base.html" %}

{% block title %}Sauron Vision — Dashboard{% endblock %}
{% block page_title %}⬡ COMMAND CENTER{% endblock %}

{% block content %}
<!-- KPI Row -->
<div class="grid grid-4" style="margin-bottom: 24px;">
    <div class="stat-box fade-in-up delay-1">
        <div class="stat-label">Portfolio Value</div>
        <div class="stat-value">€{{ portfolio.current_value|default:"10,000" }}</div>
        <div class="stat-change positive">▲ +{{ portfolio.daily_pnl_pct|default:"0.00" }}% today</div>
    </div>
    <div class="stat-box fade-in-up delay-2">
        <div class="stat-label">Active Signals</div>
        <div class="stat-value">{{ active_signals_count|default:"0" }}</div>
        <div class="stat-change" style="color: var(--accent-gold);">{{ pending_strategies|default:"0" }} strategies pending</div>
    </div>
    <div class="stat-box fade-in-up delay-3">
        <div class="stat-label">Instruments Tracked</div>
        <div class="stat-value">{{ instruments_count|default:"0" }}</div>
        <div class="stat-change" style="color: var(--accent-blue);">{{ watchlist_count|default:"0" }} on watchlist</div>
    </div>
    <div class="stat-box fade-in-up delay-4">
        <div class="stat-label">AI Tasks (24h)</div>
        <div class="stat-value">{{ ai_tasks_24h|default:"0" }}</div>
        <div class="stat-change" style="color: var(--accent-purple);">{{ ai_cost_24h|default:"$0.00" }} spent</div>
    </div>
</div>

<div class="grid grid-sidebar">
    <!-- Left Column -->
    <div>
        <!-- Active Signals Feed -->
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
                        <span style="font-family: var(--font-display); font-size: 13px;">{{ signal.score|floatformat:2 }}</span>
                    </div>
                    <div class="signal-desc">{{ signal.title }}</div>
                </div>
                {% endfor %}
            {% else %}
                <div class="empty-state">
                    <div class="empty-icon">⚡</div>
                    <p>NO ACTIVE SIGNALS — MARKETS SCANNING</p>
                </div>
            {% endif %}
        </div>

        <!-- Active Strategies -->
        <div class="card fade-in-up delay-4">
            <div class="card-header">
                <span class="card-title">⬡ Active Strategies</span>
                <a href="{% url 'strategies_list' %}" class="btn btn-sm">View All →</a>
            </div>
            {% if active_strategies %}
                <div class="table-wrapper">
                <table>
                    <thead><tr><th>Strategy</th><th>Horizon</th><th>Status</th><th>P&L</th></tr></thead>
                    <tbody>
                    {% for s in active_strategies %}
                    <tr>
                        <td>{{ s.name|truncatechars:40 }}</td>
                        <td><span class="badge badge-medium">{{ s.time_horizon }}</span></td>
                        <td><span class="badge badge-active">{{ s.status }}</span></td>
                        <td style="color: {% if s.pnl >= 0 %}var(--accent-green){% else %}var(--accent-red){% endif %}">{{ s.pnl_pct|floatformat:2 }}%</td>
                    </tr>
                    {% endfor %}
                    </tbody>
                </table>
                </div>
            {% else %}
                <div class="empty-state">
                    <div class="empty-icon">⬡</div>
                    <p>NO ACTIVE STRATEGIES</p>
                </div>
            {% endif %}
        </div>
    </div>

    <!-- Right Column -->
    <div>
        <!-- Latest News -->
        <div class="card fade-in-up delay-2" style="margin-bottom: 20px;">
            <div class="card-header">
                <span class="card-title">▤ Latest News</span>
                <a href="{% url 'news_feed' %}" class="btn btn-sm">All →</a>
            </div>
            {% if recent_news %}
                {% for article in recent_news %}
                <div style="padding: 8px 0; border-bottom: 1px solid rgba(30,30,53,0.4);">
                    <div style="font-size: 13px; margin-bottom: 3px;">{{ article.title|truncatechars:80 }}</div>
                    <div style="font-family: var(--font-mono); font-size: 10px; color: var(--text-muted);">
                        {{ article.source }} · {{ article.published_at|timesince }} ago
                        {% if article.ai_sentiment_score != None %}
                        · <span style="color: {% if article.ai_sentiment_score > 0 %}var(--accent-green){% elif article.ai_sentiment_score < 0 %}var(--accent-red){% else %}var(--text-secondary){% endif %}">
                            {{ article.ai_sentiment_score|floatformat:2 }}
                        </span>
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <div class="empty-state" style="padding: 30px;">
                    <p>NO NEWS YET</p>
                </div>
            {% endif %}
        </div>

        <!-- Portfolio Exposure -->
        <div class="card fade-in-up delay-3" style="margin-bottom: 20px;">
            <div class="card-header">
                <span class="card-title">◎ Exposure</span>
            </div>
            <ul class="kv-list">
                <li><span class="label">STOCKS</span><span class="value">{{ exposure.stock|default:"0" }}%</span></li>
                <li><span class="label">FOREX</span><span class="value">{{ exposure.forex|default:"0" }}%</span></li>
                <li><span class="label">COMMODITIES</span><span class="value">{{ exposure.commodity|default:"0" }}%</span></li>
                <li><span class="label">CASH</span><span class="value">{{ exposure.cash|default:"100" }}%</span></li>
            </ul>
        </div>

        <!-- AI Agent Status -->
        <div class="card fade-in-up delay-4">
            <div class="card-header">
                <span class="card-title">◬ AI Agents</span>
                <a href="{% url 'ai_insights' %}" class="btn btn-sm">Details →</a>
            </div>
            {% if recent_ai_tasks %}
                {% for task in recent_ai_tasks %}
                <div style="padding: 6px 0; border-bottom: 1px solid rgba(30,30,53,0.3); font-size: 12px;">
                    <span style="color: {% if task.success %}var(--accent-green){% else %}var(--accent-red){% endif %}">●</span>
                    <span style="font-family: var(--font-mono); color: var(--text-secondary);">{{ task.agent }}</span>
                    <span style="float: right; color: var(--text-muted); font-family: var(--font-mono); font-size: 10px;">{{ task.created_at|timesince }} ago</span>
                </div>
                {% endfor %}
            {% else %}
                <div class="empty-state" style="padding: 30px;">
                    <p>NO AI TASKS YET</p>
                </div>
            {% endif %}
        </div>
    </div>
</div>
{% endblock %}
'''))

    # ================================================================
    # INSTRUMENTS LIST
    # ================================================================

    created.append(create_file("templates/dashboard/instruments_list.html", r'''{% extends "base.html" %}
{% block title %}Instruments — Sauron Vision{% endblock %}
{% block page_title %}◈ INSTRUMENTS{% endblock %}

{% block content %}
<div class="card fade-in-up">
    <div class="card-header">
        <span class="card-title">Tracked Instruments ({{ instruments|length }})</span>
        <div>
            <a href="?filter=watchlist" class="btn btn-sm {% if filter == 'watchlist' %}btn-primary{% endif %}">Watchlist</a>
            <a href="?filter=stock" class="btn btn-sm {% if filter == 'stock' %}btn-primary{% endif %}">Stocks</a>
            <a href="?filter=forex" class="btn btn-sm {% if filter == 'forex' %}btn-primary{% endif %}">Forex</a>
            <a href="?filter=commodity" class="btn btn-sm {% if filter == 'commodity' %}btn-primary{% endif %}">Commodities</a>
            <a href="{% url 'instruments_list' %}" class="btn btn-sm">All</a>
        </div>
    </div>
    <div class="table-wrapper">
    <table>
        <thead><tr><th>Symbol</th><th>Name</th><th>Class</th><th>Exchange</th><th>Watchlist</th><th>Active</th></tr></thead>
        <tbody>
        {% for inst in instruments %}
        <tr>
            <td style="font-family: var(--font-display); font-size: 13px; color: var(--accent-gold);">{{ inst.symbol }}</td>
            <td>{{ inst.name }}</td>
            <td><span class="badge badge-{{ inst.asset_class }}">{{ inst.asset_class }}</span></td>
            <td style="color: var(--text-secondary);">{{ inst.exchange }}</td>
            <td>{% if inst.is_watchlist %}<span style="color: var(--accent-gold);">★</span>{% else %}<span style="color: var(--text-muted);">☆</span>{% endif %}</td>
            <td>{% if inst.is_active %}<span style="color: var(--accent-green);">●</span>{% else %}<span style="color: var(--text-muted);">○</span>{% endif %}</td>
        </tr>
        {% empty %}
        <tr><td colspan="6"><div class="empty-state"><p>NO INSTRUMENTS — Run: python manage.py seed_instruments</p></div></td></tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
</div>
{% endblock %}
'''))

    # ================================================================
    # LIVE QUOTES
    # ================================================================

    created.append(create_file("templates/dashboard/market_quotes.html", r'''{% extends "base.html" %}
{% block title %}Live Quotes — Sauron Vision{% endblock %}
{% block page_title %}◆ LIVE QUOTES{% endblock %}

{% block content %}
<div class="card fade-in-up">
    <div class="card-header">
        <span class="card-title">Real-Time Market Data</span>
        <span style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">Auto-refresh: 60s</span>
    </div>
    {% if quotes %}
    <div class="table-wrapper">
    <table>
        <thead><tr><th>Symbol</th><th>Last</th><th>Bid</th><th>Ask</th><th>Change %</th><th>Volume</th><th>Updated</th><th>Source</th></tr></thead>
        <tbody>
        {% for q in quotes %}
        <tr>
            <td style="font-family: var(--font-display); font-size: 13px;">{{ q.instrument.symbol }}</td>
            <td style="font-weight: 600;">{{ q.last }}</td>
            <td>{{ q.bid|default:"-" }}</td>
            <td>{{ q.ask|default:"-" }}</td>
            <td style="color: {% if q.change_pct > 0 %}var(--accent-green){% elif q.change_pct < 0 %}var(--accent-red){% else %}var(--text-secondary){% endif %};">
                {% if q.change_pct > 0 %}▲{% elif q.change_pct < 0 %}▼{% endif %} {{ q.change_pct|floatformat:2 }}%
            </td>
            <td>{{ q.volume|default:"-" }}</td>
            <td style="color: var(--text-muted); font-size: 11px;">{{ q.updated_at|timesince }} ago</td>
            <td style="color: var(--text-muted);">{{ q.source }}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
    {% else %}
    <div class="empty-state">
        <div class="empty-icon">◆</div>
        <p>NO LIVE QUOTES — Waiting for data adapters to fetch prices</p>
    </div>
    {% endif %}
</div>
{% endblock %}
'''))

    # ================================================================
    # ECONOMIC CALENDAR
    # ================================================================

    created.append(create_file("templates/dashboard/economic_calendar.html", r'''{% extends "base.html" %}
{% block title %}Economic Calendar — Sauron Vision{% endblock %}
{% block page_title %}◇ ECONOMIC CALENDAR{% endblock %}

{% block content %}
<div class="card fade-in-up">
    <div class="card-header">
        <span class="card-title">Upcoming Events</span>
    </div>
    {% if events %}
    <div class="table-wrapper">
    <table>
        <thead><tr><th>Date/Time</th><th>Impact</th><th>Country</th><th>Event</th><th>Forecast</th><th>Previous</th><th>Actual</th></tr></thead>
        <tbody>
        {% for ev in events %}
        <tr>
            <td style="font-size: 12px;">{{ ev.datetime|date:"M d, H:i" }}</td>
            <td><span class="badge badge-{{ ev.impact }}">{{ ev.impact }}</span></td>
            <td>{{ ev.country }}</td>
            <td>{{ ev.title }}</td>
            <td>{{ ev.forecast|default:"-" }}</td>
            <td>{{ ev.previous|default:"-" }}</td>
            <td style="font-weight: 600;">{{ ev.actual|default:"-" }}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
    {% else %}
    <div class="empty-state">
        <div class="empty-icon">◇</div>
        <p>NO ECONOMIC EVENTS — Scraper will populate this automatically</p>
    </div>
    {% endif %}
</div>
{% endblock %}
'''))

    # ================================================================
    # SIGNALS LIST
    # ================================================================

    created.append(create_file("templates/dashboard/signals_list.html", r'''{% extends "base.html" %}
{% block title %}Signals — Sauron Vision{% endblock %}
{% block page_title %}⚡ SIGNAL INTELLIGENCE{% endblock %}

{% block content %}
<div class="grid grid-4" style="margin-bottom: 24px;">
    <div class="stat-box fade-in-up delay-1">
        <div class="stat-label">Active Signals</div>
        <div class="stat-value">{{ active_count|default:"0" }}</div>
    </div>
    <div class="stat-box fade-in-up delay-2">
        <div class="stat-label">Bullish</div>
        <div class="stat-value" style="color: var(--accent-green);">{{ bullish_count|default:"0" }}</div>
    </div>
    <div class="stat-box fade-in-up delay-3">
        <div class="stat-label">Bearish</div>
        <div class="stat-value" style="color: var(--accent-red);">{{ bearish_count|default:"0" }}</div>
    </div>
    <div class="stat-box fade-in-up delay-4">
        <div class="stat-label">Avg Score</div>
        <div class="stat-value">{{ avg_score|default:"0.00" }}</div>
    </div>
</div>

<div class="card fade-in-up delay-3">
    <div class="card-header">
        <span class="card-title">All Signals</span>
        <div>
            <a href="?active=1" class="btn btn-sm {% if active_only %}btn-primary{% endif %}">Active Only</a>
            <a href="{% url 'signals_list' %}" class="btn btn-sm">All</a>
        </div>
    </div>
    {% if signals %}
    <div class="table-wrapper">
    <table>
        <thead><tr><th>Time</th><th>Symbol</th><th>Type</th><th>Direction</th><th>Urgency</th><th>Title</th><th>Score</th><th>Entry</th><th>Stop</th><th>Target</th><th>R:R</th></tr></thead>
        <tbody>
        {% for s in signals %}
        <tr>
            <td style="font-size: 11px; color: var(--text-muted);">{{ s.created_at|date:"M d H:i" }}</td>
            <td style="font-family: var(--font-display); font-size: 12px;">{{ s.instrument.symbol }}</td>
            <td><span class="badge badge-medium">{{ s.signal_type }}</span></td>
            <td><span class="badge badge-{{ s.direction }}">{{ s.direction }}</span></td>
            <td><span class="badge badge-{{ s.urgency }}">{{ s.urgency }}</span></td>
            <td>{{ s.title|truncatechars:50 }}</td>
            <td>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span>{{ s.score|floatformat:2 }}</span>
                    <div class="score-bar" style="width: 50px;">
                        <div class="score-bar-fill" style="width: {{ s.score|floatformat:0 }}%; background: {% if s.score >= 0.7 %}var(--accent-green){% elif s.score >= 0.4 %}var(--accent-gold){% else %}var(--accent-red){% endif %};"></div>
                    </div>
                </div>
            </td>
            <td style="font-family: var(--font-mono); font-size: 12px;">{{ s.suggested_entry|default:"-" }}</td>
            <td style="font-family: var(--font-mono); font-size: 12px; color: var(--accent-red);">{{ s.suggested_stop|default:"-" }}</td>
            <td style="font-family: var(--font-mono); font-size: 12px; color: var(--accent-green);">{{ s.suggested_target|default:"-" }}</td>
            <td>{{ s.risk_reward_ratio|default:"-" }}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
    {% else %}
    <div class="empty-state">
        <div class="empty-icon">⚡</div>
        <p>NO SIGNALS DETECTED — Signal engine scans every 15 minutes</p>
    </div>
    {% endif %}
</div>
{% endblock %}
'''))

    # ================================================================
    # STRATEGIES LIST
    # ================================================================

    created.append(create_file("templates/dashboard/strategies_list.html", r'''{% extends "base.html" %}
{% block title %}Strategies — Sauron Vision{% endblock %}
{% block page_title %}⬡ STRATEGY ENGINE{% endblock %}

{% block content %}
<div class="card fade-in-up">
    <div class="card-header">
        <span class="card-title">Trading Strategies</span>
        <div>
            <a href="?status=active" class="btn btn-sm">Active</a>
            <a href="?status=proposed" class="btn btn-sm">Proposed</a>
            <a href="{% url 'strategies_list' %}" class="btn btn-sm">All</a>
        </div>
    </div>
    {% if strategies %}
    <div class="table-wrapper">
    <table>
        <thead><tr><th>Strategy</th><th>Horizon</th><th>Status</th><th>Instruments</th><th>P&L</th><th>Max DD</th><th>Created</th></tr></thead>
        <tbody>
        {% for s in strategies %}
        <tr>
            <td><a href="{% url 'strategy_detail' s.pk %}" style="color: var(--text-primary); text-decoration: none;">{{ s.name|truncatechars:50 }}</a></td>
            <td><span class="badge badge-medium">{{ s.time_horizon }}</span></td>
            <td><span class="badge badge-{{ s.status }}">{{ s.status }}</span></td>
            <td style="font-family: var(--font-mono); font-size: 12px;">{{ s.legs.count }} legs</td>
            <td style="color: {% if s.pnl_pct >= 0 %}var(--accent-green){% else %}var(--accent-red){% endif %}; font-family: var(--font-mono);">{{ s.pnl_pct|floatformat:2 }}%</td>
            <td style="color: var(--accent-red); font-family: var(--font-mono);">{{ s.max_drawdown|floatformat:2 }}%</td>
            <td style="color: var(--text-muted); font-size: 12px;">{{ s.created_at|date:"M d" }}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
    {% else %}
    <div class="empty-state">
        <div class="empty-icon">⬡</div>
        <p>NO STRATEGIES — AI advisor proposes strategies from active signals</p>
    </div>
    {% endif %}
</div>
{% endblock %}
'''))

    # ================================================================
    # STRATEGY DETAIL
    # ================================================================

    created.append(create_file("templates/dashboard/strategy_detail.html", r'''{% extends "base.html" %}
{% block title %}{{ strategy.name }} — Sauron Vision{% endblock %}
{% block page_title %}⬡ STRATEGY DETAIL{% endblock %}

{% block content %}
<div class="detail-header fade-in-up">
    <div>
        <h2>{{ strategy.name }}</h2>
        <div class="detail-meta">
            <span class="badge badge-{{ strategy.status }}">{{ strategy.status }}</span>
            <span class="badge badge-medium">{{ strategy.time_horizon }}</span>
            <span>Created {{ strategy.created_at|date:"M d, Y H:i" }}</span>
        </div>
    </div>
    <a href="{% url 'strategies_list' %}" class="btn">← Back</a>
</div>

<div class="grid grid-2" style="margin-bottom: 24px;">
    <div class="card fade-in-up delay-1">
        <div class="card-header"><span class="card-title">Thesis</span></div>
        <p style="font-size: 14px; line-height: 1.7;">{{ strategy.description }}</p>
        {% if strategy.ai_reasoning %}
        <div style="margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--border);">
            <div style="font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); letter-spacing: 2px; margin-bottom: 8px;">AI REASONING</div>
            <p style="font-size: 13px; color: var(--text-secondary); line-height: 1.7;">{{ strategy.ai_reasoning|truncatechars:500 }}</p>
        </div>
        {% endif %}
    </div>

    <div class="card fade-in-up delay-2">
        <div class="card-header"><span class="card-title">Performance & Risk</span></div>
        <ul class="kv-list">
            <li><span class="label">P&L</span><span class="value" style="color: {% if strategy.pnl >= 0 %}var(--accent-green){% else %}var(--accent-red){% endif %};">€{{ strategy.pnl }} ({{ strategy.pnl_pct|floatformat:2 }}%)</span></li>
            <li><span class="label">Max Drawdown</span><span class="value" style="color: var(--accent-red);">{{ strategy.max_drawdown|floatformat:2 }}%</span></li>
            <li><span class="label">Sharpe Ratio</span><span class="value">{{ strategy.sharpe_ratio|default:"-" }}</span></li>
            <li><span class="label">Max Allocation</span><span class="value">{{ strategy.max_portfolio_allocation_pct }}%</span></li>
            <li><span class="label">Max Loss</span><span class="value">{{ strategy.max_loss_pct }}%</span></li>
        </ul>
    </div>
</div>

<!-- Strategy Legs -->
<div class="card fade-in-up delay-3">
    <div class="card-header"><span class="card-title">Strategy Legs</span></div>
    {% if strategy.legs.all %}
    <div class="table-wrapper">
    <table>
        <thead><tr><th>Instrument</th><th>Action</th><th>Weight</th><th>Entry</th><th>Stop Loss</th><th>Take Profit</th><th>Status</th></tr></thead>
        <tbody>
        {% for leg in strategy.legs.all %}
        <tr>
            <td style="font-family: var(--font-display); font-size: 13px;">{{ leg.instrument.symbol }}</td>
            <td><span class="badge badge-{% if leg.action == 'long' %}bullish{% elif leg.action == 'short' %}bearish{% else %}neutral{% endif %}">{{ leg.action }}</span></td>
            <td>{{ leg.weight|floatformat:0 }}%</td>
            <td style="font-family: var(--font-mono);">{{ leg.entry_price|default:"-" }}</td>
            <td style="font-family: var(--font-mono); color: var(--accent-red);">{{ leg.stop_loss|default:"-" }}</td>
            <td style="font-family: var(--font-mono); color: var(--accent-green);">{{ leg.take_profit|default:"-" }}</td>
            <td>{% if leg.is_entered %}<span class="badge badge-active">ENTERED</span>{% else %}<span class="badge badge-proposed">PENDING</span>{% endif %}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
    {% else %}
    <div class="empty-state" style="padding: 30px;"><p>NO LEGS DEFINED</p></div>
    {% endif %}
</div>
{% endblock %}
'''))

    # ================================================================
    # NEWS FEED
    # ================================================================

    created.append(create_file("templates/dashboard/news_feed.html", r'''{% extends "base.html" %}
{% block title %}News & Sentiment — Sauron Vision{% endblock %}
{% block page_title %}▤ NEWS & SENTIMENT{% endblock %}

{% block content %}
<div class="card fade-in-up">
    <div class="card-header">
        <span class="card-title">News Feed</span>
    </div>
    {% if articles %}
    <div class="table-wrapper">
    <table>
        <thead><tr><th>Time</th><th>Source</th><th>Title</th><th>Sentiment</th><th>Urgency</th><th>Instruments</th></tr></thead>
        <tbody>
        {% for a in articles %}
        <tr>
            <td style="font-size: 11px; color: var(--text-muted); white-space: nowrap;">{{ a.published_at|date:"M d H:i" }}</td>
            <td style="font-size: 12px;">{{ a.source }}</td>
            <td><a href="{{ a.url }}" target="_blank" style="color: var(--text-primary); text-decoration: none;">{{ a.title|truncatechars:70 }}</a></td>
            <td>
                {% if a.ai_sentiment_score != None %}
                <span style="font-family: var(--font-mono); color: {% if a.ai_sentiment_score > 0.2 %}var(--accent-green){% elif a.ai_sentiment_score < -0.2 %}var(--accent-red){% else %}var(--text-secondary){% endif %};">
                    {{ a.ai_sentiment_score|floatformat:2 }}
                </span>
                {% else %}<span style="color: var(--text-muted);">—</span>{% endif %}
            </td>
            <td>{% if a.ai_urgency %}<span class="badge badge-{{ a.ai_urgency }}">{{ a.ai_urgency }}</span>{% else %}—{% endif %}</td>
            <td style="font-family: var(--font-mono); font-size: 11px;">
                {% for inst in a.ai_affected_instruments.all %}{{ inst.symbol }}{% if not forloop.last %}, {% endif %}{% empty %}—{% endfor %}
            </td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
    {% else %}
    <div class="empty-state">
        <div class="empty-icon">▤</div>
        <p>NO NEWS — Scraper fetches news every 3 minutes during market hours</p>
    </div>
    {% endif %}
</div>
{% endblock %}
'''))

    # ================================================================
    # PORTFOLIO OVERVIEW
    # ================================================================

    created.append(create_file("templates/dashboard/portfolio_overview.html", r'''{% extends "base.html" %}
{% block title %}Portfolio — Sauron Vision{% endblock %}
{% block page_title %}◎ PORTFOLIO{% endblock %}

{% block content %}
<div class="grid grid-4" style="margin-bottom: 24px;">
    <div class="stat-box fade-in-up delay-1">
        <div class="stat-label">Total Value</div>
        <div class="stat-value">€{{ portfolio.current_value|default:"10,000" }}</div>
    </div>
    <div class="stat-box fade-in-up delay-2">
        <div class="stat-label">Cash Available</div>
        <div class="stat-value">€{{ portfolio.cash_available|default:"10,000" }}</div>
    </div>
    <div class="stat-box fade-in-up delay-3">
        <div class="stat-label">Open Positions</div>
        <div class="stat-value">{{ open_positions_count|default:"0" }}</div>
    </div>
    <div class="stat-box fade-in-up delay-4">
        <div class="stat-label">Max Daily Loss</div>
        <div class="stat-value" style="color: var(--accent-red);">{{ portfolio.max_daily_loss_pct|default:"3.0" }}%</div>
    </div>
</div>

<div class="grid grid-2">
    <div class="card fade-in-up delay-3">
        <div class="card-header"><span class="card-title">Risk Limits</span></div>
        <ul class="kv-list">
            <li><span class="label">Max Total Exposure</span><span class="value">{{ portfolio.max_total_exposure_pct|default:"100" }}%</span></li>
            <li><span class="label">Max Single Position</span><span class="value">{{ portfolio.max_single_position_pct|default:"10" }}%</span></li>
            <li><span class="label">Max Sector Exposure</span><span class="value">{{ portfolio.max_sector_exposure_pct|default:"30" }}%</span></li>
            <li><span class="label">Correlation Threshold</span><span class="value">{{ portfolio.max_correlation_threshold|default:"0.7" }}</span></li>
            <li><span class="label">Base Currency</span><span class="value">{{ portfolio.currency|default:"EUR" }}</span></li>
        </ul>
    </div>
    <div class="card fade-in-up delay-4">
        <div class="card-header"><span class="card-title">Performance History</span></div>
        {% if snapshots %}
        <div class="table-wrapper">
        <table>
            <thead><tr><th>Date</th><th>Value</th><th>Daily P&L</th><th>Cumulative</th></tr></thead>
            <tbody>
            {% for snap in snapshots %}
            <tr>
                <td>{{ snap.date|date:"M d" }}</td>
                <td style="font-family: var(--font-mono);">€{{ snap.total_value }}</td>
                <td style="color: {% if snap.daily_pnl_pct >= 0 %}var(--accent-green){% else %}var(--accent-red){% endif %}; font-family: var(--font-mono);">{{ snap.daily_pnl_pct|floatformat:2 }}%</td>
                <td style="font-family: var(--font-mono);">{{ snap.cumulative_pnl_pct|floatformat:2 }}%</td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        </div>
        {% else %}
        <div class="empty-state" style="padding: 30px;"><p>NO SNAPSHOTS YET</p></div>
        {% endif %}
    </div>
</div>
{% endblock %}
'''))

    # ================================================================
    # POSITIONS LIST
    # ================================================================

    created.append(create_file("templates/dashboard/positions_list.html", r'''{% extends "base.html" %}
{% block title %}Positions — Sauron Vision{% endblock %}
{% block page_title %}▣ OPEN POSITIONS{% endblock %}

{% block content %}
<div class="card fade-in-up">
    <div class="card-header">
        <span class="card-title">Current Positions</span>
    </div>
    {% if positions %}
    <div class="table-wrapper">
    <table>
        <thead><tr><th>Symbol</th><th>Direction</th><th>Qty</th><th>Entry</th><th>Current</th><th>Stop</th><th>Target</th><th>P&L</th><th>P&L %</th><th>Strategy</th><th>Opened</th></tr></thead>
        <tbody>
        {% for p in positions %}
        <tr>
            <td style="font-family: var(--font-display); font-size: 13px;">{{ p.instrument.symbol }}</td>
            <td><span class="badge badge-{% if p.direction == 'long' %}bullish{% else %}bearish{% endif %}">{{ p.direction }}</span></td>
            <td style="font-family: var(--font-mono);">{{ p.quantity }}</td>
            <td style="font-family: var(--font-mono);">{{ p.entry_price }}</td>
            <td style="font-family: var(--font-mono); font-weight: 600;">{{ p.current_price }}</td>
            <td style="font-family: var(--font-mono); color: var(--accent-red);">{{ p.stop_loss|default:"-" }}</td>
            <td style="font-family: var(--font-mono); color: var(--accent-green);">{{ p.take_profit|default:"-" }}</td>
            <td style="color: {% if p.unrealized_pnl >= 0 %}var(--accent-green){% else %}var(--accent-red){% endif %}; font-family: var(--font-mono);">€{{ p.unrealized_pnl }}</td>
            <td style="color: {% if p.unrealized_pnl_pct >= 0 %}var(--accent-green){% else %}var(--accent-red){% endif %}; font-family: var(--font-mono);">{{ p.unrealized_pnl_pct|floatformat:2 }}%</td>
            <td style="font-size: 12px;">{{ p.strategy.name|default:"-"|truncatechars:20 }}</td>
            <td style="font-size: 11px; color: var(--text-muted);">{{ p.opened_at|date:"M d H:i" }}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
    {% else %}
    <div class="empty-state">
        <div class="empty-icon">▣</div>
        <p>NO OPEN POSITIONS</p>
    </div>
    {% endif %}
</div>
{% endblock %}
'''))

    # ================================================================
    # AI INSIGHTS
    # ================================================================

    created.append(create_file("templates/dashboard/ai_insights.html", r'''{% extends "base.html" %}
{% block title %}AI Insights — Sauron Vision{% endblock %}
{% block page_title %}◬ AI INTELLIGENCE{% endblock %}

{% block content %}
<div class="grid grid-4" style="margin-bottom: 24px;">
    <div class="stat-box fade-in-up delay-1">
        <div class="stat-label">Total Tasks (24h)</div>
        <div class="stat-value">{{ tasks_24h|default:"0" }}</div>
    </div>
    <div class="stat-box fade-in-up delay-2">
        <div class="stat-label">Success Rate</div>
        <div class="stat-value" style="color: var(--accent-green);">{{ success_rate|default:"0" }}%</div>
    </div>
    <div class="stat-box fade-in-up delay-3">
        <div class="stat-label">API Cost (24h)</div>
        <div class="stat-value">${{ cost_24h|default:"0.00" }}</div>
    </div>
    <div class="stat-box fade-in-up delay-4">
        <div class="stat-label">Avg Response</div>
        <div class="stat-value">{{ avg_duration|default:"0.0" }}s</div>
    </div>
</div>

<!-- Latest Briefing -->
<div class="card fade-in-up delay-3" style="margin-bottom: 24px;">
    <div class="card-header"><span class="card-title">Latest AI Briefing</span></div>
    {% if latest_briefing %}
    <div style="font-size: 14px; line-height: 1.8; white-space: pre-wrap;">{{ latest_briefing.structured_output.review|default:latest_briefing.response_summary|truncatechars:2000 }}</div>
    {% else %}
    <div class="empty-state" style="padding: 30px;">
        <p>NO BRIEFING YET — Daily briefing generates at 06:00 UTC</p>
    </div>
    {% endif %}
</div>

<!-- Recent Agent Tasks -->
<div class="card fade-in-up delay-4">
    <div class="card-header">
        <span class="card-title">Recent Agent Tasks</span>
        <a href="{% url 'ai_tasks_list' %}" class="btn btn-sm">View All →</a>
    </div>
    {% if recent_tasks %}
    <div class="table-wrapper">
    <table>
        <thead><tr><th>Time</th><th>Agent</th><th>Provider</th><th>Model</th><th>Status</th><th>Duration</th><th>Tokens</th><th>Cost</th></tr></thead>
        <tbody>
        {% for t in recent_tasks %}
        <tr>
            <td style="font-size: 11px; color: var(--text-muted);">{{ t.created_at|date:"M d H:i" }}</td>
            <td style="font-family: var(--font-mono);">{{ t.agent }}</td>
            <td>{{ t.provider }}</td>
            <td style="font-size: 11px; color: var(--text-muted);">{{ t.model|truncatechars:25 }}</td>
            <td>{% if t.success %}<span style="color: var(--accent-green);">● OK</span>{% else %}<span style="color: var(--accent-red);">● FAIL</span>{% endif %}</td>
            <td style="font-family: var(--font-mono);">{{ t.duration_seconds|floatformat:1 }}s</td>
            <td style="font-family: var(--font-mono); font-size: 11px;">{{ t.input_tokens }}→{{ t.output_tokens }}</td>
            <td style="font-family: var(--font-mono);">${{ t.cost_usd }}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
    {% else %}
    <div class="empty-state" style="padding: 30px;"><p>NO AI TASKS YET</p></div>
    {% endif %}
</div>
{% endblock %}
'''))

    # ================================================================
    # AI TASKS FULL LIST
    # ================================================================

    created.append(create_file("templates/dashboard/ai_tasks_list.html", r'''{% extends "base.html" %}
{% block title %}AI Tasks — Sauron Vision{% endblock %}
{% block page_title %}▸ AGENT TASK LOG{% endblock %}

{% block content %}
<div class="card fade-in-up">
    <div class="card-header">
        <span class="card-title">All Agent Tasks</span>
    </div>
    {% if tasks %}
    <div class="table-wrapper">
    <table>
        <thead><tr><th>Time</th><th>Agent</th><th>Provider</th><th>Model</th><th>Status</th><th>Duration</th><th>In/Out Tokens</th><th>Cost</th><th>Summary</th></tr></thead>
        <tbody>
        {% for t in tasks %}
        <tr>
            <td style="font-size: 11px; color: var(--text-muted); white-space: nowrap;">{{ t.created_at|date:"M d H:i:s" }}</td>
            <td style="font-family: var(--font-mono);">{{ t.agent }}</td>
            <td>{{ t.provider }}</td>
            <td style="font-size: 10px; color: var(--text-muted);">{{ t.model|truncatechars:20 }}</td>
            <td>{% if t.success %}<span style="color: var(--accent-green);">●</span>{% else %}<span style="color: var(--accent-red);">●</span>{% endif %}</td>
            <td style="font-family: var(--font-mono);">{{ t.duration_seconds|floatformat:1 }}s</td>
            <td style="font-family: var(--font-mono); font-size: 11px;">{{ t.input_tokens }}/{{ t.output_tokens }}</td>
            <td style="font-family: var(--font-mono);">${{ t.cost_usd }}</td>
            <td style="font-size: 12px; max-width: 300px; overflow: hidden; text-overflow: ellipsis;">{{ t.response_summary|truncatechars:80 }}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
    {% else %}
    <div class="empty-state">
        <div class="empty-icon">▸</div>
        <p>NO AGENT TASKS RECORDED</p>
    </div>
    {% endif %}
</div>
{% endblock %}
'''))

    # ================================================================
    # VIEWS — dashboard/views.py (replace entirely)
    # ================================================================

    created.append(create_file("dashboard/views.py", '''"""Sauron Vision — Dashboard Views."""
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta


@login_required
def dashboard(request):
    from instruments.models import Instrument
    from signals.models import Signal
    from strategies.models import Strategy
    from scraping.models import NewsArticle
    from ai_agents.models import AgentTask
    from portfolio.services import get_or_create_default_portfolio

    portfolio = get_or_create_default_portfolio()
    now = timezone.now()
    day_ago = now - timedelta(hours=24)

    context = {
        "page_id": "dashboard",
        "portfolio": portfolio,
        "instruments_count": Instrument.objects.filter(is_active=True).count(),
        "watchlist_count": Instrument.objects.filter(is_watchlist=True).count(),
        "active_signals_count": Signal.objects.filter(is_active=True).count(),
        "pending_strategies": Strategy.objects.filter(status="proposed").count(),
        "recent_signals": Signal.objects.filter(is_active=True).select_related("instrument").order_by("-created_at")[:5],
        "active_strategies": Strategy.objects.filter(status__in=["active", "approved"]).order_by("-created_at")[:5],
        "recent_news": NewsArticle.objects.order_by("-published_at")[:5],
        "recent_ai_tasks": AgentTask.objects.order_by("-created_at")[:5],
        "ai_tasks_24h": AgentTask.objects.filter(created_at__gte=day_ago).count(),
        "ai_cost_24h": "${:.2f}".format(
            sum(float(t.cost_usd) for t in AgentTask.objects.filter(created_at__gte=day_ago))
        ),
        "exposure": {"stock": 0, "forex": 0, "commodity": 0, "cash": 100},
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

    return render(request, "dashboard/instruments_list.html", {
        "page_id": "instruments",
        "instruments": qs.order_by("asset_class", "symbol"),
        "filter": filter_type,
    })


@login_required
def market_quotes(request):
    from market_data.models import LiveQuote
    return render(request, "dashboard/market_quotes.html", {
        "page_id": "quotes",
        "quotes": LiveQuote.objects.select_related("instrument").order_by("instrument__symbol"),
    })


@login_required
def economic_calendar(request):
    from market_data.models import EconomicEvent
    return render(request, "dashboard/economic_calendar.html", {
        "page_id": "calendar",
        "events": EconomicEvent.objects.order_by("datetime")[:50],
    })


@login_required
def signals_list(request):
    from signals.models import Signal
    from django.db.models import Avg

    active_only = request.GET.get("active") == "1"
    qs = Signal.objects.select_related("instrument").order_by("-created_at")

    if active_only:
        qs = qs.filter(is_active=True)

    active_qs = Signal.objects.filter(is_active=True)

    return render(request, "dashboard/signals_list.html", {
        "page_id": "signals",
        "signals": qs[:100],
        "active_only": active_only,
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

    return render(request, "dashboard/strategies_list.html", {
        "page_id": "strategies",
        "strategies": qs[:50],
    })


@login_required
def strategy_detail(request, pk):
    from strategies.models import Strategy
    strategy = get_object_or_404(Strategy.objects.prefetch_related("legs__instrument", "adjustments"), pk=pk)
    return render(request, "dashboard/strategy_detail.html", {
        "page_id": "strategies",
        "strategy": strategy,
    })


@login_required
def news_feed(request):
    from scraping.models import NewsArticle
    return render(request, "dashboard/news_feed.html", {
        "page_id": "news",
        "articles": NewsArticle.objects.prefetch_related("ai_affected_instruments").order_by("-published_at")[:100],
    })


@login_required
def portfolio_overview(request):
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import PortfolioSnapshot

    portfolio = get_or_create_default_portfolio()
    return render(request, "dashboard/portfolio_overview.html", {
        "page_id": "portfolio",
        "portfolio": portfolio,
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
    from django.utils import timezone
    from datetime import timedelta

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
        "avg_duration": "{:.1f}".format(
            sum(t.duration_seconds for t in tasks_24h_qs) / total_24h if total_24h > 0 else 0
        ),
        "latest_briefing": AgentTask.objects.filter(agent__in=["strategy_advisor", "weekly_reviewer"], success=True).first(),
        "recent_tasks": AgentTask.objects.order_by("-created_at")[:20],
    })


@login_required
def ai_tasks_list(request):
    from ai_agents.models import AgentTask
    return render(request, "dashboard/ai_tasks_list.html", {
        "page_id": "ai_tasks",
        "tasks": AgentTask.objects.order_by("-created_at")[:200],
    })
'''))

    # ================================================================
    # URLS — dashboard/urls.py (replace entirely)
    # ================================================================

    created.append(create_file("dashboard/urls.py", '''"""Sauron Vision — Dashboard URL Configuration."""
from django.urls import path
from . import views
from .api import market_views, signal_views, strategy_views, portfolio_views, ai_views

urlpatterns = [
    # ── Frontend Pages ──────────────────────────────────────
    path("", views.dashboard, name="dashboard"),
    path("instruments/", views.instruments_list, name="instruments_list"),
    path("quotes/", views.market_quotes, name="market_quotes"),
    path("calendar/", views.economic_calendar, name="economic_calendar"),
    path("signals/", views.signals_list, name="signals_list"),
    path("strategies/", views.strategies_list, name="strategies_list"),
    path("strategies/<int:pk>/", views.strategy_detail, name="strategy_detail"),
    path("news/", views.news_feed, name="news_feed"),
    path("portfolio/", views.portfolio_overview, name="portfolio_overview"),
    path("positions/", views.positions_list, name="positions_list"),
    path("ai/", views.ai_insights, name="ai_insights"),
    path("ai/tasks/", views.ai_tasks_list, name="ai_tasks_list"),

    # ── API Endpoints ───────────────────────────────────────
    path("api/instruments/", market_views.InstrumentListView.as_view(), name="api-instrument-list"),
    path("api/quotes/", market_views.LiveQuoteListView.as_view(), name="api-live-quotes"),
    path("api/calendar/", market_views.EconomicCalendarView.as_view(), name="api-economic-calendar"),
    path("api/signals/", signal_views.SignalListView.as_view(), name="api-signal-list"),
    path("api/signals/active/", signal_views.ActiveSignalListView.as_view(), name="api-active-signals"),
    path("api/strategies/", strategy_views.StrategyListView.as_view(), name="api-strategy-list"),
    path("api/strategies/<int:pk>/", strategy_views.StrategyDetailView.as_view(), name="api-strategy-detail"),
    path("api/portfolio/", portfolio_views.PortfolioView.as_view(), name="api-portfolio"),
    path("api/portfolio/positions/", portfolio_views.PositionListView.as_view(), name="api-positions"),
    path("api/portfolio/snapshots/", portfolio_views.SnapshotListView.as_view(), name="api-snapshots"),
    path("api/ai/tasks/", ai_views.AgentTaskListView.as_view(), name="api-ai-tasks"),
    path("api/ai/briefing/", ai_views.DailyBriefingView.as_view(), name="api-daily-briefing"),
]
'''))

    # ================================================================
    # CONFIG URLS — config/urls.py (replace entirely)
    # ================================================================

    created.append(create_file("config/urls.py", '''"""Sauron Vision — Root URL Configuration."""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect

urlpatterns = [
    path("admin/", admin.site.urls),

    # Authentication
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),

    # Dashboard (all pages)
    path("", include("dashboard.urls")),
]
'''))

    # ================================================================
    # SETTINGS ADDITIONS — login redirect
    # ================================================================

    created.append(create_file("config/_login_settings.py", '''"""
Add these lines to the END of your config/settings.py:

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"
"""
'''))

    # ================================================================
    # DONE
    # ================================================================

    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║   🔴  SAURON VISION — Frontend Generated ({len(created)} files)       ║
╚══════════════════════════════════════════════════════════════════╝

  Files created:
  ─────────────────────────────────────────────────
  templates/base.html                    (main layout + particles)
  templates/registration/login.html      (login page)
  templates/dashboard/dashboard.html     (command center)
  templates/dashboard/instruments_list.html
  templates/dashboard/market_quotes.html
  templates/dashboard/economic_calendar.html
  templates/dashboard/signals_list.html
  templates/dashboard/strategies_list.html
  templates/dashboard/strategy_detail.html
  templates/dashboard/news_feed.html
  templates/dashboard/portfolio_overview.html
  templates/dashboard/positions_list.html
  templates/dashboard/ai_insights.html
  templates/dashboard/ai_tasks_list.html
  dashboard/views.py                     (all view functions)
  dashboard/urls.py                      (URL routing)
  config/urls.py                         (root URLs with auth)

  ⚠  IMPORTANT — Add these to the END of config/settings.py:

      LOGIN_URL = "login"
      LOGIN_REDIRECT_URL = "dashboard"
      LOGOUT_REDIRECT_URL = "login"

  Then run:
      python manage.py runserver

  The eye sees all. 🔴
""")


if __name__ == "__main__":
    generate()
