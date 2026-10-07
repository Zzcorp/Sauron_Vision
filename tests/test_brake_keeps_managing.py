"""A brake keeps managing; every disable is recorded (2026-10-07).

PG #138 sat OPEN on config 26 from 2026-10-06 13:12 UTC, when Morgul's G1
brake stopped the config for a booking made while NYSE was shut. The runner
skipped every disabled config whole, on purpose: the kill switch, `bot
off`, the HQ toggle and the brake all wrote the same enabled=False and
nothing recorded which of them had done it, so a runner that managed
disabled configs would have closed rows the kill switch left for
reconciliation by hand. The brake meant to stop new entries therefore also
switched off the position's time stop, trailing, break-even, the weekend
and event windows and the venue-mirrored soft stop.

Pinned here (bot_program/asset_engine/disarm.py and its callers):
  - every path that turns an AssetBotConfig off records who did it
    (extras["disabled_by"]: by, at, why, who), and every path that turns
    one back on clears it; the record survives the heartbeat and the skip
    counters;
  - a brake never relabels a stop it did not make, a hand stop of a braked
    config leaves it as found, and the kill switch supersedes a brake;
  - a malformed or unknown record is no brake; an unknown code is refused;
  - every disabler goes through the helper (source greps);
  - the runner manages a braked config with an OPEN row in both fleet
    passes and in run_asset_bot_tick, never scans it or enters, writes its
    heartbeat, and still skips a hand, kill-switch or unrecorded stop
    whole, and a braked config with nothing open;
  - a WORKING entry of a braked bot config is polled, then withdrawn; one
    that filled is booked; a refused withdrawal is retried; one with no
    order id raises no alert; the manual config's held order is polled and
    booked, never withdrawn;
  - the words: unmanaged_on_disable, why_no_trade, `bot list`, the Eye's
    brake reply and /why, Morgul's brake lines (never promising
    management for a config stopped again by hand), the manual ticket's
    refusal;
  - Morgul G10 watches a braked live config with an open row; feeds stay
    enabled-only;
  - `bot brake` records an enabled config and adopts only an unrecorded
    stop.

Run with:  python manage.py test tests.test_brake_keeps_managing
"""
import inspect
import re
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bot_program import telegram_eye as eye
from bot_program.asset_engine import disarm
from tests.test_disabled_config_unmanaged import (DESK, ROUTER,
                                                  _crossed_client,
                                                  _open_paper_row)

GROUP = "-5337454557"
NOTIFY = "bot_program.notifications.notify_staff"
SNAKE = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")
ACCENTED = re.compile(r"[À-ÖØ-öø-ÿŒœ]")
UTC = dt_tz.utc
#: A Wednesday afternoon: forex open, New York open since 13:30 UTC.
WED = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)


def _op(name="opbrake"):
    return User.objects.create_superuser(name, f"{name}@x.x", "x")


def _bot(user, name, asset_class="stock", *, enabled=True, mode="paper",
         symbols=(), extras=None):
    from bot_program.asset_models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, enabled=enabled,
        mode=mode, symbols=list(symbols), extras=dict(extras or {}),
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
        entry_score_min=0.6, min_signals_for_entry=1, cool_down_minutes=0)


def _row(cfg, symbol="AAPL", *, paper=True, status="OPEN", metadata=None):
    """A bare row, no Instrument (the research seed reads the catalogue)."""
    from bot_program.asset_models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side="BUY",
        qty=Decimal("10"), entry_price=Decimal("100"),
        stop_loss=Decimal("95"), take_profit=Decimal("110"),
        status=status, paper=paper, metadata=dict(metadata or {}))


def _record(cfg):
    cfg.refresh_from_db()
    return (cfg.extras or {}).get(disarm.RECORD_KEY)


def _finding(user, cfgs, label="EURCAD booked while forex was shut"):
    """A G1 finding naming these configs, as Morgul's guard makes one."""
    from bot_program import morgul
    return morgul.GUARD["market_shut"].finding(
        "trade:1", label=label, facts=["Booked at a stale price"],
        user=user, configs=[c.pk for c in cfgs])


def _morgul_brake(user, *cfgs):
    """Morgul's own brake on these configs; the instances are re-read (the
    brake writes through its own copies)."""
    from bot_program import morgul
    out = morgul._brake(_finding(user, cfgs))
    for cfg in cfgs:
        cfg.refresh_from_db()
    return out


def _eye_brake(user, *cfgs):
    """The group's /stop on these configs, the instances re-read."""
    reply = eye.apply_brake(user, [c.pk for c in cfgs])
    for cfg in cfgs:
        cfg.refresh_from_db()
    return reply


def _lines(reply):
    return [str(ln) for ln in reply.lines]


def _component(key, on=True, last_run=None):
    from core.platform_control import PlatformComponent
    PlatformComponent.objects.update_or_create(
        key=key, defaults={"name": key, "category": "system",
                           "is_enabled": on, "last_run_at": last_run})


def _mark(symbol, asset_class, at, source="oanda_stream", last="1.08"):
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    quote = LiveQuote.objects.create(instrument=inst, last=Decimal(last),
                                     source=source)
    LiveQuote.objects.filter(pk=quote.pk).update(updated_at=at)


def _run(*args, **kw):
    out = StringIO()
    call_command(*args, stdout=out, **kw)
    return out.getvalue()


# ── the record ───────────────────────────────────────────────────────────

class TheRecordTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.op = _op()
        self.client.force_login(self.op)

    def _assert_record(self, cfg, by, *, why=None, who=None):
        rec = _record(cfg)
        self.assertFalse(cfg.enabled)
        self.assertIsInstance(rec, dict)
        self.assertEqual(set(rec), {"by", "at", "why", "who"})
        self.assertEqual(rec["by"], by)
        at = datetime.fromisoformat(rec["at"])
        self.assertIsNotNone(at.tzinfo)
        self.assertLess(abs((timezone.now() - at).total_seconds()), 120)
        if why is not None:
            self.assertEqual(rec["why"], why)
        if who is not None:
            self.assertEqual(rec["who"], who)
        return rec

    def test_every_disabler_writes_its_record(self):
        from bot_program import alarm
        from bot_program.engine.kill_switch import execute_kill_switch
        from bot_program.management.commands.seed_bots import reset_bots
        from bot_program.management.commands.seed_research_fleet import (
            reset_research_fleet, seed_research_fleet)
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        with self.subTest("kill switch"):
            cfg = _bot(self.op, "Killed")
            execute_kill_switch(user=self.op, reason="the presser's reason")
            self._assert_record(cfg, disarm.BY_KILL_SWITCH,
                                why="the presser's reason",
                                who=self.op.username)
        with self.subTest("bot off"):
            cfg = _bot(self.op, "Shell off")
            _run("bot", "off", str(cfg.pk))
            self._assert_record(cfg, disarm.BY_BOT_OFF, why="bot off",
                                who="shell")
        with self.subTest("HQ toggle"):
            cfg = _bot(self.op, "Hq off")
            self.client.post(reverse("hq_toggle_asset_bot"),
                             {"config_id": cfg.pk})
            self._assert_record(cfg, disarm.BY_HQ_TOGGLE,
                                why="the HQ toggle", who=self.op.username)
        with self.subTest("system map toggle"):
            cfg = _bot(self.op, "Map off")
            resp = self.client.post(reverse("system_map_toggle"),
                                    {"kind": "bot", "key": cfg.pk})
            self.assertEqual(resp.json()["enabled"], False)
            self._assert_record(cfg, disarm.BY_SYSTEM_MAP,
                                why="the system map toggle",
                                who=self.op.username)
        with self.subTest("brain disable"):
            cfg = _bot(self.op, MANUAL_CONFIG_NAME, "forex")
            self.client.post(reverse("brain_disable_manual"),
                             {"config_id": cfg.pk})
            self._assert_record(cfg, disarm.BY_BRAIN,
                                why="Disable manual on the brain page",
                                who=self.op.username)
        with self.subTest("seed_bots --reset"):
            cfg = _bot(self.op, "starter_megacaps")
            _row(cfg, status="CLOSED")
            reset_bots(self.op)
            self._assert_record(cfg, disarm.BY_SEED, why="seed_bots --reset",
                                who="shell")
        with self.subTest("reset_research_fleet"):
            cfg = _bot(self.op, "research_stock_5",
                       extras={"research_fleet": True})
            _row(cfg, status="CLOSED")
            reset_research_fleet(self.op)
            self._assert_record(cfg, disarm.BY_SEED,
                                why="seed_research_fleet --reset",
                                who="shell")
        with self.subTest("Eye /stop"):
            cfg = _bot(self.op, "Eye one")
            eye.route("stop", str(cfg.pk), self.op, GROUP)
            self._assert_record(cfg, disarm.BY_EYE, why=f"/stop {cfg.pk}",
                                who=self.op.username)
        with self.subTest("Eye /stopall"):
            cfg = _bot(self.op, "Eye all")
            eye.route("stopall", "", self.op, GROUP)
            self._assert_record(cfg, disarm.BY_EYE, why="/stopall",
                                who=self.op.username)
        with self.subTest("alarm /stopall"):
            cfg = _bot(self.op, "Alarm all")
            alarm.stop_all()
            self._assert_record(cfg, disarm.BY_ALARM, why="/stopall",
                                who="the alarm chat")
        with self.subTest("Morgul brake"):
            cfg = _bot(self.op, "Forex swing", "forex")
            _morgul_brake(self.op, cfg)
            rec = self._assert_record(cfg, disarm.BY_MORGUL, who="Morgul")
            self.assertTrue(rec["why"].startswith("Market-shut booking:"),
                            rec["why"])
        with self.subTest("research stand-down"):
            # Last: a seed run reads the catalogue. A budget of 0 plans no
            # config, so this one is no longer in the plan.
            cfg = _bot(self.op, "research_forex_9", "forex",
                       symbols=["EURUSD"], extras={"research_fleet": True})
            _row(cfg, "EURUSD", status="CLOSED")
            seed_research_fleet(self.op, budget=0)
            self._assert_record(
                cfg, disarm.BY_SEED,
                why="seed_research_fleet: no longer in the plan",
                who="shell")
            self.assertEqual(cfg.symbols, [])

    def test_reenabling_clears_the_record(self):
        from bot_program.management.commands.seed_bots import seed_bots
        from instruments.models import Instrument

        def braked(name, asset_class="stock"):
            cfg = _bot(self.op, name, asset_class)
            disarm.disable_config(cfg, by=disarm.BY_MORGUL, who="Morgul",
                                  why="Market-shut booking: test")
            return cfg

        with self.subTest("bot on"):
            cfg = braked("Shell on")
            out = _run("bot", "on", str(cfg.pk))
            self.assertIn("ENABLED", out)
            self.assertIn("(the stop by Morgul's brake is cleared)", out)
            self.assertIsNone(_record(cfg))
            self.assertTrue(cfg.enabled)
        with self.subTest("HQ toggle"):
            cfg = braked("Hq on")
            resp = self.client.post(reverse("hq_toggle_asset_bot"),
                                    {"config_id": cfg.pk})
            said = " ".join(str(m) for m in get_messages(resp.wsgi_request))
            self.assertIn("ENABLED.", said)
            self.assertIn("The stop by Morgul's brake is cleared.", said)
            self.assertIsNone(_record(cfg))
            self.assertTrue(cfg.enabled)
        with self.subTest("system map toggle"):
            cfg = braked("Map on")
            resp = self.client.post(reverse("system_map_toggle"),
                                    {"kind": "bot", "key": cfg.pk})
            self.assertEqual(resp.json()["enabled"], True)
            self.assertIsNone(_record(cfg))
            self.assertTrue(cfg.enabled)
        with self.subTest("seed_bots --activate"):
            Instrument.objects.get_or_create(
                symbol="AAPL", defaults={"name": "AAPL",
                                         "asset_class": "stock"})
            cfg = braked("starter_megacaps")
            seed_bots(self.op, activate=True)
            self.assertIsNone(_record(cfg))
            self.assertTrue(cfg.enabled)

    def test_the_record_survives_a_heartbeat_and_a_skip(self):
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.safety import write_heartbeat
        from bot_program.asset_models import AssetBotConfig
        cfg = _bot(self.op, "Survivor")
        # a tick's own copy, loaded before the brake landed
        stale = AssetBotConfig.objects.get(pk=cfg.pk)
        _eye_brake(self.op, cfg)
        rec = _record(cfg)
        self.assertEqual(rec["by"], disarm.BY_EYE)
        write_heartbeat(stale, status="OK", note="a tick")
        skips.record(stale, "AAPL", skips.NO_SIGNALS, "nothing fresh")
        self.assertEqual(_record(cfg), rec)
        self.assertEqual(cfg.extras["last_tick_note"], "a tick")
        self.assertIn("AAPL", cfg.extras["skips"])
        self.assertTrue(disarm.keeps_managing(cfg))

    def test_a_brake_never_relabels_a_stop_it_did_not_make(self):
        cfg = _bot(self.op, "Forex swing", "forex")
        _row(cfg, "EURUSD")
        _run("bot", "off", str(cfg.pk))
        reply = _eye_brake(self.op, cfg)
        lines = _lines(reply)
        self.assertIn("Already stopped", lines)
        line = next(ln for ln in lines
                    if ln.startswith(f"{eye.BULLET}Forex swing #{cfg.pk}"))
        self.assertIn("stopped by `bot off` on the server", line)
        self.assertTrue(line.endswith(" — not managed while off"), line)
        self.assertEqual(_record(cfg)["by"], disarm.BY_BOT_OFF)
        self.assertFalse(disarm.keeps_managing(cfg))
        self.assertNotIn(eye.MANAGING_WORDS, lines)
        self.assertEqual(reply.meta["stopped"], [])

    def test_a_hand_stop_of_a_braked_config_leaves_it_as_found(self):
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        cfg = _bot(self.op, MANUAL_CONFIG_NAME)
        _row(cfg)
        _eye_brake(self.op, cfg)
        rec = _record(cfg)
        out = _run("bot", "off", str(cfg.pk))
        self.assertIn("already OFF (unchanged)", out)
        self.assertIn("stopped by the Telegram group's /stop", out)
        self.assertIn("stays MANAGED", out)
        self.assertEqual(_record(cfg), rec)
        resp = self.client.post(reverse("brain_disable_manual"),
                                {"config_id": cfg.pk})
        self.assertEqual(resp.status_code, 302)
        msg = self.client.session["brain_propose_result"]["msg"]
        self.assertIn("Manual stock was already disabled — stopped by the "
                      "Telegram group's /stop", msg)
        self.assertIn("stays MANAGED", msg)
        self.assertEqual(_record(cfg), rec)
        self.assertTrue(disarm.keeps_managing(cfg))

    def test_the_kill_switch_supersedes_a_brake(self):
        from bot_program.asset_engine.runner import run_all_asset_bots
        from bot_program.engine.kill_switch import execute_kill_switch
        cfg = _bot(self.op, "Stocks live", mode="live")
        row = _row(cfg, paper=False, metadata={"protected": True})
        _morgul_brake(self.op, cfg)
        self.assertTrue(disarm.keeps_managing(cfg))
        with patch("bot_program.engine.kill_switch._close_asset_trade",
                   side_effect=RuntimeError("the venue refused")):
            results = execute_kill_switch(user=self.op, reason="flatten now")
        self.assertEqual(results["asset_bots_disabled"], 0)
        self.assertEqual(len(results["errors"]), 1)
        rec = _record(cfg)
        self.assertEqual(rec["by"], disarm.BY_KILL_SWITCH)
        self.assertEqual(rec["why"], "flatten now")
        self.assertFalse(disarm.keeps_managing(cfg))
        with patch(ROUTER, return_value=_crossed_client()) as router:
            out = run_all_asset_bots()
        router.assert_not_called()
        self.assertEqual(out["braked"], [])
        row.refresh_from_db()
        self.assertEqual(row.status, "OPEN")

    def test_an_unknown_or_malformed_record_is_not_a_brake(self):
        from bot_program.asset_engine.runner import run_asset_bot_tick
        for i, bad in enumerate(("morgul", {"by": "nonsense"}, {"by": None},
                                 {"who": "Morgul"}, [], {"by": ["morgul"]},
                                 {"by": {"x": 1}})):
            with self.subTest(record=bad):
                cfg = _bot(self.op, f"Odd {i}", enabled=False,
                           extras={disarm.RECORD_KEY: bad})
                _row(cfg)
                self.assertEqual(disarm.record_of(cfg), {})
                self.assertFalse(disarm.keeps_managing(cfg))
                self.assertEqual(disarm.record_words(cfg),
                                 disarm.NO_RECORD_WORDS)
                with patch(ROUTER) as router:
                    out = run_asset_bot_tick(cfg.id)
                router.assert_not_called()
                self.assertEqual(out, {"status": "skipped",
                                       "reason": "disabled",
                                       "config_id": cfg.id})
        # a brake's record on a config that is ON again is not a brake
        on = _bot(self.op, "Rearmed", extras={disarm.RECORD_KEY: {
            "by": disarm.BY_MORGUL, "at": timezone.now().isoformat(),
            "why": "x", "who": "Morgul"}})
        self.assertFalse(disarm.keeps_managing(on))
        self.assertEqual(disarm.record_words(on), "")

    def test_disable_config_refuses_an_unknown_code(self):
        cfg = _bot(self.op, "Refused")
        with self.assertRaises(ValueError):
            disarm.disable_config(cfg, by="the_cat", why="x", who="y")
        cfg.refresh_from_db()
        self.assertTrue(cfg.enabled)
        self.assertNotIn(disarm.RECORD_KEY, cfg.extras or {})

    def test_every_assetbotconfig_disabler_goes_through_the_helper(self):
        from bot_program.engine import kill_switch
        from bot_program.management.commands import bot as bot_cmd
        from bot_program.management.commands import seed_bots as sb
        from bot_program.management.commands import seed_research_fleet as srf
        from dashboard import views_admin_hq, views_brain, views_topology
        fns = (eye.apply_brake, kill_switch.execute_kill_switch,
               bot_cmd.Command.handle, views_admin_hq.hq_toggle_asset_bot,
               views_topology.system_map_toggle,
               views_brain.brain_disable_manual, srf.seed_research_fleet,
               srf.reset_research_fleet, sb.seed_bots, sb.reset_bots)
        for fn in fns:
            src = inspect.getsource(fn)
            with self.subTest(fn=fn.__qualname__):
                self.assertTrue("disable_config(" in src
                                or "enable_config(" in src)
                for needle in ("cfg.enabled = False", "cfg.enabled = True",
                               "cfg.enabled = not cfg.enabled",
                               "cfg.enabled = enable"):
                    self.assertNotIn(needle, src)
        # the legacy BotConfig loop keeps its own write, and only it
        self.assertEqual(inspect.getsource(kill_switch)
                         .count("config.enabled = False"), 1)


# ── the runner ───────────────────────────────────────────────────────────

class TheRunnerTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.op = _op()

    def _braked(self, name="Trend", *, symbols=("DSB1",)):
        cfg = _bot(self.op, name, symbols=symbols)
        row = _open_paper_row(cfg, "DSB1")
        _eye_brake(self.op, cfg)
        self.assertTrue(disarm.keeps_managing(cfg))
        return cfg, row

    def test_a_braked_config_is_managed_by_both_fleet_passes(self):
        from bot_program.asset_engine.runner import run_all_asset_bots
        for desked in (False, True):
            with self.subTest(desked=desked):
                idle = _bot(self.op, f"Idle {int(desked)}")
                cfg, row = self._braked(f"Trend {int(desked)}")
                with patch(DESK, return_value=desked), \
                        patch(ROUTER, return_value=_crossed_client()):
                    out = run_all_asset_bots()
                self.assertEqual(bool(out.get("desk")), desked)
                row.refresh_from_db()
                self.assertEqual(row.status, "CLOSED")
                (summary,) = out["braked"]
                self.assertEqual(summary["status"], "ok")
                self.assertEqual(summary["config_id"], cfg.pk)
                self.assertTrue(summary["braked"])
                self.assertEqual(summary["managed"], 1)
                self.assertEqual(summary["opened"], [])
                # configs_ticked counts the enabled config only
                self.assertEqual(out["configs_ticked"], 1)
                idle.enabled = False
                idle.save(update_fields=["enabled"])
                cfg.refresh_from_db()
                self.assertFalse(cfg.enabled)

    def test_a_braked_config_never_scans_or_enters(self):
        from bot_program.asset_engine.base import AssetBot
        from bot_program.asset_engine.runner import (run_all_asset_bots,
                                                     run_asset_bot_tick)
        from bot_program.models import DeskPlan
        cfg, row = self._braked()
        mocks = {}
        patches = [patch.object(AssetBot, name, side_effect=AssertionError)
                   for name in ("can_open_new", "scan_symbol",
                                "propose_entry", "execute_entry")]
        for p in patches:
            mocks[p.attribute] = p.start()
            self.addCleanup(p.stop)
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "100.00"}
        for desked in (False, True):
            with patch(DESK, return_value=desked), \
                    patch(ROUTER, return_value=client):
                out = run_all_asset_bots()
            self.assertEqual(out["braked"][0]["status"], "ok")
        with patch(ROUTER, return_value=client):
            self.assertEqual(run_asset_bot_tick(cfg.id)["status"], "ok")
        for name, mock in mocks.items():
            with self.subTest(method=name):
                mock.assert_not_called()
        self.assertFalse(DeskPlan.objects.exists())
        row.refresh_from_db()
        self.assertEqual(row.status, "OPEN")

    def test_run_asset_bot_tick_on_a_braked_config_manages_only(self):
        from bot_program.asset_engine.runner import run_asset_bot_tick
        cfg, row = self._braked()
        with patch(ROUTER, return_value=_crossed_client()):
            out = run_asset_bot_tick(cfg.id)
        self.assertEqual(out["status"], "ok")
        self.assertTrue(out["braked"])
        self.assertEqual(out["by"], disarm.BY_EYE)
        self.assertEqual(out["opened"], [])
        self.assertEqual(out["managed"], 1)
        self.assertEqual(out["withdrawn"], [])
        self.assertIn("managing only, opening nothing", out["gate_reason"])
        row.refresh_from_db()
        self.assertEqual(row.status, "CLOSED")

    def test_a_hand_kill_switch_or_unrecorded_stop_is_still_skipped_whole(self):
        from bot_program.asset_engine.runner import (run_all_asset_bots,
                                                     run_asset_bot_tick)

        def hand(cfg):
            _run("bot", "off", str(cfg.pk))

        def killed(cfg):
            disarm.disable_config(cfg, by=disarm.BY_KILL_SWITCH,
                                  why="flatten", who=self.op.username)

        def unrecorded(cfg):
            cfg.enabled = False
            cfg.save(update_fields=["enabled"])

        for i, stop in enumerate((hand, killed, unrecorded)):
            with self.subTest(stop=stop.__name__):
                cfg = _bot(self.op, f"Stopped {i}", symbols=["DSB1"])
                row = _open_paper_row(cfg, "DSB1")
                stop(cfg)
                with patch(ROUTER, return_value=_crossed_client()) as router:
                    out = run_asset_bot_tick(cfg.id)
                    fleet = run_all_asset_bots()
                router.assert_not_called()
                self.assertEqual(out, {"status": "skipped",
                                       "reason": "disabled",
                                       "config_id": cfg.id})
                self.assertEqual(fleet["braked"], [])
                row.refresh_from_db()
                self.assertEqual(row.status, "OPEN")

    def test_a_braked_config_without_open_rows_is_not_ticked(self):
        from bot_program.asset_engine.runner import run_all_asset_bots
        cfg = _bot(self.op, "Nothing open", symbols=["DSB1"])
        _row(cfg, "DSB1", status="CLOSED")
        _eye_brake(self.op, cfg)
        self.assertTrue(disarm.keeps_managing(cfg))
        with patch(ROUTER, return_value=_crossed_client()) as router:
            out = run_all_asset_bots()
        router.assert_not_called()
        self.assertEqual(out["braked"], [])
        cfg.refresh_from_db()
        self.assertNotIn("last_tick_at", cfg.extras)

    def test_a_braked_config_writes_its_heartbeat(self):
        from bot_program.asset_engine.runner import run_all_asset_bots
        old = (timezone.now() - timedelta(hours=2)).isoformat()
        cfg = _bot(self.op, "Beating", symbols=["DSB1"],
                   extras={"last_tick_at": old})
        row = _open_paper_row(cfg, "DSB1")
        _eye_brake(self.op, cfg)
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "100.00"}
        with patch(ROUTER, return_value=client):
            run_all_asset_bots()
        cfg.refresh_from_db()
        self.assertGreater(datetime.fromisoformat(cfg.extras["last_tick_at"]),
                           datetime.fromisoformat(old))
        self.assertEqual(cfg.extras["last_tick_status"], "OK")
        self.assertIn("managing only, opening nothing",
                      cfg.extras["last_tick_note"])
        self.assertIn("stopped by the Telegram group's /stop",
                      cfg.extras["last_tick_note"])
        self.assertEqual(cfg.extras[disarm.RECORD_KEY]["by"], disarm.BY_EYE)
        row.refresh_from_db()
        self.assertEqual(row.status, "OPEN")


# ── a WORKING entry under a brake ────────────────────────────────────────

def _working_row(cfg, order_id="101"):
    """A WORKING live entry, booked as the engine books one, sent minutes
    ago (inside its 26-hour window)."""
    from bot_program.asset_models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol="NVDA", side="BUY",
        qty=Decimal("10"), entry_price=Decimal("100"),
        stop_loss=Decimal("98"), take_profit=Decimal("104"),
        status="OPEN", paper=False, broker_order_id=order_id,
        metadata={"entry_working": True, "qty_requested": 10.0,
                  "protective_order_ids": ["12", "13"],
                  "protective_stop_id": "13", "protected": False,
                  "entry_working_since": (timezone.now()
                                          - timedelta(minutes=10))
                  .isoformat()})


WORKING = {"state": "working", "filled": 0.0, "avgPrice": 0,
           "status": "Submitted"}
FILLED = {"state": "filled", "filled": 10.0, "avgPrice": 99.75,
          "status": "Filled"}
DEAD = {"state": "dead", "filled": 0.0, "avgPrice": 0, "status": "Cancelled"}


def _broker(status=WORKING, cancel_ok=True):
    """A broker client: `status` until the parent is cancelled, dead after
    a confirmed cancel."""
    client = MagicMock()
    client.ticker.return_value = {"lastPrice": "101", "symbol": "NVDA"}
    client.resting_order_ids.return_value = {"12", "13"}
    client.get_positions.return_value = []
    client.position_avg_cost.return_value = None
    box = {"cancelled": False, "seen": []}

    def order_status(oid):
        st = DEAD if box["cancelled"] else status
        box["seen"].append(st["state"])
        return dict(st)

    def cancel_order(oid):
        if str(oid) == "101" and cancel_ok:
            box["cancelled"] = True
        return cancel_ok
    client.order_status.side_effect = order_status
    client.cancel_order.side_effect = cancel_order
    client.box = box
    return client


class TheWorkingEntryTests(TestCase):
    def setUp(self):
        from instruments.models import Instrument
        cache.clear()
        self.addCleanup(cache.clear)
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        self.op = _op()

    def _braked_live(self, name="Work"):
        cfg = _bot(self.op, name, mode="live", symbols=["NVDA"])
        row = _working_row(cfg)
        with patch(ROUTER) as router:
            _morgul_brake(self.op, cfg)
        router.assert_not_called()     # Morgul never reaches the broker
        self.assertTrue(disarm.keeps_managing(cfg))
        return cfg, row

    def _pass(self, cfg, client):
        from bot_program.asset_engine.runner import manage_braked
        with patch(ROUTER, return_value=client):
            return manage_braked(cfg.id)

    def test_a_working_entry_is_polled_then_withdrawn(self):
        cfg, row = self._braked_live()
        client = _broker()
        out = self._pass(cfg, client)
        self.assertEqual(out["status"], "ok")
        # polled first (still working), then withdrawn and proven dead
        self.assertEqual(client.box["seen"][0], "working")
        self.assertEqual(client.box["seen"][-1], "dead")
        client.cancel_order.assert_any_call("101")
        row.refresh_from_db()
        self.assertEqual(row.status, "CANCELED")
        self.assertIn("Morgul's brake", row.metadata["entry_withdrawn_reason"])
        self.assertNotIn("entry_working", row.metadata)
        self.assertEqual(out["withdrawn"], [row.pk])

    def test_a_working_entry_that_filled_is_booked_not_withdrawn(self):
        cfg, row = self._braked_live()
        client = _broker(status=FILLED)
        out = self._pass(cfg, client)
        self.assertEqual(out["status"], "ok")
        client.cancel_order.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, "OPEN")
        self.assertNotIn("entry_working", row.metadata)
        self.assertEqual(float(row.entry_price), 99.75)
        self.assertEqual(out["withdrawn"], [])

    def test_a_refused_withdrawal_stays_working_and_is_retried(self):
        cfg, row = self._braked_live()
        client = _broker(cancel_ok=False)
        self._pass(cfg, client)
        row.refresh_from_db()
        self.assertEqual(row.status, "OPEN")
        self.assertTrue(row.metadata["entry_working"])
        self.assertEqual(client.cancel_order.call_count, 1)
        out = self._pass(cfg, client)
        self.assertEqual(client.cancel_order.call_count, 2)
        client.cancel_order.assert_called_with("101")
        self.assertEqual(out["withdrawn"], [])
        row.refresh_from_db()
        self.assertTrue(row.metadata["entry_working"])

    def test_a_working_entry_with_no_order_id_raises_no_alert_from_the_pass(self):
        from bot_program.asset_models import AssetBotTrade
        cfg, row = self._braked_live()
        AssetBotTrade.objects.filter(pk=row.pk).update(broker_order_id="")
        client = _broker()
        with patch(NOTIFY) as notify:
            out = self._pass(cfg, client)
        notify.assert_not_called()
        client.cancel_order.assert_not_called()
        self.assertEqual(out["withdrawn"], [])
        row.refresh_from_db()
        self.assertTrue(row.metadata["entry_working"])

    def test_the_manual_configs_held_order_is_polled_not_withdrawn(self):
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        cfg = _bot(self.op, MANUAL_CONFIG_NAME, mode="live")
        row = _working_row(cfg)
        _morgul_brake(self.op, cfg)
        self.assertTrue(disarm.keeps_managing(cfg))
        client = _broker()
        self._pass(cfg, client)
        self.assertEqual(client.box["seen"], ["working"])
        client.cancel_order.assert_not_called()
        row.refresh_from_db()
        self.assertTrue(row.metadata["entry_working"])
        self.assertEqual(row.status, "OPEN")
        # it fills: the next pass books it, and nothing is withdrawn
        client = _broker(status=FILLED)
        self._pass(cfg, client)
        client.cancel_order.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, "OPEN")
        self.assertNotIn("entry_working", row.metadata)
        self.assertEqual(float(row.entry_price), 99.75)


# ── the words ────────────────────────────────────────────────────────────

class TheWordsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.op = _op()

    def _assert_eye_style(self, reply):
        text = eye.fit(reply).text()
        self.assertNotIn("None", text)
        self.assertEqual(SNAKE.findall(text), [], text)
        self.assertIsNone(ACCENTED.search(text), text)
        self.assertLessEqual(len(text.split("\n")) - 1, eye.MAX_LINES)
        self.assertLessEqual(len(text), eye.TELEGRAM_MAX_CHARS)

    def test_unmanaged_on_disable_says_managed_for_a_brake(self):
        from bot_program.asset_engine.runner import unmanaged_on_disable
        cfg = _bot(self.op, "Forex swing", "forex", symbols=["EURUSD"])
        _row(cfg, "EURUSD")
        _row(cfg, "GBPUSD")
        _morgul_brake(self.op, cfg)
        text = unmanaged_on_disable(cfg)
        self.assertIn("Its 2 open positions stay MANAGED", text)
        self.assertIn("Morgul's brake", text)
        self.assertIn("ends the management", text)
        self.assertIn("closing them on Positions", text)
        self.assertNotIn("NOT MANAGED", text)
        one = _bot(self.op, "Single", "forex")
        _row(one, "EURUSD")
        _eye_brake(self.op, one)
        self.assertIn("Its open position stays MANAGED: it was stopped by "
                      "the Telegram group's /stop, a brake",
                      unmanaged_on_disable(one))
        # a hand stop still reads today's words
        hand = _bot(self.op, "Hand", "forex", symbols=["EURUSD"])
        _row(hand, "EURUSD")
        _run("bot", "off", str(hand.pk))
        text = unmanaged_on_disable(hand)
        self.assertTrue(text.startswith("Its open position is NOT MANAGED "
                                        "while it stays off"), text)
        self.assertIn("also resumes its entries", text)

    def test_why_no_trade_names_who_and_management(self):
        braked = _bot(self.op, "Braked", "forex")
        _row(braked, "EURUSD")
        _morgul_brake(self.op, braked)
        hand = _bot(self.op, "Handoff", "forex")
        _row(hand, "GBPUSD")
        _run("bot", "off", str(hand.pk))
        bare = _bot(self.op, "Unrecorded", "forex", enabled=False)
        _row(bare, "USDJPY")
        quiet = _bot(self.op, "Quiet", "forex")
        _run("bot", "off", str(quiet.pk))
        out = _run("why_no_trade")
        self.assertIn("^ OFF — stopped by Morgul's brake (Morgul) on ", out)
        self.assertIn("; 1 open, still MANAGED every tick, opening nothing",
                      out)
        self.assertIn("^ OFF — stopped by `bot off` on the server (shell) on",
                      out)
        self.assertIn("; 1 open, NOT managed while it stays off", out)
        self.assertIn("^ OFF — off with no record of who turned it off", out)
        # a record and nothing open: who, and nothing more
        line = next(ln for ln in out.splitlines()
                    if "^ OFF" in ln and ": bot off" in ln
                    and "open" not in ln)
        self.assertIn("stopped by `bot off` on the server", line)
        # never a blocker: a stopped config is a decision
        verdict = out.split("BLOCKERS — fix in this order:")[-1] \
            if "BLOCKERS — fix in this order:" in out else ""
        for name in ("Braked", "Handoff", "Unrecorded", "Quiet"):
            self.assertNotIn(name, verdict)

    def test_bot_list_prints_the_record(self):
        braked = _bot(self.op, "Braked")
        _row(braked)
        _eye_brake(self.op, braked)
        hand = _bot(self.op, "Handoff")
        _run("bot", "off", str(hand.pk))
        running = _bot(self.op, "Running")
        out = _run("bot", "list")
        lines = out.splitlines()
        i = next(n for n, ln in enumerate(lines) if f"[{braked.pk:<3}]" in ln)
        self.assertTrue(lines[i].startswith("  OFF  ["))
        self.assertIn("stopped by the Telegram group's /stop", lines[i + 1])
        self.assertTrue(lines[i + 1].endswith("; still managing"),
                        lines[i + 1])
        j = next(n for n, ln in enumerate(lines) if f"[{hand.pk:<3}]" in ln)
        self.assertIn("stopped by `bot off` on the server (shell)",
                      lines[j + 1])
        self.assertNotIn("still managing", lines[j + 1])
        k = next(n for n, ln in enumerate(lines) if f"[{running.pk:<3}]" in ln)
        self.assertTrue(lines[k].startswith("  ON   ["))
        self.assertFalse(k + 1 < len(lines)
                         and lines[k + 1].startswith("        "))

    def test_the_brake_reply_says_it_keeps_managing(self):
        from bot_program.asset_engine.disarm import enable_config
        live = _bot(self.op, "Stocks core", mode="live")
        _row(live, "AAPL", paper=False)                 # no stop at the broker
        paper = _bot(self.op, "Forex swing", "forex")
        _row(paper, "EURUSD")
        earlier = _bot(self.op, "Metals idle", "commodity")
        _row(earlier, "XAUUSD")
        _eye_brake(self.op, earlier)
        reply = eye.apply_brake(self.op, [live.pk, paper.pk, earlier.pk])
        lines = _lines(reply)
        self.assertIn("Stopped (2)", lines)
        for words in eye.BRAKE_WORDS:
            self.assertIn(words, lines)
        self.assertIn(eye.MANAGING_WORDS, lines)
        line = next(ln for ln in lines
                    if ln.startswith(f"{eye.BULLET}Metals idle #{earlier.pk}"))
        self.assertIn(" — stopped by the Telegram group's /stop on ", line)
        self.assertTrue(line.endswith(" — still managing"), line)
        self.assertIn("Positions left open: 2 (1 live · 1 paper)", lines)
        self.assertIn("Live without a stop at the broker: 1", lines)
        self.assertIn("The stopped bot still runs those stops on every tick.",
                      lines)
        self.assertIn("Paper stops are simulated by the bot, which keeps "
                      "running them.", lines)
        tick_off = ("The bot tick is off now: nothing manages them until it "
                    "is back on.")
        self.assertIn(tick_off, lines)
        self.assertFalse([ln for ln in lines if "nothing protects them" in ln
                          or "pause while" in ln], lines)
        self._assert_eye_style(reply)
        # the tick on: the line is not said
        _component("platform_master")
        _component("pipeline_asset_bots")
        enable_config(live)
        again = eye.apply_brake(self.op, everything=True)
        self.assertNotIn(tick_off, _lines(again))
        self.assertIn(eye.MANAGING_WORDS, _lines(again))
        self._assert_eye_style(again)
        # nothing stopped: no promise of management
        none = eye.apply_brake(self.op, everything=True)
        self.assertNotIn(eye.MANAGING_WORDS, _lines(none))
        self._assert_eye_style(none)

    def test_morgul_brake_lines_say_managing(self):
        from bot_program import morgul
        cfg = _bot(self.op, "Forex swing", "forex")
        _row(cfg, "EURUSD")                                     # paper
        _row(cfg, "GBPUSD", paper=False)                        # bare live
        stopped, already, pks = _morgul_brake(self.op, cfg)
        lines = morgul.brake_lines([("stopped", stopped, already,
                                     morgul._left_open(pks))])
        text = "\n".join(lines)
        self.assertIn(f"Stopped: Forex swing #{cfg.pk} — no position was "
                      f"closed; to re-arm: the server", text)
        self.assertIn("The stopped bots open nothing and keep managing what "
                      "is open", text)
        self.assertIn("At the broker without a stop: 1 — the stopped bot "
                      "still runs their stops every tick", text)
        self.assertIn("Paper positions: 1 — the stopped bot still runs their "
                      "simulated stops", text)
        self.assertNotIn("nothing protects them", text)
        self.assertNotIn("pause while", text)
        back = morgul.back_to_normal(
            [{"name": "Market-shut booking", "label": "EURCAD",
              "braked": True}], timezone.now()).text()
        self.assertIn("stay off, still managing what is open, until re-armed "
                      "on the server", back)

    def test_manual_config_error_names_who(self):
        from bot_program.manual_trade import MANUAL_CONFIG_NAME, _config_error
        cfg = _bot(self.op, MANUAL_CONFIG_NAME, "forex")
        _morgul_brake(self.op, cfg)
        error = _config_error(cfg)
        self.assertIn("The manual config for this class is disabled — stopped "
                      "by Morgul's brake", error)
        self.assertTrue(error.endswith("Re-enable it in the bot fleet to take "
                                       "manual trades again"), error)

    def test_brake_lines_never_promise_management_for_a_config_stopped_again_by_hand(self):
        from bot_program import morgul
        cfg = _bot(self.op, "Forex swing", "forex")
        _row(cfg, "EURUSD")
        stopped, _already, pks = _morgul_brake(self.op, cfg)
        # re-armed on the server, then stopped again by hand
        _run("bot", "on", str(cfg.pk))
        _run("bot", "off", str(cfg.pk))
        self.assertEqual(_record(cfg)["by"], disarm.BY_BOT_OFF)
        left = morgul._left_open(pks)
        self.assertEqual((left["paper"], left["unmanaged"]), (0, 1))
        text = "\n".join(morgul.brake_lines([("earlier", stopped, [], left)]))
        self.assertIn(f"Stopped earlier by the brake: Forex swing #{cfg.pk}",
                      text)
        self.assertIn("The stopped bots open nothing; not managed: 1 — their "
                      "bot was stopped again by hand or by the kill switch",
                      text)
        self.assertNotIn("keep managing what is open", text)

    def test_the_eye_why_says_still_managing(self):
        braked = _bot(self.op, "Stocks core", symbols=["AAPL"])
        _eye_brake(self.op, braked)
        hand = _bot(self.op, "Stocks spare", symbols=["MSFT"])
        _run("bot", "off", str(hand.pk))
        lines = _lines(eye.build_why(self.op, "AAPL"))
        self.assertIn(f"Stocks core #{braked.pk} — stopped by a brake, still "
                      f"managing · paper", lines)
        lines = _lines(eye.build_why(self.op, "MSFT"))
        self.assertTrue(any(f"Stocks spare #{hand.pk} — stopped · " in ln
                            for ln in lines), lines)
        self.assertFalse([ln for ln in lines if "still managing" in ln])


# ── Morgul G10 ───────────────────────────────────────────────────────────

class TheHeartbeatTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.op = _op()
        _component("platform_master")
        _component("pipeline_asset_bots", last_run=WED - timedelta(minutes=2))

    def _check(self):
        from bot_program import morgul
        ctx = morgul.Context(WED)
        guard = morgul.GUARD["heartbeat"]
        return ctx, guard.check(ctx, guard)

    def _stamp(self, cfg, minutes):
        from bot_program.asset_models import AssetBotConfig
        cfg.refresh_from_db()
        extras = dict(cfg.extras or {},
                      last_tick_at=(WED - timedelta(minutes=minutes))
                      .isoformat())
        AssetBotConfig.objects.filter(pk=cfg.pk).update(
            extras=extras, updated_at=WED - timedelta(hours=2))

    def test_a_braked_live_config_with_an_open_row_joins_the_tick_check(self):
        cfg = _bot(self.op, "Forex live", "forex", mode="live",
                   symbols=["EURUSD"])
        _row(cfg, "EURUSD", paper=False, metadata={"protected": True})
        _morgul_brake(self.op, cfg)
        self._stamp(cfg, 40)
        _ctx, found = self._check()
        by = {f.subject: f for f in found}
        self.assertEqual(sorted(by), ["tick"])
        f = by["tick"]
        self.assertIn(f"Forex live #{cfg.pk} (stopped by the brake, still "
                      f"managing): last tick 40 min ago", f.facts)
        self.assertEqual(f.label, "Live bots running: 0 · stopped, still "
                                  "managing: 1")

    def test_a_braked_config_without_open_rows_does_not_and_feeds_stay_enabled_only(self):
        quiet = _bot(self.op, "Forex quiet", "forex", mode="live",
                     symbols=["GBPUSD"])
        _row(quiet, "GBPUSD", paper=False, status="CLOSED")
        _morgul_brake(self.op, quiet)
        self._stamp(quiet, 40)
        self.assertEqual(self._check()[1], [])
        # an enabled stock bot, ticking, fresh; a braked forex bot with an
        # open row, ticking, whose symbol's mark is stale in an open market
        stocks = _bot(self.op, "Stocks live", mode="live", symbols=["AAPL"])
        self._stamp(stocks, 2)
        braked = _bot(self.op, "Forex braked", "forex", mode="live",
                      symbols=["EURUSD"])
        _row(braked, "EURUSD", paper=False, metadata={"protected": True})
        _morgul_brake(self.op, braked)
        self._stamp(braked, 2)
        _mark("AAPL", "stock", WED - timedelta(minutes=1), source="yfinance",
              last="336")
        _mark("EURUSD", "forex", WED - timedelta(hours=3))
        ctx, found = self._check()
        self.assertEqual(found, [])
        self.assertNotIn("feeds:forex", ctx.unjudged.get("heartbeat", ()))
        self.assertFalse([n for n in ctx.notes if "Forex" in n], ctx.notes)


# ── `bot brake` ──────────────────────────────────────────────────────────

class TheBotBrakeTests(TestCase):
    def setUp(self):
        self.op = _op()

    def test_bot_brake_records_an_enabled_config_and_adopts_only_an_unrecorded_stop(self):
        running = _bot(self.op, "Running")
        out = _run("bot", "brake", str(running.pk), why="the operator's brake")
        self.assertIn(f"[{running.pk}] Running: STOPPED by `bot brake` on the "
                      f"server — its open positions stay managed; it opens "
                      f"nothing", out)
        rec = _record(running)
        self.assertEqual((rec["by"], rec["why"], rec["who"]),
                         (disarm.BY_BOT_BRAKE, "the operator's brake",
                          "shell"))
        self.assertTrue(disarm.keeps_managing(running))
        # off before the record existed (config 26): adopted as a brake
        old = _bot(self.op, "Old stop", enabled=False)
        _row(old)
        out = _run("bot", "brake", str(old.pk))
        self.assertIn(f"[{old.pk}] Old stop: already OFF with no record — "
                      f"now recorded as a brake: its open positions are "
                      f"managed from the next tick", out)
        rec = _record(old)
        self.assertEqual((rec["by"], rec["why"]),
                         (disarm.BY_BOT_BRAKE, "bot brake"))
        self.assertTrue(disarm.keeps_managing(old))
        # stopped by hand: a brake never relabels it
        hand = _bot(self.op, "Handoff")
        _row(hand)
        _run("bot", "off", str(hand.pk))
        before = _record(hand)
        out = _run("bot", "brake", str(hand.pk))
        self.assertIn(f"[{hand.pk}] Handoff: stopped by `bot off` on the "
                      f"server (shell) on ", out)
        self.assertIn("; unchanged", out)
        self.assertEqual(_record(hand), before)
        self.assertFalse(disarm.keeps_managing(hand))
        self.assertIn("not found", _run("bot", "brake", "999999"))
