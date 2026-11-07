"""THE FEED'S STORES AND THEIR WRITE RULES, W1-W7 ON BOTH IMPLEMENTATIONS
(the eToro feed spec, F1, §5.2-§5.3; 2026-11-07).

market_data.venue_store keeps eToro's quotes per channel — vq:ws:{iid} for
the stream, vq:rest:{iid} for the feed's REST reads — and every write is a
compare-and-set by eToro's own Date: a Redis Lua script in production and
an in-memory twin with the same rules for tests and replay. The same table
of frames runs through both and must leave both stores byte for byte
alike. What is pinned:

  W1  a missing side, a value <= 0, a non-finite, unparsable or absurd
      value, a crossed quote, a spread above 10% of the mid, a Date more
      than a minute ahead of the frame's arrival: refused and counted,
      nothing stored;
  W2  a newer Date replaces, confirmed at its arrival;
  W3  the same Date and the same sides: a confirmation only (a REST answer
      confirms at its arrival less C_rest);
  W4  the same Date with other sides: kept as stored, counted — the same
      rate id included: a rate id never confirms other sides;
  W5  an older Date never replaces, whatever its rate id; an older
      snapshot confirms nothing;
  W6  a price-less frame is liveness only;
  W7  a REST answer without a Date is kept beside the record, for display;
  and "0", eToro's no-price word, never replaces a priced record: the
  absence is noted beside it and never refreshes its confirmation.

Also: the rate id orders two prints of one Date only once M2 proves it;
each channel writes only its own frames; a record expires four days after
it was last created, replaced or confirmed, never refreshed by an older
frame; sides are kept as canonical text; the REST record keeps the
answer's conversion; the read-time choice (current), the key names, the
Lua script's refusal of any key outside vq:*, and the read-only view of
the engine's rates cache (etoro_rates:r:*, both worlds), which nothing
here ever writes.

The Redis half runs where a redis-server binary is installed (it is
started on a private unix socket in a temporary folder and stopped after).
CI installs one (.github/workflows/tests.yml); there a missing binary
FAILS the Redis half instead of skipping it, so the Lua script can never
drift from the twin unseen. Run with:
    python manage.py test tests.feed.test_venue_store_rules
"""
import os
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest import mock, skipUnless

from django.test import SimpleTestCase

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=dt_tz.utc)
REDIS_SERVER = shutil.which("redis-server")
#: On CI the Redis half must run: a missing binary is a failure there.
ON_CI = os.environ.get("GITHUB_ACTIONS") == "true"
RUN_REDIS = bool(REDIS_SERVER) or ON_CI


def _vs():
    from market_data import venue_store
    return venue_store


def _at(seconds):
    return NOW + timedelta(seconds=seconds)


def _ms(seconds):
    return str(_vs()._ms(_at(seconds)))


def _frame(kind, bid="1.1000", ask="1.1002", *, vt=0, arrival=1,
           rate_id="", **kw):
    """A frame of `kind` whose eToro Date is NOW + vt s, arriving at
    NOW + arrival s."""
    vs = _vs()
    return vs.frame(kind=kind, bid=bid, ask=ask,
                    vt=None if vt is None else _at(vt), rate_id=rate_id,
                    arrival=_at(arrival), **kw)


class _Rules:
    """The table, run against `self.store` (set by the subclass through
    `self.make(**kw)`)."""

    IID = 7

    def _w(self, channel, fr, store=None):
        return (store or self.store).write(self.IID, channel, fr)

    def test_w1_refusals_are_counted_and_store_nothing(self):
        vs = _vs()
        for reason, (bid, ask) in {"missing_side": ("1.1000", None),
                                   "not_positive": ("-1", "1.1002"),
                                   "not_finite": ("NaN", "1.1002"),
                                   "unparsed": ("x", "1.1002"),
                                   "crossed": ("1.1004", "1.1002"),
                                   "wide_spread": ("1", "2"),
                                   "out_of_range": ("9e999999",
                                                    "9e999999")}.items():
            with self.subTest(reason=reason):
                fr = _frame("push", bid, ask)
                self.assertEqual(fr.outcome_hint, vs.REFUSED)
                self.assertEqual(fr.reason, reason)
                self.assertEqual(self._w("ws", fr), vs.REFUSED)
                self.assertIsNone(self.store.record(self.IID, "ws"))
        self.assertEqual(self.store.counts["refused"], 7)
        self.assertEqual(self.store.counts["refused:crossed"], 1)

    def test_w1_absurd_or_loose_text_is_refused_never_raised(self):
        """2026-11-07, review: "9e999999" overflowed out of frame(); "1e400"
        and "1_000" were taken as prices."""
        vs = _vs()
        for bid, ask, reason in (("9e999999", "9e999999", "out_of_range"),
                                 ("1e400", "1e400", "out_of_range"),
                                 ("1e-400", "1e-400", "out_of_range"),
                                 ("1_000", "1_001", "unparsed"),
                                 ("0x1", "1.1002", "unparsed"),
                                 ("Infinity", "1.1002", "not_finite")):
            with self.subTest(bid=bid):
                fr = _frame("push", bid, ask)
                self.assertEqual((fr.outcome_hint, fr.reason),
                                 (vs.REFUSED, reason))
                self.assertEqual(self._w("ws", fr), vs.REFUSED)
        self.assertIsNone(self.store.record(self.IID, "ws"))

    def test_w1_a_date_far_ahead_of_its_arrival_is_refused(self):
        vs = _vs()
        fr = _frame("push", vt=62, arrival=1)
        self.assertEqual((fr.outcome_hint, fr.reason),
                         (vs.REFUSED, "future_date"))
        self.assertEqual(self._w("ws", fr), vs.REFUSED)
        self.assertEqual(self.store.counts["refused:future_date"], 1)
        near = _frame("push", vt=61, arrival=1)       # a minute: taken
        self.assertIsNone(near.outcome_hint)

    def test_one_frame_dated_a_year_ahead_never_freezes_the_store(self):
        """The review's scenario (2026-11-07): one corrupt push dated a
        year ahead was stored as "new", and every real print after it was
        "older" for a year. Now it is refused, and real prints go on."""
        vs = _vs()
        self._w("ws", _frame("push", vt=0, arrival=1))
        self.assertEqual(self._w("ws", _frame("push", "1.1001", "1.1003",
                                              vt=365 * 86400, arrival=2)),
                         vs.REFUSED)
        for i in range(3, 8):
            self.assertEqual(self._w("ws", _frame("push", "1.1010",
                                                  f"1.10{10 + i}", vt=i,
                                                  arrival=i)), vs.NEW)
        self.assertEqual(self.store.record(self.IID, "ws").vt, _at(7))

    def test_w2_newer_replaces_confirmed_at_arrival(self):
        vs = _vs()
        self.assertEqual(self._w("ws", _frame("push", vt=0, arrival=1)),
                         vs.NEW)
        self.assertEqual(self._w("ws", _frame("push", "1.1001", "1.1003",
                                              vt=2, arrival=3)), vs.NEW)
        q = self.store.record(self.IID, "ws")
        self.assertEqual((q.bid, q.ask), (Decimal("1.1001"),
                                          Decimal("1.1003")))
        self.assertEqual(q.vt, _at(2))
        self.assertEqual(q.confirmed_at, _at(3))
        self.assertEqual(q.channel, "ws")

    def test_w3_same_is_a_confirmation_only(self):
        vs = _vs()
        self._w("ws", _frame("push", vt=0, arrival=1, rate_id="5"))
        self.assertEqual(self._w("ws", _frame("push", vt=0, arrival=5)),
                         vs.SAME)
        q = self.store.record(self.IID, "ws")
        self.assertEqual(q.confirmed_at, _at(5))
        self.assertEqual(q.arrival, _at(1), "the record itself is kept")

    def test_a_rate_id_never_overrides_the_date_or_the_sides(self):
        """2026-11-07, review: the same rate id read "same" whatever the
        sides and the Date, confirming a contradicted price. Until M2
        proves rate ids (RATE_ID_PROVEN), the Date and the sides decide."""
        vs = _vs()
        self._w("ws", _frame("push", vt=10, arrival=11, rate_id="5"))
        # the same rate id, other sides, the same Date: a conflict
        self.assertEqual(self._w("ws", _frame("push", "1.2000", "1.2002",
                                              vt=10, arrival=20,
                                              rate_id="5")), vs.CONFLICT)
        q = self.store.record(self.IID, "ws")
        self.assertEqual((q.bid, q.confirmed_at),
                         (Decimal("1.1000"), _at(11)))
        # the same rate id, an older Date: older, confirming nothing
        self.assertEqual(self._w("ws", _frame("snapshot", "1.0500",
                                              "1.0502", vt=1, arrival=30,
                                              rate_id="5")),
                         vs.SNAPSHOT_OLDER)
        self.assertEqual(self.store.record(self.IID, "ws").confirmed_at,
                         _at(11))
        # the same rate id, a newer Date and other sides: it replaces
        self.assertEqual(self._w("ws", _frame("push", "1.3000", "1.3002",
                                              vt=50, arrival=51,
                                              rate_id="5")), vs.NEW)
        q = self.store.record(self.IID, "ws")
        self.assertEqual((q.bid, q.vt), (Decimal("1.3000"), _at(50)))

    def test_once_proven_the_rate_id_orders_two_prints_of_one_date(self):
        vs = _vs()
        store = self.make(rate_id_proven=True)
        self._w("ws", _frame("push", vt=10, arrival=11, rate_id="99"),
                store)
        # a higher id at the same Date replaces, other sides or not
        self.assertEqual(self._w("ws", _frame("push", "1.1001", "1.1003",
                                              vt=10, arrival=12,
                                              rate_id="100"), store), vs.NEW)
        # a lower one is older (exactly: "99" < "100", not as text)
        self.assertEqual(self._w("ws", _frame("push", "1.1005", "1.1007",
                                              vt=10, arrival=13,
                                              rate_id="99"), store), vs.OLDER)
        # the same id with other sides: a conflict, never a confirmation
        self.assertEqual(self._w("ws", _frame("push", "1.1009", "1.1011",
                                              vt=10, arrival=14,
                                              rate_id="100"), store),
                         vs.CONFLICT)
        # the same id and sides: the same print
        self.assertEqual(self._w("ws", _frame("push", "1.1001", "1.1003",
                                              vt=10, arrival=15,
                                              rate_id="100"), store), vs.SAME)
        # a rate id never beats a Date
        self.assertEqual(self._w("ws", _frame("push", "1.2", "1.2002",
                                              vt=9, arrival=16,
                                              rate_id="999"), store),
                         vs.OLDER)
        q = store.record(self.IID, "ws")
        self.assertEqual((q.bid, q.rate_id, q.confirmed_at),
                         (Decimal("1.1001"), "100", _at(15)))

    def test_w3_a_rest_answer_confirms_at_arrival_less_c_rest(self):
        vs = _vs()
        self._w("rest", _frame("rest", vt=0, arrival=1, c_rest_s=60))
        self.assertEqual(self.store.record(self.IID, "rest").confirmed_at,
                         _at(1 - 60))
        self.assertEqual(self._w("rest", _frame("rest", vt=0, arrival=100,
                                                c_rest_s=60)), vs.SAME)
        self.assertEqual(self.store.record(self.IID, "rest").confirmed_at,
                         _at(40))
        # an earlier confirmation never moves it back
        self._w("rest", _frame("rest", vt=0, arrival=50, c_rest_s=60))
        self.assertEqual(self.store.record(self.IID, "rest").confirmed_at,
                         _at(40))

    def test_w4_a_conflict_keeps_the_stored_sides_and_is_counted(self):
        vs = _vs()
        self._w("ws", _frame("push", vt=0, arrival=1))
        self.assertEqual(self._w("ws", _frame("push", "1.1001", "1.1003",
                                              vt=0, arrival=2)),
                         vs.CONFLICT)
        q = self.store.record(self.IID, "ws")
        self.assertEqual(q.bid, Decimal("1.1000"))
        self.assertEqual(q.confirmed_at, _at(1), "a conflict confirms nothing")
        self.assertEqual(self.store.counts["same_ts_conflict"], 1)

    def test_sides_are_one_number_whatever_their_text(self):
        """2026-11-07, review: "1.10" then "1.1" at one Date read as a
        conflict and lost the confirmation. Sides are kept canonical."""
        vs = _vs()
        self._w("ws", _frame("push", "1.10", "1.1002", vt=0, arrival=1))
        self.assertEqual(self._w("ws", _frame("push", "1.1", "1.10020",
                                              vt=0, arrival=5)), vs.SAME)
        self.assertEqual(self._w("ws", _frame("push", "11E-1", "1.1002",
                                              vt=0, arrival=6)), vs.SAME)
        raw = self.store.raw(self.IID, "ws")
        self.assertEqual((raw["bid"], raw["ask"]), ("1.1", "1.1002"))
        self.assertEqual(self.store.record(self.IID, "ws").confirmed_at,
                         _at(6))

    def test_w5_older_never_replaces_and_an_older_snapshot_confirms_nothing(self):
        vs = _vs()
        self._w("ws", _frame("push", vt=10, arrival=11))
        self.assertEqual(self._w("ws", _frame("push", "1.2000", "1.2002",
                                              vt=5, arrival=12)), vs.OLDER)
        self.assertEqual(self._w("ws", _frame("snapshot", "1.2000", "1.2002",
                                              vt=5, arrival=13)),
                         vs.SNAPSHOT_OLDER)
        q = self.store.record(self.IID, "ws")
        self.assertEqual((q.bid, q.vt, q.confirmed_at),
                         (Decimal("1.1000"), _at(10), _at(11)))
        self.assertEqual(self.store.counts["snapshot_older"], 1)
        self.assertEqual(self.store.counts["older"], 1)

    def test_w6_a_priceless_frame_is_liveness_only(self):
        vs = _vs()
        self._w("ws", _frame("push", vt=0, arrival=1))
        fr = _frame("push", None, None, vt=30, arrival=30)
        self.assertEqual(fr.outcome_hint, vs.PRICELESS)
        self.assertEqual(self._w("ws", fr), vs.PRICELESS)
        q = self.store.record(self.IID, "ws")
        self.assertEqual((q.vt, q.confirmed_at), (_at(0), _at(1)))
        self.assertEqual(self.store.raw(self.IID, "ws")["seen"], _ms(30))

    def test_w7_an_untimed_rest_answer_is_kept_beside_for_display(self):
        vs = _vs()
        self._w("rest", _frame("rest", vt=0, arrival=1))
        fr = _frame("rest", "1.3000", "1.3002", vt=None, arrival=40)
        self.assertEqual(fr.outcome_hint, vs.UNTIMED)
        self.assertEqual(self._w("rest", fr), vs.UNTIMED)
        q = self.store.record(self.IID, "rest")
        self.assertEqual(q.bid, Decimal("1.1000"), "never the record")
        raw = self.store.raw(self.IID, "rest")
        self.assertEqual((raw["ub"], raw["ua"]), ("1.3", "1.3002"))
        # the display's read: an untimed quote, never LIVE (W7)
        shown = self.store.untimed(self.IID)
        self.assertIsNone(shown.vt)
        self.assertEqual((shown.bid, shown.channel),
                         (Decimal("1.3"), "rest"))
        self.assertEqual(shown.confirmed_at, _at(40 - 60))
        from market_data import venue_quotes as vq
        with mock.patch.object(vq, "C_REST_MEASURED", True):
            g = vq.grade(shown, now=_at(40), asset_class="forex",
                         session_open=True, ws_healthy=True,
                         ws_trusted=True, unconfirmed_jump=False,
                         behind=False)
        self.assertNotEqual(g.grade, vq.LIVE)
        self.assertIn(vq.UNTIMED, g.flags)
        # with no record yet, an untimed answer still makes none
        self.store.write(99, "rest", fr)
        self.assertIsNone(self.store.record(99, "rest"))

    def test_the_rest_record_keeps_the_answers_conversion(self):
        """§4.5.6: the REST store keeps eToro's Date, the rate id and the
        conversion; the conversion carries its own confirmation, and a
        stream frame has none."""
        vs = _vs()
        self.assertEqual(self._w("rest", _frame(
            "rest", vt=0, arrival=1, conversion_bid="0.5900",
            conversion_ask="0.5902")), vs.NEW)
        conv = self.store.conversion(self.IID)
        self.assertEqual((conv.bid, conv.ask, conv.confirmed_at),
                         (Decimal("0.59"), Decimal("0.5902"), _at(1 - 60)))
        # the same print later, a newer conversion: kept, with its time
        self._w("rest", _frame("rest", vt=0, arrival=30,
                               conversion_bid="0.5910",
                               conversion_ask="0.5912"))
        conv = self.store.conversion(self.IID)
        self.assertEqual((conv.bid, conv.confirmed_at),
                         (Decimal("0.591"), _at(30 - 60)))
        # an older answer's conversion is not taken; one that does not read
        # leaves the last one
        self._w("rest", _frame("rest", vt=-5, arrival=40,
                               conversion_bid="0.6", conversion_ask="0.6"))
        self._w("rest", _frame("rest", vt=1, arrival=41,
                               conversion_bid="x", conversion_ask="0.6"))
        conv = self.store.conversion(self.IID)
        self.assertEqual(conv.bid, Decimal("0.591"))
        ws = _frame("push", vt=0, arrival=1, conversion_bid="0.5",
                    conversion_ask="0.5")
        self.assertEqual((ws.cb, ws.ca), ("", ""), "a stream frame has none")

    def test_a_zero_never_replaces_a_priced_record(self):
        vs = _vs()
        self._w("rest", _frame("rest", vt=0, arrival=1))
        for bid, ask in (("0", "0"), ("0", None), (None, None)):
            with self.subTest(bid=bid, ask=ask):
                fr = _frame("rest", bid, ask, vt=20, arrival=20)
                self.assertEqual(fr.outcome_hint, vs.ZERO)
                self.assertEqual(self._w("rest", fr), vs.ZERO)
        q = self.store.record(self.IID, "rest")
        self.assertEqual((q.bid, q.vt), (Decimal("1.1000"), _at(0)))
        self.assertEqual(q.confirmed_at, _at(1 - 60),
                         "an absence never refreshes the confirmation")
        raw = self.store.raw(self.IID, "rest")
        self.assertEqual(raw["absent_n"], "3")
        self.assertEqual(raw["absent"], _ms(20))

    def test_a_newer_priced_answer_after_an_absence_replaces(self):
        vs = _vs()
        self._w("rest", _frame("rest", "0", "0", vt=0, arrival=1))
        self.assertIsNone(self.store.record(self.IID, "rest"))
        self.assertEqual(self._w("rest", _frame("rest", vt=5, arrival=6)),
                         vs.NEW)
        self.assertEqual(self.store.raw(self.IID, "rest")["absent"], "")

    def test_the_channels_never_mix(self):
        """I2: each channel writes only its own key."""
        self._w("ws", _frame("push", vt=0, arrival=1))
        self.assertIsNone(self.store.record(self.IID, "rest"))
        self._w("rest", _frame("rest", "1.1005", "1.1007", vt=9,
                               arrival=10))
        self.assertEqual(self.store.record(self.IID, "ws").bid,
                         Decimal("1.1000"))

    def test_a_frame_of_the_other_channel_is_refused_before_the_store(self):
        """2026-11-07, review: a REST answer written to "ws" became a stream
        record confirmed 60 s early, and a push written to "rest" one
        confirmed 60 s late. Each channel takes only its own frames."""
        for channel, kind in (("ws", "rest"), ("rest", "push"),
                              ("rest", "snapshot")):
            with self.subTest(channel=channel, kind=kind):
                with self.assertRaises(ValueError):
                    self._w(channel, _frame(kind, vt=0, arrival=1))
        self.assertIsNone(self.store.record(self.IID, "ws"))
        self.assertIsNone(self.store.record(self.IID, "rest"))
        self.assertEqual(sum(self.store.counts.values()), 0)

    def test_current_until_cross_channel_dates_are_proven(self):
        """Until M2 proves the Dates comparable, the WS record while it is
        a candidate, else REST carries; never a comparison of Dates."""
        self._w("ws", _frame("push", vt=0, arrival=1))
        self._w("rest", _frame("rest", "1.1005", "1.1007", vt=9,
                               arrival=10))
        self.assertEqual(self.store.current(self.IID,
                                            ws_candidate=True).channel, "ws")
        self.assertEqual(self.store.current(self.IID,
                                            ws_candidate=False).channel,
                         "rest")

    def test_current_takes_the_newer_of_the_two_rest_records(self):
        """2026-11-07, review: the feed's REST record at 12:00:00 was
        returned over the engine's at 12:00:28. Both are REST v1 answers:
        their Dates compare, proven or not; the feed's own on a tie."""
        from market_data import venue_quotes as vq
        self._w("rest", _frame("rest", vt=0, arrival=1))
        engine = vq.VenueQuote(iid=self.IID, bid="1.1050", ask="1.1052",
                               vt=_at(28), channel="engine",
                               arrival=_at(29), confirmed_at=_at(29 - 60))
        for proven in (False, True):
            with self.subTest(proven=proven):
                cur = self.store.current(self.IID, ws_candidate=False,
                                         engine=engine,
                                         cross_channel_proven=proven)
                self.assertEqual((cur.channel, cur.vt), ("engine", _at(28)))
        older = engine.__class__(iid=self.IID, bid="1.1050", ask="1.1052",
                                 vt=_at(0), channel="engine",
                                 arrival=_at(2), confirmed_at=_at(2 - 60))
        self.assertEqual(self.store.current(self.IID, ws_candidate=False,
                                            engine=older).channel, "rest")
        untimed = engine.__class__(iid=self.IID, bid="1.1050", ask="1.1052",
                                   vt=None, channel="engine",
                                   arrival=_at(40))
        self.assertEqual(self.store.current(self.IID, ws_candidate=False,
                                            engine=untimed).channel, "rest",
                         "an untimed answer is display only")

    def test_current_once_proven_is_the_newest_and_ws_wins_a_tie(self):
        self._w("ws", _frame("push", vt=0, arrival=1))
        self._w("rest", _frame("rest", "1.1005", "1.1007", vt=9,
                               arrival=10))
        self.assertEqual(self.store.current(
            self.IID, ws_candidate=True,
            cross_channel_proven=True).channel, "rest")
        self._w("ws", _frame("push", "1.1006", "1.1008", vt=9, arrival=11))
        self.assertEqual(self.store.current(
            self.IID, ws_candidate=True,
            cross_channel_proven=True).channel, "ws")

    def test_current_says_whether_the_stream_is_a_candidate(self):
        """2026-11-07, review: ws_candidate defaulted to True, so a caller
        that forgot §5.6's trust read an untrusted stream record."""
        with self.assertRaises(TypeError):
            self.store.current(self.IID)

    def test_no_record_is_none(self):
        self.assertIsNone(self.store.current(12345, ws_candidate=True))
        self.assertIsNone(self.store.record(12345, "ws"))


class TheMemoryTwinTests(_Rules, SimpleTestCase):

    def make(self, **kw):
        return _vs().MemoryVenueStore(**kw)

    def setUp(self):
        self.store = self.make()

    def test_the_twin_writes_one_frame_at_a_time(self):
        """2026-11-07, review: the twin read, decided and wrote with no
        lock, so writer B deciding on the old record while writer A wrote
        a newer one moved the store back. Forced: B decides, A writes, B
        writes — the twin now never moves back, as the atomic script."""
        vs = _vs()
        store = self.store
        store.write(self.IID, "ws", _frame("push", vt=0, arrival=1))
        real = vs.decide
        b_inside = threading.Event()
        a_done = threading.Event()

        def gated(cur, fr, **kw):
            out = real(cur, fr, **kw)
            if fr["vt"] == _ms(5):                    # writer B, older
                b_inside.set()
                a_done.wait(0.5)
            return out
        results = {}
        with mock.patch.object(vs, "decide", side_effect=gated):
            tb = threading.Thread(target=lambda: results.update(
                b=store.write(self.IID, "ws", _frame(
                    "push", "1.1500", "1.1502", vt=5, arrival=10))))
            tb.start()
            self.assertTrue(b_inside.wait(5))
            ta = threading.Thread(target=lambda: results.update(
                a=store.write(self.IID, "ws", _frame(
                    "push", "1.2000", "1.2002", vt=10, arrival=10))))
            ta.start()
            ta.join(0.2)           # A cannot write while B holds the lock
            a_done.set()
            tb.join(5)
            ta.join(5)
        self.assertEqual(results, {"b": vs.NEW, "a": vs.NEW})
        self.assertEqual(store.record(self.IID, "ws").vt, _at(10))

    def test_the_twin_expires_a_record_four_days_after_it_was_last_set(self):
        """As Redis does on the wall clock, the twin on the frames' own:
        a record nothing created, replaced or confirmed for four days is
        gone, so an older frame then writes "new" on both."""
        vs = _vs()
        keep = 4 * 86400
        self._w("ws", _frame("push", vt=10, arrival=11))
        self.assertEqual(self.store.expires_ms(self.IID, "ws"),
                         int(_ms(11)) + keep * 1000)
        # older frames never push the expiry back
        self.assertEqual(self._w("ws", _frame("push", vt=5, arrival=600)),
                         vs.OLDER)
        self.assertEqual(self.store.expires_ms(self.IID, "ws"),
                         int(_ms(11)) + keep * 1000)
        self.assertEqual(self._w("ws", _frame("push", vt=5,
                                              arrival=keep + 11)), vs.NEW)

    def test_a_new_key_written_by_an_absence_still_expires(self):
        self._w("rest", _frame("rest", "0", "0", vt=0, arrival=1))
        self.assertIsNotNone(self.store.expires_ms(self.IID, "rest"))


class _RedisServer:
    """A private redis-server on a unix socket in a temporary folder."""

    def __init__(self):
        if not REDIS_SERVER:
            raise AssertionError(
                "no redis-server binary on this CI host: the Lua half of the "
                "venue store must run here (.github/workflows/tests.yml "
                "installs it)")
        self.dir = tempfile.mkdtemp(prefix="vq-redis-")
        self.sock = os.path.join(self.dir, "r.sock")
        self.proc = subprocess.Popen(
            [REDIS_SERVER, "--port", "0", "--unixsocket", self.sock,
             "--save", "", "--appendonly", "no", "--dir", self.dir],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import redis
        self.client = redis.Redis(unix_socket_path=self.sock)
        deadline = time.monotonic() + 10
        while True:
            try:
                self.client.ping()
                break
            except Exception:  # noqa: BLE001 — still starting
                if time.monotonic() > deadline or self.proc.poll() is not None:
                    self.stop()
                    raise RuntimeError("redis-server did not start")
                time.sleep(0.05)

    def stop(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            self.proc.kill()
        shutil.rmtree(self.dir, ignore_errors=True)


@skipUnless(RUN_REDIS, "no redis-server binary on this host")
class TheRedisScriptTests(_Rules, SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = _RedisServer()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        super().tearDownClass()

    def make(self, **kw):
        return _vs().RedisVenueStore(self.server.client, **kw)

    def setUp(self):
        self.server.client.flushall()
        self.store = self.make()

    def test_the_script_refuses_any_key_outside_vq(self):
        vs = _vs()
        import redis
        script = self.server.client.register_script(vs.CAS_LUA)
        fr = _frame("push")
        with self.assertRaises(redis.ResponseError):
            script(keys=["etoro_rates:r:live:7"],
                   args=fr.args() + ["1000", "0"])
        self.assertFalse(self.server.client.exists("etoro_rates:r:live:7"))

    def test_the_records_expire_after_four_days(self):
        self._w("ws", _frame("push"))
        ttl = self.server.client.pttl(_vs().ws_key(self.IID))
        self.assertGreater(ttl, (4 * 86400 - 60) * 1000)
        self.assertLessEqual(ttl, 4 * 86400 * 1000)

    def test_an_older_frame_never_pushes_the_expiry_back(self):
        """2026-11-07, review: PEXPIRE ran on every write, so a record a
        stream kept answering "older" never expired. Only a record created,
        replaced or confirmed sets its expiry."""
        vs = _vs()
        client = self.server.client
        key = vs.ws_key(self.IID)
        self._w("ws", _frame("push", vt=10, arrival=11))
        client.pexpire(key, 5000)                 # four days nearly gone
        for outcome, fr in ((vs.OLDER, _frame("push", vt=5, arrival=12)),
                            (vs.CONFLICT, _frame("push", "1.2", "1.2002",
                                                 vt=10, arrival=13)),
                            (vs.PRICELESS, _frame("push", None, None,
                                                  vt=10, arrival=14))):
            self.assertEqual(self._w("ws", fr), outcome)
            self.assertLessEqual(client.pttl(key), 5000, outcome)
        self.assertEqual(self._w("ws", _frame("push", vt=10, arrival=15)),
                         vs.SAME)
        self.assertGreater(client.pttl(key), 5000, "a confirmation renews")

    def test_a_short_keep_expires_on_both_alike(self):
        """The expiry, on Redis's wall clock and the twin's frame clock:
        frames arriving now, a 300 ms keep, an older frame 600 ms later
        writes "new" on both."""
        vs = _vs()
        real, twin = self.make(keep_s=0.3), vs.MemoryVenueStore(keep_s=0.3)
        t0 = datetime.now(tz=dt_tz.utc)

        def fr(vt_s, arrival):
            return vs.frame(kind="push", bid="1.1", ask="1.1002",
                            vt=t0 + timedelta(seconds=vt_s), arrival=arrival)
        for store in (real, twin):
            self.assertEqual(store.write(self.IID, "ws", fr(10, t0)), vs.NEW)
        time.sleep(0.6)
        later = datetime.now(tz=dt_tz.utc)
        self.assertEqual([s.write(self.IID, "ws", fr(5, later))
                          for s in (real, twin)], [vs.NEW, vs.NEW])


@skipUnless(RUN_REDIS, "no redis-server binary on this host")
class TheTwinsAgreeTests(SimpleTestCase):
    """The same random sequences leave both stores alike, field for
    field (random.Random(seed), 50 seeds, rate ids unproven and proven)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = _RedisServer()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        super().tearDownClass()

    def test_fifty_seeds(self):
        import random
        vs = _vs()
        bids = ("1.1000", "1.1001", "0", None, "1.1002", "x", "1.1004",
                "1.10", "9e999999")
        for proven in (False, True):
            for seed in range(50):
                rng = random.Random(seed)
                self.server.client.flushall()
                twin = vs.MemoryVenueStore(rate_id_proven=proven)
                real = vs.RedisVenueStore(self.server.client,
                                          rate_id_proven=proven)
                for step in range(40):
                    kind = rng.choice(("push", "snapshot", "rest"))
                    bid = rng.choice(bids)
                    ask = None if bid is None else (
                        str(Decimal(bid) + Decimal("0.0002"))
                        if bid not in ("x", "9e999999") else "1.1002")
                    if rng.random() < 0.1:
                        ask = "0"
                    vt = rng.choice((None, 0, 1, 2, 3, 3, 4, 400)) \
                        if kind == "rest" else rng.choice((0, 1, 2, 3, 3, 4))
                    conv = rng.choice(((None, None), ("0.59", "0.5902"),
                                       ("0.591", "0.5912"), ("x", "0.6")))
                    fr = _frame(kind, bid, ask, vt=vt, arrival=step,
                                rate_id=rng.choice(("", "", "7", "8", "10",
                                                    "x9")),
                                **({"conversion_bid": conv[0],
                                    "conversion_ask": conv[1]}
                                   if kind == "rest" else {}))
                    channel = "rest" if kind == "rest" else "ws"
                    a = twin.write(1, channel, fr)
                    b = real.write(1, channel, fr)
                    self.assertEqual(a, b, f"{proven} seed {seed} step {step}")
                for channel in ("ws", "rest"):
                    self.assertEqual(twin.raw(1, channel),
                                     real.raw(1, channel),
                                     f"{proven} seed {seed} {channel}")
                self.assertEqual(dict(twin.counts), dict(real.counts),
                                 f"{proven} seed {seed}")


class TheKeysTests(SimpleTestCase):

    def test_the_feeds_keys(self):
        vs = _vs()
        self.assertEqual(vs.ws_key(7), "vq:ws:7")
        self.assertEqual(vs.rest_key(7), "vq:rest:7")
        self.assertEqual(vs.ring_key(7), "vq:ring:7")
        self.assertEqual(vs.record_key("ws", "7"), "vq:ws:7")
        with self.assertRaises(ValueError):
            vs.record_key("engine", 7)

    def test_the_engine_key_is_the_engines_own(self):
        vs = _vs()
        from bot_program.engine import etoro_rates
        for world in ("live", "demo"):
            self.assertEqual(vs.engine_key(world, 7),
                             etoro_rates._key(world, 7))

    def test_dates_are_kept_to_the_millisecond_truncated(self):
        vs = _vs()
        t = NOW + timedelta(microseconds=999_999)
        self.assertEqual(vs._ms(t) - vs._ms(NOW), 999)
        self.assertEqual(vs._to_ms(t), NOW + timedelta(milliseconds=999))


class _Cache:
    """A cache that answers per key, and records every call."""

    def __init__(self, held):
        self.held = dict(held)
        self.calls = []

    def get(self, key):
        self.calls.append(("get", key))
        value = self.held.get(key)
        if isinstance(value, Exception):
            raise value
        return value

    def __getattr__(self, name):
        def write(*a, **k):
            self.calls.append((name, a))
            raise AssertionError(f"the feed wrote the engine's cache: {name}")
        return write


class TheEngineViewTests(SimpleTestCase):
    """The engine's rates cache is read, never written, before F9."""

    def _held(self, *, at_s=-3, date="2026-11-04T11:59:56Z", rid="9",
              bid="1.1000", ask="1.1002"):
        return {"lastPrice": "1.1001", "bid": bid, "ask": ask,
                "at": _at(at_s).timestamp(), "date": date,
                "priceRateID": rid}

    def test_a_dated_answer_reads_as_a_rest_record(self):
        vs = _vs()
        c = _Cache({vs.engine_key("live", 7): self._held()})
        q = vs.engine_record(7, cache=c, now=NOW)
        self.assertEqual(q.channel, "engine")
        self.assertEqual((q.bid, q.ask), (Decimal("1.1000"),
                                          Decimal("1.1002")))
        self.assertEqual(q.vt, _at(-4))
        self.assertEqual(q.rate_id, "9")
        self.assertEqual(q.arrival, _at(-3))
        self.assertEqual(q.confirmed_at, _at(-3 - 60))
        self.assertEqual([k for op, k in c.calls], [
            vs.engine_key("live", 7), vs.engine_key("demo", 7)])
        self.assertEqual({op for op, _ in c.calls}, {"get"})

    def test_the_newest_of_the_two_worlds(self):
        """§5.2: market data carries no world; the REST reader takes the
        newest of the world keys."""
        vs = _vs()
        c = _Cache({
            vs.engine_key("live", 7): self._held(
                date="2026-11-04T11:59:50Z", bid="1.0990", ask="1.0992"),
            vs.engine_key("demo", 7): self._held(
                date="2026-11-04T11:59:58.250Z", bid="1.1010",
                ask="1.1012")})
        q = vs.engine_record(7, cache=c, now=NOW)
        self.assertEqual((q.bid, q.vt), (Decimal("1.1010"),
                                         _at(-1.75)))

    def test_an_engine_date_is_kept_to_the_millisecond(self):
        vs = _vs()
        c = _Cache({vs.engine_key("live", 7): self._held(
            date="2026-11-04T11:59:56.1239Z")})
        q = vs.engine_record(7, cache=c, now=NOW)
        self.assertEqual(q.vt, _at(-4) + timedelta(milliseconds=123))

    def test_an_answer_stamped_ahead_of_the_clock_is_not_taken(self):
        """2026-11-07, review: a cache stamp an hour ahead was taken
        (etoro_rates.get refuses one more than 5 s ahead); so is a Date far
        ahead of the answer's own arrival."""
        vs = _vs()
        for held in (self._held(at_s=3600, date="2026-11-04T12:59:59Z"),
                     self._held(at_s=-3, date="2026-11-04T13:00:00Z")):
            with self.subTest(held=held):
                c = _Cache({vs.engine_key("live", 7): held})
                self.assertIsNone(vs.engine_record(7, cache=c, now=NOW))
        c = _Cache({vs.engine_key("live", 7): self._held(
            at_s=4, date="2026-11-04T12:00:03Z")})
        self.assertIsNotNone(vs.engine_record(7, cache=c, now=NOW),
                             "a few seconds ahead is a clock, taken")

    def test_an_answer_without_a_date_or_sides_is_no_record(self):
        vs = _vs()
        for held in (None, {"lastPrice": "1.1", "at": NOW.timestamp()},
                     {"lastPrice": "0", "bid": "0", "ask": "0",
                      "at": NOW.timestamp(), "date": "2026-11-04T12:00:00Z"},
                     {"lastPrice": "1.1", "bid": "1.1", "ask": "1.1002",
                      "at": NOW.timestamp(), "date": "not a date"},
                     "garbage"):
            with self.subTest(held=held):
                c = _Cache({vs.engine_key("live", 7): held})
                self.assertIsNone(vs.engine_record(7, cache=c, now=NOW))

    def test_an_untimed_answer_only_when_asked_for_display(self):
        vs = _vs()
        c = _Cache({vs.engine_key("live", 7): {
            "lastPrice": "1.1", "bid": "1.1", "ask": "1.1002",
            "at": _at(-2).timestamp()}})
        self.assertIsNone(vs.engine_record(7, cache=c, now=NOW))
        q = vs.engine_record(7, cache=c, now=NOW, untimed=True)
        self.assertIsNone(q.vt)
        self.assertEqual(q.bid, Decimal("1.1"))

    def test_an_unreadable_cache_is_no_record(self):
        vs = _vs()
        c = _Cache({vs.engine_key("live", 7): RuntimeError("down"),
                    vs.engine_key("demo", 7): RuntimeError("down")})
        self.assertIsNone(vs.engine_record(7, cache=c, now=NOW))
        c = _Cache({vs.engine_key("live", 7): RuntimeError("down"),
                    vs.engine_key("demo", 7): self._held()})
        self.assertEqual(vs.engine_record(7, cache=c, now=NOW).vt, _at(-4),
                         "one unreadable world leaves the other")
