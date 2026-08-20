"""Portfolio services — user-aware."""
import logging
from decimal import Decimal

from django.conf import settings

logger = logging.getLogger(__name__)


def get_or_create_default_portfolio(user=None):
    """Get or create portfolio for a specific user.

    The capital is coerced to Decimal BEFORE creation: settings hands it
    over as a float, and a freshly created instance keeps whatever types
    it was given until reloaded from the database — so the first task to
    both create and use the portfolio in one run crashed on
    float + Decimal, which on a fresh deploy is the very first exposure
    run.
    """
    from .models import Portfolio

    config = settings.PORTFOLIO_CONFIG
    capital = Decimal(str(config["initial_capital"]))

    if user and user.is_authenticated:
        portfolio, created = Portfolio.objects.get_or_create(
            name=f"{user.username}_main",
            defaults={
                "initial_capital": capital,
                "current_value": capital,
                "cash_available": capital,
                "currency": config["base_currency"],
            },
        )
    else:
        portfolio, created = Portfolio.objects.get_or_create(
            name="Main",
            defaults={
                "initial_capital": capital,
                "current_value": capital,
                "cash_available": capital,
                "currency": config["base_currency"],
            },
        )

    if created:
        logger.info(f"Created portfolio: {portfolio.name}")
    return portfolio


# ── The unified position book ───────────────────────────────────────────
# Two parallel books never met: the portfolio/positions pages rendered
# only portfolio.Position (fed by the Setup form, the NL trader and the
# eToro sync), while every interactive trading path — the bots, TAKE
# TRADE, the LONG/SHORT buttons — writes bot_program.AssetBotTrade. A
# trade the operator had just taken showed in fills, the Op Center and
# forensics but was invisible on Portfolio and Positions. This is the
# READ-side union; write-side sync was rejected on purpose: no trade path
# debits Portfolio.cash_available, so mirrored rows would inflate
# current_value and every snapshot, and the Op Center already unions the
# two books for its counts — a mirror would double-count there.

class _InstrumentShim:
    """Just enough Instrument for the templates when no row matches.

    `has_page` is False here and True on a real Instrument (Django models
    answer False for a missing attribute in a template, so the flag has to
    be positive on the row that HAS the page, not negative on the one that
    does not — see `instrument_has_page` below).

    It exists because `{% url 'instrument_detail' symbol %}` proves only
    that the ROUTE can hold the string, never that the row exists: a bot can
    hold BTCUSDT while the instruments table holds BTCUSD, and the symbol
    then rendered as a live link straight to a 404. This shim is precisely
    the "no row matched" case, so it is the honest place to say so.
    """
    __slots__ = ("symbol", "asset_class", "has_page")

    def __init__(self, symbol, asset_class=""):
        self.symbol = symbol
        self.asset_class = asset_class
        self.has_page = False


def instrument_has_page(instrument) -> bool:
    """True when this instrument has a detail page that will actually load."""
    return bool(instrument is not None
                and getattr(instrument, "pk", None) is not None)


class _StrategyShim:
    """The strategy column shows the rule that took the trade."""
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


class UnifiedPosition:
    """Position-shaped view over an AssetBotTrade — exactly the attributes
    the portfolio/positions templates read, nothing more."""
    # trade_id and status are what make a row ACTIONABLE: the positions and
    # portfolio pages could show a bot position but never close one, because
    # the normalised row carried no way to name the trade behind it.
    # portfolio.Position rows have neither, and the templates render no close
    # control for them — nothing in the platform can flatten one.
    # bar_pct is display-only, filled by the positions view: the history
    # row's mini bar, scaled against the biggest move on the page. It lives
    # here because a slotted class refuses attributes it did not declare,
    # and the alternative — a parallel list zipped against this one — is how
    # a row's own numbers end up disagreeing with the bar next to them.
    __slots__ = ("instrument", "direction", "quantity", "entry_price",
                 "current_price", "stop_loss", "take_profit",
                 "unrealized_pnl", "unrealized_pnl_pct", "opened_at",
                 "closed_at", "strategy", "source", "paper",
                 "trade_id", "status", "bar_pct")


def is_option_row(trade) -> bool:
    """Is this trade premium-denominated with a contract multiplier?

    Options rows store the UNDERLYING in `symbol` and the PREMIUM in
    `entry_price`, with the contract multiplier in metadata — the options
    bot's own close path multiplies by it.

    The platform's token for this class is "options", PLURAL, in all twenty-odd
    places that branch on it. The singular used to be the only spelling here
    and matched none of them, which left the metadata key as the only working
    test — so an options row that reached the book without one (an adopted
    broker position, a hand-repaired row) was priced against the UNDERLYING's
    quote, the exact fiction the caller refuses to print.
    """
    if trade is None:
        return False
    meta = trade.metadata or {}
    return (getattr(trade, "asset_class", "") in ("options", "option")
            or meta.get("multiplier") is not None)


def value_per_unit(trade) -> float:
    """Base-currency money per price point per unit, for one trade.

    ONE derivation, because there are two consumers: the row this module
    marks, and the money block on the positions hover card. They were written
    separately and immediately drifted — the card's copy kept a spelling of
    the options test that this one had corrected, so a multiplier-less options
    row would have been denominated 100x apart in two numbers printed on the
    same screen. A percentage that does not divide its own currency figures is
    the visible symptom.
    """
    if trade is None:
        return 1.0
    meta = trade.metadata or {}
    try:
        vpu = float(meta.get("value_per_unit") or 1.0)
    except (TypeError, ValueError):
        vpu = 1.0
    if is_option_row(trade):
        try:
            vpu *= float(meta.get("multiplier") or 100)
        except (TypeError, ValueError):
            vpu *= 100
    return vpu


def _trade_to_position(trade, instruments, quotes):
    """Normalize one AssetBotTrade into the Position shape.

    Dollar P&L honours metadata["value_per_unit"] (recorded by sizing for
    forex) so a JPY position isn't booked at raw units — the same
    convention every close path applies.
    """
    up = UnifiedPosition()
    inst = instruments.get(trade.symbol)
    up.instrument = inst or _InstrumentShim(trade.symbol, trade.asset_class)
    side = (trade.side or "").upper()
    up.direction = "long" if side in ("BUY", "LONG") else "short"
    sign = 1 if up.direction == "long" else -1
    up.quantity = trade.qty
    up.entry_price = trade.entry_price
    up.stop_loss = trade.stop_loss
    up.take_profit = trade.take_profit
    up.opened_at = trade.opened_at
    up.closed_at = trade.closed_at
    up.strategy = _StrategyShim(trade.rule_name) if trade.rule_name else None
    up.source = "bot"
    up.paper = trade.paper
    up.trade_id = trade.id
    up.status = trade.status

    entry = float(trade.entry_price or 0)
    qty = float(trade.qty or 0)
    vpu = value_per_unit(trade)
    is_option = is_option_row(trade)

    if trade.status == "CLOSED":
        up.current_price = trade.exit_price
        pnl = float(trade.pnl or 0)
        up.unrealized_pnl = pnl
        notional = abs(entry * qty * vpu)
        up.unrealized_pnl_pct = round(pnl / notional * 100, 2) if notional else None
        return up

    if is_option:
        # No option-price feed exists: the only quote we could join is
        # the UNDERLYING's, and premium-vs-underlying comparisons book
        # fictitious P&L (+6000% on an at-the-money call). Honest unknown
        # beats confident fiction — the cells render an em-dash.
        up.current_price = None
        up.unrealized_pnl = None
        up.unrealized_pnl_pct = None
        return up

    quote = quotes.get(trade.symbol)
    last = float(quote.last) if quote and quote.last is not None else None
    up.current_price = quote.last if quote else None
    if last is not None and entry:
        up.unrealized_pnl = round((last - entry) * qty * vpu * sign, 2)
        up.unrealized_pnl_pct = round((last - entry) / entry * 100 * sign, 2)
    else:
        up.unrealized_pnl = None
        up.unrealized_pnl_pct = None
    return up


def _normalize_trades(trades):
    from instruments.models import Instrument
    from market_data.models import LiveQuote

    symbols = {t.symbol for t in trades}
    if not symbols:
        return []
    instruments = {i.symbol: i for i in
                   Instrument.objects.filter(symbol__in=symbols)}
    quotes = {q.instrument.symbol: q for q in
              LiveQuote.objects.select_related("instrument")
              .filter(instrument__symbol__in=symbols)}
    return [_trade_to_position(t, instruments, quotes) for t in trades]


def unified_open_positions(user, portfolio=None):
    """Every open position the user actually holds, Position-shaped:
    open/close-pending AssetBotTrades (per-user) + the given portfolio's
    open Position rows. The portfolio DEFAULTS TO THE SHARED "Main" book
    on purpose: it is the only Position book the background pipeline
    maintains (snapshots, mark-to-market, eToro sync, the REST API and
    the Telegram digest all speak "Main") — reading a per-user book here
    surfaced rows nothing ever marks and hid the existing history.
    CLOSE_PENDING counts as exposure everywhere else, so it counts here."""
    from bot_program.models import AssetBotTrade

    pf = portfolio or get_or_create_default_portfolio()
    positions = list(pf.positions.filter(closed_at__isnull=True)
                     .select_related("instrument", "strategy"))
    trades = list(AssetBotTrade.objects.filter(
        config__user=user, status__in=("OPEN", "CLOSE_PENDING"))
        .order_by("-opened_at"))
    return positions + _normalize_trades(trades)


def unified_closed_positions(user, portfolio=None):
    """Closed history across both books. AssetBotTrade closes carry real
    realized P&L (trade.pnl) — Position closes reuse unrealized_pnl, the
    only P&L field that model has."""
    from bot_program.models import AssetBotTrade

    pf = portfolio or get_or_create_default_portfolio()
    positions = list(pf.positions.filter(closed_at__isnull=False)
                     .select_related("instrument", "strategy"))
    trades = list(AssetBotTrade.objects.filter(
        config__user=user, status="CLOSED").order_by("-closed_at"))
    merged = positions + _normalize_trades(trades)
    merged.sort(key=lambda p: p.closed_at or timezone_min(), reverse=True)
    return merged


def timezone_min():
    from datetime import datetime, timezone as _tz
    return datetime.min.replace(tzinfo=_tz.utc)
