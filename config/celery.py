"""Celery configuration for Sauron Vision."""
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("sauron_vision")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# ============================================================
# Task routing — fast vs slow queues
# ============================================================
app.conf.task_routes = {
    # Tier 1-2: Fast queue (price fetching, news, signals)
    "market_data.tasks.*": {"queue": "fast"},
    "scraping.tasks.fetch_breaking_news": {"queue": "fast"},
    "scraping.tasks.fetch_social_sentiment": {"queue": "fast"},
    "signals.tasks.run_signal_scan": {"queue": "fast"},
    "indicators.tasks.recalculate_watchlist_indicators": {"queue": "fast"},
    # Tier 3-6: Slow queue (analysis, AI, heavy computation)
    "ai_agents.tasks.*": {"queue": "ai"},
    "strategies.tasks.*": {"queue": "slow"},
    "portfolio.tasks.*": {"queue": "slow"},
    "scraping.tasks.fetch_cot_reports": {"queue": "slow"},
    "scraping.tasks.fetch_sec_filings": {"queue": "slow"},
}

# ============================================================
# Beat Schedule — The Heartbeat of Sauron Vision
# ============================================================
app.conf.beat_schedule = {

    # ── UPGRADE-5: Funding alerts + retention ─────────────────
    "scan-funding-signals": {
        "task": "market_data.funding_alerts.scan_funding_signals",
        "schedule": 300.0,
    },
    "nightly-cleanup": {
        "task": "market_data.cleanup_tasks.nightly_cleanup_all",
        "schedule": crontab(hour=4, minute=15),
    },

    # ── TIER 1: Every 1-5 min (during market hours) ──────────
    "fetch-live-quotes-watchlist": {
        "task": "market_data.tasks.fetch_live_quotes",
        "schedule": 60.0,
        "kwargs": {"watchlist_only": True},
    },
    "fetch-forex-live": {
        "task": "market_data.tasks.fetch_forex_quotes",
        "schedule": 120.0,
    },
    "fetch-commodity-live": {
        "task": "market_data.tasks.fetch_commodity_quotes",
        "schedule": 300.0,
    },
    "fetch-crypto-prices": {
        "task": "market_data.tasks.fetch_crypto_quotes",
        "schedule": 120.0,
    },
    "fetch-crypto-news": {
        "task": "market_data.tasks.fetch_crypto_news_task",
        "schedule": 600.0,
    },
    "fetch-breaking-news": {
        "task": "scraping.tasks.fetch_breaking_news",
        "schedule": 180.0,
    },
    "ai-process-new-news": {
        "task": "ai_agents.tasks.process_unanalyzed_news",
        "schedule": 300.0,
    },

    # ── TIER 2: Every 15-30 min ──────────────────────────────
    "recalculate-technicals-watchlist": {
        "task": "indicators.tasks.recalculate_watchlist_indicators",
        "schedule": 900.0,
    },
    "run-signal-engine": {
        "task": "signals.tasks.run_signal_scan",
        "schedule": 900.0,
    },
    "fetch-social-sentiment": {
        "task": "scraping.tasks.fetch_social_sentiment",
        "schedule": 1800.0,
    },
    "check-economic-calendar": {
        "task": "scraping.tasks.check_economic_calendar",
        "schedule": 1800.0,
    },

    # ── TIER 3: Hourly ───────────────────────────────────────
    "update-portfolio-exposure": {
        "task": "portfolio.tasks.recalculate_exposure",
        "schedule": 3600.0,
    },
    "fetch-finviz-screener": {
        "task": "scraping.tasks.fetch_finviz_screener",
        "schedule": 3600.0,
    },
    "ai-anomaly-scan": {
        "task": "ai_agents.tasks.run_anomaly_detection",
        "schedule": 3600.0,
    },
    "aggregate-sentiment-scores": {
        "task": "scraping.tasks.aggregate_sentiment",
        "schedule": 3600.0,
    },

    # ── TIER 4: Every 4-6 hours ──────────────────────────────
    "fetch-fred-macro": {
        "task": "market_data.tasks.fetch_fred_updates",
        "schedule": 14400.0,
    },
    "fetch-tradingview-ideas": {
        "task": "scraping.tasks.fetch_tradingview_ideas",
        "schedule": 21600.0,
    },
    "ai-strategy-review": {
        "task": "ai_agents.tasks.review_active_strategies",
        "schedule": 14400.0,
    },

    # ── TIER 5: Daily (after market close) ───────────────────
    "fetch-eod-prices-full-universe": {
        "task": "market_data.tasks.fetch_eod_all_instruments",
        "schedule": crontab(hour=22, minute=30),
    },
    "recalculate-all-technicals": {
        "task": "indicators.tasks.recalculate_all_indicators",
        "schedule": crontab(hour=23, minute=0),
    },
    "daily-portfolio-snapshot": {
        "task": "portfolio.tasks.create_daily_snapshot",
        "schedule": crontab(hour=23, minute=30),
    },
    "fetch-sec-filings": {
        "task": "scraping.tasks.fetch_sec_filings",
        "schedule": crontab(hour=2, minute=0),
    },
    "ai-daily-briefing": {
        "task": "ai_agents.tasks.generate_daily_briefing",
        "schedule": crontab(hour=6, minute=0),
    },
    "run-full-signal-scan": {
        "task": "signals.tasks.run_full_universe_scan",
        "schedule": crontab(hour=23, minute=45),
    },

    # ── TIER 6: Weekly (weekend) ─────────────────────────────
    "fetch-cot-reports": {
        "task": "scraping.tasks.fetch_cot_reports",
        "schedule": crontab(hour=0, minute=0, day_of_week="saturday"),
    },
    "ai-weekly-review": {
        "task": "ai_agents.tasks.generate_weekly_review",
        "schedule": crontab(hour=10, minute=0, day_of_week="saturday"),
    },
    "ai-strategy-optimization": {
        "task": "ai_agents.tasks.optimize_strategies",
        "schedule": crontab(hour=14, minute=0, day_of_week="saturday"),
    },
    "ai-monday-game-plan": {
        "task": "ai_agents.tasks.generate_monday_plan",
        "schedule": crontab(hour=18, minute=0, day_of_week="sunday"),
    },
        "smc-lifecycle-pass": {
        "task": "signals.tasks_lifecycle.run_smc_lifecycle",
        "schedule": 300.0,
    },
    "smc-universe-scan": {
        "task": "signals.tasks_lifecycle.scan_smc_universe",
        "schedule": 1800.0,
    },
    "weekly-portfolio-rebalance-suggestions": {
        "task": "strategies.tasks.suggest_rebalancing",
        "schedule": crontab(hour=12, minute=0, day_of_week="sunday"),
    },
}
