"""Operations Center readouts: true, and moving.

The four metrics in the tab bar were computed once, at page render, and no
fragment endpoint recomputed them — so they froze at whatever they were when
the page was opened. Worse, three of the four had nothing to say: the
secondary line defaulted to the EMPTY STRING, the LIVE half read a column
nothing writes, and every failure was swallowed by a bare `except: pass`.

What is asserted here:
  - the LIVE metric counts BOTH position books, not just the legacy one
  - unrealized P&L is derived from live marks, never from the dead
    Position.unrealized_pnl column
  - a metric with nothing to measure renders an em-dash, never a 0 and never
    a blank
  - the tab bar has a refresh path that does not need a page reload
  - the LIVE tab's rule counters come from a module that exists

Run with:  python manage.py test tests.test_command_metrics
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


# ── Fixtures ─────────────────────────────────────────────────────────────

def _user(name="ocm_u"):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol, asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol,
        defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _quote(symbol, last, asset_class="crypto"):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    quote, _ = LiveQuote.objects.update_or_create(
        instrument=inst,
        defaults={"last": Decimal(str(last)), "source": "test"})
    return quote


def _portfolio(user):
    from portfolio.services import get_or_create_default_portfolio
    return get_or_create_default_portfolio(user=user)


def _position(user, symbol="AAPL", qty="1", entry="100", current="100",
              direction="long", stored_pnl="0", closed=False,
              asset_class="stock"):
    """A legacy portfolio.Position. `stored_pnl` writes the dead column on
    purpose, so a test can prove the page ignores it."""
    from portfolio.models import Position
    now = timezone.now()
    return Position.objects.create(
        portfolio=_portfolio(user),
        instrument=_instrument(symbol, asset_class),
        direction=direction,
        quantity=Decimal(qty),
        entry_price=Decimal(entry),
        current_price=Decimal(current),
        unrealized_pnl=Decimal(stored_pnl),
        opened_at=now - timedelta(days=1),
        closed_at=now if closed else None,
    )


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


def _snapshot(user, pnl_pct=1.5, when=None):
    from portfolio.models import PortfolioSnapshot
    return PortfolioSnapshot.objects.create(
        portfolio=_portfolio(user),
        date=when or timezone.localdate(),
        total_value=Decimal("10000"), cash=Decimal("9000"),
        daily_pnl=Decimal("150"), daily_pnl_pct=pnl_pct,
        cumulative_pnl_pct=1.5, max_drawdown=-2.0)


DASH = "—"


# ── 1. The LIVE metric counts both books ─────────────────────────────────

class LiveMetricUnionsBothBooksTests(TestCase):
    """Exposure lives in portfolio.Position AND bot_program.AssetBotTrade.
    Counting one of them reported "0 OPEN" to an operator holding trades,
    while the headband on the same screen counted them."""

    def setUp(self):
        self.user = _user("ocm_union")

    def test_counts_positions_and_bot_trades_together(self):
        from dashboard.views_command import _tab_bar_metrics
        _position(self.user, "AAPL")
        _trade(self.user, "BTCUSD", status="OPEN")
        self.assertEqual(_tab_bar_metrics(self.user)["live"]["primary"],
                         "2 OPEN")

    def test_close_pending_still_counts_as_exposure(self):
        """The position is still open at the broker; every other surface on
        the platform counts CLOSE_PENDING as exposure."""
        from dashboard.views_command import _tab_bar_metrics
        _trade(self.user, "BTCUSD", status="CLOSE_PENDING")
        self.assertEqual(_tab_bar_metrics(self.user)["live"]["primary"],
                         "1 OPEN")

    def test_bot_only_book_is_not_zero(self):
        from dashboard.views_command import _tab_bar_metrics
        _trade(self.user, "BTCUSD", status="OPEN")
        self.assertNotEqual(_tab_bar_metrics(self.user)["live"]["primary"],
                            "0 OPEN")


# ── 2. P&L comes from marks, not from the dead column ────────────────────

class UnrealizedFromMarksTests(TestCase):
    """Position.unrealized_pnl defaults to 0 and its only writer is an hourly
    task that marks the SHARED "Main" portfolio — on the per-user book this
    page reads it is a permanent, confident +0.00."""

    def setUp(self):
        self.user = _user("ocm_marks")

    def test_bot_trade_pnl_is_computed_from_the_live_quote(self):
        from dashboard.views_command import _tab_bar_metrics
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", status="OPEN", qty="2", entry="100")
        self.assertEqual(_tab_bar_metrics(self.user)["live"]["secondary"],
                         "+20.00")

    def test_short_side_pnl_flips_sign(self):
        from dashboard.views_command import _tab_bar_metrics
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", status="OPEN", side="SELL", qty="2",
               entry="100")
        self.assertEqual(_tab_bar_metrics(self.user)["live"]["secondary"],
                         "-20.00")

    def test_the_stored_column_is_ignored_for_legacy_positions(self):
        """A Position row carrying a stale 999 in unrealized_pnl must be
        re-priced from its quote, not believed."""
        from dashboard.views_command import _open_book
        _quote("AAPL", "105", asset_class="stock")
        _position(self.user, "AAPL", qty="1", entry="100",
                  stored_pnl="999")
        _rows, n_priced, unrealized, _deployed = _open_book(
            self.user, _portfolio(self.user))
        self.assertEqual(n_priced, 1)
        self.assertEqual(unrealized, 5.0)

    def test_unpriced_book_is_unknown_not_flat(self):
        """A position with no quote cannot be valued. Reporting +0.00 there
        is a claim the position is break-even."""
        from dashboard.views_command import _open_book, _tab_bar_metrics
        _position(self.user, "NOQUOTE", qty="1", entry="100")
        rows, n_priced, unrealized, deployed = _open_book(
            self.user, _portfolio(self.user))
        self.assertEqual(len(rows), 1)
        self.assertEqual(n_priced, 0)
        self.assertIsNone(unrealized)
        self.assertIsNone(deployed)

        metric = _tab_bar_metrics(self.user)["live"]
        self.assertEqual(metric["primary"], "1 OPEN")
        self.assertEqual(metric["secondary"], DASH)

    def test_partial_pricing_is_disclosed_in_the_tooltip(self):
        from dashboard.views_command import _tab_bar_metrics
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", status="OPEN", qty="1", entry="100")
        _position(self.user, "NOQUOTE", qty="1", entry="100")
        metric = _tab_bar_metrics(self.user)["live"]
        self.assertEqual(metric["primary"], "2 OPEN")
        self.assertIn("1 of 2", metric["title"])


# ── 3. Nothing to measure renders an em-dash ─────────────────────────────

class EmDashNotZeroTests(TestCase):
    """A dash means "not measured". A 0 is a measurement, and every one of
    these cells used to print one — or, worse, an empty string."""

    def setUp(self):
        self.user = _user("ocm_dash")
        self.metrics = None

    def _m(self):
        from dashboard.views_command import _tab_bar_metrics
        if self.metrics is None:
            self.metrics = _tab_bar_metrics(self.user)
        return self.metrics

    def test_no_secondary_is_ever_the_empty_string(self):
        """The old default. Three of the four tab heads rendered a blank
        span, which is what "it doesn't render anything" looked like."""
        for key, metric in self._m().items():
            self.assertNotEqual(metric["secondary"], "",
                                f"{key} secondary is blank")
            self.assertNotEqual(metric["primary"], "",
                                f"{key} primary is blank")

    def test_live_pnl_with_no_positions_is_a_dash(self):
        self.assertEqual(self._m()["live"]["secondary"], DASH)

    def test_portfolio_delta_without_todays_snapshot_is_a_dash(self):
        self.assertEqual(self._m()["portfolio"]["secondary"], DASH)

    def test_a_stale_snapshot_does_not_describe_today(self):
        from dashboard.views_command import _tab_bar_metrics
        _snapshot(self.user, pnl_pct=4.2,
                  when=timezone.localdate() - timedelta(days=6))
        self.assertEqual(
            _tab_bar_metrics(self.user)["portfolio"]["secondary"], DASH)

    def test_todays_snapshot_is_reported(self):
        from dashboard.views_command import _tab_bar_metrics
        _snapshot(self.user, pnl_pct=1.5)
        metric = _tab_bar_metrics(self.user)["portfolio"]
        self.assertEqual(metric["secondary"], "+1.50%")
        self.assertEqual(metric["tone"], "up")

    def test_history_without_graded_closes_is_a_dash(self):
        self.assertEqual(self._m()["history"]["primary"], DASH)
        self.assertEqual(self._m()["history"]["secondary"], DASH)

    def test_bots_without_configs_is_a_dash_not_zero_of_zero(self):
        self.assertEqual(self._m()["bots"]["primary"], DASH)

    def test_bots_pnl_with_nothing_closed_is_a_dash(self):
        """Sum() over no rows is None. Coercing it to 0 claimed the day
        closed flat on a day nothing closed at all."""
        from dashboard.views_command import _tab_bar_metrics
        _config(self.user, name="Idle")
        metric = _tab_bar_metrics(self.user)["bots"]
        self.assertEqual(metric["primary"], "1/1 ON")
        self.assertEqual(metric["secondary"], DASH)

    def test_hero_delta_without_a_snapshot_is_a_dash(self):
        from dashboard.views_command import _hero_metrics
        hero = _hero_metrics(self.user)
        self.assertEqual(hero["delta"], DASH)
        self.assertEqual(hero["delta_tone"], "")

    def test_every_metric_carries_an_explanatory_title(self):
        """The number alone cannot say which book it counted."""
        for key, metric in self._m().items():
            self.assertTrue(metric["title"].strip(),
                            f"{key} has no tooltip")


# ── 4. The tab bar refreshes without a page reload ───────────────────────

class LiveRefreshPathTests(TestCase):
    def setUp(self):
        self.user = _user("ocm_live")
        self.client.force_login(self.user)

    def test_metrics_endpoint_serves_json(self):
        r = self.client.get("/command/tab/metrics/")
        self.assertEqual(r.status_code, 200)
        payload = json.loads(r.content.decode("utf-8"))
        self.assertIn("tabs", payload)
        self.assertIn("hero", payload)
        for key in ("live", "portfolio", "history", "bots"):
            self.assertIn(key, payload["tabs"])
            self.assertIn("primary", payload["tabs"][key])
            self.assertIn("tone", payload["tabs"][key])

    def test_metrics_endpoint_requires_login(self):
        self.client.logout()
        r = self.client.get("/command/tab/metrics/")
        self.assertIn(r.status_code, (302, 403))

    def test_metrics_endpoint_is_per_user(self):
        other = _user("ocm_other")
        _trade(other, "BTCUSD", status="OPEN")
        payload = json.loads(
            self.client.get("/command/tab/metrics/").content.decode("utf-8"))
        self.assertEqual(payload["tabs"]["live"]["primary"], "0 OPEN")

    def test_page_carries_the_refresh_hooks(self):
        body = self.client.get("/command/").content.decode("utf-8", "ignore")
        for key in ("live", "portfolio", "history", "bots"):
            self.assertIn(f'data-oc-metric="{key}"', body)
        self.assertIn("/command/tab/metrics/", body)
        self.assertIn('data-oc-hero="value"', body)

    def test_page_listens_on_the_shared_eye_event(self):
        """base.html owns the one /ws/eye/ socket and re-dispatches its
        payloads as sv:eye-event — the fills that move these numbers arrive
        there."""
        body = self.client.get("/command/").content.decode("utf-8", "ignore")
        self.assertIn("sv:eye-event", body)
        for kind in ("fill_open", "fill_close", "close_pending"):
            self.assertIn(kind, body)

    def test_page_does_not_open_a_second_socket(self):
        """This page used to open its own connection to the very same
        /ws/eye/ endpoint to watch the very same events. Counted against
        another page on the same base template, because base.html legitimately
        opens the sockets both of them share."""
        command = self.client.get("/command/").content.decode("utf-8", "ignore")
        eye = self.client.get("/eye/").content.decode("utf-8", "ignore")
        self.assertEqual(command.count("new WebSocket"),
                         eye.count("new WebSocket"))

    def test_a_fallback_timer_exists_for_a_dead_socket(self):
        body = self.client.get("/command/").content.decode("utf-8", "ignore")
        self.assertIn("FALLBACK_MS", body)

    def test_movement_honours_reduced_motion(self):
        body = self.client.get("/command/").content.decode("utf-8", "ignore")
        self.assertIn("prefers-reduced-motion", body)

    def test_metrics_move_between_two_calls_without_a_reload(self):
        """The point of the endpoint: a fill lands, the next poll differs."""
        before = json.loads(
            self.client.get("/command/tab/metrics/").content.decode("utf-8"))
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", status="OPEN", qty="1", entry="100")
        after = json.loads(
            self.client.get("/command/tab/metrics/").content.decode("utf-8"))
        self.assertEqual(before["tabs"]["live"]["primary"], "0 OPEN")
        self.assertEqual(after["tabs"]["live"]["primary"], "1 OPEN")
        self.assertEqual(after["tabs"]["live"]["secondary"], "+10.00")


# ── 5. The tab bodies stop reporting fiction ─────────────────────────────

class LiveTabTruthTests(TestCase):
    def setUp(self):
        self.user = _user("ocm_livetab")
        self.client.force_login(self.user)

    def test_rule_counters_come_from_a_module_that_exists(self):
        """The import was `bot_program.rule_control_models`, which is not a
        module, so the swallowing except printed "0 rules" on every render of
        an install running twelve."""
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="ocm_rule_a")
        RuleControl.objects.create(rule_name="ocm_rule_b",
                                   status=RuleControl.STATUS_PAUSED,
                                   paused_until=timezone.now() + timedelta(days=1))
        r = self.client.get("/command/tab/live/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["live_rules_active"], 1)
        self.assertEqual(r.context["live_rules_paused"], 1)

    def test_an_expired_pause_counts_as_running(self):
        """Nothing ever writes the status column back to active."""
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="ocm_rule_expired",
                                   status=RuleControl.STATUS_PAUSED,
                                   paused_until=timezone.now() - timedelta(days=1))
        r = self.client.get("/command/tab/live/")
        self.assertEqual(r.context["live_rules_active"], 1)
        self.assertEqual(r.context["live_rules_paused"], 0)

    def test_best_card_carries_the_trades_symbol(self):
        """The card reads `.config.symbol`, and AssetBotConfig has no such
        field — it holds a `symbols` LIST. Both cards rendered a real R
        multiple above a blank symbol."""
        _trade(self.user, "ETHUSD", status="CLOSED", entry="100",
               closed_at=timezone.now(), realized_r=1.5,
               rule_name="ocm_rule", outcome="hit_target")
        r = self.client.get("/command/tab/live/")
        self.assertIsNotNone(r.context["live_24h_best"])
        self.assertEqual(r.context["live_24h_best"]["config"]["symbol"],
                         "ETHUSD")
        self.assertEqual(r.context["live_24h_best"]["config"]["rule_name"],
                         "ocm_rule")

    def test_open_pos_cell_matches_the_tab_head(self):
        from dashboard.views_command import _tab_bar_metrics
        _position(self.user, "AAPL")
        _trade(self.user, "BTCUSD", status="OPEN")
        r = self.client.get("/command/tab/live/")
        self.assertEqual(r.context["live_opens"], 2)
        self.assertEqual(_tab_bar_metrics(self.user)["live"]["primary"],
                         "2 OPEN")

    def test_gate_ratio_with_no_decisions_is_not_zero_percent(self):
        r = self.client.get("/command/tab/live/")
        self.assertEqual(r.context["gate_accept_rate"], DASH)

    def test_session_r_with_nothing_graded_is_a_dash(self):
        r = self.client.get("/command/tab/live/")
        self.assertEqual(r.context["live_24h_sum_r"], DASH)
        self.assertEqual(r.context["live_24h_win_rate"], DASH)


class PortfolioTabTruthTests(TestCase):
    def setUp(self):
        self.user = _user("ocm_pf")
        self.client.force_login(self.user)

    def test_open_positions_table_shows_bot_trades(self):
        """This tab read portfolio.Position alone, so on a platform where
        every interactive trade writes AssetBotTrade it showed an empty
        book to an operator holding one."""
        _quote("BTCUSD", "110")
        _trade(self.user, "BTCUSD", status="OPEN", qty="1", entry="100")
        r = self.client.get("/command/tab/portfolio/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["open_positions_total"], 1)
        self.assertEqual(r.context["total_unrealized"], 10.0)
        self.assertIn("BTCUSD", r.content.decode("utf-8", "ignore"))

    def test_unrealized_is_a_dash_when_nothing_can_be_priced(self):
        _position(self.user, "NOQUOTE", qty="1", entry="100",
                  stored_pnl="999")
        r = self.client.get("/command/tab/portfolio/")
        self.assertIsNone(r.context["total_unrealized"])
        self.assertIn(DASH, r.content.decode("utf-8", "ignore"))

    def test_win_rate_and_drawdown_are_none_with_no_history(self):
        r = self.client.get("/command/tab/portfolio/")
        self.assertIsNone(r.context["win_rate"])
        self.assertIsNone(r.context["profit_factor"])
        self.assertIsNone(r.context["max_drawdown"])

    def test_strip_labels_survive(self):
        """Other suites assert on these; the honesty pass must not move
        them."""
        body = self.client.get("/command/tab/portfolio/").content.decode(
            "utf-8", "ignore")
        self.assertIn("SHARPE 30D", body)
        self.assertIn("MAX DRAWDOWN", body)
        self.assertIn("PORTFOLIO VALUE", body)


class HistoryTabTruthTests(TestCase):
    def setUp(self):
        self.user = _user("ocm_hist")
        self.client.force_login(self.user)
        self.cfg = _config(self.user, name="HistBot")

    def _closed(self, realized_r, pnl="10"):
        _trade(self.user, "BTCUSD", status="CLOSED", config=self.cfg,
               closed_at=timezone.now() - timedelta(hours=2),
               realized_r=realized_r, pnl=Decimal(pnl),
               rule_name="ocm_rule")

    def test_win_rate_excludes_ungraded_closes(self):
        """A close with no realized_r has no initial risk to normalise by and
        can never be a win; leaving it in the denominator dragged the rate
        down by a silent amount."""
        self._closed(1.0)
        self._closed(-1.0)
        self._closed(None)
        r = self.client.get("/command/tab/history/")
        self.assertEqual(r.context["n_closed"], 3)
        self.assertEqual(r.context["n_graded"], 2)
        self.assertEqual(r.context["win_rate"], 50.0)

    def test_no_graded_closes_means_no_win_rate(self):
        self._closed(None)
        r = self.client.get("/command/tab/history/")
        self.assertIsNone(r.context["win_rate"])
        self.assertIsNone(r.context["total_r"])

    def test_head_and_body_use_the_same_window(self):
        """The head summarised 30 days under a body that analyses 90, so a
        trade could be in one and not the other."""
        from dashboard.views_command import _tab_bar_metrics
        _trade(self.user, "BTCUSD", status="CLOSED", config=self.cfg,
               closed_at=timezone.now() - timedelta(days=45),
               realized_r=2.0, pnl=Decimal("20"))
        self.assertEqual(_tab_bar_metrics(self.user)["history"]["primary"],
                         "1W·0L")
        r = self.client.get("/command/tab/history/")
        self.assertEqual(r.context["n_graded"], 1)

    def test_per_rule_rows_are_grouped_not_one_per_trade(self):
        """An ordering in force when values() runs rides into the GROUP BY."""
        self._closed(1.0)
        self._closed(2.0)
        r = self.client.get("/command/tab/history/")
        rows = [row for row in r.context["by_rule"]
                if row["rule_name"] == "ocm_rule"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["n"], 2)


class BotsTabTruthTests(TestCase):
    def setUp(self):
        self.user = _user("ocm_bots")
        self.client.force_login(self.user)

    def test_pnl_column_is_none_when_nothing_closed(self):
        _config(self.user, name="Quiet")
        r = self.client.get("/command/tab/bots/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context["rows"][0]["pnl_24h"])

    def test_no_configs_means_dashes_not_zeros(self):
        r = self.client.get("/command/tab/bots/")
        self.assertEqual(r.context["n_configs"], 0)
        self.assertEqual(r.context["n_enabled"], DASH)
        self.assertEqual(r.context["n_alive"], DASH)

    def test_strip_label_survives(self):
        body = self.client.get("/command/tab/bots/").content.decode(
            "utf-8", "ignore")
        self.assertIn("ALIVE 6H", body)


# ── 6. No silent swallow ─────────────────────────────────────────────────

class FailuresAreVisibleTests(TestCase):
    """Every block was wrapped in `except Exception: pass`, so a metric that
    could not be computed reported nothing anywhere — not on the page, not in
    the log, not to an operator wondering why the tab bar was blank."""

    def setUp(self):
        self.user = _user("ocm_log")

    def test_a_failing_metric_logs_and_still_renders_a_dash(self):
        from unittest.mock import patch
        from dashboard.views_command import _tab_bar_metrics

        with patch("dashboard.views_command._open_book",
                   side_effect=RuntimeError("quote feed down")):
            with self.assertLogs("dashboard.views_command", level="WARNING") as log:
                metrics = _tab_bar_metrics(self.user)

        self.assertTrue(any("quote feed down" in line for line in log.output))
        self.assertEqual(metrics["live"]["primary"], DASH)
        self.assertEqual(metrics["live"]["secondary"], DASH)

    def test_the_page_still_renders_when_a_metric_fails(self):
        from unittest.mock import patch
        self.client.force_login(self.user)
        with patch("dashboard.views_command._open_book",
                   side_effect=RuntimeError("quote feed down")):
            with self.assertLogs("dashboard.views_command", level="WARNING"):
                r = self.client.get("/command/")
        self.assertEqual(r.status_code, 200)
