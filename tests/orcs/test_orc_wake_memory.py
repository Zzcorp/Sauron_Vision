"""THE WAKE'S MEMORY, ITS CENSUS REASONS AND ITS RENDER OFF THE TICK
(bot_program/orcs/wake.py, journal.py; spec §1.3, §7.5; the O1c review).

  once        a reason read from a STATE (W4's thresholds and give-back,
              W6's close, W10) is remembered for life in seen["wake_once"]:
              however many later keys the rolling list keeps, "+1R
              reached" is recorded once
  the lock    the tick (`default`) and the census (`fast`) load the Orc in
              separate processes: the wake memory is merged under the
              Orc's lock, so neither erases what the other just wrote
  W3          the CLOSING-SIDE mark (a long's bid), once per level per
              W3_ONCE_H measured from that level's last W3, never a clock
              bucket
  W5          an earnings row is the symbol's own by the care's rule (its
              ticker, or a WORD of the title), never a substring; the
              nearest offset speaks and the farther ones are spent once;
              the words are code only
  W7          compared only on readable terms: an unreadable book or a
              stale posture is no change, the first reading is silent
  the render  the tick records the wake and its reasons in a handful of
              queries and never builds the dossier; the slow queue renders
              it as of its moment, with the care's state the tick saw
  the rows    a manual row, an adopted row, a forex row on a Saturday

Run with:  python manage.py test tests.orcs.test_orc_wake_memory
"""
from contextlib import ExitStack
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from tests.orcs.helpers import (_config, _manual_config, _manual_row, _on,
                                _row, _switch, _user, born)
from tests.orcs.test_orc_wake_detect import T0, _Detect

UTC = dt_tz.utc


def _w(code, key, t="a reason", urgent=False):
    return {"code": code, "key": key, "t": t, "urgent": urgent}


class TheOneShotMemoryTests(_Detect):

    def _roll(self, n=250):
        """A long life: n later rolling keys (W2 bars, W11 metronomes)."""
        from bot_program.orcs import journal
        from bot_program.orcs.constants import WAKE_KEYS_KEPT
        journal.remember(self.orc, wake_keys=journal.add_keys(
            WAKE_KEYS_KEPT, [f"W11:filler{i}" for i in range(n)]))
        self.orc.refresh_from_db()

    def test_plus_one_r_is_recorded_once_for_life(self):
        from bot_program.orcs.constants import WAKE_KEYS_KEPT
        self.tick(T0)
        self._care(mfe_r=1.05, r_now=1.05)
        self.tick(T0 + timedelta(minutes=16))
        self.assertIn("W4:+1", self.orc.seen["wake_once"])
        self.assertNotIn("W4:+1", self.orc.seen["wake_keys"])
        self._roll()
        self.assertEqual(len(self.orc.seen["wake_keys"]), WAKE_KEYS_KEPT)
        self.tick(T0 + timedelta(hours=1))
        self.tick(T0 + timedelta(hours=2))
        n = sum(1 for w in self.wakes() for r in w.reasons
                if r["t"] == "+1R reached")
        self.assertEqual(n, 1)

    def test_the_urgent_drawdowns_and_the_give_back_fire_once(self):
        self.tick(T0)
        self._care(mfe_r=2.0, mae_r=-0.6, r_now=0.9)
        self.tick(T0 + timedelta(minutes=1))
        first = [r["t"] for r in self.wakes()[-1].reasons]
        self.assertIn("-0.5R reached", first)
        self.assertIn("give-back to half the best", first)
        self._roll()
        self._care(mfe_r=2.0, mae_r=-0.6, r_now=1.8)
        self.tick(T0 + timedelta(minutes=30))
        later = [r["t"] for w in self.wakes()[2:] for r in w.reasons]
        for words in ("+1R reached", "+2R reached", "-0.5R reached",
                      "give-back to half the best"):
            self.assertNotIn(words, later)

    def test_a_close_in_doubt_fires_once_however_long_it_stands(self):
        from bot_program.models import AssetBotTrade
        self.tick(T0)
        meta = dict(self.row.metadata)
        meta["close_in_doubt"] = {"at": "2026-10-21T15:01:00+00:00"}
        AssetBotTrade.objects.filter(pk=self.row.pk).update(metadata=meta)
        self.row.metadata = meta
        self.tick(T0 + timedelta(minutes=2))
        self._roll()
        self.tick(T0 + timedelta(minutes=40))
        self.assertEqual(sum("W10" in self.codes(w) for w in self.wakes()),
                         1)

    def test_the_rolling_list_never_holds_a_key_twice(self):
        from bot_program.orcs import journal
        journal.remember(self.orc, wake_keys=journal.add_keys(5, ["a", "b"]))
        journal.remember(self.orc, wake_keys=journal.add_keys(5, ["b", "c"]))
        self.assertEqual(self.orc.seen["wake_keys"], ["a", "b", "c"])


class TheLockTests(_Detect):
    """Review (O1c): every writer of the wake memory merges under the
    Orc's lock. The tick holds the copy it loaded at its start; the
    census, in another process, writes in between."""

    def test_a_census_reason_queued_mid_tick_survives_the_tick_record(self):
        from bot_program.orcs import wake
        from bot_program.orcs.models import Orc
        self.tick(T0)
        stale = Orc.objects.get(pk=self.orc.pk)       # the tick loads it
        census_copy = Orc.objects.get(pk=self.orc.pk)
        self.assertTrue(wake._queue(census_copy, [
            _w("W7", "W7:mode:caution:x", "daily-loss mode caution")], T0))
        # the tick, holding its copy, records an urgent drawdown
        self._care(mfe_r=0.2, r_now=-0.6, mae_r=-0.6)
        bot = SimpleNamespace(_tick_broker_cache={}, cfg=self.cfg,
                              _last_ticks={})
        self.row._care_tick = {"now": T0 + timedelta(minutes=2)}
        with patch("django.utils.timezone.now",
                   return_value=T0 + timedelta(minutes=2)):
            w = wake.detect(bot, self.row, "100.5", "", stale)
        self.assertEqual([r["key"] for r in w.reasons], ["W4:-0.5"])
        pend = Orc.objects.get(pk=self.orc.pk).seen["wake_pending"]
        self.assertEqual([r["key"] for r in pend["reasons"]],
                         ["W7:mode:caution:x"],
                         "the census's reason waits for the next tick")
        self.tick(T0 + timedelta(minutes=20))         # after the spacing
        self.assertIn("daily-loss mode caution",
                      [r["t"] for r in self.wakes()[-1].reasons])

    def test_a_stale_census_never_erases_keys_a_tick_just_recorded(self):
        from bot_program.orcs import journal, wake
        from bot_program.orcs.constants import WAKE_KEYS_KEPT
        from bot_program.orcs.models import Orc
        self.tick(T0)
        stale = Orc.objects.get(pk=self.orc.pk)       # the census loads it
        self._care(mfe_r=1.05, r_now=1.05)
        self.tick(T0 + timedelta(minutes=16))          # records W4:+1
        # the census, on its old copy, spends a W5 key and re-queues the
        # +1R the tick has just recorded
        journal.remember(stale, wake_keys=journal.add_keys(
            WAKE_KEYS_KEPT, ["W5:9:-180"]))
        self.assertFalse(wake._queue(stale, [
            _w("W4", "W4:+1", "+1R reached")], T0 + timedelta(minutes=17)))
        seen = Orc.objects.get(pk=self.orc.pk).seen
        self.assertIn("W4:+1", seen["wake_once"])
        self.assertIn("W1", seen["wake_keys"])
        self.assertIn("W5:9:-180", seen["wake_keys"])
        self.assertFalse(seen.get("wake_pending"))

    def test_the_tick_consumes_only_the_reasons_it_recorded(self):
        from bot_program.orcs import journal
        journal.remember(self.orc, wake_pending=journal.add_reasons(
            [_w("W5", "W5:1:-60", "a print", True)], since=T0.isoformat()))
        journal.remember(self.orc, wake_pending=journal.consume_reasons(
            ["W5:1:-60"]))
        self.assertIsNone(self.orc.seen["wake_pending"])


class TheW3Tests(_Detect):

    def setUp(self):
        super().setUp()
        from bot_program.orcs.models import Orc
        from tests.orcs.helpers import _bars, _wave
        _bars("BTCUSD", "1h", _wave(200), start=T0 - timedelta(hours=200))
        th = dict(self.orc.thesis or {})
        th["invalidation"] = list(th.get("invalidation") or []) + [
            {"kind": "close_beyond", "tf": "4h", "level": 99.0,
             "level_id": "S4h-L1"}]
        Orc.objects.filter(pk=self.orc.pk).update(thesis=th)

    def _w3s(self):
        return sum("W3" in self.codes(w) for w in self.wakes())

    def test_the_closing_side_mark_not_the_tick_price(self):
        """A long closes at the bid: with the tick's last at the level and
        the bid 0.3 under it (the 1h ATR here is about 1, so the band is
        about 0.1), the closing-side mark is not near the level."""
        self.tick(T0)
        ticks = {"BTCUSD": {"lastPrice": "99.0", "bid": "98.7",
                            "ask": "99.3"}}
        self.tick(T0 + timedelta(minutes=2), price="99.0", ticks=ticks)
        self.assertEqual(self._w3s(), 0)
        ticks = {"BTCUSD": {"lastPrice": "99.3", "bid": "99.0",
                            "ask": "99.6"}}
        self.tick(T0 + timedelta(minutes=3), price="99.3", ticks=ticks)
        self.assertEqual(self._w3s(), 1, "the bid on the level")

    def test_eleven_fifty_nine_and_noon_are_one_w3(self):
        noon = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
        self.tick(noon - timedelta(hours=1))
        self.tick(noon - timedelta(minutes=1), price="99.0")
        self.tick(noon, price="99.0")
        self.tick(noon + timedelta(minutes=30), price="99.0")
        self.assertEqual(self._w3s(), 1)
        self.tick(noon + timedelta(hours=4), price="99.0")
        self.assertEqual(self._w3s(), 2, "W3_ONCE_H after the last one")


class TheCensusReasonTests(TestCase):

    def setUp(self):
        _switch("aragorn")
        _on()
        self.user = _user("orc_census_w")

    def _pending(self, orc):
        from bot_program.orcs.models import Orc
        return ((Orc.objects.get(pk=orc.pk).seen or {}).get("wake_pending")
                or {}).get("reasons") or []

    def _earnings(self, ticker, title, *, hours=10, ccy=None):
        from market_data.models import EconomicEvent
        return EconomicEvent.objects.create(
            title=title, country="US", impact="high",
            currency_affected=ccy if ccy is not None else ticker,
            source="fmp", datetime=T0 + timedelta(hours=hours))

    def test_earnings_by_the_ticker_never_a_substring(self):
        from bot_program.orcs import wake
        cfg = _config(self.user, "stock", name="st")
        t = born(self, _row(cfg, symbol="T", cls="stock"))
        ms = born(self, _row(cfg, symbol="MS", cls="stock"))
        aapl = born(self, _row(cfg, symbol="AAPL", cls="stock"))
        self._earnings("TSLA", "TSLA Earnings")
        self._earnings("MSFT", "MSFT Earnings")
        own = self._earnings("AAPL", "AAPL Earnings")
        wake.census_clock(T0)
        self.assertEqual(self._pending(t), [], "TSLA is not T's")
        self.assertEqual(self._pending(ms), [], "MSFT is not MS's")
        got = self._pending(aapl)
        self.assertEqual([r["key"] for r in got], [f"W5:{own.pk}:-1440"])
        self.assertEqual(got[0]["t"], f"AAPL earnings (C{own.pk}) in 10 h")

    def test_a_ticker_as_a_word_of_the_title_counts(self):
        from bot_program.orcs import wake
        cfg = _config(self.user, "stock", name="st")
        orc = born(self, _row(cfg, symbol="T", cls="stock"))
        self._earnings("", "AT&T (T) Earnings", ccy="")
        wake.census_clock(T0)
        self.assertEqual(len(self._pending(orc)), 1)

    def test_the_nearest_offset_speaks_the_farther_one_is_spent_once(self):
        from market_data.models import EconomicEvent

        from bot_program.orcs import wake
        from bot_program.orcs.models import Orc
        fx = _config(self.user, "forex", name="fx")
        orc = born(self, _row(fx, symbol="EURUSD", cls="forex", entry="1.10",
                              stop="1.09", target="1.12"))
        ev = EconomicEvent.objects.create(
            title="CPI m/m", country="US", impact="High",
            currency_affected="USD", source="forexfactory",
            datetime=T0 + timedelta(minutes=50))
        self.assertEqual(wake.census_clock(T0), 1)
        got = self._pending(orc)
        self.assertEqual([r["key"] for r in got], [f"W5:{ev.pk}:-60"])
        self.assertEqual(got[0]["t"],
                         f"a high-impact USD print (C{ev.pk}) in 50 min")
        keys = Orc.objects.get(pk=orc.pk).seen["wake_keys"]
        self.assertEqual(keys.count(f"W5:{ev.pk}:-180"), 1)
        for m in (5, 10, 15):
            wake.census_clock(T0 + timedelta(minutes=m))
        keys = Orc.objects.get(pk=orc.pk).seen["wake_keys"]
        self.assertEqual(keys.count(f"W5:{ev.pk}:-180"), 1,
                         "spent once, never appended every pass")
        self.assertEqual(len(self._pending(orc)), 1)

    def _book(self, value):
        from bot_program.orcs import sources
        return (sources.dash(value) if isinstance(value, str)
                else sources.ok(value))

    def test_w7_first_reading_silent_a_dash_is_no_change(self):
        from bot_program.orcs import sources, wake
        cfg = _config(self.user)
        orc = born(self, _row(cfg))
        ok = {"daily_loss_mode": "open", "open_risk_share": 0.1,
              "open_risk_t": "10% of its limit"}
        seq = [ok, "book unreadable", ok,
               {**ok, "daily_loss_mode": "caution"},
               {**ok, "daily_loss_mode": "caution", "open_risk_share": 0.85}]
        got = []
        for i, value in enumerate(seq):
            with patch.object(sources, "book",
                              return_value=self._book(value)):
                got.append(wake.census_book(T0 + timedelta(minutes=5 * i)))
        self.assertEqual(got, [0, 0, 0, 1, 1])
        words = [r["t"] for r in self._pending(orc)]
        self.assertEqual(words, ["daily-loss mode caution",
                                 "open risk at 85% of its limit"])

    def test_w7_a_book_first_read_after_a_dash_is_its_first_reading(self):
        """The census's first pass read the posture but not the book: the
        book's first readable mode is a first reading, never a change."""
        from bot_program.orcs import sources, wake
        cfg = _config(self.user)
        orc = born(self, _row(cfg))
        calm = sources.ok({"level": "calm"})
        got = []
        for i, b in enumerate(("book unreadable",
                               {"daily_loss_mode": "open",
                                "open_risk_share": 0.1,
                                "open_risk_t": "10%"})):
            with patch.object(sources, "book", return_value=self._book(b)), \
                    patch.object(sources, "posture", return_value=calm):
                got.append(wake.census_book(T0 + timedelta(minutes=5 * i)))
        self.assertEqual(got, [0, 0])
        self.assertEqual(self._pending(orc), [])

    def test_w7_a_stale_posture_keeps_the_last_reading(self):
        from bot_program.orcs import sources, wake
        cfg = _config(self.user)
        orc = born(self, _row(cfg))
        book = self._book({"daily_loss_mode": "open",
                           "open_risk_share": 0.1, "open_risk_t": "10%"})
        postures = [sources.ok({"level": "calm"}),
                    sources.dash("stale: last reading 3 h old"),
                    sources.ok({"level": "calm"}),
                    sources.ok({"level": "stressed"})]
        got = []
        for i, p in enumerate(postures):
            with patch.object(sources, "book", return_value=book), \
                    patch.object(sources, "posture", return_value=p):
                got.append(wake.census_book(T0 + timedelta(minutes=5 * i)))
        self.assertEqual(got, [0, 0, 0, 1])
        self.assertEqual([r["t"] for r in self._pending(orc)],
                         ["posture stressed"])


class TheRenderOffTheTickTests(_Detect):
    """Review (O1c): a recorded wake rendered the whole dossier inside
    AssetBot.manage_positions, between the care and the row's own checks.
    The tick now writes the wake and its reasons only; the slow queue
    renders it."""

    def test_a_recording_tick_writes_no_block_in_a_handful_of_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from bot_program.orcs import wake
        from bot_program.orcs.models import OrcDossierBlock, OrcWake
        from tests.orcs.helpers import _bars, _wave
        _bars("BTCUSD", "1h", _wave(200), start=T0 - timedelta(hours=200))
        _bars("BTCUSD", "4h", _wave(200), start=T0 - timedelta(hours=800))
        self.tick(T0)
        self._care(mfe_r=0.2, r_now=-0.6, mae_r=-0.6)
        bot = SimpleNamespace(_tick_broker_cache={}, cfg=self.cfg,
                              _last_ticks={})
        at = T0 + timedelta(minutes=2)
        self.row._care_tick = {"now": at}
        self.orc.refresh_from_db()
        self.orc._seen_before = dict(self.orc.seen)
        # the frames the tick's earlier steps already read (its per-pass
        # cache): detection reads them, never again
        from bot_program.orcs import bars
        for tf in ("4h", "1h"):
            bars.frame("BTCUSD", tf, asset_class="crypto", now=at,
                       cache=bot._tick_broker_cache)
        blocks = OrcDossierBlock.objects.count()
        with patch("django.utils.timezone.now", return_value=at), \
                CaptureQueriesContext(connection) as q:
            w = wake.detect(bot, self.row, "100.5", "", self.orc)
        self.assertIsNotNone(w)
        self.assertLessEqual(len(q.captured_queries), 8,
                             [x["sql"][:80] for x in q.captured_queries])
        self.assertEqual(OrcDossierBlock.objects.count(), blocks)
        w.refresh_from_db()
        self.assertEqual(w.components["render"], "queued")
        self.assertEqual(w.components["as_of"], at.isoformat())
        self.assertEqual(w.components["care"]["r_now"], -0.6)
        self.assertIsNone(w.score)
        self.assertEqual((w.status, w.skipped_reason),
                         ("skipped", "no model before O2"))
        self.assertEqual(wake.render_queued(), (1, 0))
        w = OrcWake.objects.get(pk=w.pk)
        self.assertEqual(w.components["render"], "done")
        self.assertIsNotNone(w.score)
        self.assertTrue(w.block_hashes)
        self.assertEqual(w.finished_at, at, "rendered as of its moment")

    def test_the_render_reads_the_care_the_tick_saw(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import OrcJournal, OrcWake
        self.tick(T0)
        self._care(mfe_r=1.05, r_now=1.05)
        self.tick(T0 + timedelta(minutes=16), render=False)
        # the care moves on before the slow queue renders the wake
        meta = dict(self.row.metadata)
        meta["care"] = {**meta["care"], "r_now": -0.2}
        AssetBotTrade.objects.filter(pk=self.row.pk).update(metadata=meta)
        from bot_program.orcs import wake
        wake.render_queued()
        w = OrcWake.objects.filter(orc=self.orc).order_by("id").last()
        entry = OrcJournal.objects.get(wake=w, kind="wake")
        self.assertAlmostEqual(entry.snapshot["r_now"], 1.05)


class TheRowsTests(TestCase):
    """One wake each on a manual row, an adopted row and a forex row on a
    Saturday: recorded in the tick, rendered off it."""

    def setUp(self):
        _switch("aragorn")
        _on()
        self.user = _user("orc_rows_w")

    def _tick(self, cfg, row, at, *, price="100.5"):
        from bot_program.orcs import wake
        from bot_program.orcs.observe import after_care
        bot = SimpleNamespace(_tick_broker_cache={}, cfg=cfg,
                              _last_ticks={})
        row._care_tick = {"now": at}
        with ExitStack() as st:
            st.enter_context(patch("django.utils.timezone.now",
                                   return_value=at))
            st.enter_context(self.captureOnCommitCallbacks(execute=True))
            after_care(bot, row, price, "")
            out = wake.render_queued()
        return out

    def _wakes(self, orc):
        from bot_program.orcs.models import OrcWake
        return list(OrcWake.objects.filter(orc=orc).order_by("id"))

    def test_a_manual_row(self):
        cfg = _manual_config(self.user)
        row = _manual_row(cfg)
        orc = born(self, row, at=T0 - timedelta(minutes=1))
        row.refresh_from_db()
        self.assertEqual(self._tick(cfg, row, T0), (1, 0))
        w = self._wakes(orc)[0]
        self.assertEqual(w.kind, "birth")
        self.assertGreaterEqual(w.components["stakes"], 5,
                                "a hand's stakes")

    def test_an_adopted_row(self):
        cfg = _config(self.user)
        row = _row(cfg)
        orc = born(self, row, at=T0 - timedelta(minutes=1), adopted=True)
        row.refresh_from_db()
        self.assertEqual(self._tick(cfg, row, T0), (1, 0))
        self.assertEqual([r["code"] for r in self._wakes(orc)[0].reasons],
                         ["W1"])

    def test_a_forex_row_on_a_saturday(self):
        """The market is shut: no metronome; an urgent reason is recorded
        and its dossier rendered on a Saturday trading day."""
        from bot_program.models import AssetBotTrade
        friday = datetime(2026, 10, 23, 18, 0, tzinfo=UTC)
        saturday = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
        fx = _config(self.user, "forex", name="fx")
        row = _row(fx, symbol="EURUSD", cls="forex", entry="1.10",
                   stop="1.09", target="1.12")
        orc = born(self, row, at=friday - timedelta(minutes=1))
        row.refresh_from_db()
        self._tick(fx, row, friday, price="1.1005")
        self.assertEqual(self._tick(fx, row, saturday, price="1.1005"),
                         (0, 0), "no metronome while the market is shut")
        meta = dict(row.metadata)
        meta["care"] = {**(meta.get("care") or {}), "mfe_r": 0.1,
                        "r_now": -0.6, "mae_r": -0.6}
        AssetBotTrade.objects.filter(pk=row.pk).update(metadata=meta)
        row.metadata = meta
        self.assertEqual(self._tick(fx, row, saturday + timedelta(minutes=5),
                                    price="1.094"), (1, 0))
        w = self._wakes(orc)[-1]
        self.assertEqual([r["code"] for r in w.reasons], ["W4"])
        self.assertTrue(w.block_hashes)


class TheBookOfTheOrcsWorldTests(TestCase):
    """Review (O1c on Council 2): the gates select on paper=False, which a
    venue's demo world (broker_env "paper") is too. The Orc's book reads
    its own money world (sources.book): a real Orc counts the world-live
    rows only, as the council's mood does, against the gates' limits and
    book size; a demo Orc has no book of its own and says so."""

    def setUp(self):
        from django.utils import timezone

        from portfolio.risk_gate import limits_book
        _switch("aragorn")
        _on()
        self.user = _user("orc_book_world")
        book = limits_book()
        book.max_daily_loss_pct = 8.0
        book.max_open_risk_pct = 15.0
        book.save()
        stub = patch("portfolio.risk_gate.venue_book_value",
                     return_value=(1000.0, "the /setup/ book"))
        stub.start()
        self.addCleanup(stub.stop)
        self.now = timezone.now()
        self.cfg = _config(self.user)
        # risk at the stop: 1 x |100 - 98| = 2 real, 4 x 2 = 8 demo
        self.live = born(self, _row(self.cfg, paper=False, symbol="BTCUSD",
                                    meta={"broker": "etoro",
                                          "broker_env": "live"}))
        self.demo = born(self, _row(self.cfg, paper=False, symbol="ETHUSD",
                                    qty="4", meta={"broker": "etoro",
                                                   "broker_env": "paper"}))

    def _demo_loss(self, pnl="-100"):
        """A demo close 10% of the book down within the gate's window."""
        from decimal import Decimal

        from bot_program.models import AssetBotTrade
        t = _row(self.cfg, paper=False, symbol="SOLUSD", status="CLOSED",
                 meta={"broker": "etoro", "broker_env": "paper"})
        AssetBotTrade.objects.filter(pk=t.pk).update(
            pnl=Decimal(pnl), closed_at=self.now - timedelta(hours=1))

    def test_the_live_book_counts_world_live_rows_only(self):
        from bot_program.orcs import sources
        from portfolio.risk_gate import daily_loss_state, open_risk_state
        # the gate itself counts the demo row with real money
        self.assertAlmostEqual(open_risk_state(self.user)["open_risk"], 10.0)
        b = sources.book(self.user, world="live")
        self.assertEqual(b["dash"], "")
        self.assertAlmostEqual(b["value"]["open_risk_share"], 2.0 / 150.0)
        self.assertEqual(b["value"]["open_risk_t"], "1% of its limit")
        self.assertEqual(b["value"]["daily_loss_mode"], "open")
        self._demo_loss()
        self.assertEqual(daily_loss_state(self.user, venue="live")["mode"],
                         "elite")
        self.assertEqual(sources.book(self.user, world="live")["value"]
                         ["daily_loss_mode"], "open",
                         "a demo loss never nets against real money")

    def test_a_demo_orc_has_no_book_of_its_own(self):
        from bot_program.orcs import dossier_position, sources
        b = sources.book(self.user, world="demo")
        self.assertIsNone(b["value"])
        self.assertEqual(b["dash"], "— (a demo world: no book of its own; "
                                    "the gates count it with real money)")
        demo_row = self.demo.root_trade
        self.assertEqual(dossier_position._ps4(
            self.demo, demo_row, {"world": "demo"})["book_headroom"],
            b["dash"])
        # a real Orc's headroom is its world's limit left, in its own R
        r_money = float(self.live.r_money)
        self.assertEqual(dossier_position._ps4(
            self.live, self.live.root_trade, {"world": "live"})
            ["book_headroom"], f"{150.0 * (1 - 2.0 / 150.0) / r_money:+.2f}R")

    def test_the_wake_reads_the_orcs_own_world(self):
        from bot_program.orcs import wake
        self.assertEqual(wake._world(self.live.root_trade), "live")
        self.assertEqual(wake._world(self.demo.root_trade), "demo")

    def test_w7_a_demo_loss_never_wakes_a_real_orc(self):
        from bot_program.orcs import wake
        from bot_program.orcs.models import Orc
        self.assertEqual(wake.census_book(T0), 0)
        self._demo_loss()
        self.assertEqual(wake.census_book(T0 + timedelta(minutes=5)), 0)
        for orc in (self.live, self.demo):
            seen = Orc.objects.get(pk=orc.pk).seen or {}
            reasons = (seen.get("wake_pending") or {}).get("reasons") or []
            self.assertFalse([r for r in reasons if r.get("code") == "W7"],
                             orc.label)
        state = Orc.objects.get(pk=self.live.pk).seen["book_state"]
        self.assertEqual(state["mode"], "open")
