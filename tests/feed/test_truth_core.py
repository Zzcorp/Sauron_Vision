"""THE TRUTH CORE (the eToro feed spec, F1, §4.3, §5.1-§5.8; 2026-11-07).

market_data.venue_quotes holds the types (VenueQuote, ReferenceQuote,
VenuePrice, Refusal), the one grade function, authority, the one money
door (money_price), the display and reference wrappers and the one
venue-source rule; market_data.venue_session the session rule. All pure:
no network, no database, no cache, and nothing in F1 calls them on a money
path. What is pinned here:

  * a quote is one coherent tuple (I3, W1): the constructor refuses a
    missing side, a value <= 0, a non-finite or unparsable value, a crossed
    quote and a spread above 10% of the mid, and keeps no mid;
  * money has one door and it is shut (I7, I14): while every feed switch
    is OFF — in F1 none exists to turn on — money_price answers
    Refusal("switch_off") for every purpose, record or none, and an
    outside quote is refused by type;
  * one pure grade function (I5, I6): LIVE, RECENT, STALE, CLOSED and NONE
    by class from the confirmation age, never Sauron's write time, with
    the quiet, jump, skew, behind and untimed flags;
  * authority never depends on a quote, and leaving it takes 60 s of
    absence (I1);
  * the screen never substitutes (I10): the main cell is eToro's numbers
    or "awaiting eToro", an outside quote only in its labelled slot;
  * the session rule is asymmetric (§5.5): a disagreement or an unmeasured
    break window can hold back an entry, never protection.

Every symbol and value is synthetic. Run with:
    python manage.py test tests.feed.test_truth_core
"""
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal

from django.test import SimpleTestCase

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=dt_tz.utc)       # a Wednesday


def _vq():
    from market_data import venue_quotes
    return venue_quotes


#: Every input grade() needs, for a healthy, trusted stream in an open
#: session (each test overrides what it is about).
OPEN_HEALTHY = dict(session_open=True, ws_healthy=True, ws_trusted=True,
                    unconfirmed_jump=False, behind=False)


def _grade(record, *, now=NOW, asset_class="forex", **kw):
    vq = _vq()
    return vq.grade(record, now=now, asset_class=asset_class,
                    **dict(OPEN_HEALTHY, **kw))


def _display(record, *, now=NOW, asset_class="forex", reference=None,
             slot_shown=False, session_closed_at=None, **kw):
    vq = _vq()
    return vq.display_quote(record, _grade(record, now=now,
                                           asset_class=asset_class, **kw),
                            now=now, reference=reference,
                            slot_shown=slot_shown,
                            session_closed_at=session_closed_at)


def _quote(bid="1.1000", ask="1.1002", *, vt_age_s=1, conf_age_s=1,
           channel="ws", iid=1, rate_id="", now=NOW):
    vq = _vq()
    vt = None if vt_age_s is None else now - timedelta(seconds=vt_age_s)
    return vq.VenueQuote(
        iid=iid, bid=bid, ask=ask, vt=vt, rate_id=rate_id,
        channel=channel, arrival=now - timedelta(seconds=conf_age_s),
        confirmed_at=now - timedelta(seconds=conf_age_s))


# ── 1. a quote is one coherent tuple (I3, W1) ────────────────────────────

class TheVenueQuoteTests(SimpleTestCase):

    def test_a_valid_quote_keeps_decimals_and_no_stored_mid(self):
        q = _quote("1.1000", "1.1002")
        self.assertEqual(q.bid, Decimal("1.1000"))
        self.assertEqual(q.ask, Decimal("1.1002"))
        self.assertEqual(q.mid, Decimal("1.1001"))
        self.assertNotIn("mid", {f for f in q.__dataclass_fields__},
                         "the mid is computed, never stored (I3)")

    def test_every_w1_refusal_names_its_reason(self):
        vq = _vq()
        cases = {
            "missing_side": (None, "1.1002"),
            "not_positive": ("0", "1.1002"),
            "not_finite": ("NaN", "1.1002"),
            "unparsed": ("abc", "1.1002"),
            "crossed": ("1.1003", "1.1002"),
            "wide_spread": ("100", "120"),
        }
        for reason, (bid, ask) in cases.items():
            with self.subTest(reason=reason):
                with self.assertRaises(vq.InvalidQuote) as cm:
                    _quote(bid, ask)
                self.assertEqual(cm.exception.reason, reason)
        for bad in ("Infinity", "-1", "-0.5", "", "1e999999"):
            with self.subTest(bad=bad):
                with self.assertRaises(vq.InvalidQuote):
                    _quote(bad, "1.1002")
        with self.assertRaises(vq.InvalidQuote) as cm:
            _quote(channel="yfinance")
        self.assertEqual(cm.exception.reason, "bad_channel")

    def test_a_side_is_plain_decimal_text_within_range(self):
        """2026-11-07, review: "9e999999" raised decimal.Overflow out of the
        constructor, "1e400" was a price and "1_000" read as 1000. A side
        is plain decimal text (an exponent allowed), within 1e-12..1e13,
        and every refusal is an InvalidQuote with its reason."""
        vq = _vq()
        for bad, reason in (("9e999999", "out_of_range"),
                            ("1e400", "out_of_range"),
                            ("1e-13", "out_of_range"),
                            ("1_000", "unparsed"), ("0x10", "unparsed"),
                            ("1.1.1", "unparsed"), ("--1", "unparsed"),
                            ("-Infinity", "not_finite"),
                            ("sNaN", "not_finite")):
            with self.subTest(bad=bad):
                with self.assertRaises(vq.InvalidQuote) as cm:
                    _quote(bad, bad)
                self.assertEqual(cm.exception.reason, reason)
        for good, want in ((" 1.1000 ", Decimal("1.1")), ("11E-1", Decimal(
                "1.1")), (Decimal("1.1"), Decimal("1.1")), (2, Decimal(2)),
                (1.5, Decimal("1.5")), ("1e12", Decimal("1e12"))):
            with self.subTest(good=good):
                self.assertEqual(_quote(good, good).bid, want)

    def test_an_exactly_ten_percent_spread_is_kept_and_a_locked_quote_too(self):
        q = _quote("95", "105")                      # 10% of the mid 100
        self.assertEqual(q.mid, Decimal("100"))
        self.assertEqual(_quote("100", "100").mid, Decimal("100"))

    def test_the_quote_is_immutable(self):
        q = _quote()
        with self.assertRaises(FrozenInstanceError):
            q.bid = Decimal("2")

    def test_the_closing_and_executable_sides(self):
        """eToro values a long at its bid and a short at its ask; a BUY
        fills at the ask and a SELL at the bid."""
        q = _quote("1.1000", "1.1002")
        self.assertEqual(q.closing_side("BUY"), (Decimal("1.1000"), "bid"))
        self.assertEqual(q.closing_side("SELL"), (Decimal("1.1002"), "ask"))
        self.assertEqual(q.closing_side("long"), (Decimal("1.1000"), "bid"))
        self.assertEqual(q.executable_side("BUY"), (Decimal("1.1002"), "ask"))
        self.assertEqual(q.executable_side("SELL"), (Decimal("1.1000"), "bid"))
        with self.assertRaises(ValueError):
            q.closing_side("FLAT")

    def test_a_confirmation_never_moves_backwards(self):
        q = _quote(conf_age_s=5)
        later = q.confirmed(NOW)
        self.assertEqual(later.confirmed_at, NOW)
        self.assertEqual(later.confirmed(NOW - timedelta(seconds=30))
                         .confirmed_at, NOW)


class TheReferenceQuoteTests(SimpleTestCase):

    def test_only_a_same_instrument_stream_quote_qualifies(self):
        """§5.7: same instrument, a real-time stream source, written <=
        120 s ago. Pollers never qualify."""
        vq = _vq()
        fresh = NOW - timedelta(seconds=30)
        ok = vq.ReferenceQuote("EURUSD", "oanda_stream", Decimal("1.1001"),
                               fresh)
        self.assertTrue(ok.qualifies(NOW))
        for src in ("yfinance", "alpha_vantage", "binance_public",
                    "coingecko", "etoro", "ibkr"):
            with self.subTest(src=src):
                self.assertFalse(vq.ReferenceQuote(
                    "EURUSD", src, Decimal("1.1001"), fresh).qualifies(NOW))
        self.assertFalse(vq.ReferenceQuote(
            "EURUSD", "oanda_stream", Decimal("1.1001"),
            NOW - timedelta(seconds=121)).qualifies(NOW))
        self.assertFalse(vq.ReferenceQuote(
            "XAUUSD", "binance_ws", Decimal("2000"), fresh,
            stand_in="future").qualifies(NOW))

    def test_the_reference_mid_comes_from_its_own_coherent_quote(self):
        vq = _vq()
        r = vq.ReferenceQuote("EURUSD", "oanda_stream", Decimal("1.1001"),
                              NOW, bid=Decimal("1.1000"),
                              ask=Decimal("1.1004"))
        self.assertEqual(r.mid, Decimal("1.1002"))
        self.assertEqual(vq.ReferenceQuote("AAPL", "finnhub_ws",
                                           Decimal("200"), NOW).mid,
                         Decimal("200"))


# ── 2. the one money door, shut (I7, I14) ────────────────────────────────

class TheMoneyDoorTests(SimpleTestCase):

    def _purposes(self):
        vq = _vq()
        return [vq.closing("BUY"), vq.closing("SELL"),
                vq.executable("BUY"), vq.executable("SELL"),
                vq.conversion("USD"), vq.conversion("JPY")]

    def test_every_purpose_is_refused_switch_off_while_no_switch_exists(self):
        vq = _vq()
        self.assertEqual(dict(vq.FEED_MONEY_SWITCHES), {},
                         "F1 adds no switch")
        live = _quote()
        stale = _quote(conf_age_s=600)
        for purpose in self._purposes():
            for record in (None, live, stale):
                with self.subTest(purpose=purpose, record=record):
                    answer = vq.money_price("EURUSD", purpose, record=record,
                                            now=NOW)
                    self.assertIsInstance(answer, vq.Refusal)
                    self.assertEqual(answer.reason, "switch_off")
                    self.assertFalse(answer, "a Refusal is falsy")

    def test_an_outside_quote_is_refused_by_type(self):
        vq = _vq()
        ref = vq.ReferenceQuote("EURUSD", "oanda_stream", Decimal("1.1"), NOW)
        for purpose in self._purposes():
            with self.assertRaises(TypeError):
                vq.money_price("EURUSD", purpose, record=ref, now=NOW)

    def test_a_purpose_is_one_of_the_three_kinds(self):
        vq = _vq()
        with self.assertRaises(TypeError):
            vq.money_price("EURUSD", "closing", now=NOW)
        with self.assertRaises(ValueError):
            vq.closing("HOLD")
        with self.assertRaises(ValueError):
            vq.conversion("")
        self.assertEqual(vq.closing("long").side, "BUY")
        self.assertEqual(vq.executable("short").side, "SELL")

    def test_the_refusal_reasons_are_the_specs_seven(self):
        vq = _vq()
        self.assertEqual(set(vq.REFUSAL_REASONS), {
            "switch_off", "not_live", "unconfirmed_jump", "session", "quiet",
            "no_record", "stale_conversion"})
        with self.assertRaises(ValueError):
            vq.Refusal("because")
        price = vq.VenuePrice(Decimal("1.1"), "bid", NOW, NOW, "ws", "LIVE")
        self.assertTrue(price)


# ── 3. one pure grade function (I5, I6) ──────────────────────────────────

class TheThresholdTests(SimpleTestCase):

    def test_the_starting_values_of_the_spec(self):
        vq = _vq()
        want = {"forex": (10, 15, 60, 2, 60, 300),
                "crypto": (10, 15, 60, 2, 60, 0),
                "index": (10, 15, 60, 3, 60, 300),
                "commodity": (15, 20, 60, 3, 120, 300),
                "stock": (60, 65, 120, 5, 300, 300)}
        for cls, row in want.items():
            self.assertEqual(tuple(vq.thresholds(cls)), row, cls)
        self.assertEqual(vq.thresholds("etf"), vq.thresholds("stock"))
        self.assertEqual(vq.thresholds("FOREX"), vq.thresholds("forex"))

    def test_an_unknown_class_takes_the_strictest_row(self):
        vq = _vq()
        t = vq.thresholds("cfd")
        for cls in ("forex", "crypto", "index", "commodity", "stock"):
            known = vq.thresholds(cls)
            self.assertLessEqual(t.live_s, known.live_s)
            self.assertLessEqual(t.stale_s, known.stale_s)
            self.assertLessEqual(t.entry_s, known.entry_s)
            self.assertLessEqual(t.entry_quiet_s, known.entry_quiet_s)

    def test_rest_alone_is_never_live_until_measured(self):
        """C_rest = 60 s until M1/M2 measure it. The spec reads that as
        "REST alone never makes LIVE", but a stock's L (65 s) is above
        60 s: a REST answer would read LIVE for 5 s. So the rule says it:
        while C_rest is unmeasured, a REST or engine record is never LIVE,
        in any class, however fresh its confirmation."""
        vq = _vq()
        self.assertEqual(vq.C_REST_UNMEASURED_S, 60)
        self.assertEqual(vq.REST_FLOOR_S, 30)
        self.assertFalse(vq.C_REST_MEASURED)
        self.assertGreater(vq.thresholds("stock").live_s,
                           vq.C_REST_UNMEASURED_S,
                           "the arithmetic alone would not hold")
        for cls in ("forex", "crypto", "index", "commodity", "stock", "etf"):
            for channel in ("rest", "engine"):
                with self.subTest(cls=cls, channel=channel):
                    g = _grade(_quote(channel=channel, vt_age_s=0,
                                      conf_age_s=0), asset_class=cls)
                    self.assertEqual(g.grade, vq.RECENT)


class TheGradeTests(SimpleTestCase):

    def test_none_without_a_record(self):
        vq = _vq()
        g = _grade(None)
        self.assertEqual(g.grade, vq.NONE)
        self.assertIsNone(g.confirm_age_s)

    def test_live_recent_stale_by_confirmation_age_per_class(self):
        vq = _vq()
        for cls in ("forex", "crypto", "index", "commodity", "stock"):
            t = vq.thresholds(cls)
            for age, want in ((0, vq.LIVE), (t.live_s, vq.LIVE),
                              (t.live_s + 1, vq.RECENT),
                              (t.stale_s, vq.RECENT),
                              (t.stale_s + 1, vq.STALE)):
                with self.subTest(cls=cls, age=age):
                    g = _grade(_quote(vt_age_s=age, conf_age_s=age),
                               asset_class=cls)
                    self.assertEqual(g.grade, want)
                    self.assertEqual(g.confirm_age_s, age)

    def test_freshness_is_the_confirmation_not_the_print(self):
        """A print 10 minutes old, confirmed a second ago, is LIVE (a
        quiet market) and flagged quiet past EQ; a print a second old
        confirmed 20 minutes ago is STALE (I5)."""
        vq = _vq()
        quiet = _grade(_quote(vt_age_s=600, conf_age_s=1))
        self.assertEqual(quiet.grade, vq.LIVE)
        self.assertIn(vq.QUIET, quiet.flags)
        self.assertEqual(quiet.print_age_s, 600)
        old = _grade(_quote(vt_age_s=1, conf_age_s=1200))
        self.assertEqual(old.grade, vq.STALE)
        lively = _grade(_quote(vt_age_s=30, conf_age_s=1))
        self.assertNotIn(vq.QUIET, lively.flags)

    def test_a_shut_session_is_closed_whatever_the_age(self):
        vq = _vq()
        for age in (1, 600, 3600):
            g = _grade(_quote(vt_age_s=age, conf_age_s=age),
                       session_open=False)
            self.assertEqual(g.grade, vq.CLOSED)
        self.assertEqual(_grade(None, session_open=False).grade, vq.NONE)

    def test_an_unconfirmed_jump_is_never_live(self):
        vq = _vq()
        g = _grade(_quote(), unconfirmed_jump=True)
        self.assertEqual(g.grade, vq.RECENT)
        self.assertIn(vq.UNCONFIRMED_JUMP, g.flags)

    def test_a_ws_record_is_live_only_while_healthy_trusted_and_not_behind(self):
        vq = _vq()
        q = _quote(channel="ws")
        for kw, flag in (({"ws_healthy": False}, None),
                         ({"ws_trusted": False}, None),
                         ({"behind": True}, vq.BEHIND)):
            with self.subTest(kw=kw):
                g = _grade(q, **kw)
                self.assertEqual(g.grade, vq.RECENT)
                if flag:
                    self.assertIn(flag, g.flags)
        rest = _quote(channel="rest")
        from unittest import mock
        with mock.patch.object(vq, "C_REST_MEASURED", True):
            self.assertEqual(_grade(rest, ws_healthy=False).grade, vq.LIVE,
                             "the stream's health never grades a REST "
                             "record")

    def test_an_untimed_record_is_never_live(self):
        """W7: an answer without eToro's Date is display only."""
        vq = _vq()
        g = _grade(_quote(vt_age_s=None, channel="rest"))
        self.assertNotEqual(g.grade, vq.LIVE)
        self.assertIn(vq.UNTIMED, g.flags)
        self.assertIsNone(g.print_age_s)

    def test_a_date_ahead_of_the_clock_is_flagged_and_floored(self):
        vq = _vq()
        ahead = _grade(_quote(vt_age_s=-5))
        self.assertIn(vq.SKEW, ahead.flags)
        self.assertEqual(ahead.print_age_s, 0)
        near = _grade(_quote(vt_age_s=-1))
        self.assertNotIn(vq.SKEW, near.flags)

    def test_ages_are_exact_seconds(self):
        """2026-11-07, review: ages were truncated to whole seconds, so a
        confirmation 15.9 s old read LIVE with L = 15 s."""
        vq = _vq()
        q = _quote(vt_age_s=0, conf_age_s=0)
        for after, want in ((15.0, vq.LIVE), (15.001, vq.RECENT),
                            (15.9, vq.RECENT)):
            with self.subTest(after=after):
                g = _grade(q, now=NOW + timedelta(seconds=after))
                self.assertEqual(g.grade, want)
                self.assertAlmostEqual(g.confirm_age_s, after, places=6)

    def test_a_confirmation_ahead_of_the_clock_is_never_live(self):
        """2026-11-07, review: with the host clock stepped back, a record
        confirmed "in the future" read LIVE at age 0 for the whole step,
        on no new evidence. Its age is unknown: flagged, never LIVE."""
        vq = _vq()
        confirmed = NOW
        for back in (60, 3600):
            with self.subTest(back=back):
                q = vq.VenueQuote(iid=1, bid="1.1", ask="1.1002",
                                  vt=confirmed, channel="ws",
                                  arrival=confirmed)
                now = confirmed - timedelta(seconds=back) + \
                    timedelta(seconds=30)
                g = _grade(q, now=now)
                self.assertNotEqual(g.grade, vq.LIVE)
                self.assertIn(vq.CLOCK_BACK, g.flags)
        q = _quote(vt_age_s=-1, conf_age_s=-1)       # within the tolerance
        g = _grade(q)
        self.assertEqual(g.grade, vq.LIVE)
        self.assertNotIn(vq.CLOCK_BACK, g.flags)

    def test_every_input_is_required(self):
        """2026-11-07, review: the stream's health, trust and lag, the jump
        and the session defaulted to the risky values, so a caller that
        forgot one was handed LIVE. Each is required."""
        vq = _vq()
        q = _quote()
        for missing in OPEN_HEALTHY:
            with self.subTest(missing=missing):
                kw = {k: v for k, v in OPEN_HEALTHY.items() if k != missing}
                with self.assertRaises(TypeError):
                    vq.grade(q, now=NOW, asset_class="forex", **kw)

    def test_a_record_older_than_four_days_is_none(self):
        vq = _vq()
        days = 4 * 86400
        self.assertEqual(_grade(_quote(vt_age_s=days, conf_age_s=days)).grade,
                         vq.STALE)
        self.assertEqual(_grade(_quote(vt_age_s=days + 1,
                                       conf_age_s=days + 1)).grade,
                         vq.NONE)

    def test_the_grade_reads_no_clock_and_no_store(self):
        """Pure: the same inputs give the same answer, and `now` is an
        argument, never read."""
        vq = _vq()
        q = _quote(conf_age_s=20)
        self.assertEqual(_grade(q), _grade(q))
        with self.assertRaises(TypeError):
            vq.grade(q, asset_class="forex", **OPEN_HEALTHY)


class TheJumpTests(SimpleTestCase):

    def test_the_bars_are_mark_sanitys(self):
        vq = _vq()
        from bot_program.mark_sanity import JUMP_PCT
        for cls, bar in JUMP_PCT.items():
            base = Decimal("100")
            inside = base * (1 + Decimal(str(bar)))
            outside = base * (1 + Decimal(str(bar)) + Decimal("0.0001"))
            self.assertFalse(vq.is_jump(base, inside, cls), cls)
            self.assertTrue(vq.is_jump(base, outside, cls), cls)
            self.assertTrue(vq.is_jump(base, base * 2 - outside, cls), cls)
        self.assertFalse(vq.is_jump(None, Decimal("1"), "forex"))
        self.assertFalse(vq.is_jump(Decimal("1"), Decimal("9"), "options"))


# ── 4. authority (I1) ────────────────────────────────────────────────────

class TheAuthorityTests(SimpleTestCase):

    def test_a_verified_id_and_any_reason_make_etoro_the_authority(self):
        vq = _vq()
        for reason in ("open_row", "broker_position", "enabled_config",
                       "open_ticket", "watchlist"):
            with self.subTest(reason=reason):
                a = vq.authority(vq.AuthorityFacts(verified_id=True,
                                                   **{reason: True}),
                                 now=NOW)
                self.assertEqual(a.authority, "etoro")
                self.assertEqual(a.why, reason)
                self.assertEqual(a.last_reason_at, NOW)

    def test_without_a_verified_id_or_a_reason_it_is_reference(self):
        vq = _vq()
        self.assertEqual(vq.authority(vq.AuthorityFacts(open_row=True),
                                      now=NOW).authority, "reference")
        self.assertEqual(vq.authority(vq.AuthorityFacts(verified_id=True),
                                      now=NOW).authority, "reference")

    def test_leaving_needs_sixty_seconds_of_absence(self):
        vq = _vq()
        facts = vq.AuthorityFacts(verified_id=True)
        held = vq.authority(facts, now=NOW,
                            last_reason_at=NOW - timedelta(seconds=59))
        self.assertEqual(held.authority, "etoro")
        gone = vq.authority(facts, now=NOW,
                            last_reason_at=NOW - timedelta(seconds=60))
        self.assertEqual(gone.authority, "reference")

    def test_authority_never_takes_a_quote(self):
        """A source can never flap the authority: the function has no
        argument a quote could reach."""
        import inspect
        vq = _vq()
        params = set(inspect.signature(vq.authority).parameters)
        self.assertEqual(params, {"facts", "now", "last_reason_at"})
        self.assertEqual(set(vq.AuthorityFacts._fields), {
            "verified_id", "open_row", "broker_position", "enabled_config",
            "open_ticket", "watchlist"})


# ── 5. the screen never substitutes (I10, A1, A4) ────────────────────────

class TheDisplayTests(SimpleTestCase):

    def _ref(self, **kw):
        vq = _vq()
        return vq.ReferenceQuote("EURUSD", "oanda_stream", Decimal("1.1050"),
                                 NOW - timedelta(seconds=5), **kw)

    def test_the_main_cell_holds_etoros_numbers_only(self):
        vq = _vq()
        cell = _display(_quote("1.1000", "1.1002"), reference=self._ref(),
                        slot_shown=False)
        self.assertEqual((cell["bid"], cell["ask"], cell["mid"]),
                         ("1.1000", "1.1002", "1.1001"))
        self.assertEqual(cell["source"], "etoro")
        self.assertEqual(cell["grade"], vq.LIVE)
        self.assertEqual(cell["label"], "eToro · live")
        self.assertIsNone(cell["slot"], "the slot hidden: no outside quote")
        self.assertNotIn("1.1050", repr({k: v for k, v in cell.items()
                                         if k != "slot"}))

    def test_the_slot_follows_its_hysteresis_even_at_live(self):
        """§5.6: the slot hides only after eToro has been LIVE for 10 s, so
        while the hysteresis still shows it (`slot_shown`), it shows at
        LIVE too (2026-11-07, review: it was dropped at once) — always in
        its own labelled slot, never in the main cell."""
        vq = _vq()
        cell = _display(_quote("1.1000", "1.1002"), reference=self._ref(),
                        slot_shown=True)
        self.assertEqual(cell["grade"], vq.LIVE)
        self.assertEqual(cell["slot"]["source"], "oanda_stream")
        self.assertEqual((cell["bid"], cell["ask"]), ("1.1000", "1.1002"))

    def test_a_degraded_grade_says_its_age(self):
        vq = _vq()
        recent = _display(_quote(vt_age_s=30, conf_age_s=30))
        self.assertEqual(recent["grade"], vq.RECENT)
        self.assertEqual(recent["label"], "eToro · 30 s")
        self.assertTrue(recent["degraded"])
        stale = _display(_quote(vt_age_s=600, conf_age_s=600))
        self.assertEqual(stale["label"], "eToro · 10 min · feed down")
        live = _display(_quote())
        self.assertFalse(live["degraded"])

    def test_the_screen_shows_the_grade_it_is_handed(self):
        """2026-11-07, review: display_quote graded on its own defaults, so
        a stream that was down, untrusted, behind or showing an unconfirmed
        jump read "eToro · live". It is handed the record's Grade (I6), and
        degraded shows degraded at once (§5.6, H7)."""
        vq = _vq()
        q = _quote(conf_age_s=2)
        for kw in ({"ws_healthy": False}, {"ws_trusted": False},
                   {"behind": True}, {"unconfirmed_jump": True}):
            with self.subTest(kw=kw):
                cell = _display(q, **kw)
                self.assertEqual(cell["grade"], vq.RECENT)
                self.assertTrue(cell["degraded"])
                self.assertEqual(cell["label"], "eToro · 2 s")
        with self.assertRaises(TypeError):
            vq.display_quote(q, None, now=NOW)

    def test_closed_says_close_only_near_the_sessions_close(self):
        """2026-11-07, review: a last print from Wednesday 14:23 showed on
        Saturday as "closed · eToro close 14:23". It is the close only
        when it lies near the session's last close."""
        vq = _vq()
        wed = datetime(2026, 11, 4, 14, 23, tzinfo=dt_tz.utc)
        fri_close = datetime(2026, 11, 6, 22, 0, tzinfo=dt_tz.utc)
        sat = datetime(2026, 11, 7, 12, 0, tzinfo=dt_tz.utc)
        old = vq.VenueQuote(iid=1, bid="1.1", ask="1.1002", vt=wed,
                            channel="ws", arrival=wed)
        cell = _display(old, now=sat, session_open=False,
                        session_closed_at=fri_close)
        self.assertEqual(cell["grade"], vq.CLOSED)
        self.assertEqual(cell["label"],
                         "closed · eToro's last price Wed 04 Nov 14:23 · "
                         "2 days ago")
        last = fri_close - timedelta(seconds=40)
        close = vq.VenueQuote(iid=1, bid="1.1", ask="1.1002", vt=last,
                              channel="ws", arrival=last)
        self.assertEqual(_display(close, now=sat, session_open=False,
                                  session_closed_at=fri_close)["label"],
                         "closed · eToro close Fri 06 Nov 21:59")
        self.assertTrue(_display(close, now=sat, session_open=False)[
            "label"].startswith("closed · eToro's last price"),
            "with no known close, never called the close")

    def test_no_record_awaits_etoro_and_the_slot_is_labelled(self):
        cell = _display(None, reference=self._ref(), slot_shown=True)
        self.assertIsNone(cell["bid"])
        self.assertIsNone(cell["ask"])
        self.assertEqual(cell["label"], "awaiting eToro")
        self.assertEqual(cell["slot"]["source"], "oanda_stream")
        self.assertEqual(cell["slot"]["price"], "1.1050")
        self.assertEqual(cell["slot"]["age_s"], 5)
        hidden = _display(None, reference=self._ref(), slot_shown=False)
        self.assertIsNone(hidden["slot"])

    def test_the_slot_carries_its_gap_and_a_stand_in_says_so(self):
        vq = _vq()
        cell = _display(_quote("1.1000", "1.1002", vt_age_s=900,
                               conf_age_s=900),
                        reference=self._ref(), slot_shown=True)
        self.assertEqual(cell["slot"]["gap_pct"], "0.45")
        fut = vq.ReferenceQuote("XAUUSD", "yfinance", Decimal("2010"), NOW,
                                stand_in="future")
        cell = _display(None, asset_class="commodity", reference=fut,
                        slot_shown=True)
        self.assertIn("future, different instrument", cell["slot"]["label"])


class TheReferenceWrapperTests(SimpleTestCase):

    def _row(self, source, last="1.1001", age_s=5, bid=None, ask=None):
        class Row:
            pass
        r = Row()
        r.source, r.last, r.bid, r.ask = source, Decimal(last), bid, ask
        r.updated_at = NOW - timedelta(seconds=age_s)
        return r

    def test_an_outside_row_becomes_a_reference(self):
        vq = _vq()
        ref = vq.reference_quote(self._row("oanda_stream"), symbol="EURUSD")
        self.assertIsInstance(ref, vq.ReferenceQuote)
        self.assertEqual(ref.source, "oanda_stream")
        self.assertTrue(ref.qualifies(NOW))

    def test_an_etoro_written_row_is_never_a_reference(self):
        vq = _vq()
        self.assertIsNone(vq.reference_quote(self._row("etoro"),
                                             symbol="EURUSD"))
        self.assertIsNone(vq.reference_quote(None, symbol="EURUSD"))
        self.assertIsNone(vq.reference_quote(self._row("yfinance", last="0"),
                                             symbol="EURUSD"))


# ── 6. the one venue-source rule (§3.2 item 3, harm 27) ──────────────────

class TheVenueSourceRuleTests(SimpleTestCase):
    """The rule itself; the side-by-side table against today's three tests
    is tests/feed/test_venue_source_one_rule.py."""

    def test_the_channel_reading_is_the_specs_rule(self):
        vq = _vq()
        for s in ("etoro", "ETORO", " eToro ", "etoro_ws", "etoro_rest",
                  "etoro-legacy"):
            self.assertTrue(vq.is_venue_source(s), s)
        for s in (None, "", "etorox", "yfinance", "oanda_stream", "xetoro",
                  "etor"):
            self.assertFalse(vq.is_venue_source(s), s)

    def test_the_exact_and_prefix_readings(self):
        vq = _vq()
        self.assertTrue(vq.is_venue_source("ETORO", reading=vq.EXACT))
        self.assertFalse(vq.is_venue_source("etoro_ws", reading=vq.EXACT))
        self.assertFalse(vq.is_venue_source(" etoro", reading=vq.EXACT))
        self.assertTrue(vq.is_venue_source("ibkr", "IBKR", reading=vq.EXACT))
        self.assertTrue(vq.is_venue_source("etorox", reading=vq.PREFIX))
        self.assertFalse(vq.is_venue_source(" etoro", reading=vq.PREFIX))
        self.assertFalse(vq.is_venue_source("etoro", "", reading=vq.EXACT))
        with self.assertRaises(ValueError):
            vq.is_venue_source("etoro", reading="fuzzy")


# ── 7. the session rule (§5.5) ───────────────────────────────────────────

def _utc(*parts):
    return datetime(*parts, tzinfo=dt_tz.utc)


class TheSessionTests(SimpleTestCase):

    def _s(self, cls, symbol, when, **kw):
        from market_data import venue_session
        return venue_session.session(cls, symbol, now=when, **kw)

    def test_forex_midweek_is_open_for_both(self):
        s = self._s("forex", "EURUSD", _utc(2026, 11, 4, 12, 0))
        self.assertTrue(s.protection_open)
        self.assertTrue(s.entries_open)
        self.assertEqual(s.words, "")

    def test_the_weekend_is_shut_for_both(self):
        s = self._s("forex", "EURUSD", _utc(2026, 11, 7, 12, 0))
        self.assertFalse(s.protection_open)
        self.assertFalse(s.entries_open)

    def test_the_winter_break_window_refuses_entries_only(self):
        """New York 17:00 is 22:00 UTC in winter: entries refuse for five
        minutes there, protection is untouched."""
        s = self._s("forex", "EURUSD", _utc(2026, 11, 4, 22, 2))
        self.assertTrue(s.protection_open)
        self.assertFalse(s.entries_open)
        self.assertTrue(s.in_break_window)
        after = self._s("forex", "EURUSD", _utc(2026, 11, 4, 22, 6))
        self.assertFalse(after.in_break_window)
        self.assertTrue(after.protection_open)
        self.assertFalse(after.entries_open, "the settle after the break")
        self.assertEqual(after.words, "settling after the daily break")
        settled = self._s("forex", "EURUSD", _utc(2026, 11, 4, 22, 10, 1))
        self.assertTrue(settled.entries_open)
        self.assertEqual(settled.words, "")

    def test_both_summer_candidate_windows_refuse_entries_until_measured(self):
        from market_data import venue_session
        self.assertEqual(dict(venue_session.MEASURED_BREAKS), {})
        for hour in (21, 22):
            with self.subTest(hour=hour):
                s = self._s("forex", "EURUSD", _utc(2026, 7, 8, hour, 2))
                self.assertTrue(s.protection_open)
                self.assertFalse(s.entries_open)
                self.assertTrue(s.in_break_window)
        self.assertTrue(self._s("forex", "EURUSD",
                                _utc(2026, 7, 8, 21, 30)).entries_open)

    def test_the_sunday_reopen_settles_entries(self):
        """The weekly open (22:00 UTC in winter) is a reopen and a daily
        break window at once: entries wait for the window and the settle
        after it; protection is open from the first minute."""
        s = self._s("forex", "EURUSD", _utc(2026, 11, 8, 22, 2))
        self.assertTrue(s.protection_open)
        self.assertFalse(s.entries_open)
        self.assertTrue(s.settling)
        mid = self._s("forex", "EURUSD", _utc(2026, 11, 8, 22, 6))
        self.assertTrue(mid.protection_open)
        self.assertFalse(mid.entries_open)
        later = self._s("forex", "EURUSD", _utc(2026, 11, 8, 22, 11))
        self.assertTrue(later.entries_open)

    def test_the_daily_break_settles_entries_as_a_reopen(self):
        """Decided 2026-11-07 (the review of F1; §5.5 leaves it open): the
        minutes after eToro's daily rollover carry its widest spreads, so
        entries settle after each break window as after a reopen; a
        commodity's daily reopen already settles through market_clock.
        Protection never waits on it. Summer, unmeasured: both candidate
        windows settle."""
        for hour in (21, 22):
            with self.subTest(hour=hour):
                s = self._s("forex", "EURUSD", _utc(2026, 7, 8, hour, 7))
                self.assertTrue(s.protection_open)
                self.assertFalse(s.entries_open)
                self.assertFalse(s.in_break_window)
                self.assertTrue(s.settling)
        self.assertTrue(self._s("forex", "EURUSD",
                                _utc(2026, 7, 8, 21, 11)).entries_open)
        gold = self._s("commodity", "XAUUSD", _utc(2026, 11, 4, 23, 2))
        self.assertTrue(gold.settling, "market_clock's daily reopen")

    def test_crypto_never_shuts_and_never_settles(self):
        for when in (_utc(2026, 11, 7, 12, 0), _utc(2026, 11, 4, 22, 2)):
            s = self._s("crypto", "BTCUSD", when)
            self.assertTrue(s.protection_open)
            self.assertTrue(s.entries_open)

    def test_etoros_flag_is_ignored_until_proven(self):
        from market_data import venue_session
        self.assertFalse(venue_session.ETORO_OPEN_PROVEN)
        s = self._s("forex", "EURUSD", _utc(2026, 11, 4, 12, 0),
                    etoro_open=False)
        self.assertTrue(s.entries_open)
        self.assertEqual(s.words, "")

    def test_once_proven_the_rule_is_asymmetric(self):
        """Protection: either source says open. Entries: both, and the
        settle passed. The screen says which source disagrees."""
        from unittest import mock
        from market_data import venue_session
        with mock.patch.object(venue_session, "ETORO_OPEN_PROVEN", True):
            shut_clock = self._s("forex", "EURUSD", _utc(2026, 11, 7, 12, 0),
                                 etoro_open=True)
            self.assertTrue(shut_clock.protection_open)
            self.assertFalse(shut_clock.entries_open)
            self.assertEqual(shut_clock.words, "eToro says open")
            shut_venue = self._s("forex", "EURUSD", _utc(2026, 11, 4, 12, 0),
                                 etoro_open=False)
            self.assertTrue(shut_venue.protection_open)
            self.assertFalse(shut_venue.entries_open)
            self.assertEqual(shut_venue.words, "eToro says closed")
            both = self._s("forex", "EURUSD", _utc(2026, 11, 4, 12, 0),
                           etoro_open=True)
            self.assertTrue(both.entries_open)

    def test_once_proven_an_unknown_flag_is_not_a_yes_for_entries(self):
        """2026-11-07, review: once proven, an unknown eToro flag (None) let
        entries through on the clock alone. §5.5: entries only when both
        sources say open. Protection still follows the clock."""
        from unittest import mock
        from market_data import venue_session
        with mock.patch.object(venue_session, "ETORO_OPEN_PROVEN", True):
            s = self._s("forex", "EURUSD", _utc(2026, 11, 4, 12, 0),
                        etoro_open=None)
            self.assertTrue(s.protection_open)
            self.assertFalse(s.entries_open)
            self.assertIsNone(s.etoro_open)
            self.assertEqual(s.words, "eToro's open flag unknown")

    def test_the_market_clock_itself_is_not_changed(self):
        from core import exchange_status
        from market_data import venue_session
        self.assertIs(venue_session.market_clock, exchange_status.market_clock)
