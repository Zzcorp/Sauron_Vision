"""The bottom headband: true, agreeing with itself, and moving.

The PORTFOLIO cell rendered `Portfolio.current_value` — a stored column whose
only writer values the LEGACY book (portfolio.Position) on the SHARED "Main"
portfolio, while the band reads the per-user book and the operator's trades
are AssetBotTrade rows. So the cell sat at its seeded 10,000 forever, on every
page of the platform, with a dropdown underneath it listing live trades. The
same defect ran through the whole strip: the cells were computed from stored
columns in one place and the dropdowns from the live book in another, so a
cell and the popup it opened could quote two different numbers for the same
position book.

What is asserted here:
  - VALUE counts BOTH books at live marks, and a bot trade moves it
  - a position with no quote dashes: value, exposure and R are em-dashes and
    never 0 — an unpriced book is unknown, not flat
  - R is denominated by the stop each trade OPENED with
    (metadata["initial_stop_loss"]), never by a trailed one
  - the BOT cell reports what the bot PROGRAM is doing: the master switch, the
    tick gate, circuit breakers, shadow mode, the last tick against its
    cadence, open positions and open R, 24h fills and win rate — and a
    platform stopped at the master switch is HALTED, never ARMED
  - every cell agrees with its own dropdown
  - the band refreshes on a fill through the platform's ONE refresher
    (_partials/live_region.html), with no page reload and no second clock

Run with:  python manage.py test tests.test_headband_truth
    (NOT RUN by the slice that wrote it — another slice owns the runner.)
"""
import html
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.utils import timezone


DASH = "—"
HOST = "127.0.0.1"
# The page the band's refresher fetches, and the cheapest full-shell render in
# the platform. Every assertion about "what a refresh returns" goes through it.
LIVE_SOURCE = "/getting-started/"


# ── Fixtures ─────────────────────────────────────────────────────────────

def _user(name="hb_u"):
    return User.objects.create_user(username=name, password="x")


def _book(user):
    """The PER-USER portfolio — the book the headband reads."""
    from portfolio.services import get_or_create_default_portfolio
    return get_or_create_default_portfolio(user=user)


def _instrument(symbol, asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _quote(symbol, last, asset_class="crypto"):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    quote, _ = LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "test"})
    return quote


def _position(user, symbol="AAPL", qty="1", entry="100", current="100",
              direction="long", stop=None, asset_class="stock", closed=False):
    """A legacy portfolio.Position on the user's own book."""
    from portfolio.models import Position
    now = timezone.now()
    return Position.objects.create(
        portfolio=_book(user), instrument=_instrument(symbol, asset_class),
        direction=direction, quantity=Decimal(qty),
        entry_price=Decimal(entry), current_price=Decimal(current),
        stop_loss=Decimal(stop) if stop is not None else None,
        opened_at=now - timedelta(days=1),
        closed_at=now if closed else None)


def _config(user, name="B1", asset_class="crypto", **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(enabled=True, mode="paper", symbols=[],
                    capital=Decimal("10000"), base_currency="USD")
    defaults.update(kw)
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, **defaults)


def _trade(user, symbol="BTCUSD", status="OPEN", side="BUY", qty="1",
           entry="100", config=None, **kw):
    from bot_program.models import AssetBotTrade
    cfg = config or _config(user, name=f"cfg-{symbol}-{status}")
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(qty), entry_price=Decimal(entry), status=status, **kw)


def _components(master=True, gate=True):
    """Seed the platform components and set the two gates the bot tick passes.

    A fresh database has NO component rows, and guarded_task reads a missing
    row as off — which is exactly the state the BOT cell has to distinguish
    from a switch somebody turned off on purpose.
    """
    from core.platform_control import PlatformComponent, seed_components
    seed_components()
    PlatformComponent.objects.filter(key="platform_master").update(
        is_enabled=master)
    PlatformComponent.objects.filter(key="pipeline_asset_bots").update(
        is_enabled=gate)


def _tick(cfg, seconds_ago=30, status="OK", note=""):
    """Write the heartbeat the runner writes, at a chosen age."""
    extras = dict(cfg.extras or {})
    extras["last_tick_at"] = (
        timezone.now() - timedelta(seconds=seconds_ago)).isoformat()
    extras["last_tick_status"] = status
    extras["last_tick_note"] = note
    cfg.extras = extras
    cfg.save(update_fields=["extras", "updated_at"])
    return cfg


def _ctx(user):
    from core.context_processors import sauron_context
    request = RequestFactory().get("/")
    request.user = user
    return sauron_context(request)


# ── HTML readers ─────────────────────────────────────────────────────────

def _text(fragment):
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment or "")).strip()


def cell(body, key):
    """The text an operator reads in the cell carrying `data-sv-live-key`.

    Read the page the way the refresher does — by key — so "the cell agrees
    with the popup" and "the refresh returns what the page rendered" are real
    assertions rather than substring luck.
    """
    m = re.search(r'data-sv-live-key="%s"[^>]*>' % re.escape(key), body)
    if not m:
        return None
    window = body[m.end():m.end() + 900]
    depth, out, i = 1, [], 0
    while i < len(window) and depth:
        if window.startswith("<span", i):
            depth += 1
        elif window.startswith("</span>", i):
            depth -= 1
            if not depth:
                break
        out.append(window[i])
        i += 1
    return _text("".join(out))


def dd_value(body, label):
    """The value of a dropdown grid cell, found by its key label.

    The label is escaped the way the template escapes it, so "OPEN P&L" finds
    the cell that renders as "OPEN P&amp;L" instead of silently finding none.
    """
    m = re.search(
        r'<span class="dk">%s</span><span class="dv[^"]*">(.*?)</span></div>'
        % re.escape(html.escape(label)), body, re.S)
    return None if not m else _text(m.group(1))


def regions(body):
    return set(re.findall(r'data-sv-live="([^"]+)"', body))


def _headband_source():
    """base.html between the band's opening tag and its refresher include."""
    text = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
        encoding="utf-8")
    start = text.index('<div class="info-panel-wrap"')
    end = text.index('_partials/live_region.html', start)
    return text[start:end]


# ── 1. VALUE counts both books, at live marks ────────────────────────────

class BookValueTests(TestCase):
    def setUp(self):
        self.user = _user("hb_value")

    def test_the_value_counts_both_books(self):
        """Legacy Positions AND AssetBotTrades, each at its live mark."""
        _quote("AAPL", "120", asset_class="stock")
        _position(self.user, "AAPL", qty="2", entry="100")
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="3", entry="100")

        cash = float(_book(self.user).cash_available)
        ctx = _ctx(self.user)
        # 2 x 120 deployed on the legacy half, 3 x 110 on the bot half.
        self.assertEqual(ctx["panel_portfolio_value"], f"{cash + 570:,.0f}")
        self.assertEqual(ctx["panel_positions"], 2)
        self.assertEqual(ctx["panel_positions_priced"], 2)

    def test_a_bot_trade_moves_the_portfolio_cell(self):
        """The regression this whole slice exists for: the cell read a stored
        column that only an hourly task on the SHARED book ever writes, so no
        trade the operator took could move it."""
        before = _ctx(self.user)["panel_portfolio_value"]
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="4", entry="100")
        after = _ctx(self.user)["panel_portfolio_value"]
        self.assertNotEqual(before, after)
        self.assertEqual(
            float(after.replace(",", "")) - float(before.replace(",", "")),
            440.0)

    def test_the_headband_and_the_op_center_count_one_book(self):
        """Both read dashboard.views_command._open_book. Two implementations
        of "what is open" is how the tab bar and the band underneath it came
        to disagree in the first place."""
        from dashboard.views_command import _open_book
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD")
        _quote("AAPL", "120", asset_class="stock")
        _position(self.user, "AAPL")
        rows, n_priced, unrealized, _deployed = _open_book(
            self.user, _book(self.user))
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_positions"], len(rows))
        self.assertEqual(ctx["panel_positions_priced"], n_priced)
        self.assertEqual(ctx["panel_open_pnl"], unrealized)

    def test_a_closed_trade_leaves_the_open_book(self):
        _quote("BTCUSD", "110")
        trade = _trade(self.user, "BTCUSD")
        self.assertEqual(_ctx(self.user)["panel_positions"], 1)
        trade.status = "CLOSED"
        trade.closed_at = timezone.now()
        trade.save(update_fields=["status", "closed_at"])
        self.assertEqual(_ctx(self.user)["panel_positions"], 0)

    def test_close_pending_still_counts_as_exposure(self):
        """The broker refused the close, so the position is still open there
        — everywhere else in the platform CLOSE_PENDING is exposure."""
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", status="CLOSE_PENDING")
        self.assertEqual(_ctx(self.user)["panel_positions"], 1)


# ── 2. Unknown is an em-dash, never a zero ───────────────────────────────

class UnpricedIsUnknownTests(TestCase):
    def setUp(self):
        self.user = _user("hb_unpriced")

    def test_an_unpriced_position_dashes_rather_than_reporting_flat(self):
        _trade(self.user, "NOQUOTE")
        ctx = _ctx(self.user)
        self.assertIsNone(ctx["panel_portfolio_value"])
        self.assertIsNone(ctx["panel_exposure"])
        self.assertIsNone(ctx["panel_open_pnl_display"])
        self.assertIsNone(ctx["panel_open_r_display"])
        self.assertEqual(ctx["panel_positions"], 1)
        self.assertIn("none with a live quote", ctx["panel_book_coverage"])

    def test_the_unpriced_cell_renders_an_em_dash_and_not_a_zero(self):
        _trade(self.user, "NOQUOTE")
        self.client.force_login(self.user)
        body = self.client.get(LIVE_SOURCE, HTTP_HOST=HOST).content.decode()
        self.assertEqual(cell(body, "hb-pf-value"), DASH)
        self.assertNotIn("€0<", body)
        self.assertIn("sv-unknown", body)

    def test_a_row_without_a_mark_carries_no_r_and_no_percent(self):
        _trade(self.user, "NOQUOTE")
        row = _ctx(self.user)["panel_open_rows"][0]
        self.assertIsNone(row["r"])
        self.assertIsNone(row["pct"])
        self.assertIsNone(row["last"])

    def test_an_empty_book_is_measured_flat_rather_than_unknown(self):
        """Nothing open is a measurement. Only an UNPRICED book is unknown."""
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_exposure"], 0)
        self.assertEqual(ctx["panel_positions"], 0)
        self.assertIsNotNone(ctx["panel_portfolio_value"])


# ── 3. R is denominated by the OPENING stop ──────────────────────────────

class OpeningStopTests(TestCase):
    def setUp(self):
        self.user = _user("hb_r")

    def test_r_uses_the_stop_the_trade_opened_with(self):
        """A trailing stop rewrites stop_loss. Grading against it makes risk
        and P&L the same quantity, so every trailed winner scores about 1R."""
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", entry="100", stop_loss=Decimal("105"),
               metadata={"initial_stop_loss": 90})
        row = _ctx(self.user)["panel_open_rows"][0]
        # 10 of risk at entry, +10 of move: 1.0R — not the 2.0R the trailed
        # stop would have claimed.
        self.assertAlmostEqual(row["r"], 1.0, places=2)

    def test_it_uses_the_platforms_own_definition_of_that_stop(self):
        from bot_program.manual_close import _initial_stop
        _quote("BTCUSD", "110")
        trade = _trade(self.user, "BTCUSD", entry="100",
                       stop_loss=Decimal("105"),
                       metadata={"initial_stop_loss": 90})
        self.assertEqual(_ctx(self.user)["panel_open_rows"][0]["stop"],
                         _initial_stop(trade))

    def test_without_metadata_the_current_stop_is_all_there_is(self):
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", entry="100", stop_loss=Decimal("95"))
        self.assertAlmostEqual(
            _ctx(self.user)["panel_open_rows"][0]["r"], 2.0, places=2)

    def test_open_r_sums_only_what_could_be_graded(self):
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", entry="100", stop_loss=Decimal("95"))
        _trade(self.user, "NOQUOTE", entry="100", stop_loss=Decimal("95"))
        ctx = _ctx(self.user)
        self.assertEqual(ctx["panel_open_r_n"], 1)
        self.assertAlmostEqual(ctx["panel_open_r"], 2.0, places=2)

    def test_a_position_with_no_stop_is_a_dash_not_a_zero(self):
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", entry="100")
        ctx = _ctx(self.user)
        self.assertIsNone(ctx["panel_open_rows"][0]["r"])
        self.assertIsNone(ctx["panel_open_r_display"])


# ── 4. The BOT cell reports the bot PROGRAM ──────────────────────────────

class BotCellTests(TestCase):
    def setUp(self):
        self.user = _user("hb_bot")

    def _bot(self):
        return _ctx(self.user)["panel_bot"]

    def test_the_master_switch_off_is_halted_and_never_armed(self):
        """A platform stopped at the master switch means every bot is idle no
        matter what its own row says: guarded_task returns before the tick."""
        _components(master=False, gate=True)
        _tick(_config(self.user))
        bot = self._bot()
        self.assertEqual(bot["state"], "HALTED")
        self.assertFalse(bot["master_on"])
        self.assertIn("master switch", bot["reason"])
        self.assertNotIn("ARMED", bot["state"])

    def test_the_cell_itself_prints_halted_with_the_master_switch_off(self):
        _components(master=False, gate=True)
        _tick(_config(self.user))
        self.client.force_login(self.user)
        body = self.client.get(LIVE_SOURCE, HTTP_HOST=HOST).content.decode()
        self.assertEqual(cell(body, "hb-bot-state"), "HALTED")
        self.assertEqual(dd_value(body, "MASTER SWITCH"), "OFF")

    def test_a_missing_component_row_is_unset_and_not_a_switch_choice(self):
        """guarded_task reads a missing key as off, so nothing runs either way
        — but the fix is to seed the components, not to flip a switch."""
        _tick(_config(self.user))
        bot = self._bot()
        self.assertEqual(bot["state"], "HALTED")
        self.assertFalse(bot["master_known"])

    def test_the_tick_gate_off_is_halted_too(self):
        _components(master=True, gate=False)
        _tick(_config(self.user))
        bot = self._bot()
        self.assertEqual(bot["state"], "HALTED")
        self.assertFalse(bot["gate_on"])
        self.assertIn("pipeline_asset_bots", bot["reason"])

    def test_an_armed_paper_bot_with_a_fresh_tick_reads_paper(self):
        _components()
        _tick(_config(self.user))
        bot = self._bot()
        self.assertEqual(bot["state"], "PAPER")
        self.assertEqual(bot["enabled"], 1)
        self.assertEqual(bot["live"], 0)

    def test_a_live_bot_says_live(self):
        _components()
        _tick(_config(self.user, mode="live"))
        bot = self._bot()
        self.assertEqual(bot["state"], "LIVE")
        self.assertEqual(bot["live"], 1)

    def test_a_bot_that_has_never_ticked_is_stalled_not_armed(self):
        """Enabled is not running. Without a heartbeat the scheduler has never
        reached this config, and saying ARMED would claim otherwise."""
        _components()
        _config(self.user)
        bot = self._bot()
        self.assertEqual(bot["state"], "STALLED")
        self.assertIsNone(bot["tick_ago"])
        self.assertEqual(bot["never_ticked"], 1)

    def test_an_overdue_tick_is_reported_against_its_own_cadence(self):
        from core.context_processors import _bot_tick_cadence_seconds
        _components()
        cadence = _bot_tick_cadence_seconds()
        _tick(_config(self.user), seconds_ago=cadence * 10)
        bot = self._bot()
        self.assertTrue(bot["tick_overdue"])
        self.assertEqual(bot["state"], "STALLED")

    def test_the_cadence_comes_from_the_beat_schedule(self):
        from core.context_processors import _bot_tick_cadence_seconds
        from config.celery import app
        self.assertEqual(
            _bot_tick_cadence_seconds(),
            float(app.conf.beat_schedule["tick-asset-bots"]["schedule"]))

    def test_a_tripped_circuit_breaker_halts_the_cell(self):
        _components()
        cfg = _tick(_config(self.user))
        now = timezone.now()
        for i in range(4):
            _trade(self.user, "BTCUSD", status="CLOSED", config=cfg,
                   pnl=Decimal("-10"), closed_at=now - timedelta(minutes=i))
        bot = self._bot()
        self.assertEqual(bot["state"], "HALTED")
        self.assertEqual(bot["halted"], 1)
        self.assertIn("circuit breaker", bot["reason"])

    def test_shadow_mode_is_not_reported_as_trading(self):
        _components()
        cfg = _config(self.user)
        cfg.extras = {"shadow_until":
                      (timezone.now() + timedelta(hours=6)).isoformat()}
        cfg.save(update_fields=["extras"])
        _tick(cfg)
        bot = self._bot()
        self.assertEqual(bot["state"], "SHADOW")
        self.assertEqual(bot["shadow"], 1)

    def test_the_kill_switch_is_named_when_every_bot_is_off(self):
        """It disables every config and leaves no flag — only its notification
        says WHY the whole program is off, which is the question being asked."""
        from alerts.models import Notification
        _components()
        _config(self.user, enabled=False)
        Notification.objects.create(
            user=self.user, notification_type="system",
            title="KILL SWITCH ACTIVATED — manual activation", body="")
        bot = self._bot()
        self.assertEqual(bot["state"], "OFF")
        self.assertIsNotNone(bot["kill_at"])
        self.assertIn("kill switch", bot["reason"].lower())

    def test_no_bot_at_all_is_none_rather_than_off(self):
        _components()
        self.assertEqual(self._bot()["state"], "NONE")

    def test_open_positions_and_open_r_are_the_bots_own(self):
        _components()
        cfg = _tick(_config(self.user))
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", config=cfg, entry="100",
               stop_loss=Decimal("95"))
        _quote("AAPL", "120", asset_class="stock")
        _position(self.user, "AAPL")
        bot = self._bot()
        self.assertEqual(bot["open"], 1)
        self.assertEqual(bot["open_r_display"], "+2.00R")
        self.assertEqual(_ctx(self.user)["panel_positions"], 2)

    def test_24h_fills_and_win_rate(self):
        _components()
        cfg = _tick(_config(self.user))
        now = timezone.now()
        _trade(self.user, "BTCUSD", status="CLOSED", config=cfg,
               pnl=Decimal("30"), closed_at=now - timedelta(minutes=5))
        _trade(self.user, "ETHUSD", status="CLOSED", config=cfg,
               pnl=Decimal("-10"), closed_at=now - timedelta(minutes=6))
        bot = self._bot()
        self.assertEqual(bot["closed_24h"], 2)
        self.assertEqual(bot["opened_24h"], 2)
        self.assertEqual(bot["winrate"], 50)
        self.assertEqual(bot["pnl_24h_display"], "+20.00")

    def test_nothing_closed_is_an_em_dash_and_never_a_zero_win_rate(self):
        """A 0% win rate reads as "the bot lost everything it took"."""
        _components()
        _tick(_config(self.user))
        bot = self._bot()
        self.assertIsNone(bot["winrate"])
        self.assertIsNone(bot["pnl_24h_display"])
        self.assertIsNone(bot["open_r_display"])
        self.assertEqual(bot["closed_24h"], 0)

    def test_each_configured_bot_is_listed_with_its_own_state(self):
        _components()
        _tick(_config(self.user, name="alpha"), seconds_ago=30)
        _config(self.user, name="beta", asset_class="stock", enabled=False)
        rows = {b["name"]: b for b in self._bot()["bots"]}
        self.assertEqual(set(rows), {"alpha", "beta"})
        self.assertTrue(rows["alpha"]["enabled"])
        self.assertIsNotNone(rows["alpha"]["tick_ago"])
        self.assertIsNone(rows["beta"]["tick_ago"])

    def test_the_raw_enabled_fact_is_kept_but_is_not_the_cell(self):
        """`panel_bot_armed` stays what it always was — a config is enabled —
        while the CELL renders the state, which is that fact AND the gates."""
        _components(master=False)
        _tick(_config(self.user))
        ctx = _ctx(self.user)
        self.assertIs(ctx["panel_bot_armed"], True)
        self.assertEqual(ctx["panel_bot"]["state"], "HALTED")


# ── 5. Cells and their popups agree ──────────────────────────────────────

class CellsAgreeWithPopupsTests(TestCase):
    def setUp(self):
        self.user = _user("hb_agree")
        _components()
        _tick(_config(self.user))
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", entry="100", stop_loss=Decimal("95"))
        self.client.force_login(self.user)
        self.body = self.client.get(
            LIVE_SOURCE, HTTP_HOST=HOST).content.decode()

    def test_the_portfolio_cell_and_its_dropdown_show_one_value(self):
        self.assertEqual(cell(self.body, "hb-pf-value"),
                         dd_value(self.body, "VALUE"))

    def test_the_positions_cell_and_its_dropdown_count_the_same_book(self):
        self.assertEqual(cell(self.body, "hb-pos-count"),
                         dd_value(self.body, "POSITIONS"))

    def test_the_bot_cell_and_its_dropdown_report_one_state(self):
        self.assertEqual(cell(self.body, "hb-bot-state"),
                         dd_value(self.body, "STATE"))

    def test_the_dropdown_lists_the_position_the_cells_counted(self):
        self.assertEqual(cell(self.body, "hb-pos-count"), "1")
        self.assertIn("BTCUSD", self.body)
        self.assertIn("2.00R", self.body)

    def test_one_book_for_the_value_cell_and_the_exposure_line(self):
        ctx = _ctx(self.user)
        self.assertEqual(cell(self.body, "hb-pf-value"),
                         f"{ctx['panel_currency_symbol']}"
                         f"{ctx['panel_portfolio_value']}")


# ── 6. The band refreshes on a fill, without a reload ────────────────────

class RefreshTests(TestCase):
    def setUp(self):
        self.user = _user("hb_live")
        self.client.force_login(self.user)

    def _page(self, url=LIVE_SOURCE):
        return self.client.get(url, HTTP_HOST=HOST).content.decode()

    def test_every_cell_declares_a_live_region(self):
        found = regions(self._page())
        for name in ("hb-pf-value", "hb-pf-sub", "hb-pf-detail",
                     "hb-pos-count", "hb-pos-sub", "hb-pos-detail",
                     "hb-bot-state", "hb-bot-sub", "hb-bot-detail",
                     "hb-signals", "hb-news", "hb-alerts", "hb-watchlist",
                     "hb-strategies", "hb-funding", "hb-liq", "hb-dd",
                     "hb-vol"):
            self.assertIn(name, found, name)

    def test_it_reuses_the_one_refresher_and_adds_no_second_clock(self):
        """live_region.html is the platform's single idiom for this. A second
        refresher would mean two clocks and two ideas of what a fill is."""
        body = self._page("/signals/")
        self.assertEqual(body.count("var LIVE_URL ="), 1)
        for marker in ("sv:eye-event", "fill_open", "fill_close",
                       "close_pending", "svLive", "prefers-reduced-motion",
                       "sc-changed"):
            self.assertIn(marker, body, marker)

    def test_the_band_never_polls_unconditionally_on_a_fast_timer(self):
        self.assertNotRegex(self._page(), r'hx-trigger="[^"]*every ')

    def test_the_live_source_really_carries_the_headband(self):
        """The refresher matches regions by name; a source that stopped
        rendering the band would leave every cell frozen and say nothing."""
        body = self._page()
        self.assertIn('var LIVE_URL = "%s"' % LIVE_SOURCE, body)
        self.assertIn("hb-pf-value", regions(body))

    def test_a_fill_changes_what_the_refresh_returns(self):
        """No reload: the same URL the band re-fetches must already carry the
        new numbers the moment the trade lands."""
        before = cell(self._page(), "hb-pf-value")
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", qty="4", entry="100")
        after = self._page()
        self.assertNotEqual(before, cell(after, "hb-pf-value"))
        self.assertEqual(cell(after, "hb-pos-count"), "1")
        self.assertIn("BTCUSD", after)

    def test_the_cached_payload_cannot_outlive_the_fill(self):
        """The dropdowns are cached per user, and a plain TTL meant a refresh
        fired by a fill was answered with the payload computed before it —
        which is precisely "the popup content doesn't change"."""
        from core.context_processors import _book_fingerprint
        book = _book(self.user)
        before = _book_fingerprint(self.user, book)
        _trade(self.user, "BTCUSD")
        self.assertNotEqual(before, _book_fingerprint(self.user, book))

    def test_the_bot_heartbeat_also_busts_the_key(self):
        from core.context_processors import _book_fingerprint
        book = _book(self.user)
        cfg = _config(self.user)
        before = _book_fingerprint(self.user, book)
        _tick(cfg)
        self.assertNotEqual(before, _book_fingerprint(self.user, book))

    def test_the_states_the_refresher_paints_are_present(self):
        body = self._page()
        self.assertIn("data-sv-live-status", body)
        self.assertIn("sv-live-offline", body)


# ── 7. House rules on the band ───────────────────────────────────────────

class HeadbandHygieneTests(TestCase):
    def test_no_multiline_hash_comment_in_the_band(self):
        """{# #} is single-line; spanning it renders the text verbatim."""
        for m in re.finditer(r"\{#(.*?)#\}", _headband_source(), re.S):
            self.assertNotIn("\n", m.group(1), m.group(1).strip()[:60])

    def test_no_comment_markup_reaches_the_browser(self):
        user = _user("hb_hygiene")
        self.client.force_login(user)
        body = self.client.get(LIVE_SOURCE, HTTP_HOST=HOST).content.decode()
        self.assertNotIn("{#", body)
        self.assertNotIn("{% comment", body)

    def test_the_band_never_hardcodes_a_currency_sign(self):
        """The book carries its own currency; the band used to print € in
        front of every figure whatever the portfolio was denominated in."""
        source = _headband_source()
        self.assertNotIn("&euro;", source)
        self.assertIn("panel_currency_symbol", source)

    def test_gold_that_prints_a_value_uses_the_ink_token(self):
        """--accent-gold is a glow tuned against near-black and fails contrast
        on the light theme."""
        css = (Path(settings.BASE_DIR) / "static" / "css"
               / "sauron.css").read_text(encoding="utf-8")
        start = css.index("Headband truth")
        block = css[start:start + 2200]
        self.assertIn("--accent-gold-ink", block)
        self.assertNotIn("var(--accent-gold)", block)

    def test_the_only_moving_thing_honours_reduced_motion(self):
        css = (Path(settings.BASE_DIR) / "static" / "css"
               / "sauron.css").read_text(encoding="utf-8")
        start = css.index("hbHaltPulse")
        self.assertIn("prefers-reduced-motion", css[start:start + 500])

    def test_a_direction_class_in_the_band_is_actually_painted(self):
        """The rows carried .up / .down from the day they were given content
        and no stylesheet matched them there, so a +2R and a −2R printed in
        the same colour."""
        css = (Path(settings.BASE_DIR) / "static" / "css"
               / "sauron.css").read_text(encoding="utf-8")
        self.assertIn(".ip-dropdown .ipr-r.up", css)
        self.assertIn(".ip-dropdown .ipr-r.down", css)

    def test_the_bot_cell_links_to_the_bots_it_counts(self):
        """It linked to the legacy crypto page while counting AssetBotConfigs
        — a different bot program from the one it was reporting on."""
        source = _headband_source()
        self.assertIn("asset_bots_dashboard", source)
        self.assertNotIn("'bot_home'", source)
