"""THE THESIS'S PREDICATES (bot_program/orcs/predicates.py, spec §1.4):
written by code at birth, checked on venue bars, journaled as facts on
their transitions only, never silently dead, in O1 never a wake, and
forward only (§6.2): a bar before the Orc's birth never meets one.

Run with:  python manage.py test tests.orcs.test_orc_predicates
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from unittest.mock import patch

import pandas as pd
from django.test import SimpleTestCase, TestCase

from tests.orcs.helpers import _config, _on, _row, _user, born, headlines

T0 = datetime(2026, 10, 12, 0, 0, tzinfo=dt_tz.utc)          # a Monday


def _frame(closes, *, tf="4h", source="etoro", start=T0, fresh=True):
    from bot_program.orcs.bars import Frame, span_of
    idx = [start + i * span_of(tf) for i in range(len(closes))]
    df = pd.DataFrame({"open": closes, "high": [c + 0.5 for c in closes],
                       "low": [c - 0.5 for c in closes], "close": closes,
                       "volume": [0] * len(closes)},
                      index=pd.DatetimeIndex(idx))
    return Frame(symbol="BTCUSD", tf=tf, df=df, swings=[], source=source,
                 newest_end=idx[-1] + span_of(tf), fresh=fresh,
                 n=len(closes))


class TheWritingTests(SimpleTestCase):

    def test_code_invalidation_time_bos_close_beyond_frozen_levels(self):
        from bot_program.orcs.menu import Level, Menu
        from bot_program.orcs.predicates import code_invalidation
        menu = Menu(symbol="BTCUSD", as_of=T0, levels=[
            Level(id="S4h-L1", kind="swing", tf="4h", side="below",
                  price=99.0, stop=98.6),
            Level(id="S4h-L2", kind="swing", tf="4h", side="below",
                  price=98.8, stop=98.4),
            Level(id="S1h-L1", kind="swing", tf="1h", side="below",
                  price=99.5, stop=99.2),
            Level(id="RN-1", kind="round", tf="", side="below", price=99.9,
                  stop=99.4)])
        preds = code_invalidation(side="BUY", manual=False, hold_h=72.0,
                                  menu=menu, entry=100.0, init_stop=98.0)
        self.assertEqual(preds, [
            {"kind": "time", "market_h": 72.0, "min_mfe_r": 1.0,
             "by": "code"},
            {"kind": "displaced_bos_against", "tf": "4h", "by": "code"},
            {"kind": "close_beyond", "tf": "4h", "level_id": "S4h-L1",
             "level": 99.0, "side": "below", "by": "code"}])
        hand = code_invalidation(side="SELL", manual=True, hold_h=None,
                                 menu=menu, entry=100.0, init_stop=102.0)
        self.assertEqual([p["kind"] for p in hand],
                         ["displaced_bos_against"],
                         "no level above a short's entry in this menu")
        self.assertTrue(all(p["by"] == "code" for p in preds + hand))

    def test_decision_tf_is_1d_for_a_stock_with_60_fresh_venue_bars(self):
        from bot_program.orcs.menu import Menu
        from bot_program.orcs.predicates import decision_tf
        menu = Menu(symbol="AAPL", as_of=T0, fresh={"1d": True},
                    n={"1d": 60})
        self.assertEqual(decision_tf("stock", "line", menu), "1d")
        self.assertEqual(decision_tf("forex", "olog_hai", menu), "1d")
        self.assertEqual(decision_tf("forex", "line", menu), "4h")
        menu.n["1d"] = 59
        self.assertEqual(decision_tf("stock", "line", menu), "4h")


class TheEvaluationTests(SimpleTestCase):

    def test_close_beyond_on_closed_venue_bar_only(self):
        from bot_program.orcs.predicates import evaluate
        pred = {"kind": "close_beyond", "tf": "4h", "level_id": "S4h-L1",
                "level": 99.0, "side": "below"}
        frame = _frame([100.0, 99.5, 98.5])
        forming = T0 + timedelta(hours=9)          # the third bar forms
        res = evaluate(pred, frames={"4h": frame}, side="BUY",
                       asset_class="crypto", start=T0, mfe_r=0.0,
                       now=forming)
        self.assertEqual(res.state, "unmet", "a forming bar never counts")
        res = evaluate(pred, frames={"4h": frame}, side="BUY",
                       asset_class="crypto", start=T0, mfe_r=0.0,
                       now=T0 + timedelta(hours=12, minutes=5))
        self.assertEqual(res.state, "unmet", "a snapshot of a bar that just "
                         "ended, before the refresh rewrote it")
        res = evaluate(pred, frames={"4h": frame}, side="BUY",
                       asset_class="crypto", start=T0, mfe_r=0.0,
                       now=T0 + timedelta(hours=12, minutes=15))
        self.assertEqual((res.state, res.bar_at),
                         ("met", T0 + timedelta(hours=8)))
        plat = _frame([100.0, 99.5, 98.5], source="yfinance_public")
        res = evaluate(pred, frames={"4h": plat}, side="BUY",
                       asset_class="crypto", start=T0, mfe_r=0.0,
                       now=T0 + timedelta(hours=12, minutes=15))
        self.assertEqual(res.state, "unchecked", "venue bars only")

    def test_displaced_bos_uses_thesis_check_on_venue_bars(self):
        from bot_program.orcs.predicates import evaluate
        pred = {"kind": "displaced_bos_against", "tf": "4h"}
        frame = _frame([100.0] * 40)
        read = {"ok": True, "break_against": {"displaced": True,
                                              "bars_ago": 2}}
        with patch("brain.thesis_check.structure_read",
                   return_value=read) as sr:
            res = evaluate(pred, frames={"4h": frame}, side="BUY",
                           asset_class="crypto", start=T0, mfe_r=0.0,
                           now=T0 + timedelta(days=7), symbol="BTCUSD",
                           mark=99.0)
        self.assertEqual(res.state, "met")
        self.assertTrue(sr.call_args.kwargs["bars"][0].equals(frame.df),
                        "every bar is final a day later")
        self.assertEqual(res.bar_at, frame.df.index[37].to_pydatetime())
        with patch("brain.thesis_check.structure_read", return_value=read):
            before = evaluate(pred, frames={"4h": frame}, side="BUY",
                              asset_class="crypto",
                              start=T0 + timedelta(days=10), mfe_r=0.0,
                              now=T0 + timedelta(days=11))
        self.assertEqual(before.state, "unmet", "a break before the birth")
        read["break_against"]["displaced"] = False
        with patch("brain.thesis_check.structure_read", return_value=read):
            weak = evaluate(pred, frames={"4h": frame}, side="BUY",
                            asset_class="crypto", start=T0, mfe_r=0.0,
                            now=T0 + timedelta(days=7))
        self.assertEqual(weak.state, "unmet")

    def test_time_in_market_hours(self):
        from bot_program.orcs.predicates import evaluate
        pred = {"kind": "time", "market_h": 72.0, "min_mfe_r": 1.0}
        fri = datetime(2026, 10, 9, 12, 0, tzinfo=dt_tz.utc)
        mon = datetime(2026, 10, 12, 12, 0, tzinfo=dt_tz.utc)
        res = evaluate(pred, frames={}, side="BUY", asset_class="forex",
                       start=fri, mfe_r=0.3, now=mon)
        self.assertEqual(res.state, "unmet", "the weekend does not count")
        later = evaluate(pred, frames={}, side="BUY", asset_class="forex",
                         start=fri, mfe_r=0.3, now=mon + timedelta(days=2))
        self.assertEqual(later.state, "met")
        self.assertIn("market hours with the best only +0.30R (needed "
                      "+1.0R)", later.why)
        crypto = evaluate(pred, frames={}, side="BUY", asset_class="crypto",
                          start=fri, mfe_r=0.3, now=mon)
        self.assertEqual(crypto.state, "met", "crypto counts wall time")
        won = evaluate(pred, frames={}, side="BUY", asset_class="crypto",
                       start=fri, mfe_r=1.2, now=mon)
        self.assertEqual(won.state, "unmet")


class TheFactTests(TestCase):

    def setUp(self):
        _on()
        self.user = _user("orc_pred")
        self.row = _row(_config(self.user))
        self.orc = born(self, self.row, at=T0)
        th = dict(self.orc.thesis)
        th["invalidation"] = [{"kind": "close_beyond", "tf": "4h",
                               "level_id": "S4h-L1", "level": 99.0,
                               "side": "below", "by": "code"}]
        self.orc.thesis = th
        self.orc.save(update_fields=["thesis"])
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(pk=self.row.pk).update(opened_at=T0)
        self.row.refresh_from_db()
        self.n = len(headlines(self.orc, kind="fact"))

    def _check(self, frame, now):
        from bot_program.orcs.predicates import check
        return check(self.orc, self.row, now=now, frames={"4h": frame})

    def _new(self):
        return headlines(self.orc, kind="fact")[self.n:]

    def test_stale_unchecked_once_and_back(self):
        stale = _frame([100.0, 100.2], fresh=False)
        self._check(stale, T0 + timedelta(hours=20))
        self._check(stale, T0 + timedelta(hours=21))
        self.assertEqual(self._new(), [
            "Invalidation unchecked: no fresh 4h bar since 08:00 UTC "
            "2026-10-12."])
        fresh = _frame([100.0, 100.2, 100.1])
        self._check(fresh, T0 + timedelta(hours=12))
        self._check(fresh, T0 + timedelta(hours=12, minutes=5))
        self.assertEqual(self._new()[1:], [
            "Invalidation checked again: fresh 4h bars."])

    def test_facts_on_transitions_only(self):
        quiet = _frame([100.0, 100.2, 100.1])
        self._check(quiet, T0 + timedelta(hours=12))
        self.assertEqual(self._new(), [], "unmet from the start: no fact")
        broke = _frame([100.0, 100.2, 98.5, 98.0])
        self._check(broke, T0 + timedelta(hours=16))
        self._check(_frame([100.0, 100.2, 98.5, 98.0, 100.5]),
                    T0 + timedelta(hours=20))
        self.assertEqual(self._new(), [
            "Invalidation met: a 4h close below 99.00 (S4h-L1) at 08:00 UTC."
        ], "met once, and a met predicate stays met")
        self.orc.refresh_from_db()
        seen = self.orc.seen["predicates"]["close_beyond:4h:S4h-L1"]
        self.assertEqual(seen["state"], "met")

    def test_no_wake_no_agenttask(self):
        from ai_agents.models import AgentTask
        from bot_program.orcs.models import OrcWake
        self._check(_frame([100.0, 98.0]),
                    T0 + timedelta(hours=8, minutes=15))
        self.assertIn("Invalidation met", self._new()[0])
        self.assertEqual(OrcWake.objects.count(), 0)
        self.assertEqual(AgentTask.objects.count(), 0)

    def test_a_dead_orc_checks_no_predicate(self):
        from bot_program.orcs import observe
        self.orc.state = "dead"
        with patch("bot_program.orcs.predicates.check") as check:
            out = observe._check_predicates(None, self.row, 100.0, "",
                                            self.orc)
        self.assertIsNone(out)
        check.assert_not_called()
        self.assertIsNone(self.orc._orc_results)


HEAD = [(c, c + 0.2, c - 0.2, c) for c in
        (100.5 + (0.15 if i % 6 < 3 else -0.15) for i in range(48))]
TAIL = [
    (100.5, 100.7, 100.2, 100.4),   # 48 opens with the row, 48h before birth
    (100.4, 100.5, 98.7, 98.9),     # 49 the dump: a close at 98.9
    (98.9, 99.8, 98.85, 99.7),
    (99.7, 100.1, 99.5, 100.0),
    (100.0, 100.2, 99.7, 99.9),
    (99.9, 100.0, 99.4, 99.5),
    (99.5, 99.7, 99.2, 99.6),       # 54 the higher low, 99.2
    (99.6, 100.0, 99.5, 99.9),
    (99.9, 100.3, 99.8, 100.2),
    (100.2, 100.6, 100.1, 100.5),
    (100.5, 100.7, 100.3, 100.5),
    (100.5, 100.7, 100.3, 100.5),
]


class TheForwardOnlyTests(TestCase):
    """A BAR BEFORE THE BIRTH NEVER MEETS A PREDICATE (D9). An idea adopted
    48 hours after its open read the 4h closes from its open: the dump two
    days before the Orc existed met its close_beyond at adoption, and the
    playbook arm exited on it at once."""

    NOW = datetime(2026, 10, 14, 10, 0, tzinfo=dt_tz.utc)

    def test_adopted_idea_reads_closes_after_birth_only(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import census
        from bot_program.orcs.models import Orc
        from tests.orcs.helpers import _bars, _switch, drive, tracks_of
        _on()
        _switch("aragorn")
        cfg = _config(_user("orc_pred_forward"))
        _bars("BTCUSD", "4h", HEAD + TAIL,
              start=self.NOW - timedelta(hours=240))
        _bars("BTCUSD", "1h", [100.5] * 240,
              start=self.NOW - timedelta(hours=240))
        row = _row(cfg, entry="100", stop="98")
        AssetBotTrade.objects.filter(pk=row.pk).update(
            opened_at=self.NOW - timedelta(hours=48))
        row.refresh_from_db()
        with patch("django.utils.timezone.now", return_value=self.NOW), \
                self.captureOnCommitCallbacks(execute=True):
            census.run(now=self.NOW)
        orc = Orc.objects.get(root_trade=row)
        self.assertEqual(orc.born_at, self.NOW)
        self.assertIn({"kind": "close_beyond", "tf": "4h",
                       "level_id": "S4h-L1", "level": 99.2,
                       "side": "below", "by": "code"},
                      orc.thesis["invalidation"])
        drive(self, cfg, row, [(self.NOW + timedelta(minutes=5), "100.5")])
        self.assertEqual([h for h in headlines(orc)
                          if h.startswith("Invalidation met")], [])
        self.assertTrue(tracks_of(orc)["playbook"].open)
        # a close below the level after the birth meets it: the refresh's
        # pass after 14:00 rewrote the 10:00 bar and stored the forming one
        _bars("BTCUSD", "4h", [(100.4, 100.5, 98.9, 99.0),
                               (99.0, 99.1, 98.95, 99.05)], start=self.NOW)
        drive(self, cfg, row, [(self.NOW + timedelta(hours=4, minutes=5),
                                "100.2")])
        self.assertIn("Invalidation met: a 4h close below 99.20 (S4h-L1) "
                      "at 10:00 UTC.", headlines(orc))


# ── the review's findings (2026-10-22), each failing before its fix ──────

class TheFinalBarTests(TestCase):
    """A SNAPSHOT IS NOT A CLOSE. The bar refresh stores the forming candle
    and rewrites it on its next pass, up to ten minutes later: a predicate
    read the snapshot of a bar that had just ended as its close, memoised
    it, and saw the final bar one decision bar late; a snapshot beyond the
    level that finalised back inside wrote a met that stayed met."""

    D = datetime(2026, 10, 14, 0, 0, tzinfo=dt_tz.utc)     # a Wednesday

    def setUp(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import Orc
        from tests.orcs.helpers import _bars
        _on()
        self.row = _row(_config(_user("orc_pred_final")))
        AssetBotTrade.objects.filter(pk=self.row.pk).update(opened_at=self.D)
        self.row.refresh_from_db()
        self.orc = born(self, self.row, at=self.D + timedelta(hours=1))
        Orc.objects.filter(pk=self.orc.pk).update(
            thesis={"invalidation": [{"kind": "close_beyond", "tf": "4h",
                                      "level": 99.0, "side": "below",
                                      "level_id": "S4h-L1"}]}, seen={})
        self.orc.refresh_from_db()
        _bars("BTCUSD", "4h", [100.0] * 40,
              start=self.D - timedelta(hours=4 * 38))
        self.n = len(headlines(self.orc, kind="fact"))

    def _check(self, at):
        from bot_program.orcs.predicates import check
        self.orc.refresh_from_db()
        return [r.state for r in check(self.orc, self.row, now=at)]

    def _snapshot_then_final(self, snapshot, final):
        """The 04:00 bar as the refresh stored it at 07:52, then as its
        pass after 08:00 rewrote it (with the forming 08:00 bar)."""
        from tests.orcs.helpers import _bars
        _bars("BTCUSD", "4h", [snapshot], start=self.D + timedelta(hours=4))
        first = self._check(self.D + timedelta(hours=8, minutes=1))
        _bars("BTCUSD", "4h", [final, (final[3], 99.8, 98.6, 99.0)],
              start=self.D + timedelta(hours=4))
        return first, self._check(self.D + timedelta(hours=8, minutes=11))

    def test_the_final_close_beyond_is_read_on_the_next_pass(self):
        first, second = self._snapshot_then_final(
            (100.0, 100.1, 99.4, 99.6), (100.0, 100.1, 98.5, 98.7))
        self.assertEqual((first, second), (["unmet"], ["met"]))
        self.assertEqual(headlines(self.orc, kind="fact")[self.n:], [
            "Invalidation met: a 4h close below 99.00 (S4h-L1) at 04:00 UTC."])

    def test_a_snapshot_beyond_that_finalises_inside_never_meets(self):
        first, second = self._snapshot_then_final(
            (100.0, 100.1, 98.5, 98.7), (100.0, 100.1, 98.5, 99.6))
        self.assertEqual((first, second), (["unmet"], ["unmet"]))
        self.assertEqual(headlines(self.orc, kind="fact")[self.n:], [])

    def test_a_rewritten_bar_is_read_again(self):
        """The memo keeps the bar's close: a final bar rewritten after it
        was read (a late correction) is read again."""
        from tests.orcs.helpers import _bars
        _bars("BTCUSD", "4h", [(100.0, 100.1, 99.4, 99.6)],
              start=self.D + timedelta(hours=4))
        at = self.D + timedelta(hours=8, minutes=20)
        self.assertEqual(self._check(at), ["unmet"])
        _bars("BTCUSD", "4h", [(100.0, 100.1, 98.5, 98.7)],
              start=self.D + timedelta(hours=4))
        self.assertEqual(self._check(at + timedelta(minutes=5)), ["met"])


class TheFinalStructureTests(SimpleTestCase):

    def test_the_structure_read_never_sees_the_forming_bar(self):
        from bot_program.orcs.predicates import evaluate
        pred = {"kind": "displaced_bos_against", "tf": "4h"}
        frame = _frame([100.0] * 40 + [96.0])          # the 41st forms
        now = T0 + timedelta(hours=4 * 40, minutes=30)
        with patch("brain.thesis_check.structure_read",
                   return_value={"ok": False}) as sr:
            evaluate(pred, frames={"4h": frame}, side="BUY",
                     asset_class="crypto", start=T0, mfe_r=0.0, now=now,
                     symbol="BTCUSD", mark=99.0)
        df = sr.call_args.kwargs["bars"][0]
        self.assertEqual(len(df), 40)
        self.assertNotIn(96.0, list(df["close"]))


class TheUnreadExcursionTests(SimpleTestCase):
    """AN UNREAD EXCURSION IS NOT A SMALL ONE. With the care switched off
    the row has no best excursion; the time predicate read None as below
    the floor, met after its hours whatever the position did, cut the
    playbook arm and wrote a 'thesis dead' fact that stayed met."""

    def test_time_with_no_measured_excursion_is_unchecked(self):
        from bot_program.orcs.predicates import evaluate, unchecked_line
        pred = {"kind": "time", "market_h": 72.0, "min_mfe_r": 1.0}
        fri = datetime(2026, 10, 9, 12, 0, tzinfo=dt_tz.utc)
        mon = datetime(2026, 10, 12, 12, 0, tzinfo=dt_tz.utc)
        res = evaluate(pred, frames={}, side="BUY", asset_class="crypto",
                       start=fri, mfe_r=None, now=mon)
        self.assertEqual(res.state, "unchecked")
        self.assertEqual(unchecked_line(pred, res),
                         "Invalidation unchecked: the care has measured no "
                         "best excursion, so the time predicate cannot be "
                         "read.")
        early = evaluate(pred, frames={}, side="BUY", asset_class="crypto",
                         start=fri, mfe_r=None, now=fri + timedelta(hours=5))
        self.assertEqual(early.state, "unmet", "inside its hours")


class TheCareOffTimeTests(TestCase):

    def test_care_off_never_meets_the_time_predicate_through_the_tick(self):
        from bot_program.models import AssetBotTrade
        from tests.orcs.helpers import _switch, drive, tracks_of
        _on()
        _switch("aragorn", False)
        cfg = _config(_user("orc_pred_care_off"))
        row = _row(cfg)
        AssetBotTrade.objects.filter(pk=row.pk).update(opened_at=T0)
        row.refresh_from_db()
        orc = born(self, row, at=T0)
        self.assertIn("time", [p["kind"] for p in
                               orc.thesis["invalidation"]])
        drive(self, cfg, row, [(T0 + timedelta(hours=73), "108.0")])
        said = headlines(orc, kind="fact")
        self.assertEqual([h for h in said if h.startswith(
            "Invalidation met")], [])
        self.assertIn("Invalidation unchecked: the care has measured no "
                      "best excursion, so the time predicate cannot be "
                      "read.", said)
        self.assertTrue(tracks_of(orc)["playbook"].open)
        _switch("aragorn", True)
        drive(self, cfg, row, [(T0 + timedelta(hours=74), "108.1")])
        said = headlines(orc, kind="fact")
        self.assertIn("Invalidation checked again: the care measures the "
                      "best excursion again.", said)
        self.assertEqual([h for h in said if h.startswith(
            "Invalidation met")], [])
