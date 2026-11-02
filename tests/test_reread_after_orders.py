"""No more fifteen-minute wait: the eToro account is read again after every
order and close the platform books, the sync reads it once per pass, and
the read is dated before its GET (2026-10-31).

The operator: "The 15min etoro refresh is way too long, to operate in a
market (wait 15min to make another trade...)". Before every eToro order
the gate (AssetBot._leverage_headroom) reads the free cash and the used
margin from stored cells. An order since the read is charged at once
(_pledged_since); a close since the read was never credited, so "close
one, then open another" was refused until the next sync.

WHAT THESE TESTS CONFRONT

  * The sync sends ONE aggregate-portfolio GET per account per pass (it
    sent two), and when the cash and the used margin do not answer it
    refreshes neither the equity nor last_sync (pages read current while
    the cells aged).
  * The cells are stamped BEFORE the GET, by the sync and by the re-read:
    a fill whose row lands while the GET is in flight is charged by
    _pledged_since, never counted nowhere; so is one booked less than
    SETTLE_S before a read's stamp (review, 2026-10-31).
  * tasks.refresh_etoro_cells writes the cash cells under one stamp and
    nothing else (not the equity, no /portfolio, no last_sync, no
    history row), keeps the old cells on a failed read, and reads nothing
    with the sync's switch off. The gate dates the equity by its own
    stamp, so a re-read never lifts the hour rule over an old one.
  * etoro_cells paces it: one read starts per account per COALESCE_S,
    and every request is read by one that starts SETTLE_S or more after
    it — a queued read starting sooner is not its read; the ticket's own
    checks inside the send queue none before the order.
  * The hooks: the bot entry booking, AssetBot._close_trade (the tick's
    exits, the care close, the CLOSE button, the funding closes), the
    TAKE TRADE live booking, the pending-close drain, the reconcile's
    venue close and the kill switch ask for it; a paper client or another
    carrier asks nothing.
  * One read per pass: inside the tick, the reconcile, the drain and the
    kill switch the asks are held, and the pass asks ONE read per account
    once it has finished, so the read never runs beside the pass's own
    closes and their proofs (the eToro request budget, 2026-10-31).
  * A pass whose cells did not answer counts as a missed sync, and the
    stall alert counts minutes at the eToro walk's own 300 s; when eToro
    answered the holdings beside them, the alert says the cash and the
    used margin did not answer, never that the broker is unreachable or
    that the keys need re-saving.

Run with:  python manage.py test tests.test_reread_after_orders
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from bot_program.equity_models import BrokerEquityReading
from bot_program.models import EtoroAccount
from tests.test_ticket_checks_like_the_send import _LiveEtoroTicket

TRADER = "bot_program.engine.etoro_client.EtoroTrader"
REFRESH = "bot_program.etoro_cells.request_refresh"
CELLS_ALERT = "bot_program.notifications.notify_broker_cells_unanswered"


def _account(user, *, demo=True, cash="300.00", used="4500.00",
             equity="5000.00", age_s=600):
    """An eToro row whose cells were read `age_s` ago, demo-stamped."""
    acct = EtoroAccount.objects.create(user=user, demo=demo, label="Main",
                                       is_primary_for_stocks=True)
    acct.set_credentials("k", "u")
    at = timezone.now() - timedelta(seconds=age_s)
    acct.last_available_cash = Decimal(cash)
    acct.last_used_margin = Decimal(used)
    acct.last_equity = Decimal(equity)
    acct.last_equity_currency = "USD"
    acct.last_equity_at = at
    acct.last_margin_at = at
    acct.last_margin_world = "demo" if demo else "live"
    acct.last_sync = at
    acct.broker_positions = [{"symbol": "OLD"}]
    acct.broker_positions_at = at
    acct.save()
    return acct


def _components(**on):
    from core.platform_control import PlatformComponent
    for key in ("platform_master", "broker_account_sync"):
        PlatformComponent.objects.update_or_create(
            key=key, defaults={"name": key, "category": "system",
                               "is_enabled": on.get(key, True)})


def _payload(cash=2000.0, used=2800.0, total=5000.0):
    return {"accountCurrency": "USD",
            "accountTotals": {"accountTotalValue": total,
                              "accountAvailableCash": cash,
                              "accountTotalUsedMargin": used}}


def _sync(client):
    from bot_program.tasks import sync_etoro_accounts
    with patch(TRADER, return_value=client):
        return sync_etoro_accounts.__wrapped__.__wrapped__()


def _live_cfg(user, asset_class="stock", name="RR"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode="live",
        symbols=["AAPL"], capital=Decimal("10000"), enabled=True,
        base_currency="USD")


def _row(cfg, **kw):
    from bot_program.models import AssetBotTrade
    d = dict(config=cfg, asset_class=cfg.asset_class, symbol="AAPL",
             side="BUY", qty=Decimal("4"), entry_price=Decimal("100"),
             stop_loss=Decimal("98"), take_profit=Decimal("104"),
             status="OPEN", paper=False,
             metadata={"broker": "etoro", "broker_env": "paper"})
    d.update(kw)
    return AssetBotTrade.objects.create(**d)


class TheSyncReadsTheAccountOnceTests(TestCase):

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("rr_sync", password="x")
        self.acct = _account(self.user)

    def _real(self, routes):
        from tests.test_etoro_client import _client
        t, fake = _client(routes, env="demo")
        return t, fake

    def test_one_aggregate_get_per_pass_serves_the_equity_and_the_cells(self):
        t, fake = self._real([
            ("GET", "aggregate-portfolio", 200, _payload()),
            ("GET", "portfolio", 200, {"clientPortfolio": {"positions": []}}),
        ])
        out = _sync(t)
        aggregate = [c for c in fake.calls
                     if c[0] == "GET" and "aggregate-portfolio" in c[1]]
        self.assertEqual(len(aggregate), 1, [c[1] for c in fake.calls])
        self.assertEqual(out["stored"], 1)
        acct = EtoroAccount.objects.get(pk=self.acct.pk)
        self.assertEqual(acct.last_available_cash, Decimal("2000.00"))
        self.assertEqual(acct.last_used_margin, Decimal("2800.00"))
        self.assertEqual(acct.last_equity, Decimal("5000.00"))
        self.assertEqual(acct.last_margin_at, acct.last_equity_at)
        self.assertEqual(acct.last_margin_world, "demo")

    def test_a_failed_aggregate_read_refreshes_neither_equity_nor_last_sync(self):
        """The skeptic's case: the cells did not answer, and last_sync must
        not make the pages read current while they age."""
        before = EtoroAccount.objects.get(pk=self.acct.pk)
        t, fake = self._real([
            ("GET", "aggregate-portfolio", 503, {}),
            ("GET", "portfolio", 200, {"clientPortfolio": {"positions": []}}),
        ])
        with patch("time.sleep"):
            out = _sync(t)
        acct = EtoroAccount.objects.get(pk=self.acct.pk)
        self.assertEqual(acct.last_sync, before.last_sync)
        self.assertEqual(acct.last_equity_at, before.last_equity_at)
        self.assertEqual(acct.last_equity, before.last_equity)
        self.assertEqual(acct.last_margin_at, before.last_margin_at)
        self.assertEqual(acct.last_available_cash, before.last_available_cash)
        # the holdings answered and keep their own stamp
        self.assertEqual(acct.broker_positions, [])
        self.assertNotEqual(acct.broker_positions_at,
                            before.broker_positions_at)
        self.assertEqual(out["cells_unread"], 1)
        self.assertEqual(out["status"], "warning")
        self.assertIn("no cash / used margin", out["reason"])
        self.assertFalse(BrokerEquityReading.objects.filter(
            broker="etoro", account_pk=self.acct.pk).exists())

    def test_a_double_whose_cells_fail_leaves_the_equity_alone_too(self):
        """An adapter without the one-read method: net_liquidation answers,
        margin_cells answers None (a failed read) — the equity is not
        written alone. A double that states no cells at all still writes
        the equity (tests.test_etoro_leverage, the cells left None)."""
        before = EtoroAccount.objects.get(pk=self.acct.pk)
        c = MagicMock(spec=["net_liquidation", "broker_portfolio",
                            "margin_cells", "demo"])
        c.net_liquidation.return_value = (2000.0, "USD")
        c.broker_portfolio.return_value = []
        c.margin_cells.return_value = None
        c.demo = True
        _sync(c)
        acct = EtoroAccount.objects.get(pk=self.acct.pk)
        self.assertEqual(acct.last_equity, before.last_equity)
        self.assertEqual(acct.last_sync, before.last_sync)

    def test_the_cells_are_stamped_before_the_read(self):
        """A fill whose row lands while the GET is in flight is not in the
        payload. Stamped after the read, it was in neither the cells nor
        _pledged_since; stamped before, it is charged."""
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _live_cfg(self.user)

        def read_while_a_row_lands():
            _row(cfg)                        # 4 x 100 at 1x: 400 of margin
            return (5000.0, "USD")

        c = MagicMock(spec=["net_liquidation", "broker_portfolio",
                            "margin_cells", "demo"])
        c.net_liquidation.side_effect = read_while_a_row_lands
        c.broker_portfolio.return_value = []
        c.margin_cells.return_value = {"available_cash": 2000.0,
                                       "used_margin": 2800.0,
                                       "currency": "USD"}
        c.demo = True
        _sync(c)
        acct = EtoroAccount.objects.get(pk=self.acct.pk)
        bot = StockBot(cfg)
        self.assertEqual(bot._pledged_since(acct.last_margin_at, "etoro"),
                         400.0)


class TheReReadTests(TestCase):

    def setUp(self):
        cache.clear()
        _components()
        self.user = User.objects.create_user("rr_read", password="x")
        self.acct = _account(self.user)

    def _run(self, client):
        from bot_program.tasks import refresh_etoro_cells
        with patch(TRADER, return_value=client) as trader:
            out = refresh_etoro_cells(self.acct.pk, why="test")
        return out, trader

    def _client(self, snapshot):
        c = MagicMock()
        c.demo = True
        if callable(snapshot):
            c.account_snapshot.side_effect = snapshot
        else:
            c.account_snapshot.return_value = snapshot
        return c

    def test_one_read_writes_the_cash_cells_and_leaves_the_rest(self):
        """The cash, the used margin and their world, under one stamp; the
        equity and its stamp stay the sync's (the pools that follow the
        account are retuned from it by the sync alone)."""
        before = EtoroAccount.objects.get(pk=self.acct.pk)
        c = self._client({"reading": (5010.0, "USD"),
                          "margin": {"available_cash": 2000.0,
                                     "used_margin": 2800.0,
                                     "currency": "USD"}})
        t0 = timezone.now()
        out, trader = self._run(c)
        self.assertTrue(out["read"], out)
        self.assertEqual(trader.call_args.kwargs.get("env"), "demo")
        acct = EtoroAccount.objects.get(pk=self.acct.pk)
        self.assertEqual(acct.last_available_cash, Decimal("2000.00"))
        self.assertEqual(acct.last_used_margin, Decimal("2800.00"))
        self.assertGreaterEqual(acct.last_margin_at, t0)
        self.assertEqual(acct.last_margin_world, "demo")
        # the equity is the sync's, with its own age
        self.assertEqual(acct.last_equity, before.last_equity)
        self.assertEqual(acct.last_equity_at, before.last_equity_at)
        # and so are last_sync, the holdings and the history
        self.assertEqual(acct.last_sync, before.last_sync)
        self.assertEqual(acct.broker_positions, [{"symbol": "OLD"}])
        self.assertEqual(acct.broker_positions_at, before.broker_positions_at)
        self.assertFalse(BrokerEquityReading.objects.exists())
        c.broker_portfolio.assert_not_called()
        c.net_liquidation.assert_not_called()

    def test_a_re_read_never_hides_a_sync_that_stopped(self):
        """A pool that follows the account stops opening when the equity
        reading is over an hour old (capital_truth.tracking_freeze_reason):
        the sync retunes those pools from that reading and the re-read
        does not, so a re-read must not make the reading look fresh."""
        from bot_program.capital_truth import tracking_freeze_reason
        EtoroAccount.objects.filter(pk=self.acct.pk).update(
            last_equity_at=timezone.now() - timedelta(hours=2))
        cfg = _live_cfg(self.user)
        cfg.extras = {"capital_tracks_broker": True}
        cfg.save(update_fields=["extras"])

        def freeze():
            # a fresh user: the one in hand caches the account it created
            return tracking_freeze_reason(
                User.objects.get(pk=self.user.pk), cfg) or ""

        self.assertIn("2.0h old", freeze())
        out, _ = self._run(self._client(
            {"reading": (5010.0, "USD"),
             "margin": {"available_cash": 2000.0, "used_margin": 2800.0,
                        "currency": "USD"}}))
        self.assertTrue(out["read"], out)
        self.assertIn("2.0h old", freeze())

    def test_a_failed_read_keeps_the_old_cells_and_their_age(self):
        before = EtoroAccount.objects.get(pk=self.acct.pk)
        out, _ = self._run(self._client(None))
        self.assertFalse(out["read"])
        acct = EtoroAccount.objects.get(pk=self.acct.pk)
        for f in ("last_available_cash", "last_used_margin", "last_margin_at",
                  "last_equity", "last_equity_at"):
            self.assertEqual(getattr(acct, f), getattr(before, f), f)

    def test_the_sync_switch_off_reads_nothing(self):
        _components(broker_account_sync=False)
        out, trader = self._run(self._client(None))
        trader.assert_not_called()
        self.assertIn("off", out["skipped"])

    def test_a_fill_landing_during_the_re_read_is_charged(self):
        """The race, on the re-read: the row is committed while the GET is
        in flight and the payload does not carry it. The gate charges it
        as pledged since the stamp."""
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _live_cfg(self.user)

        def snapshot():
            _row(cfg)                        # 400 of margin, not in it
            return {"reading": (5000.0, "USD"),
                    "margin": {"available_cash": 2000.0,
                               "used_margin": 2800.0, "currency": "USD"}}

        out, _ = self._run(self._client(snapshot))
        self.assertTrue(out["read"], out)
        from bot_program.engine.etoro_client import EtoroTrader
        gate = StockBot(cfg)._cash_gate(EtoroTrader("k", "u", env="demo"),
                                        "AAPL", qty=1.0, price=100.0,
                                        leverage=1)
        self.assertEqual(gate["pledged"], 400.0)
        self.assertEqual(gate["free"], 1600.0)

    def test_a_row_booked_settle_s_before_the_stamp_is_charged_too(self):
        """A read that starts less than SETTLE_S after a booking (another
        booking's, a pass's) may not carry its fill yet: eToro's cells move
        within the second, not at once (review, 2026-10-31). Such a row is
        charged on top of that read — twice, until its own read, when the
        payload did carry it; one booked longer before is the payload's."""
        from bot_program import etoro_cells
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade
        cfg = _live_cfg(self.user)
        stamp = timezone.now()
        just_before = _row(cfg)                    # 400 at 1x
        long_before = _row(cfg, qty=Decimal("1"))  # 100 at 1x
        AssetBotTrade.objects.filter(pk=just_before.pk).update(
            opened_at=stamp - timedelta(seconds=1))
        AssetBotTrade.objects.filter(pk=long_before.pk).update(
            opened_at=stamp - timedelta(seconds=etoro_cells.SETTLE_S + 1))
        self.assertEqual(StockBot(cfg)._pledged_since(stamp, "etoro"), 400.0)


def _snapshot_client(cash, used, total):
    c = MagicMock()
    c.demo = True
    c.account_snapshot.return_value = {
        "reading": (total, "USD"),
        "margin": {"available_cash": cash, "used_margin": used,
                   "currency": "USD"}}
    return c


class TheGateDatesTheEquityTooTests(TestCase):
    """The re-read writes the cells and never the equity (review,
    2026-10-31). The gate's hour rule read the cells' stamp alone while its
    pledge ratio divides by the equity: before the re-read both came from
    one save, after it a re-read lifted "cash reading N h old" over an
    equity of any age (celery beat down, the sync's entry off, a payload
    with no total) — MAX ACCOUNT PLEDGED judged on a stale equity, looser
    on a book that has lost since."""

    def setUp(self):
        cache.clear()
        _components()
        self.user = User.objects.create_user("rr_eq", password="x")
        # the sync has written nothing for three hours: cells AND equity
        self.acct = _account(self.user, cash="300.00", used="1500.00",
                             equity="2000.00", age_s=3 * 3600)
        from portfolio.risk_gate import limits_book
        book = limits_book()
        book.max_pledged_pct = 100
        book.save()
        self.cfg = _live_cfg(self.user)

    def _gate(self, qty=2.5):
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.engine.etoro_client import EtoroTrader
        return StockBot(self.cfg)._cash_gate(
            EtoroTrader("k", "u", env="demo"), "AAPL", qty=qty, price=100.0,
            leverage=1)

    def test_a_re_read_does_not_lift_the_hour_rule_over_an_old_equity(self):
        """The reviewer's proof A: 250 at a 100% ceiling against the stale
        2,000 passed at 87.5%; against the 1,700 the same read carried it
        is 103%."""
        self.assertIn("3.0h old", self._gate()["refusal"])
        from bot_program.tasks import refresh_etoro_cells
        with patch(TRADER, return_value=_snapshot_client(300.0, 1500.0,
                                                         1700.0)):
            self.assertTrue(refresh_etoro_cells(self.acct.pk,
                                                why="ticket")["read"])
        gate = self._gate()
        self.assertLess(gate["age_s"], 60)
        self.assertIn("equity reading 3.0h old", gate["refusal"])
        self.assertIn("only the eToro sync writes it", gate["refusal"])
        self.assertGreater(gate["equity_age_s"], 3 * 3600 - 60)

    def test_an_equity_with_no_reading_time_is_refused(self):
        EtoroAccount.objects.filter(pk=self.acct.pk).update(
            last_margin_at=timezone.now(), last_equity_at=None)
        refusal = self._gate(qty=1.0)["refusal"]
        self.assertIn("equity carries no reading time", refusal)
        self.assertIn("refused", refusal)

    def test_fresh_cells_on_a_fresh_equity_pass(self):
        now = timezone.now()
        EtoroAccount.objects.filter(pk=self.acct.pk).update(
            last_margin_at=now, last_equity_at=now)
        gate = self._gate(qty=1.0)
        self.assertEqual(gate["refusal"], "")
        self.assertLess(gate["equity_age_s"], 60)

    def test_the_cells_own_age_is_still_judged(self):
        """An equity fresher than the cells (a double that states no
        cells writes the equity alone): the cells' sentence, as before."""
        EtoroAccount.objects.filter(pk=self.acct.pk).update(
            last_equity_at=timezone.now())
        self.assertIn("cash reading 3.0h old", self._gate()["refusal"])


class ThePacingTests(TestCase):

    def setUp(self):
        cache.clear()
        _components()
        self.clock = [1000.0]
        p = patch("bot_program.etoro_cells._now",
                  side_effect=lambda: self.clock[0])
        p.start()
        self.addCleanup(p.stop)
        q = patch("bot_program.tasks.refresh_etoro_cells.apply_async")
        self.queued = q.start()
        self.addCleanup(q.stop)

    def test_one_read_per_window_a_queued_read_covers_and_one_trails(self):
        """One read starts per COALESCE_S, and a queued read covers a
        request only when it starts SETTLE_S or more after it (2026-10-31,
        review): a read starting one second after a booking may not carry
        its fill yet, and the booking used to be told it was read."""
        from bot_program import etoro_cells
        settle, window = etoro_cells.SETTLE_S, etoro_cells.COALESCE_S
        lead = etoro_cells.request_refresh(7, why="close")
        self.assertEqual(lead, settle)
        self.assertEqual(self.queued.call_count, 1)
        kw = self.queued.call_args.kwargs
        self.assertEqual(kw["args"], [7])
        self.assertEqual(kw["countdown"], settle)
        self.assertEqual(kw["queue"], "fast")
        # a request SETTLE_S before the queued read starts: that read covers it
        self.assertEqual(etoro_cells.request_refresh(7), settle)
        self.assertEqual(self.queued.call_count, 1)
        # one second later that read starts too soon for it: one more
        # read, COALESCE_S after the queued one
        self.clock[0] += 1
        trail = etoro_cells.request_refresh(7, why="entry")
        self.assertEqual(self.queued.call_count, 2)
        self.assertAlmostEqual(trail, settle - 1 + window + 0.5, places=3)
        self.assertEqual(self.queued.call_args.kwargs["countdown"], trail)
        # the first read starts and the trailing one stays queued: it
        # covers every request up to SETTLE_S before its own start
        self.clock[0] += 2
        etoro_cells.note_read_started(7)
        self.clock[0] += 5
        again = etoro_cells.request_refresh(7, why="close")
        self.assertEqual(self.queued.call_count, 2)
        self.assertAlmostEqual(again, trail - 7, places=3)
        # the trailing read starts: a new window, and an order inside it
        # queues one read at its end
        self.clock[0] += again
        etoro_cells.note_read_started(7)
        self.clock[0] += 5
        nxt = etoro_cells.request_refresh(7, why="entry")
        self.assertEqual(self.queued.call_count, 3)
        self.assertGreaterEqual(nxt, window - 5)
        # another account is paced on its own
        etoro_cells.request_refresh(8, why="close")
        self.assertEqual(self.queued.call_count, 4)

    def test_every_request_is_read_by_one_starting_settle_s_after_it(self):
        """The contract a booking relies on, over a burst of asks (a
        ticket's, a pass's, a close's, the skeptic's 2.9 s): at the moment
        it asks, a read is queued that starts SETTLE_S or more after it;
        and the reads still start COALESCE_S apart."""
        from bot_program import etoro_cells
        settle, window = etoro_cells.SETTLE_S, etoro_cells.COALESCE_S
        starts, begun = [], set()
        for at in (0.0, 0.4, 1.2, 2.5, 2.9, 3.1, 5.0, 19.0, 22.0, 22.8,
                   23.4, 23.6, 40.0, 41.5, 44.2, 60.0, 90.0):
            # the reads due by then start first, as the worker runs them
            for s in sorted(starts):
                if s <= 1000.0 + at and s not in begun:
                    self.clock[0] = s
                    etoro_cells.note_read_started(7)
                    begun.add(s)
            self.clock[0] = 1000.0 + at
            eta = etoro_cells.request_refresh(7, why="entry")
            if self.queued.call_count > len(starts):
                starts.append(self.clock[0]
                              + self.queued.call_args.kwargs["countdown"])
            with self.subTest(at=at):
                self.assertGreaterEqual(eta, settle - 1e-9)
                self.assertTrue(any(s - self.clock[0] >= settle - 1e-9
                                    for s in starts if s not in begun),
                                (at, starts))
        gaps = [b - a for a, b in zip(sorted(starts), sorted(starts)[1:])]
        self.assertTrue(all(g >= window - 1e-9 for g in gaps), gaps)

    def test_two_requests_2_9_s_apart_get_two_reads(self):
        """The skeptic's case: the second request was told 0.1 s and
        nothing more was queued."""
        from bot_program import etoro_cells
        etoro_cells.request_refresh(7, why="close")
        self.clock[0] += 2.9
        eta = etoro_cells.request_refresh(7, why="entry")
        self.assertEqual(self.queued.call_count, 2)
        self.assertGreaterEqual(eta, etoro_cells.SETTLE_S)

    def test_a_read_late_on_its_start_covers_no_request_after_it(self):
        """A queued read past its planned start (a worker running late)
        starts at a moment nobody knows: a request then queues its own."""
        from bot_program import etoro_cells
        etoro_cells.request_refresh(7, why="close")
        self.clock[0] += 5                       # planned at +3, not begun
        late = etoro_cells.request_refresh(7, why="entry")
        self.assertEqual(self.queued.call_count, 2)
        self.assertGreaterEqual(late, etoro_cells.SETTLE_S)

    def test_a_broker_that_cannot_queue_never_raises(self):
        from bot_program import etoro_cells
        self.queued.side_effect = OSError("no broker")
        self.assertIsNone(etoro_cells.request_refresh(9, why="close"))

    def test_a_queue_that_failed_promises_nothing_after_it(self):
        """No read was queued, so no window may stand: the next request
        is not told a read is coming, it queues one."""
        from bot_program import etoro_cells
        self.queued.side_effect = OSError("no broker")
        self.assertIsNone(etoro_cells.request_refresh(9, why="close"))
        self.queued.side_effect = None
        self.clock[0] += 1
        self.assertEqual(etoro_cells.request_refresh(9, why="close"),
                         etoro_cells.SETTLE_S)
        self.assertEqual(self.queued.call_count, 2)

    def test_with_the_sync_off_nothing_is_queued_or_promised(self):
        """The re-read runs under the sync's switches; with them off it
        would read nothing, so the ticket must not say a read lands."""
        from bot_program import etoro_cells
        _components(broker_account_sync=False)
        self.assertIsNone(etoro_cells.request_refresh(7, why="ticket"))
        self.queued.assert_not_called()
        _components(broker_account_sync=True, platform_master=False)
        self.assertIsNone(etoro_cells.request_refresh(7, why="ticket"))
        self.queued.assert_not_called()


class TheHooksTests(TestCase):
    """Every order and close the platform books asks the re-read once the
    booking commits; a paper client or another carrier asks nothing."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("rr_hooks", password="x")
        self.acct = _account(self.user)
        self.cfg = _live_cfg(self.user)

    def _etoro_client(self):
        from bot_program.engine.etoro_client import EtoroTrader
        return EtoroTrader("k", "u", env="demo")

    def test_the_client_hook_asks_for_etoro_only(self):
        from bot_program import etoro_cells
        from bot_program.engine.paper_trader import PaperTrader
        with patch(REFRESH) as asked, \
                self.captureOnCommitCallbacks(execute=True):
            etoro_cells.refresh_for_client(self.user, self._etoro_client(),
                                           why="entry")
        asked.assert_called_once_with(self.acct.pk, why="entry")
        for other in (MagicMock(), PaperTrader.__new__(PaperTrader)):
            with patch(REFRESH) as asked, \
                    self.captureOnCommitCallbacks(execute=True):
                etoro_cells.refresh_for_client(self.user, other, why="entry")
            asked.assert_not_called()

    def test_nothing_is_asked_before_the_booking_commits(self):
        from bot_program import etoro_cells
        with patch(REFRESH) as asked, \
                self.captureOnCommitCallbacks(execute=False) as hooks:
            etoro_cells.refresh_for_client(self.user, self._etoro_client(),
                                           why="entry")
        asked.assert_not_called()
        self.assertEqual(len(hooks), 1)

    def test_a_close_through_the_engine_asks(self):
        """AssetBot._close_trade: the tick's stop, target and time exits,
        the care close, the CLOSE button and the funding closes."""
        from bot_program.asset_engine.base import AssetBot
        from bot_program.asset_engine.stock_bot import StockBot
        trade = _row(self.cfg)
        client = MagicMock()
        client.market_order.return_value = {"orderId": "1"}
        with patch.object(AssetBot, "_reread_account_soon") as hook:
            ok = StockBot(self.cfg)._close_trade(trade, Decimal("104"),
                                                 client, reason="TP")
        self.assertTrue(ok)
        hook.assert_called_once_with(client, why="close")

    def test_a_close_that_failed_at_the_broker_asks_nothing(self):
        from bot_program.asset_engine.base import AssetBot
        from bot_program.asset_engine.stock_bot import StockBot
        trade = _row(self.cfg)
        client = MagicMock()
        client.market_order.side_effect = RuntimeError("broker down")
        with patch.object(AssetBot, "_reread_account_soon") as hook:
            StockBot(self.cfg)._close_trade(trade, Decimal("104"), client,
                                            reason="SL")
        hook.assert_not_called()

    def test_a_bot_entry_booking_asks(self):
        from bot_program.asset_engine.base import AssetBot
        from bot_program.asset_engine.stock_bot import StockBot
        from tests.test_desk_seam import _client as _mock_client
        from tests.test_execution_trust import _instrument, _signal
        _instrument("AAPL")
        _signal(_instrument("AAPL"), rule="rr_rule")
        client = _mock_client("100.00")
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client), \
                patch.object(AssetBot, "_reread_account_soon") as hook:
            res = StockBot(self.cfg).scan_symbol("AAPL")
        self.assertIsNotNone(res)
        hook.assert_called_once_with(client, why="entry")

    def test_the_pending_close_drain_asks(self):
        from bot_program.pending_closes import _finalise_closed
        trade = _row(self.cfg, status="CLOSE_PENDING")
        with patch(REFRESH) as asked, \
                self.captureOnCommitCallbacks(execute=True):
            _finalise_closed(trade, fill={"price": Decimal("101"),
                                          "metadata": {}},
                             reason="retry")
        asked.assert_called_once_with(self.acct.pk, why="close retry")

    def test_the_reconciles_venue_close_asks(self):
        from bot_program.reconcile_asset import _close_as_orphan
        trade = _row(self.cfg)
        with patch(REFRESH) as asked, \
                patch("bot_program.engine.broker_router.client_for_symbol",
                      return_value=MagicMock(closing_fill=None)), \
                self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(_close_as_orphan(trade))
        asked.assert_called_once_with(self.acct.pk, why="venue close")

    def test_a_paper_row_of_no_carrier_asks_nothing(self):
        from bot_program import etoro_cells
        trade = _row(self.cfg, paper=True, metadata={})
        with patch(REFRESH) as asked, \
                self.captureOnCommitCallbacks(execute=True):
            etoro_cells.refresh_for_trade(trade, why="close")
        asked.assert_not_called()
        # another broker's row neither
        trade = _row(self.cfg, metadata={"broker": "saxo"})
        with patch(REFRESH) as asked, \
                self.captureOnCommitCallbacks(execute=True):
            etoro_cells.refresh_for_trade(trade, why="close")
        asked.assert_not_called()

    def test_the_sources_hook_every_close_path(self):
        """Pinned on the call sites, beside the behaviour above: the kill
        switch's close books its own exits and asks too."""
        import inspect

        from bot_program.engine import kill_switch
        self.assertIn('etoro_cells.refresh_for_trade(trade, why="kill switch")',
                      inspect.getsource(kill_switch._close_asset_trade))


class TheTakeTradeLiveBookingAsksTests(TestCase):
    """The TAKE TRADE live booking on the real eToro adapter asks the
    re-read; the same lane on a MagicMock carrier asks nothing."""

    def setUp(self):
        from tests.test_etoro_client import _clear_eligibility
        from tests.test_take_trade_live import (_arm_live, _components_on,
                                                _quote)
        cache.clear()
        self.user = User.objects.create_user("rr_ticket", password="x")
        self.inst = _quote("BTCUSD", 60000)
        _components_on()
        self.cfg = _arm_live(self.user)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)
        p = patch("bot_program.asset_engine.base.ETORO_PROVEN",
                  frozenset({"crypto"}))
        p.start()
        self.addCleanup(p.stop)

    def test_the_live_booking_asks_and_a_mock_carrier_does_not(self):
        from bot_program.manual_trade import execute_take_trade
        from tests.test_etoro_client import ELIG_BTC, SEARCH_BTC, _client
        from tests.test_etoro_leverage import _account as _cells
        from tests.test_take_trade_live import (ROUTER, _fake_live_client,
                                                _filled_response, _signal)
        acct = _cells(self.user, cash=100000)
        t, _fake = _client([SEARCH_BTC, ELIG_BTC])
        with patch.object(t, "ticker", return_value={"lastPrice": "60000"}), \
                patch.object(t, "market_order",
                             return_value=_filled_response()), \
                patch(ROUTER, return_value=t), patch(REFRESH) as asked, \
                self.captureOnCommitCallbacks(execute=True):
            out = execute_take_trade(self.user, _signal(self.inst),
                                     pin_ok=True)
        self.assertTrue(out.get("ok"), out)
        self.assertIn(((acct.pk,), {"why": "take trade"}),
                      [(c.args, c.kwargs) for c in asked.call_args_list])
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(config=self.cfg).delete()
        with patch(ROUTER, return_value=_fake_live_client()), \
                patch(REFRESH) as asked, \
                self.captureOnCommitCallbacks(execute=True):
            out = execute_take_trade(self.user, _signal(self.inst),
                                     pin_ok=True)
        self.assertTrue(out.get("ok"), out)
        self.assertNotIn("take trade", [c.kwargs.get("why")
                                        for c in asked.call_args_list])


class TheBookingIsReadSettleSAfterItTests(_LiveEtoroTicket):
    """The TAKE TRADE booking on the real eToro adapter, the pacing clock
    moved by hand (review, 2026-10-31): the read that covers the booking
    starts SETTLE_S or more after it. _execute's own checks (the
    concentration probe and the preview under the lock) asked a read when
    the cells were over a minute old, SETTLE_S before the order left; the
    booking found it queued and was read a second after its fill."""

    username = "rr_settle"

    def _drive(self, *, age_s, order_s, before=None):
        from bot_program import etoro_cells
        from bot_program.manual_trade import execute_take_trade
        from tests.test_take_trade_live import (ROUTER, _filled_response,
                                                _signal)
        _components()
        acct = self._cells(cash=100000, used=0, equity=100000, age_s=age_s)
        t, _ = self._etoro()
        clock = [1000.0]
        events = []

        def order(*a, **k):
            events.append(("sent", clock[0]))
            clock[0] += order_s                # the POST and its fill poll
            events.append(("booked", clock[0]))
            return _filled_response()

        with patch("bot_program.etoro_cells._now",
                   side_effect=lambda: clock[0]), \
                patch("bot_program.tasks.refresh_etoro_cells.apply_async") \
                as queued, \
                patch.object(t, "market_order", side_effect=order), \
                patch(ROUTER, return_value=t), \
                self.captureOnCommitCallbacks(execute=True):
            if before is not None:
                clock[0] = 1000.0 + before
                etoro_cells.request_refresh(acct.pk, why="close")
                clock[0] = 1000.0
            out = execute_take_trade(self.user, _signal(self.inst),
                                     pin_ok=True)
        reads = []
        for c in queued.call_args_list:
            reads.append({"why": c.kwargs["kwargs"]["why"],
                          "countdown": c.kwargs["countdown"]})
        # each read's planned start, on the clock as it was when it was asked
        return out, dict(events), reads, queued

    def test_the_tickets_own_checks_queue_no_read_before_the_order(self):
        from bot_program import etoro_cells
        out, at, reads, _ = self._drive(age_s=600, order_s=2.0)
        self.assertTrue(out.get("ok"), out)
        self.assertEqual([r["why"] for r in reads], ["take trade"], reads)
        # asked once the booking committed, SETTLE_S before its read
        self.assertEqual(reads[0]["countdown"], etoro_cells.SETTLE_S)
        self.assertEqual(at["booked"], 1002.0)

    def test_a_booking_just_before_a_queued_read_gets_a_read_after_it(self):
        """A close's read was queued half a second before the booking: it
        is not the booking's read; one more is queued, SETTLE_S or more
        after the booking."""
        from bot_program import etoro_cells
        out, at, reads, queued = self._drive(age_s=30, order_s=2.0,
                                             before=-0.5)
        self.assertTrue(out.get("ok"), out)
        self.assertEqual([r["why"] for r in reads], ["close", "take trade"],
                         reads)
        # the close's read starts 0.5 s after the booking; the booking's
        # own starts COALESCE_S after it
        close_starts = 999.5 + reads[0]["countdown"]
        self.assertLess(close_starts - at["booked"], etoro_cells.SETTLE_S)
        own_starts = at["booked"] + reads[1]["countdown"]
        self.assertGreaterEqual(own_starts - at["booked"],
                                etoro_cells.SETTLE_S)
        self.assertGreaterEqual(own_starts - close_starts,
                                etoro_cells.COALESCE_S)


class OneReadPerPassTests(TestCase):
    """The request budget's rule for this re-read: a pass that books
    several closes (the tick's exits, the reconcile's venue closes, the
    drain, the kill switch) asks ONE read per account once it has
    finished, never one per close inside it, so the read never runs beside
    the pass's own closes and their proofs."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("rr_pass", password="x")
        self.acct = _account(self.user)
        self.cfg = _live_cfg(self.user)

    def test_the_closes_of_a_pass_ask_one_read_when_it_ends(self):
        from bot_program import etoro_cells
        rows = [_row(self.cfg) for _ in range(3)]
        with patch(REFRESH) as asked:
            with etoro_cells.one_read_per_pass():
                self.assertTrue(etoro_cells.holding())
                with self.captureOnCommitCallbacks(execute=True):
                    for r in rows:
                        etoro_cells.refresh_for_trade(r, why="close")
                # the bookings committed: still nothing while the pass runs
                asked.assert_not_called()
            asked.assert_called_once_with(self.acct.pk, why="close +2 more")
        self.assertFalse(etoro_cells.holding())

    def test_a_nested_pass_waits_for_the_outer_and_accounts_stay_apart(self):
        from bot_program import etoro_cells
        other = User.objects.create_user("rr_pass2", password="x")
        acct2 = _account(other)
        cfg2 = _live_cfg(other, name="RR2")
        with patch(REFRESH) as asked:
            with etoro_cells.one_read_per_pass():
                with etoro_cells.one_read_per_pass():
                    with self.captureOnCommitCallbacks(execute=True):
                        etoro_cells.refresh_for_trade(_row(self.cfg),
                                                      why="close")
                        etoro_cells.refresh_for_trade(_row(cfg2),
                                                      why="venue close")
                asked.assert_not_called()
            self.assertEqual(sorted(c.args[0] for c in asked.call_args_list),
                             sorted([self.acct.pk, acct2.pk]))
            self.assertEqual(asked.call_count, 2)

    def test_a_pass_that_raises_still_asks_for_what_it_booked(self):
        from bot_program import etoro_cells
        with patch(REFRESH) as asked:
            with self.assertRaises(RuntimeError):
                with etoro_cells.one_read_per_pass():
                    with self.captureOnCommitCallbacks(execute=True):
                        etoro_cells.refresh_for_trade(_row(self.cfg),
                                                      why="close")
                    raise RuntimeError("the pass broke")
        asked.assert_called_once_with(self.acct.pk, why="close")
        self.assertFalse(etoro_cells.holding())

    def test_outside_a_pass_a_close_asks_at_once(self):
        from bot_program import etoro_cells
        with patch(REFRESH) as asked, \
                self.captureOnCommitCallbacks(execute=True):
            etoro_cells.refresh_for_trade(_row(self.cfg), why="close")
        asked.assert_called_once_with(self.acct.pk, why="close")

    def test_every_pass_holds_its_asks(self):
        """The tick (the fleet pass and one config's tick), the reconcile
        (every user, and one), the pending-close drain and the kill
        switch: what each does inside runs with the asks held."""
        from bot_program import etoro_cells
        from bot_program.asset_engine import runner
        from bot_program import pending_closes, reconcile_asset
        from bot_program.engine import kill_switch

        seen = []

        def note(*a, **k):
            seen.append(etoro_cells.holding())
            return {}

        def note_and_fail(*a, **k):
            seen.append(etoro_cells.holding())
            raise RuntimeError("the venue did not answer")

        def note_unclaimed(pk):
            seen.append(etoro_cells.holding())
            return None                     # somebody else holds the row

        def check(name, call):
            seen.clear()
            with self.subTest(name):
                try:
                    call()
                except RuntimeError:
                    pass
                self.assertEqual(seen[:1], [True], seen)
                self.assertFalse(etoro_cells.holding())

        with patch.object(runner, "_manage_braked_pass", side_effect=note), \
                patch.object(runner, "_manage_stopped_paper_pass",
                             return_value={}), \
                patch.object(runner, "_run_all_legacy", return_value={}), \
                patch("bot_program.capital_desk.is_desk_enabled",
                      return_value=False):
            check("the fleet tick", runner.run_all_asset_bots)
        bot = MagicMock()
        bot.tick.side_effect = note
        with patch.object(runner, "make_bot", return_value=bot):
            check("one config's tick",
                  lambda: runner.run_asset_bot_tick(self.cfg.id))
        with patch.object(reconcile_asset, "reconcile_user",
                          side_effect=note), \
                patch.object(reconcile_asset, "reconcile_unknown_positions",
                             return_value={}):
            check("the reconcile", reconcile_asset.reconcile_all_users)
        row = _row(self.cfg)
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   side_effect=note_and_fail):
            check("one user's reconcile",
                  lambda: reconcile_asset.reconcile_user(self.user))
        row.status = "CLOSE_PENDING"
        row.save(update_fields=["status"])
        with patch.object(pending_closes, "_claim_for_retry",
                          side_effect=note_unclaimed):
            check("the drain", pending_closes.retry_all_pending_closes)
        with patch.object(kill_switch, "_close_asset_trade",
                          side_effect=note), \
                patch.object(kill_switch, "_push_close_event"):
            check("the kill switch",
                  lambda: kill_switch.execute_kill_switch(user=self.user,
                                                          reason="test"))


class AMissedCellsPassTests(TestCase):
    """A pass whose cash and used margin did not answer refreshes neither
    the equity nor last_sync (above), and counts as a missed sync: three
    such passes running raise the stall alert, the cash cells being what
    the order gate reads. A good pass clears the count."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("rr_miss", password="x")
        self.acct = _account(self.user)

    def _double(self, *, cells_answer):
        c = MagicMock(spec=["account_snapshot", "broker_portfolio", "demo"])
        c.demo = True
        c.broker_portfolio.return_value = []
        c.account_snapshot.return_value = (
            {"reading": (5000.0, "USD"),
             "margin": {"available_cash": 2000.0, "used_margin": 2800.0,
                        "currency": "USD"}} if cells_answer else None)
        return c

    def test_three_passes_without_cells_raise_the_stall_alert(self):
        """The cells alert, not the unreachable one: eToro answered the
        holdings beside them (review, 2026-10-31)."""
        with patch("bot_program.notifications.notify_broker_unreachable",
                   return_value=True) as unreachable, \
                patch(CELLS_ALERT, return_value=True) as alert:
            for _ in range(2):
                _sync(self._double(cells_answer=False))
            alert.assert_not_called()
            _sync(self._double(cells_answer=False))
        alert.assert_called_once()
        unreachable.assert_not_called()
        self.assertEqual(alert.call_args.kwargs["misses"], 3)
        self.assertEqual(alert.call_args.kwargs["broker"], "etoro")
        self.assertTrue(alert.call_args.kwargs["holdings_answered"])

    def test_a_good_pass_clears_the_count(self):
        with patch("bot_program.notifications.notify_broker_unreachable",
                   return_value=True) as unreachable, \
                patch(CELLS_ALERT, return_value=True) as alert:
            _sync(self._double(cells_answer=False))
            _sync(self._double(cells_answer=False))
            _sync(self._double(cells_answer=True))
            _sync(self._double(cells_answer=False))
            _sync(self._double(cells_answer=False))
        alert.assert_not_called()
        unreachable.assert_not_called()

    def test_the_cells_alert_says_what_happened_and_no_keys(self):
        """The reviewer's words: "broker unreachable for 3 syncs running",
        "re-save them on /brokers/", "Equity and holdings on every page are
        showing their last reading" — while /portfolio answered on the same
        keys and the holdings were just written. It says now that the cash
        and the used margin did not answer, how old the cells every eToro
        order is judged on are, and nothing about the keys."""
        from bot_program import notifications
        with patch.object(notifications, "dispatch_notification",
                          return_value=True) as sent, \
                self.assertLogs("bot_program.tasks", level="WARNING") as logs:
            for _ in range(3):
                _sync(self._double(cells_answer=False))
        sent.assert_called_once()
        kw = sent.call_args.kwargs
        words = " ".join([kw["title"], kw["body"]]
                         + kw["row_data"]["items"])
        self.assertIn("Main: eToro answered no cash or used margin for 3 "
                      "syncs running", kw["title"])
        self.assertIn("the holdings answered", kw["body"])
        self.assertIn("every eToro order is judged on", kw["body"])
        self.assertIn("10 min old", kw["body"])
        for wrong in ("unreachable", "re-save", "Re-save",
                      "Equity and holdings on every page"):
            self.assertNotIn(wrong, words)
        miss_lines = [m for m in logs.output if "consecutive miss" in m]
        self.assertEqual(len(miss_lines), 3, logs.output)
        for line in miss_lines:
            self.assertIn("answered no cash / used margin", line)
            self.assertNotIn("no equity AND no holdings", line)
            self.assertNotIn("Re-save the keys", line)

    def test_a_run_with_a_pass_that_answered_nothing_stays_unreachable(self):
        """A pass where neither read answered is the unreachable alert's,
        keys and all, whatever the other passes of the run were."""
        nothing = MagicMock(spec=["account_snapshot", "broker_portfolio",
                                  "demo"])
        nothing.demo = True
        nothing.account_snapshot.return_value = None
        nothing.broker_portfolio.return_value = None
        with patch("bot_program.notifications.notify_broker_unreachable",
                   return_value=True) as unreachable, \
                patch(CELLS_ALERT, return_value=True) as cells:
            _sync(self._double(cells_answer=False))
            _sync(nothing)
            _sync(self._double(cells_answer=False))
        unreachable.assert_called_once()
        cells.assert_not_called()
        self.assertEqual(unreachable.call_args.kwargs["misses"], 3)


class TheMinutesFollowEachWalkTests(TestCase):
    """The stall alert said "since {misses x 15} minutes ago" for every
    broker: at the eToro walk's 300 s, three missed passes are fifteen
    minutes, not forty-five. The Treasury's "the sync runs every 15" is
    each walk's own figure too."""

    def setUp(self):
        self.user = User.objects.create_user("rr_min", password="x")

    def _alert(self, broker):
        from bot_program import notifications
        with patch.object(notifications, "dispatch_notification",
                          return_value=True) as d:
            notifications.notify_broker_unreachable(
                self.user, label="Main", host="api", port=0, misses=3,
                broker=broker)
        return d.call_args.kwargs

    def test_the_alert_counts_each_walks_beat(self):
        from bot_program.broker_vision import sync_minutes
        self.assertEqual(sync_minutes("etoro"), 5)
        self.assertEqual(sync_minutes("ibkr"), 15)
        self.assertEqual(sync_minutes("saxo"), 15)
        kw = self._alert("etoro")
        self.assertIn("since 15 minutes ago", kw["body"])
        self.assertIn("Silent for 3 syncs running (about 15 minutes)",
                      kw["row_data"]["items"])
        kw = self._alert("ibkr")
        self.assertIn("since 45 minutes ago", kw["body"])
        self.assertIn("Silent for 3 syncs running (about 45 minutes)",
                      kw["row_data"]["items"])

    def test_an_unreadable_beat_says_fifteen(self):
        from bot_program.broker_vision import sync_minutes
        self.assertEqual(sync_minutes("nobody"), 15)

    def test_the_switch_and_the_broker_card_say_the_etoro_minutes(self):
        """The broker_account_sync row (/health/) and the broker card's
        hover said "every 15 min" for all three walks."""
        from pathlib import Path

        from django.conf import settings

        from core.platform_control import DEFAULT_COMPONENTS
        row = next(c for c in DEFAULT_COMPONENTS
                   if c["key"] == "broker_account_sync")
        self.assertIn("eToro every 5 min", row["description"])
        card = (Path(settings.BASE_DIR) / "templates" / "_partials"
                / "broker_account.html").read_text(encoding="utf-8")
        self.assertIn("eToro every 5 min", card)
        self.assertNotIn("written by the broker sync every 15 min", card)

    def test_the_treasury_says_the_etoro_walks_minutes(self):
        from bot_program.broker_vision import vision
        _account(self.user, age_s=3 * 3600)
        notes = " ".join(vision(self.user)["notes"])
        self.assertIn("minutes old; the sync runs every 5.", notes)
        self.assertNotIn("every 15.", notes)


class TheCadencesTests(TestCase):
    """The operator asked for both on 2026-10-31: the eToro sync every
    300 s (900 s before) and the reconcile every 5 minutes (*/15 before);
    the re-read rides the fast queue."""

    def test_the_beats_and_the_route(self):
        from celery.schedules import crontab

        from config.celery import app
        beat = app.conf.beat_schedule
        self.assertEqual(beat["sync-etoro-accounts"]["schedule"], 300.0)
        self.assertEqual(beat["reconcile-asset-bot-trades"]["schedule"],
                         crontab(minute="*/5"))
        self.assertEqual(
            app.conf.task_routes["bot_program.tasks.refresh_etoro_cells"],
            {"queue": "fast"})
        # the IBKR walk is not the operator's ask: it keeps its 900 s
        self.assertEqual(beat["sync-broker-account"]["schedule"], 900.0)
