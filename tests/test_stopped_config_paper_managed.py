"""A stopped config's paper rows stay managed (2026-10-08).

A paper row sat OPEN for weeks with nothing running its stop: its config was
off (or the platform paused), and the runner skipped a config stopped by
hand, by the kill switch, or with no record, whole. A paper row has nothing
resting at a broker, so it lost its stop outright, and the first tick that
acted booked it at the far price it saw (-8.12R).

The reasons the runner leaves those configs alone are all about a BROKER:
the kill switch leaves real rows for reconciliation by hand, and a manage
pass also books a WORKING entry that has filled. A paper row has no broker.
So, while the bot tick runs, a PAPER row is managed whatever stopped its
config: exits only, never an entry. REAL rows (live and eToro demo) are not
touched by this pass: never routed, never polled, never closed.

Run with:  python manage.py test tests.test_stopped_config_paper_managed
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase

from bot_program.asset_engine import disarm
from tests.test_disabled_config_unmanaged import (DESK, ROUTER, _config,
                                                  _open_paper_row)


def _real_row(cfg, symbol, *, working=False):
    from bot_program.models import AssetBotTrade
    from instruments.models import Instrument
    Instrument.objects.get_or_create(
        symbol=symbol,
        defaults={"name": symbol, "asset_class": cfg.asset_class})
    meta = {"broker": "etoro", "broker_env": "live"}
    if working:
        meta.update(entry_working=True, qty_requested=10.0)
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side="BUY",
        qty=Decimal("10"), entry_price=Decimal("100"),
        stop_loss=Decimal("95"), take_profit=Decimal("110"),
        status="OPEN", paper=False, broker_order_id="77" if working else "",
        metadata=meta)


class _Router:
    """client_for_symbol stand-in: every client marks 94 (past the 95
    stop), and every symbol it was asked for is kept."""

    def __init__(self):
        self.symbols = []

    def __call__(self, user, symbol, cfg=None, *a, **kw):
        self.symbols.append(symbol)
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "94.00"}
        return client


def _stops(op):
    def hand(cfg):
        disarm.disable_config(cfg, by=disarm.BY_BOT_OFF, why="by hand",
                              who=op.username)

    def killed(cfg):
        disarm.disable_config(cfg, by=disarm.BY_KILL_SWITCH, why="flatten",
                              who=op.username)

    def unrecorded(cfg):
        cfg.enabled = False
        cfg.save(update_fields=["enabled"])

    return (hand, killed, unrecorded)


class APaperRowOfAStoppedConfigIsManagedTests(TestCase):
    def setUp(self):
        self.op = User.objects.create_superuser("spm_op", "spm@x.x", "x")

    def test_run_asset_bot_tick_stops_out_the_paper_row_and_not_the_real(self):
        from bot_program.asset_engine.runner import run_asset_bot_tick
        for i, stop in enumerate(_stops(self.op)):
            with self.subTest(stop=stop.__name__):
                cfg = _config(self.op, name=f"Trend {i}", symbols=["SPMA"])
                paper = _open_paper_row(cfg, "SPMA")
                real = _real_row(cfg, "SPMR")
                stop(cfg)
                router = _Router()
                with patch(ROUTER, side_effect=router):
                    out = run_asset_bot_tick(cfg.id)
                self.assertEqual(out["status"], "ok")
                self.assertTrue(out["paper_only"])
                self.assertEqual(out["managed"], 1)
                self.assertEqual(out["opened"], [])
                paper.refresh_from_db()
                self.assertEqual(paper.status, "CLOSED")
                self.assertIn("closed:SL", paper.reason)
                real.refresh_from_db()
                self.assertEqual(real.status, "OPEN")
                self.assertNotIn("SPMR", router.symbols)
                cfg.refresh_from_db()
                self.assertFalse(cfg.enabled)

    def test_both_fleet_passes_manage_it_after_the_braked_pass(self):
        from bot_program.asset_engine.runner import run_all_asset_bots
        for desked in (False, True):
            with self.subTest(desked=desked):
                cfg = _config(self.op, name=f"Fleet {int(desked)}",
                              symbols=["SPMF"])
                paper = _open_paper_row(cfg, "SPMF")
                real = _real_row(cfg, "SPMG")
                _stops(self.op)[0](cfg)
                router = _Router()
                with patch(DESK, return_value=desked), \
                        patch(ROUTER, side_effect=router):
                    out = run_all_asset_bots()
                self.assertEqual(out["configs_ticked"], 0)
                self.assertEqual(out["braked"], [])
                (summary,) = out["paper_only"]
                self.assertEqual(summary["config_id"], cfg.pk)
                self.assertEqual(summary["managed"], 1)
                paper.refresh_from_db()
                self.assertEqual(paper.status, "CLOSED")
                real.refresh_from_db()
                self.assertEqual(real.status, "OPEN")
                self.assertNotIn("SPMG", router.symbols)

    def test_it_never_scans_proposes_or_enters(self):
        from bot_program.asset_engine.base import AssetBot
        from bot_program.asset_engine.runner import (run_all_asset_bots,
                                                     run_asset_bot_tick)
        cfg = _config(self.op, name="Never enters", symbols=["SPMN"])
        _open_paper_row(cfg, "SPMN")
        _stops(self.op)[2](cfg)
        mocks = {}
        for name in ("can_open_new", "scan_symbol", "propose_entry",
                     "execute_entry"):
            p = patch.object(AssetBot, name, side_effect=AssertionError)
            mocks[name] = p.start()
            self.addCleanup(p.stop)
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "100.00"}
        for desked in (False, True):
            with patch(DESK, return_value=desked), \
                    patch(ROUTER, return_value=client):
                out = run_all_asset_bots()
            self.assertEqual(out["paper_only"][0]["status"], "ok")
        with patch(ROUTER, return_value=client):
            self.assertEqual(run_asset_bot_tick(cfg.id)["status"], "ok")
        for name, mock in mocks.items():
            with self.subTest(method=name):
                mock.assert_not_called()

    def test_a_working_real_entry_is_never_polled(self):
        from bot_program.asset_engine.base import AssetBot
        from bot_program.asset_engine.runner import run_asset_bot_tick
        cfg = _config(self.op, name="Working", symbols=["SPMW"])
        _open_paper_row(cfg, "SPMP")
        working = _real_row(cfg, "SPMW", working=True)
        _stops(self.op)[1](cfg)
        with patch.object(AssetBot, "_poll_working_entry",
                          side_effect=AssertionError) as poll, \
                patch(ROUTER, side_effect=_Router()):
            out = run_asset_bot_tick(cfg.id)
        poll.assert_not_called()
        self.assertEqual(out["status"], "ok")
        working.refresh_from_db()
        self.assertEqual(working.status, "OPEN")
        self.assertTrue(working.metadata["entry_working"])

    def test_only_real_rows_left_means_skipped_as_before(self):
        from bot_program.asset_engine.runner import (run_all_asset_bots,
                                                     run_asset_bot_tick)
        cfg = _config(self.op, name="Real only", symbols=["SPMQ"])
        real = _real_row(cfg, "SPMQ")
        _stops(self.op)[0](cfg)
        router = _Router()
        with patch(ROUTER, side_effect=router):
            out = run_asset_bot_tick(cfg.id)
            fleet = run_all_asset_bots()
        self.assertEqual(out, {"status": "skipped", "reason": "disabled",
                               "config_id": cfg.id})
        self.assertEqual(fleet["paper_only"], [])
        self.assertEqual(router.symbols, [])
        real.refresh_from_db()
        self.assertEqual(real.status, "OPEN")

    def test_a_braked_config_is_managed_once_by_the_braked_pass(self):
        """The row stays OPEN after the braked pass (a mark of 100, not
        past the 95 stop), so the paper-only pass could still list it: it
        must not (2026-10-15 review: with the row closed by the first pass
        this test held whatever manages_paper_only returned)."""
        from bot_program.asset_engine.runner import run_all_asset_bots
        cfg = _config(self.op, name="Braked", symbols=["SPMB"])
        row = _open_paper_row(cfg, "SPMB")
        disarm.disable_config(cfg, by=disarm.BY_EYE, why="group /stop",
                              who=self.op.username)
        seen = []

        def router(user, symbol, cfg=None, *a, **kw):
            seen.append(symbol)
            client = MagicMock()
            client.ticker.return_value = {"lastPrice": "100.00"}
            return client

        with patch(ROUTER, side_effect=router):
            out = run_all_asset_bots()
        self.assertEqual(len(out["braked"]), 1)
        self.assertEqual(out["paper_only"], [])
        self.assertEqual(seen.count("SPMB"), 1)
        row.refresh_from_db()
        self.assertEqual(row.status, "OPEN")

    def test_re_enabled_since_the_listing_is_not_managed_here(self):
        from bot_program.asset_engine.runner import manage_stopped_paper
        cfg = _config(self.op, name="Re-armed", symbols=["SPME"])
        row = _open_paper_row(cfg, "SPME")
        with patch(ROUTER, side_effect=_Router()) as router:
            out = manage_stopped_paper(cfg.id)
        self.assertEqual(out["status"], "skipped")
        router.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, "OPEN")

    def test_the_master_switch_off_runs_nothing(self):
        from bot_program.tasks import tick_all_asset_bots
        from core.platform_control import PlatformComponent
        cfg = _config(self.op, name="Paused", symbols=["SPMS"])
        row = _open_paper_row(cfg, "SPMS")
        _stops(self.op)[2](cfg)
        PlatformComponent.objects.update_or_create(
            key="platform_master", defaults={"name": "platform_master",
                                             "category": "system",
                                             "is_enabled": False})
        router = _Router()
        with patch(ROUTER, side_effect=router):
            out = tick_all_asset_bots()
        self.assertEqual(out["status"], "skipped")
        self.assertEqual(router.symbols, [])
        row.refresh_from_db()
        self.assertEqual(row.status, "OPEN")


class TheWordsFollowTheRunnerTests(TestCase):
    def setUp(self):
        from tests.test_brake_keeps_managing import _tick
        self.op = User.objects.create_superuser("spm_words", "w@x.x", "x")
        _tick(True)

    def test_a_stop_over_paper_and_real_rows_says_which_stay_managed(self):
        from bot_program.asset_engine.runner import unmanaged_on_disable
        cfg = _config(self.op, name="Both", symbols=["SPMX"])
        _open_paper_row(cfg, "SPMX")
        _open_paper_row(cfg, "SPMY")
        _real_row(cfg, "SPMZ")
        _stops(self.op)[0](cfg)
        text = unmanaged_on_disable(cfg)
        self.assertIn("Its 2 paper positions stay MANAGED", text)
        self.assertIn("its stop and target", text)
        self.assertIn("Its real position is NOT MANAGED", text)
        self.assertNotIn("A paper position has no stop at all", text)

    def test_paper_only_never_says_not_managed(self):
        from bot_program.asset_engine.runner import unmanaged_on_disable
        cfg = _config(self.op, name="Paper only", symbols=["SPMV"])
        _open_paper_row(cfg, "SPMV")
        _stops(self.op)[2](cfg)
        text = unmanaged_on_disable(cfg)
        self.assertIn("Its paper position stays MANAGED", text)
        self.assertNotIn("NOT MANAGED", text)

    def test_with_the_tick_off_the_paper_promise_gives_way(self):
        from bot_program.asset_engine.runner import unmanaged_on_disable
        from tests.test_brake_keeps_managing import _tick
        cfg = _config(self.op, name="Tick off", symbols=["SPMT"])
        _open_paper_row(cfg, "SPMT")
        _stops(self.op)[0](cfg)
        _tick(False)
        text = unmanaged_on_disable(cfg)
        self.assertIn("the bot tick, which is off now: nothing manages it",
                      text)
        self.assertNotIn("stays MANAGED", text)


class TheOptionsSweepIsPaperOnlyTooTests(TestCase):
    """OptionsBot.manage_positions runs its own expiry sweep after the
    base walk: paper_only must narrow that sweep too, or a stopped options
    config's REAL contracts would be force-closed by the paper pass."""

    def test_a_real_option_near_expiry_is_never_closed_by_the_paper_pass(self):
        from django.utils import timezone
        from bot_program.asset_engine.base import make_bot
        from bot_program.asset_models import AssetBotConfig, AssetBotTrade
        op = User.objects.create_user("spm_opts", password="x")
        cfg = AssetBotConfig.objects.create(
            user=op, asset_class="options", name="Options", enabled=False,
            mode="paper", capital=Decimal("10000"), symbols=[])
        expiry = timezone.now().date().isoformat()

        def option(symbol, paper):
            return AssetBotTrade.objects.create(
                config=cfg, asset_class="options", symbol=symbol, side="BUY",
                qty=Decimal("1"), entry_price=Decimal("2"),
                stop_loss=Decimal("1"), take_profit=Decimal("4"),
                status="OPEN", paper=paper,
                metadata={"expiry": expiry, "initial_stop_loss": 1.0})

        real = option("SPMOR", paper=False)
        paper = option("SPMOP", paper=True)
        router = _Router()
        with patch(ROUTER, side_effect=router), \
                patch("bot_program.asset_engine.options_bot."
                      "current_premium_for_trade",
                      return_value=Decimal("2.5")):
            make_bot(cfg).manage_positions(paper_only=True)
        real.refresh_from_db()
        self.assertEqual(real.status, "OPEN")
        self.assertNotIn("SPMOR", router.symbols)
        paper.refresh_from_db()
        self.assertEqual(paper.status, "CLOSED")
        self.assertIn("EXPIRY_CLOSE", paper.reason)
