"""The instrument chart carries the operator's bets and a desk's tools.

The chart used to be a tape and nothing else: an operator long AAPL from
a bot and short it again from the NL trader saw two candlesticks' worth
of history and none of their own money on it. The instrument page now
hands the widget its open bets — legacy Positions on the user's books
and the AssetBotTrades whose config the user owns — flattened to one
shape (side, entry, stop, target, opened_at as epoch seconds) so the
widget can draw entry lines, SL/TP lines and an arrow on the bar the
trade opened. The signals' suggested entries ride along as circle marks.

Two things must hold for that to be honest rather than decorative:

  * SCOPE. Another operator's `<username>_main` book is their money;
    it never reaches this page. The shared limits book is everyone's by
    design (see portfolio.risk_gate.limits_book), so it does show.
  * SHAPE. The widget snaps opened_at to the nearest loaded bar and
    lightweight-charts wants numbers; a Decimal or an ISO string in the
    JSON would need a second parse in the browser. json_script escapes,
    so a rule name is data on the page, never markup.

The rest is markup pins: the toolbar must keep offering the indicator
toggles, the chart types, the log/fit/fullscreen controls and the RSI
pane container, and the widget must still register the live handle the
page pollers drive (refresh/tick) — a rebuild that drops one of those
goes back to a load-once-and-freeze tape quietly.

Run with:  python manage.py test tests.test_chart_depth
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone


def _instrument(symbol="AAPL"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": "stock"})
    return inst


def _position(user, inst, direction="long", entry="100", stop=None,
              tp=None, closed=False, portfolio=None):
    from portfolio.models import Position
    from portfolio.services import get_or_create_default_portfolio
    return Position.objects.create(
        portfolio=portfolio or get_or_create_default_portfolio(user=user),
        instrument=inst, direction=direction, quantity=Decimal("3"),
        entry_price=Decimal(entry), current_price=Decimal(entry),
        stop_loss=Decimal(stop) if stop else None,
        take_profit=Decimal(tp) if tp else None,
        opened_at=timezone.now() - timedelta(days=2),
        closed_at=timezone.now() if closed else None)


def _bot_trade(user, symbol="AAPL", side="BUY", status="OPEN",
               rule="breakout_a", paper=True):
    from bot_program.models import AssetBotConfig, AssetBotTrade
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class="stock", name="chart_bot",
        defaults=dict(enabled=True, mode="paper", symbols=[symbol],
                      capital=Decimal("5000"), base_currency="USD"))
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol=symbol, side=side,
        qty=Decimal("2"), entry_price=Decimal("101.5"),
        stop_loss=Decimal("99"), take_profit=Decimal("106"),
        status=status, paper=paper, rule_name=rule)


class ChartPositionsContextTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("chart_op",
                                                         password="x")
        self.other = get_user_model().objects.create_user("chart_other",
                                                          password="x")
        self.inst = _instrument()
        self.client.force_login(self.user)

    def _positions(self):
        resp = self.client.get("/instruments/AAPL/")
        self.assertEqual(resp.status_code, 200)
        return resp, resp.context["chart_positions"]

    def test_both_sources_reach_the_chart_with_side_and_epoch_mapped(self):
        """A short book Position and a BUY bot trade become one list in
        one vocabulary: side long/short, floats for the levels, epoch
        seconds for opened_at, and a label that names where it came
        from."""
        book = _position(self.user, self.inst, direction="short",
                         entry="120", stop="125", tp="110")
        bot = _bot_trade(self.user)
        _, positions = self._positions()
        by_id = {p["id"]: p for p in positions}
        self.assertEqual(set(by_id), {f"book-{book.pk}", f"bot-{bot.pk}"})

        b = by_id[f"book-{book.pk}"]
        self.assertEqual((b["source"], b["side"]), ("book", "short"))
        self.assertEqual((b["entry"], b["stop"], b["tp"], b["qty"]),
                         (120.0, 125.0, 110.0, 3.0))
        self.assertEqual(b["opened_at"], int(book.opened_at.timestamp()))
        self.assertTrue(b["label"].startswith("SHORT"))

        t = by_id[f"bot-{bot.pk}"]
        self.assertEqual((t["source"], t["side"]), ("bot", "long"))
        self.assertEqual((t["entry"], t["stop"], t["tp"], t["qty"]),
                         (101.5, 99.0, 106.0, 2.0))
        self.assertEqual(t["opened_at"], int(bot.opened_at.timestamp()))
        self.assertIn("breakout_a", t["label"])
        for p in positions:
            for key in ("entry", "stop", "tp", "qty"):
                self.assertNotIsInstance(p[key], Decimal, key)

    def test_a_sell_bot_trade_and_a_close_pending_one_both_show_as_short(self):
        """CLOSE_PENDING is still exposure at the broker — the bot wants
        it flat, the market has not agreed yet — so it stays on the chart
        until it actually closes."""
        _bot_trade(self.user, side="SELL", status="CLOSE_PENDING")
        _, positions = self._positions()
        self.assertEqual([(p["source"], p["side"]) for p in positions],
                         [("bot", "short")])

    def test_closed_positions_and_closed_bot_trades_never_show(self):
        _position(self.user, self.inst, closed=True)
        _bot_trade(self.user, status="CLOSED")
        _, positions = self._positions()
        self.assertEqual(positions, [])

    def test_a_user_with_nothing_open_gets_an_empty_list_not_an_error(self):
        resp, positions = self._positions()
        self.assertEqual(positions, [])
        self.assertContains(
            resp, 'id="instrument-main-chart-positions"')

    def test_another_operators_book_and_bots_never_appear(self):
        """Scope: the other user's `<username>_main` Position and their
        bot's trade on the same symbol are their money. The shared
        limits book is everyone's by design, so a Position there does
        show — that boundary is limits_book's, pinned here so nobody
        widens or narrows it by accident."""
        from portfolio.risk_gate import limits_book
        _position(self.other, self.inst, entry="50")
        _bot_trade(self.other, rule="theirs")
        shared = _position(self.user, self.inst, entry="77",
                           portfolio=limits_book())
        _, positions = self._positions()
        self.assertEqual([p["id"] for p in positions], [f"book-{shared.pk}"])
        self.assertEqual(positions[0]["entry"], 77.0)

    def test_the_positions_and_signal_marks_ship_as_json_script(self):
        """json_script, not a raw dump into a <script>: a rule name
        with a '<' in it must arrive as data. The signals' suggested
        entries ride along; a signal with no suggested_entry has no
        price to pin and is left out rather than plotted at zero."""
        from signals.models import Signal
        _bot_trade(self.user, rule="x<b>y")
        Signal.objects.create(
            instrument=self.inst, signal_type="technical",
            direction="bullish", urgency="high", title="t",
            description="d", rule_name="rule_priced", score=0.5,
            price_at_signal=Decimal("100"),
            suggested_entry=Decimal("101"), is_active=True)
        Signal.objects.create(
            instrument=self.inst, signal_type="technical",
            direction="bearish", urgency="low", title="t2",
            description="d", rule_name="rule_unpriced", score=0.4,
            price_at_signal=Decimal("100"), is_active=True)
        resp = self.client.get("/instruments/AAPL/")
        self.assertContains(
            resp, '<script id="instrument-main-chart-positions" '
                  'type="application/json">')
        self.assertContains(
            resp, '<script id="instrument-main-chart-signals" '
                  'type="application/json">')
        self.assertNotContains(resp, "x<b>y")
        self.assertContains(resp, "x\\u003Cb\\u003Ey")
        marks = resp.context["chart_signals"]
        self.assertEqual([m["label"] for m in marks], ["rule_priced"])
        self.assertEqual(marks[0]["price"], 101.0)
        self.assertEqual(marks[0]["direction"], "bullish")
        self.assertIsInstance(marks[0]["at"], int)


class ChartWidgetMarkupTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("chart_ui",
                                                         password="x")
        _instrument()
        self.client.force_login(self.user)
        self.resp = self.client.get("/instruments/AAPL/")
        self.assertEqual(self.resp.status_code, 200)

    def test_the_toolbar_offers_every_indicator_type_and_control(self):
        for ind in ("sma20", "sma50", "ema20", "bb", "vwap", "rsi",
                    "macd", "volume", "positions"):
            self.assertContains(self.resp, f'data-ind="{ind}"', msg_prefix=ind)
        for kind in ("candlestick", "heikin", "line", "area"):
            self.assertContains(self.resp, f'data-type="{kind}"',
                                msg_prefix=kind)
        for ctl in ("log", "fit", "fullscreen"):
            self.assertContains(self.resp, f'data-ctl="{ctl}"', msg_prefix=ctl)
        # The RSI pane is no longer a div in the markup: panes are built
        # on demand from PANE_SPECS, so what the page ships is the HOST they
        # are appended to. Asserting the old id would pin an implementation
        # the registry deliberately removed.
        self.assertContains(self.resp, 'id="instrument-main-chart-panes"')
        self.assertContains(self.resp,
                            'id="instrument-main-chart-countdown"')
        self.assertContains(self.resp, "subscribeVisibleLogicalRangeChange")
        self.assertContains(self.resp, "localStorage")

    def test_the_live_handle_contract_survives_the_rebuild(self):
        """sv-instrument-live.js drives window.svCharts[id].refresh()
        per poll and .tick(price) per quote; the overlays are re-applied
        inside loadData so a background refresh keeps them, and tick
        stays a raw-candle-only nudge (a Heikin-Ashi candle is an
        average — a raw tick grafted on it would lie)."""
        self.assertContains(self.resp, "window.svCharts")
        self.assertContains(self.resp, "refresh: function")
        self.assertContains(self.resp, "tick: function")
        self.assertContains(self.resp, "chartType !== 'candlestick'")
        self.assertContains(self.resp, "applyOverlays(bars)")
        self.assertContains(self.resp, "{background: true}")
