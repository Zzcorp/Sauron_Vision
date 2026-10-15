"""A paper stop books like a resting stop (2026-10-08).

A paper GBPUSD BUY opened 2026-09-03 with its stop about 30 pips under
the entry, was booked on 2026-09-28 at -8.12R. Nothing had managed it for
weeks, and a paper stop was only a per-tick comparison of one mark with the
level (base.manage_positions, the SL/TP check), so the first tick that acted
booked it at the far price it saw, at the time it saw it. A resting stop at a
broker would have filled at the stop, or at the open of the bar that gapped
through it. The morning brief then read that simulator booking as "a failed
stop or a sizing error", and the promotion ladder reads the same record.

Pinned here (bot_program/paper_exits.py and base.manage_positions):
  - the far-mark shape: the bars went through the stop days ago, the first tick
    books at the stop (or the gap's open), at the crossing bar's time,
    never -8R;
  - a gapped bar books at its open, never better: the tick's mark having
    come back near the stop no longer flatters the rule;
  - a crossing that came back is booked, where the mark alone never saw it;
  - a target books at the target, never better, even when the bar gapped
    through it; both levels in one bar: the stop;
  - the level booked is always a price the bar traded, and the modelled
    half cost is charged on top of it;
  - a row with no bars is managed as before (the mark), and its tick is
    stamped without moving the bar cursor;
  - the tick is stamped (paper_replay: tick_at, bars_through, levels), and a
    stop moved before replay existed never books an old bar;
  - a bar past the time-stop ceiling is the clock's, not the stop's, and a
    ceiling no managed tick saw books from its bar, never the far mark;
  - a real row is never replayed.
Pinned from the review of 2026-10-15 (the classes after
AStopMovedBetweenTicksTests):
  - a stop or target moved inside a bar never books a crossing printed
    before the move, however many ticks the bar sees (the level history);
  - the bar sanity: a near-zero print or a lone spike books nothing, a
    held move does, a gap's open must be confirmed, and bars of another
    instrument (futures against spot) are not replayed;
  - a stop touched at the bar's low pays the modelled cost;
  - a bar that starts shut and opens inside books at the settled open;
  - a hand-moved target is not tested against bars before the edit;
  - a hole in the 1h bars is read on the 4h bar, and a late 1h bar is
    still read;
  - an exit from the mark after an unmanaged stretch the bars cannot cover
    is closed ungraded;
  - the stamp is written onto the row as it stands, under its lock.

Run with:  python manage.py test tests.test_paper_stop_replay
"""
from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

ENTRY, STOP, TP = D("1.34991"), D("1.34690"), D("1.36000")
RISK = float(ENTRY - STOP)


def _setup(test, *, side="BUY", entry=ENTRY, stop=STOP, tp=TP,
           opened_hours=72, initial=None, paper=True, mode="paper",
           metadata=None):
    from bot_program.asset_models import AssetBotConfig, AssetBotTrade
    from instruments.models import Instrument
    test.inst, _ = Instrument.objects.get_or_create(
        symbol="GBPUSD", defaults={"asset_class": "forex", "name": "GBPUSD"})
    test.user = User.objects.create_user(f"replay_{id(test)}_{side}")
    test.cfg = AssetBotConfig.objects.create(
        user=test.user, asset_class="forex", name="fx paper", enabled=True,
        mode=mode, capital=D("10000"), symbols=["GBPUSD"])
    meta = {"initial_stop_loss": float(initial if initial is not None
                                       else stop)}
    meta.update(metadata or {})
    trade = AssetBotTrade.objects.create(
        config=test.cfg, asset_class="forex", symbol="GBPUSD", side=side,
        qty=D("1000"), entry_price=entry, stop_loss=stop, take_profit=tp,
        rule_name="rsi_bull_divergence", paper=paper, status="OPEN",
        metadata=meta)
    test.now = timezone.now()
    test.opened = test.now - timedelta(hours=opened_hours)
    AssetBotTrade.objects.filter(pk=trade.pk).update(opened_at=test.opened)
    trade.refresh_from_db()
    return trade


def _hour(t):
    return t.replace(minute=0, second=0, microsecond=0)


def _bars(test, spec, *, flat=D("1.3490"), tf="1h"):
    """1h bars from the first full hour after the open to the current hour.
    `spec` maps hours-ago (of the bar's open) to (open, high, low, close);
    every other bar is flat around `flat`."""
    from market_data.models import PriceData
    PriceData.objects.filter(instrument=test.inst).delete()
    step = timedelta(hours=1 if tf == "1h" else 4)
    ts = _hour(test.opened) + timedelta(hours=1)
    last = _hour(test.now)
    rows = []
    while ts <= last:
        ago = int(round((last - ts).total_seconds() / 3600))
        o, h, low, c = spec.get(ago, (flat, flat + D("0.0005"),
                                      flat - D("0.0005"), flat))
        rows.append(PriceData(instrument=test.inst, timeframe=tf,
                              timestamp=ts, open=o, high=h, low=low, close=c,
                              source="test"))
        ts += step
    PriceData.objects.bulk_create(rows)
    return {int(round((last - r.timestamp).total_seconds() / 3600)): r
            for r in rows}


def _after(spec, frm, to, price):
    """Bars `frm`..`to` hours ago (inclusive, frm > to) trading near price."""
    for ago in range(to, frm + 1):
        spec[ago] = (price, price + D("0.0003"), price - D("0.0003"), price)
    return spec


def _quote(test, price, age_s=60):
    from market_data.models import LiveQuote
    LiveQuote.objects.filter(instrument=test.inst).delete()
    if price is None:
        return
    LiveQuote.objects.create(instrument=test.inst, last=price, source="test")
    LiveQuote.objects.filter(instrument=test.inst).update(
        updated_at=timezone.now() - timedelta(seconds=age_s))


def _tick(test):
    from bot_program.asset_engine.base import make_bot
    with patch("bot_program.aragorn.is_on", return_value=False):
        return make_bot(test.cfg).manage_positions()


class TheMinusEightShapeTests(TestCase):
    """GBPUSD long, stop 30 pips under the entry, the bars went through it
    20 hours ago and the market ran on to 1.3255: the first tick books at
    the stop, never at the far mark."""

    def setUp(self):
        self.trade = _setup(self)
        spec = {20: (D("1.3478"), D("1.3480"), D("1.3465"), D("1.3467"))}
        self.bars = _bars(self, _after(spec, 19, 0, D("1.3260")))
        _quote(self, D("1.32549"))

    def test_the_first_tick_books_at_the_stop_never_minus_eight(self):
        self.assertEqual(_tick(self), 1)
        t = self.trade
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        self.assertIn("closed:SL", t.reason)
        self.assertEqual(t.outcome, "stopped_out")
        crossing = self.bars[20]
        # at the stop less the modelled half cost (here above the bar's low)
        self.assertLessEqual(t.exit_price, STOP)
        self.assertGreaterEqual(t.exit_price, crossing.low)
        self.assertGreater(t.realized_r, -1.2)
        self.assertLess(t.realized_r, -0.9)

    def test_it_is_booked_when_the_bar_crossed_not_when_the_tick_saw_it(self):
        _tick(self)
        self.trade.refresh_from_db()
        self.assertEqual(self.trade.closed_at, self.bars[20].timestamp)
        rec = self.trade.metadata["paper_exit"]
        self.assertEqual(rec["model"], "bar_replay")
        self.assertEqual(rec["tf"], "1h")
        self.assertFalse(rec["gapped"])
        self.assertEqual(rec["source"], "test")
        self.assertEqual(D(str(rec["level"])), STOP)

    def test_with_no_quote_the_bar_close_never_books_minus_eight_either(self):
        _quote(self, None)
        _tick(self)
        self.trade.refresh_from_db()
        self.assertEqual(self.trade.status, "CLOSED")
        self.assertGreater(self.trade.realized_r, -1.2)


class AGapBooksAtItsOpenTests(TestCase):
    def setUp(self):
        self.trade = _setup(self)
        spec = {20: (D("1.3440"), D("1.3442"), D("1.3432"), D("1.3436"))}
        self.spec = spec

    def test_a_bar_that_opened_through_the_stop_books_at_its_open(self):
        bars = _bars(self, _after(self.spec, 19, 0, D("1.3440")))
        _quote(self, D("1.34400"))
        _tick(self)
        t = self.trade
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        self.assertTrue(t.metadata["paper_exit"]["gapped"])
        self.assertLessEqual(t.exit_price, D("1.3440"))
        self.assertGreaterEqual(t.exit_price, bars[20].low)
        self.assertAlmostEqual(t.realized_r,
                               -float(ENTRY - D("1.3440")) / RISK, delta=0.1)

    def test_a_mark_back_near_the_stop_no_longer_flatters_the_gap(self):
        """Run G of the audit: the gapped resting stop fills near -1.96R;
        the mark alone, back at 1.34685, booked -1.06R."""
        _bars(self, _after(self.spec, 19, 0, D("1.3469")))
        _quote(self, D("1.34685"))
        _tick(self)
        self.trade.refresh_from_db()
        self.assertLess(self.trade.realized_r, -1.8)


class ACrossingThatCameBackTests(TestCase):
    def test_it_is_booked_where_the_mark_alone_never_saw_it(self):
        trade = _setup(self)
        spec = {20: (D("1.3478"), D("1.3480"), D("1.3465"), D("1.3476"))}
        _bars(self, _after(spec, 19, 0, D("1.3492")))
        _quote(self, D("1.34920"))
        self.assertEqual(_tick(self), 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertIn("closed:SL", trade.reason)


class TheTargetTests(TestCase):
    def test_a_target_books_at_the_target_never_the_better_open(self):
        trade = _setup(self)
        spec = {10: (D("1.3650"), D("1.3660"), D("1.3640"), D("1.3655"))}
        bars = _bars(self, _after(spec, 9, 0, D("1.3655")))
        _quote(self, D("1.36550"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertIn("closed:TP", trade.reason)
        self.assertEqual(trade.outcome, "hit_target")
        self.assertLessEqual(trade.exit_price, TP)
        self.assertEqual(trade.closed_at, bars[10].timestamp)

    def test_both_levels_in_one_bar_book_the_stop(self):
        trade = _setup(self)
        spec = {10: (D("1.3490"), D("1.3610"), D("1.3460"), D("1.3500"))}
        _bars(self, _after(spec, 9, 0, D("1.3500")))
        _quote(self, D("1.35000"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertIn("closed:SL", trade.reason)
        self.assertEqual(trade.outcome, "stopped_out")

    def test_a_short_mirrors_the_long(self):
        trade = _setup(self, side="SELL", entry=D("1.34691"),
                       stop=D("1.34992"), tp=D("1.33000"))
        spec = {20: (D("1.3520"), D("1.3530"), D("1.3515"), D("1.3525"))}
        bars = _bars(self, _after(spec, 19, 0, D("1.3700")),
                     flat=D("1.3470"))
        _quote(self, D("1.37000"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertTrue(trade.metadata["paper_exit"]["gapped"])
        # the gap's open, never past the bar's high
        self.assertGreaterEqual(trade.exit_price, D("1.3520"))
        self.assertLessEqual(trade.exit_price, bars[20].high)
        self.assertGreater(trade.realized_r, -2.0)


class NoBarsTests(TestCase):
    def test_a_row_with_no_bars_is_managed_as_before(self):
        trade = _setup(self)
        _quote(self, D("1.32549"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertNotIn("paper_exit", trade.metadata)
        self.assertLess(trade.realized_r, -7.5)
        self.assertGreater(trade.closed_at,
                           timezone.now() - timedelta(minutes=5))

    def test_its_tick_is_stamped_and_the_bar_cursor_stays(self):
        trade = _setup(self)
        _quote(self, D("1.34900"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        stamp = trade.metadata["paper_replay"]
        self.assertIn("tick_at", stamp)
        self.assertIsNone(stamp.get("bars_through"))


class TheStampTests(TestCase):
    def test_a_tick_with_no_crossing_stamps_the_tick_and_the_bars(self):
        trade = _setup(self)
        bars = _bars(self, {})
        _quote(self, D("1.34900"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        stamp = trade.metadata["paper_replay"]
        self.assertIsNotNone(stamp["tick_at"])
        # the newest COMPLETE bar is the one that opened an hour ago
        newest_complete = bars[1].timestamp + timedelta(hours=1)
        self.assertEqual(stamp["bars_through"], newest_complete.isoformat())
        self.assertEqual(D(str(stamp["stop"])), STOP)

    def test_a_stop_moved_before_replay_existed_never_books_an_old_bar(self):
        """An unstamped row whose stop was trailed: the old bars traded
        under the NEW stop while the old one was in force."""
        trade = _setup(self, stop=D("1.34950"), initial=STOP)
        spec = {30: (D("1.3490"), D("1.3492"), D("1.3480"), D("1.3490"))}
        _bars(self, _after(spec, 29, 0, D("1.3530")), flat=D("1.3530"))
        _quote(self, D("1.35300"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIn("paper_replay", trade.metadata)

    def test_a_crossing_after_the_time_ceiling_is_the_clocks(self):
        """The ceiling fell due 20h ago with no managed tick to see it: the
        time stop books from the first bar at or past it (2026-10-15),
        never the stop crossed 5h ago, never the mark of this tick."""
        trade = _setup(self, opened_hours=30)
        self.cfg.max_hold_hours = 10
        self.cfg.save(update_fields=["max_hold_hours"])
        spec = {5: (D("1.3478"), D("1.3480"), D("1.3465"), D("1.3467"))}
        bars = _bars(self, _after(spec, 4, 0, D("1.3470")))
        _quote(self, D("1.34700"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertIn("closed:TIME", trade.reason)
        self.assertEqual(trade.outcome, "time_stop")
        rec = trade.metadata["paper_exit"]
        self.assertEqual(rec["reason"], "TIME")
        ceiling = self.opened + timedelta(hours=10)
        first = min((b for b in bars.values() if b.timestamp >= ceiling),
                    key=lambda b: b.timestamp)
        self.assertEqual(trade.closed_at, first.timestamp)
        self.assertEqual(D(str(rec["level"])), first.open)


class RealRowsAreNeverReplayedTests(TestCase):
    def test_a_real_row_is_not_replayed(self):
        from bot_program import paper_exits
        trade = _setup(self, paper=False, mode="live")
        spec = {20: (D("1.3478"), D("1.3480"), D("1.3465"), D("1.3467"))}
        _bars(self, _after(spec, 19, 0, D("1.3260")))
        self.assertIsNone(paper_exits.replay(trade, now=timezone.now()))


class TheFourHourFallbackTests(TestCase):
    def test_with_no_hourly_bars_the_four_hour_bar_is_tested(self):
        trade = _setup(self)
        spec = {}
        bars = _bars(self, spec, tf="4h")
        # the 4h bar that opened 20-24h ago crosses the stop
        from market_data.models import PriceData
        crossing = min((b for b in bars.values()
                        if b.timestamp <= self.now - timedelta(hours=20)),
                       key=lambda b: abs((self.now - b.timestamp)
                                         - timedelta(hours=22)))
        PriceData.objects.filter(pk=crossing.pk).update(
            open=D("1.3478"), high=D("1.3480"), low=D("1.3465"),
            close=D("1.3467"))
        _quote(self, D("1.34900"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.metadata["paper_exit"]["tf"], "4h")
        self.assertEqual(trade.closed_at, crossing.timestamp)
        self.assertGreater(trade.realized_r, -1.2)


class AStopMovedBetweenTicksTests(TestCase):
    def test_the_bar_straddling_the_move_is_tested_against_the_looser_stop(self):
        """Tick 1 tests the bars under the stop then in force and stamps
        it; the stop is then tightened (as trailing does, after the
        replay). The bar that began before tick 1 is tested on the next
        ticks against the LOOSER stop: its low under the new stop but above
        the old one is no exit. A later bar under the new stop is one."""
        from bot_program import paper_exits
        from market_data.models import PriceData
        trade = _setup(self)
        _bars(self, {})
        b = _hour(self.now) - timedelta(hours=3)        # the straddling bar
        t1, t2 = b + timedelta(minutes=10), b + timedelta(minutes=40)
        first = paper_exits.replay(trade, now=t1)
        self.assertIsNone(first["hit"])
        paper_exits.stamp(trade, first, now=t1)
        trade.stop_loss = D("1.34800")
        trade.save(update_fields=["stop_loss"])
        PriceData.objects.filter(instrument=self.inst, timeframe="1h",
                                 timestamp=b).update(low=D("1.3478"))
        self.assertIsNone(paper_exits.replay(trade, now=t2)["hit"])
        PriceData.objects.filter(
            instrument=self.inst, timeframe="1h",
            timestamp=b + timedelta(hours=1)).update(low=D("1.3479"))
        later = paper_exits.replay(trade, now=b + timedelta(hours=1,
                                                            minutes=5))
        self.assertEqual(later["hit"]["reason"], "SL")
        self.assertEqual(later["hit"]["level"], 1.348)
        self.assertEqual(later["hit"]["bar_ts"], b + timedelta(hours=1))


# ── The review of 2026-10-15 ──────────────────────────────────────────────

from datetime import datetime, timezone as dtz  # noqa: E402


def _at(*a):
    return datetime(*a, tzinfo=dtz.utc)


def _fixed(test, *, symbol="GBPUSD", cls="forex", side="BUY", entry, stop,
           tp, opened, extras=None, metadata=None, initial=None,
           max_hold=None, exchange=""):
    """A paper row opened at a fixed instant, with its own instrument and
    config; no bars yet."""
    from bot_program.asset_models import AssetBotConfig, AssetBotTrade
    from instruments.models import Instrument
    test.inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"asset_class": cls, "name": symbol,
                                 "exchange": exchange})
    test.user = User.objects.create_user(f"fixed_{id(test)}_{symbol}_{side}")
    test.cfg = AssetBotConfig.objects.create(
        user=test.user, asset_class=cls, name=f"{cls} paper", enabled=True,
        mode="paper", capital=D("10000"), symbols=[symbol],
        extras=dict(extras or {}))
    if max_hold is not None:
        test.cfg.max_hold_hours = max_hold
        test.cfg.save(update_fields=["max_hold_hours"])
    meta = {"initial_stop_loss": float(initial if initial is not None
                                       else stop)}
    meta.update(metadata or {})
    trade = AssetBotTrade.objects.create(
        config=test.cfg, asset_class=cls, symbol=symbol, side=side,
        qty=D("1000"), entry_price=D(str(entry)), stop_loss=D(str(stop)),
        take_profit=D(str(tp)), rule_name="rsi_bull_divergence", paper=True,
        status="OPEN", metadata=meta)
    AssetBotTrade.objects.filter(pk=trade.pk).update(opened_at=opened)
    trade.refresh_from_db()
    test.trade = trade
    return trade


def _bar(test, ts, o, h, low, c, tf="1h"):
    from market_data.models import PriceData
    PriceData.objects.update_or_create(
        instrument=test.inst, timeframe=tf, timestamp=ts,
        defaults=dict(open=D(str(o)), high=D(str(h)), low=D(str(low)),
                      close=D(str(c)), source="test"))


def _flat(test, start, end, px, *, w=0.0003, tf="1h", skip=()):
    from market_data.models import PriceData
    step = timedelta(hours=1 if tf == "1h" else 4)
    rows, ts = [], start
    while ts < end:
        if ts not in skip:
            rows.append(PriceData(
                instrument=test.inst, timeframe=tf, timestamp=ts,
                open=D(str(px)), high=D(str(round(px + w, 6))),
                low=D(str(round(px - w, 6))), close=D(str(px)),
                source="test"))
        ts += step
    PriceData.objects.bulk_create(rows)


def _tick_at(test, now, mark, *, care=False, paper_only=False):
    """One managed tick at a fixed instant, the mark quoted 30s before."""
    from bot_program.asset_engine.base import make_bot
    from market_data.models import LiveQuote
    LiveQuote.objects.filter(instrument=test.inst).delete()
    if mark is not None:
        LiveQuote.objects.create(instrument=test.inst, last=D(str(mark)),
                                 source="test")
        LiveQuote.objects.filter(instrument=test.inst).update(
            updated_at=now - timedelta(seconds=30))
    with patch("django.utils.timezone.now", return_value=now), \
            patch("bot_program.aragorn.is_on", return_value=care):
        bot = make_bot(test.cfg)
        n = (bot.manage_paper_only()["managed"] if paper_only
             else bot.manage_positions())
    test.trade.refresh_from_db()
    return n


class TheLevelHistoryTests(TestCase):
    """A stop or target moved inside a bar: the bar is tested against the
    loosest level in force at ANY moment of its span, on every tick it is
    re-read. The stamp of the last tick alone booked, two ticks after a
    break-even move, the bar's low from before the move against the moved
    stop: a stop-out that never happened (review cases 3, 3b, 4)."""

    def test_break_even_inside_a_bar_books_nothing_on_later_ticks(self):
        trade = _fixed(self, entry="1.30000", stop="1.29700", tp="1.31000",
                       opened=_at(2026, 9, 16, 10, 20),
                       extras={"breakeven_at_r": 1.0})
        # dips to 1.2992 early (above the stop, under the entry), then
        # rallies to 1.3035 (+1.17R): break-even moves the stop to 1.3000
        _bar(self, _at(2026, 9, 16, 11), "1.3002", "1.3035", "1.2992",
             "1.3031")
        _tick_at(self, _at(2026, 9, 16, 11, 40), "1.30320")
        self.assertEqual(trade.stop_loss, D("1.30000"))
        for minute, mark in ((45, "1.30310"), (50, "1.30310"),
                             (55, "1.30315")):
            _tick_at(self, _at(2026, 9, 16, 11, minute), mark)
            self.assertEqual(trade.status, "OPEN", f"tick {minute}")
        moves = trade.metadata["paper_replay"]["moves"]
        self.assertEqual([m[1] for m in moves], [1.297, 1.3])
        # a later bar that trades under the moved stop is a stop-out
        _bar(self, _at(2026, 9, 16, 12), "1.3030", "1.3033", "1.2998",
             "1.3010")
        _tick_at(self, _at(2026, 9, 16, 12, 40), "1.30100")
        self.assertEqual(trade.status, "CLOSED")
        self.assertIn("closed:SL", trade.reason)
        self.assertEqual(trade.closed_at, _at(2026, 9, 16, 12))
        self.assertEqual(trade.metadata["paper_exit"]["level"], 1.3)

    def test_the_short_mirrors_it(self):
        trade = _fixed(self, side="SELL", entry="1.30000", stop="1.30300",
                       tp="1.29000", opened=_at(2026, 9, 16, 10, 20),
                       extras={"breakeven_at_r": 1.0})
        _bar(self, _at(2026, 9, 16, 11), "1.2998", "1.3008", "1.2965",
             "1.2969")
        for minute, mark in ((40, "1.29680"), (45, "1.29690"),
                             (50, "1.29690"), (55, "1.29685")):
            _tick_at(self, _at(2026, 9, 16, 11, minute), mark)
            self.assertEqual(trade.status, "OPEN", f"tick {minute}")
        self.assertEqual(trade.stop_loss, D("1.30000"))

    def test_the_third_tick_in_the_bar_never_books_the_old_low(self):
        """Production order: every tick replays AND stamps; the stop is
        tightened after tick 1 (the 2026-10-08 test replayed tick 2 without
        the stamp, so it never ran this sequence)."""
        from bot_program import paper_exits
        from market_data.models import PriceData
        trade = _setup(self)
        _bars(self, {})
        b = _hour(self.now) - timedelta(hours=3)
        PriceData.objects.filter(instrument=self.inst, timeframe="1h",
                                 timestamp=b).update(low=D("1.3478"))
        t1, t2, t3 = (b + timedelta(minutes=m) for m in (10, 20, 30))
        r1 = paper_exits.replay(trade, now=t1)
        self.assertIsNone(r1["hit"])
        paper_exits.stamp(trade, r1, now=t1)
        trade.stop_loss = D("1.34800")          # trailing, after the replay
        trade.save(update_fields=["stop_loss"])
        r2 = paper_exits.replay(trade, now=t2)
        self.assertIsNone(r2["hit"])
        paper_exits.stamp(trade, r2, now=t2)
        r3 = paper_exits.replay(trade, now=t3)
        self.assertIsNone(r3["hit"])
        paper_exits.stamp(trade, r3, now=t3)
        PriceData.objects.filter(
            instrument=self.inst, timeframe="1h",
            timestamp=b + timedelta(hours=1)).update(low=D("1.3479"))
        later = paper_exits.replay(trade,
                                   now=b + timedelta(hours=1, minutes=5))
        self.assertEqual(later["hit"]["reason"], "SL")
        self.assertEqual(later["hit"]["level"], 1.348)
        self.assertEqual(later["hit"]["bar_ts"], b + timedelta(hours=1))

    def test_the_cares_soft_stop_is_a_level_with_a_history_too(self):
        from bot_program import paper_exits
        from market_data.models import PriceData
        trade = _setup(self)
        _bars(self, {})                 # flat bars, lows at 1.3485
        b = _hour(self.now) - timedelta(hours=3)
        t1, t2, t3 = (b + timedelta(minutes=m) for m in (10, 20, 30))
        r1 = paper_exits.replay(trade, now=t1, care_on=True)
        paper_exits.stamp(trade, r1, now=t1)
        trade.metadata = {**trade.metadata,
                          "care": {"soft_stop": 1.3487}}   # the care locks
        trade.save(update_fields=["metadata"])
        for t in (t2, t3):
            r = paper_exits.replay(trade, now=t, care_on=True)
            self.assertIsNone(r["hit"])
            self.assertEqual(r["stop"], 1.3487)
            paper_exits.stamp(trade, r, now=t)
        PriceData.objects.filter(
            instrument=self.inst, timeframe="1h",
            timestamp=b + timedelta(hours=1)).update(low=D("1.3486"))
        later = paper_exits.replay(
            trade, now=b + timedelta(hours=1, minutes=5), care_on=True)
        self.assertEqual(later["hit"]["reason"], "SL")
        self.assertEqual(later["hit"]["level"], 1.3487)  # the soft stop
        self.assertEqual(later["hit"]["bar_ts"], b + timedelta(hours=1))

    def test_a_target_tightened_inside_a_bar_books_no_fake_win(self):
        from bot_program import paper_exits
        trade = _setup(self)
        _bars(self, {})                 # flat bars, highs at 1.3495
        b = _hour(self.now) - timedelta(hours=3)
        t1, t2, t3 = (b + timedelta(minutes=m) for m in (10, 20, 30))
        r1 = paper_exits.replay(trade, now=t1)
        paper_exits.stamp(trade, r1, now=t1)
        trade.take_profit = D("1.34940")      # tightened under the high
        trade.save(update_fields=["take_profit"])
        for t in (t2, t3):
            r = paper_exits.replay(trade, now=t)
            self.assertIsNone(r["hit"])
            paper_exits.stamp(trade, r, now=t)
        later = paper_exits.replay(trade,
                                   now=b + timedelta(hours=1, minutes=5))
        self.assertEqual(later["hit"]["reason"], "TP")
        self.assertEqual(later["hit"]["bar_ts"], b + timedelta(hours=1))

    def test_the_history_is_pruned_behind_the_cursor(self):
        from bot_program import paper_exits
        trade = _setup(self)
        _bars(self, {})
        stop = 1.3469
        for k, at in enumerate(_hour(self.now) - timedelta(hours=40 - 2 * i)
                               for i in range(15)):
            r = paper_exits.replay(trade, now=at)
            paper_exits.stamp(trade, r, now=at)
            stop += 0.00001
            trade.stop_loss = D(str(round(stop, 6)))
            trade.save(update_fields=["stop_loss"])
        moves = trade.metadata["paper_replay"]["moves"]
        cursor = paper_exits._parse(
            trade.metadata["paper_replay"]["bars_through"])
        self.assertLess(len(moves), 6)
        self.assertLessEqual(paper_exits._parse(moves[0][0]),
                             cursor - paper_exits.HISTORY_REACH)


class TheTimeStopFromTheBarsTests(TestCase):
    """A ceiling that fell due while nothing managed the row books from the
    first bar at or past it (review case 9: -13.38R at the far mark of the
    first tick, where the clock exit would have closed near +0.1R)."""

    def _case(self):
        trade = _fixed(self, entry="1.30000", stop="1.29700", tp="1.33000",
                       opened=_at(2026, 9, 16, 9, 20), max_hold=48)
        _flat(self, _at(2026, 9, 16, 10), _at(2026, 9, 28), 1.3005)
        _flat(self, _at(2026, 9, 28), _at(2026, 10, 5, 11), 1.2600)
        return trade

    def test_weeks_after_the_ceiling_it_books_the_ceilings_bar(self):
        trade = self._case()
        _tick_at(self, _at(2026, 10, 5, 10, 5), "1.26000")
        self.assertEqual(trade.status, "CLOSED")
        self.assertIn("closed:TIME", trade.reason)
        self.assertEqual(trade.outcome, "time_stop")
        self.assertEqual(trade.closed_at, _at(2026, 9, 18, 10))
        self.assertEqual(trade.metadata["paper_exit"]["reason"], "TIME")
        self.assertGreater(trade.realized_r, 0.0)
        self.assertLess(trade.realized_r, 0.3)

    def test_a_ceiling_a_managed_tick_saw_is_the_marks_as_before(self):
        from bot_program import paper_exits
        trade = self._case()
        ceiling = _at(2026, 9, 18, 9, 20)
        trade.metadata = {**trade.metadata, "paper_replay": {
            "tick_at": (ceiling + timedelta(minutes=5)).isoformat(),
            "bars_through": _at(2026, 9, 18, 9).isoformat(),
            "moves": [[trade.opened_at.isoformat(), 1.297, 1.33]]}}
        trade.save(update_fields=["metadata"])
        out = paper_exits.replay(trade, now=_at(2026, 9, 18, 11, 5),
                                 ceiling=ceiling)
        self.assertIsNone(out["hit"])

    def test_a_ceiling_over_the_weekend_books_the_reopens_bar(self):
        """Gate on: the bars a poller stamped while forex was shut are no
        trade; the first bar of the Sunday 21:00 reopen books, at the end
        of its settling quarter hour."""
        from bot_program import paper_exits
        from bot_program.engine import paper_trader
        trade = _fixed(self, entry="1.30000", stop="1.29700", tp="1.33000",
                       opened=_at(2026, 9, 24, 6, 20))
        _flat(self, _at(2026, 9, 24, 5), _at(2026, 9, 27, 21), 1.3005)
        _bar(self, _at(2026, 9, 27, 21), "1.2990", "1.2993", "1.2985",
             "1.2988")
        _flat(self, _at(2026, 9, 27, 22), _at(2026, 9, 30, 11), 1.2600)
        with patch.object(paper_trader, "MARKET_HOURS_GATE", True):
            out = paper_exits.replay(trade, now=_at(2026, 9, 30, 10, 5),
                                     ceiling=_at(2026, 9, 26, 6, 20))
        hit = out["hit"]
        self.assertEqual(hit["reason"], "TIME")
        self.assertEqual(hit["bar_ts"], _at(2026, 9, 27, 21))
        self.assertEqual(hit["level"], 1.299)
        self.assertEqual(hit["at"], _at(2026, 9, 27, 21, 15))


class TheBarSanityTests(TestCase):
    """A stored bar is not trusted because it is stored (review: a
    near-zero print booked about -440R, a lone spike a stop no market
    traded, spot bars against a futures-priced row a fake stop)."""

    def test_a_near_zero_print_books_nothing(self):
        trade = _setup(self)
        _bars(self, {20: (D("0.0100"), D("1.3480"), D("0.0050"),
                          D("1.3478"))})
        _quote(self, D("1.34900"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_a_close_a_feed_rounded_past_its_low_still_counts(self):
        """A close under the bar's own low traded: the range is widened to
        hold it, never the bar dropped."""
        trade = _setup(self)
        bars = _bars(self, _after({20: (D("1.3478"), D("1.3480"),
                                        D("1.3470"), D("1.3465"))},
                                  19, 0, D("1.3475")))
        _quote(self, D("1.34750"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.closed_at, bars[20].timestamp)

    def test_a_lone_spike_low_books_nothing(self):
        trade = _setup(self)
        _bars(self, {20: (D("1.3490"), D("1.3495"), D("1.1000"),
                          D("1.3490"))})
        _quote(self, D("1.34900"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_a_move_that_holds_is_a_market_and_books_once_it_has_held(self):
        from bot_program import paper_exits
        trade = _fixed(self, symbol="TSTK", cls="stock", entry="100",
                       stop="95", tp="120", opened=_at(2026, 9, 21, 10, 20))
        _flat(self, _at(2026, 9, 21, 11), _at(2026, 9, 21, 21), 100.2,
              w=0.3)
        _bar(self, _at(2026, 9, 21, 21), "60", "60.4", "59.6", "60")
        _bar(self, _at(2026, 9, 21, 22), "60", "60.4", "59.6", "60.1")
        two = paper_exits.replay(trade, now=_at(2026, 9, 21, 22, 30))
        self.assertIsNone(two["hit"])         # not yet held: it waits
        self.assertEqual(two["bars_through"],
                         _at(2026, 9, 21, 21).isoformat())
        paper_exits.stamp(trade, two, now=_at(2026, 9, 21, 22, 30))
        _bar(self, _at(2026, 9, 21, 23), "60.1", "60.5", "59.7", "60")
        held = paper_exits.replay(trade, now=_at(2026, 9, 21, 23, 30))
        self.assertEqual(held["hit"]["reason"], "SL")
        self.assertTrue(held["hit"]["gapped"])
        self.assertEqual(held["hit"]["level"], 60.0)
        self.assertEqual(held["hit"]["bar_ts"], _at(2026, 9, 21, 21))

    def test_an_open_through_the_stop_nothing_confirms_books_the_stop(self):
        trade = _setup(self)
        _bars(self, {20: (D("1.3400"), D("1.3495"), D("1.3400"),
                          D("1.3490"))})
        _quote(self, D("1.34900"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        rec = trade.metadata["paper_exit"]
        self.assertFalse(rec["gapped"])
        self.assertTrue(rec["unconfirmed_gap"])
        self.assertEqual(D(str(rec["level"])), STOP)
        self.assertGreater(trade.realized_r, -1.1)

    def test_a_gap_the_bar_traded_near_books_its_open(self):
        """Close within the class's one-print bar of the open: the market
        was there (a stock's open gap that recovered inside the hour)."""
        trade = _setup(self)
        _bars(self, _after({20: (D("1.3440"), D("1.3480"), D("1.3436"),
                                 D("1.3478"))}, 19, 0, D("1.3490")))
        _quote(self, D("1.34900"))
        _tick(self)
        trade.refresh_from_db()
        self.assertTrue(trade.metadata["paper_exit"]["gapped"])
        self.assertLessEqual(trade.exit_price, D("1.3440"))

    def test_with_no_next_bar_an_unconfirmed_gap_waits_for_its_open(self):
        from bot_program import paper_exits
        from market_data.models import PriceData
        trade = _setup(self)
        bars = _bars(self, {1: (D("1.3400"), D("1.3495"), D("1.3400"),
                                D("1.3490"))})
        bars[0].delete()                       # no bar after the gap yet
        now = _hour(self.now) + timedelta(minutes=10)
        out = paper_exits.replay(trade, now=now)
        self.assertIsNone(out["hit"])
        self.assertEqual(out["bars_through"], bars[1].timestamp.isoformat())
        paper_exits.stamp(trade, out, now=now)
        PriceData.objects.create(
            instrument=self.inst, timeframe="1h",
            timestamp=_hour(self.now), open=D("1.3488"), high=D("1.3492"),
            low=D("1.3485"), close=D("1.3490"), source="test")
        out = paper_exits.replay(trade, now=now + timedelta(minutes=5))
        self.assertEqual(out["hit"]["level"], 1.3469)
        self.assertTrue(out["hit"]["unconfirmed_gap"])

    def test_bars_of_another_instrument_are_not_replayed(self):
        """A gold row priced off Yahoo's FUTURES (PaperTrader's LiveQuote)
        and barred off eToro's spot CFD: about $25 apart. The spot bars
        cross the futures stop every hour; the row is managed on its own
        mark, as before."""
        trade = _fixed(self, symbol="XAUTEST", cls="commodity",
                       entry="2680", stop="2660", tp="2720",
                       opened=_at(2026, 9, 16, 10, 20))
        _flat(self, _at(2026, 9, 16, 10), _at(2026, 9, 16, 15), 2655.0,
              w=2.0)
        _tick_at(self, _at(2026, 9, 16, 14, 10), "2678")
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(trade.metadata["paper_replay"]["basis"], "off")

    def test_bars_that_hold_the_entry_are_the_rows_own(self):
        from bot_program import paper_exits
        trade = _setup(self)
        _bars(self, {})
        self.assertEqual(paper_exits._basis(trade), "ok")


class TheTouchPaysTheCostTests(TestCase):
    def test_a_stop_touched_at_the_bars_low_pays_the_half_cost(self):
        """The clamp to the bar's worst price waived the whole modelled
        half cost on every touch; a deep cross paid it."""
        from bot_program.asset_engine.risk_levels import (
            round_trip_cost_fraction)
        trade = _setup(self)
        spec = {20: (D("1.3478"), D("1.3480"), STOP, D("1.3475"))}
        _bars(self, _after(spec, 19, 0, D("1.3475")))
        _quote(self, D("1.34750"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        half = round_trip_cost_fraction(self.cfg, "GBPUSD") / 2
        self.assertLess(trade.exit_price, STOP)
        self.assertAlmostEqual(float(trade.exit_price),
                               float(STOP) * (1 - half), places=6)


class TheMarketClockTests(TestCase):
    """The clock's branches run with the gate ON (the suite runs it off)."""

    def setUp(self):
        self.trade = _setup(self)

    def _book(self, ts, hours=1, trade=None):
        from bot_program import paper_exits
        from bot_program.engine import paper_trader
        bar = {"tf": "1h" if hours == 1 else "4h", "ts": ts,
               "end": ts + timedelta(hours=hours)}
        with patch.object(paper_trader, "MARKET_HOURS_GATE", True):
            return paper_exits._booking_time(trade or self.trade, bar)

    def test_a_bar_shut_for_its_whole_span_is_no_trade(self):
        self.assertIsNone(self._book(_at(2026, 9, 26, 12)))

    def test_the_reopens_first_bar_books_after_its_settling_quarter(self):
        self.assertEqual(self._book(_at(2026, 9, 27, 21)),
                         _at(2026, 9, 27, 21, 15))

    def test_a_four_hour_bar_holding_the_reopen_books_at_it(self):
        self.assertEqual(self._book(_at(2026, 9, 27, 20), hours=4),
                         _at(2026, 9, 27, 21, 15))

    def test_an_hour_stamped_stock_bar_holding_the_open_books_at_it(self):
        trade = _fixed(self, symbol="AAPL", cls="stock", entry="100",
                       stop="98", tp="110", opened=_at(2026, 9, 22, 14, 20),
                       exchange="NASDAQ")
        self.assertEqual(self._book(_at(2026, 9, 23, 13), trade=trade),
                         _at(2026, 9, 23, 13, 45))

    def test_the_us_open_gap_in_the_13h_bar_is_booked(self):
        """Review case 11: the Wednesday 13:00 bar gapped at the 13:30 open
        and recovered by 14:00; it was skipped as shut and the cursor
        passed it, flattering the rule by 0.75R."""
        from bot_program import paper_exits
        from bot_program.engine import paper_trader
        trade = _fixed(self, symbol="AAPL", cls="stock", entry="100",
                       stop="98", tp="110", opened=_at(2026, 9, 22, 14, 20),
                       exchange="NASDAQ")
        _bar(self, _at(2026, 9, 22, 15), "100", "100.3", "99.8", "100.1")
        _flat(self, _at(2026, 9, 22, 16), _at(2026, 9, 22, 20), 100.2,
              w=0.3)
        _bar(self, _at(2026, 9, 23, 13), "96.5", "99.1", "96.3", "99.0")
        _bar(self, _at(2026, 9, 23, 14), "99.0", "99.4", "98.6", "99.2")
        with patch.object(paper_trader, "MARKET_HOURS_GATE", True):
            out = paper_exits.replay(trade, now=_at(2026, 9, 23, 15, 5))
        hit = out["hit"]
        self.assertEqual(hit["reason"], "SL")
        self.assertTrue(hit["gapped"])
        self.assertEqual(hit["level"], 96.5)
        self.assertEqual(hit["bar_ts"], _at(2026, 9, 23, 13))
        self.assertEqual(hit["at"], _at(2026, 9, 23, 13, 45))


class AHandMovedTargetTests(TestCase):
    """An unstamped row whose target was moved by hand (adjust_levels'
    level_edits) is replayed from the edit, never from its opening against
    a target that was not there."""

    def _row(self):
        edit_at = _hour(timezone.now()) - timedelta(hours=10, minutes=30)
        return _setup(self, metadata={"level_edits": [
            {"at": edit_at.isoformat(), "by": "op", "stop": None,
             "target": "1.36000", "widened": False, "broker": "bot"}]})

    def test_a_bar_before_the_edit_never_books_the_new_target(self):
        trade = self._row()
        _bars(self, {20: (D("1.3500"), D("1.3610"), D("1.3495"),
                          D("1.3500"))})
        _quote(self, D("1.34900"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")

    def test_a_bar_after_the_edit_does(self):
        trade = self._row()
        bars = _bars(self, {5: (D("1.3500"), D("1.3610"), D("1.3495"),
                                D("1.3500"))})
        _quote(self, D("1.34900"))
        _tick(self)
        trade.refresh_from_db()
        self.assertIn("closed:TP", trade.reason)
        self.assertEqual(trade.closed_at, bars[5].timestamp)


class AHoleInTheHourlyBarsTests(TestCase):
    """Review case 13: the 14:00 1h bar is missing; the 4h bar holding the
    hour crossed the stop, and the 1h bar written later did too. Neither
    was ever read."""

    def _row(self):
        trade = _fixed(self, entry="1.30000", stop="1.29700", tp="1.31000",
                       opened=_at(2026, 9, 16, 10, 20))
        _flat(self, _at(2026, 9, 16, 11), _at(2026, 9, 16, 18), 1.3002,
              skip=(_at(2026, 9, 16, 14),))
        return trade

    def test_the_four_hour_bar_holding_the_hole_is_read(self):
        from bot_program import paper_exits
        trade = self._row()
        _bar(self, _at(2026, 9, 16, 12), "1.3002", "1.3006", "1.2960",
             "1.3001", tf="4h")
        out = paper_exits.replay(trade, now=_at(2026, 9, 16, 18, 5))
        self.assertEqual(out["hit"]["reason"], "SL")
        self.assertEqual(out["hit"]["tf"], "4h")

    def test_a_late_hourly_bar_is_still_read(self):
        from bot_program import paper_exits
        trade = self._row()
        first = paper_exits.replay(trade, now=_at(2026, 9, 16, 18, 5))
        self.assertIsNone(first["hit"])
        self.assertEqual(first["bars_through"],
                         _at(2026, 9, 16, 14).isoformat())
        paper_exits.stamp(trade, first, now=_at(2026, 9, 16, 18, 5))
        _bar(self, _at(2026, 9, 16, 14), "1.3002", "1.3006", "1.2960",
             "1.3001")
        out = paper_exits.replay(trade, now=_at(2026, 9, 16, 18, 15))
        self.assertEqual(out["hit"]["bar_ts"], _at(2026, 9, 16, 14))
        self.assertEqual(out["hit"]["tf"], "1h")

    def test_with_every_hour_covered_the_four_hour_bar_stands_aside(self):
        from market_data.models import PriceData
        trade = _setup(self)
        hourly = _bars(self, {5: (D("1.3478"), D("1.3480"), D("1.3465"),
                                  D("1.3467"))})
        four = hourly[5].timestamp - timedelta(hours=2)
        PriceData.objects.create(instrument=self.inst, timeframe="4h",
                                 timestamp=four, open=D("1.3490"),
                                 high=D("1.3495"), low=D("1.3465"),
                                 close=D("1.3470"), source="test4h")
        _quote(self, D("1.34900"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.metadata["paper_exit"]["tf"], "1h")
        self.assertEqual(trade.closed_at, hourly[5].timestamp)


class TheFormingBarTests(TestCase):
    def test_a_crossing_later_in_the_bar_a_tick_saw_forming_is_booked(self):
        from bot_program import paper_exits
        from market_data.models import PriceData
        trade = _setup(self)
        _bars(self, {})
        b = _hour(self.now) - timedelta(hours=3)
        t1 = b + timedelta(minutes=10)
        r1 = paper_exits.replay(trade, now=t1)
        self.assertIsNone(r1["hit"])
        paper_exits.stamp(trade, r1, now=t1)
        PriceData.objects.filter(instrument=self.inst, timeframe="1h",
                                 timestamp=b).update(low=D("1.3460"))
        r2 = paper_exits.replay(trade, now=b + timedelta(minutes=40))
        self.assertEqual(r2["hit"]["bar_ts"], b)

    def test_the_bar_that_holds_the_fill_is_never_tested(self):
        from market_data.models import PriceData
        trade = _setup(self)
        _bars(self, {})
        PriceData.objects.create(
            instrument=self.inst, timeframe="1h",
            timestamp=_hour(self.opened), open=D("1.3499"),
            high=D("1.3502"), low=D("1.3460"), close=D("1.3495"),
            source="test")
        _quote(self, D("1.34900"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")


class AnUnmanagedStretchTests(TestCase):
    """A paper row nothing ran for a day or more, whose bars cannot cover
    the stretch, is closed ungraded when its mark crosses: the -8.12R of the
    far-mark paper row was such a number, and the ladder would read it as evidence."""

    def _stopped(self, *, stop="1.34950", bars=False):
        from bot_program.asset_engine import disarm
        trade = _setup(self, stop=D(stop), initial=STOP,
                       opened_hours=24 * 21)
        if bars:
            _bars(self, {})
        disarm.disable_config(self.cfg, by=disarm.BY_BOT_OFF, why="by hand",
                              who="op",
                              now=timezone.now() - timedelta(days=20))
        self.cfg.refresh_from_db()
        _quote(self, D("1.32549"))
        return trade

    def _paper_only(self):
        from bot_program.asset_engine.base import make_bot
        with patch("bot_program.aragorn.is_on", return_value=False):
            make_bot(self.cfg).manage_paper_only()

    def test_a_stopped_configs_row_with_an_unknown_history_closes_ungraded(
            self):
        trade = self._stopped()
        self._paper_only()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.outcome, "stopped_out")
        self.assertIsNone(trade.realized_r)
        flag = trade.metadata["unmanaged_exit"]
        self.assertIn("stop moved", flag["why"])
        self.assertGreater(flag["hours"], 24 * 19)

    def test_with_no_bars_too(self):
        trade = self._stopped(stop=str(STOP))
        self._paper_only()
        trade.refresh_from_db()
        self.assertIsNone(trade.realized_r)
        self.assertEqual(trade.metadata["unmanaged_exit"]["why"], "no bars")

    def test_bars_that_cover_the_stretch_book_it_graded(self):
        """The far-mark shape on a stopped config: the paper-only pass books at
        the stop, at the crossing bar's time, graded."""
        from bot_program.asset_engine import disarm
        trade = _setup(self)
        spec = {20: (D("1.3478"), D("1.3480"), D("1.3465"), D("1.3467"))}
        bars = _bars(self, _after(spec, 19, 0, D("1.3260")))
        _quote(self, D("1.32549"))
        disarm.disable_config(self.cfg, by=disarm.BY_BOT_OFF, why="by hand",
                              who="op")
        self.cfg.refresh_from_db()
        self._paper_only()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertNotIn("unmanaged_exit", trade.metadata)
        self.assertGreater(trade.realized_r, -1.2)
        self.assertEqual(trade.closed_at, bars[20].timestamp)

    def test_a_running_configs_unstamped_row_is_graded_as_before(self):
        trade = _setup(self, stop=D("1.34950"), initial=STOP,
                       opened_hours=24 * 21)
        _quote(self, D("1.32549"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertIsNotNone(trade.realized_r)
        self.assertNotIn("unmanaged_exit", trade.metadata)

    def test_a_stamped_row_three_days_unmanaged_closes_ungraded(self):
        trade = _setup(self, opened_hours=24 * 5)
        then = (timezone.now() - timedelta(days=3)).isoformat()
        trade.metadata = {**trade.metadata, "paper_replay": {
            "tick_at": then, "seen_at": then, "bars_through": None,
            "moves": [[self.opened.isoformat(), float(STOP), float(TP)]]}}
        trade.save(update_fields=["metadata"])
        _quote(self, D("1.32549"))
        _tick(self)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertIsNone(trade.realized_r)

    def test_a_row_a_shut_market_tick_saw_is_not_unmanaged(self):
        trade = _setup(self, opened_hours=24 * 5)
        then = (timezone.now() - timedelta(days=3)).isoformat()
        seen = (timezone.now() - timedelta(hours=1)).isoformat()
        trade.metadata = {**trade.metadata, "paper_replay": {
            "tick_at": then, "seen_at": seen, "bars_through": None,
            "moves": [[self.opened.isoformat(), float(STOP), float(TP)]]}}
        trade.save(update_fields=["metadata"])
        _quote(self, D("1.32549"))
        _tick(self)
        trade.refresh_from_db()
        self.assertIsNotNone(trade.realized_r)

    def test_the_shut_market_wait_refreshes_seen_at(self):
        from bot_program.engine import paper_trader
        trade = _fixed(self, entry="1.30000", stop="1.29700", tp="1.31000",
                       opened=_at(2026, 9, 24, 10, 20))
        friday = _at(2026, 9, 25, 20, 55).isoformat()
        trade.metadata = {**trade.metadata, "paper_replay": {
            "tick_at": friday, "seen_at": friday, "bars_through": None,
            "moves": [[trade.opened_at.isoformat(), 1.297, 1.31]]}}
        trade.save(update_fields=["metadata"])
        saturday = _at(2026, 9, 26, 12)
        with patch.object(paper_trader, "MARKET_HOURS_GATE", True):
            _tick_at(self, saturday, "1.30000")
        stamp = trade.metadata["paper_replay"]
        self.assertEqual(stamp["seen_at"], saturday.isoformat())
        self.assertEqual(stamp["tick_at"], friday)


class TheStampIsWrittenUnderTheRowsLockTests(TestCase):
    def test_a_write_since_the_tick_loaded_the_row_is_kept(self):
        """The thesis check's ADJUST lands on the row while the tick holds
        an older copy: the stamp no longer erases it."""
        from bot_program import paper_exits
        from bot_program.asset_models import AssetBotTrade
        trade = _setup(self)
        _bars(self, {})
        stale = AssetBotTrade.objects.get(pk=trade.pk)
        fresh = AssetBotTrade.objects.get(pk=trade.pk)
        fresh.metadata = {**fresh.metadata,
                          "thesis": {"verdict": "adjust", "stop": 1.348}}
        fresh.save(update_fields=["metadata"])
        now = timezone.now()
        paper_exits.stamp(stale, paper_exits.replay(stale, now=now), now=now)
        trade.refresh_from_db()
        self.assertEqual(trade.metadata["thesis"]["verdict"], "adjust")
        self.assertIn("paper_replay", trade.metadata)
        self.assertEqual(stale.metadata["thesis"]["verdict"], "adjust")
