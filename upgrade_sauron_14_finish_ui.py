#!/usr/bin/env python
# upgrade_sauron_14_finish_ui.py
#
# Sauron Vision - Upgrade 14: Finish what Upgrade 13 started.
#
# Honest accounting: Upgrade 13 created views and templates but never wired
# them into the existing pages. It also skipped the sentiment chart, the
# strategy wizard's leg picker, the user-facing bot console, and replacing
# profile.html's inline PIN form. This script does all of that.
#
# Prerequisites: upgrades 10, 11, 12, 13 applied.
#
# Run:
#     python upgrade_sauron_14_finish_ui.py            # idempotent
#     python upgrade_sauron_14_finish_ui.py --force    # overwrite
#     python manage.py runserver
#
# What this script does:
#
# A) Wires the metric partials into the EXISTING page templates by inserting
#    a one-line <div hx-get=...> just before the closing {% endblock %} of:
#       templates/dashboard/signals_list.html
#       templates/dashboard/strategies_list.html
#       templates/dashboard/news_feed.html
#       templates/dashboard/backtest_list.html
#       templates/dashboard/portfolio_overview.html
#       templates/dashboard/positions_list.html
#       templates/dashboard/admin_dashboard.html
#    All edits are guarded with a marker so re-runs are no-ops.
#
# B) Replaces the inline PIN form on profile.html with the credentials panel
#    that opens both PIN and password modals.
#
# C) Adds HTMX to base.html if not already present.
#
# D) Adds a sentiment trend chart to the news metrics view (uses NewsItem.
#    ai_sentiment_score that I confirmed exists in your scraping/models.py).
#
# E) Adds instrument leg picker to the strategy wizard (multi-select +
#    per-leg action/weight; saves StrategyLeg rows after Strategy creation).
#
# F) Adds a user-facing bot console page at /bot/console/ (live positions,
#    big PAUSE button, last 10 decisions log with reasons).
#
# G) Upgrades news_metrics view to compute the sentiment trend.
#
# H) Adds a few extra metric cards I should have added the first time:
#    - Signals: setup distribution donut + R-multiple histogram
#    - Strategies: per-strategy P&L bar
#    - News: sentiment gauge

import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FORCE = "--force" in sys.argv


# ============================================================================
# A) PAGE WIRING — insert hx-get divs before {% endblock %}
# ============================================================================

# Each entry: (template_path, marker_to_check, html_to_insert_before_endblock)
PAGE_WIRINGS = [
    (
        "templates/dashboard/signals_list.html",
        "hx-get=\"/htmx/metrics/signals/",
        '\n<div class="sv-metrics-wrapper" '
        'hx-get="/htmx/metrics/signals/" '
        'hx-trigger="load, every 60s" '
        'style="margin-top:32px;"></div>\n',
    ),
    (
        "templates/dashboard/strategies_list.html",
        "hx-get=\"/htmx/metrics/strategies/",
        '\n<div class="sv-metrics-wrapper" '
        'hx-get="/htmx/metrics/strategies/" '
        'hx-trigger="load" '
        'style="margin-top:32px;"></div>\n',
    ),
    (
        "templates/dashboard/news_feed.html",
        "hx-get=\"/htmx/metrics/news/",
        '\n<div class="sv-metrics-wrapper" '
        'hx-get="/htmx/metrics/news/" '
        'hx-trigger="load, every 5m" '
        'style="margin-top:32px;"></div>\n',
    ),
    (
        "templates/dashboard/backtest_list.html",
        "hx-get=\"/htmx/metrics/backtest/",
        '\n<div class="sv-metrics-wrapper" '
        'hx-get="/htmx/metrics/backtest/" '
        'hx-trigger="load" '
        'style="margin-top:32px;"></div>\n',
    ),
    (
        "templates/dashboard/portfolio_overview.html",
        "hx-get=\"/htmx/metrics/portfolio/",
        '\n<div class="sv-metrics-wrapper" '
        'hx-get="/htmx/metrics/portfolio/" '
        'hx-trigger="load, every 60s" '
        'style="margin-top:32px;"></div>\n',
    ),
    (
        "templates/dashboard/positions_list.html",
        "hx-get=\"/htmx/metrics/positions/",
        '\n<div class="sv-metrics-wrapper" '
        'hx-get="/htmx/metrics/positions/" '
        'hx-trigger="load, every 30s" '
        'style="margin-top:32px;"></div>\n',
    ),
    (
        "templates/dashboard/admin_dashboard.html",
        "hx-get=\"/htmx/admin/bots/",
        '\n<div class="sv-metrics-wrapper" '
        'hx-get="/htmx/admin/bots/" '
        'hx-trigger="load, every 30s" '
        'style="margin-top:32px;"></div>\n',
    ),
]


def wire_page(rel_path, marker, snippet):
    """Insert snippet just before the LAST {% endblock %} in the file.

    Idempotent: if marker is already present, skip.
    """
    path = ROOT / rel_path
    if not path.exists():
        return False, f"{rel_path} not found"
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return True, "already wired"

    # Find the last {% endblock %}
    text_n = text.replace("\r\n", "\n")
    last_end = text_n.rfind("{% endblock %}")
    if last_end == -1:
        return False, "no {% endblock %} found"
    new_text = text_n[:last_end] + snippet + text_n[last_end:]
    path.write_text(new_text, encoding="utf-8")
    return True, "wired"


# ============================================================================
# B) PROFILE.HTML — replace inline PIN form with credentials panel
# ============================================================================

def replace_profile_pin_form():
    """Replace the inline change_pin <form>...</form> block in profile.html
    with an include of _profile_credentials.html.

    Idempotent via marker check.
    """
    path = ROOT / "templates" / "dashboard" / "profile.html"
    if not path.exists():
        return False, "profile.html not found"
    text = path.read_text(encoding="utf-8")
    if "_profile_credentials.html" in text:
        return True, "already replaced"

    text_n = text.replace("\r\n", "\n")
    # The form starts with: <form method="post" action="{% url 'change_pin' %}"
    # and ends with </form>. Find both and excise.
    form_start_marker = "<form method=\"post\" action=\"{% url 'change_pin' %}\""
    start = text_n.find(form_start_marker)
    if start == -1:
        return False, "change_pin form not found"
    # Find the matching </form>
    form_end = text_n.find("</form>", start)
    if form_end == -1:
        return False, "form end not found"
    form_end += len("</form>")

    replacement = (
        "{% include \"dashboard/_profile_credentials.html\" %}\n"
        "  <!-- legacy inline PIN form replaced by credentials panel above -->"
    )
    new_text = text_n[:start] + replacement + text_n[form_end:]
    path.write_text(new_text, encoding="utf-8")
    return True, "replaced inline PIN form with credentials panel"


# ============================================================================
# C) BASE.HTML — add HTMX script tag if not present
# ============================================================================

def add_htmx_to_base():
    """Add htmx via CDN in base.html <head> if missing."""
    path = ROOT / "templates" / "base.html"
    if not path.exists():
        return False, "base.html not found"
    text = path.read_text(encoding="utf-8")
    if "htmx.org" in text or "htmx.min.js" in text:
        return True, "htmx already loaded"
    text_n = text.replace("\r\n", "\n")
    htmx_tag = (
        '\n    <script src="https://unpkg.com/htmx.org@1.9.10" '
        'integrity="sha384-D1Kt99CQMDuVetoL1lrYwg5t+9QdHe7NLX/SoJYkXDFfX37iInKRy5xLSi8nO7UC" '
        'crossorigin="anonymous"></script>\n'
    )
    # Insert before </head>
    if "</head>" not in text_n:
        return False, "no </head> tag in base.html"
    new_text = text_n.replace("</head>", htmx_tag + "</head>", 1)
    path.write_text(new_text, encoding="utf-8")
    return True, "added htmx script tag to <head>"


# ============================================================================
# D) UPGRADED news_metrics view — adds sentiment trend
# ============================================================================

F_METRICS_VIEWS_V2 = '''"""Metrics endpoints — v2 with sentiment trend, R-distribution, P&L bars."""
import json
from collections import Counter
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone


# ── Signals ─────────────────────────────────────────────────────────────
@login_required
def signals_metrics(request):
    ctx = {"setups": [], "totals": {}, "chart_data": "{}",
           "setup_dist": "{}", "r_hist": "{}"}
    try:
        from signals.models_smc import SmcSignal
        from signals.performance import setup_performance_summary

        active = SmcSignal.objects.filter(status__in=["ACTIVE", "TRIGGERED"])
        ctx["totals"] = {
            "active": active.count(),
            "long": active.filter(direction="LONG").count(),
            "short": active.filter(direction="SHORT").count(),
            "avg_conviction": round(
                sum(s.conviction or 0 for s in active) / max(active.count(), 1), 1
            ),
        }
        perf = setup_performance_summary(days=30)
        ctx["setups"] = [
            {"name": k, "hit_rate": v["hit_rate"], "expectancy": v["expectancy_r"],
             "n_closed": v["n_closed"], "is_empirical": v["is_empirical"]}
            for k, v in perf.items()
        ]

        # Chart 1: signals per day stacked long/short
        since = timezone.now() - timedelta(days=14)
        recent = SmcSignal.objects.filter(created_at__gte=since)
        per_day = {}
        for s in recent:
            day = s.created_at.date().isoformat()
            per_day.setdefault(day, {"long": 0, "short": 0})
            per_day[day]["long" if s.direction == "LONG" else "short"] += 1
        days_sorted = sorted(per_day.keys())
        ctx["chart_data"] = json.dumps({
            "labels": days_sorted,
            "long": [per_day[d]["long"] for d in days_sorted],
            "short": [per_day[d]["short"] for d in days_sorted],
        })

        # Chart 2: setup distribution donut (active signals)
        setup_counts = Counter(s.setup for s in active)
        ctx["setup_dist"] = json.dumps({
            "labels": list(setup_counts.keys()),
            "values": list(setup_counts.values()),
        })

        # Chart 3: R-multiple histogram from closed signals (90d)
        closed = SmcSignal.objects.filter(
            closed_at__gte=timezone.now() - timedelta(days=90),
            realized_r__isnull=False,
        )
        bins = [-3, -2, -1, 0, 1, 2, 3, 5]
        hist = [0] * (len(bins) - 1)
        for s in closed:
            r = float(s.realized_r)
            for i in range(len(bins) - 1):
                if bins[i] <= r < bins[i + 1]:
                    hist[i] += 1
                    break
        ctx["r_hist"] = json.dumps({
            "labels": [f"{bins[i]} to {bins[i+1]}R" for i in range(len(bins) - 1)],
            "values": hist,
        })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_signals_metrics.html", ctx)


# ── Strategies ──────────────────────────────────────────────────────────
@login_required
def strategies_metrics(request):
    ctx = {"by_status": [], "chart_data": "{}", "totals": {}, "pnl_data": "{}"}
    try:
        from strategies.models import Strategy
        all_strats = Strategy.objects.all()
        status_counts = Counter(s.status for s in all_strats)
        ctx["by_status"] = [{"status": k, "count": v} for k, v in status_counts.items()]
        ctx["totals"] = {
            "total": all_strats.count(),
            "active": status_counts.get("active", 0),
            "proposed": status_counts.get("proposed", 0),
            "completed": status_counts.get("completed", 0),
        }
        ctx["chart_data"] = json.dumps({
            "labels": list(status_counts.keys()),
            "values": list(status_counts.values()),
        })
        # Per-strategy P&L bar (uses any 'realized_pnl' or 'pnl' field if present)
        labels = []
        values = []
        for s in all_strats[:20]:
            pnl = getattr(s, "realized_pnl", None) or getattr(s, "pnl", None) or 0
            try:
                pnl = float(pnl)
            except (ValueError, TypeError):
                pnl = 0
            if pnl != 0:
                labels.append((s.name or f"#{s.id}")[:24])
                values.append(round(pnl, 2))
        ctx["pnl_data"] = json.dumps({"labels": labels, "values": values})
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_strategies_metrics.html", ctx)


# ── News & sentiment ────────────────────────────────────────────────────
@login_required
def news_metrics(request):
    ctx = {"totals": {}, "chart_data": "{}", "sentiment_data": "{}",
           "current_sentiment": None}
    try:
        from scraping.models import NewsItem
        since = timezone.now() - timedelta(days=14)
        # NewsItem may not have published_at; tolerate both
        ts_field = None
        for f in ("published_at", "created_at", "scraped_at", "timestamp"):
            if hasattr(NewsItem, f):
                ts_field = f
                break
        if ts_field is None:
            ctx["totals"]["count_14d"] = 0
            return render(request, "dashboard/_news_metrics.html", ctx)

        items = list(NewsItem.objects.filter(**{f"{ts_field}__gte": since}).order_by(ts_field))
        ctx["totals"]["count_14d"] = len(items)

        per_day = {}
        sentiment_per_day = {}
        for n in items:
            ts = getattr(n, ts_field) or timezone.now()
            day = ts.date().isoformat()
            per_day[day] = per_day.get(day, 0) + 1
            score = getattr(n, "ai_sentiment_score", None)
            if score is not None:
                try:
                    score_f = float(score)
                except (ValueError, TypeError):
                    continue
                sentiment_per_day.setdefault(day, []).append(score_f)

        days_sorted = sorted(per_day.keys())
        ctx["chart_data"] = json.dumps({
            "labels": days_sorted,
            "values": [per_day[d] for d in days_sorted],
        })

        # Sentiment trend: average per day, only days with data
        sent_days = [d for d in days_sorted if d in sentiment_per_day]
        sent_values = [
            round(sum(sentiment_per_day[d]) / len(sentiment_per_day[d]), 3)
            for d in sent_days
        ]
        ctx["sentiment_data"] = json.dumps({
            "labels": sent_days, "values": sent_values,
        })
        if sent_values:
            current = sent_values[-1]
            ctx["current_sentiment"] = current
            ctx["totals"]["sentiment_label"] = (
                "BULLISH" if current > 0.2
                else "BEARISH" if current < -0.2
                else "NEUTRAL"
            )
    except Exception as e:
        ctx["error"] = str(e)
        ctx["totals"]["count_14d"] = 0
    return render(request, "dashboard/_news_metrics.html", ctx)


# ── Backtest ────────────────────────────────────────────────────────────
@login_required
def backtest_metrics(request):
    ctx = {"runs": [], "chart_data": "{}"}
    try:
        from backtester.models_v2 import BacktestRunV2
        recent = BacktestRunV2.objects.all()[:10]
        ctx["runs"] = list(recent)
        if recent:
            latest = recent[0]
            curve = latest.equity_curve or []
            ctx["chart_data"] = json.dumps({
                "labels": [str(p.get("ts", i)) for i, p in enumerate(curve)],
                "equity": [p.get("equity", 0) for p in curve],
                "name": latest.name,
            })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_backtest_metrics.html", ctx)


# ── Portfolio ───────────────────────────────────────────────────────────
@login_required
def portfolio_metrics(request):
    ctx = {"exposure": {}, "chart_data": "{}"}
    try:
        from portfolio.models import Portfolio
        from strategies.portfolio_analyzer import analyze_exposure
        portfolio = Portfolio.objects.filter(user=request.user).first()
        if portfolio:
            exposure = analyze_exposure(portfolio)
            ctx["exposure"] = exposure
            asset_break = exposure.get("by_asset_class", {})
            ctx["chart_data"] = json.dumps({
                "labels": list(asset_break.keys()),
                "values": [round(v * 100, 2) for v in asset_break.values()],
            })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_portfolio_metrics.html", ctx)


# ── Positions ───────────────────────────────────────────────────────────
@login_required
def positions_metrics(request):
    ctx = {"positions": [], "chart_data": "{}"}
    try:
        from portfolio.models import Position, Portfolio
        portfolio = Portfolio.objects.filter(user=request.user).first()
        if portfolio:
            positions = Position.objects.filter(
                portfolio=portfolio, is_open=True
            ).select_related("instrument")[:50]
            ctx["positions"] = list(positions)
            symbols = []
            pnls = []
            for p in positions:
                symbols.append(getattr(p.instrument, "symbol", "?"))
                pnls.append(float(getattr(p, "unrealized_pnl", 0) or 0))
            ctx["chart_data"] = json.dumps({"labels": symbols, "values": pnls})
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_positions_metrics.html", ctx)
'''


# ============================================================================
# E) UPGRADED signals metrics template — 3 charts now
# ============================================================================

F_TPL_SIGNALS_V2 = '''{% include "_chart_assets.html" %}
<div class="signals-metrics">
  <div class="sv-section-title">Signal overview</div>
  <div class="sv-metrics-grid">
    <div class="sv-metric-card">
      <div class="sv-metric-label">Active</div>
      <div class="sv-metric-value">{{ totals.active|default:"0" }}</div>
    </div>
    <div class="sv-metric-card">
      <div class="sv-metric-label">Long</div>
      <div class="sv-metric-value up">{{ totals.long|default:"0" }}</div>
    </div>
    <div class="sv-metric-card">
      <div class="sv-metric-label">Short</div>
      <div class="sv-metric-value down">{{ totals.short|default:"0" }}</div>
    </div>
    <div class="sv-metric-card">
      <div class="sv-metric-label">Avg conviction</div>
      <div class="sv-metric-value">{{ totals.avg_conviction|default:"0" }}/100</div>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:2fr 1fr;gap:20px;">
    <div>
      <div class="sv-section-title">Signals per day (14d)</div>
      <div class="sv-chart-container"><canvas id="signals-daily-chart"></canvas></div>
    </div>
    <div>
      <div class="sv-section-title">Setup mix (active)</div>
      <div class="sv-chart-container"><canvas id="signals-setup-chart"></canvas></div>
    </div>
  </div>

  <div class="sv-section-title">R-multiple distribution (closed, 90d)</div>
  <div class="sv-chart-container short"><canvas id="signals-r-hist"></canvas></div>

  <div class="sv-section-title">Setup performance - last 30 days</div>
  {% if setups %}
    <table class="sv-perf-table">
      <thead>
        <tr><th>Setup</th><th>Hit rate</th><th>Expectancy</th><th>n closed</th><th>Source</th></tr>
      </thead>
      <tbody>
        {% for s in setups %}
          <tr>
            <td>{{ s.name }}</td>
            <td>{% if s.hit_rate %}{{ s.hit_rate|floatformat:2 }}{% else %}-{% endif %}</td>
            <td>{% if s.expectancy %}{{ s.expectancy|floatformat:2 }}R{% else %}-{% endif %}</td>
            <td>{{ s.n_closed }}</td>
            <td>{% if s.is_empirical %}empirical{% else %}fallback{% endif %}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p style="color:var(--text-muted);">No closed signals yet.</p>
  {% endif %}
</div>

<style>
.sv-perf-table { width: 100%; border-collapse: collapse;
                 font-family: var(--font-mono); font-size: 0.85rem; }
.sv-perf-table th, .sv-perf-table td { padding: 8px 10px; text-align: left;
                                        border-bottom: 1px solid var(--border); }
.sv-perf-table th { color: var(--text-muted); text-transform: uppercase;
                    font-size: 0.7rem; letter-spacing: 0.05em; }
</style>

<script>
(function() {
  const data = {{ chart_data|safe }};
  const setupDist = {{ setup_dist|safe }};
  const rHist = {{ r_hist|safe }};
  const COLORS = window.SAURON_CHART_COLORS;

  if (data.labels && data.labels.length) {
    const ctx = document.getElementById("signals-daily-chart");
    if (window._signalsDailyChart) window._signalsDailyChart.destroy();
    window._signalsDailyChart = new Chart(ctx, {
      type: "bar",
      data: { labels: data.labels, datasets: [
        { label: "Long", data: data.long,
          backgroundColor: COLORS.accentDim, borderColor: COLORS.accent, borderWidth: 1 },
        { label: "Short", data: data.short,
          backgroundColor: COLORS.redDim, borderColor: COLORS.red, borderWidth: 1 },
      ]},
      options: { responsive: true, maintainAspectRatio: false,
                 scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } },
                 plugins: { legend: { position: "top" } } },
    });
  }

  if (setupDist.labels && setupDist.labels.length) {
    const ctx = document.getElementById("signals-setup-chart");
    if (window._signalsSetupChart) window._signalsSetupChart.destroy();
    const colors = [COLORS.accent, COLORS.gold, COLORS.blue, COLORS.purple,
                    COLORS.red, "#666", "#aaa", "#0a8"];
    window._signalsSetupChart = new Chart(ctx, {
      type: "doughnut",
      data: { labels: setupDist.labels, datasets: [{ data: setupDist.values,
              backgroundColor: setupDist.labels.map((_, i) => colors[i % colors.length]),
              borderColor: COLORS.border, borderWidth: 2 }]},
      options: { responsive: true, maintainAspectRatio: false,
                 plugins: { legend: { position: "right", labels: { font: { size: 10 } } } } },
    });
  }

  if (rHist.labels && rHist.labels.length) {
    const ctx = document.getElementById("signals-r-hist");
    if (window._signalsRHist) window._signalsRHist.destroy();
    const barColors = rHist.labels.map(label => {
      const lower = parseFloat(label.split(" ")[0]);
      return lower >= 0 ? COLORS.accent : COLORS.red;
    });
    window._signalsRHist = new Chart(ctx, {
      type: "bar",
      data: { labels: rHist.labels, datasets: [{ data: rHist.values,
              backgroundColor: barColors, borderWidth: 0 }]},
      options: { responsive: true, maintainAspectRatio: false,
                 plugins: { legend: { display: false } },
                 scales: { y: { beginAtZero: true } } },
    });
  }
})();
</script>
'''


# ============================================================================
# F) UPGRADED strategies metrics template — adds P&L bar
# ============================================================================

F_TPL_STRATEGIES_V2 = '''{% include "_chart_assets.html" %}
<div class="strategies-metrics">
  <div class="sv-section-title">Strategy overview</div>
  <div class="sv-metrics-grid">
    <div class="sv-metric-card">
      <div class="sv-metric-label">Total</div>
      <div class="sv-metric-value">{{ totals.total|default:"0" }}</div>
    </div>
    <div class="sv-metric-card">
      <div class="sv-metric-label">Active</div>
      <div class="sv-metric-value up">{{ totals.active|default:"0" }}</div>
    </div>
    <div class="sv-metric-card">
      <div class="sv-metric-label">Proposed</div>
      <div class="sv-metric-value">{{ totals.proposed|default:"0" }}</div>
    </div>
    <div class="sv-metric-card">
      <div class="sv-metric-label">Completed</div>
      <div class="sv-metric-value">{{ totals.completed|default:"0" }}</div>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 2fr;gap:20px;">
    <div>
      <div class="sv-section-title">Status mix</div>
      <div class="sv-chart-container"><canvas id="strategies-status-chart"></canvas></div>
    </div>
    <div>
      <div class="sv-section-title">P&amp;L per strategy</div>
      <div class="sv-chart-container"><canvas id="strategies-pnl-chart"></canvas></div>
    </div>
  </div>

  <div style="margin-top:24px;">
    <a href="/strategies/new/" class="btn btn-primary">+ Create new strategy</a>
  </div>
</div>

<script>
(function() {
  const data = {{ chart_data|safe }};
  const pnlData = {{ pnl_data|safe }};
  const COLORS = window.SAURON_CHART_COLORS;

  if (data.labels && data.labels.length) {
    const ctx = document.getElementById("strategies-status-chart");
    if (window._stratStatusChart) window._stratStatusChart.destroy();
    const colors = [COLORS.accent, COLORS.gold, COLORS.blue, COLORS.purple, COLORS.red, "#666"];
    window._stratStatusChart = new Chart(ctx, {
      type: "doughnut",
      data: { labels: data.labels, datasets: [{ data: data.values,
              backgroundColor: data.labels.map((_, i) => colors[i % colors.length]),
              borderColor: COLORS.border, borderWidth: 2 }]},
      options: { responsive: true, maintainAspectRatio: false,
                 plugins: { legend: { position: "right" } } },
    });
  }

  if (pnlData.labels && pnlData.labels.length) {
    const ctx = document.getElementById("strategies-pnl-chart");
    if (window._stratPnlChart) window._stratPnlChart.destroy();
    const colors = pnlData.values.map(v => v >= 0 ? COLORS.accent : COLORS.red);
    window._stratPnlChart = new Chart(ctx, {
      type: "bar",
      data: { labels: pnlData.labels, datasets: [{ data: pnlData.values,
              backgroundColor: colors, borderWidth: 0 }]},
      options: { responsive: true, maintainAspectRatio: false, indexAxis: "y",
                 plugins: { legend: { display: false } } },
    });
  } else {
    const ctx = document.getElementById("strategies-pnl-chart");
    if (ctx) ctx.parentElement.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:40px;">No P&amp;L data yet.</p>';
  }
})();
</script>
'''


# ============================================================================
# G) UPGRADED news metrics template — adds sentiment chart + gauge
# ============================================================================

F_TPL_NEWS_V2 = '''{% include "_chart_assets.html" %}
<div class="news-metrics">
  <div class="sv-section-title">News &amp; sentiment</div>
  <div class="sv-metrics-grid">
    <div class="sv-metric-card">
      <div class="sv-metric-label">Articles (14d)</div>
      <div class="sv-metric-value">{{ totals.count_14d|default:"0" }}</div>
    </div>
    <div class="sv-metric-card">
      <div class="sv-metric-label">Current sentiment</div>
      <div class="sv-metric-value {% if current_sentiment > 0.2 %}up{% elif current_sentiment < -0.2 %}down{% endif %}">
        {{ totals.sentiment_label|default:"-" }}
      </div>
    </div>
    {% if current_sentiment != None %}
    <div class="sv-metric-card">
      <div class="sv-metric-label">Score</div>
      <div class="sv-metric-value">{{ current_sentiment|floatformat:2 }}</div>
    </div>
    {% endif %}
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
    <div>
      <div class="sv-section-title">Volume per day</div>
      <div class="sv-chart-container"><canvas id="news-volume-chart"></canvas></div>
    </div>
    <div>
      <div class="sv-section-title">Sentiment trend</div>
      <div class="sv-chart-container"><canvas id="news-sentiment-chart"></canvas></div>
    </div>
  </div>
</div>

<script>
(function() {
  const data = {{ chart_data|safe }};
  const sent = {{ sentiment_data|safe }};
  const COLORS = window.SAURON_CHART_COLORS;

  if (data.labels && data.labels.length) {
    const ctx = document.getElementById("news-volume-chart");
    if (window._newsVolChart) window._newsVolChart.destroy();
    window._newsVolChart = new Chart(ctx, {
      type: "line",
      data: { labels: data.labels, datasets: [{
        label: "Articles per day", data: data.values,
        borderColor: COLORS.accent, backgroundColor: COLORS.accentDim,
        tension: 0.3, fill: true,
      }]},
      options: { responsive: true, maintainAspectRatio: false,
                 plugins: { legend: { display: false } } },
    });
  }

  if (sent.labels && sent.labels.length) {
    const ctx = document.getElementById("news-sentiment-chart");
    if (window._newsSentChart) window._newsSentChart.destroy();
    window._newsSentChart = new Chart(ctx, {
      type: "line",
      data: { labels: sent.labels, datasets: [{
        label: "Avg sentiment", data: sent.values,
        borderColor: COLORS.gold, backgroundColor: "rgba(216, 176, 32, 0.18)",
        tension: 0.3, fill: true,
      }]},
      options: { responsive: true, maintainAspectRatio: false,
                 plugins: { legend: { display: false } },
                 scales: { y: { suggestedMin: -1, suggestedMax: 1,
                                ticks: { callback: v => v.toFixed(1) } } } },
    });
  } else {
    const ctx = document.getElementById("news-sentiment-chart");
    if (ctx) ctx.parentElement.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:40px;">No AI-scored sentiment yet.</p>';
  }
})();
</script>
'''


# ============================================================================
# H) UPGRADED strategy wizard view + template — instrument legs
# ============================================================================

F_WIZARD_VIEW_V2 = '''"""Strategy create wizard with instrument leg picker."""
import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST


@login_required
def strategy_wizard(request):
    """Render the wizard with available instruments for the leg picker."""
    instruments = []
    try:
        from instruments.models import Instrument
        instruments = list(
            Instrument.objects.filter(is_active=True)
            .order_by("symbol")
            .values("id", "symbol", "name")[:200]
        )
    except Exception:
        pass
    return render(request, "dashboard/_strategy_wizard.html", {
        "instruments": instruments,
        "instruments_json": json.dumps(instruments),
    })


@login_required
@require_POST
def strategy_wizard_save(request):
    """Persist Strategy + StrategyLeg rows from wizard form data."""
    try:
        from strategies.models import Strategy, StrategyLeg
        from instruments.models import Instrument
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"strategies module: {e}"})

    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()
    horizon = request.POST.get("time_horizon", "swing")
    max_alloc = request.POST.get("max_portfolio_allocation_pct", "10")
    max_loss = request.POST.get("max_loss_pct", "2")
    legs_json = request.POST.get("legs_json", "[]")

    if not name:
        return JsonResponse({"ok": False, "error": "Name is required."})

    try:
        legs = json.loads(legs_json)
    except Exception:
        legs = []

    try:
        s = Strategy.objects.create(
            name=name,
            description=description,
            time_horizon=horizon,
            status="proposed",
            max_portfolio_allocation_pct=float(max_alloc or 10),
            max_loss_pct=float(max_loss or 2),
            ai_reasoning="Created via wizard",
        )
        legs_created = 0
        for leg in legs:
            try:
                inst = Instrument.objects.get(id=int(leg.get("instrument_id")))
                StrategyLeg.objects.create(
                    strategy=s,
                    instrument=inst,
                    action=leg.get("action", "long"),
                    weight=float(leg.get("weight", 1.0)),
                )
                legs_created += 1
            except Exception:
                continue
        return JsonResponse({
            "ok": True,
            "id": s.id,
            "legs_created": legs_created,
            "redirect": f"/strategies/{s.id}/",
        })
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})
'''


F_TPL_WIZARD_V2 = '''{% extends "base.html" %}
{% block title %}New Strategy - Sauron Vision{% endblock %}
{% block content %}
<div class="container" style="max-width:780px;margin:40px auto;">
  <h2 style="font-family:var(--font-heading);color:var(--accent);text-transform:uppercase;letter-spacing:0.1em;">
    Create new strategy
  </h2>
  <p style="color:var(--text-secondary);">Define a strategy framework and add legs for the instruments it covers.</p>

  <form id="wizard-form" onsubmit="event.preventDefault(); submitWizard();">
    {% csrf_token %}

    <div class="input-group">
      <label class="input-label">Strategy name</label>
      <input type="text" name="name" class="input" required placeholder="e.g. BTC dip-buy with hedge">
    </div>
    <div class="input-group">
      <label class="input-label">Description / thesis</label>
      <textarea name="description" class="input" rows="4" placeholder="Why does this trade make sense now?"></textarea>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
      <div class="input-group">
        <label class="input-label">Time horizon</label>
        <select name="time_horizon" class="input">
          <option value="scalp">Scalp</option>
          <option value="intraday">Intraday</option>
          <option value="swing" selected>Swing</option>
          <option value="position">Position</option>
        </select>
      </div>
      <div class="input-group">
        <label class="input-label">Max allocation (%)</label>
        <input type="number" name="max_portfolio_allocation_pct" class="input" value="10" min="0" max="100" step="0.5">
      </div>
    </div>
    <div class="input-group">
      <label class="input-label">Max loss per trade (%)</label>
      <input type="number" name="max_loss_pct" class="input" value="2" min="0" max="20" step="0.5">
    </div>

    <div class="sv-section-title" style="margin-top:24px;">Legs</div>
    <p style="color:var(--text-muted);font-size:0.85rem;">Add the instruments this strategy will trade. Each leg has a direction and a weight.</p>

    <div id="legs-list" style="margin-bottom:12px;"></div>

    <div style="display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:8px;align-items:end;">
      <div>
        <label class="input-label">Instrument</label>
        <select id="leg-instrument" class="input">
          <option value="">-- select --</option>
          {% for i in instruments %}
            <option value="{{ i.id }}">{{ i.symbol }}{% if i.name %} ({{ i.name|truncatechars:30 }}){% endif %}</option>
          {% endfor %}
        </select>
      </div>
      <div>
        <label class="input-label">Action</label>
        <select id="leg-action" class="input">
          <option value="long">Long</option>
          <option value="short">Short</option>
          <option value="hedge">Hedge</option>
        </select>
      </div>
      <div>
        <label class="input-label">Weight</label>
        <input type="number" id="leg-weight" class="input" value="1.0" step="0.1" min="0">
      </div>
      <div>
        <button type="button" class="btn" onclick="addLeg()">Add leg</button>
      </div>
    </div>

    <input type="hidden" name="legs_json" id="legs-json" value="[]">

    <div id="wizard-error" style="color:var(--accent-red);font-size:0.85rem;margin:16px 0;display:none;"></div>
    <div style="display:flex;gap:12px;margin-top:24px;">
      <button type="submit" class="btn btn-primary">Create strategy</button>
      <a href="/strategies/" class="btn">Cancel</a>
    </div>
  </form>
</div>

<style>
.leg-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr auto;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 6px;
  font-family: var(--font-mono);
  font-size: 0.85rem;
  align-items: center;
}
.leg-row__remove {
  background: none; border: 1px solid var(--border);
  color: var(--accent-red); cursor: pointer; padding: 4px 8px;
  border-radius: 3px; font-size: 0.8rem;
}
</style>

<script>
const SV_INSTRUMENTS = {{ instruments_json|safe }};
const SV_LEGS = [];

function renderLegs() {
  const list = document.getElementById("legs-list");
  list.innerHTML = "";
  SV_LEGS.forEach((leg, i) => {
    const inst = SV_INSTRUMENTS.find(x => x.id == leg.instrument_id);
    const row = document.createElement("div");
    row.className = "leg-row";
    row.innerHTML = `
      <span>${inst ? inst.symbol : "?"}</span>
      <span style="color:${leg.action === 'long' ? 'var(--accent)' : leg.action === 'short' ? 'var(--accent-red)' : 'var(--accent-gold)'};">
        ${leg.action.toUpperCase()}
      </span>
      <span>${leg.weight}</span>
      <button type="button" class="leg-row__remove" onclick="removeLeg(${i})">Remove</button>
    `;
    list.appendChild(row);
  });
  document.getElementById("legs-json").value = JSON.stringify(SV_LEGS);
}

function addLeg() {
  const id = document.getElementById("leg-instrument").value;
  const action = document.getElementById("leg-action").value;
  const weight = parseFloat(document.getElementById("leg-weight").value || "1");
  if (!id) return;
  SV_LEGS.push({ instrument_id: parseInt(id), action, weight });
  renderLegs();
  document.getElementById("leg-instrument").value = "";
}

function removeLeg(i) {
  SV_LEGS.splice(i, 1);
  renderLegs();
}

async function submitWizard() {
  const form = document.getElementById("wizard-form");
  const data = new FormData(form);
  const errEl = document.getElementById("wizard-error");
  errEl.style.display = "none";
  try {
    const r = await fetch("/strategies/new/save/", {
      method: "POST", body: data,
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    const j = await r.json();
    if (j.ok) {
      window.location = j.redirect || "/strategies/";
    } else {
      errEl.textContent = j.error || "Failed to create strategy.";
      errEl.style.display = "block";
    }
  } catch (e) {
    errEl.textContent = "Network error.";
    errEl.style.display = "block";
  }
}

window.addLeg = addLeg;
window.removeLeg = removeLeg;
window.submitWizard = submitWizard;
</script>
{% endblock %}
'''


# ============================================================================
# I) USER-FACING BOT CONSOLE — view + template + URL
# ============================================================================

F_BOT_CONSOLE_VIEW = '''"""User-facing bot console: live positions + pause + decisions log."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST


@login_required
def bot_console(request):
    """Render the user's bot console page."""
    ctx = {
        "config": None, "open_trades": [], "recent_trades": [],
        "heartbeat": None, "shadow": False, "circuit": "",
    }
    try:
        cfg = request.user.bot_config
    except Exception:
        cfg = None
    if cfg:
        ctx["config"] = cfg
        try:
            ctx["open_trades"] = list(cfg.trades.filter(status="OPEN")[:20])
            ctx["recent_trades"] = list(cfg.trades.filter(status="CLOSED").order_by("-closed_at")[:10])
        except Exception:
            pass
        try:
            from bot_program.engine.heartbeat import heartbeat_age_seconds
            ctx["heartbeat"] = heartbeat_age_seconds(cfg)
        except Exception:
            pass
        try:
            from bot_program.engine.shadow import is_shadow_mode
            ctx["shadow"] = is_shadow_mode(cfg)
        except Exception:
            pass
        try:
            ctx["circuit"] = cfg.circuit_state.halt_reason or ""
        except Exception:
            pass
    return render(request, "dashboard/bot_console.html", ctx)


@login_required
@require_POST
def bot_pause(request):
    """Toggle the user's bot enabled flag (the big PAUSE/RESUME button)."""
    try:
        cfg = request.user.bot_config
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"no config: {e}"})
    cfg.enabled = not cfg.enabled
    cfg.save(update_fields=["enabled"])
    return JsonResponse({"ok": True, "enabled": cfg.enabled})
'''


F_TPL_BOT_CONSOLE = '''{% extends "base.html" %}
{% block title %}Bot Console - Sauron Vision{% endblock %}
{% block content %}
<div class="container" style="max-width:1100px;margin:30px auto;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;">
    <h2 style="font-family:var(--font-heading);color:var(--accent);text-transform:uppercase;letter-spacing:0.1em;margin:0;">
      Bot Console
    </h2>
    {% if config %}
      <button id="pause-btn" class="btn {% if config.enabled %}btn-danger{% else %}btn-primary{% endif %}"
              onclick="togglePause()" style="font-size:1.1rem;padding:14px 28px;">
        {% if config.enabled %}\u23f8  PAUSE BOT{% else %}\u25b6  RESUME BOT{% endif %}
      </button>
    {% endif %}
  </div>

  {% if not config %}
    <div class="empty-state">
      <p>No bot configured. Create one from the Bot Program page.</p>
    </div>
  {% else %}
    <div class="sv-metrics-grid">
      <div class="sv-metric-card">
        <div class="sv-metric-label">Status</div>
        <div class="sv-metric-value {% if config.enabled %}up{% else %}down{% endif %}">
          {% if config.enabled %}RUNNING{% else %}PAUSED{% endif %}
        </div>
      </div>
      <div class="sv-metric-card">
        <div class="sv-metric-label">Mode</div>
        <div class="sv-metric-value">{{ config.mode|upper }}</div>
      </div>
      <div class="sv-metric-card">
        <div class="sv-metric-label">Market</div>
        <div class="sv-metric-value">{{ config.market_type|upper }}</div>
      </div>
      <div class="sv-metric-card">
        <div class="sv-metric-label">Heartbeat</div>
        <div class="sv-metric-value">{% if heartbeat %}{{ heartbeat|floatformat:0 }}s{% else %}-{% endif %}</div>
      </div>
      <div class="sv-metric-card">
        <div class="sv-metric-label">Open trades</div>
        <div class="sv-metric-value">{{ open_trades|length }}</div>
      </div>
      {% if shadow %}
      <div class="sv-metric-card">
        <div class="sv-metric-label">Shadow mode</div>
        <div class="sv-metric-value" style="color:var(--accent-gold);">ACTIVE</div>
      </div>
      {% endif %}
      {% if circuit %}
      <div class="sv-metric-card">
        <div class="sv-metric-label">Circuit</div>
        <div class="sv-metric-value down">{{ circuit }}</div>
      </div>
      {% endif %}
    </div>

    <div class="sv-section-title">Open positions</div>
    {% if open_trades %}
      <table class="sv-perf-table">
        <thead>
          <tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th>
              <th>Stop</th><th>Target</th><th>Score</th><th>Reason</th><th>Opened</th></tr>
        </thead>
        <tbody>
          {% for t in open_trades %}
            <tr>
              <td>{{ t.symbol }}</td>
              <td class="{% if t.side == 'BUY' %}up{% else %}down{% endif %}">{{ t.side }}</td>
              <td>{{ t.qty }}</td>
              <td>{{ t.entry_price|floatformat:4 }}</td>
              <td>{{ t.stop_loss|floatformat:4 }}</td>
              <td>{{ t.take_profit|floatformat:4 }}</td>
              <td>{{ t.composite_score|floatformat:2 }}</td>
              <td style="font-size:0.75rem;color:var(--text-muted);">{{ t.reason|truncatechars:50 }}</td>
              <td style="font-size:0.75rem;">{{ t.opened_at|date:"M d H:i" }}</td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    {% else %}
      <p style="color:var(--text-muted);">No open positions.</p>
    {% endif %}

    <div class="sv-section-title">Last 10 closed trades</div>
    {% if recent_trades %}
      <table class="sv-perf-table">
        <thead>
          <tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th>
              <th>P&amp;L</th><th>Reason</th><th>Closed</th></tr>
        </thead>
        <tbody>
          {% for t in recent_trades %}
            <tr>
              <td>{{ t.symbol }}</td>
              <td>{{ t.side }}</td>
              <td>{{ t.entry_price|floatformat:4 }}</td>
              <td>{{ t.exit_price|floatformat:4 }}</td>
              <td class="{% if t.pnl_usdt > 0 %}up{% else %}down{% endif %}">{{ t.pnl_usdt|floatformat:2 }}</td>
              <td style="font-size:0.75rem;color:var(--text-muted);">{{ t.reason|truncatechars:60 }}</td>
              <td style="font-size:0.75rem;">{{ t.closed_at|date:"M d H:i" }}</td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    {% else %}
      <p style="color:var(--text-muted);">No closed trades yet.</p>
    {% endif %}
  {% endif %}
</div>

<style>
.sv-perf-table { width: 100%; border-collapse: collapse;
                 font-family: var(--font-mono); font-size: 0.85rem; margin-bottom: 24px; }
.sv-perf-table th, .sv-perf-table td { padding: 8px 10px; text-align: left;
                                        border-bottom: 1px solid var(--border); }
.sv-perf-table th { color: var(--text-muted); text-transform: uppercase;
                    font-size: 0.7rem; letter-spacing: 0.05em; }
.up { color: var(--accent); } .down { color: var(--accent-red); }
.btn-danger { background: var(--accent-red); color: white;
              border: 1px solid var(--accent-red); }
.btn-danger:hover { background: #b02020; }
</style>

<script>
function getCsrf() {
  const m = document.cookie.match(/csrftoken=([^;]+)/);
  return m ? m[1] : "";
}
async function togglePause() {
  if (!confirm("Are you sure you want to toggle the bot?")) return;
  try {
    const r = await fetch("/bot/console/pause/", {
      method: "POST", headers: { "X-CSRFToken": getCsrf() },
    });
    const j = await r.json();
    if (j.ok) location.reload();
    else alert("Failed: " + j.error);
  } catch (e) {
    alert("Network error: " + e);
  }
}
window.togglePause = togglePause;
</script>
{% endblock %}
'''


# ============================================================================
# Files to write
# ============================================================================
FILES = {
    # Replaces upgrade-13 versions with v2 (more charts + sentiment)
    "dashboard/views_metrics.py":                       F_METRICS_VIEWS_V2,
    "dashboard/views_strategy_wizard.py":               F_WIZARD_VIEW_V2,
    "templates/dashboard/_signals_metrics.html":        F_TPL_SIGNALS_V2,
    "templates/dashboard/_strategies_metrics.html":     F_TPL_STRATEGIES_V2,
    "templates/dashboard/_news_metrics.html":           F_TPL_NEWS_V2,
    "templates/dashboard/_strategy_wizard.html":        F_TPL_WIZARD_V2,

    # New: bot console
    "dashboard/views_bot_console.py":                   F_BOT_CONSOLE_VIEW,
    "templates/dashboard/bot_console.html":             F_TPL_BOT_CONSOLE,
}


# Files we always overwrite because they're known upgrade-13 outputs we're updating
ALWAYS_OVERWRITE = {
    "dashboard/views_metrics.py",
    "dashboard/views_strategy_wizard.py",
    "templates/dashboard/_signals_metrics.html",
    "templates/dashboard/_strategies_metrics.html",
    "templates/dashboard/_news_metrics.html",
    "templates/dashboard/_strategy_wizard.html",
}


# ============================================================================
# URL append for bot console
# ============================================================================
def add_bot_console_urls():
    path = ROOT / "dashboard" / "urls.py"
    if not path.exists():
        return False, "dashboard/urls.py not found"
    text = path.read_text(encoding="utf-8")
    if "views_bot_console" in text:
        return True, "already wired"
    text_n = text.replace("\r\n", "\n")

    import_line = "from .views_bot_console import bot_console, bot_pause\n"
    new_paths = (
        '    path("bot/console/", bot_console, name="bot_console"),\n'
        '    path("bot/console/pause/", bot_pause, name="bot_pause"),\n'
        ']'
    )

    if "from .views_bot_console" not in text_n:
        # Insert after the strategy wizard import line if present, else after "from . import views"
        if "from .views_strategy_wizard" in text_n:
            text_n = text_n.replace(
                "from .views_strategy_wizard import strategy_wizard, strategy_wizard_save",
                "from .views_strategy_wizard import strategy_wizard, strategy_wizard_save\n" + import_line.rstrip(),
            )
        else:
            text_n = text_n.replace(
                "from . import views",
                "from . import views\n" + import_line.rstrip(),
                1,
            )

    if text_n.rstrip().endswith("]"):
        text_n = text_n.rstrip()[:-1] + new_paths + "\n"
    else:
        return False, "urls.py doesn't end with ']'"

    path.write_text(text_n, encoding="utf-8")
    return True, "added bot console routes"


# ============================================================================
# Runner
# ============================================================================
def write_files():
    for rel, content in FILES.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        is_always = rel in ALWAYS_OVERWRITE
        if path.exists() and not FORCE and not is_always:
            existing = path.read_text(encoding="utf-8")
            if existing.strip() == content.strip():
                print(f"  OK   (unchanged): {rel}")
                continue
            print(f"  SKIP (exists, --force to overwrite): {rel}")
            continue
        if is_always and path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing.strip() == content.strip():
                print(f"  OK   (unchanged): {rel}")
                continue
        path.write_text(content, encoding="utf-8")
        print(f"  WROTE: {rel}")


def wire_pages():
    print()
    print("[wiring metric partials into existing page templates]")
    for rel, marker, snippet in PAGE_WIRINGS:
        try:
            ok, msg = wire_page(rel, marker, snippet)
            tag = "OK" if ok else "WARN"
            print(f"  {tag}: {rel} -- {msg}")
        except Exception as e:
            print(f"  ERROR: {rel} -- {e}")


def run_modifications():
    print()
    print("[modifications to other existing files]")
    for label, fn in [
        ("templates/base.html", add_htmx_to_base),
        ("templates/dashboard/profile.html", replace_profile_pin_form),
        ("dashboard/urls.py (bot console)", add_bot_console_urls),
    ]:
        try:
            ok, msg = fn()
            tag = "OK" if ok else "WARN"
            print(f"  {tag}: {label} -- {msg}")
        except Exception as e:
            print(f"  ERROR: {label} -- {e}")


def main():
    print("=" * 72)
    print("  Sauron Vision - Upgrade 14: Finish UI wiring + missing pieces")
    print("=" * 72)
    print()
    print("[1/3] Writing files (replaces upgrade-13 versions)...")
    write_files()
    wire_pages()
    run_modifications()
    print()
    print("=" * 72)
    print("  DONE.")
    print("=" * 72)
    print()
    print("  Restart the dev server:  python manage.py runserver")
    print()
    print("  Visit:")
    print("    /signals/                - now shows enriched metrics + 3 charts")
    print("    /strategies/             - status mix + per-strategy P&L")
    print("    /strategies/new/         - wizard with leg picker")
    print("    /news/                   - volume + sentiment trend + gauge")
    print("    /backtest/               - equity curve + run table")
    print("    /portfolio/              - exposure cards + asset class pie")
    print("    /positions/              - PnL bars + position table")
    print("    /admin-dashboard/        - bot control panel auto-refreshes")
    print("    /bot/console/            - your personal bot console")
    print("    /profile/                - PIN + password modal buttons")
    print()


if __name__ == "__main__":
    main()
