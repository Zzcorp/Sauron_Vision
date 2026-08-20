"""Celery tasks for portfolio — gated."""
from decimal import Decimal

from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)

# A position mark accepts data up to a day old: this runs hourly for
# valuation, not for stop management, so "the freshest print we have" beats
# "nothing" — but a weeks-dead feed must not keep repainting the same price.
MARK_MAX_AGE_HOURS = 24


def _mark_for(instrument):
    """Freshest usable price for an instrument, or None to leave the mark."""
    from datetime import timedelta
    from django.utils import timezone
    from market_data.models import LiveQuote, PriceData

    cutoff = timezone.now() - timedelta(hours=MARK_MAX_AGE_HOURS)
    try:
        lq = LiveQuote.objects.filter(instrument=instrument).first()
        if lq and lq.last and lq.updated_at >= cutoff:
            return lq.last
    except Exception:
        pass
    try:
        pd = (PriceData.objects
              .filter(instrument=instrument, timestamp__gte=cutoff)
              .order_by("-timestamp").first())
        if pd:
            return pd.close
    except Exception:
        pass
    return None


def mark_positions_to_market(positions) -> int:
    """Refresh current_price + unrealized P&L on open positions. Returns the
    number of rows marked.

    Position.unrealized_pnl had a writer NOBODY scheduled (the manual eToro
    sync) and a model default of 0 — so every dashboard that summed it
    rendered +0.00 forever, and core/context_processors.py grew a parallel
    AssetBotTrade path just to avoid it. The sign convention is the one the
    closed-trade recompute paths already use: (mark - entry) * qty, negated
    for direction="short".
    """
    marked = 0
    for pos in positions:
        mark = _mark_for(pos.instrument) if pos.instrument else None
        if mark is None:
            continue
        entry = pos.entry_price or 0
        pnl = (mark - entry) * pos.quantity
        if (pos.direction or "").lower() == "short":
            pnl = -pnl
        pos.current_price = mark
        pos.unrealized_pnl = pnl
        pos.unrealized_pnl_pct = (
            float((mark - entry) / entry * 100) if entry else 0.0)
        if (pos.direction or "").lower() == "short":
            pos.unrealized_pnl_pct = -pos.unrealized_pnl_pct
        pos.save(update_fields=["current_price", "unrealized_pnl",
                                "unrealized_pnl_pct"])
        marked += 1
    return marked


def value_and_exposure(portfolio):
    """(BookValue, by asset class, by sector, by currency) for one book.

    BOTH books. This task used to query
    `Position.objects.filter(portfolio=..., closed_at__isnull=True)` and
    nothing else, so on an account whose positions are AssetBotTrade rows —
    which is every bot entry and every TAKE TRADE — the total it wrote was
    cash and only cash, forever. `portfolio.services.live_book_value` is the
    platform's one answer to "what is this book worth right now", and using it
    here is what makes the stored column agree with the surfaces instead of
    contradicting them.

    The owner comes from the book's own name because Portfolio has no user FK
    and a Celery task has no request to take a user from. The shared "Main"
    book has no owner, so its bot half is empty by construction and it is
    valued from the legacy half exactly as before.

    A row with no quote is left out of every figure here, the same rule the
    live surfaces follow — the returned BookValue carries `n_unpriced` so the
    caller can refuse to write a total that measured nothing at all.
    """
    from portfolio.services import live_book_value, portfolio_owner

    book = live_book_value(portfolio_owner(portfolio), portfolio)

    by_asset_class, by_sector, by_currency = {}, {}, {}
    for row in book.rows:
        if row.current_price is None:
            continue
        # abs(), and the same product `_open_book` sums into `marked`, so the
        # breakdowns add up to the total printed beside them. A short position
        # is exposure of the same size as a long one, not negative exposure.
        value = abs(float(row.current_price) * float(row.quantity or 0))
        inst = getattr(row, "instrument", None)
        # A bot row whose symbol matches no Instrument arrives on a shim that
        # carries asset_class and nothing else, so sector and currency fall
        # back the same way a Position with no instrument always has.
        asset_class = getattr(inst, "asset_class", "") or "unknown"
        sector = getattr(inst, "sector", None) or "unknown"
        currency = getattr(inst, "currency", None) or "USD"
        by_asset_class[asset_class] = by_asset_class.get(asset_class, 0.0) + value
        by_sector[sector] = by_sector.get(sector, 0.0) + value
        by_currency[currency] = by_currency.get(currency, 0.0) + value

    return book, by_asset_class, by_sector, by_currency


def store_book_value(portfolio, book) -> bool:
    """Write a re-valued book into the stored column. True if it was written.

    Refuses when the union measured NOTHING — positions are open and not one
    of them carries a quote. Writing cash-only in that state would tell
    `portfolio.risk_gate.book_value()`, which scales every risk limit as a
    percentage of this column, that the exposure had gone away; a risk
    denominator must never shrink by accident. The previous value stands and
    the caller reports the refusal.

    It refuses a PARTIAL sum for the same reason, and that case is the one
    that actually happens. "None priced" is loud and rare; "four of five
    priced" is quiet and routine, and it writes a number that is wrong by
    exactly the missing row — shrinking the denominator every ceiling is a
    percentage of, and dropping a step into the equity curve that reads as a
    loss nobody took. A stale denominator is merely old. A confidently
    shrunken one moves gates.

    The str() round-trip is deliberate: on the run that CREATES the portfolio
    the instance still holds whatever types the creator passed in, and
    float + Decimal is how the very first exposure run on a fresh deploy died.
    """
    if book.value is None or book.partial:
        return False
    portfolio.current_value = Decimal(str(round(book.value, 2)))
    portfolio.save(update_fields=["current_value", "updated_at"])
    return True


@shared_task
@guarded_task("pipeline_exposure")
def recalculate_exposure():
    """Tier 3: mark open positions to market, then re-value EVERY book.

    Two things changed here, and both were the same defect. The task valued
    the legacy Position book alone, and it only ever touched the shared "Main"
    portfolio — while the pages an operator reads work on their per-user book,
    whose `current_value` was therefore written once at creation and never
    again. It sat at the seeded 10,000 while the operator traded.

    The column is kept and made true rather than deprecated. `risk_gate`
    scales max daily loss, max total exposure and max single position as
    percentages OF it, and unlike a dashboard cell a mis-scaled gate shows
    nobody anything — so the fix has to reach the stored number, not just the
    surfaces reading it.
    """
    logger.info("Recalculating portfolio exposure")

    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import Portfolio, Position

    # Called for its create side-effect: on a fresh deploy this is the run
    # that brings the shared book into existence, and the loop below would
    # otherwise iterate over nothing and report a healthy no-op.
    main = get_or_create_default_portfolio()

    books, main_row = [], None
    for portfolio in Portfolio.objects.all().order_by("id"):
        positions = Position.objects.filter(
            portfolio=portfolio, closed_at__isnull=True
        ).select_related("instrument")

        # This PERSISTS current_price and unrealized_pnl on the legacy rows,
        # which is a write the rest of the platform depends on and not an
        # input to the sum below — the union re-prices from LiveQuote in
        # memory either way. It also applies MARK_MAX_AGE_HOURS, which the
        # union does not: the union follows the same freshness policy as every
        # live surface, which is one policy where the task used to have two.
        n_rows_marked = mark_positions_to_market(positions)

        book, by_class, by_sector, by_currency = value_and_exposure(portfolio)
        wrote = store_book_value(portfolio, book)
        if not wrote:
            logger.warning(
                "Portfolio %s: %s — stored value left at %s",
                portfolio.name, book.coverage, portfolio.current_value)

        row = {
            "portfolio_id": portfolio.id,
            "portfolio": portfolio.name,
            "current_value": float(portfolio.current_value),
            "value_written": wrote,
            "cash": book.cash,
            "position_count": book.n_open,
            "priced": book.n_priced,
            "unpriced": book.n_unpriced,
            # A COUNT of legacy rows re-marked, not a money figure — the name
            # predates `book.marked` beside it and older callers read it.
            "marked": n_rows_marked,
            "deployed": book.marked,
            "exposure_by_asset_class": by_class,
            "exposure_by_sector": by_sector,
            "exposure_by_currency": by_currency,
        }
        books.append(row)
        if portfolio.pk == main.pk:
            main_row = row

        logger.info(
            "Exposure recalculated for %s: total_value=%s deployed=%s "
            "cash=%s (%s)",
            portfolio.name, book.value, book.marked, book.cash, book.coverage)

    # The shared book's figures stay at the TOP LEVEL of the payload: it is
    # the book the risk gates read, and the run log has always answered "what
    # is the platform's exposure" from these keys. Per-book detail is in
    # "books" underneath.
    out = dict(main_row or {"portfolio_id": main.pk, "portfolio": main.name,
                            "current_value": float(main.current_value),
                            "value_written": False, "cash": None,
                            "position_count": 0, "priced": 0, "unpriced": 0,
                            "marked": 0, "deployed": None,
                            "exposure_by_asset_class": {},
                            "exposure_by_sector": {},
                            "exposure_by_currency": {}})
    # "marked" is deliberately NOT a task-gate count key: a day with zero
    # open positions is a healthy no-op, not "ran and produced nothing".
    out["status"] = "ok"
    out["books"] = books
    return out


def _snapshot_book(portfolio, today, yesterday):
    """Take today's snapshot of ONE book, or return None if it cannot be.

    The value is the live union of both books, not the legacy half: a
    snapshot series built from the frozen half is the equity curve, the daily
    P&L and the drawdown watermark that the whole platform reads, and all
    three sat flat on an account whose positions are bot trades.

    None when nothing open could be priced. PortfolioSnapshot.total_value is
    a non-null column, so the only way to record "unknown" is to record
    nothing — and writing the cash-only figure instead would put a fabricated
    point on the equity curve, book a fictitious daily loss the size of the
    whole open book, and reset the drawdown peak against it.
    """
    from portfolio.models import PortfolioSnapshot

    book, by_class, by_sector, by_currency = value_and_exposure(portfolio)
    if book.value is None or book.partial:
        # Partial is refused here for the same reason store_book_value
        # refuses it, and it matters more on a CURVE: a point that is short
        # by one unpriced row is a dip that never happened, and the drawdown
        # watermark then measures itself against it forever. A gap in the
        # series is visibly a gap; a wrong point is not.
        logger.warning("No snapshot for %s on %s: %s",
                       portfolio.name, today, book.coverage)
        return None

    total_value = book.value
    store_book_value(portfolio, book)

    # Retrieve yesterday's snapshot for daily P&L comparison
    try:
        yesterday_snap = PortfolioSnapshot.objects.get(
            portfolio=portfolio, date=yesterday
        )
        prev_value = float(yesterday_snap.total_value)
    except PortfolioSnapshot.DoesNotExist:
        yesterday_snap = None
        prev_value = float(portfolio.initial_capital)

    daily_pnl = total_value - prev_value
    daily_pnl_pct = (daily_pnl / prev_value * 100) if prev_value != 0 else 0.0

    # Cumulative P&L vs initial capital
    initial = float(portfolio.initial_capital)
    cumulative_pnl_pct = ((total_value - initial) / initial * 100) if initial != 0 else 0.0

    # Max drawdown from all historical snapshots
    all_values = list(
        PortfolioSnapshot.objects.filter(portfolio=portfolio)
        .order_by("date")
        .values_list("total_value", flat=True)
    )
    all_values_f = [float(v) for v in all_values] + [total_value]

    peak = all_values_f[0]
    max_drawdown = 0.0
    for v in all_values_f:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak * 100
            if dd < max_drawdown:
                max_drawdown = dd

    # Phase-2 addition: compute the correlation matrix across open positions.
    # Best-effort: a degenerate matrix never blocks the snapshot from being written.
    try:
        from portfolio.correlation import portfolio_correlation
        cm = portfolio_correlation(portfolio)
        correlation_matrix = cm.to_dict()
    except Exception as e:
        logger.warning("correlation matrix computation failed: %s — saving empty", e)
        correlation_matrix = {}

    # Create or update the snapshot for today
    snap, created = PortfolioSnapshot.objects.update_or_create(
        portfolio=portfolio,
        date=today,
        defaults={
            "total_value": Decimal(str(round(total_value, 2))),
            "cash": portfolio.cash_available,
            "daily_pnl": Decimal(str(round(daily_pnl, 2))),
            "daily_pnl_pct": round(daily_pnl_pct, 4),
            "cumulative_pnl_pct": round(cumulative_pnl_pct, 4),
            "max_drawdown": round(max_drawdown, 4),
            "sharpe_ratio": None,
            "exposure_by_asset_class": by_class,
            "exposure_by_sector": by_sector,
            "exposure_by_currency": by_currency,
            "correlation_matrix": correlation_matrix,
        },
    )

    action = "created" if created else "updated"
    logger.info(
        "Daily snapshot %s for %s on %s: value=%.2f daily_pnl=%.2f "
        "cumulative=%.4f%% (%s)",
        action, portfolio.name, today, total_value, daily_pnl,
        cumulative_pnl_pct, book.coverage,
    )

    return {
        "status": "ok",
        "date": str(today),
        "snapshot_id": snap.id,
        "action": action,
        "portfolio_id": portfolio.id,
        "portfolio": portfolio.name,
        "total_value": round(total_value, 2),
        "cash": book.cash,
        "daily_pnl": round(daily_pnl, 2),
        "daily_pnl_pct": round(daily_pnl_pct, 4),
        "cumulative_pnl_pct": round(cumulative_pnl_pct, 4),
        "max_drawdown": round(max_drawdown, 4),
        "open_positions": book.n_open,
        # The snapshot's own honesty flag. A total that left rows out is not
        # the same number as one that priced the whole book, and a reader
        # comparing two days of the curve has to be able to tell them apart.
        "unpriced": book.n_unpriced,
        "partial": book.partial,
        "exposure_by_asset_class": by_class,
        "exposure_by_sector": by_sector,
        "exposure_by_currency": by_currency,
    }


@shared_task
@guarded_task("pipeline_snapshot")
def create_daily_snapshot():
    """Tier 5: end-of-day snapshot, for EVERY book.

    It used to snapshot the shared "Main" portfolio alone, so the per-user
    books the pages actually read had no snapshot series at all — which is why
    the headband's drawdown cell, the portfolio page's equity curve and every
    "day change" on the Operations Center were permanently unmeasured on the
    operator's own account. One snapshot per portfolio, each valued from its
    own union of the two books.
    """
    logger.info("Creating daily portfolio snapshots")

    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import Portfolio
    from django.utils import timezone
    from datetime import timedelta

    # Called for its create side-effect, exactly as in recalculate_exposure:
    # on a fresh deploy this run is the shared book's creator.
    main = get_or_create_default_portfolio()
    today = timezone.now().date()
    yesterday = today - timedelta(days=1)

    snapshots, skipped, main_row = [], [], None
    for portfolio in Portfolio.objects.all().order_by("id"):
        row = _snapshot_book(portfolio, today, yesterday)
        if row is None:
            skipped.append(portfolio.name)
            continue
        snapshots.append(row)
        if portfolio.pk == main.pk:
            main_row = row

    # The shared book stays at the top level: every existing caller and every
    # run log reads these keys. `skipped` names the books whose open positions
    # could not be priced, so a missing point on a curve has a reason attached
    # rather than looking like the task never ran.
    out = dict(main_row or {"date": str(today), "portfolio_id": main.pk,
                            "portfolio": main.name, "snapshot_id": None,
                            "action": "skipped", "total_value": None})
    out["status"] = "ok"
    out["books"] = snapshots
    out["skipped"] = skipped
    return out
