"""Used and free are eToro's own figures, with the split (2026-10-31).

The operator read on eToro's screen that most of the account was used, and
on every Sauron page a smaller "used" with the rest called "free". Both
were true and no page said what it measured. Sauron's used was its own
rows, at entry over their leverage (portfolio.services.capital_summary); a
position opened in the eToro app, a second position on a symbol Sauron
holds, a close Sauron gave up on, a pending order and the open P&L are in
eToro's figures and in no Sauron row. Its free was the pool's arithmetic,
and a pool that follows the account is eToro's TOTAL value, P&L included.
The order gate already judges every eToro order on eToro's own cells
(AssetBot._cash_gate); the pages now say the same.

WHAT THESE TESTS CONFRONT

  * The cells. One aggregate read carries the P&L, the frozen cash and
    the balance beside the cash and the used margin; the sync and the
    re-read store them under the cells' stamp, a failed read keeps them,
    a figure the payload lacks is None, never 0. margin_cells keeps its
    shape. The holdings keep each eToro row's position id, amount and net
    profit (None when the row does not say).
  * The figures (bot_program.etoro_used.account_used): eToro's used,
    available, P&L and total with their age, for the world the account
    trades in; never read is an em dash; cells read in the other world are
    not shown as this one's.
  * The split, at that read: opened by Sauron (eToro-stamped rows of the
    account's world, open when eToro was read, entry over their leverage),
    Sauron stopped closing (a close given up on that eToro still lists),
    and outside Sauron, eToro's used minus both. A non-USD stock is marked
    unconverted; rows opened since the read are said apart.
  * The outside part, position by position: the holdings matched to
    Sauron's rows by eToro's position id, else one by one by symbol, side
    and the closest units; a leg Sauron closed within eToro's list lag
    still claims its row.
  * Compared by position: the Treasury divergence and the unknown-position
    sweep report a second eToro position on a symbol Sauron holds; the
    Treasury lists CLOSE_PENDING rows, says a row newer than the snapshot
    is newer (never a blocker) and a close Sauron stopped trying apart.
  * Counted once: under shared capital the account is one pool in the
    capital summary, and no gate reads that summary (a source scan).
  * The surfaces: the Horde head, the header dropdown, the capital card,
    the positions head, the Treasury book card, the TAKE TRADE ticket's
    capital line, the portfolio strip and the Ops Center show eToro's own
    figures; nothing on an order path reads them.

AND WHAT THE REVIEW FOUND (2026-10-31)

  * The alert counts positions: two unclaimed eToro positions on one
    symbol ring as two, and its standing condition is the outside
    positions alone, so Sauron's own rows opening or closing beside them
    do not ring it again (the real notifier, Telegram's POST stubbed).
  * A fill booked while the sync was reading claims its own position id;
    a close Sauron stopped trying is "still open at eToro" only while the
    holdings list it; a negative outside part is said the other way
    round; the split's sentences agree in number.
  * The total carries its own age on every surface that prints it beside
    the cells' age; the Ops Center's cell wraps instead of cutting it.
  * The positions page's "At the broker" panel claims as the outside list
    does (a stopped close, a leg inside the list lag, the account's world,
    a row that records no broker said apart).
  * Each new heading of the comparison is pinned on the page, the command
    and vision(): CLOSING, NEWER, STOPPED, UNITS DIFFER, at eToro and on
    the symbol path, where an open row is never hidden behind a closing
    one.

Run with:  python manage.py test tests.test_used_is_etoros
"""
import json
import re
import unittest
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from bot_program.models import EtoroAccount
from tests.test_ticket_checks_like_the_send import _LiveEtoroTicket

BASE = Path(settings.BASE_DIR)
LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
TRADER = "bot_program.engine.etoro_client.EtoroTrader"


# ── fixtures ─────────────────────────────────────────────────────────────

def _user(name):
    return User.objects.create_user(name, password="x")


def _etoro(user, *, demo=False, used="6000.00", cash="3500.00", pnl="500.00",
           total="10000.00", frozen="0.00", balance="9500.00", age_s=240,
           world=None, held=None, held_age_s=None, ccy="USD"):
    """An eToro row whose cells were read `age_s` ago in its own world."""
    acct = EtoroAccount.objects.create(user=user, demo=demo, label="Main",
                                       is_primary_for_stocks=True)
    acct.set_credentials("k", "u")
    at = timezone.now() - timedelta(seconds=age_s)
    if used is not None:
        acct.last_used_margin = Decimal(used)
        acct.last_available_cash = Decimal(cash)
        acct.last_pnl = None if pnl is None else Decimal(pnl)
        acct.last_frozen_cash = None if frozen is None else Decimal(frozen)
        acct.last_balance = None if balance is None else Decimal(balance)
        acct.last_margin_at = at
        acct.last_margin_world = world or ("demo" if demo else "live")
    if total is not None:
        acct.last_equity = Decimal(total)
        acct.last_equity_currency = ccy
        acct.last_equity_at = at
    if held is not None:
        acct.broker_positions = held
        acct.broker_positions_at = timezone.now() - timedelta(
            seconds=age_s if held_age_s is None else held_age_s)
    acct.save()
    return acct


def _cfg(user, cls="stock", name="bot", mode="live", extras=None,
         capital="10000"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=cls, name=name, mode=mode, enabled=True,
        symbols=["AAPL"], capital=Decimal(capital), base_currency="USD",
        extras=extras or {})


def _row(cfg, symbol, qty, entry, *, side="BUY", status="OPEN", paper=False,
         broker="etoro", env=None, lev=None, pid=None, working=False,
         opened_ago_s=3600, closed_ago_s=None):
    """A row opened an hour ago by default: before the cells were read."""
    from bot_program.models import AssetBotTrade
    meta = {}
    if broker:
        meta["broker"] = broker
    if env:
        meta["broker_env"] = env
    if lev is not None:
        meta["leverage"] = lev
    if pid is not None:
        meta["broker_position_id"] = str(pid)
    if working:
        meta.update({"entry_working": True, "qty_requested": float(qty)})
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(str(qty)), entry_price=Decimal(str(entry)),
        status=status, paper=paper, metadata=meta)
    upd = {"opened_at": timezone.now() - timedelta(seconds=opened_ago_s)}
    if closed_ago_s is not None:
        upd["closed_at"] = timezone.now() - timedelta(seconds=closed_ago_s)
    type(t).objects.filter(pk=t.pk).update(**upd)
    t.refresh_from_db()
    return t


def _held(symbol, qty, avg, *, side="BUY", pid=None, amount=None, net=None,
          lev=None):
    """A holdings row as EtoroTrader.broker_portfolio stores it."""
    row = {"symbol": symbol, "sec_type": "CFD", "qty": float(qty),
           "side": side, "avg_cost": float(avg), "market_price": 0.0,
           "market_value": 0.0, "unrealized_pnl": 0.0, "currency": "",
           "position_id": None if pid is None else str(pid),
           "amount": amount, "net_profit": net}
    if lev is not None:
        row["leverage"] = lev
    return row


def _instrument(symbol, cls="stock", currency="USD"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": cls,
                                 "currency": currency})
    return inst


def _fresh(user):
    return User.objects.get(pk=user.pk)


def _used(user, **kw):
    from bot_program.etoro_used import account_used
    return account_used(_fresh(user), **kw)


def _payload(**extra):
    totals = {"accountTotalValue": 10000.0, "accountAvailableCash": 3500.0,
              "accountTotalUsedMargin": 6000.0}
    totals.update(extra)
    return {"accountCurrency": "USD", "accountTotals": totals}


# ── 1. the cells ─────────────────────────────────────────────────────────

class TheAggregateReadCarriesTheRestTests(SimpleTestCase):

    def test_the_snapshot_carries_the_pnl_the_frozen_cash_and_the_balance(self):
        from tests.test_etoro_client import _client
        t, _ = _client([("GET", "aggregate-portfolio", 200, _payload(
            accountCurrentPnl=500.0, accountFrozenCash=20.0,
            accountBalance=9500.0))])
        snap = t.account_snapshot()
        self.assertEqual(snap["figures"], {"pnl": 500.0, "frozen_cash": 20.0,
                                           "balance": 9500.0})
        self.assertEqual(snap["reading"], (10000.0, "USD"))

    def test_a_figure_the_payload_lacks_is_none_never_zero(self):
        from tests.test_etoro_client import _client
        t, _ = _client([("GET", "aggregate-portfolio", 200, _payload())])
        self.assertEqual(t.account_snapshot()["figures"],
                         {"pnl": None, "frozen_cash": None, "balance": None})

    def test_margin_cells_keeps_its_shape(self):
        """The gate's reader answers what it answered: the new figures ride
        the snapshot, never margin_cells."""
        from tests.test_etoro_client import _client
        t, _ = _client([("GET", "aggregate-portfolio", 200, _payload(
            accountCurrentPnl=500.0))])
        self.assertEqual(t.margin_cells(), {"available_cash": 3500.0,
                                            "used_margin": 6000.0,
                                            "currency": "USD"})


class TheSyncAndTheReReadStoreThemTests(TestCase):

    def setUp(self):
        cache.clear()
        from tests.test_reread_after_orders import _components
        _components()
        self.user = _user("ue_cells")
        self.acct = _etoro(self.user, pnl=None, frozen=None, balance=None,
                           age_s=600)

    def test_the_sync_stores_them_under_the_cells_stamp(self):
        from tests.test_etoro_client import _client
        from tests.test_reread_after_orders import _sync
        t, _ = _client([
            ("GET", "aggregate-portfolio", 200, _payload(
                accountCurrentPnl=-120.5, accountFrozenCash=42.5,
                accountBalance=10120.5)),
            ("GET", "portfolio", 200, {"clientPortfolio": {"positions": []}}),
        ], env="live")
        t0 = timezone.now()
        _sync(t)
        acct = EtoroAccount.objects.get(pk=self.acct.pk)
        self.assertEqual(acct.last_pnl, Decimal("-120.50"))
        self.assertEqual(acct.last_frozen_cash, Decimal("42.50"))
        self.assertEqual(acct.last_balance, Decimal("10120.50"))
        self.assertGreaterEqual(acct.last_margin_at, t0)

    def test_the_re_read_after_an_order_stores_them_too(self):
        from bot_program.tasks import refresh_etoro_cells
        before = EtoroAccount.objects.get(pk=self.acct.pk)
        c = MagicMock()
        c.demo = False
        c.account_snapshot.return_value = {
            "reading": (10010.0, "USD"),
            "margin": {"available_cash": 3400.0, "used_margin": 6100.0,
                       "currency": "USD"},
            "figures": {"pnl": 510.0, "frozen_cash": 0.0, "balance": 9500.0}}
        with patch(TRADER, return_value=c):
            self.assertTrue(refresh_etoro_cells(self.acct.pk)["read"])
        acct = EtoroAccount.objects.get(pk=self.acct.pk)
        self.assertEqual(acct.last_pnl, Decimal("510.00"))
        self.assertEqual(acct.last_frozen_cash, Decimal("0.00"))
        self.assertEqual(acct.last_used_margin, Decimal("6100.00"))
        # the equity stays the sync's
        self.assertEqual(acct.last_equity, before.last_equity)
        self.assertEqual(acct.last_equity_at, before.last_equity_at)

    def test_a_failed_read_keeps_them_and_a_lacking_one_is_none(self):
        from bot_program.tasks import refresh_etoro_cells
        EtoroAccount.objects.filter(pk=self.acct.pk).update(
            last_pnl=Decimal("75.00"), last_balance=Decimal("9000.00"))
        c = MagicMock()
        c.demo = False
        c.account_snapshot.return_value = None
        with patch(TRADER, return_value=c):
            self.assertFalse(refresh_etoro_cells(self.acct.pk)["read"])
        self.assertEqual(EtoroAccount.objects.get(pk=self.acct.pk).last_pnl,
                         Decimal("75.00"))
        c.account_snapshot.return_value = {
            "reading": None,
            "margin": {"available_cash": 3400.0, "used_margin": 6100.0,
                       "currency": "USD"},
            "figures": {"pnl": None, "frozen_cash": None, "balance": 9100.0}}
        with patch(TRADER, return_value=c):
            self.assertTrue(refresh_etoro_cells(self.acct.pk)["read"])
        acct = EtoroAccount.objects.get(pk=self.acct.pk)
        # dated by the same stamp as the cells: an old P&L under a new
        # stamp would be a reading nobody took
        self.assertIsNone(acct.last_pnl)
        self.assertEqual(acct.last_balance, Decimal("9100.00"))


class TheHoldingsKeepEachRowsOwnFiguresTests(SimpleTestCase):

    def test_the_position_id_the_amount_and_the_net_profit_are_kept(self):
        from tests.test_etoro_client import SEARCH_AAPL, _client
        t, _ = _client([SEARCH_AAPL, ("GET", "/portfolio", 200, {
            "positions": [
                {"positionID": 11, "instrumentID": 1001, "isBuy": True,
                 "units": 5, "openRate": 150.0, "amount": 750.0,
                 "netProfit": -12.5, "leverage": 1},
                {"positionID": 12, "instrumentID": 1001, "isBuy": True,
                 "units": 2, "openRate": 175.0},
            ]})])
        t.instrument_id("AAPL")
        rows = t.broker_portfolio()
        self.assertEqual((rows[0]["position_id"], rows[0]["amount"],
                          rows[0]["net_profit"]), ("11", 750.0, -12.5))
        # a row that does not say: None, never 0 (three states)
        self.assertEqual((rows[1]["position_id"], rows[1]["amount"],
                          rows[1]["net_profit"]), ("12", None, None))


# ── 2. the figures and the split ─────────────────────────────────────────

class EtorosOwnFiguresHeadlineTests(TestCase):

    def setUp(self):
        self.user = _user("ue_figs")

    def test_no_etoro_row_is_nothing_to_say(self):
        self.assertIsNone(_used(self.user))

    def test_the_figures_their_age_and_the_world(self):
        _etoro(self.user)
        u = _used(self.user)
        self.assertTrue(u["read"])
        self.assertEqual((u["world"], u["world_word"]), ("live", "REAL"))
        self.assertEqual((u["used"], u["available"], u["pnl"], u["total"]),
                         (6000.0, 3500.0, 500.0, 10000.0))
        self.assertEqual(u["currency"], "USD")
        self.assertEqual(u["age_t"], "4 min")
        for piece in ("eToro REAL", "used 6,000.00", "available 3,500.00",
                      "P&L +500.00", "total 10,000.00", "read 4 min ago"):
            self.assertIn(piece, u["t"])

    def test_never_read_is_a_dash_not_a_zero(self):
        _etoro(self.user, used=None, total=None)
        u = _used(self.user)
        self.assertFalse(u["read"])
        self.assertIsNone(u["used"])
        self.assertIsNone(u["outside"])
        self.assertIn("never read", u["t"])
        self.assertNotIn("0.00", u["t"])

    def test_cells_read_in_the_other_world_are_not_this_ones(self):
        """The same key pair answers both worlds; demo cells kept on a row
        unticked to live are six figures of virtual money."""
        _etoro(self.user, world="demo")
        u = _used(self.user)
        self.assertFalse(u["read"])
        self.assertIsNone(u["used"])
        self.assertIn("demo world", u["t"])

    def test_a_total_older_than_the_cells_carries_its_own_age(self):
        """The re-read after an order moves the cells and never the total."""
        acct = _etoro(self.user, age_s=20)
        EtoroAccount.objects.filter(pk=acct.pk).update(
            last_equity_at=timezone.now() - timedelta(minutes=5))
        u = _used(self.user)
        self.assertIn("total 10,000.00 (read 5 min ago)", u["t"])
        self.assertIn("read 20 s ago", u["t"])
        self.assertEqual(u["total_own_age_t"], "5 min")

    def test_a_total_as_fresh_as_the_cells_has_no_age_of_its_own(self):
        _etoro(self.user, age_s=20)
        u = _used(self.user)
        self.assertEqual(u["total_own_age_t"], "")
        self.assertIn("total 10,000.00 · read ", u["t"])


class TheSplitTests(TestCase):
    """6,000 used at eToro. Sauron's eToro rows of the real world: AAPL
    10 x 200 at 1x (2,000), MSFT 5 x 300 at 2x (750), a closing TSLA
    2 x 250 (500) — 3,250 opened by Sauron; a close given up on, NVDA
    4 x 100 (400), which eToro's holdings still list. Outside Sauron:
    6,000 - 3,250 - 400 = 2,350."""

    def setUp(self):
        self.user = _user("ue_split")
        self.acct = _etoro(self.user, held=[_held("NVDA", 4, 100, pid=41)])
        self.cfg = _cfg(self.user)
        _row(self.cfg, "AAPL", 10, 200)
        _row(self.cfg, "MSFT", 5, 300, lev=2)
        _row(self.cfg, "TSLA", 2, 250, status="CLOSE_PENDING")
        _row(self.cfg, "NVDA", 4, 100, status="ERROR", pid=41)
        # none of these is the real account's
        _row(self.cfg, "GLD", 10, 100, env="paper")          # eToro demo
        _row(self.cfg, "SPY", 10, 100, paper=True, broker="paper")
        _row(self.cfg, "SAP", 10, 100, broker="saxo")         # another venue
        _row(self.cfg, "IBM", 10, 100, broker="")             # no stamp

    def test_opened_by_sauron_stopped_closing_and_outside(self):
        u = _used(self.user)
        self.assertEqual((u["sauron"], u["sauron_n"]), (3250.0, 3))
        self.assertEqual((u["stopped"], u["stopped_n"]), (400.0, 1))
        self.assertEqual(u["outside"], 2350.0)
        self.assertEqual(u["unstamped_n"], 1)
        for piece in ("opened by Sauron 3,250.00",
                      "Sauron stopped closing, still open at eToro 400.00",
                      "outside Sauron 2,350.00", "P&L +500.00"):
            self.assertIn(piece, u["split_t"])
        # the whole sentence, its verb agreeing with one row (2026-10-31:
        # it read "1 live row record no broker")
        self.assertEqual(u["split_t"], (
            "At that read: opened by Sauron 3,250.00 · Sauron stopped "
            "closing, still open at eToro 400.00 · outside Sauron 2,350.00 · "
            "P&L +500.00; 1 live row records no broker and is not counted"))
        self.assertIn("eToro's used", u["title"])

    def test_a_row_opened_since_the_read_is_not_in_it(self):
        """eToro's 6,000 is as of its read; a row booked after it is not in
        that figure, and subtracting it would invent money outside."""
        _row(self.cfg, "AMD", 10, 100, opened_ago_s=10)
        u = _used(self.user)
        self.assertEqual(u["sauron"], 3250.0)
        self.assertEqual(u["since_n"], 1)
        self.assertIn("; 1 eToro row opened since that read; ", u["split_t"])

    def test_two_of_each_read_in_the_plural(self):
        _row(self.cfg, "AMD", 10, 100, opened_ago_s=10)
        _row(self.cfg, "AMZN", 1, 100, opened_ago_s=10)
        _row(self.cfg, "ORCL", 1, 100, broker="")
        u = _used(self.user)
        self.assertTrue(u["split_t"].endswith(
            "; 2 eToro rows opened since that read; 2 live rows record no "
            "broker and are not counted"), u["split_t"])

    def test_a_stopped_close_etoro_no_longer_lists_is_not_subtracted(self):
        """The operator closed it in the eToro app, which the close-abandoned
        alert asks him to do: it is in none of eToro's figures, so it is
        neither "still open at eToro" nor taken off eToro's used."""
        EtoroAccount.objects.filter(pk=self.acct.pk).update(
            broker_positions=[])
        u = _used(self.user)
        self.assertEqual((u["stopped"], u["stopped_n"]), (0.0, 0))
        self.assertEqual(u["stopped_gone_n"], 1)
        self.assertEqual(u["outside"], 2750.0)
        self.assertNotIn("still open at eToro", u["split_t"])
        self.assertIn("outside Sauron 2,750.00", u["split_t"])
        self.assertIn("; 1 position Sauron stopped closing is no longer "
                      "listed at eToro and is not counted", u["split_t"])

    def test_two_stopped_closes_gone_read_in_the_plural(self):
        _row(self.cfg, "AMD", 5, 120, status="ERROR", pid=42)
        EtoroAccount.objects.filter(pk=self.acct.pk).update(
            broker_positions=[])
        self.assertIn("; 2 positions Sauron stopped closing are no longer "
                      "listed at eToro and are not counted",
                      _used(self.user)["split_t"])

    def test_holdings_never_read_say_may_still_be_open(self):
        EtoroAccount.objects.filter(pk=self.acct.pk).update(
            broker_positions_at=None)
        u = _used(self.user)
        self.assertEqual((u["stopped"], u["stopped_n"]), (400.0, 1))
        self.assertEqual(u["outside"], 2350.0)
        self.assertIn("Sauron stopped closing, may still be open at eToro "
                      "400.00 · outside Sauron 2,350.00", u["split_t"])

    def test_a_negative_outside_is_said_the_other_way_round(self):
        """Sauron's rows count more than eToro holds: a stop eToro filled
        that Sauron has not booked yet, or a currency counted unconverted.
        "outside Sauron -650.00" said nothing of what it meant."""
        EtoroAccount.objects.filter(pk=self.acct.pk).update(
            last_used_margin=Decimal("3000.00"))
        u = _used(self.user)
        self.assertEqual(u["outside"], -650.0)
        self.assertNotIn("outside Sauron -", u["split_t"])
        self.assertIn("· Sauron's rows count 650.00 more than eToro's used "
                      "(a row eToro no longer holds, or an unconverted "
                      "currency) · P&L +500.00", u["split_t"])

    def test_nothing_outside_is_zero_outside(self):
        EtoroAccount.objects.filter(pk=self.acct.pk).update(
            last_used_margin=Decimal("3650.00"))
        self.assertIn("· outside Sauron 0.00 · ",
                      _used(self.user)["split_t"])

    def test_a_row_open_at_the_read_and_closed_since_was_in_it(self):
        _row(self.cfg, "AMD", 10, 100, status="CLOSED", closed_ago_s=30)
        self.assertEqual(_used(self.user)["sauron"], 4250.0)

    def test_a_non_usd_stock_is_marked_unconverted(self):
        _instrument("SIE", currency="EUR")
        _row(self.cfg, "SIE", 10, 100)
        u = _used(self.user)
        self.assertEqual(u["unconverted"], [{"symbol": "SIE",
                                             "currency": "EUR"}])
        self.assertIn("unconverted: SIE EUR", u["split_t"])

    def test_without_a_reading_the_split_is_not_invented(self):
        EtoroAccount.objects.filter(user=self.user).update(
            last_margin_at=None, last_used_margin=None,
            last_available_cash=None)
        u = _used(self.user)
        self.assertIsNone(u["outside"])
        self.assertIn("outside Sauron —", u["split_t"])

    def test_a_demo_account_reads_its_demo_rows(self):
        other = _user("ue_demo")
        _etoro(other, demo=True)
        cfg = _cfg(other)
        _row(cfg, "GLD", 10, 100, env="paper")
        _row(cfg, "AAPL", 10, 200)                            # real: not it
        u = _used(other)
        self.assertEqual((u["world"], u["world_word"]), ("demo", "DEMO"))
        self.assertEqual(u["sauron"], 1000.0)


class TheOutsidePositionByPositionTests(TestCase):

    def setUp(self):
        self.user = _user("ue_out")
        self.cfg = _cfg(self.user)

    def _held_at(self, rows, held_age_s=120):
        _etoro(self.user, held=rows, held_age_s=held_age_s)

    def test_a_second_position_on_a_held_symbol_is_listed(self):
        self._held_at([_held("NVDA", 5, 150, pid=11, amount=750.0, net=20.0),
                       _held("NVDA", 2, 175, pid=12, amount=350.0, net=12.5),
                       _held("AAPL", 3, 200, pid=13, amount=600.0)])
        _row(self.cfg, "NVDA", 5, 150, pid=11)
        _row(self.cfg, "AAPL", 3, 200)               # older row, no id
        out = _used(self.user, positions=True)["positions"]
        self.assertTrue(out["known"])
        self.assertEqual([(r["symbol"], r["position_id"]) for r in out["rows"]],
                         [("NVDA", "12")])
        row = out["rows"][0]
        self.assertEqual((row["amount"], row["margin"], row["net_profit"],
                          row["estimated"]), (350.0, 350.0, 12.5, False))
        self.assertEqual(out["margin"], 350.0)

    def test_without_ids_the_count_and_the_closest_units_decide(self):
        self._held_at([_held("NVDA", 5, 150), _held("NVDA", 2, 175)])
        _row(self.cfg, "NVDA", 5, 150)
        rows = _used(self.user, positions=True)["positions"]["rows"]
        self.assertEqual([(r["symbol"], r["qty"]) for r in rows],
                         [("NVDA", 2.0)])

    def test_two_different_ids_are_two_positions(self):
        self._held_at([_held("NVDA", 5, 150, pid=21)])
        _row(self.cfg, "NVDA", 5, 150, pid=99)
        rows = _used(self.user, positions=True)["positions"]["rows"]
        self.assertEqual([r["position_id"] for r in rows], ["21"])

    def test_an_amount_the_row_did_not_say_is_estimated_and_said_so(self):
        self._held_at([_held("XAU", 4, 100, lev=2)])
        row = _used(self.user, positions=True)["positions"]["rows"][0]
        self.assertEqual((row["amount"], row["margin"], row["estimated"]),
                         (None, 200.0, True))

    def test_a_leg_closed_inside_the_list_lag_still_claims_its_row(self):
        """eToro lists a closed position for up to a minute: the snapshot
        taken 30 s after Sauron's close still carries it."""
        self._held_at([_held("NVDA", 5, 150, pid=11)], held_age_s=120)
        _row(self.cfg, "NVDA", 5, 150, pid=11, status="CLOSED",
             closed_ago_s=150)
        self.assertEqual(
            _used(self.user, positions=True)["positions"]["rows"], [])

    def test_a_fill_booked_while_the_sync_was_reading_claims_its_own_id(self):
        """The sync dates the holdings before its reads, and a row is booked
        a second or more after eToro's fill: a fill booked between the
        stamp and the /portfolio GET is in the list, and its row was
        dropped as "booked after the read", so Sauron's own managed
        position read as outside for a whole sync while the divergence on
        the same page paired it."""
        self._held_at([_held("NVDA", 5, 150, pid=11)], held_age_s=100)
        _row(self.cfg, "NVDA", 5, 150, pid=11, opened_ago_s=98)
        self.assertEqual(
            _used(self.user, positions=True)["positions"]["rows"], [])
        from bot_program.broker_vision import divergence
        d = [x for x in divergence(_fresh(self.user))
             if x["kind"] == "etoro"][0]
        self.assertEqual((len(d["agree"]), d["only_broker"]), (1, []))

    def test_a_row_booked_after_the_read_with_no_id_claims_nothing(self):
        """Guard: without its own id it cannot be told from a position
        opened beside it, so it claims nothing, as before."""
        self._held_at([_held("NVDA", 5, 150, pid=11)], held_age_s=100)
        _row(self.cfg, "NVDA", 5, 150, opened_ago_s=98)
        rows = _used(self.user, positions=True)["positions"]["rows"]
        self.assertEqual([r["position_id"] for r in rows], ["11"])

    def test_a_row_booked_after_the_read_claims_by_its_id_only(self):
        """Guard: never by symbol and units, which could take the leg of
        another position (one the list names with no id)."""
        self._held_at([_held("NVDA", 5, 150)], held_age_s=100)
        _row(self.cfg, "NVDA", 5, 150, pid=11, opened_ago_s=98)
        rows = _used(self.user, positions=True)["positions"]["rows"]
        self.assertEqual([r["symbol"] for r in rows], ["NVDA"])


# ── 3. compared by position ──────────────────────────────────────────────

class TheTreasuryComparesEtoroByPositionTests(TestCase):

    def setUp(self):
        self.user = _user("ue_tr")
        self.cfg = _cfg(self.user)

    def _div(self):
        from bot_program.broker_vision import divergence
        return [d for d in divergence(_fresh(self.user))
                if d["kind"] == "etoro"][0]

    def test_a_second_position_on_a_held_symbol_is_only_at_the_broker(self):
        _etoro(self.user, held=[_held("NVDA", 5, 150, pid=11),
                                _held("NVDA", 2, 175, pid=12),
                                _held("AAPL", 3, 200, pid=13)])
        _row(self.cfg, "NVDA", 5, 150, pid=11)
        _row(self.cfg, "AAPL", 3, 200, pid=13)
        d = self._div()
        self.assertEqual(d["by"], "position")
        self.assertEqual(len(d["agree"]), 2)
        self.assertEqual([(h["symbol"], h["position_id"])
                          for h in d["only_broker"]], [("NVDA", "12")])
        self.assertEqual(d["only_platform"], [])

    def test_a_closing_row_is_listed_and_claims_its_leg(self):
        from bot_program.broker_vision import platform_positions
        _etoro(self.user, held=[_held("TSLA", 2, 250, pid=31)])
        _row(self.cfg, "TSLA", 2, 250, status="CLOSE_PENDING", pid=31)
        plat = platform_positions(_fresh(self.user))
        self.assertEqual([(p["symbol"], p["status"]) for p in plat["live"]],
                         [("TSLA", "CLOSE_PENDING")])
        d = self._div()
        self.assertEqual(len(d["agree"]), 1)
        self.assertEqual(d["only_broker"], [])

    def test_a_row_newer_than_the_snapshot_is_newer_not_a_blocker(self):
        from bot_program.broker_vision import vision
        _etoro(self.user, held=[_held("NVDA", 5, 150, pid=11)],
               held_age_s=240)
        _row(self.cfg, "NVDA", 5, 150, pid=11)
        _row(self.cfg, "NVDA", 2, 175, pid=12, opened_ago_s=30)
        d = self._div()
        self.assertEqual(d["only_platform"], [])
        self.assertEqual([p["symbol"] for p in d["newer"]], ["NVDA"])
        v = vision(_fresh(self.user))
        self.assertFalse(any("does NOT report" in b for b in v["blockers"]),
                         v["blockers"])

    def test_a_close_sauron_stopped_trying_is_said_apart(self):
        _etoro(self.user, held=[_held("NVDA", 4, 100, pid=41)])
        _row(self.cfg, "NVDA", 4, 100, status="ERROR", pid=41)
        d = self._div()
        self.assertEqual(d["only_broker"], [])
        self.assertEqual([(s["platform"]["symbol"], s["held"] is not None)
                          for s in d["stopped"]], [("NVDA", True)])

    def test_a_closing_row_the_broker_no_longer_lists_is_a_note(self):
        """A close being booked, not a row never finalised: no blocker."""
        from bot_program.broker_vision import vision
        _etoro(self.user, held=[])
        _row(self.cfg, "TSLA", 2, 250, status="CLOSE_PENDING", pid=31)
        d = self._div()
        self.assertEqual(d["only_platform"], [])
        self.assertEqual([p["symbol"] for p in d["closing_gone"]], ["TSLA"])
        v = vision(_fresh(self.user))
        self.assertFalse(any("does NOT report" in b for b in v["blockers"]),
                         v["blockers"])
        self.assertIn("eToro: 1 closing row(s) the broker no longer reports "
                      "— TSLA: the close is being booked.", v["notes"])

    def test_a_stopped_close_the_broker_still_lists_says_close_it(self):
        from bot_program.broker_vision import vision
        _etoro(self.user, held=[_held("NVDA", 4, 100, pid=41)])
        _row(self.cfg, "NVDA", 4, 100, status="ERROR", pid=41)
        _row(self.cfg, "AMD", 5, 120, status="ERROR", pid=42)  # not listed
        notes = vision(_fresh(self.user))["notes"]
        self.assertIn("eToro: Sauron stopped closing 1 position(s) the broker "
                      "still lists — NVDA: close them at the broker.", notes)
        self.assertFalse(any("AMD" in n for n in notes), notes)

    def test_units_that_differ_are_said_on_the_page_and_the_command(self):
        _etoro(self.user, held=[_held("NVDA", 5, 150, pid=11)])
        _row(self.cfg, "NVDA", 4, 150, pid=11)
        d = self._div()
        self.assertEqual([a["units_differ"] for a in d["agree"]], [True])
        self.client.force_login(self.user)
        page = self.client.get(reverse("treasury_page")).content.decode()
        self.assertIn("UNITS DIFFER · NVDA — the broker holds 5.0000, the "
                      "row 4.0000", page)
        out = StringIO()
        call_command("treasury", user="ue_tr", stdout=out)
        self.assertIn("UNITS DIFFER   NVDA         the broker holds 5.0000, "
                      "the row 4.0000", out.getvalue())

    def test_the_command_says_newer_closing_and_stopped(self):
        _etoro(self.user, held=[_held("NVDA", 4, 100, pid=41)],
               held_age_s=240)
        _row(self.cfg, "AMD", 2, 175, pid=12, opened_ago_s=30)
        _row(self.cfg, "TSLA", 2, 250, status="CLOSE_PENDING", pid=31)
        stopped = _row(self.cfg, "NVDA", 4, 100, status="ERROR", pid=41)
        gone = _row(self.cfg, "MSFT", 1, 300, status="ERROR", pid=43)
        out = StringIO()
        call_command("treasury", user="ue_tr", stdout=out)
        body = out.getvalue()
        self.assertIn("NEWER          AMD          BUY   2.0000  (bot) — "
                      "booked after the holdings were read; the next sync "
                      "compares it", body)
        self.assertIn("CLOSING        TSLA         BUY   2.0000  (bot) — the "
                      "broker no longer reports it: the close is being "
                      "booked", body)
        self.assertIn(f"STOPPED        NVDA         BUY   4.0000  "
                      f"(#{stopped.pk}) — Sauron stopped closing it; still "
                      f"open at the broker: close it there", body)
        self.assertIn(f"STOPPED        MSFT         BUY   1.0000  "
                      f"(#{gone.pk}) — Sauron stopped closing it; the broker "
                      f"no longer lists it", body)
        self.assertNotIn("PLATFORM ONLY", body)

    def test_the_outside_card_says_which_stopped_closes_it_counts(self):
        """Its footer names the causes that set the list apart from the
        figure above it."""
        _etoro(self.user, held=[_held("NVDA", 2, 175, pid=12)])
        self.client.force_login(self.user)
        page = self.client.get(reverse("treasury_page")).content.decode()
        card = page[page.index("Outside Sauron at eToro"):]
        card = card[:card.index("Every broker")]
        self.assertIn("minus Sauron's rows and the closes Sauron stopped "
                      "trying that eToro still lists", card)
        self.assertIn("a row Sauron counts that eToro no longer holds", card)

    def test_the_page_and_the_command_list_the_outside_part(self):
        _etoro(self.user, held=[_held("NVDA", 5, 150, pid=11),
                                _held("NVDA", 2, 175, pid=12, amount=350.0,
                                      net=12.5)])
        _row(self.cfg, "NVDA", 5, 150, pid=11)
        self.client.force_login(self.user)
        page = self.client.get(reverse("treasury_page")).content.decode()
        out = StringIO()
        call_command("treasury", user="ue_tr", stdout=out)
        body = out.getvalue()
        for text in (page, body):
            self.assertIn("eToro REAL", text)
            self.assertIn("used 6,000.00", text)
            self.assertIn("outside Sauron", text)
            self.assertIn("12.50", text)
            self.assertIn("350.00", text)
        self.assertIn("position 12", page)
        self.assertIn("position 12", body)
        self.assertIn("Outside Sauron at eToro", page)

    def test_a_non_usd_stock_row_says_unconverted_on_both(self):
        _instrument("SIE", currency="EUR")
        _etoro(self.user, held=[])
        _row(self.cfg, "SIE", 10, 100)
        _row(self.cfg, "AAPL", 3, 200)
        from bot_program.broker_vision import platform_positions
        rows = {p["symbol"]: p
                for p in platform_positions(_fresh(self.user))["live"]}
        self.assertEqual((rows["SIE"]["unconverted"],
                          rows["AAPL"]["unconverted"]), ("EUR", ""))
        self.client.force_login(self.user)
        page = self.client.get(reverse("treasury_page")).content.decode()
        self.assertIn("unconverted EUR", page)
        out = StringIO()
        call_command("treasury", user="ue_tr", stdout=out)
        self.assertIn("unconverted EUR", out.getvalue())

    def test_another_broker_keeps_the_symbol_comparison(self):
        """Only eToro is compared by position: its list holds every
        position apart and carries the id a row records. The other brokers
        keep the symbol comparison this change does not touch (IBKR nets a
        symbol into one row)."""
        from tests.test_treasury import HELD_AAPL, a_saxo, a_trade
        a_saxo(self.user, held=[HELD_AAPL])
        a_trade(self.user, "AAPL", broker="saxo")
        a_trade(self.user, "AAPL", broker="saxo", qty=5.0)
        from bot_program.broker_vision import divergence
        d = [x for x in divergence(_fresh(self.user))
             if x["kind"] == "saxo"][0]
        self.assertNotEqual(d.get("by"), "position")
        self.assertEqual(d["only_platform"], [])

    def test_another_broker_says_a_closing_row_apart_too(self):
        from bot_program.broker_vision import vision
        from tests.test_treasury import a_saxo
        a_saxo(self.user, held=[])
        _row(self.cfg, "AAPL", 10, 200, status="CLOSE_PENDING", broker="saxo")
        v = vision(_fresh(self.user))
        d = [x for x in v["divergence"] if x["kind"] == "saxo"][0]
        self.assertEqual((d["only_platform"], [p["symbol"]
                                               for p in d["closing_gone"]]),
                         ([], ["AAPL"]))
        self.assertFalse(any("does NOT report" in b for b in v["blockers"]),
                         v["blockers"])
        self.assertTrue(any("the close is being booked" in n
                            for n in v["notes"]), v["notes"])

    def test_an_open_row_is_never_hidden_behind_a_closing_one(self):
        """The symbol comparison keeps one row per symbol, and the platform
        list is ordered by symbol only: a CLOSE_PENDING row listed after an
        OPEN one on the same symbol turned the open row's "does NOT
        report" blocker into the closing note, whichever order the
        database chose."""
        from bot_program.broker_vision import divergence, platform_positions
        from tests.test_treasury import a_saxo
        a_saxo(self.user, held=[])
        opened = _row(self.cfg, "AAPL", 10, 200, broker="saxo")
        _row(self.cfg, "AAPL", 5, 200, status="CLOSE_PENDING", broker="saxo")
        plat = platform_positions(_fresh(self.user))
        for order in (plat["live"], list(reversed(plat["live"]))):
            d = [x for x in divergence(_fresh(self.user),
                                       platform={"live": order,
                                                 "paper_n": 0})
                 if x["kind"] == "saxo"][0]
            self.assertEqual([p["id"] for p in d["only_platform"]],
                             [opened.pk], order)
            self.assertEqual(d["closing_gone"], [])


class TheSweepCountsEtoroPositionsTests(TestCase):

    def setUp(self):
        self.user = _user("ue_sweep")
        self.cfg = _cfg(self.user)

    def _sweep(self, positions):
        from bot_program.engine.etoro_client import EtoroTrader
        from bot_program.reconcile_asset import reconcile_unknown_positions
        t = EtoroTrader("k", "u", env="live")
        with patch.object(t, "get_positions", return_value=positions), \
                patch.object(t, "instrument_id", return_value=1001), \
                patch("bot_program.engine.broker_router.client_for_symbol",
                      return_value=t), \
                patch("bot_program.notifications.notify_unclaimed_position",
                      return_value=True) as told:
            out = reconcile_unknown_positions(self.user)
        return out, told

    def test_a_second_position_on_a_held_symbol_is_reported(self):
        _row(self.cfg, "NVDA", 5, 150, pid=11)
        out, told = self._sweep([
            {"symbol": "NVDA", "qty": 5.0, "side": "BUY", "position_id": "11"},
            {"symbol": "NVDA", "qty": 2.0, "side": "BUY", "position_id": "12"}])
        self.assertEqual(out["unclaimed"], 1)
        self.assertEqual(out["symbols"], ["NVDA"])
        self.assertTrue(told.called)
        self.assertTrue(any("NVDA" in s and "beside" in s
                            for s in told.call_args.kwargs["symbols"]),
                        told.call_args.kwargs["symbols"])

    def test_without_ids_the_count_decides(self):
        _row(self.cfg, "NVDA", 5, 150)
        out, _ = self._sweep([
            {"symbol": "NVDA", "qty": 5.0, "side": "BUY", "position_id": ""},
            {"symbol": "NVDA", "qty": 2.0, "side": "BUY", "position_id": ""}])
        self.assertEqual(out["unclaimed"], 1)

    def test_every_position_claimed_is_a_clean_sweep(self):
        _row(self.cfg, "NVDA", 5, 150, pid=11)
        _row(self.cfg, "NVDA", 2, 175, pid=12)
        out, told = self._sweep([
            {"symbol": "NVDA", "qty": 5.0, "side": "BUY", "position_id": "11"},
            {"symbol": "NVDA", "qty": 2.0, "side": "BUY", "position_id": "12"}])
        self.assertEqual(out["unclaimed"], 0)
        self.assertFalse(told.called)

    def test_a_row_closed_inside_the_grace_still_claims_one(self):
        _row(self.cfg, "NVDA", 5, 150, pid=11)
        _row(self.cfg, "NVDA", 2, 175, pid=12, status="CLOSED",
             closed_ago_s=30)
        out, _ = self._sweep([
            {"symbol": "NVDA", "qty": 5.0, "side": "BUY", "position_id": "11"},
            {"symbol": "NVDA", "qty": 2.0, "side": "BUY", "position_id": "12"}])
        self.assertEqual(out["unclaimed"], 0)

    def test_a_row_of_another_venue_claims_nothing_at_etoro(self):
        _row(self.cfg, "NVDA", 5, 150, broker="saxo")
        out, _ = self._sweep([
            {"symbol": "NVDA", "qty": 5.0, "side": "BUY", "position_id": "11"}])
        self.assertEqual(out["unclaimed"], 1)


def _nvda(*pids, qty=5.0):
    return [{"symbol": "NVDA", "qty": qty, "side": "BUY",
             "position_id": str(p)} for p in pids]


class TheUnclaimedAlertCountsPositionsTests(TestCase):
    """The real notifier, Telegram's POST the only thing stubbed: the bell
    and the phone say how many positions nothing guards, and a standing
    one is said once a window whatever Sauron's own rows do beside it."""

    def setUp(self):
        self.user = _user("ue_alert")
        self.cfg = _cfg(self.user)

    def _sweep(self, positions, *, client=None):
        """(the sweep's result, the Telegram summaries it said)."""
        from bot_program import notifications as N
        from bot_program.engine.etoro_client import EtoroTrader
        from bot_program.reconcile_asset import reconcile_unknown_positions
        t = client or EtoroTrader("k", "u", env="live")
        said, real = [], N.dispatch_notification

        def spy(*args, **kwargs):
            said.append((kwargs.get("telegram") or {}).get("summary", ""))
            return real(*args, **kwargs)

        with patch.object(t, "get_positions", return_value=positions), \
                patch.object(t, "instrument_id", return_value=1001), \
                patch("bot_program.engine.broker_router.client_for_symbol",
                      return_value=t), \
                patch("bot_program.notifications.dispatch_notification",
                      side_effect=spy), \
                patch("requests.post"):
            out = reconcile_unknown_positions(_fresh(self.user))
        return out, said

    def _bells(self):
        from alerts.models import Notification
        return list(Notification.objects.filter(
            user=self.user, title__contains="no row claims").order_by("pk"))

    def test_two_outside_positions_on_one_symbol_ring_as_two(self):
        out, said = self._sweep(_nvda(11, 12))
        self.assertEqual(out["unclaimed"], 2)
        [bell] = self._bells()
        self.assertEqual(bell.title,
                         "▲ 2 positions at EtoroTrader that no row claims")
        self.assertTrue(bell.body.startswith("NVDA ×2. "), bell.body)
        self.assertEqual(said, ["EtoroTrader holds positions Sauron has no "
                                "record of, so nothing on the platform "
                                "guards them."])

    def test_two_beside_a_held_symbol_ring_as_two(self):
        _row(self.cfg, "NVDA", 5, 150, pid=101)
        out, _said = self._sweep(_nvda(101, 201, 202))
        self.assertEqual(out["unclaimed"], 2)
        [bell] = self._bells()
        self.assertEqual(bell.title,
                         "▲ 2 positions at EtoroTrader that no row claims")
        self.assertTrue(bell.body.startswith("NVDA (+2 beside Sauron's 1). "),
                        bell.body)

    def test_the_account_entry_path_counts_positions_too(self):
        """No config routes to eToro: the account itself is swept."""
        from bot_program.models import AssetBotConfig
        from bot_program.reconcile_asset import reconcile_unknown_positions
        AssetBotConfig.objects.filter(user=self.user).delete()
        _etoro(self.user)

        class Book:
            def get_positions(self):
                return _nvda(11, 12)

        with patch("bot_program.engine.etoro_client.EtoroTrader",
                   return_value=Book()), patch("requests.post"):
            out = reconcile_unknown_positions(_fresh(self.user))
        self.assertEqual(out["unclaimed"], 2)
        self.assertEqual([b.title for b in self._bells()],
                         ["▲ 2 positions at eToro Main that no row claims"])

    def test_sauron_s_own_rows_beside_it_do_not_ring_it_again(self):
        """One hand-placed position (id 12) stands beside Sauron's NVDA. A
        second Sauron row on the symbol, then Sauron's rows closing, are
        not a new unclaimed position: the standing one is said once a
        window (the alert's key held Sauron's count and rang each time)."""
        mine = _row(self.cfg, "NVDA", 5, 150, pid=11)
        self._sweep(_nvda(11, 12))
        self.assertEqual(len(self._bells()), 1)
        second = _row(self.cfg, "NVDA", 5, 150, pid=13)
        self._sweep(_nvda(11, 12, 13))
        self.assertEqual(len(self._bells()), 1)
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(pk__in=(mine.pk, second.pk)).update(
            status="CLOSED", closed_at=timezone.now() - timedelta(hours=1))
        self._sweep(_nvda(12))
        self.assertEqual(len(self._bells()), 1)
        # a second outside position is a changed condition, said at once
        self._sweep(_nvda(12, 14))
        self.assertEqual([b.title for b in self._bells()][-1],
                         "▲ 2 positions at EtoroTrader that no row claims")
        self.assertEqual(len(self._bells()), 2)


# ── 4. counted once ──────────────────────────────────────────────────────

class TheAccountIsCountedOnceTests(TestCase):

    def setUp(self):
        self.user = _user("ue_once")

    def _switch(self, on):
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key="shared_capital_live",
            defaults={"name": "Shared Capital (one pool)",
                      "category": "system", "is_enabled": on})

    def _followers(self):
        for i, cls in enumerate(("stock", "crypto", "forex")):
            _cfg(self.user, cls=cls, name=f"f{i}", capital="10000",
                 extras={"capital_tracks_broker": True})
        _cfg(self.user, cls="crypto", name="paper", mode="paper",
             capital="4000")

    def test_shared_capital_counts_the_account_once(self):
        from portfolio.services import capital_summary
        self._switch(True)
        self._followers()
        _row(self._live_cfg(), "AAPL", 10, 200)
        cap = capital_summary(self.user)
        self.assertTrue(cap["shared"])
        self.assertEqual(cap["pool_live"], 10000.0)
        self.assertEqual(cap["pool_total"], 14000.0)
        self.assertEqual(cap["free_live"], 8000.0)
        self.assertEqual(cap["free_total"], 12000.0)
        live = [c for c in cap["classes"] if c["mode"] == "live"]
        self.assertTrue(all(c["shared"] for c in live), live)

    def test_the_slices_still_sum(self):
        from portfolio.services import capital_summary
        self._switch(False)
        self._followers()
        cap = capital_summary(self.user)
        self.assertFalse(cap["shared"])
        self.assertEqual(cap["pool_live"], 30000.0)

    def _live_cfg(self):
        from bot_program.models import AssetBotConfig
        return AssetBotConfig.objects.get(user=self.user, name="f0")

    @override_settings(CACHES=LOCMEM)
    def test_the_horde_counts_it_once_reading_its_switch_its_own_way(self):
        """The band reads its switches in one batch and never through
        is_component_enabled (dashboard/horde.py rule 5): it hands the
        summary the switch it read."""
        cache.clear()
        self._switch(True)
        self._followers()
        self.client.force_login(self.user)
        boom = MagicMock(side_effect=AssertionError("forbidden reader"))
        with patch("core.platform_control.is_component_enabled", boom):
            board = self.client.get("/api/horde/").json()
        boom.assert_not_called()
        self.assertIn("of 10,000.00 used", board["head"]["pools"]["live_t"])


class NoGateReadsTheCapitalSummaryTests(SimpleTestCase):
    """The proof the brief asks for before counting the account once: the
    summary's every reader is a page. A gate that reads it would make the
    change above a change to a limit."""

    READERS = {"dashboard/horde.py", "dashboard/views.py",
               "core/context_processors.py", "portfolio/services.py"}

    SKIP = {"tests", "staticfiles", "static", "templates", "venv", ".venv",
            "node_modules", "frontend", "test_backups"}

    def test_only_pages_read_it(self):
        found = set()
        pat = re.compile(r"capital_summary\s*\(|import[^\n]*capital_summary")
        # The project's own packages only: never a virtualenv, a build or
        # another worktree that may sit inside the checkout.
        roots = [p for p in BASE.iterdir()
                 if p.is_dir() and not p.name.startswith(".")
                 and p.name not in self.SKIP]
        paths = [p for root in roots for p in root.rglob("*.py")]
        paths += [p for p in BASE.glob("*.py")]
        for path in paths:
            rel = path.relative_to(BASE).as_posix()
            if "/migrations/" in rel:
                continue
            try:
                src = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if pat.search(src):
                found.add(rel)
        self.assertEqual(found, self.READERS)


# ── 5. the surfaces ──────────────────────────────────────────────────────

def _seeded(name):
    """The split's account and rows, for the surfaces."""
    user = _user(name)
    _etoro(user, held=[_held("NVDA", 5, 150, pid=11),
                       _held("NVDA", 2, 175, pid=12, amount=350.0, net=12.5)],
           held_age_s=120)
    cfg = _cfg(user)
    _row(cfg, "NVDA", 5, 150, pid=11)
    return user


@override_settings(CACHES=LOCMEM)
class TheHordeHeadTests(TestCase):

    def setUp(self):
        cache.clear()
        self.user = _seeded("ue_horde")
        self.client.force_login(self.user)

    def test_the_head_carries_etoros_own_figures_and_the_split(self):
        board = self.client.get("/api/horde/").json()
        hd = board["head"]["etoro"]
        self.assertIn("eToro REAL", hd["t"])
        self.assertIn("used 6,000.00", hd["t"])
        self.assertIn("opened by Sauron 750.00", hd["split_t"])
        self.assertIn("outside Sauron 5,250.00", hd["split_t"])
        json.dumps(board)                       # the payload stays JSON

    @unittest.skipUnless(__import__("shutil").which("node"), "node is not installed")
    def test_the_script_paints_them_before_the_pools(self):
        from tests.test_the_horde import OPEN, _drive
        board = self.client.get("/api/horde/").json()
        tab = self.client.get("/api/horde/", {"part": "tab"}).json()
        got = _drive(OPEN + """
            const table = env.$('svHordeTable');
            const cells = table.querySelectorAll('.hd-cell');
            return cells.map((c) => c.textContent);
        """, {"board": board, "tab": tab, "seat": {}})
        at = [i for i, t in enumerate(got) if "eToro REAL" in t]
        pools = [i for i, t in enumerate(got) if t.startswith("POOLS")]
        self.assertTrue(at and pools, got)
        self.assertLess(at[0], pools[0])
        self.assertTrue(got[at[0]].startswith("AT ETORO"), got[at[0]])
        self.assertIn("outside Sauron", got[at[0]])

    def test_every_word_key_of_the_band_is_said_once(self):
        """The script reads its words by key, the last span winning: a key
        written twice silently replaces the first sentence everywhere it is
        used (the cell's title first read "At eToro: instrument {id}")."""
        from collections import Counter
        src = (BASE / "templates" / "_partials" / "the_horde.html").read_text(
            encoding="utf-8")
        keys = Counter(re.findall(r'data-w="([^"]+)"', src))
        self.assertEqual([k for k, n in keys.items() if n > 1], [])


class TheHeaderDropdownTests(TestCase):

    def test_the_live_line_headlines_etoros_figures(self):
        from core.context_processors import sauron_context
        user = _seeded("ue_head")
        cache.clear()
        request = RequestFactory().get("/")
        request.user = user
        ctx = sauron_context(request)
        e = ctx["panel_etoro"]
        self.assertEqual((e["used_t"], e["available_t"], e["pnl_t"],
                          e["total_t"]),
                         ("6,000.00", "3,500.00", "+500.00", "10,000.00"))
        self.assertIn("outside Sauron 5,250.00", e["split_t"])

    def test_the_template_renders_them_with_their_dashes(self):
        base = (BASE / "templates" / "base.html").read_text(encoding="utf-8")
        for needle in ("panel_etoro.used_t", "panel_etoro.available_t",
                       "panel_etoro.pnl_t", "panel_etoro.total_t"):
            self.assertIn(needle, base)
            cell = base[base.index(needle):base.index(needle) + 500]
            self.assertIn("sv-unknown", cell, needle)
        self.assertIn("panel_etoro.split_t", base)
        # the eToro cells come before the pool's LIVE ENGAGED
        self.assertLess(base.index("panel_etoro.used_t"),
                        base.index("panel_used_live"))


class ThePagesTests(TestCase):

    def setUp(self):
        cache.clear()
        self.user = _seeded("ue_pages")
        self.client.force_login(self.user)

    def test_the_capital_card_and_the_positions_head(self):
        page = self.client.get(reverse("positions_list")).content.decode()
        card = page[page.index('data-sv-live="cap-card"'):]
        card = card[:card.index("Used is capital-at-work")]
        self.assertIn("ETORO USED", card)
        self.assertIn("6,000.00", card)
        self.assertIn("outside Sauron 5,250.00", card)
        strip = page[page.index('data-sv-live="pos-strip"'):
                     page.index('data-sv-live="cap-card"')]
        self.assertIn("ETORO USED", strip)
        self.assertIn("3,500.00 available", strip)
        self.assertIn("outside Sauron 5,250.00", strip)

    def test_the_portfolio_strip(self):
        page = self.client.get(reverse("portfolio_overview")).content.decode()
        strip = page[page.index('data-sv-live="pf-strip"'):]
        strip = strip[:strip.index('data-sv-live="cap-card"')]
        self.assertIn("ETORO USED", strip)
        self.assertIn("6,000.00", strip)
        self.assertIn("outside Sauron 5,250.00", strip)

    def test_the_ops_center_live_strip(self):
        from dashboard.views_command import command_tab_live
        request = RequestFactory().get("/")
        request.user = self.user
        with patch("dashboard.views_eye._build_eye_context", return_value={}):
            html = command_tab_live(request).content.decode()
        self.assertIn("ETORO USED", html)
        self.assertIn("6,000", html)
        self.assertIn("read 4 min ago", html)

    def test_the_positions_broker_panel_claims_by_position(self):
        page = self.client.get(reverse("positions_list")).content.decode()
        panel = page[page.index("At the broker"):]
        panel = panel[:panel.index("</table>")]
        self.assertEqual(panel.count("bkp-claim--unclaimed"), 1, panel)

    def test_the_ops_center_cell_wraps_instead_of_cutting(self):
        """One line with an ellipsis showed "3,500.00 available · …": the
        total and the age were cut at every width."""
        from dashboard.views_command import command_tab_live
        request = RequestFactory().get("/")
        request.user = self.user
        with patch("dashboard.views_eye._build_eye_context", return_value={}):
            html = command_tab_live(request).content.decode()
        cell = html[html.index("ETORO USED"):]
        cell = cell[:cell.index("</div>")]
        self.assertIn('class="oc-strip-sub oc-strip-sub--wrap"', cell)
        self.assertIn("10,000.00 total", cell)


class TheTotalCarriesItsOwnAgeEverywhereTests(TestCase):
    """The cells were read 20 s ago (the re-read after a close), the total
    three hours ago (the sync stalled): every surface that prints the
    cells' age beside the total says the total's own (the head line
    already did)."""

    def setUp(self):
        cache.clear()
        self.user = _user("ue_age")
        acct = _etoro(self.user, age_s=20,
                      held=[_held("NVDA", 5, 150, pid=11)])
        EtoroAccount.objects.filter(pk=acct.pk).update(
            last_equity_at=timezone.now() - timedelta(hours=3))
        _row(_cfg(self.user), "NVDA", 5, 150, pid=11)
        self.client.force_login(self.user)

    def test_the_positions_strip(self):
        page = self.client.get(reverse("positions_list")).content.decode()
        strip = page[page.index('data-sv-live="pos-strip"'):
                     page.index('data-sv-live="cap-card"')]
        self.assertIn("3,500.00 available · 10,000.00 total (read 3 h ago) · "
                      "read ", strip)

    def test_the_portfolio_strip(self):
        page = self.client.get(reverse("portfolio_overview")).content.decode()
        strip = page[page.index('data-sv-live="pf-strip"'):]
        strip = strip[:strip.index('data-sv-live="cap-card"')]
        self.assertIn("10,000.00 total (read 3 h ago) · read ", strip)

    def test_the_ops_center(self):
        from dashboard.views_command import command_tab_live
        request = RequestFactory().get("/")
        request.user = self.user
        with patch("dashboard.views_eye._build_eye_context", return_value={}):
            html = command_tab_live(request).content.decode()
        self.assertIn("10,000.00 total (read 3 h ago) · read ", html)

    def test_the_header_dropdown(self):
        page = self.client.get(reverse("positions_list")).content.decode()
        at = page.index('ETORO TOTAL</span><span class="dv">')
        note = page[at:]
        note = note[note.index('class="ip-dd-note"'):]
        note = note[:note.index("</div>")]
        self.assertIn("; the total read 3 h ago.", note)

    def test_a_fresh_total_carries_no_age_of_its_own(self):
        EtoroAccount.objects.filter(user=self.user).update(
            last_equity_at=timezone.now() - timedelta(seconds=20))
        page = self.client.get(reverse("positions_list")).content.decode()
        self.assertIn("10,000.00 total · read ", page)
        self.assertNotIn("the total read", page)


class TheAtTheBrokerPanelTests(TestCase):
    """The positions page's panel claims eToro's positions as the outside
    list does: the rows of the account's world that are open, a close
    Sauron stopped trying (said STOPPED), a row closed inside the list's
    lag; a row that records no broker is said apart, never CLAIMED as
    eToro's or UNCLAIMED."""

    def setUp(self):
        cache.clear()
        self.user = _user("ue_panel")
        self.cfg = _cfg(self.user)
        self.client.force_login(self.user)

    def _chips(self, held):
        _etoro(self.user, held=held, held_age_s=120)
        page = self.client.get(reverse("positions_list")).content.decode()
        panel = page[page.index("At the broker"):]
        panel = panel[:panel.index("</table>")]
        return re.findall(r'<td data-label="Symbol">([^<]*)</td>.*?'
                          r'<td data-label="Claim">(.*?)</td>', panel, re.S)

    def test_a_stopped_close_reads_stopped(self):
        _row(self.cfg, "MSFT", 2, 300, status="ERROR", pid=41)
        [(sym, chip)] = self._chips([_held("MSFT", 2, 300, pid=41)])
        self.assertEqual(sym, "MSFT")
        self.assertIn(">STOPPED<", chip)
        self.assertNotIn("UNCLAIMED", chip)

    def test_a_leg_closed_inside_the_list_lag_is_claimed(self):
        _row(self.cfg, "NVDA", 5, 150, pid=11, status="CLOSED",
             closed_ago_s=150)
        [(_sym, chip)] = self._chips([_held("NVDA", 5, 150, pid=11)])
        self.assertIn(">CLAIMED<", chip)

    def test_a_second_leg_is_unclaimed_in_etoros_words(self):
        """"No Sauron row matches this symbol — opened by hand in TWS" was
        false twice over: a row does match the symbol, and TWS is IBKR's."""
        _row(self.cfg, "NVDA", 5, 150, pid=11)
        chips = self._chips([_held("NVDA", 5, 150, pid=11),
                             _held("NVDA", 2, 175, pid=12)])
        self.assertEqual([s for s, _c in chips], ["NVDA", "NVDA"])
        self.assertIn(">CLAIMED<", chips[0][1])
        self.assertIn(">UNCLAIMED<", chips[1][1])
        for words in ("No Sauron row accounts for this position",
                      "a second position beside Sauron's"):
            self.assertIn(words, chips[1][1])
        self.assertNotIn("TWS", chips[1][1])

    def test_a_row_of_another_world_claims_nothing(self):
        _row(self.cfg, "NVDA", 5, 150, pid=11, env="paper")   # eToro demo
        [(_sym, chip)] = self._chips([_held("NVDA", 5, 150, pid=11)])
        self.assertIn(">UNCLAIMED<", chip)

    def test_a_row_that_records_no_broker_is_said_apart(self):
        _row(self.cfg, "IBM", 10, 100, broker="")
        [(_sym, chip)] = self._chips([_held("IBM", 10, 100, pid=51)])
        self.assertIn(">NO BROKER<", chip)
        self.assertNotIn("CLAIMED<", chip)


class TheTicketsCapitalLineTests(_LiveEtoroTicket):
    """The ticket's eToro line (C2's "eToro cash", the gate's own free)
    carries eToro's P&L, its total and the split; the pool's `available`
    and `deficit` are untouched."""

    username = "ue_ticket"

    def test_the_cash_line_carries_the_pnl_the_total_and_the_split(self):
        from tests.test_ticket_checks_like_the_send import REFRESH
        acct = self._cells(age_s=30)
        EtoroAccount.objects.filter(pk=acct.pk).update(
            last_pnl=Decimal("-42.00"))
        client, _ = self._etoro()
        with patch(REFRESH):
            out = self._preview(client)
        cg = out["cash_gate"]
        self.assertEqual(cg["pnl"], -42.0)
        self.assertEqual(cg["total"], 10000.0)
        self.assertIn("opened by Sauron", cg["split_t"])
        self.assertIn("outside Sauron", cg["split_t"])
        # the gate's own free, beside the pool's arithmetic, both as before
        self.assertEqual(cg["free"], 1000.0)
        self.assertEqual(out["available"], float(self.cfg.capital))
        self.assertEqual(out["deficit"], 0.0)


class TheTicketDialogTests(SimpleTestCase):

    def test_the_dialog_headlines_etoro_before_the_pool(self):
        src = (BASE / "templates" / "base.html").read_text(encoding="utf-8")
        fn = src[src.index("function sizeDialog(p)"):]
        fn = fn[:fn.index("var okBtn = host.querySelector")]
        self.assertLess(fn.index("facts.push(['eToro cash'"),
                        fn.index("facts.push(['Capital free'"))
        cash_line = fn[fn.index("facts.push(['eToro cash'"):]
        cash_line = cash_line[:cash_line.index("]);")]
        self.assertIn("cg.pnl", cash_line)
        self.assertIn("P&L", cash_line)
        self.assertIn("cg.split_t", fn)


class NothingOnAnOrderPathReadsItTests(SimpleTestCase):

    def test_the_gates_do_not_import_it(self):
        for rel in ("bot_program/asset_engine/base.py",
                    "portfolio/risk_gate.py", "bot_program/asset_engine/sizing.py"):
            src = (BASE / rel).read_text(encoding="utf-8")
            self.assertNotIn("etoro_used", src, rel)
            self.assertNotIn("last_pnl", src, rel)
