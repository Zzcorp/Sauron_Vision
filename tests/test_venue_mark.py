"""THE VENUE MARK: a real row is valued at its venue's own rate (2026-10-05).

The operator bought WTI and silver at eToro and the positions page showed a
gain at the open: the entry was eToro's fill, the mark the platform's Yahoo
quote, and the basis between the two rendered as P&L. Now the manage tick
stamps the venue's mark on a real row each time it reads one, and the book
prefers a fresh stamp over the LiveQuote for a real row — never for a paper
row, whose quote IS its venue. The page says which mark it shows.

Run with:  python manage.py test tests.test_venue_mark
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_risk_limits_bind import _config, _quote
from tests.test_scale_out import _trade


def _age(trade, seconds):
    """Age the row's venue mark by `seconds`."""
    meta = dict(trade.metadata)
    vm = dict(meta["venue_mark"])
    vm["at"] = (timezone.now() - timedelta(seconds=seconds)).isoformat()
    meta["venue_mark"] = vm
    trade.metadata = meta
    trade.save(update_fields=["metadata"])


class TheStampTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("vm_u", password="x")
        self.cfg = _config(self.user, symbols=["BTCUSD"])

    def test_a_real_row_is_stamped_and_read_while_fresh(self):
        from bot_program.venue_mark import MAX_AGE_S, fresh, stamp
        t = _trade(self.cfg, paper=False)
        self.assertTrue(stamp(t, Decimal("101.5"), source="etoro"))
        t.refresh_from_db()
        vm = t.metadata["venue_mark"]
        self.assertEqual((vm["price"], vm["source"]), (101.5, "etoro"))
        self.assertEqual(t.metadata["initial_stop_loss"], 98.0,
                         "the other keys stay")
        f = fresh(t)
        self.assertEqual((f["price"], f["source"]), (101.5, "etoro"))
        self.assertLess(f["age_s"], 5)
        _age(t, MAX_AGE_S + 10)
        self.assertIsNone(fresh(t), "a stale stamp is not a mark")
        self.assertIsNotNone(fresh(t, max_age_s=MAX_AGE_S + 100))

    def test_never_a_paper_row_a_bad_price_or_the_same_print_twice(self):
        from bot_program.venue_mark import REWRITE_AFTER_S, fresh, stamp
        paper = _trade(self.cfg)
        self.assertFalse(stamp(paper, Decimal("101.5"), source="etoro"))
        paper.refresh_from_db()
        self.assertNotIn("venue_mark", paper.metadata)
        self.assertIsNone(fresh(paper))
        t = _trade(self.cfg, paper=False, symbol="ETHUSD")
        for bad in (None, 0, -1, "x"):
            self.assertFalse(stamp(t, bad, source="etoro"))
        t.refresh_from_db()
        self.assertNotIn("venue_mark", t.metadata)
        self.assertTrue(stamp(t, 101.5))
        self.assertFalse(stamp(t, 101.5), "the same print, just written")
        self.assertTrue(stamp(t, 101.6), "a new print is always written")
        _age(t, REWRITE_AFTER_S + 5)
        self.assertTrue(stamp(t, 101.6), "the same print, old enough")
        # a paper row's stamp (planted by hand) is never read
        planted = _trade(self.cfg, symbol="LTCUSD",
                         meta={"venue_mark": {"price": 50.0,
                                              "at": timezone.now().isoformat(),
                                              "source": "etoro"}})
        self.assertIsNone(fresh(planted))


class TheBookTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("vm_book", password="x")
        self.cfg = _config(self.user, symbols=["BTCUSD"])
        _quote("BTCUSD", "100.9")

    def _row(self, symbol="BTCUSD"):
        from portfolio.services import unified_open_positions
        rows = [r for r in unified_open_positions(self.user)
                if getattr(r.instrument, "symbol", "") == symbol]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_a_real_row_prefers_a_fresh_venue_mark_over_the_platform_quote(self):
        from bot_program.venue_mark import MAX_AGE_S, stamp
        t = _trade(self.cfg, paper=False)           # entry 100, qty 1
        stamp(t, 100.2, source="etoro")
        row = self._row()
        self.assertEqual(row.current_price, Decimal("100.2"))
        self.assertAlmostEqual(row.unrealized_pnl, 0.2, places=6)
        self.assertEqual(row.mark_source, "venue")
        # the stamp gone stale: the platform's quote, said so
        _age(t, MAX_AGE_S + 10)
        row = self._row()
        self.assertEqual(row.current_price, Decimal("100.9"))
        self.assertAlmostEqual(row.unrealized_pnl, 0.9, places=6)
        self.assertEqual(row.mark_source, "quote")

    def test_a_paper_row_reads_the_platform_quote_whatever_the_stamp(self):
        _trade(self.cfg, meta={"venue_mark": {"price": 100.2,
                                              "at": timezone.now().isoformat(),
                                              "source": "etoro"}})
        row = self._row()
        self.assertEqual(row.current_price, Decimal("100.9"))
        self.assertEqual(row.mark_source, "quote")

    def test_no_quote_and_no_stamp_is_unknown_and_a_close_is_the_exit(self):
        t = _trade(self.cfg, paper=False, symbol="NOQUOTE")
        row = self._row("NOQUOTE")
        self.assertIsNone(row.current_price)
        self.assertIsNone(row.unrealized_pnl)
        self.assertIsNone(row.mark_source)
        t.status = "CLOSED"
        t.exit_price = Decimal("99")
        t.pnl = Decimal("-1")
        t.closed_at = timezone.now()
        t.save()
        from portfolio.services import unified_closed_positions
        closed = [r for r in unified_closed_positions(self.user)
                  if getattr(r.instrument, "symbol", "") == "NOQUOTE"][0]
        self.assertEqual(closed.mark_source, "exit")

    def test_the_book_value_reads_the_venue_mark_too(self):
        from bot_program.venue_mark import stamp
        from portfolio.services import live_book_value
        t = _trade(self.cfg, paper=False, qty="10")      # entry 100
        stamp(t, 100.2, source="etoro")
        book = live_book_value(self.user)
        row = [r for r in book.rows if getattr(r, "trade_id", None) == t.id][0]
        self.assertEqual(row.current_price, Decimal("100.2"))
        self.assertAlmostEqual(row.unrealized_pnl, 2.0, places=6)


class TheEngineTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("vm_eng", password="x")
        self.cfg = _config(self.user, symbols=["BTCUSD", "ETHUSD"])
        from bot_program.asset_engine.base import make_bot
        self.bot = make_bot(self.cfg)

    def test_the_manage_tick_stamps_a_real_row_at_the_venues_rate_never_a_paper_one(self):
        t = _trade(self.cfg, paper=False)
        client = mock.MagicMock(spec=["ticker"])
        client.ticker.return_value = {"lastPrice": "100.4", "symbol": "BTCUSD"}
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=client):
            self.assertEqual(self.bot.manage_positions(), 0)
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN")
        vm = t.metadata["venue_mark"]
        self.assertEqual(vm["price"], 100.4)
        self.assertIn("at", vm)
        paper = _trade(self.cfg, symbol="ETHUSD")
        _quote("ETHUSD", "100.4")
        with mock.patch("bot_program.engine.paper_trader.paper_market_shut",
                        return_value=""):
            self.bot.manage_positions()
        paper.refresh_from_db()
        self.assertNotIn("venue_mark", paper.metadata)


class TheWiringTests(SimpleTestCase):

    def test_the_stamp_sits_after_the_sanity_gate_and_before_everything_that_acts(self):
        import inspect

        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.manage_positions)
        gate = src.index('mark_sanity.check(self, trade, price, client)["ok"]')
        stamp = src.index("venue_mark.stamp(trade, price")
        vanished = src.index("self._protection_vanished(trade, client)")
        self.assertLess(gate, stamp)
        self.assertLess(stamp, vanished)

    def test_the_book_and_the_page_know_the_marks_source(self):
        import inspect
        from pathlib import Path

        from portfolio import services
        self.assertIn("mark_source", services.UnifiedPosition.__slots__)
        book = inspect.getsource(services._trade_to_position)
        # 2026-10-08: through the one answer, venue_mark.resolve, which
        # answers "venue" for a fresh stamp (tests.test_venue_mark_birth)
        self.assertIn(
            "from bot_program.venue_mark import resolve as _venue_resolve",
            book)
        self.assertIn("mk = _venue_resolve(trade, quote)", book)
        self.assertIn("up.mark_source = mk.source", book)
        from dashboard import views
        self.assertIn('"mark_source"', inspect.getsource(views._live_row))
        tpl = Path(views.__file__).resolve().parents[1] / "templates" / \
            "dashboard" / "positions_list.html"
        self.assertIn("mark_source", tpl.read_text())
