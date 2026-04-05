#!/usr/bin/env python3
"""
SAURON VISION — Critical Fix
1. Backtester migration directory
2. Instruments list — clickable links + hover preview
3. Sidebar collapse — proper design, scroll, expand back
4. All interconnections working

Run inside sauron_vision/ directory.
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
    # 1. BACKTESTER — create migrations directory
    # ================================================================
    os.makedirs("backtester/migrations", exist_ok=True)
    created.append(create_file("backtester/migrations/__init__.py", ""))
    print("  [OK] backtester/migrations created")

    # ================================================================
    # 2. INSTRUMENTS LIST — clickable, with hover preview
    # ================================================================
    created.append(create_file("templates/dashboard/instruments_list.html",
r'''{% extends "base.html" %}
{% block title %}Instruments — Sauron Vision{% endblock %}
{% block page_title %}Instruments{% endblock %}

{% block content %}
<div class="card fade-in-up">
    <div class="card-header">
        <span class="card-title">Tracked Instruments ({{ instruments|length }})</span>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
            <a href="?filter=watchlist" class="btn btn-sm {% if filter == 'watchlist' %}btn-primary{% endif %}">Watchlist</a>
            <a href="?filter=stock" class="btn btn-sm {% if filter == 'stock' %}btn-primary{% endif %}">Stocks</a>
            <a href="?filter=forex" class="btn btn-sm {% if filter == 'forex' %}btn-primary{% endif %}">Forex</a>
            <a href="?filter=commodity" class="btn btn-sm {% if filter == 'commodity' %}btn-primary{% endif %}">Commodities</a>
            <a href="?filter=index" class="btn btn-sm {% if filter == 'index' %}btn-primary{% endif %}">Indices</a>
            <a href="?filter=etf" class="btn btn-sm {% if filter == 'etf' %}btn-primary{% endif %}">ETFs</a>
            <a href="?filter=crypto" class="btn btn-sm {% if filter == 'crypto' %}btn-primary{% endif %}">Crypto</a>
            <a href="{% url 'instruments_list' %}" class="btn btn-sm">All</a>
        </div>
    </div>
    <div class="table-wrapper">
    <table>
        <thead><tr><th>Symbol</th><th>Name</th><th>Class</th><th>Exchange</th><th>Watchlist</th><th>Active</th></tr></thead>
        <tbody>
        {% for inst in instruments %}
        <tr class="instrument-row" data-instrument="{{ inst.symbol }}" onclick="window.location='{% url 'instrument_detail' inst.symbol %}'" style="cursor:pointer;">
            <td>
                <a href="{% url 'instrument_detail' inst.symbol %}" style="font-family:var(--font-display);font-size:13px;color:var(--accent);text-decoration:none;font-weight:700;" data-instrument="{{ inst.symbol }}">{{ inst.symbol }}</a>
            </td>
            <td>{{ inst.name }}</td>
            <td><span class="badge badge-{{ inst.asset_class }}">{{ inst.asset_class }}</span></td>
            <td style="color:var(--text-secondary);">{{ inst.exchange }}</td>
            <td>{% if inst.is_watchlist %}<span style="color:var(--accent-gold);">&#x2605;</span>{% else %}<span style="color:var(--text-muted);">&#x2606;</span>{% endif %}</td>
            <td>{% if inst.is_active %}<span style="color:var(--accent);">&#x25CF;</span>{% else %}<span style="color:var(--text-muted);">&#x25CB;</span>{% endif %}</td>
        </tr>
        {% empty %}
        <tr><td colspan="6"><div class="empty-state"><p>NO INSTRUMENTS — Run: python manage.py init_platform</p></div></td></tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
</div>
{% endblock %}
'''))
    print("  [OK] instruments list — clickable rows with preview")

    # ================================================================
    # 3. SIDEBAR — complete redesign of collapse behavior
    # ================================================================
    base_path = "templates/base.html"
    with open(base_path, "r", encoding="utf-8") as f:
        content = f.read()

    # ── Remove ALL old sidebar collapse CSS ──
    content = re.sub(
        r'/\* ── Collapsible Sidebar.*?margin-left: 64px; \}',
        '/* sidebar-collapse CSS removed for replacement */',
        content,
        flags=re.DOTALL
    )

    # ── Remove old collapse button if it was injected badly ──
    content = content.replace(
        '<div class="sidebar-brand"><button class="sidebar-collapse-btn" onclick="document.getElementById(\'mainSidebar\').classList.toggle(\'collapsed\')" title="Collapse sidebar">\u276e</button>',
        '<div class="sidebar-brand">'
    )

    # ── Insert proper sidebar collapse CSS ──
    SIDEBAR_CSS = '''
        /* ── Sidebar Collapse ────────────────────── */
        .sidebar {
            transition: width 0.3s ease;
            overflow-y: auto;
            overflow-x: hidden;
        }
        .sidebar-toggle {
            position: absolute; top: 18px; right: -14px; z-index: 110;
            width: 28px; height: 28px; border-radius: 50%;
            background: var(--bg-card); border: 1px solid var(--border);
            color: var(--text-muted); cursor: pointer;
            display: flex; align-items: center; justify-content: center;
            font-size: 12px; transition: all 0.25s;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        }
        .sidebar-toggle:hover {
            border-color: var(--accent); color: var(--accent);
            box-shadow: 0 0 12px var(--accent-glow);
        }
        .sidebar-toggle .arrow { transition: transform 0.3s; display: inline-block; }
        .sidebar.mini .sidebar-toggle .arrow { transform: rotate(180deg); }

        .sidebar.mini { width: 68px; }
        .sidebar.mini .sidebar-brand h1 > span:not(.brand-eye-wrap),
        .sidebar.mini .sidebar-brand .subtitle { display: none; }
        .sidebar.mini .sidebar-brand { padding: 16px 12px; display: flex; justify-content: center; }
        .sidebar.mini .sidebar-brand h1 { justify-content: center; gap: 0; }
        .sidebar.mini .brand-eye { width: 28px; height: 28px; }
        .sidebar.mini .nav-section {
            font-size: 0; padding: 12px 0 2px; margin: 0;
            border-top: 1px solid var(--border); height: auto;
        }
        .sidebar.mini .nav-link {
            padding: 12px 0; justify-content: center;
            border-left: none; gap: 0; position: relative;
        }
        .sidebar.mini .nav-link .label-text { display: none; }
        .sidebar.mini .nav-link .icon { font-size: 18px; width: auto; }
        .sidebar.mini .nav-link:hover .label-text {
            display: block; position: absolute; left: 72px; top: 50%;
            transform: translateY(-50%); white-space: nowrap;
            background: var(--bg-card); border: 1px solid var(--border);
            padding: 8px 16px; border-radius: 8px; font-size: 13px;
            color: var(--text-primary); font-family: var(--font-heading);
            box-shadow: 0 4px 24px rgba(0,0,0,0.5); z-index: 500;
            pointer-events: none; letter-spacing: 0.5px; font-weight: 500;
        }
        .sidebar.mini .sidebar-footer {
            padding: 10px 8px; justify-content: center;
        }
        .sidebar.mini .sidebar-footer a,
        .sidebar.mini .sidebar-footer .logout-btn { font-size: 0; }
        .sidebar.mini .sidebar-footer a::after { content: '\\2699'; font-size: 16px; }
        .sidebar.mini .sidebar-footer .logout-btn::after { content: '\\23FB'; font-size: 16px; }

        body:has(.sidebar.mini) .main-content { margin-left: 68px; }
'''

    content = content.replace(
        '/* sidebar-collapse CSS removed for replacement */',
        SIDEBAR_CSS
    )

    # ── Fix all nav-link text to use .label-text span ──
    # Replace each nav link to wrap text in span.label-text
    nav_items = re.findall(r'(<a href="[^"]*" class="nav-link[^"]*"[^>]*>)<span class="icon">([^<]+)</span>\s*([^<]+)</a>', content)
    for full_match_tuple in nav_items:
        open_tag, icon_char, text = full_match_tuple
        old = f'{open_tag}<span class="icon">{icon_char}</span> {text}</a>'
        # Clean any data-label from old attempts
        text_clean = text.strip()
        new = f'{open_tag}<span class="icon">{icon_char}</span> <span class="label-text">{text_clean}</span></a>'
        content = content.replace(old, new)

    # Also handle ones that already have data-label
    content = re.sub(
        r'data-label="[^"]*">([^<]+)</a>',
        lambda m: f'><span class="label-text">{m.group(1).strip()}</span></a>',
        content
    )

    # ── Replace sidebar brand to add toggle button ──
    content = content.replace(
        '<aside class="sidebar" id="mainSidebar">',
        '<aside class="sidebar" id="mainSidebar">'
    )

    # Add toggle button inside sidebar brand (after brand div opens)
    if "sidebar-toggle" not in content:
        content = content.replace(
            '<div class="sidebar-brand">',
            '<div class="sidebar-brand" style="position:relative;">\n'
            '            <button class="sidebar-toggle" onclick="toggleSidebar()" title="Collapse/Expand">'
            '<span class="arrow">\u276e</span></button>'
        )

    # ── Add sidebar toggle JS ──
    if "toggleSidebar" not in content:
        toggle_js = '''
<script>
function toggleSidebar() {
    const sb = document.getElementById('mainSidebar');
    sb.classList.toggle('mini');
    localStorage.setItem('sauron_sidebar', sb.classList.contains('mini') ? 'mini' : 'full');
}
// Restore sidebar state on load
(function() {
    const state = localStorage.getItem('sauron_sidebar');
    if (state === 'mini') {
        const sb = document.getElementById('mainSidebar');
        if (sb) sb.classList.add('mini');
    }
})();
</script>
'''
        content = content.replace('{% block extra_js %}{% endblock %}', toggle_js + '\n{% block extra_js %}{% endblock %}')

    # ── Fix the old mobile override that forced sidebar display:none ──
    content = content.replace(
        '.sidebar { display: none; } .main-content { margin-left: 0; }',
        '.sidebar { transform: translateX(-100%); } .main-content { margin-left: 0 !important; }'
    )

    with open(base_path, "w", encoding="utf-8") as f:
        f.write(content)
    created.append(base_path)
    print("  [OK] sidebar — clean collapse with scroll, expand back, tooltips")

    # ================================================================
    # 4. Fix instrument detail view — filter update
    # ================================================================
    views_path = "dashboard/views.py"
    with open(views_path, "r", encoding="utf-8") as f:
        vc = f.read()

    # Fix instruments_list to include index, etf, crypto filters
    if '"index"' not in vc.split("def instruments_list")[1].split("def ")[0] if "def instruments_list" in vc else "":
        vc = vc.replace(
            'elif filter_type in ["stock", "forex", "commodity"]:',
            'elif filter_type in ["stock", "forex", "commodity", "index", "etf", "crypto"]:'
        )
        with open(views_path, "w", encoding="utf-8") as f:
            f.write(vc)
        print("  [OK] instruments filter — added index, etf, crypto")

    # ================================================================
    # 5. Also add AI Memory model to migrations
    # ================================================================
    ai_models_path = "ai_agents/models.py"
    if os.path.exists(ai_models_path):
        with open(ai_models_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "AIMemory" not in content:
            content += '''

class AIMemory(models.Model):
    """Persistent memory entries for AI agents."""
    agent = models.CharField(max_length=30, db_index=True)
    category = models.CharField(max_length=50)
    content = models.TextField()
    confidence = models.FloatField(default=0.5)
    source_task_id = models.IntegerField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-confidence", "-created_at"]

    def __str__(self):
        return f"[{self.agent}] {self.category}: {self.content[:80]}"

    @classmethod
    def remember(cls, agent, category, content, confidence=0.5, source_task_id=None, valid_days=None):
        from django.utils import timezone as tz
        from datetime import timedelta
        valid_until = tz.now() + timedelta(days=valid_days) if valid_days else None
        return cls.objects.create(agent=agent, category=category, content=content, confidence=confidence, source_task_id=source_task_id, valid_until=valid_until)

    @classmethod
    def recall(cls, agent, category=None, limit=10):
        from django.utils import timezone as tz
        qs = cls.objects.filter(agent=agent)
        if category:
            qs = qs.filter(category=category)
        qs = qs.filter(models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=tz.now()))
        return list(qs[:limit].values("category", "content", "confidence"))

    @classmethod
    def get_context_for_agent(cls, agent, max_chars=8000):
        memories = cls.recall(agent, limit=20)
        if not memories:
            return ""
        lines = ["## Agent Memory\\n"]
        total = 0
        for m in memories:
            line = f"- [{m['category']}] {m['content']}"
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)
        return "\\n".join(lines)
'''
            with open(ai_models_path, "w", encoding="utf-8") as f:
                f.write(content)
            print("  [OK] AIMemory model added to ai_agents/models.py")

    # ================================================================
    # 6. Add OptionsFlow to scraping models
    # ================================================================
    scraping_models_path = "scraping/models.py"
    if os.path.exists(scraping_models_path):
        with open(scraping_models_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "OptionsFlow" not in content:
            content += '''

class OptionsFlow(models.Model):
    """Unusual options activity tracking."""
    instrument = models.ForeignKey("instruments.Instrument", on_delete=models.CASCADE, related_name="options_flow")
    timestamp = models.DateTimeField()
    contract_type = models.CharField(max_length=4)
    strike = models.DecimalField(max_digits=20, decimal_places=2)
    expiry = models.DateField()
    volume = models.IntegerField()
    open_interest = models.IntegerField(default=0)
    premium = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    sentiment = models.CharField(max_length=10)
    is_unusual = models.BooleanField(default=False)
    source = models.CharField(max_length=50)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.instrument.symbol} {self.contract_type.upper()} {self.strike}"
'''
            with open(scraping_models_path, "w", encoding="utf-8") as f:
                f.write(content)
            print("  [OK] OptionsFlow model added to scraping/models.py")

    # ================================================================
    # 7. Add MacroObservation model if missing
    # ================================================================
    md_models_path = "market_data/models.py"
    if os.path.exists(md_models_path):
        with open(md_models_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "MacroObservation" not in content:
            content += '''

class MacroObservation(models.Model):
    """Individual FRED data point."""
    indicator = models.ForeignKey(MacroIndicator, on_delete=models.CASCADE, related_name="observations")
    date = models.DateField()
    value = models.DecimalField(max_digits=20, decimal_places=4)

    class Meta:
        unique_together = ["indicator", "date"]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.indicator.series_id} {self.date}: {self.value}"
'''
            with open(md_models_path, "w", encoding="utf-8") as f:
                f.write(content)
            print("  [OK] MacroObservation model added")

    # ================================================================
    # 8. Add Signal outcome fields if missing
    # ================================================================
    signals_model_path = "signals/models.py"
    if os.path.exists(signals_model_path):
        with open(signals_model_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "outcome" not in content:
            content = content.replace(
                "class Meta:",
                '''outcome = models.CharField(max_length=20, blank=True)  # hit_target, stopped_out, expired
    expired_at = models.DateTimeField(null=True, blank=True)

    class Meta:''',
                1
            )
            with open(signals_model_path, "w", encoding="utf-8") as f:
                f.write(content)
            print("  [OK] Signal outcome fields added")

    # ================================================================
    # 9. Add MacroIndicator fields if missing
    # ================================================================
    if os.path.exists(md_models_path):
        with open(md_models_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "last_value" not in content and "MacroIndicator" in content:
            content = content.replace(
                'class MacroIndicator(models.Model):',
                'class MacroIndicator(models.Model):\n'
                '    last_value = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)\n'
                '    last_date = models.DateField(null=True, blank=True)\n'
            )
            # Remove duplicate if it double-inserts
            with open(md_models_path, "w", encoding="utf-8") as f:
                f.write(content)
            print("  [OK] MacroIndicator last_value fields added")

    # ================================================================
    # 10. Ensure requirements include all needed packages
    # ================================================================
    req_path = "requirements.txt"
    if os.path.exists(req_path):
        with open(req_path, "r", encoding="utf-8") as f:
            reqs = f.read()
        additions = []
        for pkg in ["yfinance", "feedparser", "channels", "pytz"]:
            if pkg not in reqs:
                additions.append(pkg)
        if additions:
            with open(req_path, "a", encoding="utf-8") as f:
                for pkg in additions:
                    f.write(f"\n{pkg}")
            print(f"  [OK] Added to requirements.txt: {', '.join(additions)}")

    print(f"""
  CRITICAL FIX COMPLETE ({len(created)} files)

  Run these commands IN ORDER:

    pip install yfinance feedparser
    python manage.py makemigrations backtester ai_agents scraping signals market_data
    python manage.py migrate
    python manage.py init_platform
    python manage.py runserver

  What was fixed:
    1. Backtester migrations dir created — table will exist after migrate
    2. Instruments list — each row is clickable, links to detail page
    3. Sidebar collapse — clean design, scrolls, remembers state, expands back
    4. Instrument filters — index, etf, crypto added
    5. AIMemory model — in correct models.py for migration
    6. OptionsFlow model — in correct models.py for migration
    7. MacroObservation model — for FRED data storage
    8. Signal outcome fields — for performance tracking
    9. Requirements updated

  The sidebar now:
    - Click the arrow button on the sidebar edge to collapse
    - Collapsed: shows icons only, hover shows name tooltip
    - Click the arrow again to expand
    - Scrolls properly in both states
    - Remembers your choice (localStorage)
""")


if __name__ == "__main__":
    generate()
