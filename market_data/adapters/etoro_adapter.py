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
        # The budget's words for the last read it did not send, or ""
        # (2026-11-02): the sync tells "not asked" from a failed fetch.
        self.not_asked = ""
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            })

    def is_configured(self):
        return bool(self.api_key)

    def _budgeted(self, what: str) -> bool:
        """THE eTORO REQUEST BUDGET (2026-11-01, bot_program/engine/
        etoro_budget): each GET here is an account read at P2. This legacy
        sync carries no user key, so its budget is keyed by the hash of
        its own key (never the key). False when the budget did not send
        it: the getter answers None, as for a failed fetch, nothing was
        asked, and `not_asked` keeps the budget's words (2026-11-02), so
        sync_etoro_positions says so instead of a failure."""
        from bot_program.engine import etoro_budget
        try:
            etoro_budget.take(etoro_budget.key_hash(self.api_key),
                              etoro_budget.ACCOUNT, etoro_budget.P2,
                              where="account", why=f"legacy sync: {what}")
            return True
        except etoro_budget.Refused as e:
            logger.info("eToro %s not asked: %s", what, e)
            self.not_asked = str(getattr(e, "why", "") or e)
            return False

    def get_portfolio(self):
        """Fetch current portfolio positions from eToro."""
        if not self._budgeted("portfolio fetch"):
            return None
        try:
            resp = self.session.get(f"{BASE_URL}/api/v1/portfolio")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"eToro portfolio fetch failed: {e}")
            return None

    def get_positions(self):
        """Fetch open positions."""
        if not self._budgeted("positions fetch"):
            return None
        try:
            resp = self.session.get(f"{BASE_URL}/api/v1/positions")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"eToro positions fetch failed: {e}")
            return None

    def get_account_balance(self):
        """Fetch account balance and equity."""
        if not self._budgeted("balance fetch"):
            return None
        try:
            resp = self.session.get(f"{BASE_URL}/api/v1/account/balance")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"eToro balance fetch failed: {e}")
            return None


def sync_etoro_positions():
    """Sync eToro positions into Sauron Vision portfolio."""
    from decimal import Decimal, InvalidOperation

    from instruments.models import Instrument
    from market_data.models import LiveQuote
    from portfolio.models import Position
    from portfolio.services import get_or_create_default_portfolio
    from django.utils import timezone

    client = EtoroClient()
    if not client.is_configured():
        logger.warning("eToro API key not configured")
        return {"status": "not_configured"}

    positions_data = client.get_positions()
    if not positions_data:
        if client.not_asked:
            # THE BUDGET DID NOT SEND IT (2026-11-02, completes E1): nothing
            # was asked, so nothing failed and the key is not in question
            return {"status": "not_asked", "why": client.not_asked}
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
    synced = 0

    for pos in positions_data.get("positions", []):
        symbol = pos.get("symbol", "")
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
        # Through write_quote, not around it. `not in (None, "")` ADMITS A
        # LITERAL 0, and this wrote Decimal("0") straight into LiveQuote —
        # the exact case write_quote refuses, because "a 0 written into
        # LiveQuote reads downstream as a real price of zero". This row
        # values the REAL-MONEY book, per the comment above.
        #
        # A False return means the price was unusable or a better source
        # holds the row; either way the position stays honestly UNPRICED
        # rather than being marked at zero.
        current_rate = pos.get("currentRate")
        if current_rate not in (None, ""):
            from market_data.quotes import write_quote
            if not write_quote(instrument.symbol, last=current_rate,
                               source="etoro", instrument=instrument):
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
                "current_price": pos.get("currentRate", 0),
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

    return {"status": "success", "synced": synced}
