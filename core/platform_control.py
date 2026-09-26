"""Platform control — start/stop scrapers, agents, and pipeline components."""
import logging

from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)


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
        from core.secret_scrub import scrub

        self.last_run_at = timezone.now()
        self.last_status = status or ("success" if success else "error")
        # SCRUBBED, and here rather than at each call site because this is
        # the one place every ingest outcome passes through.
        # `raise_for_status()` builds its message from the full url,
        # query string included, so one 403 on a call authenticated by
        # `?apikey=...` put a live key on the health page, in this column,
        # and in every log line that echoed it. A hundred callers cannot
        # each be trusted to remember; this one can.
        self.last_message = scrub(message)[:500]
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
    {"key": "scraper_forex", "name": "Forex Quotes", "description": "Forex marks — Alpha Vantage when a key is set, keyless yfinance for the rest (every 10 min)", "category": "scraper"},
    {"key": "scraper_commodities", "name": "Commodity Quotes", "description": "Commodity prices from the catalogue via yfinance (every 5 min)", "category": "scraper"},
    {"key": "scraper_indices", "name": "Index Quotes", "description": "Index levels via yfinance — feeds the headband, no bot reads these (every 5 min)", "category": "scraper"},
    {"key": "scraper_news", "name": "Breaking News", "description": "Fetch news from APIs and RSS (every 3 min)", "category": "scraper"},
    {"key": "scraper_sentiment", "name": "Social Sentiment", "description": "Reddit, StockTwits sentiment (every 30 min)", "category": "scraper"},
    {"key": "scraper_calendar", "name": "Economic Calendar", "description": "Check upcoming economic events (every 30 min)", "category": "scraper"},
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
     "description": "Claude reviews each proposed trade before opening (regime/news/decay) — for the LEGACY crypto bot only, which is not scheduled; the multi-asset bots never consult it. Slow & costs tokens. Leave OFF.",
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
    {"key": "generator_auto_research", "name": "Generator Auto-Research",
     "description": "The weekly Strategy Generator arms its own proposals in RESEARCH stage: the scanner produces graded signals for them, no bot trades them (the stage gate), and the admin can still reject. Off (default) = proposals wait for a click on the brain page.",
     "category": "agent"},
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

    # ── Phase 61 — open-position watcher ──────────────────────
    # Without this row the @guarded_task on brain.tasks.run_position_review
    # short-circuits on every beat and the watcher silently never runs.
    {"key": "agent_position_review", "name": "Open-Position Reviewer",
     "description": "Watches OPEN positions between entry and exit. A free pass every 30 min scores R at risk, excursion, distance to stop/target, age, regime flip, vol expansion, events and concentration; only flagged positions reach a budgeted model pass answering hold / tighten / trim / exit. PROPOSES ONLY.",
     "category": "agent"},

    # ── HORIZON — the 5-10 year sector synthesis (2026-09-12) ─
    # Without this row the @guarded_task on brain.tasks.run_horizon
    # short-circuits on every beat. Description counted under 300 chars
    # (the Postgres column; see the share allocator rows above).
    {"key": "agent_horizon", "name": "Horizon (5-10y sector synthesis)",
     "description": "Monthly (1st, 04:45 UTC) on the frontier model, ~1.5 USD a run: sector tilts -2..+2 with graded 6/12-month calls, and asset-class tilts the share allocator reads as a ±10% prior at most. Off by default; /horizon/ shows the view and its grade record.",
     "category": "agent"},

    # ── Phase 13 — multi-asset bot framework ──────────────────
    {"key": "pipeline_asset_bots", "name": "Multi-Asset Bots (stocks/forex/commodities)",
     "description": "Phase-13 framework: per-(user, asset_class) bot configs that consume Phase-1 Signals and route trades through Phase-4 broker_router (Alpaca for stocks, OANDA for forex, commodities live through eToro's box only). Crypto bot is unchanged.",
     "category": "pipeline"},

    # ── Broker account sync ───────────────────────────────────
    # ONE KEY, THREE WALKS: sync_broker_account (IBKR), sync_saxo_accounts
    # and sync_etoro_accounts all carry @guarded_task("broker_account_sync")
    # (tasks.py:300, :605, :801). This row said "(IBKR)" for months after the
    # other two arrived, so unticking it to stop IBKR stopped Saxo and eToro
    # with no warning anywhere. The old description also called it read-only
    # and said it touches no gate denominator: since pools can follow the
    # account, every follower's capital IS this reading times its share, and
    # the entry path freezes a follower whose reading has gone stale.
    {"key": "broker_account_sync", "name": "Broker Account Sync (Saxo · eToro · IBKR)",
     "description": "Caches equity and holdings for every keyed Saxo, eToro and IBKR account every 15 min — the source of every 'as the broker sees it' cell. ONE switch for all THREE walks: unticking it stops Saxo and eToro too. Every following pool's capital is this reading times its share.",
     "category": "pipeline"},

    # ── Share allocator ───────────────────────────────────────
    # Without these rows the @guarded_task on propose_share_plans skips on
    # every beat and /shares/ shows no plan without saying why.
    {"key": "pipeline_share_allocator", "name": "Share Allocator (proposer)",
     # Descriptions are a 300-char column, enforced on the VPS Postgres and
     # not on the SQLite suite: the first cut of these two was 600 chars,
     # seed_components failed on deploy and the stack stayed down (2026-09-12).
     "description": "Every 4h after the sync: a TARGET share of the account per live follower pool from graded evidence, regime, opportunity density and news risk, under floor/ceiling, a 10-pt/day cap and a drawdown governor. SHADOW by default: apply needs LIVE mode and the trading PIN. See /shares/.",
     "category": "pipeline"},
    {"key": "share_allocator_mode_live", "name": "Share Allocator Live Mode",
     "description": "Off (default) = shadow: plans are proposed and graded, apply is refused. On = an admin can apply a plan (PIN on /shares/, --yes on the shell), writing each follower's account_share_pct and re-sizing pools via the sync. Rollback restores exactly. Caps and the governor hold in both modes.",
     "category": "system"},
    # De-risk fast, re-risk slow (2026-09-12): the third switch. Off by
    # default; needs LIVE mode too. Description counted under 300 chars.
    {"key": "share_allocator_auto_derisk", "name": "Share Allocator Auto De-risk",
     "description": "Off (default). On + LIVE mode: a SHOCK plan that only LOWERS shares (every target <= current) is applied automatically, within the daily apply cap, with snapshot and rollback, and staff are notified. Re-risking is never automatic: a plan with any upward target waits for the PIN.",
     "category": "system"},

    # ── The capital desk (2026-09-12) ─────────────────────────
    # Without the first row `is_component_enabled` answers False,
    # run_all_asset_bots is the legacy config-after-config loop and the
    # desk never sees a candidate — which is the correct default, and the
    # reason the switch must exist before anything can be graded.
    # Descriptions counted under the 300-char Postgres column, like the
    # share allocator rows above.
    {"key": "pipeline_capital_desk", "name": "Capital Desk (fleet pass)",
     "description": "The fleet pass runs TWO-PHASE: every bot proposes first, the desk ranks the tick's entries on graded expected R per unit of marginal (correlation-aware) risk against one budget per venue, then they execute. SHADOW: nothing the bots do changes — the plan on /desk/ is the counterfactual being graded.",
     "category": "pipeline"},
    {"key": "capital_desk_mode_live", "name": "Capital Desk Live Mode",
     "description": "Off (default) = shadow: the plan is recorded and graded, the fleet is unchanged. On = the plan is OBEYED — displaced entries are skipped and chosen sizes multiplied, never above 1. The budget, the caps and every per-order refusal hold in both modes. Flip after weeks of positive edge, not before.",
     "category": "system"},

    # ── eToro fractional units (2026-09-23) ──────────────────────
    # Without this row _venue_fractional_units answers None and the stock
    # bot rounds to whole shares on eToro — the correct default. Description
    # under the 300-char Postgres column (the registry test measures it).
    {"key": "fractional_units_live", "name": "Fractional Units Live Mode (eToro)",
     "description": "Off (default) = the STOCK bot rounds to WHOLE shares on eToro. On = the sized fraction is sent. Crypto (8 dp) and commodity (4 dp) send fractions whatever this says; forex snaps to 100 units, to 1 only when ON and measured fractional. Flip only after D2c pins (deploy/ETORO_DEPARTURE.md section 4).",
     "category": "system"},

    # ── The Telegram eye (2026-09-26) ───────────────────────────
    # bot_program/telegram_eye.py answers the group every 15 s, in
    # English, to the configured staff chat only; its one write turns
    # bots OFF. OFF on arrival like every row here: after the deploy,
    # `manage.py component on telegram_eye`. One poll at a time holds a
    # batch, under a Postgres advisory lock, NOT this row: the gate's
    # mark_run writes it after every run and would wait behind it.
    # Description measured at 276 chars (< 300).
    {"key": "telegram_eye", "name": "Telegram Eye (group commands)",
     "description": "Answers the Sauron Vision Telegram group every 15 s, in English: /status, /positions, /why, /help and questions. Its only write to trading state is the brake: /stop and /stopall turn bots OFF, never on. Replies to the configured staff chat only. OFF on arrival: turning it on starts answering.",
     "category": "system"},

    # ── The three that were never registered (found live 2026-09-13) ────
    # These keys have guarded tasks and beat entries in this codebase, and
    # had NO row in DEFAULT_COMPONENTS. `is_component_enabled` returns
    # False for a key with no row, so the gate skipped all three on every
    # single run since the day they were written — silently, at INFO, one
    # line buried among thousands of bar lines. On the live box the
    # registry held 51 components and none of these.
    #
    # The old comment on RETIRED_COMPONENT_KEYS called them "admin-created
    # by hand". That is not a design, it is a dependency on somebody
    # remembering, and nobody did: price alerts were never checked and the
    # 07:00 and 17:00 digests were never sent. Seeding them here costs
    # nothing — is_enabled defaults to False, so each arrives OFF and the
    # operator turns on what they want. tests/test_component_registry.py
    # now fails if any guarded_task key is missing from this list.
    {"key": "pipeline_alerts", "name": "Price Alerts",
     "description": "Checks every active price alert against the current quote. OFF on arrival: turning it on starts evaluating alerts the operator may have set months ago.",
     "category": "pipeline"},
    {"key": "pipeline_digest", "name": "Morning and EOD Digests",
     "description": "The 07:00 and 17:00 UTC digests. OFF on arrival — turning it on SENDS messages outward on a schedule, so it is the operator's decision, not a deploy's.",
     "category": "pipeline"},
    {"key": "agent_commentator", "name": "Market Commentator",
     "description": "Daily market commentary from the commentator agent. OFF on arrival: it costs model spend on every run.",
     "category": "agent"},
    # 2026-09-15 — the watchdog for a paper campaign. `paper_readiness`
    # answers the question the moment it is asked; a campaign that starts
    # green and goes cold on day twelve spends seventy-eight days producing
    # nothing, and the only thing that would notice is somebody choosing to
    # run the command again. Nothing on this platform chose to.
    {"key": "pipeline_campaign_watch", "name": "Evidence Chain Watchdog",
     "description": "Daily read-only check that the paper-campaign evidence chain (bars -> indicators -> signals -> fills -> outcomes -> ladder) is still complete, and one notification when a link goes cold. Writes nothing and makes no broker call.",
     "category": "pipeline"},

    # ── eToro leverage (2026-09-23; the words 2026-09-26) ──────
    # A per-config extras["leverage"] is handed to EtoroTrader.market_order
    # as a body field. It changes the margin eToro locks, never the units
    # or the loss at the stop. OFF until the class's proof is in the
    # engine's proven set (asset_engine/base.py — NOT named here: a switch
    # must not be able to name the proof set, tests/test_etoro_proofs.py)
    # and a levered fill has printed its band (ETORO_DEPARTURE §7-0); the
    # engine also judges the multiplier against the instrument's LIVE
    # leverageValues (eligibility, measured 2026-09-23); a missing row
    # reads OFF. Read by asset_engine/base.judge_order_leverage on the
    # tick and by preflight_live §4. 2026-09-26: the platform cap is 20x
    # (forex and index 20, commodity 10, stock 5, crypto 2), and the
    # attack mode ("auto") sends 1x while this is OFF. The proven
    # multipliers bind "auto" only; a typed multiplier needs its class
    # proven, the class ceiling and the instrument's LIVE list.
    # Description measured at 299 chars (< 300).
    {"key": "etoro_leverage_live", "name": "eToro Leverage (per config)",
     "description": "Off (default): a typed extras['leverage'] above 1 is REFUSED at the tick and by preflight_live; 'auto' goes at 1x. On: up to 20x (forex, index; commodity 10x, stock 5x, crypto 2x) if in the instrument's LIVE leverageValues and its class is in the proven set; 'auto' is held to its proven multiplier.",
     "category": "system"},
]


# Components that once existed and were deliberately removed. Named
# explicitly rather than pruning everything outside DEFAULT_COMPONENTS,
# because an admin can create a row by hand and a blanket prune would
# silently disable it.
#
# This comment used to name pipeline_alerts, pipeline_digest and
# agent_commentator as the hand-made keys it was protecting. They are in
# DEFAULT_COMPONENTS now: "admin-created by hand" turned out to mean
# "never created at all" on the live box, and the gate had been skipping
# all three since they were written. Seeding beats remembering.
RETIRED_COMPONENT_KEYS = ["scraper_finviz"]


def seed_components():
    """Register all default components, and bury the retired ones.

    Without the delete, a removed component's row survives on deployed
    databases forever: the registry keeps listing it, its toggle keeps
    reporting "started" for a task that no longer exists, and the bulk
    scraper toggle keeps counting it.
    """
    PlatformComponent.objects.filter(key__in=RETIRED_COMPONENT_KEYS).delete()
    created = 0
    for comp in DEFAULT_COMPONENTS:
        row, was_created = PlatformComponent.objects.get_or_create(
            key=comp["key"],
            defaults=comp,
        )
        if was_created:
            created += 1
            continue
        # THE LABELS ARE THE CODE'S; THE SWITCH IS THE OPERATOR'S.
        #
        # `defaults` applies only on CREATION, so on every deployed database
        # the name, description and category froze the day the row was first
        # seeded — and a correction to any of them was inert in the one place
        # it was needed. `broker_account_sync` went on reading
        # "Broker Account Sync (IBKR)" for months after it began gating the
        # Saxo and eToro walks as well, and no edit to the table above could
        # have changed that.
        #
        # `is_enabled` is NEVER touched here, nor any counter or last-run
        # field. That is the operator's own state: a deploy that silently
        # flipped a component back ON would be a far worse bug than a stale
        # label, and a missing row already reads OFF by design.
        stale = [f for f in ("name", "description", "category")
                 if f in comp and getattr(row, f) != comp[f]]
        if stale:
            for field in stale:
                setattr(row, field, comp[field])
            row.save(update_fields=stale + ["updated_at"])
            logger.info("[components] %s: refreshed %s (the switch was left "
                        "as the operator set it)", comp["key"],
                        ", ".join(stale))
    return created
