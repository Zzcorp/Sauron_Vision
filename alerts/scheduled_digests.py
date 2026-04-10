"""Scheduled digest generation — morning brief and market close summary."""
import logging
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


def generate_morning_digest(user=None):
    """Generate morning market brief digest.

    Runs at configured time (e.g., 7 AM user's timezone).
    Returns dict with sections for: portfolio overnight, pre-market movers,
    upcoming events, active signals summary, news highlights.
    """
    from portfolio.services import get_or_create_default_portfolio
    from signals.models import Signal
    from market_data.models import EconomicEvent, LiveQuote
    from scraping.models import NewsArticle
    from instruments.models import Instrument

    now = timezone.now()
    yesterday = now - timedelta(hours=24)

    digest = {
        'type': 'morning_brief',
        'generated_at': now.isoformat(),
        'sections': {},
    }

    # Portfolio overnight summary
    try:
        portfolio = get_or_create_default_portfolio(user=user)
        from portfolio.models import Position
        open_positions = Position.objects.filter(
            portfolio=portfolio, closed_at__isnull=True
        ).select_related('instrument')

        digest['sections']['portfolio'] = {
            'value': float(portfolio.current_value),
            'cash': float(portfolio.cash_available),
            'open_positions': open_positions.count(),
            'top_movers': [{
                'symbol': p.instrument.symbol,
                'pnl_pct': p.unrealized_pnl_pct,
                'direction': p.direction,
            } for p in sorted(open_positions, key=lambda x: abs(x.unrealized_pnl_pct), reverse=True)[:5]],
        }
    except Exception as e:
        logger.error(f"Morning digest portfolio section failed: {e}")

    # Active signals
    try:
        active_signals = Signal.objects.filter(is_active=True).select_related('instrument').order_by('-score')[:10]
        digest['sections']['signals'] = [{
            'symbol': s.instrument.symbol,
            'type': s.signal_type,
            'direction': s.direction,
            'score': s.score,
            'urgency': s.urgency,
        } for s in active_signals]
    except Exception as e:
        logger.error(f"Morning digest signals section failed: {e}")

    # Today's economic events
    try:
        today_start = now.replace(hour=0, minute=0, second=0)
        today_end = today_start + timedelta(days=1)
        events = EconomicEvent.objects.filter(
            datetime__gte=today_start, datetime__lt=today_end
        ).order_by('datetime')

        digest['sections']['events'] = [{
            'title': e.title,
            'time': e.datetime.strftime('%H:%M'),
            'impact': e.impact,
            'country': e.country,
            'forecast': e.forecast,
            'previous': e.previous,
        } for e in events[:15]]
    except Exception as e:
        logger.error(f"Morning digest events section failed: {e}")

    # Top news
    try:
        news = NewsArticle.objects.filter(
            published_at__gte=yesterday
        ).order_by('-ai_sentiment_score')[:5]

        digest['sections']['news'] = [{
            'title': n.title,
            'source': n.source,
            'sentiment': n.ai_sentiment_score,
            'summary': (n.ai_summary or n.content_summary or '')[:200],
        } for n in news]
    except Exception as e:
        logger.error(f"Morning digest news section failed: {e}")

    return digest


def generate_eod_digest(user=None):
    """Generate end-of-day market summary.

    Runs after market close (e.g., 4:30 PM EST).
    """
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import Position, PortfolioSnapshot
    from strategies.models import Strategy

    now = timezone.now()
    today = now.date()

    digest = {
        'type': 'end_of_day',
        'generated_at': now.isoformat(),
        'sections': {},
    }

    # Daily P&L
    try:
        portfolio = get_or_create_default_portfolio(user=user)
        snapshot = PortfolioSnapshot.objects.filter(
            portfolio=portfolio, date=today
        ).first()

        if snapshot:
            digest['sections']['daily_pnl'] = {
                'pnl': float(snapshot.daily_pnl),
                'pnl_pct': snapshot.daily_pnl_pct,
                'total_value': float(snapshot.total_value),
                'cumulative_pnl_pct': snapshot.cumulative_pnl_pct,
                'max_drawdown': snapshot.max_drawdown,
            }
    except Exception as e:
        logger.error(f"EOD digest P&L section failed: {e}")

    # Trades executed today
    try:
        portfolio = get_or_create_default_portfolio(user=user)
        today_start = timezone.now().replace(hour=0, minute=0, second=0)

        opened = Position.objects.filter(
            portfolio=portfolio, opened_at__gte=today_start
        ).select_related('instrument')
        closed = Position.objects.filter(
            portfolio=portfolio, closed_at__gte=today_start
        ).select_related('instrument')

        digest['sections']['trades'] = {
            'opened': [{
                'symbol': p.instrument.symbol,
                'direction': p.direction,
                'entry_price': float(p.entry_price),
            } for p in opened],
            'closed': [{
                'symbol': p.instrument.symbol,
                'direction': p.direction,
                'pnl_pct': p.unrealized_pnl_pct,
            } for p in closed],
        }
    except Exception as e:
        logger.error(f"EOD digest trades section failed: {e}")

    # Strategy performance
    try:
        active = Strategy.objects.filter(status='active')
        digest['sections']['strategies'] = [{
            'name': s.name,
            'pnl_pct': s.pnl_pct,
            'status': s.status,
        } for s in active]
    except Exception as e:
        logger.error(f"EOD digest strategies section failed: {e}")

    return digest


def send_digest(digest, user=None):
    """Send a generated digest via all configured channels."""
    from alerts.models import Notification

    title_map = {
        'morning_brief': 'Morning Market Brief',
        'end_of_day': 'End of Day Summary',
    }
    title = title_map.get(digest['type'], 'Market Digest')

    # Format sections into readable text
    body_parts = [f"**{title}**\n"]

    for section_name, data in digest.get('sections', {}).items():
        body_parts.append(f"\n**{section_name.replace('_', ' ').title()}:**")
        if isinstance(data, list):
            for item in data[:5]:
                if isinstance(item, dict):
                    body_parts.append(f"  - {', '.join(f'{k}: {v}' for k, v in list(item.items())[:3])}")
        elif isinstance(data, dict):
            for k, v in list(data.items())[:5]:
                if not isinstance(v, (list, dict)):
                    body_parts.append(f"  {k}: {v}")

    body = '\n'.join(body_parts)

    if user:
        Notification.create_for_user(user, 'system', title, body)
    else:
        Notification.create_for_all('system', title, body)

    # Also send via external channels
    try:
        from alerts.channels.telegram_alert import send_telegram
        if user:
            prefs = getattr(user, 'notification_prefs', None)
            if prefs and prefs.telegram_chat_id:
                send_telegram(prefs.telegram_chat_id, body[:4000])
    except Exception:
        pass

    return True
