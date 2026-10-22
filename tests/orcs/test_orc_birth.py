"""BORN (spec §1.2, O1a): one Orc per open position, from the entry, the
working fill, TAKE TRADE and the census, idempotent; its stamp merged on
the row under the lock; r_money frozen from the initial stop; the manual
flag failing toward manual; its seat, thesis, army type and care ghost.

Run with:  python manage.py test tests.orcs.test_orc_birth
"""
import json
from datetime import datetime
from datetime import timezone as dt_tz
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import TestCase

from tests.orcs.helpers import (_config, _manual_config, _manual_row, _on,
                                _row, _user, born, headlines, journal)

UTC = dt_tz.utc
WED = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
NOTIFY = "bot_program.notifications.dispatch_notification"


def _fmt(value, cls="crypto", symbol="BTCUSD"):
    from core.price_format import format_price
    return format_price(value, cls, symbol)


class TheHooksTests(TestCase):
    """The three entry paths register the birth on commit."""

    def setUp(self):
        _on()
        self.user = _user("orc_hooks")

    def test_birth_from_execute_entry_is_idempotent(self):
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.birth import ensure
        from bot_program.orcs.models import Orc, OrcLeg
        from tests.test_desk_seam import ROUTER, _client
        from tests.test_desk_seam import _config as _desk_config
        from tests.test_desk_seam import _signal
        cfg = _desk_config(self.user, symbols=["ORCA1"])
        _signal("ORCA1", "bullish", 0.85, rule="orc_rule")
        bot = StockBot(cfg)
        with patch(ROUTER, return_value=_client()), \
                self.captureOnCommitCallbacks(execute=True):
            res = bot.scan_symbol("ORCA1")
        self.assertIsNotNone(res)
        row = AssetBotTrade.objects.get(pk=res["trade_id"])
        orc = Orc.objects.get(root_trade=row)
        self.assertEqual(row.metadata["orc"],
                         {"idea": orc.pk, "leg": 1, "kind": "root",
                          "parent_rule": "orc_rule"})
        self.assertFalse(orc.adopted)
        self.assertEqual(orc.thesis["source"], "entry")
        self.assertEqual(headlines(orc, kind="birth")[0][:9], "Born at 1")
        self.assertEqual(ensure(row), orc)
        self.assertEqual(ensure(AssetBotTrade.objects.get(pk=row.pk)), orc)
        self.assertEqual(Orc.objects.count(), 1)
        self.assertEqual(OrcLeg.objects.count(), 1)

    def test_a_working_entry_is_born_at_its_fill(self):
        from bot_program.asset_engine.base import make_bot
        from bot_program.orcs.birth import ensure, ensure_on_commit
        from bot_program.orcs.models import Orc
        cfg = _config(self.user)
        row = _row(cfg, meta={"entry_working": True, "qty_requested": 1.0,
                              "protective_order_ids": [],
                              "protected": False})
        with self.captureOnCommitCallbacks(execute=True) as cbs:
            ensure_on_commit(row)
        self.assertEqual(cbs, [], "a working entry registers nothing")
        self.assertIsNone(ensure(row), "an order, not a position")
        with patch("bot_program.notifications.notify_bot_fill_open"), \
                self.captureOnCommitCallbacks(execute=True):
            make_bot(cfg)._finish_working_entry(row, MagicMock(), qty=1.0,
                                                price=100.5, source="broker")
        orc = Orc.objects.get(root_trade=row)
        self.assertEqual(row.metadata["orc"]["idea"], orc.pk,
                         "the tick's copy carries the stamp")
        row.refresh_from_db()
        self.assertEqual(row.metadata["orc"]["idea"], orc.pk)
        self.assertNotIn("entry_working", row.metadata)

    def test_a_manual_ticket_is_born_after_its_commit_and_never_on_a_rollback(self):
        import inspect

        from bot_program import manual_trade
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.birth import ensure_on_commit
        from bot_program.orcs.models import Orc
        from tests.test_take_trade import _quote, _signal
        inst = _quote("BTCUSD", 60000)
        with self.captureOnCommitCallbacks(execute=True):
            out = execute_take_trade(self.user, _signal(inst))
        self.assertTrue(out.get("ok"), out)
        orc = Orc.objects.get(root_trade_id=out["trade_id"])
        self.assertTrue(orc.manual)
        self.assertEqual(orc.commission, "advise")
        self.assertEqual(orc.seat.rule_key, "manual_take")
        # a rolled-back booking leaves nothing to run
        cfg = AssetBotTrade.objects.get(pk=out["trade_id"]).config
        with self.captureOnCommitCallbacks(execute=True) as cbs:
            try:
                with transaction.atomic():
                    ghost = _manual_row(cfg, symbol="ETHUSD")
                    ensure_on_commit(ghost)
                    raise RuntimeError("the booking failed")
            except RuntimeError:
                pass
        self.assertEqual(cbs, [])
        self.assertEqual(Orc.objects.count(), 1)
        # the hook sits inside _book_row, before its return
        src = inspect.getsource(manual_trade)
        book = src[src.index("def _book_row"):]
        self.assertLess(book.index("ensure_on_commit(row)"),
                        book.index("return row"))


def _now_on_commit(trade, cache=None):
    """The hook as production runs it: the runner holds no atomic block, so
    the birth's on_commit runs at once, inside execute_entry (a TestCase
    would otherwise defer it past the desk's stamp)."""
    from bot_program.orcs.birth import _ensure_quietly
    if not (trade.metadata or {}).get("entry_working"):
        _ensure_quietly(trade.pk, trade, cache)


class TheDeskKeysTests(TestCase):
    """The desk stamps its multiplier and lane after execute_entry returns
    (runner._stamp_desk_keys), and the idea is born inside execute_entry:
    the thesis gains those keys once, right after the stamp."""

    def setUp(self):
        from tests.test_capital_desk import _component, _signal
        from tests.test_capital_desk import _config as _desk_config
        _on()
        _component("pipeline_capital_desk")
        self.user = _user("orc_desk")
        self.cfg = _desk_config(self.user, name="Orc Desk", symbols=["ORCD1"])
        _signal("ORCD1", rule="orc_desk_rule")

    def _run(self):
        from bot_program.asset_engine.runner import run_all_asset_bots
        from bot_program.models import AssetBotTrade
        from tests.test_capital_desk import ROUTER as DESK_ROUTER
        from tests.test_capital_desk import _client as _desk_client
        with patch(DESK_ROUTER, return_value=_desk_client()), \
                patch("bot_program.orcs.birth.ensure_on_commit",
                      side_effect=_now_on_commit):
            run_all_asset_bots()
        return AssetBotTrade.objects.get(symbol="ORCD1")

    def test_the_runner_writes_the_desk_keys_into_the_thesis(self):
        from bot_program.orcs.models import Orc
        row = self._run()
        self.assertEqual(row.metadata["desk_size_mult"], 1.0)
        orc = Orc.objects.get(root_trade=row)
        self.assertEqual(orc.thesis["source"], "entry")
        prov = orc.thesis["provenance"]
        self.assertEqual(prov.get("desk_size_mult"), 1.0)
        self.assertEqual(prov.get("desk_lane"), row.metadata["desk_lane"])
        self.assertTrue(orc.seen.get("provenance_completed"))

    def test_the_birth_precedes_the_stamp_and_the_completion_runs_once(self):
        from bot_program.orcs import journal
        from bot_program.orcs.models import Orc
        from bot_program.orcs.thesis import complete_provenance
        with patch("bot_program.orcs.thesis.complete_provenance"):
            row = self._run()
        orc = Orc.objects.get(root_trade=row)
        self.assertNotIn("desk_size_mult", orc.thesis["provenance"],
                         "born inside execute_entry, before the desk wrote")
        before = dict(orc.thesis)
        # a fact after the birth: the thesis is closed to the completion
        journal.append(orc, "fact", "A later fact.", fact=True)
        self.assertFalse(complete_provenance(row))
        orc.refresh_from_db()
        self.assertEqual(orc.thesis, before)
        # with nothing past its birth lines it takes the keys, once
        seen = dict(orc.seen)
        seen["fact_seq"] = seen["birth_seq"]
        Orc.objects.filter(pk=orc.pk).update(seen=seen)
        self.assertTrue(complete_provenance(row))
        self.assertFalse(complete_provenance(row))
        orc.refresh_from_db()
        self.assertEqual(orc.thesis["provenance"]["desk_size_mult"], 1.0)
        self.assertEqual({k: v for k, v in orc.thesis.items()
                          if k != "provenance"},
                         {k: v for k, v in before.items()
                          if k != "provenance"})

    def test_a_row_with_no_orc_costs_no_query(self):
        from bot_program.orcs.thesis import complete_provenance
        row = _row(_config(self.user, name="plain"),
                   meta={"desk_size_mult": 0.5})
        with self.assertNumQueries(0):
            self.assertFalse(complete_provenance(row))


class TheBirthTests(TestCase):

    def setUp(self):
        _on()
        self.user = _user("orc_birth")
        self.cfg = _config(self.user)

    def test_two_births_race_to_one_orc(self):
        from bot_program.orcs.models import Orc, OrcLeg
        row = _row(self.cfg)
        first = born(self, row)
        self.assertIsNotNone(first)
        # the other process committed between our check and our create
        with patch("bot_program.orcs.birth._existing", return_value=None):
            again = born(self, row)
        self.assertEqual(again, first)
        self.assertEqual(Orc.objects.count(), 1)
        self.assertEqual(OrcLeg.objects.count(), 1)

    def test_r_money_is_frozen_from_the_initial_stop(self):
        from bot_program.manual_close import _risk_dollars
        row = _row(self.cfg, qty="2")
        orc = born(self, row)
        self.assertEqual(orc.r_money, Decimal("4.0000"))
        row.stop_loss = Decimal("99.5")
        row.save(update_fields=["stop_loss"])
        orc.refresh_from_db()
        self.assertEqual(orc.r_money, Decimal("4.0000"), "frozen at birth")
        fx_cfg = _config(self.user, "forex")
        fx = _row(fx_cfg, qty="1000", entry="1.1000", stop="1.0950",
                  symbol="EURUSD")
        fx_orc = born(self, fx)
        self.assertAlmostEqual(float(fx_orc.r_money), _risk_dollars(fx),
                               places=4)
        self.assertEqual(fx_orc.ccy, "USD")

    def test_no_stop_means_no_r_and_shadow_for_life(self):
        row = _row(self.cfg, stop=None)
        orc = born(self, row)
        self.assertIsNone(orc.r_money)
        self.assertEqual(orc.seat.level, 0)
        self.assertEqual(headlines(orc, kind="birth"), [
            f"Born at {_fmt(row.entry_price)} with no stop: no R, so this "
            f"Orc stays in shadow for life."])

    def test_the_birth_line_names_the_entry_and_the_stop(self):
        row = _row(self.cfg)
        orc = born(self, row)
        self.assertEqual(headlines(orc, kind="birth"), [
            f"Born at {_fmt(Decimal('100'))}, stop {_fmt(98.0)}: 1R is the "
            f"distance to that stop."])

    def test_manual_fails_toward_manual(self):
        from bot_program.orcs.birth import fail_toward_manual
        bot_row = _row(self.cfg)
        self.assertFalse(fail_toward_manual(bot_row, self.cfg))
        ticket = _manual_row(self.cfg)
        self.assertTrue(fail_toward_manual(ticket, self.cfg),
                        "the manual rule, whatever the config")
        lane = _manual_config(self.user)
        lane_row = _row(lane, rule="golden_cross")
        self.assertTrue(fail_toward_manual(lane_row, lane),
                        "the manual lane, whatever the rule")
        with patch("bot_program.share_allocator._is_manual_lane",
                   side_effect=RuntimeError("unreadable")):
            self.assertTrue(fail_toward_manual(bot_row, self.cfg),
                            "an unreadable lane fails toward manual")
        with patch("bot_program.share_allocator._is_manual_lane",
                   side_effect=RuntimeError("unreadable")):
            orc = born(self, bot_row)
        self.assertTrue(orc.manual)
        self.assertEqual(orc.commission, "advise",
                         "never a bot idea with commission class")

    def test_skips_working_options_and_unticked_configs(self):
        from bot_program.asset_engine import disarm
        from bot_program.orcs.birth import ensure, skip_reason
        from bot_program.orcs.models import Orc
        working = _row(self.cfg, meta={"entry_working": True})
        self.assertIsNone(ensure(working))
        self.assertEqual(skip_reason(working, self.cfg), "an entry still working at the venue")
        opt_cfg = _config(self.user, "options")
        self.assertIsNone(ensure(_row(opt_cfg, symbol="AAPL240119C00190000")))
        opt_row = _row(self.cfg, cls="options", symbol="AAPL240119C00190000")
        self.assertIsNone(ensure(opt_row))
        closed = _row(self.cfg, status="CLOSED", symbol="ETHUSD")
        self.assertIsNone(ensure(closed))
        # a hand-disabled config: its real row is never managed
        off = _config(self.user, mode="live", name="off")
        disarm.disable_config(off, by=disarm.BY_BOT_OFF, why="t", who="t")
        off.refresh_from_db()
        self.assertIsNone(ensure(_row(off, paper=False, symbol="SOLUSD")))
        # ...its paper row still is (manage_paper_only)
        self.assertIsNotNone(born(self, _row(off, paper=True,
                                             symbol="ADAUSD")))
        # a braked config's real row is managed (manage_braked)
        braked = _config(self.user, mode="live", name="braked")
        disarm.disable_config(braked, by=disarm.BY_EYE, why="t", who="t")
        braked.refresh_from_db()
        self.assertIsNotNone(born(self, _row(braked, paper=False,
                                             symbol="XRPUSD")))
        self.assertEqual(Orc.objects.count(), 2)

    def test_paper_births_stop_at_the_cap_and_the_setting_overrides_it(self):
        from bot_program.orcs.models import Orc, OrcSetting
        OrcSetting.objects.create(key="max_paper_orcs", value=2)
        rows = [_row(self.cfg, symbol=s) for s in ("A1USD", "A2USD", "A3USD")]
        self.assertIsNotNone(born(self, rows[0]))
        self.assertIsNotNone(born(self, rows[1]))
        self.assertIsNone(born(self, rows[2]), "the cap holds")
        real_cfg = _config(self.user, mode="live", name="real")
        self.assertIsNotNone(born(self, _row(real_cfg, paper=False,
                                             symbol="A4USD")),
                             "real rows are never capped")
        OrcSetting.objects.filter(key="max_paper_orcs").update(value=3)
        self.assertIsNotNone(born(self, rows[2]))
        self.assertEqual(Orc.objects.filter(paper=True).count(), 3)

    def test_the_stamp_is_merged_under_the_lock_and_kept_in_memory(self):
        from bot_program.models import AssetBotTrade
        row = _row(self.cfg, meta={"care": {"peak": 101.0}})
        # another writer lands after the tick read its copy
        AssetBotTrade.objects.filter(pk=row.pk).update(metadata={
            **row.metadata, "adjusted_by": "operator"})
        row.metadata = {**row.metadata, "tick_only": 1}
        orc = born(self, row)
        stamp = {"idea": orc.pk, "leg": 1, "kind": "root",
                 "parent_rule": "golden_cross"}
        self.assertEqual(row.metadata["orc"], stamp)
        self.assertEqual(row.metadata["tick_only"], 1,
                         "the tick's copy keeps its own keys")
        fresh = AssetBotTrade.objects.get(pk=row.pk)
        self.assertEqual(fresh.metadata["orc"], stamp)
        self.assertEqual(fresh.metadata["adjusted_by"], "operator",
                         "never clobbered by a stale copy")
        self.assertNotIn("tick_only", fresh.metadata)

    def test_the_care_track_is_seeded_once(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import OrcTrack
        care = {"peak": 104.0, "worst": 99.0, "since": "2026-10-14T10:00:00+00:00",
                "soft_stop": 102.0, "soft_why": "trail", "venue_stop": 101.5,
                "mfe_r": 2.0}
        row = _row(self.cfg, meta={"care": care})
        orc = born(self, row)
        track = OrcTrack.objects.get(orc=orc, arm="care")
        for key in ("peak", "worst", "since", "soft_stop", "soft_why"):
            self.assertEqual(track.state[key], care[key], key)
        self.assertEqual(track.state["venue_stop"], 98.0,
                         "the stop the venue holds: the row's stop_loss")
        self.assertEqual(track.state["mirror_venue_stop"], 101.5,
                         "the mirror's record, kept beside it")
        self.assertEqual(track.state["seeded_from"], "care")
        self.assertEqual((track.state["qty"], track.state["entry"],
                          track.state["initial_stop"], track.state["side"]),
                         (1.0, 100.0, 98.0, "BUY"))
        self.assertIsNone(track.state["last_tick_at"])
        self.assertTrue(track.open)
        AssetBotTrade.objects.filter(pk=row.pk).update(metadata={
            **row.metadata, "care": {**care, "soft_stop": 103.0}})
        born(self, AssetBotTrade.objects.get(pk=row.pk))
        track.refresh_from_db()
        self.assertEqual(track.state["soft_stop"], 102.0, "never reseeded")
        self.assertEqual(OrcTrack.objects.filter(orc=orc).count(), 1)
        fresh = born(self, _row(self.cfg, symbol="ETHUSD"))
        state = OrcTrack.objects.get(orc=fresh, arm="care").state
        self.assertEqual((state["seeded_from"], state["peak"],
                          state["worst"]), ("entry", 100.0, 100.0))

    def test_the_ghost_is_seeded_on_the_stop_the_venue_holds(self):
        """An adopted row whose venue stop was moved (by hand, or by the
        engine's own break-even) with no mirror record: the ghost starts on
        that stop, never on the looser initial one."""
        from bot_program.orcs.models import OrcTrack
        lane = _manual_config(self.user, "commodity", mode="live")
        row = _manual_row(lane, paper=False, symbol="XAUUSD", cls="commodity",
                          entry="2650", stop="2600", target="2750",
                          meta={"care": {"peak": 2680.0, "worst": 2640.0}})
        row.stop_loss = Decimal("2640")
        row.save(update_fields=["stop_loss"])
        with patch(NOTIFY):
            orc = born(self, row, adopted=True)
        state = OrcTrack.objects.get(orc=orc, arm="care").state
        self.assertEqual(state["initial_stop"], 2600.0)
        self.assertEqual(state["venue_stop"], 2640.0)
        self.assertIsNone(state["mirror_venue_stop"])
        # no stop on the row: the mirror's record, else nothing
        bare = _row(self.cfg, stop=None, symbol="ETHUSD",
                    meta={"care": {"venue_stop": 99.0}})
        state = OrcTrack.objects.get(orc=born(self, bare), arm="care").state
        self.assertEqual((state["venue_stop"], state["mirror_venue_stop"]),
                         (99.0, 99.0))

    def test_an_etoro_demo_row_sits_on_a_demo_seat_under_the_cap(self):
        """paper=False with broker_env "paper" is DEMO by the platform's own
        rule (position_summary.world_of): its own seat, never the real-money
        one; inside the cap on the Orcs outside real money; no phone line."""
        from dashboard.position_summary import world_of

        from bot_program.orcs.birth import ensure, notify_adopted
        from bot_program.orcs.models import Orc, OrcSeat, OrcSetting
        etoro = _config(self.user, mode="live", name="etoro bot")
        demo_meta = {"broker": "etoro", "broker_env": "paper"}
        demo = _row(etoro, paper=False, symbol="D1USD", meta=demo_meta)
        real = _row(etoro, paper=False, symbol="R1USD",
                    meta={"broker": "etoro", "broker_env": "live"})
        self.assertEqual((world_of(demo), world_of(real)), ("demo", "live"))
        with patch(NOTIFY) as note, \
                self.captureOnCommitCallbacks(execute=True):
            d = ensure(demo, adopted=True)
            r = ensure(real, adopted=True)
        self.assertEqual((d.seat.venue, d.seat.asset_class, d.seat.rule_key),
                         ("demo", "crypto", "*"))
        self.assertEqual(r.seat.venue, "live")
        self.assertNotEqual(d.seat, r.seat, "never pooled with real money")
        self.assertEqual([c.kwargs["title"][:len(f"Orc #{real.pk} ")]
                          for c in note.call_args_list],
                         [f"Orc #{real.pk} "], "a line for real money only")
        self.assertFalse(notify_adopted(d.pk))
        # one cap over paper and demo together; real money never capped
        OrcSetting.objects.create(key="max_paper_orcs", value=2)
        self.assertIsNotNone(born(self, _row(self.cfg, symbol="P1USD")))
        self.assertIsNone(born(self, _row(etoro, paper=False, symbol="D2USD",
                                          meta=demo_meta)),
                          "the demo row is over the cap")
        self.assertIsNone(born(self, _row(self.cfg, symbol="P2USD")),
                          "and so is the paper row")
        self.assertIsNotNone(born(self, _row(etoro, paper=False,
                                             symbol="R2USD")))
        self.assertEqual(OrcSeat.objects.filter(venue="live").count(), 1)
        self.assertEqual(Orc.objects.filter(seat__venue="live").count(), 2)

    def test_seats_are_l0_per_venue_class_and_rule_key(self):
        from bot_program.orcs.models import OrcSeat
        a = born(self, _row(self.cfg, symbol="S1USD"))
        b = born(self, _row(self.cfg, symbol="S2USD"))
        self.assertEqual(a.seat, b.seat)
        self.assertEqual((a.seat.venue, a.seat.asset_class, a.seat.rule_key,
                          a.seat.level), ("paper", "crypto", "*", 0))
        self.assertEqual(a.commission, "class")
        live = born(self, _row(_config(self.user, mode="live", name="l"),
                               paper=False, symbol="S3USD"))
        self.assertEqual((live.seat.venue, live.seat.rule_key),
                         ("live", "*"))
        hand = born(self, _manual_row(_manual_config(self.user),
                                      symbol="S4USD"))
        self.assertEqual((hand.seat.venue, hand.seat.rule_key),
                         ("paper", "manual_take"))
        self.assertEqual(OrcSeat.objects.count(), 3)
        self.assertEqual(set(OrcSeat.objects.values_list("level", flat=True)),
                         {0})

    def test_the_thesis_is_written_once_and_carries_no_money(self):
        from bot_program.models import AssetBotTrade
        meta = {"risk_dollars": 25.0, "capital_use": 1000.0,
                "notional_fraction": 0.1, "risk_fraction": 0.0025,
                "leverage": 2, "promotion_stage": "paper",
                "cost_fraction_charged": 0.001,
                "aragorn": {"state": "probation", "size": 0.5},
                "posture": {"level": "stressed", "kind": "risk_on_long",
                            "size": 0.5, "live": True,
                            "why": "a stressed tape"},
                "desk_size_mult": 0.75, "desk_lane": "swing",
                "debate": {"ran": True, "binding": False,
                           "champion_wins": False, "why": "w",
                           "executioner": {"verdict": "cut",
                                           "conviction": 0.7,
                                           "killer": "a sweep above"},
                           "champion": {"verdict": "back",
                                        "conviction": 0.6}}}
        row = _row(self.cfg, meta=meta)
        orc = born(self, row)
        th = orc.thesis
        self.assertEqual(th["source"], "entry")
        self.assertEqual(th["rule"], "golden_cross")
        self.assertEqual(th["provenance"]["debate"],
                         {"ran": True, "binding": False,
                          "champion_wins": False, "executioner": "cut",
                          "champion": "back", "killer": "a sweep above"})
        self.assertEqual(th["provenance"]["leverage"], 2)
        self.assertEqual(th["provenance"]["aragorn"],
                         {"state": "probation", "size": 0.5})
        self.assertEqual(th["provenance"]["posture"],
                         {"level": "stressed", "kind": "risk_on_long",
                          "size": 0.5, "live": True,
                          "why": "a stressed tape"})
        self.assertEqual((th["provenance"]["desk_size_mult"],
                          th["provenance"]["desk_lane"]), (0.75, "swing"))
        blob = json.dumps(th)
        for key in ("risk_dollars", "capital_use", "notional_fraction",
                    "risk_fraction", "conviction"):
            self.assertNotIn(key, blob)
        self.assertEqual(th["invalidation"], [
            {"kind": "time", "market_h": 72.0, "min_mfe_r": 1.0},
            {"kind": "displaced_bos_against", "tf": "4h"}])
        self.assertEqual(th["horizon_market_h"], 72.0)
        AssetBotTrade.objects.filter(pk=row.pk).update(
            reason="a new reason", metadata={**row.metadata,
                                             "leverage": 5})
        born(self, AssetBotTrade.objects.get(pk=row.pk))
        orc.refresh_from_db()
        self.assertEqual(orc.thesis, th, "immutable after birth")
        hand = born(self, _manual_row(_manual_config(self.user),
                                      symbol="H1USD", meta={
                                          "signal_id": 7,
                                          "size_source": "risk_budget",
                                          "theme_at_entry": {"ok": False,
                                                             "reason": "r"},
                                          "risk_dollars": 30.0}))
        self.assertEqual(hand.thesis["invalidation"],
                         [{"kind": "displaced_bos_against", "tf": "4h"}])
        self.assertEqual(hand.thesis["provenance"],
                         {"signal_id": 7, "size_source": "risk_budget",
                          "theme_at_entry": False})

    def test_a_scalp_thesis_holds_the_personas_hours_and_no_session_end(self):
        """The scalp persona's hold (personas.py, max_hold_hours 8) is the
        time predicate and the horizon; no clause ends the idea at a
        session's end (spec §1.6: the clock is the persona's)."""
        scalp = _config(self.user, extras={"persona": "scalp"}, name="sc")
        orc = born(self, _row(scalp, symbol="M1USD"), now=WED)
        th = orc.thesis
        self.assertEqual(th["invalidation"][0],
                         {"kind": "time", "market_h": 8.0, "min_mfe_r": 1.0})
        self.assertEqual(th["horizon_market_h"], 8.0)
        kinds = [p["kind"] for p in th["invalidation"]]
        self.assertEqual(kinds.count("time"), 1)
        self.assertEqual([k for k in kinds if "session" in k], [])
        self.assertNotIn("session", json.dumps(th["invalidation"]))

    def test_army_type_is_assigned_and_journaled_at_birth(self):
        from bot_program.orcs.birth import ensure
        scalp = _config(self.user, extras={"persona": "scalp"}, name="sc")
        with self.captureOnCommitCallbacks(execute=True):
            orc = ensure(_row(scalp, symbol="M1USD"), now=WED)
        self.assertEqual(orc.army_type, "mercenaries")
        self.assertEqual(orc.army_why["why"],
                         ["the config wears the scalp persona"])
        self.assertIn("Army: Mercenaries. The config wears the scalp persona.",
                      headlines(orc, kind="fact"))
        stock = _config(self.user, "stock", name="st")
        with self.captureOnCommitCallbacks(execute=True):
            deep = ensure(_row(stock, symbol="ORCB1", cls="stock"), now=WED)
        self.assertEqual(deep.army_type, "line")
        self.assertEqual(deep.army_why["overlay"], "corsairs")
        lines = headlines(deep, kind="fact")
        self.assertIn("Army: Line Orcs. The config wears no persona.", lines)
        self.assertIn("Corsair overlay: an overnight shut inside the "
                      "expected hold (Wednesday 20:00 UTC); a weekend shut "
                      "inside the expected hold (Friday 20:00 UTC).", lines)
        facts = [e.fact_id for e in journal(deep, kind="fact")]
        self.assertEqual(facts, ["F1", "F2"])


class TheCensusAndCommandTests(TestCase):

    def setUp(self):
        self.user = _user("orc_adopt")
        self.cfg = _config(self.user)

    def test_the_census_adopts_what_the_hooks_missed(self):
        from bot_program.orcs import census
        from bot_program.orcs.models import Orc, OrcSetting
        _on(False)
        rows = [_row(self.cfg, symbol=s) for s in ("C1USD", "C2USD", "C3USD")]
        real = _row(_config(self.user, mode="live", name="r"), paper=False,
                    symbol="C4USD")
        self.assertEqual(census.run()["status"], "skipped")
        self.assertEqual(Orc.objects.count(), 0)
        _on()
        OrcSetting.objects.create(key="max_paper_orcs", value=2)
        with patch(NOTIFY), self.captureOnCommitCallbacks(execute=True):
            out = census.run()
        self.assertEqual((out["born"], out["adopted"]), (3, 3))
        adopted = set(Orc.objects.values_list("root_trade_id", flat=True))
        self.assertEqual(adopted, {rows[0].pk, rows[1].pk, real.pk},
                         "paper rows oldest first under the cap")
        orc = Orc.objects.get(root_trade=rows[0])
        self.assertTrue(orc.adopted)
        self.assertEqual(orc.thesis["source"], "reconstructed")
        self.assertEqual(len(headlines(orc, kind="adopt")), 1)
        self.assertTrue(headlines(orc, kind="adopt")[0].startswith(
            f"Adopted at {_fmt(Decimal('100'))}, stop {_fmt(98.0)}. "))
        with self.captureOnCommitCallbacks(execute=True):
            again = census.run()
        self.assertEqual(again["born"], 0)

    def test_adoption_reconstructs_the_thesis_from_the_row(self):
        """§1.2: the reason, the care's history, the stop moves, the setup
        memory the ticket showed, the thesis check and the latest review."""
        from brain.position_review_models import PositionReview
        from bot_program.orcs.birth import ensure
        from tests.test_desk_seam import _signal as _seam_signal
        _on()
        care = {"soft_why": "trail", "mfe_r": 1.2,
                "since": "2026-10-12T08:00:00+00:00", "peak": 102.4}
        moves = [{"to": "99.0", "asked": "99.0", "at": "101.0",
                  "why": "breakeven:broker",
                  "when": "2026-10-12T09:00:00+00:00"},
                 {"to": "100.5", "asked": "100.5", "at": "102.4",
                  "why": "trail:broker",
                  "when": "2026-10-13T09:00:00+00:00"}]
        row = _row(self.cfg, meta={"care": care, "stop_moves": moves,
                                   "thesis": {"verdict": "hold"},
                                   "risk_dollars": 25.0})
        PositionReview.objects.create(
            book="bot", position_id=row.pk, symbol="BTCUSD", side="BUY",
            verdict="tighten", mark=101, unrealized_r=0.5)
        memory = {"ok": True, "thin": False, "n": 31, "avg_r": 0.4,
                  "words": "The last 31 times golden_cross fired on crypto: "
                           "55% won, +0.40R a trade."}
        with patch("backtester.proving.memory.memory_for",
                   return_value=memory) as mem, \
                patch(NOTIFY), self.captureOnCommitCallbacks(execute=True):
            orc = ensure(row, adopted=True)
        mem.assert_called_once_with("golden_cross", "BTCUSD", "crypto")
        self.assertEqual(orc.thesis["source"], "reconstructed")
        self.assertEqual(orc.thesis["reconstructed_from"], {
            "care": {"soft_why": "trail", "mfe_r": 1.2,
                     "since": "2026-10-12T08:00:00+00:00"},
            "stop_moves_n": 2,
            "stop_moves": [
                {"to": "99.0", "why": "breakeven:broker",
                 "when": "2026-10-12T09:00:00+00:00"},
                {"to": "100.5", "why": "trail:broker",
                 "when": "2026-10-13T09:00:00+00:00"}],
            "setup_memory": {"ok": True, "words": memory["words"]},
            "thesis_verdict": "hold",
            "last_review_verdict": "tighten"})
        self.assertNotIn("risk_dollars", json.dumps(orc.thesis))
        # a hand ticket taken on a signal: the SIGNAL's rule is remembered;
        # an unread memory reads ok False and never stops the adoption
        sig = _seam_signal("ORCH1", "bullish", 0.8, rule="sweep_rule",
                           asset_class="crypto")
        lane = _manual_config(self.user)
        hand = _manual_row(lane, symbol="ORCH1", meta={"signal_id": sig.pk})
        with patch("backtester.proving.memory.memory_for",
                   side_effect=RuntimeError("no bars")) as broken, \
                patch(NOTIFY), self.captureOnCommitCallbacks(execute=True):
            hand_orc = ensure(hand, adopted=True)
        broken.assert_called_once_with("sweep_rule", "ORCH1", "crypto")
        self.assertEqual(hand_orc.thesis["reconstructed_from"]["setup_memory"],
                         {"ok": False, "words": ""})
        bare = _manual_row(lane, symbol="ORCH2")
        with patch("backtester.proving.memory.memory_for") as none, \
                patch(NOTIFY), self.captureOnCommitCallbacks(execute=True):
            bare_orc = ensure(bare, adopted=True)
        none.assert_not_called()
        self.assertEqual(bare_orc.thesis["reconstructed_from"]["setup_memory"],
                         {"ok": False, "words": ""})

    def test_adopt_plans_by_default_writes_with_yes_and_refuses_while_off(self):
        from bot_program.orcs.models import Orc
        row = _row(self.cfg)
        _on(False)
        out = StringIO()
        call_command("orcs", "adopt", "--open", stdout=out)
        self.assertIn(f"#{row.pk}", out.getvalue())
        self.assertIn("orcs switch is OFF", out.getvalue())
        with self.assertRaises(CommandError):
            call_command("orcs", "adopt", "--open", "--yes", stdout=StringIO())
        self.assertEqual(Orc.objects.count(), 0)
        _on()
        plan = StringIO()
        call_command("orcs", "adopt", "--open", stdout=plan)
        self.assertIn("plan only", plan.getvalue())
        self.assertEqual(Orc.objects.count(), 0)
        done = StringIO()
        with patch(NOTIFY), self.captureOnCommitCallbacks(execute=True):
            call_command("orcs", "adopt", "--open", "--yes", stdout=done)
        self.assertEqual(Orc.objects.get().root_trade_id, row.pk)
        self.assertIn("adopted 1", done.getvalue())
        status = StringIO()
        call_command("orcs", stdout=status)
        self.assertIn(f"Orc #{row.pk}", status.getvalue())

    def test_the_plan_counts_the_cap_as_the_adoption_spends_it(self):
        from bot_program.orcs.models import Orc, OrcSetting
        _on()
        OrcSetting.objects.create(key="max_paper_orcs", value=1)
        rows = [_row(self.cfg, symbol=s) for s in ("P1USD", "P2USD", "P3USD")]
        etoro = _config(self.user, mode="live", name="etoro")
        demo = _row(etoro, paper=False, symbol="D1USD",
                    meta={"broker": "etoro", "broker_env": "paper"})
        real = _row(etoro, paper=False, symbol="R1USD")
        plan = StringIO()
        call_command("orcs", "adopt", "--open", stdout=plan)
        text = plan.getvalue()
        self.assertEqual(text.count("would be adopted"), 2, text)
        self.assertIn(f"#{rows[0].pk} P1USD long (paper): would be adopted",
                      text)
        self.assertIn(f"#{real.pk} R1USD long (real): would be adopted", text)
        for r, world in ((rows[1], "paper"), (rows[2], "paper"),
                         (demo, "demo")):
            self.assertIn(f"#{r.pk} {r.symbol} long ({world}): no Orc: the "
                          f"paper cap is full (1 at most outside real "
                          f"money).", text)
        done = StringIO()
        with patch(NOTIFY), self.captureOnCommitCallbacks(execute=True):
            call_command("orcs", "adopt", "--open", "--yes", stdout=done)
        self.assertEqual(set(Orc.objects.values_list("root_trade_id",
                                                     flat=True)),
                         {rows[0].pk, real.pk}, "the plan was the truth")
        status = StringIO()
        call_command("orcs", stdout=status)
        self.assertIn(f"Orc #{real.pk} R1USD long (real,", status.getvalue())
        self.assertIn(f"Orc #{rows[0].pk} P1USD long (paper,",
                      status.getvalue())

    def test_the_adoption_line_is_exact_real_rows_only(self):
        from bot_program.orcs.birth import ensure
        from bot_program.orcs.models import Orc
        _on()
        lane = _manual_config(self.user, "commodity", mode="live")
        hand = _manual_row(lane, paper=False, symbol="XAUUSD", cls="commodity",
                           entry="2650", stop="2630", target="2700")
        bot_cfg = _config(self.user, mode="live", name="real bot")
        bot_row = _row(bot_cfg, paper=False, side="SELL", stop="102",
                       target="90", symbol="ETHUSD")
        paper = _row(self.cfg, symbol="SOLUSD")
        with patch(NOTIFY) as note, self.captureOnCommitCallbacks(execute=True):
            ensure(hand, adopted=True)
            ensure(bot_row, adopted=True)
            ensure(paper, adopted=True)
        self.assertEqual(note.call_count, 2, "paper rows: the journal only")
        calls = {c.kwargs["title"]: c for c in note.call_args_list}
        self.assertIn(f"Orc #{hand.pk} adopted XAUUSD long (advise). Its "
                      f"thesis is reconstructed; state yours on its page.",
                      calls)
        self.assertIn(f"Orc #{bot_row.pk} adopted ETHUSD short (bot idea, "
                      f"shadow). Its thesis is reconstructed from the "
                      f"entry's record.", calls)
        for c in note.call_args_list:
            self.assertEqual(c.args[1], "orc_adopted")
            self.assertEqual(c.args[0], self.user)
        # a hook birth (not adopted) says nothing on the phone
        with patch(NOTIFY) as quiet, \
                self.captureOnCommitCallbacks(execute=True):
            ensure(_row(bot_cfg, paper=False, symbol="LTCUSD"))
        quiet.assert_not_called()
        self.assertEqual(Orc.objects.count(), 4)
        from bot_program.notifications import NOTIFY_MARKS, OPERATOR_KINDS
        self.assertIn("orc_adopted", OPERATOR_KINDS)
        self.assertIn("orc_adopted", NOTIFY_MARKS)
