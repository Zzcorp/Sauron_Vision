"""Celery tasks for AI agents — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inline helper agents (no dedicated module needed)
# ---------------------------------------------------------------------------

class DailyBriefingAgent:
    """Generates a concise morning briefing from daily market context."""

    agent_name = "daily_briefing"
    default_tier = "balanced"

    def __init__(self):
        from django.conf import settings
        ai_config = settings.AI_CONFIG
        provider_name = ai_config["default_provider"]
        model = ai_config["models"].get(self.default_tier, "claude-sonnet-5")
        self._provider_name = provider_name
        self._model = model
        self._provider = self._get_provider(provider_name)

    def _get_provider(self, provider_name):
        if provider_name == "claude":
            from ai_agents.providers.claude_provider import ClaudeProvider
            return ClaudeProvider()
        elif provider_name == "openai":
            from ai_agents.providers.openai_provider import OpenAIProvider
            return OpenAIProvider()
        elif provider_name == "ollama":
            from ai_agents.providers.ollama_provider import OllamaProvider
            return OllamaProvider()
        raise ValueError(f"Unknown AI provider: {provider_name}")

    def run(self, context: str) -> dict:
        from ai_agents.models import AgentTask
        import time

        system_prompt = (
            "You are the Sauron Vision Morning Briefing assistant. "
            "Given the current market state, active signals, strategies, recent news, "
            "and upcoming economic events, produce a concise, actionable morning briefing "
            "for a professional trader. Structure it as: Market Overview, Key Signals, "
            "Strategy Watch, News Highlights, Events to Watch. Be direct and data-driven."
        )

        start = time.time()
        try:
            raw, usage = self._provider.complete(
                system_prompt=system_prompt,
                user_message=context,
                model=self._model,
            )
            duration = time.time() - start
            AgentTask.objects.create(
                agent=self.agent_name,
                provider=self._provider_name,
                model=self._model,
                prompt_summary=context[:500],
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cost_usd=usage.get("cost_usd", 0),
                response_summary=raw[:500],
                structured_output={"briefing": raw},
                success=True,
                duration_seconds=round(duration, 2),
            )
            return {"briefing": raw}
        except Exception as e:
            duration = time.time() - start
            AgentTask.objects.create(
                agent=self.agent_name,
                provider=self._provider_name,
                model=self._model,
                prompt_summary=context[:500],
                success=False,
                error=str(e),
                duration_seconds=round(duration, 2),
            )
            raise


class MondayPlanAgent:
    """Generates a weekly game plan every Sunday evening."""

    agent_name = "monday_plan"
    default_tier = "balanced"

    def __init__(self):
        from django.conf import settings
        ai_config = settings.AI_CONFIG
        provider_name = ai_config["default_provider"]
        model = ai_config["models"].get(self.default_tier, "claude-sonnet-5")
        self._provider_name = provider_name
        self._model = model
        self._provider = self._get_provider(provider_name)

    def _get_provider(self, provider_name):
        if provider_name == "claude":
            from ai_agents.providers.claude_provider import ClaudeProvider
            return ClaudeProvider()
        elif provider_name == "openai":
            from ai_agents.providers.openai_provider import OpenAIProvider
            return OpenAIProvider()
        elif provider_name == "ollama":
            from ai_agents.providers.ollama_provider import OllamaProvider
            return OllamaProvider()
        raise ValueError(f"Unknown AI provider: {provider_name}")

    def run(self, context: str) -> dict:
        from ai_agents.models import AgentTask
        import time

        system_prompt = (
            "You are the Sauron Vision Monday Game Plan assistant. "
            "Given the portfolio state, active strategies, upcoming economic events this week, "
            "and the most recent weekly review, produce a structured weekly game plan for the "
            "coming trading week. Cover: Weekly Macro Outlook, Priority Strategies, Key Levels "
            "to Watch, Economic Event Risk, Position Sizing Guidance, and Risk Management Reminders. "
            "Be specific, reference the actual data provided, and prioritise actionability."
        )

        start = time.time()
        try:
            raw, usage = self._provider.complete(
                system_prompt=system_prompt,
                user_message=context,
                model=self._model,
            )
            duration = time.time() - start
            AgentTask.objects.create(
                agent=self.agent_name,
                provider=self._provider_name,
                model=self._model,
                prompt_summary=context[:500],
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cost_usd=usage.get("cost_usd", 0),
                response_summary=raw[:500],
                structured_output={"plan": raw},
                success=True,
                duration_seconds=round(duration, 2),
            )
            return {"plan": raw}
        except Exception as e:
            duration = time.time() - start
            AgentTask.objects.create(
                agent=self.agent_name,
                provider=self._provider_name,
                model=self._model,
                prompt_summary=context[:500],
                success=False,
                error=str(e),
                duration_seconds=round(duration, 2),
            )
            raise


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

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
    import json
    from django.utils import timezone
    from market_data.models import LiveQuote
    from alerts.models import Notification
    from ai_agents.agents.anomaly_detector import AnomalyDetectorAgent

    logger.info("Running AI anomaly detection")

    quotes = LiveQuote.objects.select_related("instrument").all()
    if not quotes:
        return {"status": "no_market_data"}

    lines = []
    for q in quotes:
        lines.append(
            f"{q.instrument.symbol}: last={q.last}, change_pct={q.change_pct}%, "
            f"volume={q.volume}, updated={q.updated_at.strftime('%H:%M:%S UTC')}"
        )
    market_data_str = "\n".join(lines)

    result = AnomalyDetectorAgent().run(market_data=market_data_str)

    anomalies = result.get("anomalies", [])
    severe = [a for a in anomalies if a.get("severity", 0) >= 7]

    if severe:
        descriptions = "; ".join(
            f"{a['symbol']} — {a['description']}" for a in severe[:5]
        )
        Notification.create_for_all(
            notification_type="system",
            title=f"Market Anomaly Alert ({len(severe)} severe)",
            body=descriptions,
            url="/market-data/",
        )
        logger.warning(f"Anomaly detection: {len(severe)} severe anomalies found.")

    return {
        "status": "success",
        "total_anomalies": len(anomalies),
        "severe_anomalies": len(severe),
        "market_stress_level": result.get("market_stress_level"),
        "notifications_sent": len(severe) > 0,
    }


@shared_task
@guarded_task("agent_strategy")
def review_active_strategies():
    """Tier 4: AI review of active strategies."""
    import json
    from strategies.models import Strategy, StrategyAdjustment
    from portfolio.models import Portfolio
    from ai_agents.agents.strategy_advisor import StrategyAdvisorAgent

    logger.info("AI reviewing active strategies")

    active_strategies = list(
        Strategy.objects.filter(status="active")
        .prefetch_related("legs", "source_signals", "positions")
    )

    if not active_strategies:
        return {"status": "no_active_strategies"}

    # Build signals list from all source signals across active strategies
    signals_seen = {}
    for strategy in active_strategies:
        for sig in strategy.source_signals.all():
            if sig.id not in signals_seen:
                signals_seen[sig.id] = {
                    "id": sig.id,
                    "title": sig.title,
                    "direction": sig.direction,
                    "score": sig.score,
                    "urgency": sig.urgency,
                    "signal_type": sig.signal_type,
                    "instrument": sig.instrument.symbol if sig.instrument else None,
                    "is_active": sig.is_active,
                }
    signals_list = list(signals_seen.values())

    # Build portfolio snapshot from the first portfolio (main)
    portfolio_obj = Portfolio.objects.first()
    if portfolio_obj:
        portfolio_dict = {
            "name": portfolio_obj.name,
            "current_value": str(portfolio_obj.current_value),
            "cash_available": str(portfolio_obj.cash_available),
            "currency": portfolio_obj.currency,
        }
        positions = portfolio_obj.positions.select_related("instrument", "strategy").filter(closed_at__isnull=True)
        exposure_dict = {}
        for pos in positions:
            symbol = pos.instrument.symbol
            exposure_dict[symbol] = {
                "direction": pos.direction,
                "quantity": str(pos.quantity),
                "entry_price": str(pos.entry_price),
                "current_price": str(pos.current_price),
                "unrealized_pnl": str(pos.unrealized_pnl),
                "unrealized_pnl_pct": pos.unrealized_pnl_pct,
            }
    else:
        portfolio_dict = {}
        exposure_dict = {}

    # Append summary of each active strategy to portfolio context
    portfolio_dict["active_strategies"] = [
        {
            "id": s.id,
            "name": s.name,
            "time_horizon": s.time_horizon,
            "pnl": str(s.pnl),
            "pnl_pct": s.pnl_pct,
            "max_drawdown": s.max_drawdown,
            "legs": [
                {
                    "symbol": leg.instrument.symbol,
                    "action": leg.action,
                    "weight": leg.weight,
                    "is_entered": leg.is_entered,
                }
                for leg in s.legs.all()
            ],
        }
        for s in active_strategies
    ]

    result = StrategyAdvisorAgent().run(
        signals=signals_list,
        portfolio=portfolio_dict,
        exposure=exposure_dict,
    )

    # Create StrategyAdjustment records for proposed changes
    adjustments_created = 0
    proposed_strategies = result.get("strategies", [])
    for proposal in proposed_strategies:
        # Match by name to existing active strategies if possible
        matched = next(
            (s for s in active_strategies if s.name.lower() in proposal.get("name", "").lower()),
            active_strategies[0] if active_strategies else None,
        )
        if matched is None:
            continue
        StrategyAdjustment.objects.create(
            strategy=matched,
            adjustment_type="ai_review",
            reason=proposal.get("thesis", "AI strategy review"),
            details={
                "proposal": proposal,
                "portfolio_notes": result.get("portfolio_notes", ""),
                "macro_assessment": result.get("macro_assessment", ""),
            },
        )
        adjustments_created += 1

    return {
        "status": "success",
        "strategies_reviewed": len(active_strategies),
        "proposals": len(proposed_strategies),
        "adjustments_created": adjustments_created,
        "portfolio_notes": result.get("portfolio_notes", ""),
    }


@shared_task
@guarded_task("agent_daily_briefing")
def generate_daily_briefing():
    """Tier 5: Generate morning briefing."""
    import json
    from django.utils import timezone
    from signals.models import Signal
    from strategies.models import Strategy
    from scraping.models import NewsArticle
    from market_data.models import EconomicEvent
    from portfolio.models import Portfolio
    from alerts.models import Notification

    logger.info("Generating AI daily briefing")

    now = timezone.now()
    today = now.date()

    # Active signals count
    active_signals = Signal.objects.filter(is_active=True)
    signal_count = active_signals.count()
    top_signals = list(active_signals.order_by("-score")[:5].values(
        "title", "direction", "score", "urgency"
    ))

    # Portfolio snapshot
    portfolio_obj = Portfolio.objects.first()
    portfolio_info = {}
    if portfolio_obj:
        portfolio_info = {
            "name": portfolio_obj.name,
            "current_value": str(portfolio_obj.current_value),
            "cash_available": str(portfolio_obj.cash_available),
            "currency": portfolio_obj.currency,
        }

    # Recent news (last 24 h, AI-processed)
    since_yesterday = now - timezone.timedelta(hours=24)
    recent_news = list(
        NewsArticle.objects.filter(
            ai_processed_at__gte=since_yesterday
        ).order_by("-ai_sentiment_score")[:7].values("title", "source", "ai_summary", "ai_urgency", "ai_sentiment_score")
    )

    # Upcoming economic events (today + tomorrow)
    upcoming_events = list(
        EconomicEvent.objects.filter(
            datetime__date__gte=today,
            datetime__date__lte=today + timezone.timedelta(days=1),
        ).order_by("datetime")[:10].values("title", "country", "datetime", "impact", "forecast")
    )

    # Active strategies
    active_strategies = list(
        Strategy.objects.filter(status="active").values(
            "name", "time_horizon", "pnl", "pnl_pct", "status"
        )
    )

    context = (
        f"DATE: {today.strftime('%A, %d %B %Y')}\n\n"
        f"ACTIVE SIGNALS ({signal_count} total):\n"
        f"{json.dumps(top_signals, indent=2, default=str)}\n\n"
        f"PORTFOLIO:\n{json.dumps(portfolio_info, indent=2, default=str)}\n\n"
        f"ACTIVE STRATEGIES:\n{json.dumps(active_strategies, indent=2, default=str)}\n\n"
        f"RECENT NEWS (last 24h):\n{json.dumps(recent_news, indent=2, default=str)}\n\n"
        f"UPCOMING ECONOMIC EVENTS:\n{json.dumps(upcoming_events, indent=2, default=str)}"
    )

    result = DailyBriefingAgent().run(context=context)
    briefing_text = result.get("briefing", "")

    Notification.create_for_all(
        notification_type="system",
        title=f"Morning Briefing — {today.strftime('%d %b %Y')}",
        body=briefing_text[:2000],
        url="/dashboard/",
    )

    return {
        "status": "success",
        "date": str(today),
        "briefing_length": len(briefing_text),
        "signals_included": signal_count,
        "news_included": len(recent_news),
        "events_included": len(upcoming_events),
    }


@shared_task
@guarded_task("agent_weekly_review")
def generate_weekly_review():
    """Tier 6: Saturday deep weekly review."""
    import json
    from django.utils import timezone
    from datetime import timedelta
    from strategies.models import Strategy
    from signals.models import Signal
    from portfolio.models import PortfolioSnapshot
    from scraping.models import NewsArticle
    from market_data.models import EconomicEvent
    from alerts.models import Newsletter
    from ai_agents.agents.weekly_reviewer import WeeklyReviewerAgent

    logger.info("Generating AI weekly review")

    now = timezone.now()
    week_ago = now - timedelta(days=7)

    # Portfolio snapshots for the last 7 days
    snapshots = list(
        PortfolioSnapshot.objects.filter(date__gte=week_ago.date())
        .order_by("date")
        .values(
            "date", "total_value", "cash", "daily_pnl", "daily_pnl_pct",
            "cumulative_pnl_pct", "max_drawdown", "sharpe_ratio",
            "exposure_by_asset_class", "exposure_by_sector",
        )
    )

    # Active + completed strategies this week
    strategies = list(
        Strategy.objects.filter(
            status__in=["active", "completed"]
        ).values(
            "name", "status", "time_horizon", "pnl", "pnl_pct",
            "max_drawdown", "sharpe_ratio", "created_at", "closed_at",
        )
    )

    # Signals created this week
    signals = list(
        Signal.objects.filter(created_at__gte=week_ago)
        .values(
            "title", "direction", "score", "urgency", "signal_type",
            "is_active", "outcome", "created_at",
        )
    )

    # AI-processed news this week
    news_articles = list(
        NewsArticle.objects.filter(ai_processed_at__gte=week_ago)
        .order_by("-ai_sentiment_score")[:20]
        .values("title", "source", "ai_summary", "ai_urgency", "ai_sentiment_score", "published_at")
    )
    news_digest = "\n".join(
        f"[{a['ai_urgency'].upper()}] {a['title']} — {a['ai_summary']}"
        for a in news_articles
    )

    # Economic events from the past week
    economic_events = list(
        EconomicEvent.objects.filter(
            datetime__gte=week_ago,
            datetime__lte=now,
        ).order_by("datetime")
        .values("title", "country", "datetime", "impact", "actual", "forecast", "previous")
    )

    result = WeeklyReviewerAgent().run(
        snapshots=json.dumps(snapshots, indent=2, default=str),
        strategies=json.dumps(strategies, indent=2, default=str),
        signals=json.dumps(signals, indent=2, default=str),
        macro="",
        news_digest=news_digest,
        economic_events=json.dumps(economic_events, indent=2, default=str),
    )

    review_text = result.get("review", "")
    week_label = now.strftime("Week of %d %b %Y")

    Newsletter.objects.create(
        title=f"Sauron Vision Weekly Review — {week_label}",
        frequency="weekly",
        status="ai_generated",
        content_markdown=review_text,
        ai_prompt=f"Weekly review for {week_label}. "
                  f"{len(snapshots)} portfolio snapshots, {len(signals)} signals, "
                  f"{len(strategies)} strategies.",
    )

    return {
        "status": "success",
        "week": week_label,
        "snapshots": len(snapshots),
        "strategies": len(strategies),
        "signals": len(signals),
        "news_articles": len(news_articles),
        "economic_events": len(economic_events),
        "review_length": len(review_text),
    }


@shared_task
@guarded_task("agent_optimization")
def optimize_strategies():
    """Tier 6: Saturday strategy optimization."""
    import json
    from strategies.models import Strategy, StrategyAdjustment
    from strategies.engine import StrategyEngine
    from portfolio.models import Portfolio
    from market_data.models import LiveQuote
    from ai_agents.agents.strategy_advisor import StrategyAdvisorAgent

    logger.info("Running AI strategy optimization")

    active_strategies = list(
        Strategy.objects.filter(status="active")
        .prefetch_related("legs__instrument", "source_signals", "positions")
    )

    if not active_strategies:
        return {"status": "no_active_strategies"}

    # Gather current market data for context
    quotes = {
        q.instrument.symbol: {
            "last": str(q.last),
            "change_pct": str(q.change_pct),
            "volume": q.volume,
        }
        for q in LiveQuote.objects.select_related("instrument").all()
    }

    # Portfolio context
    portfolio_obj = Portfolio.objects.first()
    portfolio_dict = {}
    exposure_dict = {}
    if portfolio_obj:
        portfolio_dict = {
            "current_value": str(portfolio_obj.current_value),
            "cash_available": str(portfolio_obj.cash_available),
            "currency": portfolio_obj.currency,
        }
        for pos in portfolio_obj.positions.select_related("instrument").filter(closed_at__isnull=True):
            exposure_dict[pos.instrument.symbol] = {
                "direction": pos.direction,
                "unrealized_pnl_pct": pos.unrealized_pnl_pct,
                "unrealized_pnl": str(pos.unrealized_pnl),
            }

    engine = StrategyEngine()
    adjustments_created = 0
    engine_results = {}

    for strategy in active_strategies:
        # Build per-strategy current data context
        strategy_symbols = [leg.instrument.symbol for leg in strategy.legs.all()]
        current_data = {sym: quotes.get(sym, {}) for sym in strategy_symbols}

        # Engine-based suggestions (rule-based)
        engine_suggestion = engine.suggest_adjustments(strategy, current_data=current_data)

        engine_results[strategy.id] = engine_suggestion

        if engine_suggestion.get("adjustments"):
            StrategyAdjustment.objects.create(
                strategy=strategy,
                adjustment_type="engine_optimization",
                reason="Automated engine optimization pass",
                details=engine_suggestion,
            )
            adjustments_created += 1

    # Aggregate signals across all active strategies for AI advisor
    signals_list = []
    seen_ids = set()
    for strategy in active_strategies:
        for sig in strategy.source_signals.all():
            if sig.id not in seen_ids:
                seen_ids.add(sig.id)
                signals_list.append({
                    "id": sig.id,
                    "title": sig.title,
                    "direction": sig.direction,
                    "score": sig.score,
                    "urgency": sig.urgency,
                    "instrument": sig.instrument.symbol if sig.instrument else None,
                    "is_active": sig.is_active,
                })

    portfolio_dict["active_strategies"] = [
        {
            "id": s.id,
            "name": s.name,
            "pnl_pct": s.pnl_pct,
            "max_drawdown": s.max_drawdown,
            "engine_suggestion": engine_results.get(s.id, {}),
        }
        for s in active_strategies
    ]

    ai_result = StrategyAdvisorAgent().run(
        signals=signals_list,
        portfolio=portfolio_dict,
        exposure=exposure_dict,
    )

    # Create StrategyAdjustment records for AI proposals
    for proposal in ai_result.get("strategies", []):
        matched = next(
            (s for s in active_strategies if s.name.lower() in proposal.get("name", "").lower()),
            active_strategies[0] if active_strategies else None,
        )
        if matched is None:
            continue
        StrategyAdjustment.objects.create(
            strategy=matched,
            adjustment_type="ai_optimization",
            reason=proposal.get("thesis", "AI optimization proposal"),
            details={
                "proposal": proposal,
                "portfolio_notes": ai_result.get("portfolio_notes", ""),
                "macro_assessment": ai_result.get("macro_assessment", ""),
            },
        )
        adjustments_created += 1

    return {
        "status": "success",
        "strategies_optimized": len(active_strategies),
        "adjustments_created": adjustments_created,
        "ai_proposals": len(ai_result.get("strategies", [])),
        "portfolio_notes": ai_result.get("portfolio_notes", ""),
    }


@shared_task
@guarded_task("agent_commentator")
def generate_daily_commentary():
    """Generate and post daily market commentary."""
    from ai_agents.agents.market_commentator import MarketCommentatorAgent
    from market_data.models import LiveQuote
    from signals.models import Signal
    from scraping.models import NewsArticle
    from market_data.models import EconomicEvent
    from alerts.models import Notification
    from django.utils import timezone
    from datetime import timedelta

    now = timezone.now()
    yesterday = now - timedelta(hours=24)

    # Gather market data
    quotes = LiveQuote.objects.select_related('instrument').order_by('-instrument__is_watchlist')[:20]
    market_data = "\n".join([
        f"{q.instrument.symbol}: {q.last} ({q.change_pct:+.2f}%)" for q in quotes
    ])

    # Top movers
    top_movers = LiveQuote.objects.select_related('instrument').order_by('-change_pct')[:5]
    movers_str = "\n".join([f"{q.instrument.symbol}: {q.change_pct:+.2f}%" for q in top_movers])

    # Active signals
    signals = Signal.objects.filter(is_active=True).select_related('instrument')[:10]
    signals_str = "\n".join([f"{s.instrument.symbol} {s.direction} (score: {s.score:.2f})" for s in signals])

    # News
    news = NewsArticle.objects.filter(published_at__gte=yesterday).order_by('-ai_sentiment_score')[:5]
    news_str = "\n".join([f"- {n.title}" for n in news])

    # Events
    events = EconomicEvent.objects.filter(datetime__gte=yesterday, datetime__lte=now + timedelta(hours=24))[:10]
    events_str = "\n".join([f"- {e.title} ({e.country})" for e in events])

    agent = MarketCommentatorAgent()
    result = agent.run(
        date=now.strftime('%Y-%m-%d'),
        market_data=market_data,
        top_movers=movers_str,
        signals_summary=signals_str,
        news_highlights=news_str,
        events=events_str,
    )

    # Post as notification
    commentary = result.get('commentary', '')
    Notification.create_for_all('system', 'Daily Market Commentary', commentary[:1000])

    return {"status": "success", "length": len(commentary)}


@shared_task
@guarded_task("agent_monday_plan")
def generate_monday_plan():
    """Tier 6: Sunday evening Monday game plan."""
    import json
    from django.utils import timezone
    from datetime import timedelta
    from strategies.models import Strategy
    from portfolio.models import Portfolio, PortfolioSnapshot
    from market_data.models import EconomicEvent
    from alerts.models import Notification, Newsletter

    logger.info("Generating Monday game plan")

    now = timezone.now()
    today = now.date()
    week_ahead = today + timedelta(days=7)

    # Current portfolio state
    portfolio_obj = Portfolio.objects.first()
    portfolio_info = {}
    if portfolio_obj:
        portfolio_info = {
            "name": portfolio_obj.name,
            "current_value": str(portfolio_obj.current_value),
            "cash_available": str(portfolio_obj.cash_available),
            "currency": portfolio_obj.currency,
            "max_single_position_pct": portfolio_obj.max_single_position_pct,
            "max_daily_loss_pct": portfolio_obj.max_daily_loss_pct,
        }
        latest_snapshot = (
            PortfolioSnapshot.objects.filter(portfolio=portfolio_obj)
            .order_by("-date")
            .first()
        )
        if latest_snapshot:
            portfolio_info["latest_snapshot"] = {
                "date": str(latest_snapshot.date),
                "total_value": str(latest_snapshot.total_value),
                "daily_pnl_pct": latest_snapshot.daily_pnl_pct,
                "cumulative_pnl_pct": latest_snapshot.cumulative_pnl_pct,
                "max_drawdown": latest_snapshot.max_drawdown,
                "exposure_by_asset_class": latest_snapshot.exposure_by_asset_class,
                "exposure_by_sector": latest_snapshot.exposure_by_sector,
            }

    # Active strategies
    active_strategies = list(
        Strategy.objects.filter(status="active")
        .values("name", "time_horizon", "pnl", "pnl_pct", "max_drawdown", "ai_reasoning")
    )

    # Economic events for the coming week
    upcoming_events = list(
        EconomicEvent.objects.filter(
            datetime__date__gte=today,
            datetime__date__lte=week_ahead,
        ).order_by("datetime")
        .values("title", "country", "datetime", "impact", "forecast", "currency_affected")
    )

    # Last weekly review newsletter (most recent ai_generated or approved)
    last_review = (
        Newsletter.objects.filter(
            frequency="weekly",
            status__in=["ai_generated", "approved", "sent"],
        )
        .order_by("-created_at")
        .first()
    )
    last_review_text = last_review.content_markdown[:3000] if last_review else "No previous weekly review available."

    context = (
        f"PLANNING DATE: {today.strftime('%A, %d %B %Y')} (for the week ahead)\n\n"
        f"PORTFOLIO STATE:\n{json.dumps(portfolio_info, indent=2, default=str)}\n\n"
        f"ACTIVE STRATEGIES ({len(active_strategies)}):\n"
        f"{json.dumps(active_strategies, indent=2, default=str)}\n\n"
        f"ECONOMIC EVENTS THIS WEEK:\n{json.dumps(upcoming_events, indent=2, default=str)}\n\n"
        f"LAST WEEKLY REVIEW:\n{last_review_text}"
    )

    result = MondayPlanAgent().run(context=context)
    plan_text = result.get("plan", "")

    Notification.create_for_all(
        notification_type="system",
        title=f"Monday Game Plan — {today.strftime('%d %b %Y')}",
        body=plan_text[:2000],
        url="/dashboard/",
    )

    return {
        "status": "success",
        "date": str(today),
        "plan_length": len(plan_text),
        "active_strategies": len(active_strategies),
        "events_this_week": len(upcoming_events),
    }


# ─── Phase 3: signal journal + decay investigation ─────────────────────────

def _ai_enabled() -> bool:
    """True iff Claude API key is configured. Tasks no-op silently otherwise."""
    import os
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())


@shared_task
@guarded_task("pipeline_ai_journal")
def journal_closed_signal_task(signal_id: int):
    """Phase-3: auto-generate a TradeJournalEntry for a closed Signal."""
    if not _ai_enabled():
        return {"status": "skipped", "reason": "no_anthropic_api_key"}

    from signals.models import Signal
    from ai_agents.agents.signal_journal import journal_closed_signal

    sig = Signal.objects.filter(id=signal_id).first()
    if sig is None:
        return {"status": "skipped", "reason": "signal_not_found", "signal_id": signal_id}

    entry = journal_closed_signal(sig)
    if entry is None:
        return {"status": "skipped", "reason": "below_threshold_or_active",
                "signal_id": signal_id}
    return {"status": "ok", "signal_id": signal_id, "entry_id": entry.id,
            "grade": entry.grade}


@shared_task
@guarded_task("pipeline_calibration")
def resolve_pending_calibrations():
    """Phase 6: nightly auto-resolver for AgentPredictions whose deadlines have passed.

    Walks every unresolved prediction past its `expected_resolution_at`,
    looks up ground truth (Signal closure or 30d rule expectancy), stamps
    `actual_value`, `was_correct`, `score`, and `evaluated_at`.

    The trust scores consumed by the risk gate read from these resolved
    predictions, so this task is the heartbeat of the calibration loop.
    """
    from ai_agents.calibration import resolve_pending_predictions
    result = resolve_pending_predictions()
    logger.info("Calibration auto-resolver: resolved=%d failed=%d",
                result.get("resolved", 0), result.get("failed", 0))
    return {"status": "ok", **result}


@shared_task
@guarded_task("pipeline_ai_decay")
def investigate_decaying_rules():
    """Phase-3 nightly task: investigate every rule that decay_flag flags as decaying."""
    if not _ai_enabled():
        return {"status": "skipped", "reason": "no_anthropic_api_key"}

    from signals.models import Signal
    from signals.performance import decay_flag
    from ai_agents.agents.decay_investigator import investigate_decaying_rule

    rules = (
        Signal.objects
        .filter(is_active=False).exclude(outcome="").exclude(rule_name="")
        .values_list("rule_name", flat=True).distinct()
    )

    decaying = [r for r in rules if r and decay_flag(r)["is_decaying"]]
    investigations = []
    for rn in decaying:
        try:
            inv = investigate_decaying_rule(rn)
            if inv:
                investigations.append({"rule_name": rn, "investigation_id": inv.id,
                                       "action": inv.recommended_action})
        except Exception as e:
            logger.warning("decay investigation failed for %s: %s", rn, e)

    return {
        "status": "ok",
        "rules_scanned": Signal.objects.filter(is_active=False).exclude(outcome="").exclude(rule_name="").values("rule_name").distinct().count(),
        "decaying": len(decaying),
        "investigations_created": len(investigations),
        "investigations": investigations,
    }

