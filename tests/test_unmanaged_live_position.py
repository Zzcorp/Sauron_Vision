"""A real position whose manager has been switched off now says so.

`manage_positions` refuses to manage a LIVE trade when the router hands back
a PaperTrader, and that refusal is right: a stale LiveQuote read through
PaperTrader can cross SL/TP, PaperTrader returns a synthetic FILLED order, and
the row is stamped CLOSED while the real position is still open at the broker.

But the refusal was a `logger.error` and nothing else. So a funded position
could sit with its manager off — for as long as the Gateway stayed
unreachable — and leave no trace anywhere the operator looks. A live IBKR
account re-authenticates with 2FA most days; one missed push overnight is the
whole scenario.

What the alert has to get right is that the honest answer is neither "you are
fine" nor "you are naked". Protective legs are GTC since 9e2bc10, so the stop
and target are still working orders at the broker and outlive the session that
placed them. What stops is everything the platform adds on top: the time stop,
the trailing stop, the break-even move, and the check that notices a
protective leg has vanished.

Run with:  python manage.py test tests.test_unmanaged_live_position
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase


def _user(name="unmanaged_u"):
    return User.objects.create_user(name, password="x")


def _cfg(user, name="LIVEBOT", mode="live"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="stock", name=name, mode=mode,
        symbols=["NVDA"], capital=Decimal("10000"), enabled=True)


def _trade(cfg, *, symbol="NVDA", paper=False):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol=symbol, side="BUY",
        qty=Decimal("5"), entry_price=Decimal("100"),
        stop_loss=Decimal("98"), take_profit=Decimal("104"),
        status="OPEN", paper=paper,
        metadata={"protected": True, "protective_stop_id": "13"})


def _paper_client(cfg=None):
    """The real PaperTrader, because `_is_paper_client` is an isinstance check
    and a MagicMock would slip straight past it."""
    from bot_program.engine.paper_trader import PaperTrader
    return PaperTrader(cfg)


def _live_client():
    client = MagicMock()
    client.ticker.return_value = {"lastPrice": "101", "symbol": "NVDA"}
    client.resting_order_ids.return_value = ["13"]
    client.get_positions.return_value = [{"symbol": "NVDA", "qty": "5"}]
    return client


class TheAlertFiresTests(TestCase):

    def setUp(self):
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        self.user = _user()
        self.cfg = _cfg(self.user)

    def _tick(self, client):
        from bot_program.asset_engine.stock_bot import StockBot
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            return StockBot(self.cfg).manage_positions()

    def _alerts(self):
        from alerts.models import Notification
        return Notification.objects.filter(
            user=self.user, title__icontains="unmanaged")

    def test_a_live_position_on_a_paper_fallback_raises_an_alert(self):
        _trade(self.cfg)
        self._tick(_paper_client())
        self.assertEqual(self._alerts().count(), 1)

    def test_the_row_is_left_OPEN_and_untouched(self):
        """The alert must not have changed the safety behaviour it reports."""
        from bot_program.models import AssetBotTrade
        trade = _trade(self.cfg)
        closed = self._tick(_paper_client())
        trade.refresh_from_db()
        self.assertEqual(closed, 0)
        self.assertEqual(trade.status, "OPEN")
        self.assertTrue((trade.metadata or {}).get("protected"))

    def test_the_symbol_is_named(self):
        _trade(self.cfg)
        self._tick(_paper_client())
        self.assertIn("NVDA", self._alerts().first().title)

    def test_it_says_what_still_protects_the_position(self):
        """"Unmanaged" without this reads as "naked", and an operator who
        believes the stop is gone may flatten a position that did not need
        flattening — at market, in a hurry, by hand."""
        _trade(self.cfg)
        self._tick(_paper_client())
        body = self._alerts().first().body
        self.assertIn("GTC", body)
        self.assertIn("still working", body)

    def test_it_says_what_stopped(self):
        _trade(self.cfg)
        self._tick(_paper_client())
        body = self._alerts().first().body
        for stopped in ("time stop", "trailing stop", "protective leg"):
            self.assertIn(stopped, body)

    def test_it_says_nothing_was_faked(self):
        _trade(self.cfg)
        self._tick(_paper_client())
        body = self._alerts().first().body
        self.assertIn("left OPEN on purpose", body)

    def test_it_points_at_the_gateway_login(self):
        """The most likely cause on a funded account is a missed 2FA push."""
        _trade(self.cfg)
        self._tick(_paper_client())
        self.assertIn("2FA", self._alerts().first().body)


class TheAlertIsQuietWhenItShouldBeTests(TestCase):

    def setUp(self):
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        self.user = _user("quiet_u")

    def _tick(self, cfg, client):
        from bot_program.asset_engine.stock_bot import StockBot
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            return StockBot(cfg).manage_positions()

    def _alerts(self):
        from alerts.models import Notification
        return Notification.objects.filter(
            user=self.user, title__icontains="unmanaged")

    def test_a_PAPER_trade_on_a_paper_client_is_not_an_alert(self):
        """That is the ordinary configuration of this deployment. Alerting on
        it would produce one notification per position per tick forever, which
        is the failure mode that buried a four-day outage."""
        cfg = _cfg(self.user, mode="paper")
        _trade(cfg, paper=True)
        self._tick(cfg, _paper_client())
        self.assertEqual(self._alerts().count(), 0)

    def test_a_reachable_broker_is_not_an_alert(self):
        cfg = _cfg(self.user)
        _trade(cfg)
        self._tick(cfg, _live_client())
        self.assertEqual(self._alerts().count(), 0)

    def test_it_is_deduped_within_the_hour(self):
        cfg = _cfg(self.user)
        _trade(cfg)
        for _ in range(4):
            self._tick(cfg, _paper_client())
        self.assertEqual(self._alerts().count(), 1)

    def test_two_unmanaged_symbols_are_two_facts(self):
        """Deduped per SYMBOL, not per config. Keying on the config name is
        the mistake the breaker alert made, where six configs called "manual"
        silenced each other."""
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "AAPL", "asset_class": "stock"})
        cfg = _cfg(self.user)
        cfg.symbols = ["NVDA", "AAPL"]
        cfg.save(update_fields=["symbols"])
        _trade(cfg, symbol="NVDA")
        _trade(cfg, symbol="AAPL")
        self._tick(cfg, _paper_client())
        titles = set(self._alerts().values_list("title", flat=True))
        self.assertEqual(len(titles), 2, titles)


class ABusySessionIsADifferentSentenceTests(TestCase):
    """A held trading session means nothing was asked of the broker and
    nothing is wrong with it. Saying "unreachable" there sends the operator to
    the Gateway, and from there to the HQ disconnect — which really would put
    every live path on paper."""

    def setUp(self):
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        self.user = _user("busy_u")
        self.cfg = _cfg(self.user)
        _trade(self.cfg)

    def _tick(self, *, busy):
        from bot_program.asset_engine.stock_bot import StockBot
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=_paper_client()):
            with patch("bot_program.engine.broker_router.session_busy",
                       return_value=busy):
                StockBot(self.cfg).manage_positions()
        from alerts.models import Notification
        return Notification.objects.filter(
            user=self.user, title__icontains="unmanaged").first().body

    def test_a_held_session_is_named_as_such(self):
        body = self._tick(busy=True)
        self.assertIn("held by another process", body)
        self.assertNotIn("Gateway logged in", body)

    def test_an_unreachable_broker_asks_about_the_gateway(self):
        body = self._tick(busy=False)
        self.assertIn("Gateway logged in", body)
