"""A config disabled by a stop that is not a brake is not managed — and
every lever that disables one says so.

The brain page's "Disable manual" press told the operator the config
"manages what is open and opens nothing new". The runner skips a disabled
config whole (run_asset_bot_tick, both fleet passes), so a disabled manual
config's open positions lose their time stop, trailing and every
platform-checked stop, and a paper row loses its stop outright. The runner
stays that way on purpose for a stop that is not a brake: the kill switch
leaves its rows for reconciliation by hand. These tests pin the runner's
behaviour and the words that now state it (2026-09-26).

Since 2026-10-07 every stop is recorded on the config
(bot_program/asset_engine/disarm.py), and a config a BRAKE stopped is
still managed (tests/test_brake_keeps_managing.py). The configs here carry
no record, or a hand stop's (`bot off`, the brain's button), so every
test below still holds as it did.

Run with:  python manage.py test tests.test_disabled_config_unmanaged
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

ROUTER = "bot_program.engine.broker_router.client_for_symbol"
DESK = "bot_program.capital_desk.is_desk_enabled"


def _config(user, asset_class="stock", enabled=True, name=None, symbols=()):
    from bot_program.manual_trade import MANUAL_CONFIG_NAME
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name or MANUAL_CONFIG_NAME,
        enabled=enabled, mode="paper", symbols=list(symbols),
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
        entry_score_min=0.6, min_signals_for_entry=1, cool_down_minutes=0)


def _open_paper_row(cfg, symbol):
    """A paper BUY whose stop (95) the mark below (94) has already crossed."""
    from bot_program.models import AssetBotTrade
    from instruments.models import Instrument
    Instrument.objects.get_or_create(
        symbol=symbol,
        defaults={"name": symbol, "asset_class": cfg.asset_class})
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side="BUY",
        qty=Decimal("10"), entry_price=Decimal("100"),
        stop_loss=Decimal("95"), take_profit=Decimal("110"),
        status="OPEN", paper=True)


def _crossed_client():
    client = MagicMock()
    client.ticker.return_value = {"lastPrice": "94.00"}
    return client


class TheRunnerLeavesADisabledConfigAloneTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dis_runner", password="x")

    def test_enabled_the_tick_closes_the_row_through_its_stop(self):
        """The control: the same row on an ENABLED manual config IS managed,
        so the disabled cases below cannot pass for want of a live setup."""
        from bot_program.asset_engine.runner import run_asset_bot_tick
        cfg = _config(self.user)
        trade = _open_paper_row(cfg, "DSB1")
        with patch(ROUTER, return_value=_crossed_client()):
            out = run_asset_bot_tick(cfg.id)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["managed"], 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")

    def test_disabled_the_tick_never_reads_the_mark_and_the_row_stays_open(self):
        from bot_program.asset_engine.runner import run_asset_bot_tick
        cfg = _config(self.user, enabled=False)
        trade = _open_paper_row(cfg, "DSB1")
        with patch(ROUTER, return_value=_crossed_client()) as router:
            out = run_asset_bot_tick(cfg.id)
        self.assertEqual(out, {"status": "skipped", "reason": "disabled",
                               "config_id": cfg.id})
        router.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_neither_fleet_pass_manages_a_disabled_config(self):
        from bot_program.asset_engine.runner import run_all_asset_bots
        cfg = _config(self.user, enabled=False)
        trade = _open_paper_row(cfg, "DSB1")
        for desked in (False, True):
            with self.subTest(desked=desked), \
                    patch(DESK, return_value=desked), \
                    patch(ROUTER, return_value=_crossed_client()) as router:
                out = run_all_asset_bots()
                self.assertEqual(bool(out.get("desk")), desked)
                self.assertEqual(out["configs_ticked"], 0)
                router.assert_not_called()
                trade.refresh_from_db()
                self.assertEqual(trade.status, "OPEN")


class TheBrainPressSaysWhatItLeavesTests(TestCase):
    def setUp(self):
        self.op = User.objects.create_superuser("dis_brain", "op@x.x", "x")
        self.client.force_login(self.op)

    def _press(self, cfg):
        resp = self.client.post(reverse("brain_disable_manual"),
                                {"config_id": cfg.id})
        self.assertEqual(resp.status_code, 302)
        return self.client.session["brain_propose_result"]["msg"]

    def test_a_press_over_open_positions_says_they_are_not_managed(self):
        cfg = _config(self.op, "forex")
        _open_paper_row(cfg, "DSB2")
        _open_paper_row(cfg, "DSB3")
        msg = self._press(cfg)
        cfg.refresh_from_db()
        self.assertFalse(cfg.enabled)
        self.assertIn("Manual forex is DISABLED", msg)
        self.assertIn("Its 2 open positions are NOT MANAGED", msg)
        self.assertIn("A paper position has no stop at all", msg)
        # Never promises a bracket: an unprotected live entry has none.
        self.assertIn("what rests at the broker, if anything", msg)
        self.assertIn("Close them on Positions", msg)
        self.assertNotIn("manages what is open", msg)

    def test_a_press_over_nothing_open_says_nothing_is_left_unmanaged(self):
        msg = self._press(_config(self.op, "stock"))
        self.assertIn("Manual stock is DISABLED", msg)
        self.assertIn("nothing is left unmanaged", msg)
        self.assertNotIn("NOT MANAGED", msg)

    def test_a_second_press_still_names_what_is_unmanaged(self):
        cfg = _config(self.op, "stock", enabled=False)
        _open_paper_row(cfg, "DSB4")
        msg = self._press(cfg)
        self.assertIn("Manual stock was already disabled", msg)
        self.assertIn("Its open position is NOT MANAGED", msg)

    def test_the_page_names_the_cost_before_the_press(self):
        from brain.models import BrainReport
        BrainReport.objects.create(
            regime_label="trending", regime_confidence=0.6,
            portfolio_health_score=0.5, rule_status_overlay={},
            top_concerns=[{"kind": "discretionary_drift", "severity": 0.45,
                           "ref": "manual_take",
                           "text": "manual_take used outside commodities."}])
        forex = _config(self.op, "forex")
        _open_paper_row(forex, "DSB5")
        _config(self.op, "stock")
        html = self.client.get(reverse("brain_dashboard")).content.decode()
        self.assertIn("Disable manual &middot; forex", html)
        self.assertIn("Disabling stops the platform managing", html)
        self.assertIn("Open now: forex 1, stock 0.", html)
        self.assertIn(reverse("positions_list"), html)


class BotOffSaysWhatItLeavesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dis_cmd", password="x")

    def _off(self, cfg):
        out = StringIO()
        call_command("bot", "off", str(cfg.id), stdout=out)
        return out.getvalue()

    def test_bot_off_over_an_open_position_says_it_is_not_managed(self):
        cfg = _config(self.user)
        _open_paper_row(cfg, "DSB6")
        text = self._off(cfg)
        cfg.refresh_from_db()
        self.assertFalse(cfg.enabled)
        self.assertIn("DISABLED", text)
        self.assertIn("Its open position is NOT MANAGED", text)
        self.assertIn("with no symbols it opens nothing on its own", text)

    def test_bot_off_never_calls_re_enabling_harmless_on_a_bot_with_symbols(self):
        cfg = _config(self.user, name="Trend", symbols=["DSB7"])
        _open_paper_row(cfg, "DSB7")
        text = self._off(cfg)
        self.assertIn("NOT MANAGED", text)
        self.assertIn("also resumes its entries", text)
        self.assertNotIn("opens nothing on its own", text)

    def test_bot_off_over_nothing_open_adds_no_warning(self):
        text = self._off(_config(self.user))
        self.assertIn("DISABLED", text)
        self.assertNotIn("NOT MANAGED", text)
