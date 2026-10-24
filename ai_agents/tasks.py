"""Celery tasks for AI agents — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)
from ai_agents.calibration import (  # noqa: E402 — after the logger, like the rest
    CALLS_INSTRUCTION, clamp_horizon, extract_calls,
    log_direction_prediction, register_calls, register_proposal_calls,
)


# NO ACCOUNT MONEY IN A PROMPT (2026-10-24). The morning briefing, the
# Monday plan, the weekly review (the newsletter), the strategy advisor and
# the trade journal reach readers who are not staff: the bell of every
# active user, /briefing/, the letter, /ai/ and the AI ledger. Their prompts
# used to carry the lowest-id book's value and cash, the snapshots' totals,
# cash, daily P&L and exposure, the positions' sizes and P&L, all in money,
# and an answer could repeat any of them. They carry percentages, R and
# counts now; the account's size never reaches the model.


def _shares_pct(exposure) -> dict:
    """{key: its percent of the whole} for an exposure in money (a
    snapshot's by-class or by-sector notionals): the book's shape without
    its size. {} for anything else, or a whole of zero."""
    if not isinstance(exposure, dict):
        return {}
    try:
        values = {k: abs(float(v)) for k, v in exposure.items()}
    except (TypeError, ValueError):
        return {}
    total = sum(values.values())
    if total <= 0:
        return {}
    return {k: round(v / total * 100, 1) for k, v in values.items()}


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
        from ai_agents.catalog import resolve_agent
        model = resolve_agent(self.agent_name, self.default_tier)
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
            + CALLS_INSTRUCTION
        )

        start = time.time()
        try:
            # record=False: this inline agent writes its own richer
            # AgentTask row just below — the provider's built-in ledger
            # write would double-count it (same opt-out as BaseAgent.run).
            raw, usage = self._provider.complete(
                system_prompt=system_prompt,
                user_message=context,
                model=self._model,
                record=False,
            )
            duration = time.time() - start
            AgentTask.objects.create(
                agent=self.agent_name,
                provider=self._provider_name,
                model=usage.get("model") or self._model,
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
            # A refused/empty generation was still billed; the provider
            # hangs its usage on the exception so this failure row can
            # carry the real cost instead of a $0 that undercounts.
            billed = getattr(e, "usage", {}) or {}
            AgentTask.objects.create(
                agent=self.agent_name,
                provider=self._provider_name,
                model=billed.get("model") or self._model,
                prompt_summary=context[:500],
                input_tokens=billed.get("input_tokens", 0),
                output_tokens=billed.get("output_tokens", 0),
                cost_usd=billed.get("cost_usd", 0),
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
        from ai_agents.catalog import resolve_agent
        model = resolve_agent(self.agent_name, self.default_tier)
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

    def run(self, context: str, week=None) -> dict:
        """The plan for `context`. `week` (2026-09-27): the Monday of the
        week it is for, kept beside the whole text on this run's AgentTask
        row, the row /briefing/#monday-plan reads (ai_agents/monday_plan.py).
        """
        from ai_agents.models import AgentTask
        import time

        system_prompt = (
            "You are the Sauron Vision Monday Game Plan assistant. "
            "Given the portfolio state, active strategies, upcoming economic events this week, "
            "and the most recent weekly review, produce a structured weekly game plan for the "
            "coming trading week. Cover: Weekly Macro Outlook, Priority Strategies, Key Levels "
            "to Watch, Economic Event Risk, Position Sizing Guidance, and Risk Management Reminders. "
            "Be specific, reference the actual data provided, and prioritise actionability."
            + CALLS_INSTRUCTION
        )

        start = time.time()
        try:
            # record=False: this inline agent writes its own richer
            # AgentTask row just below — the provider's built-in ledger
            # write would double-count it (same opt-out as BaseAgent.run).
            raw, usage = self._provider.complete(
                system_prompt=system_prompt,
                user_message=context,
                model=self._model,
                record=False,
            )
            duration = time.time() - start
            AgentTask.objects.create(
                agent=self.agent_name,
                provider=self._provider_name,
                model=usage.get("model") or self._model,
                prompt_summary=context[:500],
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cost_usd=usage.get("cost_usd", 0),
                response_summary=raw[:500],
                # The WHOLE plan and its week: the store the page reads.
                structured_output=({"plan": raw, "week_of": week.isoformat()}
                                   if week is not None else {"plan": raw}),
                success=True,
                duration_seconds=round(duration, 2),
            )
            return {"plan": raw}
        except Exception as e:
            duration = time.time() - start
            # A refused/empty generation was still billed; the provider
            # hangs its usage on the exception so this failure row can
            # carry the real cost instead of a $0 that undercounts.
            billed = getattr(e, "usage", {}) or {}
            AgentTask.objects.create(
                agent=self.agent_name,
                provider=self._provider_name,
                model=billed.get("model") or self._model,
                prompt_summary=context[:500],
                input_tokens=billed.get("input_tokens", 0),
                output_tokens=billed.get("output_tokens", 0),
                cost_usd=billed.get("cost_usd", 0),
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

    # Speak the counts `core.task_gate.judge_result` already reads, instead of
    # a bare adjective. Until 2026-09-13 this returned {"status": "success",
    # "processed": processed} unconditionally: with no ANTHROPIC_API_KEY on
    # the box every one of the ten articles threw, each exception was
    # swallowed above, and the task reported SUCCESS with processed=0 every
    # five minutes. `agent_news_analyst` sat green while NewsArticle
    # .ai_sentiment_score was never written once — and two setups
    # (starter_news_event_bullish, generated_20260823_news_divergence_reclaim)
    # were blind on that column, which `setups diagnose` finally surfaced as
    # "only 1 sentiment-tagged articles".
    #
    # judge_result's WORK_KEYS/DONE_KEYS turn "attempted 10, stored 0" into a
    # warning by itself — the machinery was there, this caller just never used
    # its vocabulary. `processed` is kept for any existing reader.
    return {"status": "success", "processed": processed,
            "attempted": len(unprocessed), "stored": processed}


# An agent's answer is unbounded and the detail card is a popup, not a
# page. The title keeps stating how many were severe, so a truncated card
# under-shows rather than misreports.
MAX_ANOMALY_ITEMS = 12

# A quote the pollers have not touched in two scan cycles is a memory, not
# a reading. Handing it to the anomaly agent produced alerts ABOUT the
# staleness ("data timestamp 19:19:07 UTC is stale") — the scan reporting
# its own input problem as a market event.
ANOMALY_STALE_MINUTES = 120

# The scan runs hourly and a real anomaly does not expire in an hour, so
# the same reading re-alerted every cycle: one weekend produced the same
# four-severe TSLA/RICE/FX alert around the clock. One notification per
# (symbol, type) per window; the finding still counts in the task result,
# it just stops re-ringing the bell.
ANOMALY_REPEAT_COOLDOWN_S = 6 * 3600


def _fresh_open_quotes(quotes, now_utc):
    """The quotes the anomaly scan is allowed to reason about: markets that
    are open right now, readings younger than ANOMALY_STALE_MINUTES.

    The scan used to read the whole LiveQuote table around the clock. On a
    Saturday that table is Friday's closing prints wearing today's page:
    TSLA "up 5.14%" (frozen since the close), FX volume 0 (the market is
    shut), rice "moving" on 1,708 lots (a stale rotation row). The agent
    dutifully found anomalies in all of it, all weekend, because nothing
    told it the tape it was reading had stopped. A closed market cannot
    have a market anomaly — the anomaly was showing it the data at all.

    Returns (kept, dropped_closed, dropped_stale) so the task can say what
    it excluded rather than silently narrowing.
    """
    from datetime import timedelta
    from core.exchange_status import get_exchange_status, market_status_for

    # One clock read for the whole table — fourteen timezones once, not
    # once per instrument.
    status = get_exchange_status(now_utc)
    stale_before = now_utc - timedelta(minutes=ANOMALY_STALE_MINUTES)

    kept, dropped_closed, dropped_stale = [], 0, 0
    for q in quotes:
        market = market_status_for(q.instrument.asset_class,
                                   q.instrument.exchange, _status=status,
                                   symbol=q.instrument.symbol,
                                   now_utc=now_utc)
        if not market["is_open"]:
            dropped_closed += 1
            continue
        if q.updated_at < stale_before:
            dropped_stale += 1
            continue
        kept.append(q)
    return kept, dropped_closed, dropped_stale


def _anomaly_fingerprint(a: dict) -> "str | None":
    """What makes two severe anomalies "the same alert": the asset and the
    kind of anomaly. Not the description — the agent rephrases freely, and
    a cooldown keyed on prose would never match itself.

    None means "no stable identity, no cooldown": the agent's answer is
    model output and either field can come back blank, and every blank
    used to share ONE key — the first symbol-less anomaly would mute
    every different symbol-less anomaly for six hours. An anomaly this
    module cannot identify always rings; a repeated bell is cheaper than
    a silenced distinct alert.
    """
    symbol = str(a.get("symbol") or "").strip().upper()
    kind = str(a.get("type") or "").strip().lower()
    if not symbol or not kind:
        return None
    return f"anomaly:notified:{symbol}:{kind}"


def _anomaly_items(severe: list) -> list:
    """One card row per severe anomaly: the asset, what the scan saw, and
    a link to that asset's own page.

    An anomaly on a symbol we do not track carries no url. The row still
    names the asset — more than the flattened body line ever gave the
    reader — and one unrecognised symbol never costs the others their
    links.
    """
    from alerts.links import instrument_url

    items = []
    for a in severe[:MAX_ANOMALY_ITEMS]:
        symbol = str(a.get("symbol") or "").strip()
        description = str(a.get("description") or "").strip()
        severity = a.get("severity")
        detail = f"severity {severity} · {description}" if severity else description
        items.append({
            "label": symbol or "—",
            "detail": detail or "—",
            "url": instrument_url(symbol),
        })
    return items


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

    now = timezone.now()
    fresh, dropped_closed, dropped_stale = _fresh_open_quotes(quotes, now)
    if not fresh:
        # Saturday, mostly: every non-crypto market shut and no crypto
        # quote young enough. Scanning anyway is how a weekend produced
        # hourly "TSLA up 5.14%, no apparent catalyst" alerts about
        # Friday's close.
        return {
            "status": "skipped",
            "reason": (f"no open-market quotes fresh enough to scan "
                       f"({dropped_closed} closed-market, "
                       f"{dropped_stale} stale excluded)"),
        }

    lines = []
    for q in fresh:
        lines.append(
            f"{q.instrument.symbol}: last={q.last}, change_pct={q.change_pct}%, "
            f"volume={q.volume}, updated={q.updated_at.strftime('%H:%M:%S UTC')}"
        )
    market_data_str = (
        f"Snapshot time: {now.strftime('%A %H:%M UTC')}. Only instruments "
        f"whose market is OPEN right now are listed; closed markets and "
        f"stale rows are already excluded — do not infer anything from an "
        f"instrument's absence.\n" + "\n".join(lines)
    )

    result = AnomalyDetectorAgent().run(market_data=market_data_str)

    anomalies = result.get("anomalies", [])
    severe = [a for a in anomalies if a.get("severity", 0) >= 7]

    # An anomaly that implies a direction is a call the calibration can
    # grade; one without is a description. The call's confidence is the
    # detector's own probability of that direction, even odds when it
    # states none — never the severity: severity says how bad the
    # anomaly is, and a severity-3 "up" stored as "30% up" was
    # Brier-scored as a call that expected DOWN. The same symbol is not
    # stacked while a call is live.
    calls_registered = 0
    for a in anomalies:
        if not isinstance(a, dict):
            continue
        pred = log_direction_prediction(
            "anomaly_detector", a.get("symbol"), a.get("expected_direction"),
            horizon_hours=clamp_horizon(a.get("horizon_hours"), 24.0),
            confidence=a.get("confidence", 0.5),
            notes=str(a.get("description") or "")[:300])
        if pred is not None:
            calls_registered += 1

    # The agent re-detects the same condition every hour for as long as it
    # holds — correctly. Re-NOTIFYING it every hour is the spam. Anything
    # alerted within the cooldown window stays out of this notification;
    # a dead cache fails open (alert again) because a lost reminder is
    # cheaper than a lost alert.
    from django.core.cache import cache
    suppressed = 0
    fresh_severe = []
    for a in severe:
        key = _anomaly_fingerprint(a)
        try:
            if key and cache.get(key):
                suppressed += 1
                continue
        except Exception:
            pass
        fresh_severe.append(a)
    severe = fresh_severe

    if severe:
        # .get, not indexing: the agent's answer is model output, and one
        # missing key here used to raise before the notification was built
        # — losing the whole alert over a formatting detail.
        descriptions = "; ".join(
            f"{a.get('symbol') or '—'} — {a.get('description') or '—'}"
            for a in severe[:5]
        )
        items = _anomaly_items(severe)
        # One severe anomaly has exactly one underlying asset, so the click
        # belongs on that asset's page — the scan knew the symbol and made
        # the operator go find it in a list of every quote. Several share no
        # single destination and keep /quotes/, which renders the same
        # LiveQuote table the scan read ("/market-data/" was never a route
        # and 404ed for months). An untracked symbol falls back too: every
        # asset is reachable from the list, none from a 404.
        # Deep-link whenever every severe anomaly points at the SAME asset,
        # not only when there is exactly one of them. The scan fires
        # repeatedly on one instrument — nine times on EURGBP in a day is an
        # ordinary reading — and "several anomalies, all on EURGBP" is the
        # case where the operator most wants to land on EURGBP. It used to
        # count rows rather than distinct assets, so that alert dropped them
        # on the quotes list to find it themselves.
        urls = {i["url"] for i in items if i.get("url")}
        deep_link = urls.pop() if len(urls) == 1 else ""
        Notification.create_for_all(
            notification_type="system",
            title=f"Market Anomaly Alert ({len(severe)} severe)",
            body=descriptions,
            url=deep_link or "/quotes/",
            # The body flattens seven anomalies into one prose line and the
            # url can only point at one page; this is where each anomaly
            # keeps its own asset and its own link.
            data={"items": items},
        )
        # Stamped AFTER the notification went out: a stamp-then-fail order
        # would silence the next six hours of a condition nobody was told
        # about.
        for a in severe:
            key = _anomaly_fingerprint(a)
            if not key:
                continue  # no identity, no cooldown — it rings every time
            try:
                cache.set(key, True, ANOMALY_REPEAT_COOLDOWN_S)
            except Exception:
                pass
        logger.warning(f"Anomaly detection: {len(severe)} severe anomalies found.")

    return {
        "status": "success",
        "total_anomalies": len(anomalies),
        "severe_anomalies": len(severe),
        "suppressed_repeats": suppressed,
        "quotes_scanned": len(fresh),
        "excluded_closed_market": dropped_closed,
        "excluded_stale": dropped_stale,
        "market_stress_level": result.get("market_stress_level"),
        "notifications_sent": len(severe) > 0,
        "calls_registered": calls_registered,
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

    # Build portfolio snapshot from the first portfolio (main): its name,
    # never its value, cash or a position's size or P&L in money (see
    # _shares_pct above, 2026-10-24).
    portfolio_obj = Portfolio.objects.first()
    if portfolio_obj:
        portfolio_dict = {
            "name": portfolio_obj.name,
            "currency": portfolio_obj.currency,
        }
        positions = portfolio_obj.positions.select_related("instrument", "strategy").filter(closed_at__isnull=True)
        exposure_dict = {}
        for pos in positions:
            symbol = pos.instrument.symbol
            exposure_dict[symbol] = {
                "direction": pos.direction,
                "entry_price": str(pos.entry_price),
                "current_price": str(pos.current_price),
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
    calls_registered = 0
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
        # The legs it proposed become calls the calibration grades — the
        # StrategyAdjustment table is read by nobody, the grade is.
        calls_registered += register_proposal_calls("strategy_advisor",
                                                    proposal)

    return {
        "status": "success",
        "strategies_reviewed": len(active_strategies),
        "proposals": len(proposed_strategies),
        "adjustments_created": adjustments_created,
        "calls_registered": calls_registered,
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

    # NO PORTFOLIO SECTION (2026-10-24): the briefing goes to the bell of
    # every active user, staff or not, and it was handed the lowest-id
    # book's value and cash. Nothing about the account's money is given.

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
            "name", "time_horizon", "pnl_pct", "status"
        )
    )

    context = (
        f"DATE: {today.strftime('%A, %d %B %Y')}\n\n"
        f"ACTIVE SIGNALS ({signal_count} total):\n"
        f"{json.dumps(top_signals, indent=2, default=str)}\n\n"
        f"ACTIVE STRATEGIES:\n{json.dumps(active_strategies, indent=2, default=str)}\n\n"
        f"RECENT NEWS (last 24h):\n{json.dumps(recent_news, indent=2, default=str)}\n\n"
        f"UPCOMING ECONOMIC EVENTS:\n{json.dumps(upcoming_events, indent=2, default=str)}"
    )

    result = DailyBriefingAgent().run(context=context)
    briefing_text = result.get("briefing", "")
    # The views it stated become calls the calibration grades.
    calls_registered = register_calls("daily_briefing",
                                      extract_calls(briefing_text))
    # Sauron reads its own report (ai_agents/next_steps.py, 2026-10-03):
    # the steps it recommends become proposals on /briefing/#next-steps.
    # Never raises; a reader that fails does not fail the report.
    from ai_agents.next_steps import extract as _extract_steps
    _extract_steps("daily_briefing", briefing_text)

    Notification.create_for_all(
        notification_type="system",
        title=f"Morning Briefing — {today.strftime('%d %b %Y')}",
        body=briefing_text[:2000],
        url="/briefing/",
    )

    return {
        "status": "success",
        "date": str(today),
        "briefing_length": len(briefing_text),
        "signals_included": signal_count,
        "news_included": len(recent_news),
        "events_included": len(upcoming_events),
        "calls_registered": calls_registered,
    }


def _sizing_words(gap) -> str:
    """risk_gate.sizing_gap's note as a ratio, never the money: the review
    becomes the newsletter, and the note quoted the pools and the book
    (2026-10-24). "" when the pools fit the book."""
    if not gap.get("text"):
        return ""
    book = float(gap.get("book") or 0)
    n = gap.get("configs") or 0
    if book > 0:
        size = (f"totalling {float(gap.get('pools') or 0) / book:,.1f} "
                f"times the book")
        research = float(gap.get("research_pools") or 0)
        if research:
            size += f" (and research pools of {research / book:,.1f} times it)"
    else:
        size = "against an empty book"
    return (f"Sized by {n} paper pool{'' if n == 1 else 's'} {size} — the "
            f"percentages and the drawdown measure the book, not the money "
            f"that sized the positions.")


def _sizing_notes(portfolio_names) -> dict:
    """{portfolio name: sizing note (_sizing_words)} for the books the
    review reads — "" for a book whose paper pools fit it, or whose owner
    cannot be named (the shared "Main" book has no owner). Never raises: a note
    that cannot be read is an empty note, not a missing review."""
    from django.contrib.auth import get_user_model
    from portfolio.models import Portfolio
    from portfolio.risk_gate import sizing_gap
    from portfolio.services import PER_USER_SUFFIX
    out = {}
    for name in portfolio_names:
        text = ""
        try:
            if name and name.endswith(PER_USER_SUFFIX):
                username = name[: -len(PER_USER_SUFFIX)]
                user = get_user_model().objects.filter(
                    username=username).first()
                book = Portfolio.objects.filter(name=name).first()
                if user is not None and book is not None:
                    text = _sizing_words(sizing_gap(user, book))
        except Exception as e:  # noqa: BLE001
            logger.warning("[weekly review] sizing note for %s unreadable: %s",
                           name, e)
        out[name] = text
    return out


# ── The weekly review reads the live book (2026-10-08) ───────────────────
# The wiring audit of 2026-10-08 ("the weekly review grades wizard plans
# nothing executes, with macro passed as an empty string"): the review read
# PortfolioSnapshot and strategies.Strategy — wizard plans nothing executes
# (dashboard/views.py) — and passed macro="" although its prompt requires a
# macro regime section. It is the operator's one weekly synthesis, and it
# seeds the newsletter, the Monday plan and the pause or size-cut proposals.
# It now reads what the book did: the closed trades per rule and class from
# bot_grading.bot_performance_summary, LIVE, DEMO and PAPER apart and
# labelled by the platform's three worlds (position_summary.world_of: a
# broker's demo account is paper=False, never real money);
# the scorecard per lane (bots, the hand lane); the skip counters; Morgul's
# findings and the brakes of the week; the latest FRED observations and the
# measured market stress. R and counts, never a balance.

#: The days the weekly review reads.
WEEK_DAYS = 7
#: Rows per book and configs in the skips, so a large fleet stays readable.
WEEK_MAX_ROWS = 40


def _r4(value):
    try:
        return None if value is None else round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _week_book(world: str, words: str, now) -> dict:
    """One world's week: closed trades per (rule, class) and the scorecard
    per lane. `world` is one of position_summary.world_of's three: "live"
    (real money), "demo" (simulated at a broker's demo account), "paper"
    (simulated). By world, not by venue (2026-10-08, review): the venue
    split is paper=False, and a demo row is paper=False, so the "LIVE BOOK
    (real money)" used to count eToro demo closes as money made or lost."""
    from datetime import timedelta
    from bot_program import scorecard
    from bot_program.bot_grading import VENUE_ALL, bot_performance_summary
    since = now - timedelta(days=WEEK_DAYS)
    rows = bot_performance_summary(since=since, venue=VENUE_ALL, world=world)
    by_rule = [{"rule_name": r["rule_name"], "asset_class": r["asset_class"],
                "n": r["n"], "n_wins": r["n_wins"],
                "n_losses": r["n_losses"], "win_rate": _r4(r["win_rate"]),
                "expectancy_r": _r4(r["expectancy"]),
                "avg_duration_min": r["avg_duration_min"]}
               for r in rows[:WEEK_MAX_ROWS]]
    lanes = {}
    trades = scorecard.rows(days=WEEK_DAYS, now=now, world=world)
    for lane, group in scorecard.group(trades, lambda r: r["lane"]).items():
        s = scorecard.summarize(group)
        lanes[lane] = {"n": s["n"], "unmeasured": s["unmeasured"],
                       "thin_sample": s["thin"],
                       "win_rate": _r4(s["win_rate"]),
                       "avg_win_r": _r4(s["avg_win"]),
                       "avg_loss_r": _r4(s["avg_loss"]),
                       "expectancy": _r4(s["expectancy"]),
                       "sum_r": _r4(s["sum_r"]),
                       "closed_by_hand": s["by_hand"],
                       "targets_hit": s["targets_hit"],
                       "gave_back_after_1r": s["gave_back"],
                       "stops_that_did_not_hold": s["overshoot"],
                       "diagnosis": scorecard.diagnosis(s)}
    return {"venue": words, "days": WEEK_DAYS,
            "n_closed_graded": sum(r["n"] for r in rows),
            "by_rule": by_rule, "scorecard": lanes,
            "note": ("rule_name manual_take is the hand lane: trades the "
                     "operator took by hand; lane 'manual' in the "
                     "scorecard is the same trades")}


def _week_skips() -> dict:
    """Why the bots did not trade: each config's top skip codes and the
    one-sentence diagnosis (asset_engine/skips.py)."""
    from bot_program.asset_engine import skips
    from bot_program.models import AssetBotConfig
    configs = []
    for cfg in AssetBotConfig.objects.order_by("-enabled", "pk")[:200]:
        counts = skips.summary(cfg)
        if not counts:
            continue
        configs.append({
            "config": cfg.name, "asset_class": cfg.asset_class,
            "mode": cfg.mode, "enabled": bool(cfg.enabled),
            "top": [{"code": k, "count": v}
                    for k, v in list(counts.items())[:5]],
            "diagnosis": skips.diagnose(cfg)})
        if len(configs) >= WEEK_MAX_ROWS:
            break
    return {"configs": configs,
            "note": ("the counters are cumulative since each config's "
                     "counters began, not this week alone: read the "
                     "distribution, not the totals")}


def _week_guards(now) -> dict:
    """Every Morgul finding still standing, with when it was first seen
    and whether that was this week, and the brakes of the week from the
    audit chain (AuditLogEntry config_braked).

    EVERY STANDING FINDING (2026-10-08, review): Morgul rewrites its state
    each run (morgul._store, a 7-day TTL renewed every five minutes), so a
    finding is kept for as long as it stands and dropped when it clears.
    One first seen two weeks ago and still standing is live; it used to be
    left out of the week as if it were not."""
    from datetime import timedelta
    from django.utils.dateparse import parse_datetime
    since = now - timedelta(days=WEEK_DAYS)
    findings = []
    try:
        from bot_program import morgul
        state = morgul._load(morgul.STATE_KEY) or {}
        for entry in state.values():
            if not isinstance(entry, dict):
                continue
            first = parse_datetime(str(entry.get("first") or ""))
            findings.append({"guard": entry.get("name") or entry.get("guard"),
                             "severity": entry.get("severity"),
                             "label": str(entry.get("label") or "")[:200],
                             "first_seen": (first.isoformat() if first
                                            else None),
                             "new_this_week": bool(first and first >= since),
                             "braked": bool(entry.get("braked"))})
        findings.sort(key=lambda f: f["first_seen"] or "", reverse=True)
        findings = findings[:WEEK_MAX_ROWS]
    except Exception as e:  # noqa: BLE001 — a section, never the review
        logger.warning("[weekly review] Morgul's findings unread: %s", e)
    brakes = []
    try:
        from bot_program.audit import CONFIG_BRAKED
        from bot_program.audit_models import AuditLogEntry
        for row in (AuditLogEntry.objects
                    .filter(kind=CONFIG_BRAKED, created_at__gte=since)
                    .order_by("-created_at")[:WEEK_MAX_ROWS]):
            d = row.data or {}
            brakes.append({"config": d.get("config"),
                           "by": d.get("by_words") or d.get("by"),
                           "brake": bool(d.get("brake")),
                           "at": row.created_at.isoformat(),
                           "why": str(d.get("why") or "")[:200]})
    except Exception as e:  # noqa: BLE001
        logger.warning("[weekly review] brakes unread: %s", e)
    return {"findings": findings, "brakes": brakes,
            "note": ("findings: every Morgul finding still standing, with "
                     "when it was first seen (new_this_week says whether "
                     "that was this week); one that cleared is not kept. "
                     "brakes: 'brake' true means the bot kept managing its "
                     "open positions and opened nothing new")}


def _week_macro(now) -> dict:
    """The latest FRED observation of every series the platform reads
    (core.constants.FRED_SERIES), the previous one WITH ITS DATE, and the
    measured market stress with the crisis-mode switch. Never empty: a
    missing series is said.

    THE PREVIOUS OBSERVATION, DATED (2026-10-08, review): "week_ago" was
    the newest observation 7 days before the last, which for a monthly
    series (FEDFUNDS, CPIAUCSL, UNRATE, M2SL) is last month's release and
    for GDP last quarter's, printed as a week's change. A series that
    prints more often than weekly (its last two observations under 7 days
    apart: the daily ones) is compared with its value a week before; any
    other with the release before its last. Either way the date is said."""
    from datetime import timedelta
    from core.constants import FRED_SERIES
    from market_data.models import MacroObservation
    fred = {}
    for series_id, name in FRED_SERIES.items():
        obs = list(MacroObservation.objects
                   .filter(indicator__series_id=series_id)
                   .order_by("-date")[:2])
        if not obs:
            fred[series_id] = {"name": name, "missing": True}
            continue
        last = obs[0]
        before = obs[1] if len(obs) > 1 else None
        if before is not None and (last.date - before.date).days < WEEK_DAYS:
            before = (MacroObservation.objects
                      .filter(indicator__series_id=series_id,
                              date__lte=last.date - timedelta(days=WEEK_DAYS))
                      .order_by("-date").first())
        fred[series_id] = {
            "name": name, "value": _r4(last.value),
            "date": last.date.isoformat(),
            "age_days": (now.date() - last.date).days,
            "previous": _r4(before.value) if before else None,
            "previous_date": before.date.isoformat() if before else None}
    stored = [k for k, v in fred.items() if not v.get("missing")]
    out = {"fred": fred,
           "fred_note": ("" if stored else
                         "no FRED observation stored: the FRED scrape has "
                         "not run or has no key; say so, do not guess")}
    try:
        from bot_program import market_stress
        from bot_program.posture import crisis_mode_on
        cur = market_stress.current(now)
        out["market_stress"] = {
            "level": cur.get("level"), "score": cur.get("score"),
            "fresh": bool(cur.get("fresh")), "why": cur.get("why"),
            "what_it_does": market_stress.POSTURE_WORDS.get(
                cur.get("level"), "")}
        out["crisis_mode_on"] = bool(crisis_mode_on())
    except Exception as e:  # noqa: BLE001
        out["market_stress"] = {"level": None,
                                "why": f"unreadable: {type(e).__name__}"}
        out["crisis_mode_on"] = None
    out["note"] = ("market_stress is the posture the platform MEASURES; it "
                   "sizes real-money orders only while crisis_mode_on is "
                   "true")
    return out


def weekly_book_context(now=None) -> dict:
    """The live book's week for the weekly review: {live_book, demo_book,
    paper_book, skips, guards, macro}. Each section is fenced: one that
    cannot be read says so and the others stand."""
    from django.utils import timezone
    from dashboard.position_summary import WORLD_DEMO, WORLD_LIVE, WORLD_PAPER
    now = now or timezone.now()
    out = {}
    builders = (
        ("live_book", lambda: _week_book(
            WORLD_LIVE, "live: real money", now)),
        ("demo_book", lambda: _week_book(
            WORLD_DEMO, "demo: simulated at a broker's demo account "
                        "(eToro demo), not money", now)),
        ("paper_book", lambda: _week_book(
            WORLD_PAPER, "paper: simulated", now)),
        ("skips", _week_skips),
        ("guards", lambda: _week_guards(now)),
        ("macro", lambda: _week_macro(now)),
    )
    for key, build in builders:
        try:
            out[key] = build()
        except Exception as e:  # noqa: BLE001
            logger.warning("[weekly review] %s unread: %s", key, e)
            out[key] = {"unreadable": f"{type(e).__name__}: {e}"[:200]}
    return out


@shared_task
@guarded_task("agent_weekly_review")
def generate_weekly_review():
    """Tier 6: Saturday deep weekly review, built from the live book
    (weekly_book_context, 2026-10-08)."""
    import json
    from django.utils import timezone
    from datetime import timedelta
    from signals.models import Signal
    from portfolio.models import PortfolioSnapshot
    from scraping.models import NewsArticle
    from market_data.models import EconomicEvent
    from ai_agents.agents.weekly_reviewer import WeeklyReviewerAgent

    logger.info("Generating AI weekly review")

    now = timezone.now()
    week_ago = now - timedelta(days=7)

    # Portfolio snapshots for the last 7 days — NAMED (2026-10-04): the
    # review of 2026-10-02 had to call two unnamed series "Portfolio A"
    # and "Portfolio B", and graded B "critical, -97.6% drawdown" on a 500
    # book whose positions a 10,000 manual pool had sized. Each row says
    # which book it is and, when that book's paper pools exceed it, that
    # its percentages measure the book and not the money that sized the
    # positions (risk_gate.sizing_gap).
    # In percent (2026-10-24): the review becomes the newsletter, so no
    # total, cash, daily P&L or exposure in money; the exposure is each
    # class's and sector's share of the whole.
    snapshots = list(
        PortfolioSnapshot.objects.filter(date__gte=week_ago.date())
        .order_by("portfolio__name", "date")
        .values(
            "portfolio__name", "date",
            "daily_pnl_pct", "cumulative_pnl_pct", "max_drawdown",
            "sharpe_ratio", "exposure_by_asset_class", "exposure_by_sector",
        )
    )
    notes = _sizing_notes({s["portfolio__name"] for s in snapshots})
    for s in snapshots:
        s["portfolio"] = s.pop("portfolio__name")
        s["sizing_note"] = notes.get(s["portfolio"], "")
        s["exposure_by_asset_class_pct"] = _shares_pct(
            s.pop("exposure_by_asset_class"))
        s["exposure_by_sector_pct"] = _shares_pct(
            s.pop("exposure_by_sector"))

    # THE LIVE BOOK (2026-10-08): what the bots and the hand lane closed,
    # live and paper apart; the scorecard per lane; the skips; the guards
    # and the brakes; FRED and the measured stress. strategies.Strategy
    # (wizard plans NOTHING executes) is no longer read: a plan that never
    # traded was graded as if it had.
    book = weekly_book_context(now)
    live, paper = book.get("live_book") or {}, book.get("paper_book") or {}
    demo = book.get("demo_book") or {}
    scorecards = {"live (real money)": live.get("scorecard"),
                  "demo (simulated at eToro)": demo.get("scorecard"),
                  "paper (simulated)": paper.get("scorecard")}

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

    def _j(value):
        return json.dumps(value, indent=1, default=str)

    result = WeeklyReviewerAgent().run(
        snapshots=_j(snapshots),
        live_book=_j({k: v for k, v in live.items() if k != "scorecard"}),
        demo_book=_j({k: v for k, v in demo.items() if k != "scorecard"}),
        paper_book=_j({k: v for k, v in paper.items() if k != "scorecard"}),
        scorecard=_j(scorecards),
        skips=_j(book.get("skips")),
        guards=_j(book.get("guards")),
        signals=_j(signals),
        macro=_j(book.get("macro")),
        news_digest=news_digest,
        economic_events=_j(economic_events),
    )

    review_text = result.get("review", "")
    calls_registered = register_calls("weekly_reviewer",
                                      extract_calls(review_text))
    # Sauron reads its own report (ai_agents/next_steps.py, 2026-10-03):
    # the steps it recommends become proposals on /briefing/#next-steps.
    # Never raises; a reader that fails does not fail the report.
    from ai_agents.next_steps import extract as _extract_steps
    _extract_steps("weekly_review", review_text)
    week_label = now.strftime("Week of %d %b %Y")

    # THE REVIEW IS THE WEEK'S LETTER (2026-09-29). It used to land as an
    # ai_generated row nobody was told about. weekly_draft makes it the
    # edition: READY, scheduled for the next Sunday 08:00 Paris (sent by
    # alerts.tasks.send_due_newsletters unless cancelled), any older
    # waiting weekly edition cancelled, and the staff told at once, on the
    # bell and on Telegram, when it goes out and where to read, edit or
    # cancel it. generate_monday_plan reads this row's content as before.
    from alerts.newsletter_service import weekly_draft
    newsletter, announced = weekly_draft(
        review_text, now=now,
        prompt=f"Weekly review for {week_label}. "
               f"{len(snapshots)} portfolio snapshots, {len(signals)} signals, "
               f"{live.get('n_closed_graded', 0)} live, "
               f"{demo.get('n_closed_graded', 0)} demo and "
               f"{paper.get('n_closed_graded', 0)} paper graded closes.")

    return {
        "status": "success",
        "week": week_label,
        "newsletter_id": newsletter.pk,
        "scheduled_for": (newsletter.scheduled_for.isoformat()
                          if newsletter.scheduled_for else None),
        "staff_told": announced,
        "snapshots": len(snapshots),
        "live_closes": live.get("n_closed_graded", 0),
        "demo_closes": demo.get("n_closed_graded", 0),
        "paper_closes": paper.get("n_closed_graded", 0),
        "signals": len(signals),
        "news_articles": len(news_articles),
        "economic_events": len(economic_events),
        "review_length": len(review_text),
        "calls_registered": calls_registered,
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
        # No value, cash or P&L in money (2026-10-24, see _shares_pct).
        portfolio_dict = {
            "currency": portfolio_obj.currency,
        }
        for pos in portfolio_obj.positions.select_related("instrument").filter(closed_at__isnull=True):
            exposure_dict[pos.instrument.symbol] = {
                "direction": pos.direction,
                "unrealized_pnl_pct": pos.unrealized_pnl_pct,
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
    calls_registered = 0
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
        calls_registered += register_proposal_calls("strategy_advisor",
                                                    proposal)

    return {
        "status": "success",
        "strategies_optimized": len(active_strategies),
        "adjustments_created": adjustments_created,
        "ai_proposals": len(ai_result.get("strategies", [])),
        "calls_registered": calls_registered,
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


#: The oldest weekly review the Monday plan reads (2026-10-24): the
#: Saturday review runs a day before the plan, so eight days covers one
#: missed week's margin and never an old review fed back for months.
REVIEW_MAX_AGE_DAYS = 8


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
    from alerts.models import Newsletter
    from ai_agents import monday_plan as mp

    logger.info("Generating Monday game plan")

    now = timezone.now()
    today = now.date()
    week_ahead = today + timedelta(days=7)

    # Current portfolio state
    portfolio_obj = Portfolio.objects.first()
    portfolio_info = {}
    # In percent (2026-10-24): the plan goes to the bell of every active
    # user and /briefing/, so no value, cash, total or exposure in money.
    if portfolio_obj:
        portfolio_info = {
            "name": portfolio_obj.name,
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
                "daily_pnl_pct": latest_snapshot.daily_pnl_pct,
                "cumulative_pnl_pct": latest_snapshot.cumulative_pnl_pct,
                "max_drawdown": latest_snapshot.max_drawdown,
                "exposure_by_asset_class_pct": _shares_pct(
                    latest_snapshot.exposure_by_asset_class),
                "exposure_by_sector_pct": _shares_pct(
                    latest_snapshot.exposure_by_sector),
            }

    # Active strategies
    active_strategies = list(
        Strategy.objects.filter(status="active")
        .values("name", "time_horizon", "pnl_pct", "max_drawdown", "ai_reasoning")
    )

    # Economic events for the coming week
    upcoming_events = list(
        EconomicEvent.objects.filter(
            datetime__date__gte=today,
            datetime__date__lte=week_ahead,
        ).order_by("datetime")
        .values("title", "country", "datetime", "impact", "forecast", "currency_affected")
    )

    # The last weekly review: the latest row the Saturday review WROTE
    # (origin "weekly_review") with content, whatever became of its email
    # (review, 2026-09-29). Picking by send status skipped a review whose
    # letter was cancelled or failed on Sunday morning, and the Sunday
    # evening plan read a review a week older. An empty row (the model
    # answered nothing) and an admin-made edition are not the review.
    #
    # RECENT ONLY (2026-10-24): the newest of the last REVIEW_MAX_AGE_DAYS.
    # A review written before 2026-10-24 was made from the book's value,
    # cash, P&L and exposure in money, and the plan goes to the bell of
    # every active user: an old review is never fed back, week after week,
    # while agent_weekly_review is off.
    last_review = (
        Newsletter.objects.filter(
            origin="weekly_review",
            created_at__gte=now - timedelta(days=REVIEW_MAX_AGE_DAYS))
        .exclude(content_markdown="")
        .order_by("-created_at", "-pk")
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

    # THE PLAN, READ WHOLE (2026-09-27). The operator: "the monday game
    # plan is not fully visible it seems, only on hover". It went to the
    # bell alone, cut at 2,000 characters, linked to a page that never
    # showed it. The whole text stays on the run's own AgentTask row with
    # the week it is for; /briefing/#monday-plan shows it; the bell and
    # the staff group get a short summary and the way to it.
    week = mp.week_of(now)
    result = MondayPlanAgent().run(context=context, week=week)
    plan_text = result.get("plan", "")
    calls_registered = register_calls("monday_plan", extract_calls(plan_text))
    # Sauron reads its own report (ai_agents/next_steps.py, 2026-10-03):
    # the steps it recommends become proposals on /briefing/#next-steps.
    # Never raises; a reader that fails does not fail the report.
    from ai_agents.next_steps import extract as _extract_steps
    _extract_steps("monday_plan", plan_text)
    announced = mp.announce(plan_text, week)

    return {
        "status": "success",
        "date": str(today),
        "week_of": str(week),
        "announced": announced,
        "plan_length": len(plan_text),
        "active_strategies": len(active_strategies),
        "events_this_week": len(upcoming_events),
        "calls_registered": calls_registered,
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
    # THE COUNCIL (2026-10-08, ai_agents/council_grading.py): graded right
    # after the direction calls above (the Opportunist's are among them)
    # and after the 03:00 consolidation resolved the hypothesis market
    # (the Theorist's theories). No beat of its own: it rides this one.
    try:
        from ai_agents.council_grading import grade_due
        council = grade_due()
    except Exception as e:  # noqa: BLE001 — the council never breaks calibration
        logger.warning("[council] grading failed: %s", e)
        council = {"error": type(e).__name__}
    return {"status": "ok", **result, "council": council}


@shared_task(soft_time_limit=300, time_limit=330)
def run_council_sitting(session_id):
    """THE COUNCIL's sitting (2026-10-08, ai_agents/agents/council.py):
    three waves of shadow voices on one live bot order that has left, or
    on one live ticket its owner asked about. On the ai queue
    (ai_agents.tasks.* routes there). Idempotent: only a queued session
    is claimed. Worst case three waves of COUNCIL_WAVE_TIMEOUT_S, inside
    the soft limit; no order ever waits for it."""
    from ai_agents.agents.council import run_sitting
    out = run_sitting(int(session_id))
    # THE COUNCIL BAND (2026-10-22): tell the owner's open band that a
    # sitting closed, so its badge and its next read wake on it. One
    # fenced push to the page's own eye socket: no banner (the page has no
    # words for this kind), nothing to any chat, never a raise.
    if (out or {}).get("status") != "noop":
        try:
            from ai_agents.council_models import CouncilSession
            from dashboard.consumers import push_eye_event
            s = (CouncilSession.objects.select_related("user", "config__user")
                 .filter(id=int(session_id)).first())
            if s is not None:
                owner = s.user or (s.config.user if s.config_id else None)
                verdict = (s.voices.filter(voice="emperor", status="spoke")
                           .values_list("verdict", flat=True).first() or "")
                push_eye_event(owner, "council_sitting", {
                    "session": s.id, "origin": s.origin, "symbol": s.symbol,
                    "side": s.side, "status": s.status, "verdict": verdict})
        except Exception as e:  # noqa: BLE001 — the band is beside the sitting
            logger.info("[council] band event not sent: %s", type(e).__name__)
    return out


@shared_task
@guarded_task("pipeline_ai_decay")
def investigate_decaying_rules():
    """Phase-3 nightly task: investigate every rule that decay_flag flags
    as decaying.

    The decay scan and the evolution trigger run BEFORE the AI-key gate —
    both are pure DB statistics and component checks, no LLM anywhere.
    Behind the gate they were silently dead on keyless deployments (a
    supported mode), so a rule could decay all week while the operator
    believed the nightly reflex existed."""
    from signals.models import Signal
    from signals.performance import decay_flag

    # order_by clears Signal's Meta.ordering — left in place it rides into
    # the DISTINCT, returning one row per (rule_name, created_at) pair, and
    # every decayed rule got investigated once per duplicate occurrence.
    rules = (
        Signal.objects
        .filter(is_active=False).exclude(outcome="").exclude(rule_name="")
        .values_list("rule_name", flat=True)
        .distinct().order_by("rule_name")
    )

    decaying = [r for r in rules if r and decay_flag(r)["is_decaying"]]

    # Event-driven evolution: confirmed decay IS the trigger — the fix
    # proposal goes on the operator's desk tonight, not next Sunday, key
    # or no key. Fully gated inside (component switches, schema, stale-
    # proposal expiry, open-proposal dedupe) and never raises.
    evolutions_triggered = 0
    for rn in decaying:
        try:
            from signals.evolution import propose_if_fresh
            out = propose_if_fresh(rn)
            evolutions_triggered += out.get("proposed", 0)
        except Exception as e:  # noqa: BLE001
            logger.warning("decay-triggered evolution failed for %s: %s", rn, e)

    if not _ai_enabled():
        return {"status": "skipped", "reason": "no_anthropic_api_key",
                "decaying": len(decaying),
                "evolutions_triggered": evolutions_triggered}

    from ai_agents.agents.decay_investigator import investigate_decaying_rule

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
        "rules_scanned": Signal.objects.filter(is_active=False).exclude(outcome="").exclude(rule_name="").order_by().values("rule_name").distinct().count(),
        "decaying": len(decaying),
        "investigations_created": len(investigations),
        "investigations": investigations,
        "evolutions_triggered": evolutions_triggered,
    }

