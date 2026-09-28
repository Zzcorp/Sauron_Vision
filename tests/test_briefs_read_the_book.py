# -*- coding: utf-8 -*-
"""THE DIGESTS READ THE WHOLE BOOK, THE REAL ACCOUNT FIRST (2026-09-27).

The operator, 2026-09-27: "in morning brief no position open, when 5
are..." and then "shouldn't it reference all portfolio and especially the
live one?". Pinned here (alerts/digest_book.py, alerts/scheduled_digests.py,
bot_program/telegram_eye.read_live_account):
  * B1 five paper AssetBotTrades on an empty legacy book: the brief reads
    "Open positions: 5 (5 simulated · 0 real money)" with the movers, the
    biggest first, in the positions page's own numbers; a real-money row
    counts as real and sits under Real money; a live-mode row on the eToro
    demo is simulated; closed, error and canceled rows and another user's
    rows are not counted; a legacy Position row counts once, its P&L with
    no currency (as the page prints it); the seeded book reads "Book
    value: not set", an entered one its value; the digest names whose
    book it is ("User: Sauron");
  * B2 the end-of-day summary lists today's opens and closes from
    AssetBotTrade with the P&L and R the rows booked; yesterday's rows,
    error and canceled rows and another user's rows are not listed; a
    legacy row of today counts once; while the book is the seed, the
    Daily P&L says "Not measured while the book value is not set." and
    prints none of the snapshot's figures;
  * B3 a user with nothing open reads "No open positions." first, after
    the "User:" line;
  * B5 both digests open with Real money, then Simulated: the real
    account from a patched live read (equity, cash, used margin, held,
    the time); on a raising read or with no key, the cells stamped in the
    live world with "as of <time>" and the reason; a stored key that does
    not decrypt is said so, never "no key"; cells stamped in the demo
    world never printed as real money, and an equity newer than its world
    stamp printed in neither section; positions held at eToro that the
    platform does not list are counted; the read is the Eye's own (three
    client reads, the status report still two), and the real client path
    sends GETs only, to aggregate-portfolio and portfolio; the module
    carries no write;
  * a digest_book that fails to import costs the book's lines, not the
    digest;
  * the rendered lines (digest_lines, the Telegram text) are plain English.

Run with:  python manage.py test tests.test_briefs_read_the_book
"""
import os
import re
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

READ = "bot_program.telegram_eye.read_live_account"
TRADER = "bot_program.engine.etoro_client.EtoroTrader"
LIVE = {"equity": (2249.65, "USD"), "positions": 0,
        "cells": {"available_cash": 2249.65, "used_margin": 0.0,
                  "currency": "USD"}}
DEMO_LINE = ("Sauron trades on the demo account; the real account is read, "
             "not traded.")
UNKNOWN = "the stored reading does not say which account it came from"
SAURON = "User: Sauron"
SNAKE = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")
ACCENTED = re.compile(r"[À-ÖØ-öø-ÿŒœ]")
FRENCH = (" le ", " la ", " les ", " des ", " du ", " une ", " est ",
          " pour ", " avec ", " sur ", " vous ", " et ")
#: The five positions the Sauron user held on 2026-09-27 (#61, #68, #102,
#: #111, #110), with marks: (symbol, class, side, qty, entry, mark,
#: value_per_unit). The P&L is _trade_to_position's: (mark - entry) x qty
#: x value_per_unit x sign; the percentage (mark - entry) / entry x 100 x
#: sign, both rounded to 2 places.
FIVE = (
    ("AAPL", "stock", "SELL", "0.5", "255.00", "251.30", None),
    ("GBPUSD", "forex", "BUY", "1000", "1.34000", "1.34520", None),
    ("NFLX", "stock", "BUY", "0.2", "1180.00", "1204.60", None),
    ("USDNOK", "forex", "SELL", "1000", "10.0000", "10.0510", 0.0995),
    ("USDZAR", "forex", "BUY", "1000", "17.5000", "17.4210", 0.0574),
)
FIVE_LINES = [
    "• NFLX long · +2.08% · +4.92 USD · Simulated",
    "• AAPL short · +1.45% · +1.85 USD · Simulated",
    "• USDNOK short · -0.51% · -5.07 USD · Simulated",
    "• USDZAR long · -0.45% · -4.53 USD · Simulated",
    "• GBPUSD long · +0.39% · +5.20 USD · Simulated",
]
_UNSET = object()


def _user(name):
    return User.objects.create_user(name, password="x",
                                    email=f"{name.lower()}@x.io")


def _cfg(user, asset_class="stock", *, mode="paper", name=None):
    from bot_program.asset_models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, mode=mode,
        name=name or f"{asset_class} {mode}", symbols=[],
        base_currency="USD")


def _quote(symbol, last, asset_class="stock"):
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "is_active": True})
    LiveQuote.objects.filter(instrument=inst).delete()
    LiveQuote.objects.create(instrument=inst, last=Decimal(last),
                             source="test")
    return inst


def _trade(cfg, symbol, *, side="BUY", qty="1", entry="100", stop=None,
           paper=True, status="OPEN", metadata=None, opened_at=None,
           closed_at=None, pnl=_UNSET, realized_r=None, outcome="",
           exit_price=None):
    from bot_program.asset_models import AssetBotTrade
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(qty), entry_price=Decimal(entry),
        stop_loss=None if stop is None else Decimal(stop),
        exit_price=None if exit_price is None else Decimal(exit_price),
        paper=paper, status=status, metadata=dict(metadata or {}),
        pnl=Decimal("0") if pnl is _UNSET else (
            None if pnl is None else Decimal(pnl)),
        realized_r=realized_r, outcome=outcome)
    stamps = {}
    if opened_at is not None:
        stamps["opened_at"] = opened_at
    if closed_at is not None:
        stamps["closed_at"] = closed_at
    if stamps:
        AssetBotTrade.objects.filter(pk=t.pk).update(**stamps)
        t.refresh_from_db()
    return t


def _etoro(user, *, keys=True, **fields):
    from bot_program.models import EtoroAccount
    acct = EtoroAccount.objects.create(user=user, **fields)
    if keys:
        acct.set_credentials("the-api-key", "the-user-key")
        acct.save()
    return acct


def _legacy(user, symbol, *, direction="long", qty="1", entry="1.1000",
            opened_at=None, closed_at=None, pnl="0"):
    from portfolio.models import Position
    from portfolio.services import get_or_create_default_portfolio
    book = get_or_create_default_portfolio(user=user)
    inst = _quote(symbol, entry, "forex")
    return Position.objects.create(
        portfolio=book, instrument=inst, direction=direction,
        quantity=Decimal(qty), entry_price=Decimal(entry),
        current_price=Decimal(entry), unrealized_pnl=Decimal(pnl),
        opened_at=opened_at or timezone.now(), closed_at=closed_at)


def _today(k):
    """A moment of today (UTC), k tenths of the way from 00:00 to now."""
    now = timezone.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start + (now - start) * k / 10


def _yesterday():
    now = timezone.now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0) \
        - timedelta(hours=1)


def _morning(user, read=LIVE, **patches):
    from alerts.scheduled_digests import generate_morning_digest
    kw = {"side_effect": read} if isinstance(read, Exception) else \
        {"return_value": read}
    with patch(READ, **kw) as reader:
        digest = generate_morning_digest(user=user)
    digest["_reader"] = reader
    return digest


def _eod(user, read=LIVE):
    from alerts.scheduled_digests import generate_eod_digest
    kw = {"side_effect": read} if isinstance(read, Exception) else \
        {"return_value": read}
    with patch(READ, **kw):
        return generate_eod_digest(user=user)


def _lines(digest, section):
    return [str(ln) for ln in digest["sections"][section]["lines"]]


class _BookCase(TestCase):
    """The Sauron user of 2026-09-27: five paper positions, an empty legacy
    book, the eToro row in demo with its demo cells stamped."""

    def setUp(self):
        self.user = _user("Sauron")
        self.stock = _cfg(self.user, "stock")
        self.forex = _cfg(self.user, "forex")
        self.five = []
        for sym, ac, side, qty, entry, mark, vpu in FIVE:
            _quote(sym, mark, ac)
            meta = {} if vpu is None else {"value_per_unit": vpu}
            self.five.append(_trade(
                self.stock if ac == "stock" else self.forex, sym, side=side,
                qty=qty, entry=entry, metadata=meta))
        self.synced = timezone.now() - timedelta(minutes=12)
        self.acct = _etoro(
            self.user, demo=True, is_primary_for_stocks=True,
            last_equity=Decimal("99812.40"), last_equity_currency="USD",
            last_equity_at=self.synced, last_available_cash=Decimal("97500"),
            last_used_margin=Decimal("2312.40"), last_margin_at=self.synced,
            last_margin_world="demo", last_sync=self.synced)

    def live_stamps(self, at):
        """The row turned live, its cells stamped in the live world."""
        self.acct.demo = False
        self.acct.last_margin_world = "live"
        self.acct.last_margin_at = at
        self.acct.last_equity_at = at
        self.acct.last_equity = Decimal("2249.65")
        self.acct.last_available_cash = Decimal("2200.00")
        self.acct.last_used_margin = Decimal("49.65")
        self.acct.broker_positions = []
        self.acct.broker_positions_at = at
        self.acct.save()


# ── B1: the brief counts the book the positions page reads ───────────────

class TheBriefReadsTheBookTests(_BookCase):
    def test_five_paper_positions_on_an_empty_legacy_book_read_five(self):
        from portfolio.models import Position
        digest = _morning(self.user)
        self.assertEqual(Position.objects.count(), 0)
        self.assertEqual(digest["summary"], [
            SAURON, "Open positions: 5 (5 simulated · 0 real money)"])
        self.assertEqual(digest["book"],
                         {"open": 5, "simulated": 5, "real_money": 0})
        self.assertNotIn("portfolio", digest["sections"])
        sim = _lines(digest, "simulated")
        self.assertEqual(sim[0], "5 positions open, the biggest moves first")
        self.assertEqual(sim[1:6], FIVE_LINES)
        self.assertEqual(sim[6:], [
            "Open P&L: +2.37 USD",
            "eToro demo account equity: 99,812.40 USD (synced 12 min ago)",
            "Book value: not set"])

    def test_the_movers_are_the_positions_pages_own_numbers(self):
        from dashboard.views import _live_open_book
        from portfolio.services import get_or_create_default_portfolio
        digest = _morning(self.user)
        items = {it["trade_id"]: it
                 for it in digest["sections"]["simulated"]["positions"]}
        _objs, rows, _n, _u, _d = _live_open_book(
            self.user, get_or_create_default_portfolio(user=self.user))
        self.assertEqual(len(rows), 5)
        for row in rows:
            item = items[row["trade_id"]]
            self.assertEqual(item["pnl"], row["unrealized_pnl"])
            self.assertEqual(item["pnl_pct"], row["unrealized_pnl_pct"])
            self.assertIn(f"· {row['pct_text']} · {row['pnl_text']} USD ·",
                          item["line"])

    def test_one_real_money_row_counts_as_real_and_sits_under_real_money(self):
        live = _cfg(self.user, "stock", mode="live")
        _quote("TSLA", "250")
        _trade(live, "TSLA", qty="1", entry="240", paper=False,
               metadata={"broker": "etoro", "broker_env": "live"})
        digest = _morning(self.user)
        self.assertEqual(digest["summary"], [
            SAURON, "Open positions: 6 (5 simulated · 1 real money)"])
        real = _lines(digest, "real_money")
        self.assertIn("Real-money positions on the platform: 1", real)
        self.assertIn("• TSLA long · +4.17% · +10.00 USD · Real money (eToro)",
                      real)
        sim = _lines(digest, "simulated")
        self.assertFalse([ln for ln in sim if "TSLA" in ln], sim)
        # a simulated row never appears under Real money
        self.assertFalse([ln for ln in real if "Simulated" in ln], real)
        self.assertEqual(sim[1:6], FIVE_LINES)

    def test_a_live_mode_row_on_the_etoro_demo_is_simulated(self):
        live = _cfg(self.user, "stock", mode="live")
        _quote("MSFT", "420")
        _trade(live, "MSFT", qty="1", entry="400", paper=False,
               metadata={"broker": "etoro", "broker_env": "paper"})
        digest = _morning(self.user)
        self.assertEqual(digest["summary"], [
            SAURON, "Open positions: 6 (6 simulated · 0 real money)"])
        self.assertIn("• MSFT long · +5.00% · +20.00 USD · Simulated "
                      "(eToro demo)", _lines(digest, "simulated"))
        self.assertIn("No real-money position on the platform.",
                      _lines(digest, "real_money"))

    def test_closed_error_canceled_and_another_users_rows_are_not_counted(self):
        for status in ("CLOSED", "ERROR", "CANCELED"):
            _trade(self.stock, "NFLX", status=status)
        other = _user("ISA_CAPITAL")
        _trade(_cfg(other, "stock"), "NFLX")
        _trade(_cfg(other, "stock", mode="live"), "NFLX", paper=False,
               metadata={"broker": "etoro", "broker_env": "live"})
        digest = _morning(self.user)
        self.assertEqual(digest["summary"], [
            SAURON, "Open positions: 5 (5 simulated · 0 real money)"])
        self.assertEqual(_lines(digest, "simulated")[1:6], FIVE_LINES)

    def test_a_legacy_position_counts_once(self):
        _legacy(self.user, "EURUSD", entry="1.1000")
        _quote("EURUSD", "1.1100", "forex")
        digest = _morning(self.user)
        self.assertEqual(digest["summary"], [
            SAURON, "Open positions: 6 (6 simulated · 0 real money)"])
        every = _lines(digest, "real_money") + _lines(digest, "simulated")
        self.assertEqual([ln for ln in every if "EURUSD" in ln], [
            "• EURUSD long · +0.91% · +0.01 · Simulated"])

    def test_a_legacy_rows_pnl_carries_no_currency_as_on_the_page(self):
        """(mark - entry) x qty is in the instrument's price currency
        (USD for EURUSD), unconverted; the book's currency (EUR by
        default) would be a false label. The page prints it bare."""
        from dashboard.views import _live_open_book
        from portfolio.services import get_or_create_default_portfolio
        book = get_or_create_default_portfolio(user=self.user)
        book.currency = "EUR"
        book.save()
        _legacy(self.user, "EURUSD", entry="1.1000")
        _quote("EURUSD", "1.1100", "forex")
        digest = _morning(self.user)
        item = [it for it in digest["sections"]["simulated"]["positions"]
                if it["symbol"] == "EURUSD"][0]
        self.assertEqual(item["currency"], "")
        self.assertNotIn("EUR ", item["line"])
        _o, rows, _n, _u, _d = _live_open_book(self.user, book)
        row = [r for r in rows if r["symbol"] == "EURUSD"][0]
        self.assertIn(f"· {row['pct_text']} · {row['pnl_text']} · Simulated",
                      item["line"])
        # mixed currencies: no Open P&L sum is printed
        self.assertFalse([ln for ln in _lines(digest, "simulated")
                          if ln.startswith("Open P&L")])

    def test_the_digest_names_whose_book_it_is(self):
        """A chat several users share gets the first user's digest: the
        reader must see whose book the counts are."""
        other = _user("ISA_CAPITAL")
        _quote("NFLX", "1204.60")
        _trade(_cfg(other, "stock"), "NFLX", qty="0.2", entry="1180.00")
        mine, theirs = _morning(self.user), _morning(other)
        self.assertEqual(mine["summary"][0], SAURON)
        self.assertEqual(theirs["summary"], [
            "User: ISA_CAPITAL",
            "Open positions: 1 (1 simulated · 0 real money)"])

    def test_a_book_whose_capital_was_entered_prints_its_value(self):
        from bot_program.telegram_eye import money
        from portfolio.services import (get_or_create_default_portfolio,
                                        live_book_value)
        book = get_or_create_default_portfolio(user=self.user)
        book.initial_capital = book.cash_available = Decimal("2500.00")
        book.save()
        digest = _morning(self.user)
        bv = live_book_value(self.user, book)
        sim = _lines(digest, "simulated")
        self.assertIn(f"Book value: {money(bv.value, bv.currency)} · "
                      f"cash {money(2500, bv.currency)}", sim)
        self.assertNotIn("Book value: not set", sim)


# ── B3: nothing open ─────────────────────────────────────────────────────

class NothingOpenTests(TestCase):
    def test_a_user_with_nothing_open_reads_no_open_positions_first(self):
        from alerts.scheduled_digests import digest_lines
        user = _user("Nobody")
        for digest in (_morning(user), _eod(user)):
            self.assertEqual(digest["summary"],
                             ["User: Nobody", "No open positions."])
            self.assertEqual(digest_lines(digest)[:2],
                             ["User: Nobody", "No open positions."])
            self.assertEqual(_lines(digest, "real_money"), [
                "eToro real account: not connected",
                "No real-money position on the platform."])
            self.assertEqual(_lines(digest, "simulated"), [
                "No simulated position.", "Book value: not set"])
        self.assertEqual(_lines(_eod(user), "trades"),
                         ["No trade opened or closed today."])


# ── B5: the real account first ───────────────────────────────────────────

class RealMoneyFirstTests(_BookCase):
    def test_both_digests_open_with_real_money_then_simulated(self):
        from alerts.scheduled_digests import digest_lines
        for digest in (_morning(self.user), _eod(self.user)):
            self.assertEqual(list(digest["sections"])[:2],
                             ["real_money", "simulated"])
            lines = [str(ln) for ln in digest_lines(digest)]
            self.assertEqual(lines[:3], [
                SAURON, "Open positions: 5 (5 simulated · 0 real money)",
                "Real money"])
            self.assertLess(lines.index("Real money"),
                            lines.index("Simulated"))

    def test_the_real_account_from_the_live_read(self):
        digest = _morning(self.user)
        digest["_reader"].assert_called_once_with(
            "the-api-key", "the-user-key", cells=True)
        real = _lines(digest, "real_money")
        self.assertRegex(real[0], r"^eToro real account, read at "
                                  r"\d{4}-\d\d-\d\d \d\d:\d\d UTC$")
        self.assertEqual(real[1:], [
            "Equity: 2,249.65 USD", "Available cash: 2,249.65 USD",
            "Used margin: 0.00 USD", "Held at eToro: none",
            "No real-money position on the platform.", DEMO_LINE])
        account = digest["sections"]["real_money"]["account"]
        self.assertEqual(account["source"], "live read")
        self.assertEqual(account["equity"], 2249.65)

    def test_a_raising_read_falls_back_to_the_cells_stamped_live(self):
        from bot_program.telegram_eye import when
        at = timezone.now() - timedelta(minutes=20)
        self.live_stamps(at)
        digest = _morning(self.user, requests.ConnectionError("down"))
        self.assertEqual(_lines(digest, "real_money"), [
            f"eToro real account, as of {when(at)} (the live read did not "
            f"answer)",
            "Equity: 2,249.65 USD", "Available cash: 2,200.00 USD",
            "Used margin: 49.65 USD", "Held at eToro: none",
            "No real-money position on the platform."])
        # the row is live: no demo line, and no demo equity under Simulated
        self.assertFalse([ln for ln in _lines(digest, "simulated")
                          if "demo" in ln])

    def test_a_read_that_answers_no_equity_falls_back_too(self):
        at = timezone.now() - timedelta(minutes=5)
        self.live_stamps(at)
        digest = _morning(self.user, {"equity": None, "positions": 0,
                                      "cells": None})
        real = _lines(digest, "real_money")
        self.assertIn("(the live read did not answer)", real[0])
        self.assertIn("Equity: 2,249.65 USD", real)

    def test_no_key_reads_the_stamped_cells_and_never_calls_the_read(self):
        from bot_program.telegram_eye import when
        at = timezone.now() - timedelta(minutes=20)
        self.live_stamps(at)
        self.acct.api_key_enc = ""
        self.acct.save()
        digest = _morning(self.user)
        digest["_reader"].assert_not_called()
        real = _lines(digest, "real_money")
        self.assertEqual(real[0], f"eToro real account, as of {when(at)} "
                                  f"(no key is stored for a live read)")
        self.assertIn("Equity: 2,249.65 USD", real)

    def test_cells_stamped_in_the_demo_world_are_never_real_money(self):
        digest = _morning(self.user, requests.ConnectionError("down"))
        real = _lines(digest, "real_money")
        self.assertEqual(real, [
            "eToro real account: the live read did not answer, and no "
            "earlier reading of it is stored",
            "No real-money position on the platform.", DEMO_LINE])
        self.assertFalse([ln for ln in real if "99,812.40" in ln
                          or "97,500.00" in ln])
        self.assertIn(
            "eToro demo account equity: 99,812.40 USD (synced 12 min ago)",
            _lines(digest, "simulated"))

    def test_an_equity_newer_than_its_world_stamp_is_in_neither_section(self):
        """sync_etoro_accounts writes the equity whenever that read answers
        and the world only with a margin cell: right after the flip, the
        real account's equity can sit beside an older "demo" stamp."""
        self.acct.demo = False
        self.acct.last_margin_at = timezone.now() - timedelta(minutes=30)
        self.acct.last_equity = Decimal("2249.65")
        self.acct.last_equity_at = timezone.now() - timedelta(minutes=3)
        self.acct.save()
        digest = _morning(self.user, requests.ConnectionError("down"))
        real = _lines(digest, "real_money")
        self.assertEqual(real, [
            f"eToro real account: the live read did not answer, and "
            f"{UNKNOWN}",
            "No real-money position on the platform."])
        every = "\n".join(real + _lines(digest, "simulated"))
        self.assertNotIn("2,249.65", every)
        self.assertNotIn("eToro demo account", every)
        # while the platform trades the demo, Simulated says it too
        self.acct.demo = True
        self.acct.save()
        sim = _lines(_morning(self.user), "simulated")
        self.assertIn(f"eToro demo account: {UNKNOWN}", sim)
        self.assertFalse([ln for ln in sim if "demo account equity" in ln])

    def test_a_stored_key_that_does_not_decrypt_is_said_so(self):
        from bot_program.models import EtoroAccount
        from bot_program.telegram_eye import when
        at = timezone.now() - timedelta(minutes=20)
        self.live_stamps(at)
        self.acct.api_key_enc = "not-a-token-this-server-can-decrypt"
        self.acct.save()
        # get_credentials swallows the failure: (None, None), no raise
        self.assertEqual(self.acct.get_credentials(), (None, None))
        digest = _morning(self.user)
        digest["_reader"].assert_not_called()
        real = _lines(digest, "real_money")
        self.assertEqual(real[0], f"eToro real account, as of {when(at)} "
                                  f"(the stored key could not be read)")
        self.assertIn("Equity: 2,249.65 USD", real)
        # a reader that raises says the same, never "no key"
        with patch.object(EtoroAccount, "get_credentials",
                          side_effect=ValueError("bad token")):
            real = _lines(_morning(self.user), "real_money")
        self.assertIn("(the stored key could not be read)", real[0])
        self.assertFalse([ln for ln in real if "no key" in ln], real)

    def test_positions_held_at_etoro_that_the_platform_does_not_list(self):
        live = _cfg(self.user, "stock", mode="live")
        _quote("TSLA", "250")
        _trade(live, "TSLA", qty="1", entry="240", paper=False,
               metadata={"broker": "etoro", "broker_env": "live"})
        real = _lines(_morning(self.user, dict(LIVE, positions=3)),
                      "real_money")
        extra = "2 positions held at eToro are not on the platform"
        self.assertIn("Held at eToro: 3 positions", real)
        self.assertIn(extra, real)
        self.assertLess(real.index(extra),
                        real.index("Real-money positions on the platform: 1"))
        one = _lines(_morning(self.user, dict(LIVE, positions=2)),
                     "real_money")
        self.assertIn("1 position held at eToro is not on the platform", one)
        # as many held as the platform lists: no such line
        same = _lines(_morning(self.user, dict(LIVE, positions=1)),
                      "real_money")
        self.assertFalse([ln for ln in same if "not on the platform" in ln],
                         same)
        # the stamped live cells count the same way
        self.live_stamps(timezone.now() - timedelta(minutes=20))
        self.acct.broker_positions = [{"symbol": "TSLA"}, {"symbol": "AMD"}]
        self.acct.save()
        stamped = _lines(_morning(self.user, requests.ConnectionError("x")),
                         "real_money")
        self.assertIn("1 position held at eToro is not on the platform",
                      stamped)

    def test_the_read_is_the_eyes_own_and_only_reads(self):
        from alerts.scheduled_digests import generate_morning_digest
        from bot_program import telegram_eye as eye
        client = MagicMock()
        client.net_liquidation.return_value = (2249.65, "USD")
        client.get_positions.return_value = []
        client.margin_cells.return_value = {
            "available_cash": 2249.65, "used_margin": 0.0, "currency": "USD"}
        with patch(TRADER, return_value=client) as trader:
            digest = generate_morning_digest(user=self.user)
        self.assertEqual(trader.call_args.kwargs.get("env"), "live")
        self.assertEqual({c[0] for c in client.method_calls},
                         {"net_liquidation", "get_positions",
                          "margin_cells"})
        self.assertIn("Equity: 2,249.65 USD", _lines(digest, "real_money"))
        # the status report keeps its two reads
        client.reset_mock()
        with patch(TRADER, return_value=client):
            out = eye.read_live_account("k", "u")
        self.assertEqual({c[0] for c in client.method_calls},
                         {"net_liquidation", "get_positions"})
        self.assertNotIn("cells", out)

    def test_the_real_client_sends_gets_only(self):
        from alerts.scheduled_digests import generate_morning_digest
        payloads = {
            "aggregate-portfolio": {
                "accountCurrency": "USD",
                "accountTotals": {"accountTotalValue": 2249.65,
                                  "accountAvailableCash": 2249.65,
                                  "accountTotalUsedMargin": 0.0}},
            "portfolio": {"clientPortfolio": {"positions": []}},
        }
        urls = []

        def fake_get(session, url, **kwargs):
            urls.append(url)
            body = payloads[url.rsplit("/", 1)[-1]]
            return MagicMock(status_code=200, json=lambda: body,
                             raise_for_status=lambda: None)

        writes = MagicMock(side_effect=AssertionError("a write was sent"))
        with patch.object(requests.Session, "get", fake_get), \
                patch.object(requests.Session, "post", writes), \
                patch.object(requests.Session, "put", writes), \
                patch.object(requests.Session, "patch", writes), \
                patch.object(requests.Session, "delete", writes):
            digest = generate_morning_digest(user=self.user)
        writes.assert_not_called()
        self.assertEqual(len(urls), 3, urls)
        for url in urls:
            self.assertRegex(url, r"/api/v1/trading/info/"
                                  r"(aggregate-portfolio|portfolio)$")
            self.assertNotIn("/demo/", url)
        self.assertEqual(_lines(digest, "real_money")[1:5], [
            "Equity: 2,249.65 USD", "Available cash: 2,249.65 USD",
            "Used margin: 0.00 USD", "Held at eToro: none"])

    def test_the_module_carries_no_write(self):
        import inspect
        from alerts import digest_book
        src = inspect.getsource(digest_book)
        for needle in ("market_order", "close_position", "cancel_order",
                       "modify_protective", "modify_target",
                       "set_credentials", "select_for_update",
                       "enabled = True", ".save(", "objects.create",
                       "objects.update", ".post(", ".delete("):
            self.assertNotIn(needle, src)


# ── B2: the end-of-day summary ───────────────────────────────────────────

class EndOfDayTests(TestCase):
    def setUp(self):
        self.user = _user("Father")
        self.paper = _cfg(self.user, "stock")
        self.live = _cfg(self.user, "stock", mode="live")

    def test_todays_opens_and_closes_from_assetbottrade(self):
        real = {"broker": "etoro", "broker_env": "live"}
        _trade(self.paper, "NFLX", opened_at=_today(2))
        _trade(self.paper, "AAPL", side="SELL", status="CLOSED",
               opened_at=_yesterday(), closed_at=_today(5), pnl="-12.40",
               realized_r=-0.62, outcome="stopped_out", exit_price="260")
        _trade(self.live, "TSLA", paper=False, metadata=real, status="CLOSED",
               opened_at=_today(3), closed_at=_today(6), pnl="8.10",
               realized_r=0.81, outcome="hit_target", exit_price="248.10")
        # never listed: an error and a canceled row of today, yesterday's
        # round trip, another user's row of today
        _trade(self.paper, "MSFT", status="ERROR", opened_at=_today(4))
        _trade(self.paper, "AMZN", status="CANCELED", opened_at=_today(4))
        _trade(self.paper, "GOOG", status="CLOSED", opened_at=_yesterday(),
               closed_at=_yesterday(), pnl="3")
        _trade(_cfg(_user("Other"), "stock"), "META", opened_at=_today(4))
        digest = _eod(self.user)
        self.assertEqual(list(digest["sections"])[:2],
                         ["real_money", "simulated"])
        self.assertEqual(_lines(digest, "trades"), [
            "Opened: 2 · Closed: 2",
            "• Opened NFLX long · Simulated",
            "• Opened TSLA long · Real money (eToro)",
            "• Closed AAPL short · Stop loss hit · -12.40 USD · -0.62R · "
            "Simulated",
            "• Closed TSLA long · Target reached · +8.10 USD · +0.81R · "
            "Real money (eToro)"])
        closes = digest["sections"]["trades"]["closed"]
        self.assertEqual([(c["pnl"], c["r"]) for c in closes],
                         [(-12.4, -0.62), (8.1, 0.81)])
        # the book: NFLX is still open
        self.assertEqual(digest["summary"], [
            "User: Father", "Open positions: 1 (1 simulated · 0 real money)"])

    def test_a_close_nothing_could_price_says_so(self):
        _trade(self.paper, "AAPL", status="CLOSED", opened_at=_yesterday(),
               closed_at=_today(5), pnl=None)
        self.assertEqual(_lines(_eod(self.user), "trades")[1],
                         "• Closed AAPL long · result not priced · "
                         "Simulated")

    def test_a_legacy_position_of_today_counts_once(self):
        from portfolio.services import get_or_create_default_portfolio
        _legacy(self.user, "EURUSD", opened_at=_today(2))
        _legacy(self.user, "GBPUSD", opened_at=_yesterday(),
                closed_at=_today(3), pnl="-3.10")
        ccy = get_or_create_default_portfolio(user=self.user).currency
        lines = _lines(_eod(self.user), "trades")
        self.assertEqual(lines, [
            "Opened: 1 · Closed: 1",
            "• Opened EURUSD long · Simulated",
            "• Closed GBPUSD long · -3.10 · Simulated"])
        # the P&L is the instrument's price currency, never the book's
        self.assertFalse([ln for ln in lines if f" {ccy} " in ln], lines)

    def test_the_seeded_books_snapshot_is_said_not_printed(self):
        """Every snapshot figure of a seeded book is measured from the
        seed: the total, the two percentages and the drawdown divide by
        it, and the money P&L misses every close (nothing credits the
        seed). The section says so and prints none of them."""
        from alerts.scheduled_digests import digest_lines
        from portfolio.models import PortfolioSnapshot
        from portfolio.services import get_or_create_default_portfolio
        book = get_or_create_default_portfolio(user=self.user)
        PortfolioSnapshot.objects.create(
            portfolio=book, date=timezone.now().date(),
            total_value=Decimal("10031.20"), cash=book.cash_available,
            daily_pnl=Decimal("31.20"), daily_pnl_pct=0.37,
            cumulative_pnl_pct=0.43, max_drawdown=-0.05)
        digest = _eod(self.user)
        self.assertEqual(digest["sections"]["daily_pnl"], {
            "seeded": True,
            "lines": ["Not measured while the book value is not set."]})
        lines = [str(ln) for ln in digest_lines(digest)]
        at = lines.index("Daily P&L")
        self.assertEqual(lines[at + 1],
                         "Not measured while the book value is not set.")
        self.assertIn("Book value: not set", lines)
        text = "\n".join(lines)
        for figure in ("10,031.20", "31.20", "0.37", "0.43", "-0.05"):
            self.assertNotIn(figure, text)
        # a book whose capital was entered prints the snapshot
        book.initial_capital = book.cash_available = Decimal("2500.00")
        book.save()
        daily = _eod(self.user)["sections"]["daily_pnl"]
        self.assertEqual(daily["total_value"], 10031.2)
        self.assertEqual((daily["pnl"], daily["pnl_pct"],
                          daily["cumulative_pnl_pct"], daily["max_drawdown"]),
                         (31.2, 0.37, 0.43, -0.05))

    def test_a_measured_books_daily_pnl_carries_the_books_currency(self):
        """The P&L and the total value are money of the book, printed in
        its currency with the book section's own money words — never
        bare figures beside "Book value: ... EUR" and "Equity: ... USD",
        which read as dollars. The percentages carry their sign and
        their % sign."""
        from alerts.scheduled_digests import digest_lines
        from portfolio.models import PortfolioSnapshot
        from portfolio.services import get_or_create_default_portfolio
        book = get_or_create_default_portfolio(user=self.user)
        book.initial_capital = book.cash_available = Decimal("2500.00")
        book.save()
        PortfolioSnapshot.objects.create(
            portfolio=book, date=timezone.now().date(),
            total_value=Decimal("10031.20"), cash=book.cash_available,
            daily_pnl=Decimal("-312.50"), daily_pnl_pct=-3.02,
            cumulative_pnl_pct=0.43, max_drawdown=-0.05)
        ccy = book.currency
        self.assertTrue(ccy)
        digest = _eod(self.user)
        daily = digest["sections"]["daily_pnl"]
        self.assertEqual(daily["currency"], ccy)
        self.assertEqual((daily["pnl"], daily["total_value"]),
                         (-312.5, 10031.2))
        self.assertEqual(daily["lines"], [
            f"P&L: -312.50 {ccy} (-3.02%)",
            f"Total value: 10,031.20 {ccy}",
            "Cumulative P&L: +0.43%",
            "Max drawdown: -0.05%"])
        lines = [str(ln) for ln in digest_lines(digest)]
        at = lines.index("Daily P&L")
        self.assertEqual(lines[at + 1:at + 5], daily["lines"])
        text = "\n".join(lines)
        self.assertNotIn("• P&L: -312.50\n", text + "\n")
        self.assertNotIn("Total value: 10,031.20\n", text + "\n")


# ── the import of the new module is guarded ──────────────────────────────

class TheBookImportIsGuardedTests(TestCase):
    def test_a_book_module_that_fails_to_import_costs_only_its_lines(self):
        import sys
        from alerts.scheduled_digests import (digest_lines,
                                              generate_eod_digest,
                                              generate_morning_digest)
        user = _user("Guarded")
        name = "alerts.digest_book"
        before = sys.modules.get(name, _UNSET)
        sys.modules[name] = None  # the import now raises
        try:
            morning = generate_morning_digest(user=user)
            eod = generate_eod_digest(user=user)
        finally:
            if before is _UNSET:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = before
        for digest in (morning, eod):
            self.assertEqual(len(digest["summary"]), 1)
            self.assertTrue(digest["summary"][0].startswith(
                "The open positions could not be read ("), digest["summary"])
            self.assertNotIn("real_money", digest["sections"])
            self.assertEqual(digest_lines(digest)[0], digest["summary"][0])
        self.assertIn("signals", morning["sections"])
        self.assertIn("strategies", eod["sections"])
        self.assertNotIn("trades", eod["sections"])


# ── the rendered text ────────────────────────────────────────────────────

class PlainEnglishTests(_BookCase):
    def assertPlain(self, text):
        self.assertNotIn("None", text)
        self.assertNotIn("Decimal(", text)
        self.assertNotIn("nan", text.lower().split())
        self.assertNotIn("*", text)
        self.assertIsNone(SNAKE.search(text), text)
        self.assertIsNone(ACCENTED.search(text), text)
        low = " " + re.sub(r"[^a-z]+", " ", text.lower()) + " "
        for word in FRENCH:
            self.assertNotIn(word, low, text)

    def test_the_rendered_lines_are_plain_english(self):
        from alerts.scheduled_digests import digest_lines
        live = _cfg(self.user, "stock", mode="live")
        _quote("TSLA", "250")
        _trade(live, "TSLA", entry="240", paper=False,
               metadata={"broker": "etoro", "broker_env": "live"})
        _trade(self.stock, "AAPL", side="SELL", status="CLOSED",
               opened_at=_yesterday(), closed_at=_today(5), pnl="-12.40",
               realized_r=-0.62, outcome="stopped_out")
        _legacy(self.user, "EURUSD")
        for digest in (_morning(self.user), _eod(self.user),
                       _morning(self.user, requests.ConnectionError("x"))):
            lines = digest_lines(digest)
            self.assertTrue(all(isinstance(ln, str) for ln in lines))
            self.assertPlain("\n".join(lines))

    def test_the_telegram_text_opens_with_the_book(self):
        from alerts.models import UserNotificationPrefs
        from alerts.scheduled_digests import send_digest
        prefs, _ = UserNotificationPrefs.objects.get_or_create(user=self.user)
        prefs.telegram_chat_id = "-5337454557"
        prefs.save()
        digest = _morning(self.user)
        env = {"TELEGRAM_BOT_TOKEN": "123:t", "TELEGRAM_CHAT_ID": "-1"}
        with patch.dict(os.environ, env), \
                patch("requests.post", return_value=MagicMock(
                    ok=True, status_code=200, text="{}")) as post:
            send_digest(digest, user=self.user)
        text = post.call_args.kwargs["json"]["text"]
        head = text.split("\n")[:5]
        self.assertEqual(head, [
            "<b>\u2600\uFE0F Morning Market Brief</b>",
            SAURON, "Open positions: 5 (5 simulated · 0 real money)",
            "<b>Real money</b>", head[4]])
        self.assertTrue(head[4].startswith("eToro real account, read at "))
        self.assertLess(text.index("<b>Real money</b>"),
                        text.index("<b>Simulated</b>"))
        self.assertPlain(text)
