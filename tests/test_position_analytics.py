"""The Position Analytics panel: it renders, it reads both books, it never
prints a zero it did not measure.

This panel had never drawn anything at all. `positions_metrics` filtered
`Position.objects.filter(portfolio=..., is_open=True)`, and portfolio.Position
carries no `is_open` — an open row is one whose `closed_at` is null — so every
request raised FieldError. A bare `except Exception` around the whole body
caught it, put the message in a context key the template never rendered, and
fell through to the empty state. A permanently broken query and an empty book
produced byte-identical markup, which is why nobody noticed for as long as
they did. And even a valid query would have found nothing: it read a per-user
Portfolio, while the pipeline maintains the shared "Main" book and every
interactive trade writes bot_program.AssetBotTrade.

What is asserted here:
  - both position books reach the panel, and a per-user portfolio does not
  - a read that fails says so, in the panel, in words
  - an unpriced symbol draws the partial's "not measured" marker, and a book
    with nothing graded prints an em-dash — never a confident 0.00
  - R is denominated by the stop each position OPENED with, so a trailing
    stop cannot flatter the distribution
  - exposure is divided by MONEY, which is the reading the count donut at the
    top of the page does not give
  - the charts are the house partials, not Chart.js

Run with:  python manage.py test tests.test_position_analytics
"""
import re
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

DASH = "—"
HOST = {"HTTP_HOST": "127.0.0.1"}


# ── Fixtures ─────────────────────────────────────────────────────────────

def _instrument(symbol, asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _quote(symbol, last, asset_class="crypto"):
    from market_data.models import LiveQuote
    LiveQuote.objects.update_or_create(
        instrument=_instrument(symbol, asset_class),
        defaults={"last": Decimal(str(last)), "source": "test"})


def _main_book():
    """The SHARED "Main" portfolio — the only Position book the pipeline
    marks, and the one the panel is supposed to read."""
    from portfolio.services import get_or_create_default_portfolio
    return get_or_create_default_portfolio()


def _position(symbol="AAPL", qty="1", entry="100", direction="long",
              asset_class="stock", portfolio=None, days_old=1):
    from portfolio.models import Position
    return Position.objects.create(
        portfolio=portfolio or _main_book(),
        instrument=_instrument(symbol, asset_class),
        direction=direction, quantity=Decimal(qty),
        entry_price=Decimal(entry), current_price=Decimal(entry),
        # The dead column, written on purpose: the panel must ignore it and
        # mark the row itself.
        unrealized_pnl=Decimal("999"),
        opened_at=timezone.now() - timedelta(days=days_old))


def _config(user, name="B1", asset_class="crypto"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, enabled=True,
        mode="paper", symbols=[], capital=Decimal("10000"),
        base_currency="USD")


def _trade(user, symbol="BTCUSD", side="BUY", qty="1", entry="100",
           stop=None, initial_stop=None, config=None, hours_old=None,
           asset_class="crypto"):
    """One open AssetBotTrade. `stop` is the CURRENT (possibly trailed) stop;
    `initial_stop` is what the trade was actually taken with."""
    from bot_program.models import AssetBotTrade
    cfg = config or _config(user, name="cfg-%s-%s" % (symbol, side),
                            asset_class=asset_class)
    trade = AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(qty), entry_price=Decimal(entry), status="OPEN",
        stop_loss=Decimal(stop) if stop is not None else None,
        metadata=({} if initial_stop is None
                  else {"initial_stop_loss": float(initial_stop)}))
    if hours_old is not None:
        # opened_at is auto_now_add, so it can only be moved after the fact.
        AssetBotTrade.objects.filter(pk=trade.pk).update(
            opened_at=timezone.now() - timedelta(hours=hours_old))
    return trade


# ── Reading the fragment the way an operator reads the panel ─────────────

def _body(client):
    return client.get(reverse("metrics_positions"), **HOST).content.decode()


def _strip(body):
    """{cell label: the text under it}."""
    pattern = (r'<span class="oc-strip-label">(.*?)</span>\s*'
               r'<span class="oc-strip-value ([^"]*)">(.*?)</span>')
    return {label: value.strip()
            for label, _tone, value in re.findall(pattern, body, re.S)}


def _section(body, title):
    """The markup of one panel section, from its heading to the next one."""
    start = body.index('<div class="pa-section">%s' % title)
    rest = body[start + 1:]
    end = rest.find('<div class="pa-section">')
    return rest if end < 0 else rest[:end]


def _bar_titles(markup):
    """Every bar's native tooltip, in draw order — "LABEL: DISPLAY · NOTE"."""
    return re.findall(r"<title>([^<]*)</title>", markup)


def _donut(markup):
    """{key: pct} out of the donut's data attribute."""
    found = re.search(r'data-donut="([^"]*)"', markup)
    if not found:
        return {}
    return {part.split(":")[0]: float(part.split(":")[1])
            for part in found.group(1).split(";") if ":" in part}


class PanelTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pa_u", password="x")
        self.client.force_login(self.user)

    def body(self):
        return _body(self.client)


# ── 1. Both books, and only the book the pipeline maintains ──────────────

class BothBooksTests(PanelTestCase):
    """Exposure lives in two places, and the panel used to look in a third."""

    def test_the_panel_counts_the_legacy_book_and_the_bot_book(self):
        _position(symbol="AAPL", entry="100")
        _quote("AAPL", 110, asset_class="stock")
        _trade(self.user, symbol="BTCUSD", entry="100")
        _quote("BTCUSD", 90)

        body = self.body()
        self.assertIn("AAPL", body)
        self.assertIn("BTCUSD", body)
        # +10 on the long stock, -10 on the long crypto: both marked from
        # live quotes, neither read off Position.unrealized_pnl (which this
        # fixture wrote as 999 precisely so a stored-column read would show).
        titles = _bar_titles(_section(body, "Unrealized P&amp;L by symbol"))
        self.assertIn("AAPL: +10.00 · 1 position", titles)
        self.assertIn("BTCUSD: -10.00 · 1 position", titles)
        self.assertNotIn("999", body)

    def test_a_per_user_portfolio_is_not_the_book_it_reads(self):
        """`Portfolio.objects.filter(user=...)` was the third defect: the
        pipeline never marks that book and no trade path writes to it."""
        from portfolio.services import get_or_create_default_portfolio
        mine = get_or_create_default_portfolio(user=self.user)
        self.assertNotEqual(mine.pk, _main_book().pk)

        _position(symbol="GHOST", entry="100", portfolio=mine)
        _position(symbol="REAL", entry="100")
        _quote("REAL", 100, asset_class="stock")

        body = self.body()
        self.assertIn("REAL", body)
        self.assertNotIn("GHOST", body)


# ── 2. The query that raised on every single request ─────────────────────

class TheQueryThatNeverRanTests(PanelTestCase):

    def test_position_has_no_is_open_field(self):
        """The named bug. An open Position is one with a null closed_at."""
        from portfolio.models import Position
        names = {f.name for f in Position._meta.get_fields()}
        self.assertNotIn("is_open", names)
        self.assertIn("closed_at", names)

    def test_a_closed_position_stays_out_of_the_open_book(self):
        from portfolio.models import Position
        _position(symbol="OPENP", entry="100")
        closed = _position(symbol="SHUTP", entry="100")
        Position.objects.filter(pk=closed.pk).update(closed_at=timezone.now())
        _quote("OPENP", 100, asset_class="stock")
        _quote("SHUTP", 100, asset_class="stock")

        body = self.body()
        self.assertIn("OPENP", body)
        self.assertNotIn("SHUTP", body)

    def test_the_panel_renders_analytics_instead_of_the_empty_state(self):
        _position(symbol="AAPL", entry="100")
        _quote("AAPL", 120, asset_class="stock")
        body = self.body()
        self.assertNotIn("nothing to analyse", body)
        self.assertIn("sv-bars-svg", body)


# ── 3. A failure is shown, never rendered as absence ─────────────────────

class FailureIsShownTests(PanelTestCase):
    """The swallowing `except` is what made the bug survive."""

    def test_a_broken_read_says_so_instead_of_showing_an_empty_book(self):
        _position(symbol="AAPL", entry="100")
        with mock.patch("dashboard.views._live_open_book",
                        side_effect=RuntimeError("no such column")):
            body = self.body()
        self.assertIn("could not be read", body)
        # Critically NOT the empty-book wording: those two states were
        # indistinguishable before, which is the whole defect.
        self.assertNotIn("nothing to analyse", body)

    def test_an_empty_book_says_something_a_failure_does_not(self):
        body = self.body()
        self.assertIn("nothing to analyse", body)
        self.assertNotIn("could not be read", body)
        # An empty book is not a flat book: no chart claims a zero reading.
        self.assertNotIn("0.00", body)


# ── 4. Unmeasured is an em-dash, never a zero ────────────────────────────

class NoConfidentZeroTests(PanelTestCase):

    def test_an_unpriced_symbol_draws_the_not_measured_marker(self):
        """No LiveQuote means the P&L is unknown. A bar of length zero next
        to a symbol that really is flat would be the same picture."""
        _trade(self.user, symbol="NOQUOTE", entry="100")
        markup = _section(self.body(), "Unrealized P&amp;L by symbol")
        self.assertIn("sv-bar--unknown", markup)
        self.assertIn("NOQUOTE: %s not measured · 1 position, none priced"
                      % DASH, _bar_titles(markup))

    def test_open_r_is_a_dash_when_nothing_carries_a_stop(self):
        _trade(self.user, symbol="BTCUSD", entry="100")
        _quote("BTCUSD", 120)
        strip = _strip(self.body())
        self.assertEqual(strip["OPEN R"], DASH)
        self.assertNotIn("0.00R", self.body())

    def test_the_age_cells_carry_a_unit_and_not_a_bare_number(self):
        """Every age is formatted in the view, so "5" can never reach the
        page meaning five of something unstated."""
        _trade(self.user, symbol="BTCUSD", entry="100", hours_old=5)
        _quote("BTCUSD", 100)
        strip = _strip(self.body())
        self.assertEqual(strip["OLDEST"], "5.0h")
        self.assertEqual(strip["MEDIAN AGE"], "5.0h")


# ── 5. R is denominated by the stop the trade OPENED with ────────────────

class RIsAgainstTheOpeningStopTests(PanelTestCase):

    def test_a_trailed_stop_does_not_become_the_denominator(self):
        """Entry 100, opening stop 90, stop since trailed to 99, mark 110.
        Against the opening stop that is +1.00R. Against the trailed one it
        is +10R — risk and P&L become the same quantity, and every trailed
        winner scores like a monster."""
        _trade(self.user, symbol="BTCUSD", entry="100", stop="99",
               initial_stop="90")
        _quote("BTCUSD", 110)

        body = self.body()
        self.assertEqual(_strip(body)["OPEN R"], "+1.00R")
        # An empty bucket draws no bar at all — that is the partial's way of
        # showing a measured zero against a baseline it always paints — so
        # the ONE bar that exists is the whole assertion. [1:] drops the
        # chart's own axis title.
        titles = _bar_titles(_section(body, "R across the open book"))
        self.assertEqual(titles[1:], ["+1 to +2R: 1 open"])

    def test_a_position_with_no_recorded_stop_is_left_out_not_scored_zero(self):
        _trade(self.user, symbol="BTCUSD", entry="100", initial_stop="90")
        _trade(self.user, symbol="ETHUSD", entry="100")
        _quote("BTCUSD", 105)
        _quote("ETHUSD", 105)

        body = self.body()
        self.assertIn("1 of 2 graded", body)
        # The ungraded row is not parked in the 0-to-1R bucket alongside the
        # graded one, which would be a claim that it was measured and came
        # out barely ahead.
        titles = _bar_titles(_section(body, "R across the open book"))
        self.assertEqual(titles[1:], ["0 to +1R: 1 open"])


# ── 6. Exposure is divided by money, not by position count ───────────────

class ExposureIsByValueTests(PanelTestCase):

    def test_the_direction_donut_divides_notional_not_positions(self):
        """One large long against two small shorts. By count the book is
        two-thirds short; by money it is five-sixths long, and only one of
        those two readings tells the operator what they are carrying."""
        _trade(self.user, symbol="BIGL", side="BUY", qty="1", entry="100")
        _trade(self.user, symbol="SM1", side="SELL", qty="1", entry="10")
        _trade(self.user, symbol="SM2", side="SELL", qty="1", entry="10")
        for symbol, last in (("BIGL", 100), ("SM1", 10), ("SM2", 10)):
            _quote(symbol, last)

        body = self.body()
        shares = _donut(_section(body, "Exposure by direction"))
        self.assertEqual(shares, {"long": 83.3, "short": 16.7})
        self.assertEqual(_strip(body)["NET BIAS"], "83% long")

    def test_asset_classes_are_summed_across_both_books(self):
        _position(symbol="AAPL", entry="100", asset_class="stock")
        _trade(self.user, symbol="BTCUSD", entry="100", asset_class="crypto")
        _quote("AAPL", 100, asset_class="stock")
        _quote("BTCUSD", 100)

        shares = _donut(_section(self.body(), "Exposure by asset class"))
        self.assertEqual(shares, {"stock": 50.0, "crypto": 50.0})

    def test_concentration_names_the_symbol_it_measured(self):
        _trade(self.user, symbol="BIGL", qty="3", entry="100")
        _trade(self.user, symbol="SM1", qty="1", entry="100")
        _quote("BIGL", 100)
        _quote("SM1", 100)

        body = self.body()
        self.assertEqual(_strip(body)["CONCENTRATION"], "75%")
        self.assertIn("in BIGL", body)


# ── 7. Age is an analytic the table above does not carry ─────────────────

class AgeTests(PanelTestCase):

    def test_the_oldest_position_is_named_and_the_median_splits_the_book(self):
        _trade(self.user, symbol="OLD", entry="100", hours_old=72)
        _trade(self.user, symbol="MID", entry="100", hours_old=10)
        _trade(self.user, symbol="NEW", entry="100", hours_old=1)
        for symbol in ("OLD", "MID", "NEW"):
            _quote(symbol, 100)

        body = self.body()
        strip = _strip(body)
        self.assertEqual(strip["OLDEST"], "3.0d")
        self.assertEqual(strip["MEDIAN AGE"], "10.0h")
        # Oldest first, so the bar order is the ranking itself.
        titles = _bar_titles(_section(body, "Time held"))
        self.assertEqual([t.split(":")[0] for t in titles[1:]],
                         ["OLD", "MID", "NEW"])

    def test_a_fresh_position_still_draws_a_bar(self):
        """Age in hours rounds a one-minute-old entry to 0.0 at two decimal
        places, and a zero value draws nothing — so the newest row on the
        book, the one most likely to be looked for, vanished."""
        _trade(self.user, symbol="FRESH", entry="100", hours_old=0.02)
        _quote("FRESH", 100)
        markup = _section(self.body(), "Time held")
        self.assertIn("FRESH: 1m", "\n".join(_bar_titles(markup)))
        self.assertIn("sv-bar sv-bar--blue", markup)


# ── 8. House charts, not Chart.js ────────────────────────────────────────

class HouseChartsTests(PanelTestCase):

    def test_the_panel_draws_with_the_shared_partials(self):
        _trade(self.user, symbol="BTCUSD", entry="100", initial_stop="90")
        _quote("BTCUSD", 110)
        body = self.body()
        for marker in ("sv-bars-svg", "oc-donut", "oc-strip"):
            self.assertIn(marker, body)

    def test_no_canvas_and_no_chart_js_survive(self):
        _trade(self.user, symbol="BTCUSD", entry="100")
        _quote("BTCUSD", 110)
        body = self.body()
        for banned in ("<canvas", "new Chart(", "_chart_assets"):
            self.assertNotIn(
                banned, body,
                "%r is Chart.js, which cannot read the theme tokens and "
                "cannot tell a measured zero from a missing reading" % banned)

    def test_the_panel_is_not_a_second_copy_of_the_table_above_it(self):
        """The old fragment re-rendered the positions table verbatim. The
        page already has those columns six inches higher up."""
        _trade(self.user, symbol="BTCUSD", entry="100")
        _quote("BTCUSD", 110)
        body = self.body()
        for column in (">Entry<", ">Current<", ">Unrealized<"):
            self.assertNotIn(column, body)
