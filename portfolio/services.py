"""Portfolio services — user-aware."""
import logging
from decimal import Decimal
from typing import NamedTuple, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# How a per-user book is named, and the name of the shared one. These are the
# ONLY link between a Portfolio row and the person whose trades belong to it:
# portfolio.Portfolio carries no user FK, so a background task holding a book
# has no request to take a user from. `portfolio_owner` below is the exact
# inverse of the name `get_or_create_default_portfolio` builds, and it lives
# beside it so the two spellings cannot drift apart.
PER_USER_SUFFIX = "_main"
SHARED_BOOK_NAME = "Main"

# The sign to put in front of a money figure. Every surface used to hardcode a
# € or a $ regardless of what the book was denominated in, which is a claim
# about the account rather than a decoration. A currency with no glyph here
# prints as its CODE plus a space — "SEK 12,400" is honest; a euro sign on a
# dollar book is not.
CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥",
                    "CHF": "CHF "}


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


def portfolio_owner(portfolio):
    """The user whose book this is, or None for the shared "Main" book.

    The inverse of the naming above. A Celery task re-pricing a book it was
    handed rather than asked for needs to know whose AssetBotTrades belong to
    it, and the name is the only record of that. None is a real answer and not
    a failure: the shared book genuinely has no owner, and its bot half is
    therefore empty — see `unified_open_positions`.

    `.first()` and not `.get()`: a hand-created portfolio whose name merely
    LOOKS like the convention has no owner either, and that is a book to value
    from the legacy half, not an exception to raise inside an hourly task.
    """
    from django.contrib.auth import get_user_model

    name = portfolio.name or ""
    if not name.endswith(PER_USER_SUFFIX):
        return None
    return get_user_model().objects.filter(
        username=name[:-len(PER_USER_SUFFIX)]).first()


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
    CLOSE_PENDING counts as exposure everywhere else, so it counts here.

    `user=None` means a book with no owner — the shared "Main" one — and the
    bot half is then skipped OUTRIGHT rather than filtered on
    `config__user=None`. Both return the same empty set today, but only one of
    them says why: nobody's bot trades belong to a book nobody owns, and a
    filter that happens to match nothing is a fact about the schema rather
    than a decision anyone made."""
    from bot_program.models import AssetBotTrade

    pf = portfolio or get_or_create_default_portfolio()
    positions = list(pf.positions.filter(closed_at__isnull=True)
                     .select_related("instrument", "strategy"))
    if user is None:
        return positions
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
    if user is None:
        # An unowned book, same rule as the open side: no user, no bot half.
        return positions
    trades = list(AssetBotTrade.objects.filter(
        config__user=user, status="CLOSED").order_by("-closed_at"))
    merged = positions + _normalize_trades(trades)
    merged.sort(key=lambda p: p.closed_at or timezone_min(), reverse=True)
    return merged


def timezone_min():
    from datetime import datetime, timezone as _tz
    return datetime.min.replace(tzinfo=_tz.utc)


# ── What the book is worth, right now ───────────────────────────────────
# `Portfolio.current_value` is a STORED column, and its only maintainers were
# two tasks that valued the LEGACY book alone. Every bot entry and every TAKE
# TRADE writes bot_program.AssetBotTrade, so on the operator's own account the
# column never moved off its seeded capital — and it was rendered as "portfolio
# value" by the bottom headband, the Operations Center tab head and hero, the
# portfolio page strip and the PDF report, while `portfolio.risk_gate` scaled
# every risk limit as a percentage of it. This is the one live answer those
# surfaces now share.

class BookValue(NamedTuple):
    """The worth of one book, with every part of the answer beside it.

    A total whose components are invisible is a number nobody can check, and
    this one is a PARTIAL sum whenever a position has no quote — so the count
    that was left out travels with it and the surfaces can say so.
    """
    # cash + marked, or None when nothing open could be priced.
    value: Optional[float]
    # The book's own cash column. None only if it is unreadable — never 0.0
    # as a fallback, which would print as a wiped account.
    cash: Optional[float]
    # Marked notional of the PRICED open rows; 0.0 for an empty book (a real
    # measurement of nothing deployed), None when nothing could be priced.
    marked: Optional[float]
    # Open P&L over the priced rows, straight from `_open_book` — None where
    # it did not measure one, including on an empty book, so a surface that
    # prints it keeps rendering an em-dash rather than a confident "+0.00".
    unrealized: Optional[float]
    n_open: int
    n_priced: int
    n_unpriced: int
    partial: bool
    currency: str
    coverage: str
    rows: list
    # The two halves of `value - cash`, kept beside it so the total stays
    # checkable: real money that LEFT the cash column contributes its marked
    # notional, simulated money that never left it contributes only its P&L.
    # `funded_marked + simulated_pnl` is exactly what the positions added.
    # Defaulted so an older caller constructing a BookValue by keyword does
    # not break, and so the pair reads as "nothing open" rather than unknown.
    funded_marked: float = 0.0
    simulated_pnl: float = 0.0

    @property
    def currency_symbol(self) -> str:
        """The glyph to print before these figures — see CURRENCY_SYMBOLS."""
        return CURRENCY_SYMBOLS.get(
            self.currency, f"{self.currency} " if self.currency else "")

    @property
    def value_text(self) -> Optional[str]:
        """The book value with its currency sign, or None when unmeasured.

        Formatted here so the em-dash rule lives in ONE place instead of in a
        branch on every surface — each of those branches is another chance for
        a cell to quietly print a confident zero.
        """
        if self.value is None:
            return None
        return f"{self.currency_symbol}{self.value:,.2f}"

    @property
    def exposure_pct(self) -> Optional[float]:
        """Share of the book deployed, or None when it is not measurable."""
        if self.value is None or self.value <= 0 or self.marked is None:
            return None
        return self.marked / self.value * 100

    @property
    def cash_pct(self) -> Optional[float]:
        """Share of the book still in cash, or None when not measurable.

        NOT `100 - exposure_pct`: with positions open and none of them priced
        that arithmetic yields 100 and claims the book carries no exposure at
        all, which is the opposite of what an unpriced book means.
        """
        if self.value is None or self.value <= 0 or self.cash is None:
            return None
        return self.cash / self.value * 100



def _simulated_realized_pnl(user) -> float:
    """Cumulative realized P&L over this user's CLOSED simulated trades.

    Since inception, because the seeded capital is the starting point and
    the book value is what that capital has become. A window would make the
    number drift back toward the seed as old trades aged out of it.

    Only `paper` rows. A funded row's realized P&L is already inside the
    broker's cash balance, and counting it here as well would add the whole
    trading history to the account twice.

    0.0 rather than None on an empty history: a book with no closed trades
    has realized exactly nothing, which is a measurement.
    """
    if user is None:
        return 0.0
    try:
        from django.db.models import Sum
        from bot_program.models import AssetBotTrade
        total = (AssetBotTrade.objects
                 .filter(config__user=user, status="CLOSED", paper=True)
                 .aggregate(total=Sum("pnl"))["total"])
        return float(total or 0.0)
    except Exception:  # noqa: BLE001 — a book value must not 500 a page
        logger.warning("Could not read realized P&L for %s; the book value "
                       "excludes closed trades this read.", user, exc_info=True)
        return 0.0


def live_book_value(user, portfolio=None, book=None) -> BookValue:
    """Cash plus everything open, marked — the platform's one book value.

    The union comes from `dashboard.views_command._open_book`, which is the
    platform's single re-pricing of the two position books (it re-marks legacy
    rows in memory against the same LiveQuote table the bot rows used). A third
    walk over the same rows is how two cells on one screen start disagreeing.

    VALUE is cash plus what each open position actually ADDS to the book,
    and those are two different sums depending on where the money came from.

    A position opened with REAL money left the cash column when it opened —
    on a broker-synced book `cash_available` is the broker's availableBalance
    and arrives already debited — so it contributes its marked notional, and
    cash + marked rebuilds equity exactly.

    A SIMULATED position never touched that column. Nothing on this platform
    debits `cash_available` when a paper trade opens; its only writers are
    the /setup/ form, the eToro balance import and the seeder. Adding a paper
    notional on top of cash that still holds it meant opening a position that
    had made NOTHING grew the book by the size of the position — a flat 2-lot
    of gold on a 10,000 book valued it at 14,800. So a simulated row
    contributes only its P&L, which is the only thing about it that is real.

    Both branches agree wherever they can be compared, and the distinction is
    `paper`, a flag the rows already carry rather than a new one to maintain.
    `marked` stays the true deployed notional across BOTH kinds, because
    exposure is a question about position size and not about whose money it
    is — so `exposure_pct` keeps meaning what it says.

    A position with NO QUOTE is left out of `marked` entirely, and deliberately
    not valued at its entry price: entry cost inside a figure labelled "current
    value" is a price claim nobody made, and it would let the total move on a
    fill while the unquoted symbol stayed unquoted. Left out, the total is a
    partial sum — so `n_unpriced`, `partial` and `coverage` come back with it
    and the surfaces show that the number is short of the whole book. When
    NOTHING open can be priced the value is None: an unpriced book is unknown,
    not flat. An EMPTY book is the opposite case and measures zero deployed.

    `user=None` values a book with no owner (the shared "Main" one) from its
    legacy half alone. `book` accepts an `_open_book` 4-tuple the caller
    already holds, so a page rendering both the rows and the total pays for
    the union once.
    """
    from dashboard.views_command import _open_book

    pf = (portfolio if portfolio is not None
          else get_or_create_default_portfolio(user=user))
    rows, n_priced, unrealized, deployed = (
        _open_book(user, pf) if book is None else book)
    n_open = len(rows)

    cash = None
    if pf.cash_available is not None:
        try:
            cash = float(pf.cash_available)
        except (TypeError, ValueError):
            logger.warning("Portfolio %s has an unreadable cash column (%r); "
                           "book value reads as unmeasured rather than zero.",
                           pf.pk, pf.cash_available)

    marked = 0.0 if n_open == 0 else deployed

    # ── What a position ADDS to the book ────────────────────────────────
    # `cash + marked` was the formula this platform already used, and on a
    # broker-synced book it is right: the balance arrives already debited
    # for whatever is deployed, so adding the marked notional back rebuilds
    # equity.
    #
    # On a SIMULATED position it is wrong, and not subtly. Nothing debits
    # `cash_available` when a paper trade opens — grep the writers: the
    # /setup/ form, the eToro balance import, the seeder, and nothing else.
    # So the entry notional was added to a cash column that still held it,
    # and opening a position that had made EXACTLY NOTHING grew the book by
    # its full size: a flat 2-lot of gold on a 10,000 book read as 14,800.
    # A 48% gain, booked for placing a trade. Every percentage downstream
    # inherited it — and because the risk gates are percentages OF this
    # number, an inflated book quietly loosened every ceiling the operator
    # had set, which is the half of this bug that shows nobody anything.
    #
    # So a row contributes what actually moved: real money that left the
    # cash column contributes its marked notional, simulated money that
    # never left it contributes only its P&L.
    simulated_pnl = 0.0
    funded_marked = 0.0
    # REALIZED P&L on closed simulated trades, since inception.
    #
    # Without this the book was a snapshot of what is open and nothing else:
    # a paper trade that lost 500 and closed moved the value by exactly
    # zero, because nothing debits `cash_available` on a simulated fill and
    # the row is no longer open to be marked. An account that had lost half
    # its money over fifty closed trades still read as its seeded capital.
    #
    # Funded rows are deliberately NOT summed here: on a broker-synced book
    # the cash column IS the broker's balance and already has every realized
    # gain and loss in it, so adding them again would double-count the whole
    # trading history.
    simulated_realized = _simulated_realized_pnl(user)
    for row in rows:
        if getattr(row, "current_price", None) is None \
                or getattr(row, "unrealized_pnl", None) is None:
            continue
        if getattr(row, "paper", False):
            simulated_pnl += float(row.unrealized_pnl)
        else:
            funded_marked += abs(float(row.current_price)
                                 * float(row.quantity or 0))

    value = (None if cash is None or marked is None
             else round(cash + funded_marked + simulated_pnl
                        + simulated_realized, 2))

    if n_open == 0:
        coverage = "Nothing open in either book."
    elif n_priced == n_open:
        coverage = f"All {n_open} open positions marked to live quotes."
    elif n_priced:
        coverage = (f"{n_priced} of {n_open} open positions have a live "
                    f"quote; the other {n_open - n_priced} are not in these "
                    f"figures.")
    else:
        coverage = (f"{n_open} open, none with a live quote — value, "
                    f"exposure and P&L cannot be measured.")

    return BookValue(
        value=value, cash=cash, marked=marked, unrealized=unrealized,
        n_open=n_open, n_priced=n_priced, n_unpriced=n_open - n_priced,
        partial=n_open > n_priced, currency=(pf.currency or "").upper(),
        coverage=coverage, rows=rows,
        funded_marked=round(funded_marked, 2),
        simulated_pnl=round(simulated_pnl, 2))
