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


#: A section's name as the digest's heading says it.
SECTION_WORDS = {
    'portfolio': 'Portfolio',
    'signals': 'Active signals',
    'events': 'Economic events today',
    'news': 'News',
    'daily_pnl': 'Daily P&L',
    'trades': 'Trades today',
    'strategies': 'Active strategies',
}

#: A field's name as a digest line says it.
KEY_WORDS = {
    'pnl': 'P&L',
    'pnl_pct': 'P&L %',
    'daily_pnl': 'Daily P&L',
    'cumulative_pnl_pct': 'Cumulative P&L %',
    'max_drawdown': 'Max drawdown',
    'total_value': 'Total value',
    'open_positions': 'Open positions',
    'top_movers': 'Top movers',
    'entry_price': 'Entry price',
}


def _digest_key(key) -> str:
    key = str(key)
    return KEY_WORDS.get(key) or key.replace('_', ' ').capitalize()


def _digest_value(value) -> str:
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def digest_lines(digest) -> list:
    """The digest as lines: a bold heading per section, then one bullet
    per row (five at most, three fields a row). A list inside a section is
    counted, never dropped in silence. Shared by the bell's body and
    Telegram (2026-09-26: the body was Markdown the bell printed as is)."""
    from bot_program.notifications import TelegramHeading
    lines = []
    for section_name, data in (digest.get('sections') or {}).items():
        rows = []
        if isinstance(data, list):
            for item in data[:5]:
                if isinstance(item, dict):
                    rows.append("• " + ", ".join(
                        f"{_digest_key(k)}: {_digest_value(v)}"
                        for k, v in list(item.items())[:3]))
        elif isinstance(data, dict):
            for k, v in list(data.items())[:5]:
                if isinstance(v, list):
                    rows.append(f"• {_digest_key(k)}: {len(v)}")
                elif not isinstance(v, dict):
                    rows.append(f"• {_digest_key(k)}: {_digest_value(v)}")
        lines.append(TelegramHeading(
            SECTION_WORDS.get(section_name)
            or str(section_name).replace('_', ' ').capitalize()))
        lines.extend(rows or ["• Nothing to report"])
    return lines or ["Nothing to report"]


def send_digest(digest, user=None, *, chats_done=None):
    """Send a generated digest via all configured channels.

    `chats_done` (2026-09-26): the set a scheduled run passes for all its
    users. A Telegram chat already in it is not posted again, so a chat
    several users share (the Sauron group) receives one digest per run;
    the first user met speaks for it. The bell is still per user.
    """
    from alerts.models import Notification

    title_map = {
        'morning_brief': 'Morning Market Brief',
        'end_of_day': 'End of Day Summary',
    }
    title = title_map.get(digest['type'], 'Market Digest')

    # One set of lines for the bell's body and for Telegram.
    lines = digest_lines(digest)
    body = '\n'.join(str(line) for line in lines)

    if user:
        Notification.create_for_user(user, 'system', title, body)
    else:
        Notification.create_for_all('system', title, body)

    # Also send via external channels: the USER's chat, in the house
    # style. Until 2026-09-26 this called send_telegram(chat id, body):
    # the chat id became the bold title and the digest went to the
    # platform chat instead.
    try:
        from alerts.channels.telegram_alert import MARKS, send_to_chat
        if user:
            prefs = getattr(user, 'notification_prefs', None)
            chat = str(getattr(prefs, 'telegram_chat_id', '') or '').strip()
            if chat and (chats_done is None or chat not in chats_done):
                if chats_done is not None:
                    chats_done.add(chat)
                send_to_chat(chat, title, lines=lines,
                             mark=MARKS.get(digest['type'], MARKS['digest']))
    except Exception:
        pass

    return True
