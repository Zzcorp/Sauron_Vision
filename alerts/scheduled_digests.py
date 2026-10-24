"""Scheduled digest generation — morning brief and market close summary."""
import logging
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


def generate_morning_digest(user=None):
    """Generate morning market brief digest.

    Runs at configured time (e.g., 7 AM user's timezone).
    Returns dict with sections for: portfolio overnight, pre-market movers,
    upcoming events, active signals summary, news highlights. Opens with
    the whole book, the real account first (alerts/digest_book.py,
    2026-09-27): a summary line, then "Real money", then "Simulated".
    """
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

    # THE WHOLE BOOK, THE REAL ACCOUNT FIRST (2026-09-27). The operator
    # read "no position open" here while five were: this counted the
    # legacy Position table, empty on the live box, while every position
    # the platform holds is an AssetBotTrade. alerts/digest_book.py reads
    # the book the positions page reads, and the eToro real account
    # through the Telegram Eye's live read. add_book never raises; the
    # import is guarded too, so a module that fails to load costs the
    # book's lines, not the whole brief.
    try:
        from alerts.digest_book import add_book
        add_book(digest, user, now, 'Morning digest')
    except Exception as e:
        logger.error(f"Morning digest book section failed: {e}")
        digest['summary'] = [
            f"The open positions could not be read ({type(e).__name__})."]

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

    # THE BIG MONEY BOARD (2026-10-09, bigmoney/read.py): the week's lean
    # per market from forced flows, the trend followers near a trigger, the
    # tide, the forced flows ahead and what is blind. Words only (no
    # decimals, no percentages, no currency figures, no levels). Left out
    # while the big_money_board switch is off.
    try:
        from bigmoney.read import brief_lines, is_on as big_money_on
        if big_money_on():
            digest['sections']['big_money'] = {'lines': brief_lines()}
    except Exception as e:
        logger.error(f"Morning digest big money section failed: {e}")

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

    # THE LADDER OVERNIGHT (2026-10-08, the wiring audit: ladder moves
    # reached no person). The promotion sweep runs at 04:30, inside most
    # quiet hours, so its one
    # summary reaches the bell and not the phone: this is the phone's copy.
    # The night's moves from PromotionEvent, the refusals from the sweep's
    # own audit row (they were a log line). R and stages, never money.
    try:
        digest['sections']['ladder'] = {'lines': ladder_overnight_lines(now)}
    except Exception as e:
        logger.error(f"Morning digest ladder section failed: {e}")

    return digest


#: Moves listed in the ladder section before "+N more".
LADDER_LINES_MAX = 8


def ladder_overnight_lines(now=None, *, hours=24) -> list:
    """The promotion ladder's last `hours`, as digest lines: every stage
    change (PromotionEvent) newest first, then what the newest sweep held
    back (its ladder_sweep audit row). One line saying so when nothing
    moved."""
    from bot_program.audit import LADDER_SWEEP
    from bot_program.audit_models import AuditLogEntry
    from signals.models_control import PromotionEvent
    from signals.promotion_pipeline import (_rule_words, mover_words,
                                            stage_words)
    now = now or timezone.now()
    since = now - timedelta(hours=hours)
    events = list(PromotionEvent.objects.filter(created_at__gte=since)
                  .select_related('triggered_by')
                  .order_by('-created_at')[:LADDER_LINES_MAX + 1])
    lines = []
    for ev in events[:LADDER_LINES_MAX]:
        lines.append(f"• {_rule_words(ev.rule_name)}: "
                     f"{stage_words(ev.from_stage or 'research')} → "
                     f"{stage_words(ev.to_stage)} (by {mover_words(ev)})")
    if len(events) > LADDER_LINES_MAX:
        more = PromotionEvent.objects.filter(created_at__gte=since).count()
        lines.append(f"• +{more - LADDER_LINES_MAX} more on /promotions/")
    sweep = (AuditLogEntry.objects.filter(kind=LADDER_SWEEP,
                                          created_at__gte=since)
             .order_by('-id').first())
    blocked = [b for b in ((sweep.data or {}).get('blocked') or [])
               if isinstance(b, dict)] if sweep else []
    if blocked:
        names = ", ".join(_rule_words(b.get('rule_name')) for b in blocked[:5])
        more = f" (+{len(blocked) - 5} more)" if len(blocked) > 5 else ""
        lines.append(f"• Held back: {len(blocked)} by the evidence gate — "
                     f"{names}{more}")
    if not lines:
        lines.append(f"• No rule changed stage in the last {hours} hours")
    return lines


def generate_eod_digest(user=None):
    """Generate end-of-day market summary.

    Runs after market close (e.g., 4:30 PM EST). Opens with the whole
    book, the real account first, and "Trades today" reads the user's
    AssetBotTrades (alerts/digest_book.py, 2026-09-27).
    """
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import PortfolioSnapshot
    from strategies.models import Strategy

    now = timezone.now()
    today = now.date()

    digest = {
        'type': 'end_of_day',
        'generated_at': now.isoformat(),
        'sections': {},
    }

    # THE WHOLE BOOK, THE REAL ACCOUNT FIRST (2026-09-27): the summary
    # line, "Real money", then "Simulated" (see the morning brief; the
    # import is guarded the same way).
    seeded = False
    try:
        from alerts.digest_book import add_book
        seeded = add_book(digest, user, now, 'EOD digest')
    except Exception as e:
        logger.error(f"EOD digest book section failed: {e}")
        digest['summary'] = [
            f"The open positions could not be read ({type(e).__name__})."]

    # Daily P&L
    try:
        portfolio = get_or_create_default_portfolio(user=user)
        snapshot = PortfolioSnapshot.objects.filter(
            portfolio=portfolio, date=today
        ).first()

        if snapshot and seeded:
            # 2026-09-27: while the book's capital is the seed nobody
            # entered, every figure of the snapshot is measured from it:
            # the total is the seed plus what the open positions add, the
            # percentages and the drawdown divide by it, and the P&L is
            # the day's move of that total (nothing credits the seed when
            # a simulated position closes, so a close takes its P&L out).
            # Said, not printed: the open P&L is under Simulated, the
            # closes under Trades today.
            digest['sections']['daily_pnl'] = {
                'seeded': True,
                'lines': ["Not measured while the book value is not set."],
            }
        elif snapshot:
            # 2026-09-28: worded, in the book's own currency and the book
            # section's own money words (alerts/digest_book.py: eye.money
            # for a value, ps.money signed for a P&L, ps.percent). Bare
            # figures here read as dollars beside "Equity: ... USD" while
            # the book is in EUR. The figures stay beside the lines.
            from dashboard import position_summary as ps
            from bot_program.telegram_eye import money
            code = str(portfolio.currency or '')
            digest['sections']['daily_pnl'] = {
                'pnl': float(snapshot.daily_pnl),
                'pnl_pct': snapshot.daily_pnl_pct,
                'total_value': float(snapshot.total_value),
                'cumulative_pnl_pct': snapshot.cumulative_pnl_pct,
                'max_drawdown': snapshot.max_drawdown,
                'currency': code,
                'lines': [
                    f"P&L: {ps.money(snapshot.daily_pnl, code, signed=True)}"
                    f" ({ps.percent(snapshot.daily_pnl_pct)})",
                    f"Total value: {money(snapshot.total_value, code)}",
                    f"Cumulative P&L: "
                    f"{ps.percent(snapshot.cumulative_pnl_pct)}",
                    f"Max drawdown: {ps.percent(snapshot.max_drawdown)}",
                ],
            }
    except Exception as e:
        logger.error(f"EOD digest P&L section failed: {e}")

    # Trades today (2026-09-27): the user's AssetBotTrades opened or closed
    # since the UTC day start (the rows the positions page lists), the
    # closes with the P&L and R they booked; the legacy book's Position
    # rows only when it holds any. This read the legacy table alone,
    # empty on the live box.
    try:
        from alerts.digest_book import trades_today
        digest['sections']['trades'] = trades_today(user, now)
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
    'real_money': 'Real money',
    'simulated': 'Simulated',
    'portfolio': 'Portfolio',
    'signals': 'Active signals',
    'events': 'Economic events today',
    'big_money': 'Big money',
    'news': 'News',
    'daily_pnl': 'Daily P&L',
    'trades': 'Trades today',
    'strategies': 'Active strategies',
    'ladder': 'Ladder overnight',
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
    Telegram (2026-09-26: the body was Markdown the bell printed as is).

    2026-09-27: the digest's `summary` lines come first, before any
    heading ("Open positions: 5 (5 simulated · 0 real money)"), and a
    section that words itself (a dict carrying `lines`: Real money,
    Simulated, Trades today) is printed as written; alerts/digest_book.py
    caps its own lists."""
    from bot_program.notifications import TelegramHeading
    lines = [line for line in (digest.get('summary') or [])
             if str(line or '').strip()]
    for section_name, data in (digest.get('sections') or {}).items():
        rows = []
        if isinstance(data, dict) and isinstance(data.get('lines'), list):
            rows = [line for line in data['lines']
                    if str(line or '').strip()]
        elif isinstance(data, list):
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


def digest_users():
    """The active users in the order a scheduled digest is sent for them
    (2026-10-24): staff and superusers first, each group by id.

    A chat several users share gets ONE digest per run, the first user
    met's (send_digest's chats_done), and that digest shows the user's
    real account: equity, cash, used margin. The walk was an unordered
    query, so the database chose whose account everyone in the chat read.
    In this order a shared chat gets a staff member's digest when one
    shares it (the lowest id), else the lowest-id user's; the digest names
    whose it is (alerts/digest_book.owner_line). A chat of one user, and
    every bell, are unchanged."""
    from django.contrib.auth.models import User
    from django.db.models import Case, IntegerField, Q, Value, When
    return (User.objects.filter(is_active=True)
            .annotate(digest_rank=Case(
                When(Q(is_staff=True) | Q(is_superuser=True), then=Value(0)),
                default=Value(1), output_field=IntegerField()))
            .order_by("digest_rank", "pk"))


#: The digest's sections about the account (alerts/digest_book.py, the
#: daily P&L, the legacy portfolio block): its money.
ACCOUNT_SECTIONS = ('real_money', 'simulated', 'portfolio', 'daily_pnl',
                    'trades')


def account_free_lines(digest) -> list:
    """digest_lines without ACCOUNT_SECTIONS (2026-10-24): what the next
    steps reader (ai_agents/next_steps.py) is handed. Its steps are shown
    to any login on /briefing/#next-steps, so the book's value, cash and
    P&L in money never reach the AI. The summary line is counts only."""
    rest = {k: v for k, v in (digest.get('sections') or {}).items()
            if k not in ACCOUNT_SECTIONS}
    return digest_lines({**digest, 'sections': rest})


def send_digest(digest, user=None, *, chats_done=None):
    """Send a generated digest via all configured channels.

    `chats_done` (2026-09-26): the set a scheduled run passes for all its
    users. A Telegram chat already in it is not posted again, so a chat
    several users share (the Sauron group) receives one digest per run;
    the first user met speaks for it, and the run meets them in
    digest_users' order (a staff member first, 2026-10-24). The bell is
    still per user.
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
