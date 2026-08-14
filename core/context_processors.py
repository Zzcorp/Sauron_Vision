"""Global context processors for Sauron Vision."""
import logging
from .exchange_status import get_exchange_status

logger = logging.getLogger(__name__)


def sauron_context(request):
    """Inject all global data into every template."""

    # ── Timezone ──
    user_tz = "UTC"
    if hasattr(request, "user") and request.user.is_authenticated:
        try:
            user_tz = request.user.trader_profile.timezone_preference or "UTC"
        except Exception:
            pass

    # ── Exchange status ──
    try:
        exchange_data = get_exchange_status()
    except Exception:
        exchange_data = {"open_count": 0, "total": 14, "exchanges": []}

    # ── Enabled markets ──
    try:
        from core.market_config import MarketConfig
        enabled_markets = list(MarketConfig.objects.filter(is_enabled=True).values_list("market_key", flat=True))
    except Exception:
        enabled_markets = ["stock", "forex", "commodity"]

    # ── Defaults ──
    ctx = {
        "user_timezone": user_tz,
        "exchanges_open_count": exchange_data["open_count"],
        "exchanges_total": exchange_data["total"],
        "exchanges_list": exchange_data["exchanges"],
        "enabled_markets": enabled_markets,
        "ticker_items": [],
        "notification_count": 0,
        "recent_notifications": [],
        "panel_portfolio_value": "0",
        "panel_cash": "0",
        "panel_cash_pct": 100,
        "panel_positions": 0,
        "panel_exposure": 0,
        "panel_signals": 0,
        "panel_bullish": 0,
        "panel_bearish": 0,
        "panel_strategies": 0,
        "panel_proposed": 0,
        "panel_news": 0,
        "panel_sentiment": "—",
        "panel_ai_cost": "0.00",
        "panel_ai_tasks": 0,
        "panel_drawdown": "0.0",
        "panel_max_dd": "3.0",
        "panel_daily_pnl": 0,
        "panel_daily_pnl_display": "+0.00%",
        "panel_watchlist": 0,
        "panel_recent_signals": [],
        "panel_recent_positions": [],
        "panel_recent_news": [],
        "panel_recent_strategies": [],
    }

    if not hasattr(request, "user") or not request.user.is_authenticated:
        return ctx

    # ── Notifications ──
    try:
        from alerts.models import Notification
        ctx["notification_count"] = Notification.unread_count(request.user)
        ctx["recent_notifications"] = list(Notification.recent(request.user, limit=10))
    except Exception as e:
        logger.debug(f"Notifications unavailable: {e}")

    # ── Ticker + Panel ──
    try:
        from market_data.models import LiveQuote
        from signals.models import Signal
        from scraping.models import NewsArticle
        from strategies.models import Strategy
        from django.utils import timezone as tz
        from datetime import timedelta

        now = tz.now()
        day_ago = now - timedelta(hours=24)
        ticker = []

        # Quotes
        for q in LiveQuote.objects.select_related("instrument").order_by("-updated_at")[:15]:
            change = float(q.change_pct or 0)
            spread_pct = None
            try:
                if q.bid and q.ask and float(q.ask) > 0:
                    spread_pct = (float(q.ask) - float(q.bid)) / float(q.ask) * 100
            except Exception:
                spread_pct = None
            age_s = int((now - q.updated_at).total_seconds()) if q.updated_at else None
            if age_s is None:
                age_display = "unknown"
            elif age_s < 90:
                age_display = "just now"
            elif age_s < 3600:
                age_display = f"{age_s // 60}m ago"
            elif age_s < 86400:
                age_display = f"{age_s // 3600}h ago"
            else:
                age_display = f"{age_s // 86400}d ago"
            ticker.append({
                "type": "quote", "symbol": q.instrument.symbol,
                "name": q.instrument.name or "",
                "price": str(q.last), "change": change,
                "change_display": f"+{change:.2f}%" if change >= 0 else f"{change:.2f}%",
                "asset_class": q.instrument.asset_class,
                "bid": q.bid, "ask": q.ask,
                "spread_pct": round(spread_pct, 3) if spread_pct is not None else None,
                "volume": q.volume,
                # A price with no age is a price you cannot act on: the quote
                # pollers are rate-limited and a "live" number can be hours old.
                "age_s": age_s, "age_display": age_display,
                "stale": bool(age_s is not None and age_s > 900),
                "source": q.source or "",
                "url": f"/instruments/{q.instrument.symbol}/",
            })

        # Signals. The popup used to carry only score, urgency and direction —
        # so hovering a signal told you a setup existed but nothing about the
        # trade it proposes. The levels are the whole point of a signal: where
        # to get in, where you are wrong, and what you are playing for.
        active_signals = Signal.objects.filter(is_active=True)
        for s in active_signals.select_related("instrument").order_by("-score")[:5]:
            entry = s.suggested_entry or s.price_at_signal
            rr = s.risk_reward_ratio
            if rr is None and entry and s.suggested_stop and s.suggested_target:
                risk = abs(float(entry) - float(s.suggested_stop))
                if risk > 0:
                    rr = round(abs(float(s.suggested_target) - float(entry)) / risk, 2)
            # How far price has travelled since the signal fired: a setup is
            # only actionable while price is still near its entry.
            drift_pct = None
            try:
                lq = LiveQuote.objects.filter(instrument=s.instrument).first()
                if lq and lq.last and s.price_at_signal:
                    drift_pct = (float(lq.last) - float(s.price_at_signal)) / float(s.price_at_signal) * 100
            except Exception:
                drift_pct = None
            age_min = int((now - s.created_at).total_seconds() // 60) if s.created_at else None
            ticker.append({
                "type": "signal", "symbol": s.instrument.symbol,
                "title": s.title or "",
                "description": (s.description or "")[:400],
                "direction": s.direction, "score": f"{s.score:.2f}",
                "score_pct": int(round(float(s.score or 0) * 100)),
                "urgency": s.urgency,
                "rule_name": s.rule_name or "",
                "signal_type": s.signal_type or "",
                "entry": entry, "stop": s.suggested_stop,
                "target": s.suggested_target, "rr": rr,
                "drift_pct": round(drift_pct, 2) if drift_pct is not None else None,
                "age_min": age_min,
                "asset_class": s.instrument.asset_class,
                "url": "/signals/",
            })

        # News
        for n in NewsArticle.objects.prefetch_related("ai_affected_instruments").order_by("-published_at")[:12]:
            try:
                affected_list = list(n.ai_affected_instruments.all()[:6])
                affected_chips = [i.symbol for i in affected_list]
                affected_syms = ", ".join(affected_chips)
            except Exception:
                affected_syms = ""; affected_chips = []
            summary_txt = (n.ai_summary or n.content_summary or "").strip()
            import re as _re
            tokens = _re.findall(r"\b[A-Z][A-Za-z]{3,}\b", n.title or "")
            keywords = list(dict.fromkeys(tokens))[:5]
            sent = n.ai_sentiment_score
            if sent is None: implication = "Impact pending analysis"
            elif sent > 0.3: implication = "Bullish — risk-on setup"
            elif sent < -0.3: implication = "Bearish — risk-off setup"
            else: implication = "Neutral — mixed signal"
            ticker.append({
                "type": "news", "news_id": n.id, "title": n.title, "source": n.source,
                "summary": summary_txt[:400],
                "sentiment_score": sent,
                "urgency": n.ai_urgency or "",
                "affected": affected_syms,
                "affected_chips": affected_chips,
                "keywords": keywords,
                "implication": implication,
                "published_at": n.published_at.strftime("%H:%M") if n.published_at else "",
                "url": f"/news/{n.id}/",
            })

        ctx["ticker_items"] = ticker
        ctx["panel_signals"] = active_signals.count()
        ctx["panel_bullish"] = active_signals.filter(direction="bullish").count()
        ctx["panel_bearish"] = active_signals.filter(direction="bearish").count()
        ctx["panel_strategies"] = Strategy.objects.filter(status__in=["active", "approved"]).count()
        ctx["panel_proposed"] = Strategy.objects.filter(status="proposed").count()
        ctx["panel_news"] = NewsArticle.objects.filter(published_at__gte=day_ago).count()

    except Exception as e:
        logger.debug(f"Ticker/panel data unavailable: {e}")

    # Portfolio
    try:
        from portfolio.services import get_or_create_default_portfolio
        portfolio = get_or_create_default_portfolio(user=request.user)
        open_pos = portfolio.positions.filter(closed_at__isnull=True)
        cash_pct = round(float(portfolio.cash_available) / max(float(portfolio.current_value), 1) * 100)
        ctx["panel_portfolio_value"] = f"{portfolio.current_value:,.0f}"
        ctx["panel_cash"] = f"{portfolio.cash_available:,.0f}"
        ctx["panel_cash_pct"] = cash_pct
        ctx["panel_positions"] = open_pos.count()
        ctx["panel_exposure"] = 100 - cash_pct
        ctx["panel_max_dd"] = f"{portfolio.max_daily_loss_pct}"
        ctx["panel_watchlist"] = portfolio.positions.filter(instrument__is_watchlist=True).count()
        # Expanded panel data
        ctx["panel_recent_positions"] = list(open_pos.select_related("instrument")[:5])
    except Exception as e:
        logger.debug(f"Portfolio data unavailable: {e}")

    # Expanded panel signals + news
    try:
        from signals.models import Signal
        from scraping.models import NewsArticle
        ctx["panel_recent_signals"] = list(Signal.objects.filter(is_active=True).select_related("instrument").order_by("-score")[:5])
        ctx["panel_recent_news"] = list(NewsArticle.objects.order_by("-published_at")[:5])
        ctx["panel_recent_strategies"] = list(Strategy.objects.filter(status__in=["active", "approved", "proposed"]).order_by("-created_at")[:5])
    except Exception as e:
        logger.debug(f"Panel signals/news unavailable: {e}")

    return ctx
