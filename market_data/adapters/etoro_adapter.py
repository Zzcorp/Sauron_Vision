"""eToro API adapter — portfolio sync, positions, trading."""
import os
import requests
import logging

logger = logging.getLogger(__name__)

API_KEY = os.getenv("ETORO_API_KEY", "")
BASE_URL = "https://api.etoro.com"  # Official eToro API


class EtoroClient:
    """Client for eToro Public API."""

    def __init__(self, api_key=None):
        self.api_key = api_key or API_KEY
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            })

    def is_configured(self):
        return bool(self.api_key)

    def get_portfolio(self):
        """Fetch current portfolio positions from eToro."""
        try:
            resp = self.session.get(f"{BASE_URL}/api/v1/portfolio")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"eToro portfolio fetch failed: {e}")
            return None

    def get_positions(self):
        """Fetch open positions."""
        try:
            resp = self.session.get(f"{BASE_URL}/api/v1/positions")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"eToro positions fetch failed: {e}")
            return None

    def get_account_balance(self):
        """Fetch account balance and equity."""
        try:
            resp = self.session.get(f"{BASE_URL}/api/v1/account/balance")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"eToro balance fetch failed: {e}")
            return None


def _usable_mark(value):
    """A finite, strictly positive price, or None.

    Zero is not a price. eToro reports currentRate 0 for a halted or
    unpriced instrument, and it must not reach the mark table as a fact.
    """
    from decimal import Decimal, InvalidOperation
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return d if d.is_finite() and d > 0 else None


def sync_etoro_positions():
    """Sync eToro positions into Sauron Vision portfolio."""
    from instruments.models import Instrument
    from market_data.quotes import write_quote
    from portfolio.models import Position
    from portfolio.services import get_or_create_default_portfolio
    from django.utils import timezone

    client = EtoroClient()
    if not client.is_configured():
        logger.warning("eToro API key not configured")
        return {"status": "not_configured"}

    positions_data = client.get_positions()
    if not positions_data:
        return {"status": "fetch_failed"}

    # The shared "Main" book, because this sync has no user to attribute to:
    # it authenticates with ONE global ETORO_API_KEY, so it describes the
    # platform's broker account rather than any operator's own book.
    #
    # KNOWN CONSEQUENCE, recorded rather than hidden: the position pages and
    # /portfolio/ read each USER's book, so positions imported here are not
    # displayed on them. That is the honest state of a single-key sync on a
    # multi-user install — the alternative was showing every operator the
    # same broker account and calling it theirs. Attributing the sync to a
    # user needs per-user eToro credentials, which is a bigger change than
    # a book swap and should not be faked by guessing an owner.
    portfolio = get_or_create_default_portfolio()
    synced = skipped = 0

    for pos in positions_data.get("positions", []):
        symbol = (pos.get("symbol") or "").strip().upper()
        if not symbol:
            # eToro's API is instrumentId-based and can answer without a
            # ticker. Instrument.symbol is unique but "" is a legal value, so
            # an unguarded get_or_create collapsed EVERY unsymboled position
            # — this sync and every future one — onto one blank row. The
            # Position upsert underneath then overwrote that single row on
            # each iteration, and N distinct real-money holdings were recorded
            # as one carrying the last one's quantity and P&L, with the book
            # value and the risk denominator wrong by whatever the discarded
            # positions were worth. A position we cannot name is skipped and
            # counted, not merged into a fiction.
            logger.warning(
                "eToro position %r has no symbol — skipped rather than "
                "merged onto a blank Instrument row",
                pos.get("positionId") or pos.get("instrumentId") or "?")
            skipped += 1
            continue

        instrument, _ = Instrument.objects.get_or_create(
            symbol=symbol,
            defaults={
                "name": pos.get("name", symbol),
                "asset_class": "stock",
                "exchange": "ETORO",
                "is_active": True,
            }
        )

        # The broker's mark goes into the platform's ONE mark table, not just
        # into the position row. Everything that values a book reads LiveQuote
        # — and these instruments are created with is_watchlist=False and no
        # bot config, which signals.universe excludes from the quote sweep, so
        # nothing else will ever quote them. Without this the broker's own
        # positions counted as UNPRICED: the book value went unmeasured, the
        # nightly snapshot was skipped, the equity curve stopped and the risk
        # denominator froze — on the real-money book, silently.
        #
        # Through the one writer now, and past a real price check first. The
        # old guard was `current_rate not in (None, "")`, which 0 satisfies,
        # so a halted instrument's currentRate of 0 went in as a genuine mark
        # under a source the priority table does not name — and then held
        # that zero against yfinance and coingecko for the full 300-second
        # hold while portfolio/services valued the position at nothing.
        current_rate = pos.get("currentRate")
        mark = _usable_mark(current_rate)
        if mark is not None:
            write_quote(instrument.symbol, last=mark, source="etoro",
                        instrument=instrument)
        elif current_rate not in (None, ""):
            logger.warning(
                "eToro sent an unusable currentRate for %s (%r); the "
                "position is recorded but stays unpriced.",
                instrument.symbol, current_rate)

        Position.objects.update_or_create(
            portfolio=portfolio,
            instrument=instrument,
            closed_at__isnull=True,
            defaults={
                "direction": "long" if pos.get("isBuy", True) else "short",
                "quantity": pos.get("amount", 0),
                "entry_price": pos.get("openRate", 0),
                # The same validated mark the quote table got. Handing the
                # raw field through meant an unusable currentRate reached a
                # DecimalField and raised out of the loop, so ONE malformed
                # position aborted the sync and every holding after it in
                # the payload went unrecorded — on the real-money book,
                # under a warning that said the position was recorded. With
                # no usable mark the row values at cost rather than at zero.
                "current_price": (mark if mark is not None
                                  else pos.get("openRate", 0)),
                "stop_loss": pos.get("stopLossRate"),
                "take_profit": pos.get("takeProfitRate"),
                "unrealized_pnl": pos.get("netProfit", 0),
                "unrealized_pnl_pct": pos.get("netProfitPercentage", 0),
                "opened_at": timezone.now(),
            }
        )
        synced += 1

    # Sync balance
    balance = client.get_account_balance()
    if balance:
        portfolio.current_value = balance.get("equity", portfolio.current_value)
        portfolio.cash_available = balance.get("availableBalance", portfolio.cash_available)
        portfolio.save()

    out = {"status": "success", "synced": synced}
    if skipped:
        # Surfaced rather than swallowed: a sync that reports success while
        # silently dropping holdings is how a book goes wrong unnoticed.
        out["skipped_unsymboled"] = skipped
    return out
