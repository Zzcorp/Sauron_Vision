"""THE FAITHFULNESS AUDIT (spec §6.1): on rows no Orc acts on (every row in
O1), the care ghost, stepped on its own state, reproduces the REAL care
tick by tick and exits with it, on every path the care has: break-even and
trail, the mirror, the weekend and the event windows, the posture floors,
the thesis check's structure stop, the crowd, the no-progress clock, the
manual lane, the engine's knobs and the config's time stop. A refused
mirror is counted, never hidden. Each test drives the real care().

Run with:  python manage.py test tests.orcs.test_orc_faithfulness
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from tests.orcs.helpers import (_config, _manual_config, _manual_row, _on,
                                _row, _switch, _user, born, care_tick, drive,
                                headlines, tracks_of)

WED = datetime(2026, 10, 14, 10, 0, tzinfo=dt_tz.utc)
FRI = datetime(2026, 10, 16, 19, 30, tzinfo=dt_tz.utc)    # 15:30 New York


def _open_at(row, at):
    from bot_program.models import AssetBotTrade
    AssetBotTrade.objects.filter(pk=row.pk).update(opened_at=at)
    row.refresh_from_db()


def _fake_close(trade, price, client, *, reason, paper_exit=None):
    """The close the care asks for, booked as the engine books it: the row
    CLOSED at the price, the reason tagged (no broker in a test)."""
    trade.status = "CLOSED"
    trade.exit_price = Decimal(str(price))
    trade.closed_at = timezone.now()
    trade.outcome = "time_stop" if reason == "TIME" else "stopped_out"
    trade.reason = ((trade.reason or "") + f" | closed:{reason}").strip()
    trade.save()
    return True


class _Faith(TestCase):

    def setUp(self):
        _on()
        _switch("aragorn")
        self.user = _user("orc_faith")

    def assertFaithful(self, orc, row, *, arm="care"):
        """The ghost's care equals the row's, and its venue stop the row's
        stop (the mirror accepted, or the engine's own)."""
        row.refresh_from_db()
        g = tracks_of(orc)[arm].state
        care = row.metadata.get("care") or {}
        for key in ("peak", "worst", "soft_stop", "soft_why"):
            self.assertEqual(g.get(key), care.get(key), key)
        self.assertEqual(g.get("venue_stop"), float(row.stop_loss),
                         "the venue's stop")

    def assertExitedTogether(self, orc, row, now):
        from bot_program.orcs import ghost
        ghost.step_bars(orc, now=now)
        t = tracks_of(orc)
        self.assertFalse(t["care"].open)
        self.assertFalse(t["orc_shadow"].open)
        self.assertEqual(t["care"].exit_price, t["orc_shadow"].exit_price)
        self.assertEqual(t["orc_shadow"].exit_r - t["care"].exit_r, 0.0,
                         "the same exit, the same price: zero exactly")
        f = ghost.faithfulness(orc)
        self.assertEqual(f["differed"], 0, f)
        self.assertTrue(f["matched"], f)

    def _live(self, *, cls="crypto", symbol="BTCUSD", protected=True,
              refuse=False, meta=None, cfg=None, **row_kw):
        cfg = cfg or _config(self.user, cls, mode="live",
                             name=f"live {symbol}")
        extra = {"broker": "etoro", "broker_env": "live"}
        if protected:
            extra.update(protected=True, protective_trade_id="P1")
        row = _row(cfg, paper=False, symbol=symbol, cls=cls,
                   meta={**extra, **(meta or {})}, **row_kw)
        from bot_program.asset_engine.base import make_bot
        bot = make_bot(cfg)
        client = MagicMock()
        client.close_needs_position_id.return_value = True
        client.get_positions.return_value = []
        client.modify_protective.return_value = (
            {"ok": False, "reason": "refused by the venue"} if refuse
            else {"ok": True, "price": None})
        return cfg, row, bot, client


class ThePaperTests(_Faith):

    def test_paper_bot_breakeven_trail_close(self):
        cfg = _config(self.user)
        row = _row(cfg)
        _open_at(row, WED)
        orc = born(self, row)
        marks = ["101.0", "102.2", "103.0", "104.2", "103.6"]
        for i, p in enumerate(marks, start=1):
            drive(self, cfg, row, [(WED + timedelta(minutes=30 * i), p)])
            self.assertFaithful(orc, row)
        drive(self, cfg, row, [(WED + timedelta(hours=3), "102.1")])
        self.assertEqual(row.status, "CLOSED")
        self.assertEqual(tracks_of(orc)["care"].state["exit"]["kind"], "care")
        self.assertExitedTogether(orc, row, WED + timedelta(hours=4))
        self.assertIn("The care ghost exited: the care's trail at",
                      "\n".join(headlines(orc)))

    def test_no_progress(self):
        cfg = _config(self.user)
        row = _row(cfg, meta={"care": {"since": WED.isoformat()}})
        _open_at(row, WED)
        orc = born(self, row)
        drive(self, cfg, row, [(WED + timedelta(hours=1), "100.3")])
        self.assertFaithful(orc, row)
        drive(self, cfg, row, [(WED + timedelta(hours=73), "100.4")])
        self.assertEqual(row.status, "CLOSED")
        self.assertEqual(row.metadata.get("care_exit"), "no progress")
        g = tracks_of(orc)["care"]
        self.assertEqual(g.exit_why, "the care's no progress")
        self.assertExitedTogether(orc, row, WED + timedelta(hours=74))

    def test_engine_knobs(self):
        cfg = _config(self.user, extras={"breakeven_at_r": 0.5,
                                         "breakeven_buffer_r": 0.1})
        row = _row(cfg)
        _open_at(row, WED)
        orc = born(self, row)
        drive(self, cfg, row, [(WED + timedelta(minutes=30), "101.2")])
        row.refresh_from_db()
        self.assertEqual(float(row.stop_loss), 100.2, "the engine's BE")
        self.assertFaithful(orc, row)
        self.assertTrue(tracks_of(orc)["care"].state["breakeven_armed"])
        drive(self, cfg, row, [(WED + timedelta(minutes=60), "101.6")])
        self.assertFaithful(orc, row)
        drive(self, cfg, row, [(WED + timedelta(minutes=90), "100.1")])
        self.assertEqual(row.status, "CLOSED", "the engine's stop")
        self.assertEqual(tracks_of(orc)["care"].state["exit"]["kind"], "stop")
        self.assertExitedTogether(orc, row, WED + timedelta(hours=3))

    def test_config_time_stop_shared_event(self):
        cfg = _config(self.user, extras={"max_hold_hours": 2})
        row = _row(cfg)
        _open_at(row, WED)
        orc = born(self, row)
        drive(self, cfg, row, [(WED + timedelta(minutes=30), "100.6")])
        self.assertFaithful(orc, row)
        drive(self, cfg, row, [(WED + timedelta(hours=2, minutes=5),
                                "100.7")])
        self.assertEqual(row.status, "CLOSED")
        self.assertEqual(row.outcome, "time_stop")
        self.assertTrue(tracks_of(orc)["care"].open,
                        "the hook never ran: the time stop fires first")
        self.assertExitedTogether(orc, row, WED + timedelta(hours=3))
        self.assertEqual(tracks_of(orc)["care"].state["exit"]["kind"],
                         "time")
        # the paper time stop's booked fill is taken back off once, then
        # charged once: the absolute price, not only the zero difference
        from bot_program.orcs import pricing
        o = tracks_of(orc)["orc_shadow"]
        cf = o.state["cf"]
        self.assertGreater(cf, 0)
        row.refresh_from_db()
        self.assertAlmostEqual(float(o.exit_price), pricing.market_exit_px(
            pricing.Tick(at=None, p=float(row.exit_price) / (1 - cf / 2)),
            "BUY", cf), places=6)

    def test_thesis_structure_stop(self):
        cfg = _config(self.user)
        thesis = {"verdict": "adjust", "stop": 99.5,
                  "at": (WED + timedelta(minutes=20)).isoformat()}
        row = _row(cfg, meta={"thesis": thesis})
        _open_at(row, WED)
        orc = born(self, row)
        drive(self, cfg, row, [(WED + timedelta(minutes=30), "100.4")])
        row.refresh_from_db()
        self.assertEqual(row.metadata["care"]["soft_why"], "structure")
        self.assertFaithful(orc, row)

    def test_crowd_moved_locks(self):
        _switch("smart_money")
        cfg = _config(self.user)
        row = _row(cfg)
        _open_at(row, WED)
        orc = born(self, row)
        # the trail at 102.2 sits in the zone of a swing low at 102.5: the
        # care moves it to 102.0, beyond the crowd (smart_money, HUNT 0.5)
        crowd = {"atr": 1.0, "levels": [(102.5, "swing low")]}
        with patch("bot_program.smart_money.care_levels",
                   return_value=crowd):
            drive(self, cfg, row, [(WED + timedelta(minutes=30), "104.2")])
        row.refresh_from_db()
        self.assertEqual(row.metadata["care"]["soft_why"],
                         "trail (beyond the crowd)")
        self.assertEqual(row.metadata["care"]["soft_stop"], 102.0)
        self.assertFaithful(orc, row)

    def test_manual_row_locks_only(self):
        lane = _manual_config(self.user)
        row = _manual_row(lane)
        _open_at(row, WED)
        orc = born(self, row)
        # a manual lane: the lock is kept, nothing cuts it on a rule
        for i, p in enumerate(["102.2", "100.6"], start=1):
            drive(self, lane, row, [(WED + timedelta(minutes=30 * i), p)])
            self.assertFaithful(orc, row)
        self.assertEqual(row.status, "OPEN", "above the lock, held")
        self.assertEqual(row.metadata["care"]["soft_why"], "breakeven")
        drive(self, lane, row, [(WED + timedelta(minutes=90), "100.1")])
        self.assertEqual(row.status, "CLOSED", "the lock crossed")
        self.assertExitedTogether(orc, row, WED + timedelta(hours=3))


class TheLiveTests(_Faith):

    def test_live_protected_with_accepted_mirror(self):
        cfg, row, bot, client = self._live()
        _open_at(row, WED)
        orc = born(self, row)
        for i, p in enumerate(["101.0", "102.5", "104.2", "103.5"], start=1):
            care_tick(self, bot, row, p, client,
                      WED + timedelta(minutes=30 * i))
            self.assertFaithful(orc, row)
        self.assertEqual(float(row.stop_loss), 102.2, "the trail, mirrored")
        care_tick(self, bot, row, "102.0", client, WED + timedelta(hours=3))
        self.assertTrue(tracks_of(orc)["care"].state["waits_for_venue"])
        row.status, row.outcome = "CLOSED", "stopped_out"
        row.exit_price, row.closed_at = Decimal("102.2"), WED + timedelta(
            hours=3, minutes=5)
        row.metadata = {**row.metadata, "exit_fill_source": "venue_stop"}
        with self.captureOnCommitCallbacks(execute=True):
            row.save()
        self.assertExitedTogether(orc, row, WED + timedelta(hours=4))

    def test_refused_mirror_is_counted(self):
        from bot_program.orcs import ghost
        cfg, row, bot, client = self._live(refuse=True)
        _open_at(row, WED)
        orc = born(self, row)
        care_tick(self, bot, row, "102.5", client, WED + timedelta(minutes=30))
        care_tick(self, bot, row, "102.6", client, WED + timedelta(minutes=60))
        row.refresh_from_db()
        self.assertEqual(float(row.stop_loss), 98.0, "the venue refused")
        self.assertIn("venue_stop_refusal", row.metadata["care"])
        g = tracks_of(orc)["care"].state
        self.assertEqual(g["venue_stop"], 100.2, "assumed accepted")
        f = ghost.faithfulness(orc)
        self.assertGreaterEqual(f["differed"], 1)
        self.assertEqual(f["first"]["what"], "venue")
        self.assertIn("Faithfulness: the care ghost differed on",
                      ghost.faith_line(f))

    def test_weekend_lock_and_cut(self):
        # the lock: a paper forex winner in Friday's last hour
        cfg = _config(self.user, "forex", name="fx")
        row = _row(cfg, symbol="EURUSD", cls="forex", entry="1.1000",
                   stop="1.0980", target="1.1100")
        _open_at(row, FRI - timedelta(hours=2))
        orc = born(self, row)
        drive(self, cfg, row, [(FRI, "1.1012")])
        row.refresh_from_db()
        self.assertEqual(row.metadata["care"]["soft_why"], "weekend lock")
        self.assertFaithful(orc, row)
        # the cut: a real 5x loser, unprotected
        cfg2, live, bot, client = self._live(
            cls="forex", symbol="GBPUSD", protected=False,
            meta={"leverage": 5}, entry="1.3000", stop="1.2980",
            target="1.3100")
        _open_at(live, FRI - timedelta(hours=2))
        lorc = born(self, live)
        with patch.object(bot, "_close_trade", side_effect=_fake_close):
            care_tick(self, bot, live, "1.2995", client, FRI)
        live.refresh_from_db()
        self.assertEqual(live.metadata.get("care_exit"), "weekend cut")
        self.assertEqual(tracks_of(lorc)["care"].state["exit"]["why"],
                         "the care's weekend cut")
        self.assertExitedTogether(lorc, live, FRI + timedelta(minutes=30))

    def test_holiday_eve_lock_and_cut(self):
        """R29: the long shut (position_care.long_shut_ahead) reads the
        row's symbol; the ghost's shadow row carries it, so the shadow
        care locks and cuts on a US holiday's eve with the real one."""
        eve = datetime(2026, 12, 24, 17, 30, tzinfo=dt_tz.utc)  # 12:30 NY
        cfg = _config(self.user, "stock", name="st")
        row = _row(cfg, symbol="AAPL", cls="stock")
        _open_at(row, eve - timedelta(hours=2))
        orc = born(self, row)
        drive(self, cfg, row, [(eve, "101.2")])
        row.refresh_from_db()
        self.assertEqual(row.metadata["care"]["soft_why"], "weekend lock")
        self.assertFaithful(orc, row)
        cfg2, live, bot, client = self._live(
            cls="stock", symbol="MSFT", protected=False,
            meta={"leverage": 5})
        _open_at(live, eve - timedelta(hours=2))
        lorc = born(self, live)
        with patch.object(bot, "_close_trade", side_effect=_fake_close):
            care_tick(self, bot, live, "99.5", client, eve)
        live.refresh_from_db()
        self.assertEqual(live.metadata.get("care_exit"), "weekend cut")
        self.assertEqual(tracks_of(lorc)["care"].state["exit"]["why"],
                         "the care's weekend cut")
        self.assertExitedTogether(lorc, live, eve + timedelta(minutes=30))

    def test_holiday_eve_reads_the_rows_own_symbol(self):
        """The twin of the eve above on a London index row: the real care
        keeps the London clock (no lock), and the shadow row, which
        carries the symbol, agrees. A shadow or a care that dropped the
        symbol would fall back to the class's New York session and lock."""
        eve = datetime(2026, 12, 24, 17, 30, tzinfo=dt_tz.utc)  # 12:30 NY
        cfg = _config(self.user, "stock", name="ix")
        row = _row(cfg, symbol="FTSE100", cls="index")
        _open_at(row, eve - timedelta(hours=2))
        orc = born(self, row)
        drive(self, cfg, row, [(eve, "101.2")])
        row.refresh_from_db()
        care = row.metadata.get("care") or {}
        self.assertNotEqual(care.get("soft_why"), "weekend lock")
        self.assertEqual(tracks_of(orc)["care"].state.get("soft_why"),
                         care.get("soft_why"))
        self.assertFaithful(orc, row)

    def test_event_lock_and_cut(self):
        from market_data.models import EconomicEvent
        at = WED + timedelta(minutes=30)
        EconomicEvent.objects.create(
            title="US CPI m/m", country="US", datetime=at + timedelta(
                minutes=30), impact="High", currency_affected="USD",
            source="forexfactory")
        cfg = _config(self.user)
        row = _row(cfg)
        _open_at(row, WED)
        orc = born(self, row)
        drive(self, cfg, row, [(at, "101.2")])
        row.refresh_from_db()
        self.assertEqual(row.metadata["care"]["soft_why"], "event lock")
        self.assertFaithful(orc, row)
        cfg2, live, bot, client = self._live(
            symbol="ETHUSD", protected=False, meta={"leverage": 5})
        _open_at(live, WED)
        lorc = born(self, live)
        with patch.object(bot, "_close_trade", side_effect=_fake_close):
            care_tick(self, bot, live, "99.5", client, at)
        live.refresh_from_db()
        self.assertEqual(live.metadata.get("care_exit"), "event cut")
        self.assertExitedTogether(lorc, live, at + timedelta(minutes=30))

    def test_crisis_and_stressed_floors(self):
        cfg, row, bot, client = self._live(protected=False)
        _open_at(row, WED)
        orc = born(self, row)
        with patch("bot_program.posture.crisis_mode_on", return_value=True), \
                patch("bot_program.market_stress.current",
                      return_value={"level": "crisis"}), \
                patch("bot_program.posture.classify",
                      return_value="risk_on_long"):
            care_tick(self, bot, row, "99.4", client,
                      WED + timedelta(minutes=30))
        row.refresh_from_db()
        self.assertEqual(row.metadata["care"]["soft_why"], "crisis")
        self.assertEqual(row.metadata["care"]["soft_stop"], 99.0)
        self.assertEqual(tracks_of(orc)["care"].state["soft_stop"], 99.0)
        self.assertEqual(tracks_of(orc)["care"].state["soft_why"], "crisis")
        with patch("bot_program.posture.crisis_mode_on", return_value=True), \
                patch("bot_program.market_stress.current",
                      return_value={"level": "stressed"}), \
                patch("bot_program.posture.classify",
                      return_value="risk_on_long"):
            care_tick(self, bot, row, "99.6", client,
                      WED + timedelta(minutes=60))
        self.assertEqual(tracks_of(orc)["care"].state["soft_stop"], 99.0,
                         "tighten-only, as the care")


class TheAuditCommandTests(_Faith):

    def test_shadow_audit_command_prints_and_journals(self):
        from bot_program.orcs.models import Orc
        cfg = _config(self.user)
        row = _row(cfg)
        _open_at(row, WED)
        orc = born(self, row)
        drive(self, cfg, row, [(WED + timedelta(minutes=30), "102.2"),
                               (WED + timedelta(minutes=60), "100.1")])
        self.assertEqual(row.status, "CLOSED")
        from bot_program.orcs import ghost
        ghost.step_bars(orc, now=WED + timedelta(hours=2))
        Orc.objects.filter(pk=orc.pk).update(died_at=timezone.now())
        n = len(headlines(orc))
        out = StringIO()
        call_command("orcs", "shadow-audit", "--days", "7", stdout=out)
        text = out.getvalue()
        self.assertIn("Shadow audit · last 7 days · 1 idea(s) checked", text)
        self.assertIn(f"Orc #{row.pk} BTCUSD: Faithfulness: the care ghost "
                      f"matched the care on", text)
        self.assertEqual(len(headlines(orc)), n, "prints only by default")
        call_command("orcs", "shadow-audit", "--journal", stdout=StringIO())
        call_command("orcs", "shadow-audit", "--journal", stdout=StringIO())
        lines = [h for h in headlines(orc, kind="fact")
                 if h.startswith("Faithfulness")]
        self.assertEqual(len(lines), 1, "journaled once")
