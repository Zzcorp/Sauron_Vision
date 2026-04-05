#!/usr/bin/env python3
"""
SAURON VISION — Patch v4.1
Admin panel start/stop controls for scrapers, agents, and the entire platform.
Run inside sauron_vision/ directory.
"""
import os

def create_file(path, content=""):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path

def append_if_missing(path, marker, text):
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if marker in content:
        return False
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
    return True


def generate():
    created = []

    # ================================================================
    # 1. PLATFORM CONTROL MODEL — on/off for every component
    # ================================================================

    created.append(create_file("core/platform_control.py", '''"""Platform control — start/stop scrapers, agents, and pipeline components."""
from django.db import models
from django.utils import timezone


class PlatformComponent(models.Model):
    """Each row represents a controllable component of the platform."""

    CATEGORY_CHOICES = [
        ("scraper", "Data Scraper"),
        ("agent", "AI Agent"),
        ("pipeline", "Data Pipeline"),
        ("system", "System"),
    ]

    key = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=300, blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)

    is_enabled = models.BooleanField(default=False)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=20, blank=True)  # "success", "error", "skipped"
    last_message = models.CharField(max_length=500, blank=True)
    run_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        status = "ON" if self.is_enabled else "OFF"
        return f"[{status}] {self.name}"

    def mark_run(self, success=True, message=""):
        self.last_run_at = timezone.now()
        self.last_status = "success" if success else "error"
        self.last_message = message[:500]
        self.run_count += 1
        if not success:
            self.error_count += 1
        self.save(update_fields=["last_run_at", "last_status", "last_message", "run_count", "error_count", "updated_at"])


def is_component_enabled(key: str) -> bool:
    """Check if a platform component is enabled. Returns False if not found."""
    try:
        return PlatformComponent.objects.get(key=key).is_enabled
    except PlatformComponent.DoesNotExist:
        return False


def get_component(key: str):
    """Get a component by key, or None."""
    try:
        return PlatformComponent.objects.get(key=key)
    except PlatformComponent.DoesNotExist:
        return None


# ── Default components to register ───────────────────────
DEFAULT_COMPONENTS = [
    # System
    {"key": "platform_master", "name": "Platform Master Switch", "description": "Global kill switch — disables ALL automated tasks", "category": "system"},

    # Scrapers
    {"key": "scraper_live_quotes", "name": "Live Quotes Fetcher", "description": "Fetch real-time price quotes for watchlist (every 60s)", "category": "scraper"},
    {"key": "scraper_forex", "name": "Forex Quotes", "description": "Fetch forex pair quotes (every 2 min)", "category": "scraper"},
    {"key": "scraper_commodities", "name": "Commodity Quotes", "description": "Fetch commodity prices (every 5 min)", "category": "scraper"},
    {"key": "scraper_news", "name": "Breaking News", "description": "Fetch news from APIs and RSS (every 3 min)", "category": "scraper"},
    {"key": "scraper_sentiment", "name": "Social Sentiment", "description": "Reddit, StockTwits sentiment (every 30 min)", "category": "scraper"},
    {"key": "scraper_calendar", "name": "Economic Calendar", "description": "Check upcoming economic events (every 30 min)", "category": "scraper"},
    {"key": "scraper_finviz", "name": "FinViz Screener", "description": "Stock screener data (every 1 hour)", "category": "scraper"},
    {"key": "scraper_tradingview", "name": "TradingView Ideas", "description": "Community ideas and technicals (every 6 hours)", "category": "scraper"},
    {"key": "scraper_fred", "name": "FRED Macro Data", "description": "Federal Reserve economic data (every 4 hours)", "category": "scraper"},
    {"key": "scraper_eod", "name": "EOD Price History", "description": "End-of-day OHLCV for full universe (daily 22:30 UTC)", "category": "scraper"},
    {"key": "scraper_sec", "name": "SEC Filings", "description": "13F and Form 4 filings (daily 02:00 UTC)", "category": "scraper"},
    {"key": "scraper_cot", "name": "COT Reports", "description": "CFTC Commitments of Traders (weekly Saturday)", "category": "scraper"},
    {"key": "scraper_etoro", "name": "eToro Position Sync", "description": "Sync positions from eToro account", "category": "scraper"},

    # Pipeline
    {"key": "pipeline_indicators", "name": "Technical Indicators", "description": "RSI, MACD, Bollinger, ATR computation (every 15 min)", "category": "pipeline"},
    {"key": "pipeline_signals", "name": "Signal Engine", "description": "Signal detection and scoring (every 15 min)", "category": "pipeline"},
    {"key": "pipeline_exposure", "name": "Portfolio Exposure", "description": "Recalculate exposure breakdown (every 1 hour)", "category": "pipeline"},
    {"key": "pipeline_snapshot", "name": "Daily Snapshot", "description": "End-of-day portfolio snapshot (daily 23:30 UTC)", "category": "pipeline"},
    {"key": "pipeline_sentiment_agg", "name": "Sentiment Aggregation", "description": "Aggregate sentiment scores (every 1 hour)", "category": "pipeline"},

    # AI Agents
    {"key": "agent_news_analyst", "name": "News Analyst", "description": "AI processes news into structured sentiment (every 5 min)", "category": "agent"},
    {"key": "agent_anomaly", "name": "Anomaly Detector", "description": "Detect unusual market patterns (every 1 hour)", "category": "agent"},
    {"key": "agent_strategy", "name": "Strategy Advisor", "description": "Portfolio-aware strategy proposals (every 4 hours)", "category": "agent"},
    {"key": "agent_daily_briefing", "name": "Daily Briefing", "description": "Morning briefing generation (daily 06:00 UTC)", "category": "agent"},
    {"key": "agent_weekly_review", "name": "Weekly Review", "description": "Deep weekly analysis (Saturday 10:00 UTC)", "category": "agent"},
    {"key": "agent_optimization", "name": "Strategy Optimization", "description": "Strategy parameter tuning (Saturday 14:00 UTC)", "category": "agent"},
    {"key": "agent_monday_plan", "name": "Monday Planner", "description": "Monday game plan generation (Sunday 18:00 UTC)", "category": "agent"},
]


def seed_components():
    """Register all default components."""
    created = 0
    for comp in DEFAULT_COMPONENTS:
        _, was_created = PlatformComponent.objects.get_or_create(
            key=comp["key"],
            defaults=comp,
        )
        if was_created:
            created += 1
    return created
'''))

    # ================================================================
    # 2. REGISTER MODEL IN ADMIN
    # ================================================================

    created.append(create_file("core/admin.py", '''from django.contrib import admin
from .platform_control import PlatformComponent


@admin.register(PlatformComponent)
class PlatformComponentAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "is_enabled", "last_run_at", "last_status", "run_count", "error_count"]
    list_filter = ["category", "is_enabled", "last_status"]
    list_editable = ["is_enabled"]
    search_fields = ["name", "key"]
'''))

    # ================================================================
    # 3. ADD TO INSTALLED APPS & CREATE MIGRATION
    # ================================================================

    # core needs a models.py that imports PlatformComponent
    core_models = "core/models.py"
    if not os.path.exists(core_models):
        created.append(create_file(core_models, ''))

    # Ensure core has migrations dir
    os.makedirs("core/migrations", exist_ok=True)
    init_path = "core/migrations/__init__.py"
    if not os.path.exists(init_path):
        created.append(create_file(init_path, ''))

    # Add PlatformComponent import to core/models.py so Django finds it
    if os.path.exists(core_models):
        with open(core_models, "r", encoding="utf-8") as f:
            content = f.read()
        if "PlatformComponent" not in content:
            with open(core_models, "a", encoding="utf-8") as f:
                f.write('\nfrom .platform_control import PlatformComponent  # noqa\n')
            created.append(core_models)

    # ================================================================
    # 4. SEED COMMAND — register components
    # ================================================================

    os.makedirs("core/management/commands", exist_ok=True)
    for p in ["core/management/__init__.py", "core/management/commands/__init__.py"]:
        if not os.path.exists(p):
            created.append(create_file(p, ''))

    created.append(create_file("core/management/commands/seed_components.py",
'''"""Register all platform components."""
from django.core.management.base import BaseCommand
from core.platform_control import seed_components


class Command(BaseCommand):
    help = "Register all platform components (scrapers, agents, pipelines)"

    def handle(self, *args, **options):
        count = seed_components()
        self.stdout.write(self.style.SUCCESS(f"Registered {count} new components"))
'''))

    # Also add to init_platform command
    init_cmd = "instruments/management/commands/init_platform.py"
    if os.path.exists(init_cmd):
        with open(init_cmd, "r", encoding="utf-8") as f:
            content = f.read()
        if "seed_components" not in content:
            content = content.replace(
                "# Step 4: Check API keys",
                '''# Step 4: Register platform components
        self.stdout.write("Step 4: Registering platform components...")
        from core.platform_control import seed_components
        comp_count = seed_components()
        self.stdout.write(self.style.SUCCESS(f"  -> {comp_count} new components registered\\n"))

        # Step 5: Check API keys'''
            )
            content = content.replace("Step 4: Checking API keys", "Step 5: Checking API keys")
            with open(init_cmd, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(init_cmd)

    # ================================================================
    # 5. GATE ALL CELERY TASKS — check component before running
    # ================================================================

    created.append(create_file("core/task_gate.py", '''"""Task gate — check if a component is enabled before executing."""
import logging
from functools import wraps
from core.platform_control import is_component_enabled, get_component

logger = logging.getLogger(__name__)


def guarded_task(component_key):
    """
    Decorator for Celery tasks. Checks two things:
    1. The master switch is ON
    2. The specific component is ON
    If either is off, the task returns early with a skip message.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Check master switch
            if not is_component_enabled("platform_master"):
                logger.info(f"[GATE] Platform master switch OFF — skipping {component_key}")
                return {"status": "skipped", "reason": "platform_disabled"}

            # Check component switch
            if not is_component_enabled(component_key):
                logger.info(f"[GATE] Component {component_key} disabled — skipping")
                return {"status": "skipped", "reason": f"{component_key}_disabled"}

            # Execute
            comp = get_component(component_key)
            try:
                result = func(*args, **kwargs)
                if comp:
                    msg = str(result.get("status", "ok")) if isinstance(result, dict) else "ok"
                    comp.mark_run(success=True, message=msg)
                return result
            except Exception as e:
                if comp:
                    comp.mark_run(success=False, message=str(e)[:500])
                raise

        return wrapper
    return decorator
'''))

    # ================================================================
    # 6. UPDATE ALL CELERY TASKS to use the gate
    # ================================================================

    created.append(create_file("market_data/tasks.py", '''"""Celery tasks for market data ingestion — gated by platform control."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
@guarded_task("scraper_live_quotes")
def fetch_live_quotes(self, watchlist_only=True):
    """Tier 1: Fetch live quotes for watchlist instruments."""
    from instruments.models import Instrument
    from core.market_calendar import is_any_market_open

    if not is_any_market_open():
        return {"status": "skipped", "reason": "markets_closed"}

    qs = Instrument.objects.filter(is_active=True)
    if watchlist_only:
        qs = qs.filter(is_watchlist=True)

    symbols = list(qs.values_list("symbol", flat=True))
    logger.info(f"Fetching live quotes for {len(symbols)} instruments")
    # TODO: Implement adapter calls
    return {"status": "success", "count": len(symbols)}


@shared_task
@guarded_task("scraper_forex")
def fetch_forex_quotes():
    """Tier 1: Fetch forex pair quotes."""
    from core.market_calendar import is_forex_open
    if not is_forex_open():
        return {"status": "skipped", "reason": "forex_closed"}
    logger.info("Fetching forex quotes")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("scraper_commodities")
def fetch_commodity_quotes():
    """Tier 1: Fetch commodity quotes."""
    logger.info("Fetching commodity quotes")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("scraper_fred")
def fetch_fred_updates():
    """Tier 4: Fetch latest FRED macro data."""
    logger.info("Fetching FRED macro updates")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("scraper_eod")
def fetch_eod_all_instruments():
    """Tier 5: End-of-day data for the full universe."""
    logger.info("Fetching EOD prices for all instruments")
    return {"status": "pending_implementation"}
'''))

    created.append(create_file("scraping/tasks.py", '''"""Celery tasks for web scraping — gated by platform control."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task
@guarded_task("scraper_news")
def fetch_breaking_news():
    """Tier 1: Fetch latest news."""
    logger.info("Fetching breaking news")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("scraper_sentiment")
def fetch_social_sentiment():
    """Tier 2: Fetch sentiment from Reddit, StockTwits."""
    logger.info("Fetching social sentiment")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("scraper_calendar")
def check_economic_calendar():
    """Tier 2: Check for upcoming economic events."""
    logger.info("Checking economic calendar")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("scraper_finviz")
def fetch_finviz_screener():
    """Tier 3: Fetch FinViz screener data."""
    logger.info("Fetching FinViz screener")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("pipeline_sentiment_agg")
def aggregate_sentiment():
    """Tier 3: Aggregate sentiment scores across sources."""
    logger.info("Aggregating sentiment scores")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("scraper_tradingview")
def fetch_tradingview_ideas():
    """Tier 4: Fetch TradingView community ideas."""
    logger.info("Fetching TradingView ideas")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("scraper_sec")
def fetch_sec_filings():
    """Tier 5: Fetch latest SEC filings."""
    logger.info("Fetching SEC filings")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("scraper_cot")
def fetch_cot_reports():
    """Tier 6: Fetch CFTC Commitments of Traders reports."""
    logger.info("Fetching COT reports")
    return {"status": "pending_implementation"}
'''))

    created.append(create_file("indicators/tasks.py", '''"""Celery tasks for technical indicators — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task
@guarded_task("pipeline_indicators")
def recalculate_watchlist_indicators():
    """Tier 2: Recalculate indicators for watchlist."""
    logger.info("Recalculating technical indicators for watchlist")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("pipeline_indicators")
def recalculate_all_indicators():
    """Tier 5: Daily full recalculation."""
    logger.info("Recalculating all technical indicators")
    return {"status": "pending_implementation"}
'''))

    created.append(create_file("signals/tasks.py", '''"""Celery tasks for signal detection — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task
@guarded_task("pipeline_signals")
def run_signal_scan():
    """Tier 2: Run signal scan on watchlist."""
    logger.info("Running signal scan on watchlist")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("pipeline_signals")
def run_full_universe_scan():
    """Tier 5: Daily full universe signal scan."""
    logger.info("Running full universe signal scan")
    return {"status": "pending_implementation"}
'''))

    created.append(create_file("portfolio/tasks.py", '''"""Celery tasks for portfolio — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task
@guarded_task("pipeline_exposure")
def recalculate_exposure():
    """Tier 3: Recalculate portfolio exposure."""
    logger.info("Recalculating portfolio exposure")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("pipeline_snapshot")
def create_daily_snapshot():
    """Tier 5: Create end-of-day snapshot."""
    logger.info("Creating daily portfolio snapshot")
    return {"status": "pending_implementation"}
'''))

    created.append(create_file("ai_agents/tasks.py", '''"""Celery tasks for AI agents — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task
@guarded_task("agent_news_analyst")
def process_unanalyzed_news():
    """Tier 1: Process news with AI sentiment analysis."""
    from scraping.models import NewsArticle
    from ai_agents.agents.news_analyst import NewsAnalystAgent

    unprocessed = NewsArticle.objects.filter(ai_processed_at__isnull=True).order_by("-published_at")[:10]
    if not unprocessed:
        return {"status": "no_unprocessed_news"}

    agent = NewsAnalystAgent()
    processed = 0

    for article in unprocessed:
        try:
            result = agent.run(article={
                "title": article.title,
                "source": article.source,
                "published_at": str(article.published_at),
                "content": article.content_summary or article.raw_content[:2000],
            })
            from django.utils import timezone
            article.ai_sentiment_score = result.get("sentiment_score", 0)
            article.ai_urgency = result.get("urgency", "low")
            article.ai_summary = result.get("summary", "")
            article.ai_processed_at = timezone.now()
            article.save()
            processed += 1
        except Exception as e:
            logger.error(f"Failed to process article {article.id}: {e}")

    return {"status": "success", "processed": processed}


@shared_task
@guarded_task("agent_anomaly")
def run_anomaly_detection():
    """Tier 3: AI anomaly detection scan."""
    logger.info("Running AI anomaly detection")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("agent_strategy")
def review_active_strategies():
    """Tier 4: AI review of active strategies."""
    logger.info("AI reviewing active strategies")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("agent_daily_briefing")
def generate_daily_briefing():
    """Tier 5: Generate morning briefing."""
    logger.info("Generating AI daily briefing")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("agent_weekly_review")
def generate_weekly_review():
    """Tier 6: Saturday deep weekly review."""
    logger.info("Generating AI weekly review")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("agent_optimization")
def optimize_strategies():
    """Tier 6: Saturday strategy optimization."""
    logger.info("Running AI strategy optimization")
    return {"status": "pending_implementation"}


@shared_task
@guarded_task("agent_monday_plan")
def generate_monday_plan():
    """Tier 6: Sunday evening Monday game plan."""
    logger.info("Generating Monday game plan")
    return {"status": "pending_implementation"}
'''))

    created.append(create_file("strategies/tasks.py", '''"""Celery tasks for strategies — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task
@guarded_task("agent_strategy")
def suggest_rebalancing():
    """Tier 6: Weekly portfolio rebalancing suggestions."""
    logger.info("Generating rebalancing suggestions")
    return {"status": "pending_implementation"}
'''))

    # ================================================================
    # 7. ADMIN DASHBOARD — with start/stop controls
    # ================================================================

    created.append(create_file("templates/dashboard/admin_dashboard.html", r'''{% extends "base.html" %}
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

<!-- ── Master Switch ─────────────────────────────── -->
<div class="card fade-in-up" style="margin-bottom:24px;border-color:{% if master_enabled %}var(--accent){% else %}var(--accent-red){% endif %};">
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
            <div style="font-family:var(--font-display);font-size:18px;font-weight:700;letter-spacing:2px;color:{% if master_enabled %}var(--accent){% else %}var(--accent-red){% endif %};">
                {% if master_enabled %}PLATFORM ACTIVE{% else %}PLATFORM STOPPED{% endif %}
            </div>
            <div style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted);margin-top:4px;">
                Master switch controls all automated scrapers, agents, and pipelines
            </div>
        </div>
        <form method="post" action="{% url 'admin_toggle_component' %}">
            {% csrf_token %}
            <input type="hidden" name="key" value="platform_master">
            {% if master_enabled %}
            <button type="submit" class="btn" style="background:var(--accent-red-dim);border-color:var(--accent-red);color:var(--accent-red);font-size:14px;padding:12px 32px;letter-spacing:2px;">
                STOP ALL
            </button>
            {% else %}
            <button type="submit" class="btn btn-primary" style="font-size:14px;padding:12px 32px;letter-spacing:2px;">
                START PLATFORM
            </button>
            {% endif %}
        </form>
    </div>
</div>

<!-- ── Quick Actions ─────────────────────────────── -->
<div class="grid grid-4" style="margin-bottom:24px;">
    <form method="post" action="{% url 'admin_bulk_toggle' %}">{% csrf_token %}<input type="hidden" name="category" value="scraper"><input type="hidden" name="action" value="enable">
        <button type="submit" class="btn" style="width:100%;">Start All Scrapers</button>
    </form>
    <form method="post" action="{% url 'admin_bulk_toggle' %}">{% csrf_token %}<input type="hidden" name="category" value="scraper"><input type="hidden" name="action" value="disable">
        <button type="submit" class="btn" style="width:100%;border-color:var(--accent-red-dim);">Stop All Scrapers</button>
    </form>
    <form method="post" action="{% url 'admin_bulk_toggle' %}">{% csrf_token %}<input type="hidden" name="category" value="agent"><input type="hidden" name="action" value="enable">
        <button type="submit" class="btn" style="width:100%;">Start All Agents</button>
    </form>
    <form method="post" action="{% url 'admin_bulk_toggle' %}">{% csrf_token %}<input type="hidden" name="category" value="agent"><input type="hidden" name="action" value="disable">
        <button type="submit" class="btn" style="width:100%;border-color:var(--accent-red-dim);">Stop All Agents</button>
    </form>
</div>

<!-- ── Component Controls ────────────────────────── -->
{% for cat_name, cat_components in components_by_category.items %}
<div class="section-label fade-in-up">{{ cat_name|upper }}</div>
<div class="card fade-in-up" style="margin-bottom:20px;">
    <div class="table-wrapper">
    <table>
        <thead><tr><th>Component</th><th>Status</th><th>Last Run</th><th>Result</th><th>Runs</th><th>Errors</th><th>Action</th></tr></thead>
        <tbody>
        {% for c in cat_components %}
        <tr>
            <td>
                <div style="font-weight:600;">{{ c.name }}</div>
                <div style="font-size:10px;color:var(--text-muted);font-family:var(--font-mono);">{{ c.description }}</div>
            </td>
            <td>
                {% if c.is_enabled %}
                <span style="color:var(--accent);font-family:var(--font-mono);font-size:12px;">RUNNING</span>
                {% else %}
                <span style="color:var(--text-muted);font-family:var(--font-mono);font-size:12px;">STOPPED</span>
                {% endif %}
            </td>
            <td style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted);">
                {% if c.last_run_at %}{{ c.last_run_at|timesince }} ago{% else %}Never{% endif %}
            </td>
            <td>
                {% if c.last_status == "success" %}<span style="color:var(--accent);">OK</span>
                {% elif c.last_status == "error" %}<span style="color:var(--accent-red);">ERR</span>
                {% elif c.last_status == "skipped" %}<span style="color:var(--text-muted);">SKIP</span>
                {% else %}<span style="color:var(--text-muted);">---</span>{% endif %}
            </td>
            <td style="font-family:var(--font-mono);font-size:12px;">{{ c.run_count }}</td>
            <td style="font-family:var(--font-mono);font-size:12px;color:{% if c.error_count > 0 %}var(--accent-red){% else %}var(--text-muted){% endif %};">{{ c.error_count }}</td>
            <td>
                <form method="post" action="{% url 'admin_toggle_component' %}" style="display:inline;">
                    {% csrf_token %}
                    <input type="hidden" name="key" value="{{ c.key }}">
                    {% if c.is_enabled %}
                    <button type="submit" class="btn btn-sm" style="border-color:var(--accent-red-dim);color:var(--accent-red);font-size:10px;">STOP</button>
                    {% else %}
                    <button type="submit" class="btn btn-sm btn-primary" style="font-size:10px;">START</button>
                    {% endif %}
                </form>
            </td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
</div>
{% endfor %}

<!-- ── System Stats (same as before) ─────────────── -->
<div class="section-label fade-in-up">System Overview</div>
<div class="grid grid-5" style="margin-bottom:20px;">
    <div class="stat-box fade-in-up delay-1">
        <div class="stat-label">Total Users</div>
        <div class="stat-value">{{ total_users }}</div>
        <div class="stat-sub">{{ active_users }} active</div>
    </div>
    <div class="stat-box fade-in-up delay-2">
        <div class="stat-label">Instruments</div>
        <div class="stat-value">{{ total_instruments }}</div>
        <div class="stat-sub">{{ watchlist_instruments }} watched</div>
    </div>
    <div class="stat-box fade-in-up delay-3">
        <div class="stat-label">Active Signals</div>
        <div class="stat-value" style="color:var(--accent);">{{ active_signals }}</div>
    </div>
    <div class="stat-box fade-in-up delay-4">
        <div class="stat-label">AI Tasks (24h)</div>
        <div class="stat-value">{{ ai_tasks_24h }}</div>
        <div class="stat-sub">${{ ai_cost_24h }} cost</div>
    </div>
    <div class="stat-box fade-in-up delay-5">
        <div class="stat-label">News Articles</div>
        <div class="stat-value">{{ total_news }}</div>
        <div class="stat-sub">{{ unprocessed_news }} unprocessed</div>
    </div>
</div>

<!-- Users -->
<div class="section-label fade-in-up">Users</div>
<div class="card fade-in-up delay-5" style="margin-bottom:24px;">
    <div class="card-header">
        <span class="card-title">Registered Users</span>
        <a href="{% url 'admin:auth_user_add' %}" class="btn btn-primary btn-sm" target="_blank">+ Add User</a>
    </div>
    <div class="table-wrapper">
    <table>
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
    </table>
    </div>
</div>

<!-- Data Health -->
<div class="section-label fade-in-up">Data Pipeline Health</div>
<div class="card fade-in-up delay-6">
    <div class="card-header"><span class="card-title">Data Sources</span></div>
    <div class="table-wrapper">
    <table>
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
    </table>
    </div>
</div>
{% endblock %}
'''))

    # ================================================================
    # 8. ADMIN VIEWS — toggle + bulk toggle
    # ================================================================

    admin_views_code = '''

@login_required
def admin_toggle_component(request):
    """Toggle a single platform component on/off."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    if request.method == "POST":
        from core.platform_control import PlatformComponent
        from django.contrib import messages
        key = request.POST.get("key", "")
        try:
            comp = PlatformComponent.objects.get(key=key)
            comp.is_enabled = not comp.is_enabled
            comp.save()
            action = "started" if comp.is_enabled else "stopped"
            messages.success(request, f"{comp.name} {action}.")
        except PlatformComponent.DoesNotExist:
            messages.error(request, f"Component '{key}' not found.")
    from django.shortcuts import redirect
    return redirect("admin_dashboard")


@login_required
def admin_bulk_toggle(request):
    """Enable or disable all components in a category."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    if request.method == "POST":
        from core.platform_control import PlatformComponent
        from django.contrib import messages
        category = request.POST.get("category", "")
        action = request.POST.get("action", "")
        enable = action == "enable"
        count = PlatformComponent.objects.filter(category=category).update(is_enabled=enable)
        verb = "started" if enable else "stopped"
        messages.success(request, f"{count} {category} components {verb}.")
    from django.shortcuts import redirect
    return redirect("admin_dashboard")
'''

    append_if_missing("dashboard/views.py", "def admin_toggle_component", admin_views_code)

    # Update admin_dashboard view to include components
    views_path = "dashboard/views.py"
    if os.path.exists(views_path):
        with open(views_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "components_by_category" not in content:
            content = content.replace(
                '    return render(request, "dashboard/admin_dashboard.html", context)',
                '''    # Platform components
    from core.platform_control import PlatformComponent, is_component_enabled
    from collections import OrderedDict

    master_enabled = is_component_enabled("platform_master")
    all_components = PlatformComponent.objects.exclude(key="platform_master").order_by("category", "name")
    components_by_category = OrderedDict()
    cat_labels = {"scraper": "Data Scrapers", "pipeline": "Data Pipeline", "agent": "AI Agents", "system": "System"}
    for comp in all_components:
        label = cat_labels.get(comp.category, comp.category)
        if label not in components_by_category:
            components_by_category[label] = []
        components_by_category[label].append(comp)

    context["master_enabled"] = master_enabled
    context["components_by_category"] = components_by_category

    return render(request, "dashboard/admin_dashboard.html", context)'''
            )
            with open(views_path, "w", encoding="utf-8") as f:
                f.write(content)

    # Add URLs
    urls_path = "dashboard/urls.py"
    if os.path.exists(urls_path):
        with open(urls_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "admin_toggle_component" not in content:
            content = content.replace(
                'path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),',
                'path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),\n'
                '    path("admin-dashboard/toggle/", views.admin_toggle_component, name="admin_toggle_component"),\n'
                '    path("admin-dashboard/bulk-toggle/", views.admin_bulk_toggle, name="admin_bulk_toggle"),'
            )
            with open(urls_path, "w", encoding="utf-8") as f:
                f.write(content)

    print(f"""
  SAURON VISION — Patch v4.1 Applied ({len(created)} files)

  Platform control system:
    - Master switch: one click to start/stop EVERYTHING
    - Per-component toggles for each scraper, agent, pipeline
    - Bulk start/stop by category (all scrapers, all agents)
    - Every Celery task checks its gate before executing
    - Run counts, error counts, last run time tracked

  Commands to run:

    python manage.py makemigrations core
    python manage.py migrate
    python manage.py seed_components
    python manage.py runserver

  Then go to /admin-dashboard/ and click START PLATFORM.
  Individual components can be toggled on/off independently.
""")


if __name__ == "__main__":
    generate()
