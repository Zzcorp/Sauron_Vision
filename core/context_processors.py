"""Global context processors for Sauron Vision."""
import logging
from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from .exchange_status import get_exchange_status

logger = logging.getLogger(__name__)


def _panel_detail(user):
    """The contents of the info-panel dropdowns.

    Several of these cells opened a panel containing a title and a link to the
    page you were already one click from. ALERTS and WATCHLIST had literally
    nothing else in them; DRAWDOWN and VOLATILITY had no panel at all. A
    dropdown that tells you nothing you did not already read on the cell is
    worse than no dropdown, because it costs a hover to discover that.

    Cached for 20 seconds per user. This runs on EVERY page render, and the
    aggregate queries below are not free — but the underlying numbers only
    move when a scan or a fill lands, so a short TTL costs nothing in accuracy
    and takes the whole block off the critical path for the other 19 seconds.
    """
    import sys
    from django.core.cache import cache

    # The cache is keyed on the user's primary key, which is stable and unique
    # in production. Under the test runner it is neither: every TestCase rolls
    # the database back, so primary keys restart and a payload cached by one
    # test is served to a different user in the next. That made assertions on
    # anything in the headband depend on how long the preceding test took.
    testing = "test" in sys.argv or any("pytest" in a for a in sys.argv)

    key = f"sv:panel_detail:{user.pk}"
    if not testing:
        cached = cache.get(key)
        if cached is not None:
            return cached

    out = {}
    now = timezone.now()
    day_ago = now - timedelta(hours=24)

    # ── Open bot trades, with live risk ──────────────────────────────────
    # The R-multiple is the number that says whether a position is working,
    # and it is computable here: we hold the entry, the stop it opened with,
    # and a live quote. Position.unrealized_pnl is deliberately NOT used —
    # nothing in the codebase ever writes it, so it would render +0.00 on
    # every row forever.
    try:
        from bot_program.models import AssetBotTrade
        from market_data.models import LiveQuote

        trades = list(AssetBotTrade.objects.filter(
            config__user=user, status__in=("OPEN", "CLOSE_PENDING")
        ).order_by("-opened_at")[:6])
        quotes = {}
        if trades:
            symbols = {t.symbol for t in trades}
            quotes = {q.instrument.symbol: q for q in LiveQuote.objects
                      .select_related("instrument")
                      .filter(instrument__symbol__in=symbols)}

        rows = []
        for t in trades:
            q = quotes.get(t.symbol)
            last = float(q.last) if q and q.last is not None else None
            entry = float(t.entry_price or 0)
            stop = float(t.stop_loss) if t.stop_loss is not None else None
            r_mult = pct = None
            if last is not None and entry:
                direction = 1 if (t.side or "").upper() in ("BUY", "LONG") else -1
                pct = (last - entry) / entry * 100 * direction
                if stop is not None and abs(entry - stop) > 1e-12:
                    r_mult = (last - entry) * direction / abs(entry - stop)
            rows.append({
                "symbol": t.symbol, "side": (t.side or "").upper(),
                "qty": t.qty, "entry": entry, "stop": stop, "last": last,
                "r": None if r_mult is None else round(r_mult, 2),
                "pct": None if pct is None else round(pct, 2),
                "paper": t.paper, "opened_at": t.opened_at,
            })
        out["panel_open_trades"] = rows

        closed = AssetBotTrade.objects.filter(
            config__user=user, status="CLOSED", closed_at__gte=day_ago)
        n_closed = closed.count()
        wins = closed.filter(pnl__gt=0).count() if n_closed else 0
        out["panel_bot_trades_24h"] = n_closed
        out["panel_bot_winrate"] = round(wins / n_closed * 100) if n_closed else None
        last_closed = closed.order_by("-closed_at").first()
        out["panel_bot_last"] = ({
            "symbol": last_closed.symbol,
            "outcome": (last_closed.outcome or "closed").replace("_", " "),
            "r": last_closed.realized_r,
            "when": last_closed.closed_at,
        } if last_closed else None)
    except Exception as e:
        logger.debug(f"Panel bot detail unavailable: {e}")

    # ── The signals themselves, not just how many ────────────────────────
    try:
        from signals.models import Signal
        out["panel_top_signals"] = [{
            "symbol": s.instrument.symbol,
            "direction": s.direction,
            "score_pct": int(round((s.score or 0) * 100)),
            "rule": s.rule_name or s.signal_type or "",
            "created_at": s.created_at,
            "entry": s.suggested_entry,
            "stop": s.suggested_stop,
        } for s in Signal.objects.filter(is_active=True)
            .select_related("instrument").order_by("-score")[:4]]
    except Exception as e:
        logger.debug(f"Panel signal detail unavailable: {e}")

    # ── Watchlist with prices, so the cell is a watchlist and not a count ─
    try:
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        wl = list(Instrument.objects.filter(is_watchlist=True, is_active=True)[:6])
        wq = {q.instrument_id: q for q in LiveQuote.objects.filter(
            instrument__in=wl)} if wl else {}
        out["panel_watchlist_rows"] = [{
            "symbol": i.symbol,
            "last": wq[i.id].last if i.id in wq else None,
            "change": float(wq[i.id].change_pct or 0) if i.id in wq else None,
        } for i in wl]
    except Exception as e:
        logger.debug(f"Panel watchlist detail unavailable: {e}")

    # ── Drawdown, with the peak it is measured from ──────────────────────
    try:
        from portfolio.models import PortfolioSnapshot
        from portfolio.services import get_or_create_default_portfolio
        pf = get_or_create_default_portfolio(user=user)
        snaps = list(PortfolioSnapshot.objects.filter(portfolio=pf)
                     .order_by("-date")[:180])
        if snaps:
            peak = max(snaps, key=lambda s: s.total_value or 0)
            cur = snaps[0]
            out["panel_dd_peak"] = peak.total_value
            out["panel_dd_peak_date"] = peak.date
            out["panel_dd_current"] = cur.total_value
            out["panel_dd_snapshots"] = len(snaps)
    except Exception as e:
        logger.debug(f"Panel drawdown detail unavailable: {e}")

    # ── Realised volatility. There is no VIX feed in this platform, and the
    #    cell was labelled "VIX index" while rendering a variable nobody set.
    #    This is what we can actually measure: 20-day annualised realised
    #    volatility of the instrument with the most price history.
    try:
        import statistics
        from market_data.models import PriceData

        # Periods per year, for annualising. Do NOT hardcode a timeframe: this
        # deployment holds 4h and 1h bars and no daily ones at all, so asking
        # for "1d" found nothing and the cell would have stayed blank forever
        # while looking like a missing feed.
        PERIODS = {"1d": 252, "4h": 252 * 6, "1h": 252 * 24}
        for tf, per_year in PERIODS.items():
            bars = list(PriceData.objects.filter(timeframe=tf)
                        .order_by("-timestamp")
                        .values_list("instrument__symbol", "close")[:600])
            by_symbol = {}
            for sym, close in bars:
                by_symbol.setdefault(sym, []).append(float(close))
            best = max(by_symbol.items(), key=lambda kv: len(kv[1]), default=None)
            if not best or len(best[1]) < 21:
                continue
            closes = best[1][:21]                     # newest first
            rets = [(closes[i] - closes[i + 1]) / closes[i + 1]
                    for i in range(20) if closes[i + 1]]
            if len(rets) >= 10:
                out["panel_vol_pct"] = round(
                    statistics.pstdev(rets) * (per_year ** 0.5) * 100, 1)
                out["panel_vol_symbol"] = best[0]
                out["panel_vol_days"] = len(rets)
                out["panel_vol_tf"] = tf
                break
    except Exception as e:
        logger.debug(f"Panel volatility unavailable: {e}")

    if not testing:
        cache.set(key, out, 20)
    return out


def _compact(value):
    """Money at a glance: 1.2B, 340M, 18K.

    The liquidation cells are 60px wide in the info panel. A raw
    1,238,904,551 does not fit and wraps into the cell below it, so the figure
    that gets read is whichever half survived.
    """
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    for cut, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= cut:
            return f"{n / cut:,.1f}{suffix}"
    return f"{n:,.0f}"


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
        # None, not "0.0" and not "+0.00%". These are measurements, and until
        # one has been taken the honest answer is an em-dash. A confident red
        # 0.0% drawdown reads as "no downside", not as "we could not compute
        # it" — which is the failure mode this platform already has a whole
        # test module about.
        "panel_drawdown": None,
        "panel_max_dd": "3.0",
        "panel_daily_pnl": None,
        "panel_daily_pnl_display": None,
        # Fourteen of the thirty panel_* names below were rendered by
        # base.html and assigned by nothing at all, so the info panel showed a
        # fabricated constant on every page of the platform. The BOT cell was
        # the worst of them: panel_bot_armed was never set, so the header
        # permanently reported OFF / OFFLINE / 0 open even with the bot armed
        # and holding positions.
        "panel_signals_24h": 0,
        "panel_bot_armed": None,
        "panel_bot_mode": None,
        "panel_bot_open": None,
        "panel_bot_pnl_24h_display": None,
        "panel_funding_display": None,
        "panel_funding_extreme_count": None,
        "panel_funding_flips": None,
        "panel_funding_samples": None,
        "panel_liq_24h_display": None,
        "panel_liq_count": None,
        "panel_liq_long_display": None,
        "panel_liq_short_display": None,
        "panel_vix": None,
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

        # No quotes here and no signals either, deliberately. The headband
        # directly above already shows live prices, and the signals rail on
        # the right is the signals' home — each carried in the ticker was a
        # duplicate crowding out the one thing with no other home: news.
        active_signals = Signal.objects.filter(is_active=True)

        # News
        for n in NewsArticle.objects.prefetch_related("ai_affected_instruments").order_by("-published_at")[:18]:
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
        # Rendered by base.html as "24H NEW" and assigned by nothing, so the
        # signals dropdown reported zero new signals in perpetuity.
        ctx["panel_signals_24h"] = Signal.objects.filter(created_at__gte=day_ago).count()
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

        # Drawdown and daily P&L come from the most recent snapshot. Both used
        # to be hardcoded constants — "0.0" and "+0.00%" — sitting in the same
        # weight and colour as a real reading.
        from portfolio.models import PortfolioSnapshot
        snap = PortfolioSnapshot.objects.filter(
            portfolio=portfolio).order_by("-date").first()
        if snap:
            if snap.max_drawdown is not None:
                # Already stored as a negative percentage by portfolio.tasks —
                # do not multiply by 100, and show it as a magnitude.
                ctx["panel_drawdown"] = f"{abs(float(snap.max_drawdown)):.1f}"
            # A snapshot from last week does not describe today's P&L.
            if snap.date == timezone.localdate() and snap.daily_pnl_pct is not None:
                pct = float(snap.daily_pnl_pct)
                ctx["panel_daily_pnl"] = pct
                ctx["panel_daily_pnl_display"] = f"{pct:+.2f}%"
    except Exception as e:
        logger.debug(f"Portfolio data unavailable: {e}")

    # Computed independently of the ticker block above: that one is wrapped in
    # its own try, and if it fails before assigning day_ago every panel below
    # would die on a NameError swallowed as "no data".
    day_ago = timezone.now() - timedelta(hours=24)

    # Everything the info-panel dropdowns show, behind a 20s cache.
    try:
        ctx.update(_panel_detail(request.user))
    except Exception as e:
        logger.debug(f"Panel detail unavailable: {e}")

    # ── Bot program ──
    try:
        from bot_program.models import AssetBotConfig, AssetBotTrade

        configs = AssetBotConfig.objects.filter(user=request.user)
        enabled = configs.filter(enabled=True)
        ctx["panel_bot_armed"] = enabled.exists()
        modes = sorted({c.mode for c in enabled})
        ctx["panel_bot_mode"] = (modes[0] if len(modes) == 1
                                 else ("mixed" if modes else "—"))
        ctx["panel_bot_open"] = AssetBotTrade.objects.filter(
            config__user=request.user, status__in=("OPEN", "CLOSE_PENDING")).count()

        closed_24h = AssetBotTrade.objects.filter(
            config__user=request.user, status="CLOSED", closed_at__gte=day_ago)
        pnl = closed_24h.aggregate(total=Sum("pnl"))["total"]
        # Distinguish "no trades closed today" from "closed flat".
        ctx["panel_bot_pnl_24h_display"] = (
            f"{float(pnl):+,.2f}" if pnl is not None else None)
    except Exception as e:
        logger.debug(f"Bot panel data unavailable: {e}")

    # ── Funding and liquidations ──
    try:
        from market_data.models import FundingRate, LiquidationEvent

        rates = list(FundingRate.objects.filter(
            timestamp__gte=day_ago).values_list("symbol", "funding_rate"))
        if rates:
            values = [float(r) for _, r in rates if r is not None]
            if values:
                ctx["panel_funding_samples"] = len(values)
                ctx["panel_funding_display"] = f"{sum(values) / len(values) * 100:+.4f}%"
                ctx["panel_funding_extreme_count"] = sum(
                    1 for v in values if abs(v) >= 0.001)
                # A flip is the rate changing sign for a symbol: the moment
                # the crowd stops paying to be long and starts paying to be
                # short, which is the whole reason to watch this number.
                flips = 0
                by_symbol = {}
                for symbol, rate in rates:
                    if rate is None:
                        continue
                    by_symbol.setdefault(symbol, []).append(float(rate))
                for series in by_symbol.values():
                    flips += sum(1 for a, b in zip(series, series[1:])
                                 if (a >= 0) != (b >= 0))
                ctx["panel_funding_flips"] = flips

        liqs = LiquidationEvent.objects.filter(timestamp__gte=day_ago)
        agg = liqs.aggregate(total=Sum("notional_usd"), n=Count("id"))
        if agg["n"]:
            ctx["panel_liq_count"] = agg["n"]
            ctx["panel_liq_24h_display"] = _compact(agg["total"] or 0)
            longs = liqs.filter(side__iexact="long").aggregate(t=Sum("notional_usd"))["t"]
            shorts = liqs.filter(side__iexact="short").aggregate(t=Sum("notional_usd"))["t"]
            ctx["panel_liq_long_display"] = _compact(longs or 0)
            ctx["panel_liq_short_display"] = _compact(shorts or 0)
    except Exception as e:
        logger.debug(f"Funding/liquidation panel data unavailable: {e}")

    # Expanded panel signals + news
    try:
        from signals.models import Signal
        from scraping.models import NewsArticle
        # "-created_at", not "-score": this list is named RECENT and feeds the
        # signals rail top-down — ranking by score parked a strong old signal
        # at the top while new arrivals appeared buried mid-list. The score is
        # already visible on every card (gauge + number); the rail's job is
        # what just happened.
        ctx["panel_recent_signals"] = list(Signal.objects.filter(is_active=True).select_related("instrument").order_by("-created_at")[:5])
        ctx["panel_recent_news"] = list(NewsArticle.objects.order_by("-published_at")[:5])
        ctx["panel_recent_strategies"] = list(Strategy.objects.filter(status__in=["active", "approved", "proposed"]).order_by("-created_at")[:5])
    except Exception as e:
        logger.debug(f"Panel signals/news unavailable: {e}")

    return ctx
