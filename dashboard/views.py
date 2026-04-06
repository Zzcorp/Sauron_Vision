"""Sauron Vision — Dashboard Views (enriched)."""
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import timedelta
from django.db.models import Avg, Sum


@login_required
def dashboard(request):
    from instruments.models import Instrument
    from signals.models import Signal
    from strategies.models import Strategy
    from scraping.models import NewsArticle
    from ai_agents.models import AgentTask
    from market_data.models import EconomicEvent
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import Position, PortfolioSnapshot
    from core.market_calendar import is_forex_open, is_us_market_open, is_eu_market_open, is_weekend

    portfolio = get_or_create_default_portfolio()
    now = timezone.now()
    day_ago = now - timedelta(hours=24)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Portfolio metrics
    open_positions = Position.objects.filter(portfolio=portfolio, closed_at__isnull=True)
    total_unrealized = sum(float(p.unrealized_pnl) for p in open_positions)
    cash_pct = round(float(portfolio.cash_available) / max(float(portfolio.current_value), 1) * 100)

    latest_snapshot = PortfolioSnapshot.objects.filter(portfolio=portfolio).first()

    # Signal metrics
    active_signals = Signal.objects.filter(is_active=True)
    avg_score = active_signals.aggregate(avg=Avg("score"))["avg"]

    # Strategy metrics
    active_strats = Strategy.objects.filter(status__in=["active", "approved"])
    proposed_strats = Strategy.objects.filter(status="proposed")

    # News metrics
    news_24h_qs = NewsArticle.objects.filter(published_at__gte=day_ago)
    avg_sentiment = news_24h_qs.filter(ai_sentiment_score__isnull=False).aggregate(avg=Avg("ai_sentiment_score"))["avg"]

    # Economic calendar
    upcoming = EconomicEvent.objects.filter(datetime__gte=now)
    high_impact = upcoming.filter(impact="high")

    # AI metrics
    ai_24h = AgentTask.objects.filter(created_at__gte=day_ago)
    ai_mtd = AgentTask.objects.filter(created_at__gte=month_start)
    ai_total = ai_24h.count()
    ai_success = ai_24h.filter(success=True).count()
    ai_tokens = sum(t.input_tokens + t.output_tokens for t in ai_24h)
    last_task = AgentTask.objects.order_by("-created_at").first()

    context = {
        "page_id": "dashboard",
        "portfolio": portfolio,

        # Portfolio
        "daily_pnl_pct": "+{:.2f}".format(latest_snapshot.daily_pnl_pct) if latest_snapshot else "+0.00",
        "cash_pct": cash_pct,
        "total_unrealized_pnl": "{:.2f}".format(total_unrealized),
        "open_positions_count": open_positions.count(),
        "total_exposure_pct": 100 - cash_pct,
        "max_drawdown": "{:.2f}".format(latest_snapshot.max_drawdown) if latest_snapshot else "0.00",
        "sharpe_ratio": "{:.2f}".format(latest_snapshot.sharpe_ratio) if latest_snapshot and latest_snapshot.sharpe_ratio else "—",

        # Markets
        "instruments_count": Instrument.objects.filter(is_active=True).count(),
        "watchlist_count": Instrument.objects.filter(is_watchlist=True).count(),
        "active_signals_count": active_signals.count(),
        "bullish_count": active_signals.filter(direction="bullish").count(),
        "bearish_count": active_signals.filter(direction="bearish").count(),
        "avg_signal_score": "{:.2f}".format(avg_score) if avg_score else "—",
        "active_strategies_count": active_strats.count(),
        "proposed_strategies": proposed_strats.count(),

        # News
        "news_24h": news_24h_qs.count(),
        "avg_news_sentiment": "{:.2f}".format(avg_sentiment) if avg_sentiment else "—",

        # Economic calendar
        "upcoming_events": upcoming.count(),
        "high_impact_events": high_impact.count(),

        # AI
        "ai_tasks_24h": ai_total,
        "ai_success_rate": round(ai_success / ai_total * 100) if ai_total > 0 else 0,
        "ai_cost_24h": "${:.2f}".format(sum(float(t.cost_usd) for t in ai_24h)),
        "ai_cost_mtd": "${:.2f}".format(sum(float(t.cost_usd) for t in ai_mtd)),
        "ai_avg_duration": "{:.1f}".format(sum(t.duration_seconds for t in ai_24h) / ai_total if ai_total > 0 else 0),
        "ai_tokens_24h": "{:,}".format(ai_tokens),
        "last_agent_name": last_task.agent if last_task else "—",
        "last_agent_time": "{} ago".format(last_task.created_at.strftime("%H:%M")) if last_task else "—",

        # Exposure
        "exposure": {"stock": 0, "forex": 0, "commodity": 0, "cash": cash_pct},

        # Market sessions
        "forex_open": is_forex_open(),
        "us_open": is_us_market_open(),
        "eu_open": is_eu_market_open(),
        "is_weekend": is_weekend(),

        # Feed data
        "recent_signals": active_signals.select_related("instrument").order_by("-created_at")[:8],
        "active_strategies": active_strats.order_by("-created_at")[:5],
        "recent_news": NewsArticle.objects.order_by("-published_at")[:6],
        "recent_ai_tasks": AgentTask.objects.order_by("-created_at")[:8],
    }
    return render(request, "dashboard/dashboard.html", context)


@login_required
def instruments_list(request):
    from instruments.models import Instrument
    qs = Instrument.objects.filter(is_active=True)
    filter_type = request.GET.get("filter", "")
    if filter_type == "watchlist":
        qs = qs.filter(is_watchlist=True)
    elif filter_type in ["stock", "forex", "commodity", "index", "etf", "crypto"]:
        qs = qs.filter(asset_class=filter_type)
    return render(request, "dashboard/instruments_list.html", {"page_id": "instruments", "instruments": qs.order_by("asset_class", "symbol"), "filter": filter_type})


@login_required
def market_quotes(request):
    from market_data.models import LiveQuote
    return render(request, "dashboard/market_quotes.html", {"page_id": "quotes", "quotes": LiveQuote.objects.select_related("instrument").order_by("instrument__symbol")})


@login_required
def economic_calendar(request):
    from market_data.models import EconomicEvent
    return render(request, "dashboard/economic_calendar.html", {"page_id": "calendar", "events": EconomicEvent.objects.order_by("datetime")[:50]})


@login_required
def signals_list(request):
    from signals.models import Signal
    active_only = request.GET.get("active") == "1"
    qs = Signal.objects.select_related("instrument").order_by("-created_at")
    if active_only:
        qs = qs.filter(is_active=True)
    active_qs = Signal.objects.filter(is_active=True)
    return render(request, "dashboard/signals_list.html", {
        "page_id": "signals", "signals": qs[:100], "active_only": active_only,
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
    return render(request, "dashboard/strategies_list.html", {"page_id": "strategies", "strategies": qs[:50]})


@login_required
def strategy_detail(request, pk):
    from strategies.models import Strategy
    strategy = get_object_or_404(Strategy.objects.prefetch_related("legs__instrument", "adjustments"), pk=pk)
    return render(request, "dashboard/strategy_detail.html", {"page_id": "strategies", "strategy": strategy})


@login_required
def news_feed(request):
    from scraping.models import NewsArticle
    return render(request, "dashboard/news_feed.html", {"page_id": "news", "articles": NewsArticle.objects.prefetch_related("ai_affected_instruments").order_by("-published_at")[:100]})


@login_required
def portfolio_overview(request):
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import PortfolioSnapshot
    portfolio = get_or_create_default_portfolio()
    return render(request, "dashboard/portfolio_overview.html", {
        "page_id": "portfolio", "portfolio": portfolio,
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
        "avg_duration": "{:.1f}".format(sum(t.duration_seconds for t in tasks_24h_qs) / total_24h if total_24h > 0 else 0),
        "latest_briefing": AgentTask.objects.filter(agent__in=["strategy_advisor", "weekly_reviewer"], success=True).first(),
        "recent_tasks": AgentTask.objects.order_by("-created_at")[:20],
    })


@login_required
def ai_tasks_list(request):
    from ai_agents.models import AgentTask
    return render(request, "dashboard/ai_tasks_list.html", {"page_id": "ai_tasks", "tasks": AgentTask.objects.order_by("-created_at")[:200]})


@login_required
def profile(request):
    """User profile: personal info + trading preferences."""
    from django.contrib import messages
    from portfolio.trader_profile import TraderProfile

    profile_obj, _ = TraderProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        # Personal info (on User model)
        request.user.email = request.POST.get("email", request.user.email)
        request.user.first_name = request.POST.get("first_name", "")
        request.user.last_name = request.POST.get("last_name", "")
        request.user.save()

        # Profile fields
        profile_obj.display_name = request.POST.get("display_name", "")
        profile_obj.bio = request.POST.get("bio", "")
        profile_obj.location = request.POST.get("location", "")
        profile_obj.phone = request.POST.get("phone", "")
        profile_obj.timezone_preference = request.POST.get("timezone_preference", "UTC")

        # Trading profile
        profile_obj.experience_level = request.POST.get("experience_level", "intermediate")
        profile_obj.trading_style = request.POST.get("trading_style", "swing_trader")
        profile_obj.risk_appetite = request.POST.get("risk_appetite", "moderate")
        profile_obj.analysis_approach = request.POST.get("analysis_approach", "mixed")
        profile_obj.preferred_session = request.POST.get("preferred_session", "european")
        profile_obj.available_hours_per_day = float(request.POST.get("available_hours_per_day", 2))

        # Markets
        profile_obj.trade_stocks = "trade_stocks" in request.POST
        profile_obj.trade_forex = "trade_forex" in request.POST
        profile_obj.trade_commodities = "trade_commodities" in request.POST
        profile_obj.trade_crypto = "trade_crypto" in request.POST
        profile_obj.trade_indices = "trade_indices" in request.POST
        profile_obj.trade_bonds = "trade_bonds" in request.POST

        # Goals
        profile_obj.monthly_return_target_pct = float(request.POST.get("monthly_return_target_pct", 3))
        profile_obj.max_acceptable_drawdown_pct = float(request.POST.get("max_acceptable_drawdown_pct", 10))
        profile_obj.annual_income_target = request.POST.get("annual_income_target", 0) or 0

        # AI
        profile_obj.theme_mode = request.POST.get("theme_mode", profile_obj.theme_mode)
        profile_obj.ai_autonomy = request.POST.get("ai_autonomy", "suggest")
        profile_obj.ai_commentary_detail = request.POST.get("ai_commentary_detail", "detailed")

        # Notifications
        profile_obj.notify_channel = request.POST.get("notify_channel", "telegram")
        profile_obj.notify_signals = "notify_signals" in request.POST
        profile_obj.notify_strategies = "notify_strategies" in request.POST
        profile_obj.notify_news_critical = "notify_news_critical" in request.POST
        profile_obj.notify_portfolio = "notify_portfolio" in request.POST
        profile_obj.notify_weekly_review = "notify_weekly_review" in request.POST

        profile_obj.save()
        messages.success(request, "Profile updated successfully.")

        from django.shortcuts import redirect
        return redirect("profile")

    # Common timezones
    timezones = [
        "UTC", "Europe/Paris", "Europe/London", "Europe/Berlin", "Europe/Zurich",
        "US/Eastern", "US/Central", "US/Pacific",
        "Asia/Tokyo", "Asia/Shanghai", "Asia/Singapore", "Asia/Dubai",
        "Australia/Sydney", "Pacific/Auckland",
    ]

    return render(request, "dashboard/profile.html", {
        "page_id": "profile",
        "profile": profile_obj,
        "timezones": timezones,
        "experience_choices": TraderProfile.EXPERIENCE_CHOICES,
        "style_choices": TraderProfile.STYLE_CHOICES,
        "risk_choices": TraderProfile.RISK_CHOICES,
        "analysis_choices": TraderProfile.ANALYSIS_CHOICES,
        "session_choices": TraderProfile.SESSION_CHOICES,
    })


@login_required
def setup(request):
    """Account setup: capital, risk, eToro, manual positions."""
    import os
    from django.contrib import messages
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import Position
    from instruments.models import Instrument
    from django.utils import timezone

    portfolio = get_or_create_default_portfolio()

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "update_capital":
            portfolio.initial_capital = request.POST.get("initial_capital", portfolio.initial_capital)
            portfolio.current_value = request.POST.get("current_value", portfolio.current_value)
            portfolio.cash_available = request.POST.get("cash_available", portfolio.cash_available)
            portfolio.currency = request.POST.get("currency", portfolio.currency)
            portfolio.save()
            messages.success(request, "Portfolio capital updated successfully.")

        elif action == "update_risk":
            portfolio.max_total_exposure_pct = float(request.POST.get("max_exposure", 100))
            portfolio.max_single_position_pct = float(request.POST.get("max_position", 10))
            portfolio.max_daily_loss_pct = float(request.POST.get("max_daily_loss", 3))
            portfolio.max_correlation_threshold = float(request.POST.get("max_correlation", 0.7))
            portfolio.save()
            messages.success(request, "Risk limits updated successfully.")

        elif action == "connect_etoro":
            etoro_key = request.POST.get("etoro_api_key", "").strip()
            if etoro_key:
                # Store in env or DB (for simplicity, write to .env-like storage)
                os.environ["ETORO_API_KEY"] = etoro_key
                messages.success(request, "eToro API key saved. Use Sync to pull positions.")
            else:
                messages.error(request, "Please provide an eToro API key.")

        elif action == "sync_etoro":
            from market_data.adapters.etoro_adapter import sync_etoro_positions
            result = sync_etoro_positions()
            if result.get("status") == "success":
                messages.success(request, f"Synced {result['synced']} positions from eToro.")
            elif result.get("status") == "not_configured":
                messages.error(request, "eToro API key not configured.")
            else:
                messages.error(request, "Failed to sync eToro positions. Check your API key.")

        elif action == "add_position":
            symbol = request.POST.get("symbol", "").upper().strip()
            if symbol:
                instrument, _ = Instrument.objects.get_or_create(
                    symbol=symbol,
                    defaults={
                        "name": symbol,
                        "asset_class": request.POST.get("asset_class", "stock"),
                        "is_active": True,
                    }
                )
                Position.objects.create(
                    portfolio=portfolio,
                    instrument=instrument,
                    direction=request.POST.get("direction", "long"),
                    quantity=request.POST.get("quantity", 0),
                    entry_price=request.POST.get("entry_price", 0),
                    current_price=request.POST.get("entry_price", 0),
                    stop_loss=request.POST.get("stop_loss") or None,
                    take_profit=request.POST.get("take_profit") or None,
                    opened_at=timezone.now(),
                )
                messages.success(request, f"Position {symbol} added successfully.")
            else:
                messages.error(request, "Symbol is required.")

        from django.shortcuts import redirect
        return redirect("setup")

    # API keys status
    api_keys = [
        {"name": "Anthropic (Claude AI)", "configured": bool(os.getenv("ANTHROPIC_API_KEY")), "url": "https://console.anthropic.com", "url_label": "console.anthropic.com"},
        {"name": "Alpha Vantage", "configured": bool(os.getenv("ALPHA_VANTAGE_API_KEY")), "url": "https://www.alphavantage.co/support/#api-key", "url_label": "alphavantage.co"},
        {"name": "Twelve Data", "configured": bool(os.getenv("TWELVE_DATA_API_KEY")), "url": "https://twelvedata.com", "url_label": "twelvedata.com"},
        {"name": "Finnhub", "configured": bool(os.getenv("FINNHUB_API_KEY")), "url": "https://finnhub.io", "url_label": "finnhub.io"},
        {"name": "FMP", "configured": bool(os.getenv("FMP_API_KEY")), "url": "https://financialmodelingprep.com", "url_label": "financialmodelingprep.com"},
        {"name": "FRED", "configured": bool(os.getenv("FRED_API_KEY")), "url": "https://fred.stlouisfed.org/docs/api/api_key.html", "url_label": "fred.stlouisfed.org"},
        {"name": "eToro", "configured": bool(os.getenv("ETORO_API_KEY")), "url": "https://api-portal.etoro.com", "url_label": "api-portal.etoro.com"},
        {"name": "Telegram", "configured": bool(os.getenv("TELEGRAM_BOT_TOKEN")), "url": "https://core.telegram.org/bots#botfather", "url_label": "BotFather"},
    ]

    etoro_key = os.getenv("ETORO_API_KEY", "")
    etoro_masked = ("●" * 20 + etoro_key[-4:]) if len(etoro_key) > 4 else ""

    return render(request, "dashboard/setup.html", {
        "page_id": "setup",
        "portfolio": portfolio,
        "api_keys": api_keys,
        "etoro_connected": bool(etoro_key),
        "etoro_key_masked": etoro_masked,
    })


@login_required
def getting_started(request):
    return render(request, "dashboard/getting_started.html", {"page_id": "getting_started"})


@login_required
def toggle_theme(request):
    """Toggle light/dark theme via AJAX or form POST."""
    from portfolio.trader_profile import TraderProfile
    from django.http import JsonResponse
    from django.shortcuts import redirect

    profile, _ = TraderProfile.objects.get_or_create(user=request.user)
    profile.theme_mode = "light" if profile.theme_mode == "dark" else "dark"
    profile.save()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"theme": profile.theme_mode})
    return redirect(request.META.get("HTTP_REFERER", "dashboard"))


@login_required
def admin_dashboard(request):
    """Superuser admin dashboard — system overview."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Superuser access required.")

    import os
    from django.contrib.auth.models import User
    from instruments.models import Instrument
    from signals.models import Signal
    from strategies.models import Strategy
    from scraping.models import NewsArticle, SentimentSnapshot, COTReport, InstitutionalFiling
    from market_data.models import PriceData, LiveQuote, EconomicEvent, MacroIndicator
    from ai_agents.models import AgentTask
    from django.utils import timezone as tz
    from datetime import timedelta
    from django.db.models import Count, Avg

    now = tz.now()
    day_ago = now - timedelta(hours=24)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # AI stats by agent
    ai_24h = AgentTask.objects.filter(created_at__gte=day_ago)
    ai_mtd = AgentTask.objects.filter(created_at__gte=month_start)
    ai_total_24 = ai_24h.count()
    ai_success_24 = ai_24h.filter(success=True).count()
    ai_tokens = sum(t.input_tokens + t.output_tokens for t in ai_24h)

    agent_stats = []
    for agent_name in ai_24h.values_list("agent", flat=True).distinct():
        agent_qs = ai_24h.filter(agent=agent_name)
        agent_stats.append({
            "agent": agent_name,
            "total": agent_qs.count(),
            "success": agent_qs.filter(success=True).count(),
            "fails": agent_qs.filter(success=False).count(),
            "avg_time": "{:.1f}".format(sum(t.duration_seconds for t in agent_qs) / max(agent_qs.count(), 1)),
            "cost": "{:.4f}".format(sum(float(t.cost_usd) for t in agent_qs)),
        })

    # Asset class breakdown
    asset_classes = Instrument.objects.values("asset_class").annotate(count=Count("id")).order_by("asset_class")

    # API keys
    api_keys_status = [
        {"name": "Anthropic", "ok": bool(os.getenv("ANTHROPIC_API_KEY"))},
        {"name": "Alpha Vantage", "ok": bool(os.getenv("ALPHA_VANTAGE_API_KEY"))},
        {"name": "Twelve Data", "ok": bool(os.getenv("TWELVE_DATA_API_KEY"))},
        {"name": "Finnhub", "ok": bool(os.getenv("FINNHUB_API_KEY"))},
        {"name": "FMP", "ok": bool(os.getenv("FMP_API_KEY"))},
        {"name": "FRED", "ok": bool(os.getenv("FRED_API_KEY"))},
        {"name": "eToro Public", "ok": bool(os.getenv("ETORO_PUBLIC_KEY"))},
        {"name": "eToro User", "ok": bool(os.getenv("ETORO_USER_KEY"))},
        {"name": "Telegram", "ok": bool(os.getenv("TELEGRAM_BOT_TOKEN"))},
        {"name": "ScraperAPI (proxy)", "ok": bool(os.getenv("SCRAPER_API_KEY"))},
        {"name": "SERP API", "ok": bool(os.getenv("SERP_API_KEY"))},
    ]

    # Data sources health
    data_sources = [
        {"name": "Price Data (OHLCV)", "count": PriceData.objects.count(), "last_updated": PriceData.objects.order_by("-timestamp").values_list("timestamp", flat=True).first()},
        {"name": "Live Quotes", "count": LiveQuote.objects.count(), "last_updated": LiveQuote.objects.order_by("-updated_at").values_list("updated_at", flat=True).first()},
        {"name": "News Articles", "count": NewsArticle.objects.count(), "last_updated": NewsArticle.objects.order_by("-scraped_at").values_list("scraped_at", flat=True).first()},
        {"name": "Sentiment Snapshots", "count": SentimentSnapshot.objects.count(), "last_updated": SentimentSnapshot.objects.order_by("-timestamp").values_list("timestamp", flat=True).first()},
        {"name": "Economic Events", "count": EconomicEvent.objects.count(), "last_updated": None},
        {"name": "COT Reports", "count": COTReport.objects.count(), "last_updated": COTReport.objects.order_by("-report_date").values_list("report_date", flat=True).first()},
        {"name": "Institutional Filings", "count": InstitutionalFiling.objects.count(), "last_updated": InstitutionalFiling.objects.order_by("-filing_date").values_list("filing_date", flat=True).first()},
        {"name": "Macro Indicators", "count": MacroIndicator.objects.count(), "last_updated": None},
        {"name": "AI Agent Tasks", "count": AgentTask.objects.count(), "last_updated": AgentTask.objects.order_by("-created_at").values_list("created_at", flat=True).first()},
    ]

    context = {
        "page_id": "admin_dashboard",
        "total_users": User.objects.count(),
        "active_users": User.objects.filter(is_active=True).count(),
        "users": User.objects.order_by("-date_joined"),
        "total_instruments": Instrument.objects.count(),
        "watchlist_instruments": Instrument.objects.filter(is_watchlist=True).count(),
        "asset_class_counts": [{"class": ac["asset_class"], "count": ac["count"]} for ac in asset_classes],
        "active_signals": Signal.objects.filter(is_active=True).count(),
        "total_signals": Signal.objects.count(),
        "total_strategies": Strategy.objects.count(),
        "active_strategies": Strategy.objects.filter(status__in=["active", "approved"]).count(),
        "total_news": NewsArticle.objects.count(),
        "unprocessed_news": NewsArticle.objects.filter(ai_processed_at__isnull=True).count(),
        "ai_tasks_24h": ai_total_24,
        "ai_success_rate": round(ai_success_24 / max(ai_total_24, 1) * 100),
        "ai_cost_24h": "{:.2f}".format(sum(float(t.cost_usd) for t in ai_24h)),
        "ai_cost_mtd": "{:.2f}".format(sum(float(t.cost_usd) for t in ai_mtd)),
        "ai_tokens_24h": "{:,}".format(ai_tokens),
        "ai_avg_duration": "{:.1f}".format(sum(t.duration_seconds for t in ai_24h) / max(ai_total_24, 1)),
        "agent_stats": agent_stats,
        "api_keys_status": api_keys_status,
        "data_sources": data_sources,
    }
    # Platform components
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

    # Market configs
    from core.market_config import MarketConfig
    market_configs = MarketConfig.objects.all()
    context["market_configs"] = market_configs

    context["master_enabled"] = master_enabled
    context["components_by_category"] = components_by_category

    return render(request, "dashboard/admin_dashboard.html", context)


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


@login_required
def instrument_detail(request, symbol):
    """Instrument detail page with chart, indicators, signals, news."""
    import json
    from instruments.models import Instrument
    from market_data.models import PriceData, LiveQuote
    from indicators.models import TechnicalIndicator
    from signals.models import Signal
    from scraping.models import NewsArticle

    instrument = get_object_or_404(Instrument, symbol=symbol)

    # Get price data for chart
    prices = PriceData.objects.filter(
        instrument=instrument, timeframe="1d"
    ).order_by("timestamp")[:200]

    price_data = []
    for p in prices:
        price_data.append({
            "time": p.timestamp.strftime("%Y-%m-%d"),
            "open": float(p.open),
            "high": float(p.high),
            "low": float(p.low),
            "close": float(p.close),
        })

    # Get quote
    quote = None
    try:
        quote = instrument.live_quote
    except Exception:
        pass

    # Get latest technicals
    technicals = TechnicalIndicator.objects.filter(instrument=instrument).first()

    # Get signals
    signals = Signal.objects.filter(instrument=instrument).order_by("-created_at")[:10]

    # Get related news
    news = instrument.news_articles.order_by("-published_at")[:5]

    return render(request, "dashboard/instrument_detail.html", {
        "page_id": "instruments",
        "instrument": instrument,
        "quote": quote,
        "technicals": technicals,
        "signals": signals,
        "news": news,
        "price_data_json": json.dumps(price_data),
    })


@login_required
def backtest_list(request):
    """List all backtests for the current user."""
    from backtester.models import BacktestRun
    runs = BacktestRun.objects.filter(user=request.user).order_by("-created_at")[:50]
    return render(request, "dashboard/backtest_list.html", {
        "page_id": "backtest",
        "runs": runs,
    })


@login_required
def instrument_preview_api(request, symbol):
    """API endpoint for instrument hover preview."""
    from django.http import JsonResponse
    from instruments.models import Instrument
    from signals.models import Signal

    try:
        inst = Instrument.objects.get(symbol=symbol)
    except Instrument.DoesNotExist:
        return JsonResponse({"symbol": symbol, "error": "not_found"})

    # Get quote
    price = None
    change_pct = 0
    volume = None
    try:
        quote = inst.live_quote
        price = str(quote.last)
        change_pct = float(quote.change_pct)
        volume = str(quote.volume) if quote.volume else None
    except Exception:
        pass

    # Count signals
    active_signals = Signal.objects.filter(instrument=inst, is_active=True).count()

    return JsonResponse({
        "symbol": inst.symbol,
        "name": inst.name,
        "asset_class": inst.asset_class,
        "exchange": inst.exchange,
        "price": price,
        "change_pct": change_pct,
        "volume": volume,
        "active_signals": active_signals,
    })


@login_required
def admin_create_user(request):
    """Create a new user from admin popup."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    if request.method == "POST":
        from django.contrib.auth.models import User
        from django.contrib import messages
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        email = request.POST.get("email", "")
        first_name = request.POST.get("first_name", "")
        last_name = request.POST.get("last_name", "")
        is_staff = "is_staff" in request.POST
        is_superuser = "is_superuser" in request.POST

        if not username or not password:
            messages.error(request, "Username and password are required.")
        elif User.objects.filter(username=username).exists():
            messages.error(request, f"Username '{username}' already exists.")
        else:
            user = User.objects.create_user(
                username=username, password=password, email=email,
                first_name=first_name, last_name=last_name,
            )
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.save()
            messages.success(request, f"User '{username}' created successfully.")
    from django.shortcuts import redirect
    return redirect("admin_dashboard")


@login_required
def admin_toggle_market(request):
    """Toggle a market on/off from admin dashboard."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    if request.method == "POST":
        from core.market_config import MarketConfig
        from django.contrib import messages
        key = request.POST.get("market_key", "")
        try:
            market = MarketConfig.objects.get(market_key=key)
            market.is_enabled = not market.is_enabled
            market.save()
            action = "enabled" if market.is_enabled else "disabled"
            messages.success(request, f"{market.display_name} market {action}.")
        except MarketConfig.DoesNotExist:
            messages.error(request, f"Market '{key}' not found.")
    from django.shortcuts import redirect
    return redirect("admin_dashboard")


@login_required
def admin_newsletters(request):
    """Newsletter management page."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()

    from alerts.models import Newsletter
    from django.contrib import messages

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "create":
            nl = Newsletter.objects.create(
                title=request.POST.get("title", "Weekly Report"),
                frequency=request.POST.get("frequency", "weekly"),
                send_telegram="send_telegram" in request.POST,
                send_email="send_email" in request.POST,
                send_whatsapp="send_whatsapp" in request.POST,
                created_by=request.user,
            )
            # Auto-generate with AI
            from alerts.newsletter_service import generate_newsletter_with_ai
            generate_newsletter_with_ai(nl, nl.frequency)
            messages.success(request, f"Newsletter '{nl.title}' generated. Review before sending.")

        elif action == "approve":
            nl_id = request.POST.get("newsletter_id")
            nl = Newsletter.objects.get(id=nl_id)
            nl.status = "approved"
            nl.save()
            messages.success(request, f"Newsletter '{nl.title}' approved.")

        elif action == "send":
            nl_id = request.POST.get("newsletter_id")
            nl = Newsletter.objects.get(id=nl_id)
            from alerts.newsletter_service import send_newsletter
            result = send_newsletter(nl)
            if "error" in result:
                messages.error(request, result["error"])
            else:
                messages.success(request, f"Newsletter sent to {result['recipients']} recipients.")

        elif action == "edit":
            nl_id = request.POST.get("newsletter_id")
            nl = Newsletter.objects.get(id=nl_id)
            nl.content_markdown = request.POST.get("content", nl.content_markdown)
            nl.title = request.POST.get("title", nl.title)
            nl.save()
            messages.success(request, "Newsletter updated.")

        elif action == "delete":
            nl_id = request.POST.get("newsletter_id")
            Newsletter.objects.filter(id=nl_id).delete()
            messages.success(request, "Newsletter deleted.")

        from django.shortcuts import redirect
        return redirect("admin_newsletters")

    newsletters = Newsletter.objects.all()[:30]
    return render(request, "dashboard/admin_newsletters.html", {
        "page_id": "admin_newsletters",
        "newsletters": newsletters,
    })


@login_required
def user_notifications(request):
    """User notification preferences page."""
    from alerts.models import UserNotificationPrefs, AlertRule
    from django.contrib import messages

    prefs, _ = UserNotificationPrefs.objects.get_or_create(user=request.user)

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "save_prefs":
            prefs.telegram_chat_id = request.POST.get("telegram_chat_id", "")
            prefs.whatsapp_number = request.POST.get("whatsapp_number", "")
            prefs.email_notifications = "email_notifications" in request.POST
            prefs.sms_number = request.POST.get("sms_number", "")
            prefs.receive_signals = "receive_signals" in request.POST
            prefs.receive_strategies = "receive_strategies" in request.POST
            prefs.receive_news_alerts = "receive_news_alerts" in request.POST
            prefs.receive_portfolio_alerts = "receive_portfolio_alerts" in request.POST
            prefs.receive_weekly_newsletter = "receive_weekly_newsletter" in request.POST
            prefs.receive_monthly_newsletter = "receive_monthly_newsletter" in request.POST
            prefs.save()
            messages.success(request, "Notification preferences saved.")

        elif action == "add_rule":
            AlertRule.objects.create(
                user=request.user,
                name=request.POST.get("rule_name", "Custom Alert"),
                instrument_symbol=request.POST.get("rule_symbol", ""),
                asset_class=request.POST.get("rule_asset_class", ""),
                min_score=float(request.POST.get("rule_min_score", 0.5)),
                direction=request.POST.get("rule_direction", ""),
                notify_telegram="rule_telegram" in request.POST,
                notify_email="rule_email" in request.POST,
                notify_whatsapp="rule_whatsapp" in request.POST,
            )
            messages.success(request, "Alert rule created.")

        elif action == "delete_rule":
            rule_id = request.POST.get("rule_id")
            AlertRule.objects.filter(id=rule_id, user=request.user).delete()
            messages.success(request, "Alert rule deleted.")

        from django.shortcuts import redirect
        return redirect("user_notifications")

    rules = AlertRule.objects.filter(user=request.user)
    return render(request, "dashboard/user_notifications.html", {
        "page_id": "notifications",
        "prefs": prefs,
        "rules": rules,
    })


@login_required
def mark_notification_read(request, notif_id):
    """Mark a single notification as read."""
    from alerts.models import Notification
    from django.http import JsonResponse
    Notification.objects.filter(id=notif_id, user=request.user).update(read=True)
    return JsonResponse({"status": "ok"})


@login_required
def mark_all_notifications_read(request):
    """Mark all notifications as read."""
    from alerts.models import Notification
    from django.shortcuts import redirect
    Notification.objects.filter(user=request.user, read=False).update(read=True)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        from django.http import JsonResponse
        return JsonResponse({"status": "ok"})
    return redirect(request.META.get("HTTP_REFERER", "dashboard"))


@login_required
def ai_chat_api(request):
    """AI chat endpoint — send question to Claude, get response."""
    from django.http import JsonResponse
    import json, os

    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        data = json.loads(request.body)
        message = data.get("message", "")
    except Exception:
        return JsonResponse({"error": "Invalid request"}, status=400)

    if not message:
        return JsonResponse({"error": "Empty message"}, status=400)

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return JsonResponse({"response": "Anthropic API key not configured. Add ANTHROPIC_API_KEY to your .env file."})

    # Build context
    context_parts = [f"User: {request.user.username}"]
    try:
        from signals.models import Signal
        from portfolio.services import get_or_create_default_portfolio
        portfolio = get_or_create_default_portfolio(user=request.user)
        context_parts.append(f"Portfolio: {portfolio.currency} {portfolio.current_value}")
        active = Signal.objects.filter(is_active=True).count()
        context_parts.append(f"Active signals: {active}")
    except Exception:
        pass

    system_prompt = f"""You are Sauron Vision AI, a trading intelligence assistant.
You help traders analyze markets, review signals, and make informed decisions.
Current user context: {'; '.join(context_parts)}
Be concise, data-driven, and professional. Use markdown formatting."""

    try:
        import requests as req
        resp = req.post("https://api.anthropic.com/v1/messages", headers={
            "x-api-key": api_key,
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
        }, json={
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [{"role": "user", "content": message}],
        }, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        ai_text = result.get("content", [{}])[0].get("text", "No response")
        return JsonResponse({"response": ai_text})
    except Exception as e:
        return JsonResponse({"response": f"AI request failed: {str(e)}"})


@login_required
def ai_chat_page(request):
    """AI chat page."""
    from ai_agents.models import AgentTask
    from django.utils import timezone
    from datetime import timedelta
    now = timezone.now()
    day_ago = now - timedelta(hours=24)
    ai_24h = AgentTask.objects.filter(created_at__gte=day_ago)
    return render(request, "dashboard/ai_chat.html", {
        "page_id": "ai_chat",
        "ai_tasks_24h": ai_24h.count(),
        "ai_cost_24h": "{:.2f}".format(sum(float(t.cost_usd) for t in ai_24h)),
    })


@login_required
def intro_page(request):
    """Login intro animation — shows loading sequence then redirects to dashboard."""
    return render(request, "dashboard/intro.html")