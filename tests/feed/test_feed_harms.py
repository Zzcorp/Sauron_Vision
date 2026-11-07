"""THE HARM COUNTERS (the eToro feed spec, F1, §6.2; 2026-11-07).

Evidence before any PIN: every time today's code does one of the harms
F2a, F2b, F5 and F8 remove, one FeedHarmEvent row says so, and
`manage.py feed_harms --days N` prints the counts by kind — never a price,
an account figure or an id. What is pinned:

  * the kinds, the model, its migration and the command (listed on /ops/
    as a read, off the Run lane);
  * each hook records what it should, and only that: a mark-sanity skip
    of a real row (why, the levels, whether the closing side crossed the
    stop or the target), a CLOSE refused for no usable price mark (the
    dialog's and the close's), the kill switch's wait before each close,
    a poller's previousClose, a poller's price outside the market clock's
    session, a zero or crossed side stored, and every real exit booked at
    the mark, at an outside quote, at a level the venue held, unpriced, or
    left CLOSE_PENDING;
  * EVERY HOOK IS FENCED AND OUT OF THE MONEY PATH'S TRANSACTION: with the
    counter's write raising, and with the hook itself raising, each money
    path answers exactly as it does with no counter; a money path that
    rolls back leaves no harm row; a counter write that fails never fails
    the path's own commit; one WARNING per failure, never more, on the
    counter's side and on the path's; a money module reaches the counters
    only through bot_program.feed_fence;
  * the kill switch's harm rows wait until the sweep's last close is sent.

Run with:  python manage.py test tests.feed.test_feed_harms
"""
import contextlib
import io
import logging
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.db import transaction
from django.test import SimpleTestCase, TestCase

from tests.feed import harness as H

WRITE = "bot_program.feed_harms._insert"
#: In production most money paths run in autocommit, where an on-commit
#: callback runs at once; a TestCase holds every test in one transaction,
#: so the tests that care say "as autocommit does" with this patch.
AT_ONCE = "bot_program.feed_harms._after_commit"


def _fh():
    from bot_program import feed_harms
    return feed_harms


def _rows(kind=None):
    from bot_program.feed_harm_models import FeedHarmEvent
    qs = FeedHarmEvent.objects.all()
    return list(qs.filter(kind=kind) if kind else qs)


def _poll_commodities(case, info):
    """The commodity poller's pass over one synthetic instrument whose
    Yahoo answer is `info` (its components switched on)."""
    from market_data import tasks
    from tests.test_aragorn import _switch
    _switch("platform_master")
    _switch("scraper_commodities")

    class _Ticker:
        def __init__(self, sym):
            self.info = dict(info)
    with mock.patch("yfinance.Ticker", _Ticker), \
            mock.patch("market_data.tasks._quote_universe",
                       return_value=[H.instrument("XAUUSD", "commodity")]), \
            mock.patch("core.market_calendar.is_weekend",
                       return_value=False), \
            case.captureOnCommitCallbacks(execute=True):
        return tasks.fetch_commodity_quotes()


class CounterBroke(Exception):
    """A counter's failure no money path raises on its own: the fences log
    the failure's type, so a test counts exactly the fences' words."""


@contextlib.contextmanager
def _told(*names):
    """Every record logged under the named loggers and their children
    while the block runs."""
    records = []

    class _Keep(logging.Handler):
        def emit(self, record):
            records.append(record)
    keep = _Keep(level=logging.DEBUG)
    loggers = [logging.getLogger(n) for n in names]
    levels = [lg.level for lg in loggers]
    for lg in loggers:
        lg.addHandler(keep)
        lg.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        for lg, level in zip(loggers, levels):
            lg.removeHandler(keep)
            lg.setLevel(level)


class _Case(TestCase):

    def setUp(self):
        self.clock = H.FakeClock()
        self.clock.__enter__()
        self.addCleanup(self.clock.__exit__, None, None, None)
        p = mock.patch("bot_program.venue_mark.market_shut",
                       return_value=None)
        p.start()
        self.addCleanup(p.stop)
        self.owner = H.user("harm_owner")
        self.cfg = H.live_config(self.owner, "forex")
        H.instrument("EURUSD", "forex")
        _fh()._reset_warnings()

    def _row(self, **kw):
        d = dict(entry="1.1000", stop="1.0900", target="1.1200")
        d.update(kw)
        return H.real_row(self.cfg, "EURUSD", **d)

    def _paper_row(self):
        from bot_program.models import AssetBotTrade
        cfg = H.live_config(self.owner, "forex", name="paper_book")
        cfg.mode = "paper"
        cfg.save(update_fields=["mode"])
        return AssetBotTrade.objects.create(
            config=cfg, asset_class="forex", symbol="EURUSD", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("1.1"),
            stop_loss=Decimal("1.09"), take_profit=Decimal("1.12"),
            status="OPEN", paper=True, rule_name="replay",
            metadata={"initial_stop_loss": 1.09})


# ── 1. the kinds, the model, its migration, the command ──────────────────

class TheModelTests(SimpleTestCase):
    #: makemigrations reads the migration history
    databases = {"default"}

    def test_the_kinds(self):
        fh = _fh()
        self.assertEqual(set(fh.KINDS), {
            "mark_skip_reference", "mark_skip_jump", "mark_skip_frozen",
            "close_no_mark", "close_preview_no_mark", "kill_switch_wait",
            "poller_previous_close", "poller_out_of_session",
            "quote_bad_sides", "exit_at_mark", "exit_at_outside_quote",
            "exit_at_level", "exit_unpriced", "exit_close_pending"})
        self.assertEqual(set(fh.KIND_WORDS), set(fh.KINDS))
        self.assertEqual(set(fh.POLLER_SOURCES), {
            "yfinance", "alpha_vantage", "binance_public", "coingecko"})

    def test_the_model_and_its_migration(self):
        from bot_program.feed_harm_models import FeedHarmEvent
        names = {f.name for f in FeedHarmEvent._meta.get_fields()}
        self.assertTrue({"at", "kind", "real", "symbol", "source", "seconds",
                         "detail", "ref"} <= names)
        self.assertEqual(FeedHarmEvent._meta.app_label, "bot_program")
        from importlib import import_module
        mig = import_module("bot_program.migrations.0051_feed_harm_event")
        self.assertEqual(mig.Migration.dependencies,
                         [("bot_program", "0050_orcs_o2b")])
        created = [op.name for op in mig.Migration.operations
                   if op.__class__.__name__ == "CreateModel"]
        self.assertEqual(created, ["FeedHarmEvent"])

    def test_no_model_change_is_left_without_a_migration(self):
        out = io.StringIO()
        try:
            call_command("makemigrations", "bot_program", "--check",
                         "--dry-run", stdout=out, stderr=out)
        except SystemExit as e:
            self.fail(f"bot_program has an unmigrated change: {out.getvalue()}"
                      f" ({e})")


class TheCommandTests(TestCase):

    def test_counts_by_kind_and_never_a_price_an_account_figure_or_an_id(self):
        from bot_program.feed_harm_models import FeedHarmEvent
        from django.utils import timezone
        now = timezone.now()
        for kind, n in (("mark_skip_reference", 3), ("close_no_mark", 1),
                        ("exit_at_mark", 2)):
            for i in range(n):
                FeedHarmEvent.objects.create(
                    kind=kind, real=True, symbol="EURUSD", source="yfinance",
                    ref=f"trade:{9000 + i}" if kind == "exit_at_mark" else "",
                    detail={"price": 7.25, "reference": 8.5,
                            "stop": 6.75, "why": "suspect mark: 0.7%",
                            "equity": 250000.0})
        for s in (0.4, 19.8, 1.2):
            FeedHarmEvent.objects.create(kind="kill_switch_wait", real=True,
                                         symbol="AAPL", seconds=s)
        old = FeedHarmEvent.objects.create(kind="close_no_mark", real=True)
        FeedHarmEvent.objects.filter(pk=old.pk).update(
            at=now - __import__("datetime").timedelta(days=9))
        out = io.StringIO()
        call_command("feed_harms", "--days", "7", stdout=out)
        text = out.getvalue()
        self.assertIn("mark_skip_reference", text)
        lines = {ln.split()[0]: ln for ln in text.splitlines()
                 if ln.strip() and ln.split()[0] in _fh().KINDS}
        self.assertEqual(lines["mark_skip_reference"].split()[1], "3")
        self.assertEqual(lines["close_no_mark"].split()[1], "1",
                         "the nine-day-old row is outside the window")
        self.assertEqual(lines["exit_at_mark"].split()[1], "2")
        self.assertEqual(lines["kill_switch_wait"].split()[1], "3")
        self.assertIn("max 19.8 s", lines["kill_switch_wait"])
        self.assertEqual(lines["exit_unpriced"].split()[1], "0",
                         "every kind is listed, zeros included")
        for secret in ("7.25", "8.5", "6.75", "250000", "9000",
                       "EURUSD", "AAPL", "yfinance", "0.7%"):
            self.assertNotIn(secret, text)

    def test_the_days_are_a_positive_whole_number(self):
        from django.core.management.base import CommandError
        with self.assertRaisesRegex(CommandError, "--days"):
            call_command("feed_harms", "--days", "0", stdout=io.StringIO())

    def test_the_command_is_in_the_catalogue_and_off_the_run_lane(self):
        """/ops/ lists it as a read (core.ops_commands): read-only, asking
        no broker, and not on the page's Run lane, whose set is pinned."""
        from core import ops_commands
        entry = ops_commands.get("feed_harms")
        self.assertIsNotNone(entry)
        self.assertEqual((entry["category"], entry["read_only"]),
                         ("read", True))
        self.assertFalse(ops_commands.is_runnable(entry))
        self.assertNotIn("feed_harms", ops_commands.runnable_names())


# ── 2. each hook, and only what it should ────────────────────────────────

class TheMarkSkipTests(_Case):

    def _check(self, trade, price, *, last_ticks=None):
        from bot_program import mark_sanity
        bot = SimpleNamespace(cfg=trade.config,
                              _last_ticks=last_ticks or {})
        with self.captureOnCommitCallbacks(execute=True):
            return mark_sanity.check(bot, trade, price, None)

    def test_a_disagreeing_reference_with_the_levels_and_the_crossing(self):
        """A real long at 1.1000, stop 1.0900: eToro's bid 1.0890 is
        through the stop while an outside quote 1% away suspends it."""
        H.write_live_quote("EURUSD", source="oanda_stream", last="1.1000",
                           clock=self.clock)
        t = self._row()
        v = self._check(t, 1.0891, last_ticks={"EURUSD": {
            "bid": "1.0890", "ask": "1.0892"}})
        self.assertFalse(v["ok"])
        (row,) = _rows()
        self.assertEqual((row.kind, row.real, row.symbol),
                         ("mark_skip_reference", True, "EURUSD"))
        d = row.detail
        self.assertEqual((d["closing_basis"], d["closing_side"]),
                         ("bid", 1.089))
        self.assertTrue(d["crossed_stop"])
        self.assertFalse(d["crossed_target"])
        self.assertEqual((d["stop"], d["target"], d["reference"]),
                         (1.09, 1.12, 1.1))
        self.assertIn("platform's quote", d["why"])

    def test_a_jump_and_a_freeze_are_their_own_kinds(self):
        from datetime import timedelta
        t = self._row(meta={"care": {
            "last_mark": 1.1, "last_mark_at": self.clock.ago(60).isoformat(),
            "mark_same_since": self.clock.ago(60).isoformat()}})
        self._check(t, 1.12)
        self.assertEqual([r.kind for r in _rows()], ["mark_skip_jump"])
        frozen = self._row(meta={"care": {
            "last_mark": 1.1,
            "last_mark_at": self.clock.ago(3000).isoformat(),
            "mark_same_since": self.clock.ago(3000).isoformat()}})
        with mock.patch("bot_program.notifications.notify_staff"):
            self._check(frozen, 1.1)
        self.assertEqual(sorted(r.kind for r in _rows()),
                         ["mark_skip_frozen", "mark_skip_jump"])
        self.assertIsNotNone(timedelta)

    def test_a_paper_row_and_an_accepted_mark_record_nothing(self):
        H.write_live_quote("EURUSD", source="oanda_stream", last="1.1000",
                           clock=self.clock)
        self._check(self._paper_row(), 1.05)
        self._check(self._row(), 1.1001)
        self.assertEqual(_rows(), [])


class TheCloseRefusalTests(_Case):

    def test_the_dialog_and_the_close_each_count_their_refusal(self):
        from bot_program.manual_close import execute_close, preview_close
        t = self._row()
        with H.route_to(H.EtoroTrader()), \
                self.captureOnCommitCallbacks(execute=True):
            preview_close(self.owner, t)
            execute_close(self.owner, t, pin_ok=True)
        self.assertEqual(sorted((r.kind, r.real) for r in _rows()),
                         [("close_no_mark", True),
                          ("close_preview_no_mark", True)])

    def test_a_close_with_a_mark_counts_nothing(self):
        from bot_program.manual_close import preview_close
        with H.route_to(H.EtoroTrader({"EURUSD": H.tick("1.1")})), \
                self.captureOnCommitCallbacks(execute=True):
            self.assertNotIn("error", preview_close(self.owner, self._row()))
        self.assertEqual(_rows(), [])


class TheKillSwitchWaitTests(_Case):

    def _sweep(self, etoro, *, at_once=False):
        from bot_program.engine.kill_switch import execute_kill_switch
        ctx = (mock.patch(AT_ONCE, side_effect=lambda fn: fn()) if at_once
               else contextlib.nullcontext())
        with ctx, H.route_to(etoro), \
                self.captureOnCommitCallbacks(execute=True):
            return execute_kill_switch(self.owner, reason="replay")

    def test_one_wait_per_close_in_seconds(self):
        self._row(position_id="p-1")
        self._row(position_id="p-2")
        etoro = H.EtoroTrader(writes="accept")
        self._sweep(etoro)
        waits = _rows("kill_switch_wait")
        self.assertEqual(len(waits), 2)
        for w in waits:
            self.assertTrue(w.real)
            self.assertGreaterEqual(w.seconds, 0.0)
        self.assertEqual(len(etoro.writes_sent), 2)

    def test_the_rows_wait_until_the_last_close_is_sent(self):
        """Not one harm row is written while a close is still to send —
        even with every callback running at once, as in autocommit; the
        same rows outside a sweep are written at once."""
        self._row(position_id="p-1")
        self._row(position_id="p-2")
        seen = []

        class _Counting(H.EtoroTrader):
            def close_position(self_, *a, **k):
                seen.append(len(_rows()))
                return super().close_position(*a, **k)
        self._sweep(_Counting(writes="accept"), at_once=True)
        self.assertEqual(seen, [0, 0])
        self.assertEqual(len(_rows("kill_switch_wait")), 2)
        self.assertEqual(len(_rows("exit_close_pending")), 2)
        # outside a sweep, the close's own booking writes at once
        from bot_program.engine.kill_switch import _close_asset_trade
        t = self._row(position_id="p-3")
        with mock.patch(AT_ONCE, side_effect=lambda fn: fn()), \
                H.route_to(H.EtoroTrader(writes="accept")):
            with self.assertRaises(RuntimeError):
                _close_asset_trade(t, self.clock.now)
            self.assertEqual(len(_rows("exit_close_pending")), 3)

    def test_a_hanging_read_is_measured(self):
        import time as _time
        self._row()

        class _Slow(H.EtoroTrader):
            def ticker(self_, symbol):
                _time.sleep(0.05)
                return super().ticker(symbol)
        self._sweep(_Slow(writes="accept"))
        (w,) = _rows("kill_switch_wait")
        self.assertGreaterEqual(w.seconds, 0.05)


class ThePollerTests(_Case):

    def _write(self, symbol, cls, **kw):
        from market_data.quotes import write_quote
        inst = H.instrument(symbol, cls)
        with self.captureOnCommitCallbacks(execute=True):
            return write_quote(symbol, instrument=inst, **kw)

    def test_zero_or_crossed_sides_stored_are_counted(self):
        self.assertTrue(self._write("EURUSD", "forex", last="1.1",
                                    source="alpha_vantage", bid="0",
                                    ask="1.1002"))
        self.assertTrue(self._write("EURUSD", "forex", last="1.1",
                                    source="alpha_vantage", bid="1.1003",
                                    ask="1.1002"))
        self.assertTrue(self._write("EURUSD", "forex", last="1.1",
                                    source="alpha_vantage", bid="1.0999",
                                    ask="1.1001"))
        rows = _rows("quote_bad_sides")
        self.assertEqual([r.detail["why"] for r in rows],
                         ["zero side", "crossed"])
        self.assertEqual({r.source for r in rows}, {"alpha_vantage"})

    def test_a_poller_price_outside_the_session_is_counted(self):
        """Wednesday 12:00 UTC: the US stock session is shut, crypto never
        is; a stream is not a poller."""
        self._write("AAPL", "stock", last="200", source="yfinance")
        self._write("BTCUSD", "crypto", last="50000", source="binance_public")
        self._write("AAPL", "stock", last="200", source="finnhub_ws")
        rows = _rows("poller_out_of_session")
        self.assertEqual([(r.symbol, r.source) for r in rows],
                         [("AAPL", "yfinance")])

    def test_a_refused_write_counts_nothing(self):
        self._write("EURUSD", "forex", last="1.1", source="oanda_stream")
        self.assertFalse(self._write("EURUSD", "forex", last="1.1",
                                     source="alpha_vantage", bid="0",
                                     ask="1.1002"))
        self.assertEqual(_rows(), [])

    def test_a_previous_close_written_by_the_poller_is_counted(self):
        out = _poll_commodities(self, {"previousClose": 2000.0})
        self.assertEqual(out.get("fetched"), 1, out)
        rows = _rows("poller_previous_close")
        self.assertEqual([(r.symbol, r.source) for r in rows],
                         [("XAUUSD", "yfinance")])

    def test_a_market_price_is_not_a_previous_close(self):
        out = _poll_commodities(self, {"regularMarketPrice": 2001.0,
                                       "previousClose": 2000.0})
        self.assertEqual(out.get("fetched"), 1, out)
        self.assertEqual(_rows("poller_previous_close"), [])


class TheExitBookingTests(_Case):

    def test_the_drain_books_at_the_mark(self):
        from bot_program.pending_closes import retry_trade_close
        t = self._row(status="CLOSE_PENDING")
        with H.route_to(H.EtoroTrader({"EURUSD": H.tick("1.0990")},
                                      positions=[])), \
                self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(retry_trade_close(t))
        self.assertEqual([(r.kind, r.ref) for r in _rows()],
                         [("exit_at_mark", f"trade:{t.pk}")])

    def test_the_reconcile_books_an_outside_quote(self):
        from bot_program.reconcile_asset import _close_as_orphan
        t = self._row()
        H.write_live_quote("EURUSD", source="oanda_stream", last="1.0980",
                           clock=self.clock)
        with H.route_to(H.EtoroTrader()), \
                self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(_close_as_orphan(t))
        (row,) = _rows()
        self.assertEqual((row.kind, row.source),
                         ("exit_at_outside_quote", "oanda_stream"))

    def test_the_interim_writers_quote_is_etoros_own_mark(self):
        from bot_program.reconcile_asset import _close_as_orphan
        t = self._row()
        H.write_live_quote("EURUSD", source="etoro", last="1.0980",
                           clock=self.clock)
        with H.route_to(H.EtoroTrader()), \
                self.captureOnCommitCallbacks(execute=True):
            _close_as_orphan(t)
        self.assertEqual([r.kind for r in _rows()], ["exit_at_mark"])

    def test_the_kill_switch_leaves_pending_or_books_unpriced(self):
        from bot_program.engine.kill_switch import _close_asset_trade
        pending = self._row(position_id="p-1")
        with H.route_to(H.EtoroTrader(writes="accept")), \
                self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError):
                _close_asset_trade(pending, self.clock.now)
        bare = self._row(position_id="p-2")
        filled = {"orderId": "c-2", "status": "FILLED", "executedQty": "1"}
        with H.route_to(H.EtoroTrader(writes="accept",
                                      close_answer=filled)), \
                self.captureOnCommitCallbacks(execute=True):
            _close_asset_trade(bare, self.clock.now)
        self.assertEqual(sorted((r.kind, r.ref) for r in _rows()), [
            ("exit_close_pending", f"trade:{pending.pk}"),
            ("exit_unpriced", f"trade:{bare.pk}")])

    def test_a_broker_fill_and_a_paper_row_are_no_harm(self):
        from bot_program.pending_closes import (_finalise_closed,
                                                resolve_exit_fill)
        t = self._row(status="CLOSE_PENDING")
        fill = resolve_exit_fill(t, {"status": "FILLED", "executedQty": "1",
                                     "avgPrice": "1.0995"},
                                 mark=Decimal("1.0990"))
        with self.captureOnCommitCallbacks(execute=True):
            _finalise_closed(t, fill=fill, reason="replay")
            p = self._paper_row()
            p.status = "CLOSED"
            p.save()
        self.assertEqual([r.kind for r in _rows()], [])

    def test_a_re_save_of_an_old_booking_is_not_a_booking(self):
        from datetime import timedelta
        t = self._row(status="CLOSED", meta={"exit_fill_source": "mark"})
        type(t).objects.filter(pk=t.pk).update(
            closed_at=self.clock.now - timedelta(days=2))
        t.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            t.save()
        self.assertEqual(_rows(), [])

    def test_a_row_saved_again_is_counted_once(self):
        from bot_program.pending_closes import retry_trade_close
        t = self._row(status="CLOSE_PENDING")
        with H.route_to(H.EtoroTrader({"EURUSD": H.tick("1.0990")},
                                      positions=[])), \
                self.captureOnCommitCallbacks(execute=True):
            retry_trade_close(t)
        t.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            t.save()
            t.save(update_fields=["metadata"])
        self.assertEqual(len(_rows("exit_at_mark")), 1)


# ── 3. the fences: the money path never sees the counter ────────────────

class TheFenceTests(_Case):
    """With the counter's write raising, and with the path's hook itself
    raising, every money path answers exactly as with no counter."""

    def _modes(self, *hooks):
        """(name, a context manager) for: no failure, the write raising,
        each named hook raising."""
        fh = _fh()
        out = [("none", contextlib.nullcontext),
               ("write", lambda: mock.patch(WRITE, side_effect=RuntimeError(
                   "the counter's table is gone")))]
        for hook in hooks:
            out.append((hook, lambda hook=hook: mock.patch.object(
                fh, hook, side_effect=RuntimeError("the hook raises"))))
        return out

    def _same(self, results):
        first = results[0][1]
        for name, got in results[1:]:
            self.assertEqual(got, first, name)

    def test_mark_sanity_verdict_unchanged(self):
        from bot_program import mark_sanity
        H.write_live_quote("EURUSD", source="oanda_stream", last="1.1000",
                           clock=self.clock)
        results = []
        for name, mode in self._modes("on_mark_verdict", "_record"):
            t = self._row()
            bot = SimpleNamespace(cfg=self.cfg, _last_ticks={})
            with mode(), self.captureOnCommitCallbacks(execute=True):
                v = mark_sanity.check(bot, t, 1.0891, None)
            t.refresh_from_db()
            results.append((name, (v, t.metadata["care"].get(
                "mark_suspect", {}).get("why"))))
        self._same(results)
        self.assertFalse(results[0][1][0]["ok"],
                         "a raising hook never flips a verdict")

    def test_the_close_refusal_unchanged(self):
        from bot_program.manual_close import execute_close, preview_close
        results = []
        for name, mode in self._modes("on_close_refused", "_record"):
            t = self._row(position_id=f"p-{name}")
            with mode(), H.route_to(H.EtoroTrader()), \
                    self.captureOnCommitCallbacks(execute=True):
                got = (preview_close(self.owner, t),
                       execute_close(self.owner, t, pin_ok=True))
            t.refresh_from_db()
            results.append((name, (got, t.status)))
        self._same(results)
        self.assertEqual(results[0][1][1], "OPEN")

    def test_the_kill_switch_unchanged(self):
        from bot_program.engine.kill_switch import execute_kill_switch
        from bot_program.models import AssetBotTrade
        results = []
        for name, mode in self._modes("hold", "note_wait",
                                      "on_kill_switch_wait",
                                      "on_exit_saved", "_record"):
            AssetBotTrade.objects.all().delete()
            t = self._row(position_id=f"p-{name}")
            etoro = H.EtoroTrader(writes="accept")
            with mode(), H.route_to(etoro), \
                    self.captureOnCommitCallbacks(execute=True):
                r = execute_kill_switch(self.owner, reason="replay")
            results.append((name, (r["asset_positions_closed"],
                                   len(r["errors"]), H.row_state(t),
                                   etoro.methods)))
        self._same(results)
        self.assertEqual(results[0][1][2]["status"], "CLOSE_PENDING")

    def test_write_quote_unchanged(self):
        from market_data.models import LiveQuote
        from market_data.quotes import write_quote
        inst = H.instrument("AAPL", "stock")
        results = []
        for name, mode in self._modes("on_quote_written", "_record"):
            LiveQuote.objects.filter(instrument=inst).delete()
            with mode(), self.captureOnCommitCallbacks(execute=True):
                ok = write_quote("AAPL", last="200", source="yfinance",
                                 bid="0", ask="201", instrument=inst)
            q = LiveQuote.objects.get(instrument=inst)
            results.append((name, (ok, q.last, q.bid, q.ask, q.source)))
        self._same(results)
        self.assertTrue(results[0][1][0])

    def test_the_poller_unchanged(self):
        """The commodity poller's pass and its write, with Yahoo's
        previous close standing in for a market price (counted)."""
        from market_data.models import LiveQuote
        results = []
        for name, mode in self._modes("on_previous_close",
                                      "on_quote_written", "_record"):
            LiveQuote.objects.all().delete()
            with mode():
                out = _poll_commodities(self, {"previousClose": 2000.0})
            q = LiveQuote.objects.get(instrument__symbol="XAUUSD")
            results.append((name, (out, q.last, q.source)))
        self._same(results)
        self.assertEqual(results[0][1][0].get("fetched"), 1)

    def test_every_booking_unchanged(self):
        from bot_program.pending_closes import retry_trade_close
        from bot_program.reconcile_asset import _close_as_orphan
        results = []
        for name, mode in self._modes("on_exit_saved",
                                      "note_booking_quote", "_record"):
            from market_data.models import LiveQuote
            LiveQuote.objects.all().delete()
            drained = self._row(status="CLOSE_PENDING",
                                position_id=f"d-{name}")
            orphan = self._row(position_id=f"o-{name}")
            with mode(), self.captureOnCommitCallbacks(execute=True):
                with H.route_to(H.EtoroTrader(
                        {"EURUSD": H.tick("1.0990")}, positions=[])):
                    closed = retry_trade_close(drained)
                H.write_live_quote("EURUSD", source="oanda_stream",
                                   last="1.0980", clock=self.clock)
                with H.route_to(H.EtoroTrader()):
                    booked = _close_as_orphan(orphan)
            results.append((name, (closed, H.row_state(drained), booked,
                                   H.row_state(orphan))))
        self._same(results)
        self.assertEqual(results[0][1][1]["status"], "CLOSED")
        self.assertEqual(results[0][1][3]["exit_price"], "1.098")

    def test_one_warning_per_failure_never_more(self):
        from bot_program import mark_sanity
        H.write_live_quote("EURUSD", source="oanda_stream", last="1.1000",
                           clock=self.clock)
        with mock.patch(WRITE, side_effect=RuntimeError("gone")), \
                self.assertLogs("bot_program.feed_harms",
                                level=logging.DEBUG) as logs:
            for _ in range(3):
                with self.captureOnCommitCallbacks(execute=True):
                    mark_sanity.check(SimpleNamespace(cfg=self.cfg),
                                      self._row(), 1.0891, None)
        warnings = [r for r in logs.records if r.levelno >= logging.WARNING]
        self.assertEqual(len(warnings), 1, [r.getMessage() for r in
                                            logs.records])
        self.assertNotIn("1.0891", warnings[0].getMessage())

    def test_a_hook_that_always_raises_is_told_once_per_path(self):
        """The fence on the money path's side tells a failure as the
        counter's own does: one WARNING per path, hook and kind of failure,
        DEBUG after, however often the path runs — and the path never
        raises."""
        from bot_program import mark_sanity
        from bot_program.engine.kill_switch import execute_kill_switch
        from bot_program.manual_close import preview_close
        from bot_program.reconcile_asset import _close_as_orphan
        from market_data.quotes import write_quote
        inst = H.instrument("AAPL", "stock")
        H.write_live_quote("EURUSD", source="oanda_stream", last="1.1000",
                           clock=self.clock)
        rows = iter(range(1, 100))

        def sanity():
            mark_sanity.check(SimpleNamespace(cfg=self.cfg),
                              self._row(position_id=f"s-{next(rows)}"),
                              1.0891, None)

        def refusal():
            with H.route_to(H.EtoroTrader()):
                preview_close(self.owner,
                              self._row(position_id=f"r-{next(rows)}"))

        def quote():
            write_quote("AAPL", last="200", source="yfinance", bid="0",
                        ask="201", instrument=inst)

        def orphan():
            with H.route_to(H.EtoroTrader()):
                _close_as_orphan(self._row(position_id=f"o-{next(rows)}"))

        def sweep():
            self._row(position_id=f"k-{next(rows)}")
            with H.route_to(H.EtoroTrader(writes="accept")):
                execute_kill_switch(self.owner, reason="replay")

        def poll():
            _poll_commodities(self, {"previousClose": 2000.0})

        for hook, path in (("on_mark_verdict", sanity),
                           ("on_close_refused", refusal),
                           ("on_quote_written", quote),
                           ("note_booking_quote", orphan),
                           ("hold", sweep),
                           ("note_wait", sweep),
                           ("on_kill_switch_wait", sweep),
                           ("on_previous_close", poll)):
            with self.subTest(hook=hook), \
                    mock.patch.object(_fh(), hook,
                                      side_effect=CounterBroke()), \
                    _told("bot_program", "market_data") as told:
                for _ in range(3):
                    path()
                said = [r for r in told if "CounterBroke" in r.getMessage()]
                self.assertEqual(
                    [r.levelno for r in said if r.levelno >= logging.WARNING],
                    [logging.WARNING],
                    [(r.name, r.levelname, r.getMessage()) for r in said])
                self.assertGreaterEqual(len(said), 3, "each failure is told")


class TheFenceIsTheOnlyWayInTests(SimpleTestCase):
    """A money path reaches the counters only through bot_program
    .feed_fence, so no path holds a call to them outside the fence."""

    #: who may import the counters themselves: the fence, the app's ready()
    #: (it registers the exit receiver), the report command and the module
    ALLOWED = {"bot_program/feed_fence.py", "bot_program/apps.py",
               "bot_program/feed_harms.py",
               "bot_program/management/commands/feed_harms.py"}

    def test_no_money_module_imports_the_counters(self):
        import ast
        from pathlib import Path

        from django.conf import settings
        base = Path(settings.BASE_DIR)
        hits, seen = [], 0
        for tree in ("bot_program", "market_data", "portfolio", "brain",
                     "ai_agents", "core"):
            for path in (base / tree).rglob("*.py"):
                rel = str(path.relative_to(base)).replace("\\", "/")
                if "/migrations/" in rel or rel in self.ALLOWED:
                    continue
                seen += 1
                for node in ast.walk(ast.parse(path.read_text("utf-8"))):
                    if isinstance(node, ast.ImportFrom):
                        mod = node.module or ""
                        names = {a.name for a in node.names}
                        if (mod.endswith("feed_harms")
                                or ("feed_harms" in names
                                    and (mod in ("", "bot_program")
                                         or node.level))):
                            hits.append(f"{rel}:{node.lineno}")
                    elif isinstance(node, ast.Import):
                        if any(a.name.endswith("feed_harms")
                               for a in node.names):
                            hits.append(f"{rel}:{node.lineno}")
        self.assertGreater(seen, 300)
        self.assertEqual(hits, [], "call the counters through "
                                   "bot_program.feed_fence.count")


class TheTransactionTests(_Case):
    """The counter's row is never inside the money path's transaction."""

    def test_a_rolled_back_booking_leaves_no_harm_row(self):
        t = self._row()
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    t.status = "CLOSED"
                    t.exit_price = Decimal("1.0990")
                    t.metadata = {**t.metadata, "exit_fill_source": "mark"}
                    t.save()
                    raise RuntimeError("the booking fails after its save")
            except RuntimeError:
                pass
        self.assertEqual(_rows(), [])
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN")

    def test_the_row_is_written_after_the_commit_in_its_own_block(self):
        t = self._row()
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            with transaction.atomic():
                t.status = "CLOSED"
                t.exit_price = Decimal("1.0990")
                t.metadata = {**t.metadata, "exit_fill_source": "mark"}
                t.save()
                self.assertEqual(_rows(), [], "nothing inside the block")
        self.assertEqual(_rows(), [], "nothing before the commit")
        self.assertTrue(callbacks)
        for cb in callbacks:
            cb()
        self.assertEqual([r.kind for r in _rows()], ["exit_at_mark"])

    def test_a_failing_counter_write_never_fails_the_paths_commit(self):
        from bot_program.models import AssetBotTrade
        t = self._row()
        with mock.patch(WRITE, side_effect=RuntimeError("gone")), \
                self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                t.status = "CLOSED"
                t.exit_price = Decimal("1.0990")
                t.metadata = {**t.metadata, "exit_fill_source": "mark"}
                t.save()
        self.assertEqual(AssetBotTrade.objects.get(pk=t.pk).status, "CLOSED")
        self.assertEqual(_rows(), [])


# ── 4. the hooks moved nothing around them ───────────────────────────────

class TheHooksMovedNothingTests(_Case):
    """Pinned on behaviour (2026-11-07, this change's own review: two
    helpers first landed between a function and its decorators): the hooks
    sit inside the paths they watch and move nothing around them. The
    CLOSE paths and the kill switch keep their P0 scope in the eToro
    request budget, and the kill switch its one account read per pass."""

    def test_the_close_paths_keep_their_p0_scope(self):
        from bot_program.engine import etoro_budget
        from bot_program.manual_close import execute_close, preview_close
        seen = []

        class _Spy(H.EtoroTrader):
            def ticker(self_, symbol):
                seen.append(etoro_budget.current())
                return super().ticker(symbol)
        t = self._row()
        with H.route_to(_Spy()), self.captureOnCommitCallbacks(execute=True):
            preview_close(self.owner, t)
            execute_close(self.owner, t, pin_ok=True)
        self.assertEqual(seen, [(etoro_budget.P0, "CLOSE button")] * 2)

    def test_the_kill_switch_keeps_its_scope_and_its_one_read(self):
        from bot_program import etoro_cells
        from bot_program.engine import etoro_budget
        from bot_program.engine.kill_switch import execute_kill_switch
        seen = []

        class _Spy(H.EtoroTrader):
            def close_position(self_, *a, **k):
                seen.append((etoro_budget.current(), etoro_cells.holding()))
                return super().close_position(*a, **k)
        self._row(position_id="p-1")
        with H.route_to(_Spy(writes="accept")), \
                self.captureOnCommitCallbacks(execute=True):
            execute_kill_switch(self.owner, reason="replay")
        self.assertEqual(seen, [((etoro_budget.P0, "kill switch"), True)])
