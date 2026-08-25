"""Celery configuration for Sauron Vision."""
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("sauron_vision")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# autodiscover_tasks() only imports each app's `tasks` module. Task modules
# living outside that convention must be imported explicitly, or beat
# enqueues their entries into the void ("Received unregistered task") and
# they never run on any worker.
app.conf.imports = (
    "market_data.cleanup_tasks",
    "market_data.funding_alerts",
    "signals.tasks_lifecycle",
)

# ============================================================
# Task routing — fast vs slow queues
# ============================================================
# Anything not matched by task_routes below (brain.*, alerts.*,
# bot_program.*, most signals.*) lands on the default queue. It MUST be one
# the documented workers consume (-Q fast,default / -Q slow,ai) — without
# this line Celery publishes unrouted tasks to an implicit "celery" queue
# that no worker subscribes to, and half the beat schedule silently rots.
app.conf.task_default_queue = "default"

app.conf.task_routes = {
    # Overrides the market_data.tasks.* glob below: Celery's MapRoute checks
    # exact task names before any pattern, so this wins wherever it sits. A
    # cold FRED run walks twelve series of 500 observations each; on the fast
    # queue it sits in front of the 60-second quote poller, which is the one
    # task in the system that must not wait.
    "market_data.tasks.fetch_fred_updates": {"queue": "slow"},
    # Tier 1-2: Fast queue (price fetching, news, signals)
    "market_data.tasks.*": {"queue": "fast"},
    "scraping.tasks.fetch_breaking_news": {"queue": "fast"},
    "scraping.tasks.fetch_social_sentiment": {"queue": "fast"},
    "signals.tasks.run_signal_scan": {"queue": "fast"},
    "indicators.tasks.recalculate_watchlist_indicators": {"queue": "fast"},
    # Tier 3-6: Slow queue (analysis, AI, heavy computation)
    # A backtest replays every bar in the window for every symbol. Left on
    # the default queue it would sit in front of the 60-second quote poller
    # on the fast/default worker; the slow worker exists for exactly this.
    "backtester.tasks.*": {"queue": "slow"},
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

    # ── PHASE 37: Sauron's Mind synthesizer ───────────────────
    # Hourly, not half-hourly: the world does not change materially every
    # 30 minutes, and this is the largest recurring AI cost in the system.
    "sauron-mind-synthesize": {
        "task": "brain.tasks.run_sauron_mind",
        "schedule": 3600.0,
    },
    "sauron-mind-resolve-predictions": {
        "task": "brain.tasks.resolve_brain_predictions",
        "schedule": 3600.0,  # hourly
    },

    # ── PHASE 38: Critic + nightly consolidation ──────────────
    # The critic is deep-tier and the single most expensive recurring call.
    # Hypotheses do not arrive fast enough to justify 48 passes a day.
    "sauron-critic-pass": {
        "task": "brain.tasks.run_critic_pass",
        "schedule": 7200.0,
    },
    "sauron-consolidation-nightly": {
        "task": "brain.tasks.run_consolidation",
        "schedule": crontab(hour=3, minute=0),  # 03:00 UTC daily
    },
    "sauron-strategist-daily": {
        "task": "brain.tasks.run_strategist",
        "schedule": crontab(hour=6, minute=0),  # 06:00 UTC daily
    },
    "sauron-strategy-generator-weekly": {
        "task": "brain.tasks.run_strategy_generator",
        "schedule": crontab(hour=4, minute=0, day_of_week=0),  # Sun 04:00 UTC
    },
    "sauron-auto-demoter-daily": {
        "task": "brain.tasks.run_auto_demoter",
        "schedule": crontab(hour=4, minute=30),  # 04:30 UTC daily
    },
    "sauron-earnings-reviewer": {
        "task": "brain.tasks.run_earnings_reviewer",
        "schedule": 14400.0,  # every 4 hours
    },
    # Deterministic detectors, no LLM call — cheap, so it stays frequent.
    "sauron-anomaly-scanner": {
        "task": "brain.tasks.run_anomaly_scanner",
        "schedule": 1800.0,
    },
    # ── PHASE 61: open-position watcher ───────────────────────
    # Half-hourly because a position can travel from +2R to its stop inside
    # one hour and the whole point is to speak BEFORE the mechanical exit
    # does. The cadence is affordable because the pass that runs every time
    # is pure Python; the model half is gated on a trigger firing and capped
    # per pass and per day inside position_review_agent.
    "sauron-position-review": {
        "task": "brain.tasks.run_position_review",
        "schedule": 1800.0,
    },

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
    # Alpha Vantage spend is budgeted inside the task (25/day), so cadence
    # no longer decides the paid-API bill — the rest of each run is keyless
    # yfinance. 600s keeps forex marks inside the paper trader's 900s
    # freshness window: at the old 1800s a forex quote was stale for half
    # its life and the mark silently fell back to bar closes. For real
    # forex ticks enable the OANDA streamer — free, broker-grade.
    "fetch-forex-live": {
        "task": "market_data.tasks.fetch_forex_quotes",
        "schedule": 600.0,
    },
    "fetch-commodity-live": {
        "task": "market_data.tasks.fetch_commodity_quotes",
        "schedule": 300.0,
    },
    "fetch-index-live": {
        "task": "market_data.tasks.fetch_index_quotes",
        "schedule": 300.0,
    },
    # CoinGecko's demo tier is ~10k calls/month; 120s exceeded it. The
    # Binance streamer is the real-time source when enabled.
    "fetch-crypto-prices": {
        "task": "market_data.tasks.fetch_crypto_quotes",
        "schedule": 300.0,
    },
    "fetch-crypto-news": {
        "task": "market_data.tasks.fetch_crypto_news_task",
        "schedule": 600.0,
    },
    # Marketaux free tier is 100 requests/day; 180s was ~5x over it.
    "fetch-breaking-news": {
        "task": "scraping.tasks.fetch_breaking_news",
        "schedule": 900.0,
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
    "daily-market-commentary": {
        "task": "ai_agents.tasks.generate_daily_commentary",
        "schedule": crontab(hour=17, minute=30),
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

    # ── Phase 3 — AI decay investigation (nightly) ───────────
    "investigate-decaying-rules": {
        "task": "ai_agents.tasks.investigate_decaying_rules",
        "schedule": crontab(hour=2, minute=30),
    },

    # ── Phase 5 — rule actuator: read decay investigations,
    #              propose enforcement actions (no auto-apply)
    "propose-rule-actions": {
        "task": "signals.tasks.propose_rule_actions",
        "schedule": crontab(hour=3, minute=0),
    },

    # ── Phase 6 — calibration: resolve agent predictions whose
    #              ground truth is now available.
    "resolve-pending-calibrations": {
        "task": "ai_agents.tasks.resolve_pending_calibrations",
        "schedule": crontab(hour=3, minute=30),
    },

    # ── Phase 7 — meta-allocator: propose new ensemble weights.
    #              Weekly to give realized_r distributions time to update.
    "propose-meta-allocation": {
        "task": "signals.tasks.propose_meta_allocation",
        "schedule": crontab(hour=4, minute=0, day_of_week="sunday"),
    },

    # ── Phase 9 — strategy evolution: scan decaying parameter-aware rules,
    #              propose mutations. Beat fires DAILY; the task's own
    #              cadence gate makes non-Sunday runs conditional on the
    #              week's closed-trade volume, so the effective rhythm is
    #              weekly on a quiet book and near-daily on a busy one.
    "propose-strategy-evolutions": {
        "task": "signals.tasks.propose_strategy_evolutions",
        "schedule": crontab(hour=5, minute=0),
    },

    # ── Phase 10 — opportunity scanner: match registered setups against
    #              every instrument; resolve flags after their horizon.
    "scan-opportunities": {
        "task": "signals.tasks.scan_opportunities",
        "schedule": crontab(hour=9, minute=0),  # daily 09:00 UTC
    },
    "resolve-opportunity-flags": {
        "task": "signals.tasks.resolve_opportunity_flags",
        "schedule": crontab(hour=23, minute=15),  # nightly 23:15 UTC
    },

    # Bars for the bot universe (1h + 4h) from each bot's own broker.
    # MUST stay ahead of the signal scan: technical + SMC rules read 4h
    # bars, and with none present every rule returns None and the bots
    # can only HOLD.
    "refresh-bot-bars": {
        "task": "market_data.tasks.refresh_bot_bars_task",
        "schedule": 600.0,
    },

    # ── Phase 13.5 — multi-asset bot tick (every 5 min).
    #              Per-asset bots short-circuit themselves outside their
    #              relevant trading windows: ForexBot HOLDs over weekends
    #              and outside preferred sessions; StockBot HOLDs during
    #              earnings blackouts. Unconditional 5-min cadence is fine.
    "tick-asset-bots": {
        "task": "bot_program.tasks.tick_all_asset_bots",
        "schedule": 300.0,  # every 5 minutes
    },

    # ── Phase 14.1 — refresh OptionContract chains (Greeks + bid/ask) for
    #              all users running an enabled options AssetBotConfig.
    #              Hourly during the NYSE active window — chains don't shift
    #              meaningfully on a sub-hour cadence and IBKR has rate
    #              budgets we don't want to burn through.
    "refresh-option-chains": {
        "task": "bot_program.tasks.refresh_all_option_chains",
        "schedule": crontab(minute=15, hour="13-20"),  # 13:15..20:15 UTC ≈ NYSE hours
    },

    # ── Phase 26 — daily track-record decay detection. Compares last 7d
    #              of bot-trade performance vs the 30d baseline per
    #              (rule, asset_class). Fires notifications and persists
    #              a RuleTrackRecordAlert audit row when decay detected.
    "track-record-decay-check": {
        "task": "bot_program.tasks.check_all_track_record_decay",
        "schedule": crontab(hour=6, minute=15),  # 06:15 UTC daily
    },

    # ── Phase 19 — live IBKR market-data feed. Pulls klines + ticker for
    #              instruments routed through IBKR. Hourly during NYSE
    #              active window matches Phase-14.1 chain refresh cadence.
    "ibkr-data-feed": {
        "task": "bot_program.tasks.refresh_all_ibkr_market_data",
        "schedule": crontab(minute=30, hour="13-20"),  # 13:30..20:30 UTC
    },

    # ── Phase 33.4 — reconcile open live AssetBotTrade rows against broker
    #              state. Catches manual closes, broker liquidations, and
    #              worker-died-mid-order drift. Every 15 min during NYSE
    #              hours — extending to 24/7 is fine but mostly noise outside
    #              market hours since broker positions don't change.
    # Drain trades stuck in CLOSE_PENDING (broker close failed; the position
    # is still live at the broker). Every 5 min, all day — a stranded live
    # position is not a market-hours-only problem.
    "retry-pending-closes": {
        "task": "bot_program.tasks.retry_pending_closes",
        "schedule": 300.0,
    },

    "reconcile-asset-bot-trades": {
        "task": "bot_program.tasks.reconcile_all_asset_bot_trades",
        "schedule": crontab(minute="*/15", hour="13-21"),
    },

    # NB: there is deliberately no in-app "daily-postgres-backup" entry.
    # core.backups.run_postgres_backup shells out to pg_dump, which is not in
    # the application image (Dockerfile.prod installs libpq5, not the client
    # binaries), and it returns {"ok": False} instead of raising -- so it
    # recorded a SUCCESS in django-celery-results every night while producing
    # nothing. Even repaired it wrote to /app/backups, which is in no volume
    # and dies with the next rebuild. The `backup` service in
    # deploy/docker-compose.yml is the single real path: it runs in an image
    # that has both pg_dump and rclone, and writes to a named volume.

    # ── Phase 8 — promotion pipeline: walk every rule, auto-promote
    #              the eligible and auto-demote the degrading.
    "auto-evaluate-promotions": {
        "task": "signals.tasks.auto_evaluate_promotions",
        "schedule": crontab(hour=4, minute=30),
    },

    # ── Phase 11 — pattern miner: scan historical multi-modal data
    #              and propose new setup candidates. Weekly because mining
    #              is expensive and patterns evolve slowly.
    "mine-patterns": {
        "task": "signals.tasks.mine_patterns",
        "schedule": crontab(hour=6, minute=0, day_of_week="sunday"),
    },
        "smc-lifecycle-pass": {
        "task": "signals.tasks_lifecycle.run_smc_lifecycle",
        "schedule": 300.0,
    },
    # Phase 1 — plain-Signal lifecycle: stamp MFE/MAE, close stop/target/
    # expiry, populate realized_r for the whole self-improvement loop.
    "signal-lifecycle-pass": {
        "task": "signals.tasks_lifecycle.run_signal_lifecycle",
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

    # ── Alerts / Digests ─────────────────────────────────────
    "send-morning-digest": {
        "task": "alerts.tasks.send_morning_digest",
        "schedule": crontab(hour=7, minute=0),
    },
    "send-eod-digest": {
        "task": "alerts.tasks.send_eod_digest",
        "schedule": crontab(hour=17, minute=0),
    },
    "check-price-alerts": {
        "task": "alerts.tasks.check_all_price_alerts",
        "schedule": 60.0,  # Every minute
    },
}
