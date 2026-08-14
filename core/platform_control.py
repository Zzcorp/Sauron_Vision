"""Platform control — start/stop scrapers, agents, and pipeline components."""
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

    def mark_run(self, success=True, message="", status=None):
        """Record a run.

        `status` allows a third outcome beyond success and error: "warning",
        meaning the task completed without raising but did not do its job —
        it parsed rows and stored none, or it was starved of a credential.
        Without that distinction, six scrapers holding zero rows between them
        all reported a clean green run, which is the single reason nobody
        noticed the earnings blackout had never once fired.
        """
        self.last_run_at = timezone.now()
        self.last_status = status or ("success" if success else "error")
        self.last_message = message[:500]
        self.run_count += 1
        # A warning is not a crash: it should not inflate the error rate the
        # health page uses to decide whether a component is broken.
        if self.last_status == "error":
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
    {"key": "scraper_crypto", "name": "Crypto Prices", "description": "Fetch crypto prices from CoinGecko/Binance (every 2 min)", "category": "scraper"},
    {"key": "scraper_crypto_news", "name": "Crypto News", "description": "Fetch crypto news from CoinDesk, CoinTelegraph (every 10 min)", "category": "scraper"},
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

    # ── Phase 3 — AI operational ──────────────────────────────
    {"key": "feature_ai_pretrade_gate", "name": "AI Pre-Trade Sanity Gate",
     "description": "Claude reviews each proposed trade before opening (regime/news/decay). Slow & costs tokens — leave OFF unless you want it.",
     "category": "agent"},
    {"key": "pipeline_ai_journal", "name": "AI Signal Journal",
     "description": "Auto-generate journal entry when a signal closes with |R| ≥ 0.5",
     "category": "agent"},
    {"key": "pipeline_ai_decay", "name": "AI Decay Investigator",
     "description": "Investigate decaying rules nightly (DecayInvestigatorAgent)",
     "category": "agent"},

    # ── Phase 5 — closed-loop actuator ────────────────────────
    {"key": "pipeline_actuator", "name": "Rule Actuator (proposer)",
     "description": "Daily task that reads decay investigations and proposes RuleActions. Proposals are NEVER auto-applied; admin must confirm.",
     "category": "pipeline"},
    {"key": "actuator_mode_live", "name": "Actuator Live Mode",
     "description": "Off (default) = shadow / preview only — admin cannot apply proposals. On = admin can apply (and rollback). Even in live mode, every action requires explicit admin confirmation.",
     "category": "system"},

    # ── Phase 6 — calibration loop ────────────────────────────
    {"key": "pipeline_calibration", "name": "Calibration Auto-Resolver",
     "description": "Nightly task that resolves AgentPredictions whose ground truth is available. Powers the agent trust scores consumed by the risk gate.",
     "category": "pipeline"},

    # ── Phase 7 — meta-allocator ──────────────────────────────
    {"key": "pipeline_meta_allocator", "name": "Meta-Allocator (proposer)",
     "description": "Weekly task that proposes new per-rule capital weights using a 3-method ensemble (uniform, inverse-vol, expectancy) blended by data quality. Always proposes in shadow state.",
     "category": "pipeline"},
    {"key": "meta_allocator_mode_live", "name": "Meta-Allocator Live Mode",
     "description": "Off (default) = shadow / preview only. On = admin can apply allocations. Caps + smoothing + active-only rules are enforced regardless of mode.",
     "category": "system"},

    # ── Phase 9 — strategy evolution ──────────────────────────
    {"key": "pipeline_evolution", "name": "Strategy Evolution (proposer)",
     "description": "Weekly task that scans decaying parameter-aware rules and proposes mutations. Mutations require admin approval. Approved mutations fork into RESEARCH stage and walk the Phase-8 pipeline before reaching live capital.",
     "category": "pipeline"},

    # ── Phase 8 — promotion pipeline ──────────────────────────
    {"key": "pipeline_promotion", "name": "Promotion Pipeline (auto-evaluate)",
     "description": "Daily task that walks every rule and auto-promotes eligible rules / auto-demotes degrading ones. Strict gates: research → paper → live_small → live_full.",
     "category": "pipeline"},

    # ── Phase 10 — opportunity scanner ─────────────────────────
    {"key": "pipeline_opportunity_scanner", "name": "Opportunity Scanner",
     "description": "Daily multi-modal scanner: matches registered OpportunitySetups against every active instrument. Each match creates an OpportunityFlag + a linked Signal that flows through Phase 1–9. Resolves flags after their horizon.",
     "category": "pipeline"},

    # ── Phase 11 — pattern miner ──────────────────────────────
    {"key": "pipeline_pattern_miner", "name": "Pattern Miner (auto-discover setups)",
     "description": "Weekly task that mines historical price + news + calendar + macro data for repeating setup patterns. Each surviving frequent itemset becomes a DiscoveredSetup row. Admin reviews + activates promising ones, which then walk the Phase-8 promotion ladder before reaching live capital.",
     "category": "pipeline"},

    # ── Phase 12 — real-time event engine ─────────────────────
    {"key": "pipeline_event_engine", "name": "Event-Driven Engine",
     "description": "Real-time fast-rule dispatcher. When OFF, the Celery wrapper task short-circuits — direct synchronous calls to `dispatch_event()` still work. Sub-second latency from streamer event to Signal row.",
     "category": "pipeline"},

    # ── Phase 13 — multi-asset bot framework ──────────────────
    {"key": "pipeline_asset_bots", "name": "Multi-Asset Bots (stocks/forex/commodities)",
     "description": "Phase-13 framework: per-(user, asset_class) bot configs that consume Phase-1 Signals and route trades through Phase-4 broker_router (Alpaca for stocks, OANDA for forex, paper-only for commodities). Crypto bot is unchanged.",
     "category": "pipeline"},
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
