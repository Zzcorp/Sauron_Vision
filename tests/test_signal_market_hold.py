"""The market clock behind a signal's announcement (2026-11-12).

The operator, 2026-11-11: signals were announced while their market was
shut ("please fix it"). Nothing that wrote, announced or showed a signal
asked the market clock; the bots, the paper venue, Morgul and the ticket
already did.

signals/market_hold.py is the one place a signal's announcement and its
card ask "can this instrument trade now": market_state(instrument), on
core.exchange_status.market_clock, with the classes on which the bots
already refuse a shut market (entry_timing.SHUT_CLASSES) and the bots'
own settling quarter hour (entry_timing.OPEN_SETTLE_MINUTES). It adds no
clock of its own.

Pinned here, at fixed instants (November for winter hours, July for
summer), with no database:
  * crypto and an unmodelled class never read shut; a clock that cannot
    be read holds nothing and says so at WARNING;
  * forex, a US share (a holiday and an early close among them), gold on
    COMEX and an index: shut, settling and open, with the hour the market
    opens and the hour it can be traded;
  * an index is shut only while its cash session AND the CME futures week
    are both shut;
  * the class set and the settle are the bots' own;
  * the label a shut market is announced with: "market shut · opens Sun
    22:00 UTC", "market shut" alone when the clock does not know the hour,
    nothing while the market is open (its first quarter hour included);
  * GATE off (the suite's default, tests/__init__.py): nothing reads shut.

THE OPTIONAL HOLD (the switch signal_market_hold, OFF on arrival), with a
test database: at birth (cases 9 to 13: held on a shut market from every
creator; announced as today with the switch off, with no row, and when
the hold cannot be written), at the open (14 to 23: wait, release once,
drop with a named reason, best score first), and that nothing else moved
(24 to 28: every engine row, the bots' decisions, the grade, the guard on
the engine's files, the lifecycle task).

Run with:  python manage.py test tests.test_signal_market_hold
"""
import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

UTC = dt_timezone.utc


def _t(*parts):
    return datetime(*parts, tzinfo=UTC)


#: Winter hours (the US clocks changed on 2026-11-01).
SAT_0005 = _t(2026, 11, 7, 0, 5)
SAT_NOON = _t(2026, 11, 7, 12, 0)
SUN_2130 = _t(2026, 11, 8, 21, 30)
SUN_2205 = _t(2026, 11, 8, 22, 5)
SUN_2220 = _t(2026, 11, 8, 22, 20)
SUN_OPEN = _t(2026, 11, 8, 22, 0)
MON_0900 = _t(2026, 11, 9, 9, 0)
MON_1000 = _t(2026, 11, 9, 10, 0)
MON_BELL = _t(2026, 11, 9, 14, 30)
TUE_0300 = _t(2026, 11, 10, 3, 0)
TUE_2230 = _t(2026, 11, 10, 22, 30)
THANKSGIVING = _t(2026, 11, 26, 15, 0)
EARLY_CLOSE = _t(2026, 11, 27, 18, 30)
#: Summer hours.
JUL_SAT = _t(2026, 7, 11, 0, 5)
JUL_SUN_2030 = _t(2026, 7, 12, 20, 30)
JUL_SUN_2105 = _t(2026, 7, 12, 21, 5)
JUL_SUN_2120 = _t(2026, 7, 12, 21, 20)
JUL_OPEN = _t(2026, 7, 12, 21, 0)

QUARTER = timedelta(minutes=15)


def _inst(symbol, asset_class, exchange=""):
    """An instrument as market_state reads it: three attributes."""
    return SimpleNamespace(symbol=symbol, asset_class=asset_class,
                           exchange=exchange)


EURUSD = _inst("EURUSD", "forex")
AAPL = _inst("AAPL", "stock", "NASDAQ")
SPY = _inst("SPY", "etf", "NYSE")
XAUUSD = _inst("XAUUSD", "commodity", "COMEX")
SPX500 = _inst("SPX500", "index")
BTCUSD = _inst("BTCUSD", "crypto")


@contextmanager
def _at(when, gate=True):
    """The wall clock fixed at `when`, and the gate ON (the suite runs
    with it off, tests/__init__.py)."""
    from signals import market_hold
    with patch("django.utils.timezone.now", return_value=when), \
            patch.object(market_hold, "GATE", gate):
        yield


def _state(inst, when, gate=True):
    from signals.market_hold import market_state
    with _at(when, gate):
        return market_state(inst)


class TheClockTests(SimpleTestCase):
    def test_1_crypto_on_a_saturday_is_never_held(self):
        st = _state(BTCUSD, SAT_NOON)
        self.assertEqual((st["state"], st["tradeable"]), ("always", True))
        self.assertEqual((st["label"], st["words"]), ("", ""))

    def test_2_forex_over_the_weekend_in_winter(self):
        st = _state(EURUSD, SAT_0005)
        self.assertEqual((st["state"], st["tradeable"]), ("shut", False))
        self.assertEqual(st["reopens"], SUN_OPEN)
        self.assertEqual(st["tradeable_at"], SUN_OPEN + QUARTER)
        self.assertEqual(st["session"], "FOREX")
        self.assertIn("opens Sunday 22:00 UTC", st["words"])
        # Sunday 21:30: the UTC row reads open, the New York week does not
        st = _state(EURUSD, SUN_2130)
        self.assertEqual((st["state"], st["reopens"]), ("shut", SUN_OPEN))
        st = _state(EURUSD, SUN_2205)
        self.assertEqual((st["state"], st["tradeable"]), ("settling", False))
        self.assertEqual(st["opened"], SUN_OPEN)
        self.assertEqual(st["tradeable_at"], SUN_OPEN + QUARTER)
        self.assertIsNone(st["reopens"])
        st = _state(EURUSD, SUN_2220)
        self.assertEqual((st["state"], st["tradeable"]), ("open", True))
        self.assertEqual(st["opened"], SUN_OPEN)
        self.assertEqual(st["words"], "")

    def test_2_forex_over_the_weekend_in_summer(self):
        st = _state(EURUSD, JUL_SAT)
        self.assertEqual((st["state"], st["reopens"]), ("shut", JUL_OPEN))
        self.assertEqual(st["tradeable_at"], JUL_OPEN + QUARTER)
        self.assertEqual(_state(EURUSD, JUL_SUN_2030)["state"], "shut")
        self.assertEqual(_state(EURUSD, JUL_SUN_2105)["state"], "settling")
        self.assertEqual(_state(EURUSD, JUL_SUN_2120)["state"], "open")

    def test_3_a_us_share_before_the_bell_on_a_holiday_and_after_an_early_close(
            self):
        st = _state(AAPL, MON_0900)
        self.assertEqual((st["state"], st["reopens"]), ("shut", MON_BELL))
        self.assertEqual(st["tradeable_at"], MON_BELL + QUARTER)
        self.assertEqual(_state(AAPL, MON_BELL + timedelta(minutes=5))["state"],
                         "settling")
        self.assertEqual(_state(AAPL, MON_BELL + timedelta(minutes=20))["state"],
                         "open")
        # Thanksgiving: shut all day, until Friday's bell
        st = _state(AAPL, THANKSGIVING)
        self.assertEqual((st["state"], st["reopens"]),
                         ("shut", _t(2026, 11, 27, 14, 30)))
        # the Friday after: the 13:00 New York close has passed
        st = _state(AAPL, EARLY_CLOSE)
        self.assertEqual((st["state"], st["reopens"]),
                         ("shut", _t(2026, 11, 30, 14, 30)))
        # an ETF reads its venue the same way
        self.assertEqual(_state(SPY, MON_0900)["reopens"], MON_BELL)

    def test_4_gold_in_the_daily_break(self):
        st = _state(XAUUSD, TUE_2230)
        self.assertEqual((st["state"], st["reopens"]),
                         ("shut", _t(2026, 11, 10, 23, 0)))
        self.assertEqual(st["session"], "CME")

    def test_5_an_index_is_shut_only_when_cash_and_futures_both_are(self):
        # Tuesday 03:00 UTC: New York's cash session is shut, the futures
        # week is open, and the broker's index CFD trades
        st = _state(SPX500, TUE_0300)
        self.assertEqual((st["state"], st["tradeable"]), ("open", True))
        self.assertEqual(st["label"], "")
        # Saturday: both shut; the futures week opens first
        st = _state(SPX500, SAT_NOON)
        self.assertEqual((st["state"], st["tradeable"]), ("shut", False))
        self.assertEqual(st["reopens"], _t(2026, 11, 8, 23, 0))
        self.assertIn("opens Sunday 23:00 UTC", st["words"])
        # the futures' daily break, the cash session shut as well
        st = _state(SPX500, TUE_2230)
        self.assertEqual((st["state"], st["reopens"]),
                         ("shut", _t(2026, 11, 10, 23, 0)))
        # an index that is not American: said as an approximation
        st = _state(_inst("DAX40", "index"), SAT_NOON)
        self.assertEqual(st["state"], "shut")
        self.assertIn("approximation", st["words"])
        self.assertNotIn("approximation", _state(SPX500, SAT_NOON)["words"])

    def test_6_an_unmodelled_class_and_an_unread_clock_hold_nothing(self):
        for cls in ("cfd", "bond", "options", "", "something_new"):
            with self.subTest(asset_class=cls):
                st = _state(_inst("ANY", cls), SAT_NOON)
                self.assertEqual((st["state"], st["tradeable"]),
                                 ("unmodelled", True))
                self.assertEqual(st["label"], "")
        with patch("signals.market_hold.market_clock",
                   side_effect=RuntimeError("no calendar")), \
                self.assertLogs("signals.market_hold", "WARNING") as logs:
            st = _state(EURUSD, SAT_NOON)
        self.assertEqual((st["state"], st["tradeable"]), ("unmodelled", True))
        self.assertEqual(st["label"], "")
        self.assertIn("EURUSD", logs.output[0])
        # an instrument that carries nothing at all
        self.assertTrue(_state(SimpleNamespace(), SAT_NOON)["tradeable"])
        self.assertTrue(_state(None, SAT_NOON)["tradeable"])

    def test_7_the_classes_and_the_settle_are_the_bots_own(self):
        from bot_program import entry_timing
        from signals import market_hold
        self.assertEqual(market_hold.HOLD_CLASSES, entry_timing.SHUT_CLASSES)
        self.assertEqual(market_hold.SETTLE_MINUTES,
                         entry_timing.OPEN_SETTLE_MINUTES)
        self.assertEqual(market_hold.SETTLE,
                         timedelta(minutes=entry_timing.OPEN_SETTLE_MINUTES))

    def test_8_the_gate_off_holds_nothing(self):
        for inst in (EURUSD, AAPL, XAUUSD, SPX500, BTCUSD):
            with self.subTest(symbol=inst.symbol):
                st = _state(inst, SAT_NOON, gate=False)
                self.assertEqual((st["state"], st["tradeable"]), ("off", True))
                self.assertEqual((st["label"], st["words"]), ("", ""))

    def test_the_suite_runs_with_the_gate_off(self):
        """tests/__init__.py: without it a test that announces a signal
        would read the hour it runs at."""
        from signals import market_hold
        self.assertIs(market_hold.GATE, False)

    def test_an_explicit_moment_is_read_instead_of_the_wall_clock(self):
        from signals.market_hold import market_state
        with _at(MON_1000):
            self.assertEqual(market_state(EURUSD)["state"], "open")
            self.assertEqual(market_state(EURUSD, now=SAT_NOON)["state"],
                             "shut")


class TheLabelTests(SimpleTestCase):
    """What a shut market is announced with, on every channel and card."""

    def _label(self, inst, when, gate=True):
        from signals.market_hold import shut_label
        with _at(when, gate):
            return shut_label(inst)

    def test_a_shut_market_says_so_with_the_hour_it_opens(self):
        self.assertEqual(self._label(EURUSD, SAT_NOON),
                         "market shut · opens Sun 22:00 UTC")
        self.assertEqual(self._label(AAPL, MON_0900),
                         "market shut · opens Mon 14:30 UTC")
        self.assertEqual(self._label(AAPL, THANKSGIVING),
                         "market shut · opens Fri 14:30 UTC")
        self.assertEqual(self._label(XAUUSD, TUE_2230),
                         "market shut · opens Tue 23:00 UTC")
        self.assertEqual(self._label(SPX500, SAT_NOON),
                         "market shut · opens Sun 23:00 UTC")
        self.assertEqual(self._label(EURUSD, JUL_SAT),
                         "market shut · opens Sun 21:00 UTC")

    def test_the_state_carries_the_two_halves_of_the_label(self):
        st = _state(EURUSD, SAT_NOON)
        self.assertEqual(st["label"], "market shut · opens Sun 22:00 UTC")
        self.assertEqual(st["opens"], "opens Sun 22:00 UTC")

    def test_an_open_market_says_nothing(self):
        for inst, when in ((EURUSD, MON_1000), (BTCUSD, SAT_NOON),
                           (SPX500, TUE_0300),
                           (AAPL, MON_BELL + timedelta(minutes=20))):
            with self.subTest(symbol=inst.symbol):
                self.assertEqual(self._label(inst, when), "")

    def test_the_first_quarter_hour_is_an_open_market(self):
        """Settling is the hold's word (the announcement may wait for a
        market price); the market is open, so nothing says shut."""
        self.assertEqual(_state(EURUSD, SUN_2205)["state"], "settling")
        self.assertEqual(self._label(EURUSD, SUN_2205), "")
        self.assertEqual(_state(EURUSD, SUN_2205)["label"], "")

    def test_an_unknown_reopening_says_only_market_shut(self):
        clock = {"is_open": False, "session": "FOREX", "modelled": True,
                 "reopens": None, "reopens_words": "", "opened": None,
                 "closed": None}
        with patch("signals.market_hold.market_clock", return_value=clock):
            self.assertEqual(self._label(EURUSD, SAT_NOON), "market shut")
            st = _state(EURUSD, SAT_NOON)
        self.assertEqual((st["state"], st["opens"]), ("shut", ""))
        self.assertIsNone(st["tradeable_at"])

    def test_a_label_never_raises(self):
        from signals.market_hold import shut_label
        with patch("signals.market_hold.market_state",
                   side_effect=RuntimeError("boom")), \
                self.assertLogs("signals.market_hold", "WARNING"):
            with _at(SAT_NOON):
                self.assertEqual(shut_label(EURUSD), "")

    def test_the_gate_off_says_nothing(self):
        self.assertEqual(self._label(EURUSD, SAT_NOON, gate=False), "")

    def test_the_weekday_is_from_a_fixed_table(self):
        """No locale can change the words (core.exchange_status.utc_words
        does the same with the long names)."""
        from signals.market_hold import opens_words
        days = [opens_words(_t(2026, 11, 9 + i, 7, 5)) for i in range(7)]
        self.assertEqual(days, [
            "Mon 07:05 UTC", "Tue 07:05 UTC", "Wed 07:05 UTC",
            "Thu 07:05 UTC", "Fri 07:05 UTC", "Sat 07:05 UTC",
            "Sun 07:05 UTC"])
        # another zone's instant is said in UTC
        paris = dt_timezone(timedelta(hours=1))
        self.assertEqual(opens_words(datetime(2026, 11, 9, 0, 30, tzinfo=paris)),
                         "Sun 23:30 UTC")


# ═════════════════════════════════════════════════════════════════════════
# THE OPTIONAL HOLD (2026-11-12, the switch signal_market_hold, OFF on
# arrival). On: a signal born while its market cannot trade is written
# exactly as today and its announcement waits for the open; a pass every
# five minutes then announces it once, if it is still active, under 24
# hours old and the first price of the session leaves its plan valid, or
# drops it with a named reason. Off (the default): every signal is
# announced at birth, a shut market's with its label (above).
# ═════════════════════════════════════════════════════════════════════════

SUN_0900 = _t(2026, 11, 8, 9, 0)
SUN_2210 = _t(2026, 11, 8, 22, 10)
SUN_2217 = _t(2026, 11, 8, 22, 17)
SUN_2225 = _t(2026, 11, 8, 22, 25)
SUN_2240 = _t(2026, 11, 8, 22, 40)
SUN_2250 = _t(2026, 11, 8, 22, 50)
SWITCH = "signal_market_hold"
FIRED = "fired Sunday 09:00 UTC, while its market was shut"
TOKEN = "123456:market-hold-test-token"
ENV = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "-100999",
       "DOMAIN": ""}


def _db_inst(symbol, asset_class="forex", exchange=""):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "exchange": exchange, "is_active": True})
    return inst


def _sig(inst, born, *, rule="mh_rule", direction="bearish", score=0.55,
         entry="1.08500", stop="1.09000", target="1.07500", active=True):
    """A synthetic signal whose created_at is `born`. Bearish by default:
    entry 1.08500, stop 1.09000 above, target 1.07500 below (2.00 to 1)."""
    from signals.models import Signal
    s = Signal.objects.create(
        instrument=inst, signal_type="technical", direction=direction,
        urgency="medium", title=f"MACD cross on {inst.symbol}",
        description="d", rule_name=rule, score=score, sub_scores={},
        price_at_signal=Decimal(entry), suggested_entry=Decimal(entry),
        suggested_stop=None if stop is None else Decimal(stop),
        suggested_target=None if target is None else Decimal(target),
        risk_reward_ratio=2.0, is_active=active)
    Signal.objects.filter(pk=s.pk).update(created_at=born)
    return Signal.objects.select_related("instrument").get(pk=s.pk)


def _switch(on=True):
    from core.platform_control import PlatformComponent
    PlatformComponent.objects.update_or_create(
        key=SWITCH, defaults={"name": "Signal Market Hold",
                              "category": "pipeline", "is_enabled": on})


def _quote(inst, last, at):
    from market_data.models import LiveQuote
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "test"})
    LiveQuote.objects.filter(instrument=inst).update(updated_at=at)


def _bar(inst, opened_at, close, timeframe="1h"):
    from market_data.models import PriceData
    px = Decimal(str(close))
    PriceData.objects.create(instrument=inst, timeframe=timeframe,
                             timestamp=opened_at, open=px, high=px, low=px,
                             close=px, volume=0, source="test")


def _holds(**filters):
    from signals.models import SignalHold
    return list(SignalHold.objects.filter(**filters).order_by("pk"))


def _hold_of(sig):
    from signals.models import SignalHold
    return SignalHold.objects.get(signal=sig)


class _Heard:
    """What an announcement did, step by step."""

    def __init__(self):
        self.steps = []          # ("banner"|"bell"|"channels", signal pk)
        self.banners = []        # the payloads pushed
        self.notes = []          # the note each channels call carried
        self.dispatch = MagicMock(side_effect=self._channels)

    def push(self, user, kind, payload):
        if kind == "new_signal":
            self.steps.append(("banner", payload["signal_id"]))
            self.banners.append(dict(payload))
        return True

    def _channels(self, signal, note=""):
        self.steps.append(("channels", signal.pk))
        self.notes.append(note)
        return {"chats": 1, "sent": 1, "held": 0, "refused": 0}

    @property
    def said(self):
        return bool(self.steps) or self.dispatch.called


@contextmanager
def _listening(when, gate=True):
    """The clock fixed at `when`, the banner captured, the channels step
    replaced by a recorder; the bell writes its real rows."""
    heard = _Heard()
    with _at(when, gate), \
            patch("dashboard.consumers.push_eye_event",
                  side_effect=heard.push), \
            patch("alerts.dispatch.dispatch_signal_alert", heard.dispatch):
        yield heard


def _bells():
    from alerts.models import Notification
    return [(n.title, n.body) for n in Notification.objects.order_by("pk")]


def _announce(sig, when, gate=True):
    from signals.announce import announce_new_signal
    with _listening(when, gate) as heard:
        heard.out = announce_new_signal(sig)
    return heard


def _release(when, gate=True):
    from signals.market_hold import release_due
    with _listening(when, gate) as heard:
        heard.out = release_due()
    return heard


class _HoldBase(TestCase):
    def setUp(self):
        cache.clear()
        env = patch.dict(os.environ, ENV)
        env.start()
        self.addCleanup(env.stop)
        self.staff = User.objects.create_user("mh_staff", password="x",
                                              is_staff=True)
        self.inst = _db_inst("EURUSD")
        _switch(True)

    def _held(self, inst=None, born=SUN_0900, **kw):
        """A signal born at `born` on a shut market, its announcement
        held; nothing was said."""
        sig = _sig(inst or self.inst, born, **kw)
        heard = _announce(sig, born)
        self.assertFalse(heard.said, heard.steps)
        self.assertIn("held", heard.out)
        return sig


class AtBirthTests(_HoldBase):
    def test_9_a_forex_signal_born_on_saturday_is_held(self):
        sig = _sig(self.inst, SAT_NOON)
        heard = _announce(sig, SAT_NOON)
        self.assertFalse(heard.said, heard.steps)
        heard.dispatch.assert_not_called()
        self.assertEqual(_bells(), [])
        hold = _hold_of(sig)
        self.assertEqual((hold.state, hold.reason), ("held", "market_shut"))
        self.assertEqual(hold.reopens_at, SUN_OPEN)
        self.assertEqual(hold.held_at, SAT_NOON)
        self.assertIsNone(hold.decided_at)
        self.assertIsNone(hold.mark)
        self.assertEqual(hold.words, "the forex market is shut: it opens "
                                     "Sunday 22:00 UTC")
        self.assertEqual(heard.out, {"signal_id": sig.pk,
                                     "held": hold.words})
        self.assertEqual(len(_holds()), 1)

    def test_10_a_forex_signal_born_on_monday_is_announced_in_the_engines_order(
            self):
        """The assertions of tests/test_signal_announce.py, the switch on:
        the birth path keeps its two one-argument calls."""
        from signals.announce import announce_new_signal
        calls = []

        def push(user, kind, payload):
            calls.append(("banner", kind, payload["symbol"]))
            return True

        def bell(signal):
            calls.append(("bell", signal.pk))

        def channels(signal):
            calls.append(("channels", signal.pk))
            return {"chats": 0, "sent": 0, "held": 0, "refused": 0}

        sig = _sig(self.inst, MON_1000)
        with _at(MON_1000), \
                patch("dashboard.consumers.push_eye_event", side_effect=push), \
                patch("alerts.notify.notify_new_signal", side_effect=bell), \
                patch("alerts.dispatch.dispatch_signal_alert",
                      side_effect=channels):
            out = announce_new_signal(sig)
        self.assertEqual(calls, [("banner", "new_signal", "EURUSD"),
                                 ("bell", sig.pk), ("channels", sig.pk)])
        self.assertEqual((out["banner"], out["bell"]), (1, "ok"))
        self.assertEqual(out["channels"]["chats"], 0)
        self.assertNotIn("held", out)
        self.assertEqual(_holds(), [])

    def test_a_signal_born_in_the_first_quarter_hour_is_held_as_settling(self):
        sig = _sig(self.inst, SUN_2205)
        heard = _announce(sig, SUN_2205)
        self.assertFalse(heard.said)
        hold = _hold_of(sig)
        self.assertEqual((hold.state, hold.reason),
                         ("held", "market_settling"))
        self.assertIsNone(hold.reopens_at)
        self.assertIn("first quarter hour", hold.words)

    def test_crypto_and_an_open_market_are_never_held(self):
        btc = _sig(_db_inst("BTCUSD", "crypto"), SAT_NOON,
                   direction="bullish", entry="60000", stop="58000",
                   target="64000")
        self.assertTrue(_announce(btc, SAT_NOON).said)
        spx = _sig(_db_inst("SPX500", "index"), TUE_0300,
                   direction="bullish", entry="5000", stop="4900",
                   target="5200")
        self.assertTrue(_announce(spx, TUE_0300).said)
        self.assertEqual(_holds(), [])

    def test_a_second_announcement_of_a_held_signal_stays_held(self):
        sig = self._held(born=SAT_NOON)
        again = _announce(sig, SAT_NOON + timedelta(minutes=1))
        self.assertFalse(again.said)
        self.assertIn("held", again.out)
        self.assertEqual(len(_holds()), 1)

    # ── 11: every creator ────────────────────────────────────────────

    def _nothing_said_and_held(self, heard, signal_id):
        from signals.models import Signal
        self.assertTrue(Signal.objects.filter(pk=signal_id,
                                              is_active=True).exists())
        self.assertFalse(heard.said, heard.steps)
        self.assertEqual(_bells(), [])
        self.assertEqual([(h.signal_id, h.state, h.reason) for h in _holds()],
                         [(signal_id, "held", "market_shut")])

    def test_11_the_rule_engine_goes_through_the_hold(self):
        from signals.models import Signal
        from signals.tasks import _create_signals_and_notify
        payload = {"symbol": "EURUSD", "rule": "golden_cross",
                   "direction": "LONG", "score": 0.8, "headline": "h",
                   "thesis": "t", "entry": 1.085, "stop": 1.08,
                   "target": 1.095}
        with _listening(SAT_NOON) as heard:
            self.assertEqual(_create_signals_and_notify([payload]), 1)
        self._nothing_said_and_held(
            heard, Signal.objects.get(rule_name="golden_cross").pk)

    def _setup(self):
        from signals.models import OpportunitySetup
        _bar(self.inst, SAT_NOON - timedelta(hours=1), "1.08500", "1d")
        return OpportunitySetup.objects.create(
            name="mh_setup", direction="bullish", conditions=[],
            min_match_score=0.0, suggested_horizon_days=5, asset_classes=[],
            sizing={"stop_pct": 2.0, "target_rr": 2.0}, is_active=True)

    def test_11_a_live_scanner_pass_goes_through_the_hold(self):
        from signals.opportunity_scanner import scan_setup
        setup = self._setup()
        with _listening(SAT_NOON) as heard:
            out = scan_setup(setup, self.inst, as_of=False)
        self.assertTrue(out["matched"])
        self._nothing_said_and_held(heard, out["signal_id"])

    def test_12_the_scanners_reuse_branch_writes_no_second_hold(self):
        from signals.models import OpportunityFlag
        from signals.opportunity_scanner import scan_setup
        setup = self._setup()
        with _listening(SAT_NOON):
            first = scan_setup(setup, self.inst, as_of=False)
        with _listening(SUN_0900) as heard:
            second = scan_setup(setup, self.inst, as_of=False)
        self.assertEqual(first["signal_id"], second["signal_id"])
        self.assertEqual(OpportunityFlag.objects.count(), 2)
        self._nothing_said_and_held(heard, first["signal_id"])
        self.assertEqual(_hold_of(first["signal_id"]).held_at, SAT_NOON)

    def test_11_the_tradingview_task_goes_through_the_hold(self):
        from signals import tasks
        sig = _sig(self.inst, SAT_NOON, rule="tradingview:squeeze")
        with _listening(SAT_NOON) as heard:
            out = tasks.announce_signal(sig.pk)
        self.assertEqual(out["status"], "ok")
        self.assertIn("held", out)
        self._nothing_said_and_held(heard, sig.pk)

    def test_11_a_fast_rule_goes_through_the_hold_and_the_admin_button_does_not(
            self):
        from signals.fast_rules import (FastRule, SignalSpec, dispatch_event,
                                        register_default_rules,
                                        register_fast_rule, reset_fast_rules)
        reset_fast_rules()

        def restore():
            reset_fast_rules()
            register_default_rules()

        self.addCleanup(restore)

        class _Always(FastRule):
            rule_name = "mh_fast_rule"
            event_types = ["mh_evt"]
            cooldown_seconds = 0

            def evaluate(self, event_type, payload):
                from instruments.models import Instrument
                inst = Instrument.objects.get(symbol=payload["symbol"])
                return SignalSpec(instrument=inst, direction="bullish",
                                  score=0.8, price=1.085, stop=1.08,
                                  target=1.095)

        register_fast_rule(_Always())
        with _listening(SAT_NOON) as heard:
            out = dispatch_event("mh_evt", {"symbol": "EURUSD"})
        self.assertEqual(len(out["signal_ids"]), 1)
        self._nothing_said_and_held(heard, out["signal_ids"][0])
        # the HQ test button is never announced, so it has nothing to hold
        with _listening(SAT_NOON) as heard, \
                self.assertLogs("signals.fast_rules", "INFO"):
            admin = dispatch_event("mh_evt", {"symbol": "EURUSD"},
                                   source="admin")
        self.assertEqual(len(admin["signal_ids"]), 1)
        self.assertFalse(heard.said)
        self.assertEqual(len(_holds()), 1)

    # ── 13: off, no row, a hold that cannot be written ───────────────

    def _a_reader(self):
        """The staff user reads Telegram and email, as the rows of
        tests/test_signal_shut_words were printed for."""
        from alerts.models import UserNotificationPrefs
        from tests import test_signal_shut_words as words
        p, _ = UserNotificationPrefs.objects.get_or_create(user=self.staff)
        p.telegram_chat_id, p.receive_signals = words.CHAT, True
        p.email_notifications = True
        p.save()
        self.staff.email = "mh_reader@x.io"
        self.staff.save(update_fields=["email"])

    def _as_today(self, when, symbol="EURUSD"):
        """Announce one of tests/test_signal_shut_words' rows for real
        (the bell's rows, the Telegram text): what each channel carried."""
        from tests import test_signal_shut_words as words
        sig = words._signal(symbol)
        return sig, words._Base._announce(self, sig, when)

    def _assert_said_with_the_label(self, sig, got):
        """A shut market, announced at birth: main's bytes and the label,
        nothing else (tests/test_signal_shut_words pins each channel)."""
        from tests import test_signal_shut_words as words
        main = words.MAIN["EURUSD"]
        self.assertEqual(got["banner"], [{**main["banner"],
                                          "signal_id": sig.pk,
                                          "market": words.SHUT_SUN}])
        kind, title, body, url = main["bell"]
        self.assertEqual(got["bell"],
                         [(kind, title, f"{body} · {words.SHUT_SUN}", url)])
        want = list(main["telegram"])
        want.insert(3, "Market shut · opens Sun 22:00 UTC")
        self.assertEqual(got["telegram"], [want])

    def test_13_the_switch_off_announces_as_today(self):
        from tests import test_signal_shut_words as words
        self._a_reader()
        _switch(False)
        # a shut market: announced at once, the label the only difference
        sig, got = self._as_today(SAT_NOON)
        self._assert_said_with_the_label(sig, got)
        self.assertNotIn("held", got["out"])
        # an open market: main's bytes
        sig, got = self._as_today(MON_1000, "BTCUSD")
        words._Base.assertMainsBytes(self, got, "BTCUSD", sig)
        self.assertEqual(_holds(), [])

    def test_13_the_switch_with_no_row_announces_as_today(self):
        from core.platform_control import PlatformComponent
        from signals import market_hold
        self._a_reader()
        PlatformComponent.objects.filter(key=SWITCH).delete()
        self.assertFalse(market_hold.enabled())
        sig, got = self._as_today(SAT_NOON)
        self._assert_said_with_the_label(sig, got)
        self.assertEqual(_holds(), [])

    def test_13_an_open_market_keeps_mains_bytes_with_the_switch_on(self):
        from tests import test_signal_shut_words as words
        self._a_reader()
        sig, got = self._as_today(MON_1000)
        words._Base.assertMainsBytes(self, got, "EURUSD", sig)
        self.assertEqual(_holds(), [])

    def test_13_a_hold_that_cannot_be_written_announces_as_today(self):
        """And the write sits in its own savepoint, so a database refusal
        cannot poison the creator's transaction."""
        from django.db import DatabaseError, connection
        from signals.models import SignalHold
        depth = []

        def refuse(*a, **kw):
            depth.append(len(connection.savepoint_ids))
            raise DatabaseError("the table is not there")

        outer = len(connection.savepoint_ids)
        sig = _sig(self.inst, SAT_NOON)
        with patch.object(SignalHold.objects, "get_or_create",
                          side_effect=refuse), \
                self.assertLogs("signals.market_hold", "WARNING") as logs:
            heard = _announce(sig, SAT_NOON)
        self.assertEqual(depth, [outer + 1])
        self.assertIn("announced now", "\n".join(logs.output))
        self.assertEqual([s[0] for s in heard.steps], ["banner", "channels"])
        self.assertEqual(len(_bells()), 1)
        self.assertEqual(heard.banners[0]["market"],
                         "market shut · opens Sun 22:00 UTC")
        self.assertNotIn("held", heard.out)
        self.assertEqual(_holds(), [])

    def test_13_a_hold_that_raises_announces_as_today(self):
        """The outer fence of announce_new_signal: whatever the hold
        raises, the signal is announced now and the log says why. No test
        made hold_at_birth raise (the review of 2026-11-12)."""
        sig = _sig(self.inst, SAT_NOON)
        with patch("signals.market_hold.hold_at_birth",
                   side_effect=RuntimeError("the hold broke")), \
                self.assertLogs("signals.announce", "WARNING") as logs:
            heard = _announce(sig, SAT_NOON)
        self.assertIn("announced now", "\n".join(logs.output))
        self.assertEqual([s[0] for s in heard.steps], ["banner", "channels"])
        self.assertEqual(len(_bells()), 1)
        self.assertEqual(set(heard.out),
                         {"signal_id", "banner", "bell", "channels"})
        self.assertEqual(_holds(), [])

    def test_the_gate_off_holds_nothing_with_the_switch_on(self):
        sig = _sig(self.inst, SAT_NOON)
        heard = _announce(sig, SAT_NOON, gate=False)
        self.assertTrue(heard.said)
        self.assertNotIn("market", heard.banners[0])
        self.assertEqual(_holds(), [])


class AtTheOpenTests(_HoldBase):
    def test_14_still_shut_settling_and_an_old_quote_wait(self):
        sig = self._held()
        _quote(self.inst, "1.08450", SUN_2130)
        for when in (SUN_2130, SUN_2205):
            with self.subTest(when=when):
                heard = _release(when)
                self.assertFalse(heard.said)
                self.assertEqual(heard.out["waiting"], 1)
        # open and settled, but the only quote was written inside the
        # first quarter hour: not yet a price of the new session
        _quote(self.inst, "1.08450", SUN_2210)
        heard = _release(SUN_2220)
        self.assertFalse(heard.said)
        self.assertEqual((heard.out["waiting"], heard.out["released"],
                          heard.out["dropped"]), (1, 0, 0))
        # and a quote older than the engine's own bound is no price at all
        _quote(self.inst, "1.08450", SUN_2217)
        heard = _release(SUN_2217 + timedelta(minutes=16))
        self.assertFalse(heard.said)
        self.assertEqual(_hold_of(sig).state, "held")
        self.assertEqual(_bells(), [])

    def test_15_a_fresh_quote_inside_the_plan_is_announced_once(self):
        sig = self._held()
        _quote(self.inst, "1.08450", SUN_2217)
        heard = _release(SUN_2220)
        self.assertEqual(heard.steps, [("banner", sig.pk),
                                       ("channels", sig.pk)])
        self.assertEqual(heard.banners[0]["market"], FIRED)
        self.assertEqual(_bells(), [(
            "BEARISH EURUSD", f"MACD cross on EURUSD — Score: 0.55 · {FIRED}")])
        self.assertEqual(heard.notes, [
            "Fired Sunday 09:00 UTC, while the market was shut. First price "
            "since the open: 1.08450."])
        self.assertEqual((heard.out["released"], heard.out["dropped"],
                          heard.out["waiting"]), (1, 0, 0))
        hold = _hold_of(sig)
        self.assertEqual((hold.state, hold.reason), ("released", "valid"))
        self.assertEqual(hold.decided_at, SUN_2220)
        self.assertEqual(hold.mark, Decimal("1.08450"))
        self.assertEqual(hold.reopens_at, SUN_OPEN)
        self.assertIn(FIRED, hold.words)
        # a second pass announces nothing
        again = _release(SUN_2225)
        self.assertFalse(again.said)
        self.assertEqual(again.out["released"], 0)
        self.assertEqual(len(_bells()), 1)

    def test_15_the_released_telegram_message_as_the_phone_shows_it(self):
        from alerts.models import UserNotificationPrefs
        from signals.market_hold import release_due
        p, _ = UserNotificationPrefs.objects.get_or_create(user=self.staff)
        p.telegram_chat_id, p.receive_signals = "-4000000001", True
        p.save()
        self._held()
        _quote(self.inst, "1.08450", SUN_2217)
        ok = MagicMock(ok=True, status_code=200, text='{"ok":true}')
        with _at(SUN_2220), patch("requests.post", return_value=ok) as post, \
                patch("dashboard.consumers.push_eye_event",
                      return_value=True):
            release_due()
        self.assertEqual(post.call_count, 1)
        text = post.call_args.kwargs["json"]["text"]
        self.assertEqual(text.split("\n"), [
            "<b>\U0001F4C9 Signal · EURUSD · SELL</b>",
            "Sauron flags EURUSD as a sell at 1.08500.",
            "",
            "Fired Sunday 09:00 UTC, while the market was shut. First price "
            "since the open: 1.08450.",
            "Score: 0.55",
            "Rule: Mh rule",
            "Entry 1.08500 · stop 1.09000 · target 1.07500",
            "Reward to risk: 2.00",
            "Urgency: medium",
            "Page: /instruments/EURUSD/ on the platform"])
        from tests.test_telegram_v2 import jargon
        self.assertEqual(jargon(text), [])

    def test_16_a_gap_through_the_stop_past_the_target_and_chased_are_dropped(
            self):
        cases = (("EURUSD", "1.09100", "stop_crossed", "through its stop"),
                 ("MHFXB", "1.07400", "target_reached", "reached its target"),
                 ("MHFXC", "1.07900", "chased", "reward to risk"))
        sigs = {}
        for symbol, mark, _reason, _words in cases:
            inst = _db_inst(symbol)
            sigs[symbol] = self._held(inst)
            _quote(inst, mark, SUN_2217)
        heard = _release(SUN_2220)
        self.assertFalse(heard.said, heard.steps)
        self.assertEqual(_bells(), [])
        self.assertEqual((heard.out["dropped"], heard.out["released"]), (3, 0))
        for symbol, mark, reason, words in cases:
            with self.subTest(symbol=symbol):
                hold = _hold_of(sigs[symbol])
                self.assertEqual((hold.state, hold.reason),
                                 ("dropped", reason))
                self.assertEqual(hold.mark, Decimal(mark))
                self.assertEqual(hold.decided_at, SUN_2220)
                self.assertIn(words, hold.words)
        # dropped for good: a later pass does not bring one back
        _quote(self.inst, "1.08450", SUN_2225)
        self.assertFalse(_release(SUN_2225 + timedelta(minutes=3)).said)

    def test_17_born_saturday_0005_read_sunday_2220_is_dropped_aged(self):
        sig = self._held(born=SAT_0005)
        _quote(self.inst, "1.08450", SUN_2217)
        heard = _release(SUN_2220)
        self.assertFalse(heard.said)
        hold = _hold_of(sig)
        self.assertEqual((hold.state, hold.reason), ("dropped", "aged_shut"))
        # The words claim nothing about the market: a signal can age
        # inside the no-price grace, after its market has opened and
        # settled (the review of 2026-11-12).
        self.assertEqual(hold.words,
                         "Its 24 hours ended Sunday 00:05 UTC before it "
                         "could be announced at the open: it was never "
                         "announced.")
        self.assertIsNone(hold.mark)

    def test_17_it_ages_while_its_market_is_still_shut(self):
        """The 24 hours are read before the clock: a Saturday 00:05 signal
        is dropped on the first pass after Sunday 00:05."""
        sig = self._held(born=SAT_0005)
        self.assertEqual(_release(_t(2026, 11, 7, 23, 0)).out["waiting"], 1)
        heard = _release(_t(2026, 11, 8, 0, 5))
        self.assertEqual(heard.out["dropped"], 1)
        self.assertEqual(_hold_of(sig).reason, "aged_shut")

    def test_18_closed_by_the_engine_before_the_open(self):
        from signals.models import Signal
        sig = self._held()
        Signal.objects.filter(pk=sig.pk).update(
            is_active=False, outcome="expired", expired_at=SUN_2130)
        _quote(self.inst, "1.08450", SUN_2217)
        heard = _release(SUN_2220)
        self.assertFalse(heard.said)
        hold = _hold_of(sig)
        self.assertEqual((hold.state, hold.reason), ("dropped", "closed"))
        self.assertIn("closed it before", hold.words)

    def test_19_no_price_thirty_minutes_after_the_settle_is_released_unchecked(
            self):
        sig = self._held()
        heard = _release(SUN_2240)          # 25 minutes after the settle
        self.assertFalse(heard.said)
        self.assertEqual(heard.out["waiting"], 1)
        heard = _release(SUN_2250)          # 35 minutes after it
        self.assertEqual(heard.steps, [("banner", sig.pk),
                                       ("channels", sig.pk)])
        clause = (f"{FIRED}; no price since the open: its levels were not "
                  f"re-checked")
        self.assertEqual(heard.banners[0]["market"], clause)
        self.assertEqual(_bells()[0][1],
                         f"MACD cross on EURUSD — Score: 0.55 · {clause}")
        self.assertEqual(heard.notes, [
            "Fired Sunday 09:00 UTC, while the market was shut. No price "
            "since the open: its levels were not re-checked."])
        hold = _hold_of(sig)
        self.assertEqual((hold.state, hold.reason), ("released", "unchecked"))
        self.assertIsNone(hold.mark)

    def test_19_a_first_price_that_cannot_be_judged_is_released_unchecked(
            self):
        """A price that cannot be read or judged is no price (rule 5): the
        row waits out the grace, then is announced, saying so. Left to
        raise, it stayed held on every pass and ended aged_shut with
        untrue words, never announced (the review of 2026-11-12)."""
        from signals import market_hold
        for n, part in enumerate(("_first_price", "levels_reason")):
            with self.subTest(part=part):
                inst = _db_inst(f"MHFJ{n}")
                sig = self._held(inst)
                _quote(inst, "1.08450", SUN_2217)
                with patch.object(market_hold, part,
                                  side_effect=RuntimeError("unreadable")), \
                        self.assertLogs("signals.market_hold", "ERROR"):
                    heard = _release(SUN_2220)      # in the grace: it waits
                    self.assertFalse(heard.said)
                    self.assertEqual((heard.out["waiting"],
                                      heard.out["errors"]), (1, 1))
                    self.assertEqual(_hold_of(sig).state, "held")
                    _quote(inst, "1.08450", _t(2026, 11, 8, 22, 47))
                    heard = _release(SUN_2250)      # past it: announced
                self.assertEqual(heard.steps, [("banner", sig.pk),
                                               ("channels", sig.pk)])
                clause = (f"{FIRED}; its first price could not be judged: "
                          f"its levels were not re-checked")
                self.assertEqual(heard.banners[0]["market"], clause)
                self.assertEqual(heard.notes, [
                    "Fired Sunday 09:00 UTC, while the market was shut. Its "
                    "first price since the open could not be judged: its "
                    "levels were not re-checked."])
                hold = _hold_of(sig)
                self.assertEqual((hold.state, hold.reason),
                                 ("released", "unchecked"))
                self.assertEqual(hold.words,
                                 f"Announced at the open: {clause}.")
                self.assertIsNone(hold.mark)
                # the pass still says a judgment failed
                self.assertEqual((heard.out["released"],
                                  heard.out["errors"]), (1, 1))

    def test_19_a_judgment_that_fails_once_is_made_on_the_next_pass(self):
        from signals import market_hold
        sig = self._held()
        _quote(self.inst, "1.08450", SUN_2217)
        with patch.object(market_hold, "_first_price",
                          side_effect=RuntimeError("once")), \
                self.assertLogs("signals.market_hold", "ERROR"):
            self.assertEqual(_release(SUN_2220).out["waiting"], 1)
        heard = _release(SUN_2225)
        self.assertEqual((heard.out["released"], heard.out["errors"]), (1, 0))
        self.assertEqual(heard.banners[0]["market"], FIRED)
        hold = _hold_of(sig)
        self.assertEqual((hold.state, hold.reason), ("released", "valid"))
        self.assertEqual(hold.mark, Decimal("1.08450"))

    def test_a_release_that_could_not_be_announced_says_so_on_its_row(self):
        """The row is settled before the announcement goes out, so that a
        release is announced at most once. One that fails must not go on
        reading "announced at the open" (the review of 2026-11-12)."""
        from core.platform_control import PlatformComponent
        sig = self._held()
        _quote(self.inst, "1.08450", SUN_2217)
        with patch("signals.announce.announce_released",
                   side_effect=RuntimeError("no announcement")), \
                self.assertLogs("signals.market_hold", "ERROR"):
            heard = _release(SUN_2220)
        self.assertFalse(heard.said)
        self.assertEqual(_bells(), [])
        hold = _hold_of(sig)
        self.assertEqual((hold.state, hold.reason),
                         ("released", "announce_failed"))
        self.assertEqual(hold.words, "Released at the open, but its "
                                     "announcement failed.")
        self.assertEqual((heard.out["released"], heard.out["errors"]), (0, 1))
        row = PlatformComponent.objects.get(key=SWITCH)
        self.assertEqual(row.last_status, "error")
        self.assertEqual(row.last_message,
                         "0 waiting for their market · 0 announced at the "
                         "open · 0 dropped · 1 could not be judged or "
                         "announced")
        # it is not tried again: a release is announced at most once
        self.assertFalse(_release(SUN_2225).said)

    def test_a_release_whose_three_steps_all_failed_says_so_too(self):
        from signals.market_hold import release_due
        sig = self._held()
        _quote(self.inst, "1.08450", SUN_2217)
        down = RuntimeError("down")
        with _at(SUN_2220), \
                patch("dashboard.consumers.push_eye_event",
                      side_effect=down), \
                patch("alerts.notify.notify_new_signal", side_effect=down), \
                patch("alerts.dispatch.dispatch_signal_alert",
                      side_effect=down), \
                self.assertLogs("signals.market_hold", "ERROR"):
            out = release_due()
        self.assertEqual(_bells(), [])
        hold = _hold_of(sig)
        self.assertEqual((hold.state, hold.reason),
                         ("released", "announce_failed"))
        self.assertEqual((out["released"], out["errors"]), (0, 1))

    def test_a_release_heard_in_one_place_is_an_announcement(self):
        from signals.market_hold import release_due
        sig = self._held()
        _quote(self.inst, "1.08450", SUN_2217)
        down = RuntimeError("down")
        with _at(SUN_2220), \
                patch("dashboard.consumers.push_eye_event",
                      side_effect=down), \
                patch("alerts.dispatch.dispatch_signal_alert",
                      side_effect=down), \
                self.assertLogs("signals.announce", "ERROR"):
            out = release_due()
        self.assertEqual(len(_bells()), 1)
        hold = _hold_of(sig)
        self.assertEqual((hold.state, hold.reason), ("released", "valid"))
        self.assertEqual((out["released"], out["errors"]), (1, 0))

    def test_19_a_bar_opened_since_the_open_counts_as_a_price(self):
        # a bar from before the shut is no price of the new session
        sig = self._held()
        _bar(self.inst, _t(2026, 11, 6, 20, 0), "1.08450", "4h")
        self.assertFalse(_release(SUN_2220).said)
        # the first hour's bar is: judged, and inside the plan
        _bar(self.inst, SUN_OPEN, "1.08440", "1h")
        heard = _release(SUN_2225)
        self.assertEqual(heard.out["released"], 1)
        self.assertEqual(_hold_of(sig).mark, Decimal("1.08440"))
        self.assertEqual(heard.notes, [
            "Fired Sunday 09:00 UTC, while the market was shut. First price "
            "since the open: 1.08440."])
        # and a bar through the stop drops it
        other = _db_inst("MHFXB")
        gapped = self._held(other)
        _bar(other, SUN_OPEN, "1.09200", "4h")
        heard = _release(SUN_2225)
        self.assertFalse(heard.said)
        self.assertEqual(_hold_of(gapped).reason, "stop_crossed")

    def test_20_three_released_at_one_open_go_out_in_score_order(self):
        sigs = {}
        for symbol, score in (("EURUSD", 0.60), ("MHFXB", 0.90),
                              ("MHFXC", 0.75)):
            inst = _db_inst(symbol)
            sigs[symbol] = self._held(inst, score=score)
            _quote(inst, "1.08450", SUN_2217)
        heard = _release(SUN_2220)
        order = [pk for step, pk in heard.steps if step == "channels"]
        self.assertEqual(order, [sigs["MHFXB"].pk, sigs["MHFXC"].pk,
                                 sigs["EURUSD"].pk])
        self.assertEqual(heard.out["released"], 3)

    def test_20_the_telegram_guard_holds_the_rest_of_a_burst(self):
        """Twenty signal messages a chat an hour (alerts/dispatch): at an
        open the best twenty go out and the guard counts the others."""
        from alerts.dispatch import SIGNAL_FLOOD_MAX
        from alerts.models import UserNotificationPrefs
        from signals.market_hold import release_due
        p, _ = UserNotificationPrefs.objects.get_or_create(user=self.staff)
        p.telegram_chat_id, p.receive_signals = "-4000000001", True
        p.save()
        n = SIGNAL_FLOOD_MAX + 3
        for i in range(n):
            self._held(rule=f"mh_rule_{i}", score=round(0.30 + i * 0.02, 2))
        _quote(self.inst, "1.08450", SUN_2217)
        ok = MagicMock(ok=True, status_code=200, text='{"ok":true}')
        with _at(SUN_2220), patch("requests.post", return_value=ok) as post, \
                patch("dashboard.consumers.push_eye_event",
                      return_value=True):
            out = release_due()
        self.assertEqual(out["released"], n)
        self.assertEqual(post.call_count, SIGNAL_FLOOD_MAX)
        scores = [float(c.kwargs["json"]["text"].split("Score: ")[1][:4])
                  for c in post.call_args_list]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(scores[0], round(0.30 + (n - 1) * 0.02, 2))

    def test_21_a_rule_still_at_research_gets_banner_and_bell_no_telegram(
            self):
        from signals.rule_birth import BORN_AT_RESEARCH
        sig = self._held(rule=sorted(BORN_AT_RESEARCH)[0])
        _quote(self.inst, "1.08450", SUN_2217)
        heard = _release(SUN_2220)
        self.assertEqual(heard.steps, [("banner", sig.pk)])
        heard.dispatch.assert_not_called()
        self.assertEqual(len(_bells()), 1)
        self.assertTrue(_bells()[0][1].endswith(f" · {FIRED}"))
        self.assertEqual(_hold_of(sig).state, "released")

    def test_a_signal_held_in_the_first_quarter_hour_says_so_at_release(self):
        sig = _sig(self.inst, SUN_2205)
        self.assertFalse(_announce(sig, SUN_2205).said)
        _quote(self.inst, "1.08450", SUN_2217)
        heard = _release(SUN_2220)
        self.assertEqual(heard.banners[0]["market"],
                         "fired Sunday 22:05 UTC, in its market's first "
                         "quarter hour")
        self.assertEqual(heard.notes, [
            "Fired Sunday 22:05 UTC, in the market's first quarter hour. "
            "First price since the open: 1.08450."])

    def test_23_the_switch_turned_off_with_a_held_row_still_settles_it(self):
        kept = self._held()
        gapped = self._held(_db_inst("MHFXB"))
        _switch(False)
        _quote(self.inst, "1.08450", SUN_2217)
        _quote(_db_inst("MHFXB"), "1.09100", SUN_2217)
        heard = _release(SUN_2220)
        self.assertEqual([pk for step, pk in heard.steps
                          if step == "channels"], [kept.pk])
        self.assertEqual(_hold_of(kept).state, "released")
        self.assertEqual((_hold_of(gapped).state, _hold_of(gapped).reason),
                         ("dropped", "stop_crossed"))
        # and with the switch off nothing new is held
        fresh = _sig(_db_inst("MHFXC"), SUN_2220)
        self.assertTrue(_announce(fresh, SAT_NOON).said)
        self.assertEqual(len(_holds(state="held")), 0)

    def test_one_bad_row_never_starves_the_pass(self):
        from signals import market_hold
        bad = self._held()
        good = self._held(_db_inst("MHFXB"), score=0.4)
        _quote(self.inst, "1.08450", SUN_2217)
        _quote(_db_inst("MHFXB"), "1.08450", SUN_2217)
        real = market_hold._judge

        def judge(hold, now):
            if hold.signal_id == bad.pk:
                raise RuntimeError("one bad row")
            return real(hold, now)

        with patch.object(market_hold, "_judge", side_effect=judge), \
                self.assertLogs("signals.market_hold", "ERROR"):
            heard = _release(SUN_2220)
        self.assertEqual((heard.out["errors"], heard.out["released"]), (1, 1))
        self.assertEqual(_hold_of(good).state, "released")
        self.assertEqual(_hold_of(bad).state, "held")

    def test_the_pass_does_nothing_with_the_gate_off(self):
        sig = self._held()
        _quote(self.inst, "1.08450", SUN_2217)
        heard = _release(SUN_2220, gate=False)
        self.assertFalse(heard.said)
        self.assertEqual(_hold_of(sig).state, "held")

    def test_the_pass_records_its_run_on_the_switch(self):
        from core.platform_control import PlatformComponent
        self._held()
        _release(SUN_2130)
        row = PlatformComponent.objects.get(key=SWITCH)
        self.assertEqual(row.last_status, "success")
        self.assertEqual(row.last_message,
                         "1 waiting for their market · 0 announced at the "
                         "open · 0 dropped")
        # nothing held, the switch on: the pass still says it ran, so the
        # switch never reads "enabled, but has never run"
        from signals.models import SignalHold
        SignalHold.objects.all().delete()
        PlatformComponent.objects.filter(key=SWITCH).update(last_message="")
        _release(SUN_2220)
        self.assertEqual(PlatformComponent.objects.get(key=SWITCH)
                         .last_message,
                         "0 waiting for their market · 0 announced at the "
                         "open · 0 dropped")
        # nothing held, the switch off: no write at all
        _switch(False)
        PlatformComponent.objects.filter(key=SWITCH).update(last_message="")
        _release(SUN_2225)
        self.assertEqual(PlatformComponent.objects.get(key=SWITCH)
                         .last_message, "")


class LevelsReasonTests(TestCase):
    def test_22_levels_reason_is_the_rails_own_verdict_on_a_grid(self):
        """The rail's three price rules and the hold's are one judgment:
        for every mark of a grid the two give the same reason."""
        from dashboard.signal_rail import _price_verdict, _side_of
        from signals.market_hold import levels_reason
        inst = SimpleNamespace(asset_class="forex", symbol="EURUSD")
        plans = (("bullish", "1.08500", "1.08000", "1.09500"),
                 ("bearish", "1.08500", "1.09000", "1.07500"),
                 ("bullish", "1.08500", "1.08000", None),
                 ("bearish", "1.08500", None, "1.07500"),
                 ("bullish", "1.08500", None, None),
                 # a plan under the ticket's 1.00 line at its own entry
                 ("bullish", "1.08500", "1.08000", "1.08700"),
                 ("neutral", "1.08500", "1.08000", "1.09500"))
        seen = set()
        for direction, entry, stop, target in plans:
            s = SimpleNamespace(
                instrument=inst, direction=direction,
                suggested_entry=Decimal(entry), price_at_signal=Decimal(entry),
                suggested_stop=None if stop is None else Decimal(stop),
                suggested_target=None if target is None else Decimal(target))
            f = lambda v: None if v is None else float(v)  # noqa: E731
            for step in range(0, 61):
                mark = round(1.0700 + step * 0.0005, 5)
                hit = _price_verdict(s, mark, _side_of(direction), MON_1000)
                rail = hit[0] if hit else ""
                mine = levels_reason(direction, f(entry), f(stop), f(target),
                                     mark)
                self.assertEqual(mine, rail, (direction, stop, target, mark))
                seen.add(mine)
        self.assertEqual(seen, {"", "stop_crossed", "target_reached",
                                "chased"})
        self.assertEqual(levels_reason("bullish", 1.085, 1.08, 1.095, None),
                         "")


class MoneyDirectionTests(_HoldBase):
    """The hold moves an announcement and nothing else: what the engine,
    the bots and the grader read is exactly what they read."""

    def _world(self):
        from bot_program.models import AssetBotTrade
        from instruments.models import Instrument
        from signals.models import (OpportunityFlag, PromotionEvent,
                                    RuleControl, Signal)

        def row(obj):
            return json.dumps({f.attname: getattr(obj, f.attname)
                               for f in obj._meta.concrete_fields},
                              sort_keys=True, default=str)
        return {model.__name__: sorted(row(o) for o in model.objects.all())
                for model in (Signal, RuleControl, PromotionEvent,
                              AssetBotTrade, Instrument, OpportunityFlag)}

    def test_24_no_engine_row_moves_on_a_hold_a_release_or_a_drop(self):
        from signals.models import RuleControl
        RuleControl.objects.create(rule_name="mh_rule",
                                   promotion_stage="live_full")
        kept = _sig(self.inst, SUN_0900)
        gapped = _sig(_db_inst("MHFXB"), SUN_0900)
        aged = _sig(_db_inst("MHFXC"), SAT_0005)
        before = self._world()
        self.assertEqual(len(before["Signal"]), 3)
        for sig in (kept, gapped):
            self.assertFalse(_announce(sig, SUN_0900).said)
        self.assertFalse(_announce(aged, SAT_0005).said)
        self.assertEqual(len(_holds(state="held")), 3)
        self.assertEqual(self._world(), before)
        _quote(self.inst, "1.08450", SUN_2217)
        _quote(_db_inst("MHFXB"), "1.09100", SUN_2217)
        heard = _release(SUN_2220)
        self.assertEqual((heard.out["released"], heard.out["dropped"]), (1, 2))
        self.assertEqual(self._world(), before)

    def test_25_the_bots_decide_the_same_with_the_switch_on_and_off(self):
        from bot_program.asset_engine import ForexBot, StockBot
        from signals.models import RuleControl
        from tests.test_evidence_honesty import _cfg as bot_cfg
        aapl = _db_inst("AAPL", "stock", "NASDAQ")
        stock = bot_cfg(self.staff, asset_class="stock", name="MH stock",
                        mode="paper", symbols=["AAPL"],
                        capital=Decimal("10000"), min_signals_for_entry=2)
        fx = bot_cfg(self.staff, asset_class="forex", name="MH fx",
                     mode="paper", symbols=["EURUSD"],
                     capital=Decimal("10000"), min_signals_for_entry=2,
                     extras={"session_filter_disabled": True})
        sigs = []
        for rule in ("golden_cross", "macd_cross"):
            RuleControl.objects.create(rule_name=rule,
                                       promotion_stage="live_full")
            sigs.append(_sig(aapl, MON_0900, rule=rule, direction="bullish",
                             score=0.85, entry="100", stop="95",
                             target="110"))
            sigs.append(_sig(self.inst, SUN_2130, rule=rule,
                             direction="bullish", score=0.85, entry="1.08500",
                             stop="1.08000", target="1.09500"))

        def decisions(when):
            out = []
            with _at(when):
                for bot, symbol in ((StockBot(stock), "AAPL"),
                                    (ForexBot(fx), "EURUSD")):
                    d = bot.decide(symbol)
                    out.append((d.direction, round(float(d.score or 0), 6),
                                d.rule_name, list(d.reasons)))
            return out

        # the switch off: nothing held, the bots' read of the rows
        _switch(False)
        early, late = _t(2026, 11, 9, 9, 30), _t(2026, 11, 9, 15, 0)
        off_early, off_late = decisions(early), decisions(late)
        self.assertEqual([d[0] for d in off_early], ["BUY", "BUY"], off_early)
        # the switch on: every signal held
        _switch(True)
        for sig in sigs:
            born = MON_0900 if sig.instrument_id == aapl.pk else SUN_2130
            self.assertFalse(_announce(sig, born).said)
        self.assertEqual(len(_holds(state="held")), 4)
        self.assertEqual(decisions(early), off_early)
        # released (the shares, a price inside the plan) and dropped (the
        # pair, a gap through the stop): the same decisions again
        _quote(aapl, "101", _t(2026, 11, 9, 14, 50))
        _quote(self.inst, "1.07900", _t(2026, 11, 9, 14, 50))
        heard = _release(_t(2026, 11, 9, 14, 55))
        self.assertEqual((heard.out["released"], heard.out["dropped"]), (2, 2))
        from market_data.models import LiveQuote
        LiveQuote.objects.all().delete()
        self.assertEqual(decisions(late), off_late)
        _switch(False)
        self.assertEqual(decisions(late), off_late)

    def test_26_grading_is_the_same_for_a_held_signal(self):
        """A weekend-born signal, first priced after the reopen: a gap
        through the target, a gap through the stop, no gap. The grade is
        today's, held or not (its entry realism is not this fix's)."""
        from signals.models import Signal
        from signals.performance import evaluate_signal_outcome
        cases = (("1.09700", "hit_target", 2.0), ("1.07900", "stopped_out",
                                                  -1.0),
                 ("1.08600", "active", None))
        for i, (mark, outcome, r) in enumerate(cases):
            graded = []
            for held in (False, True):
                inst = _db_inst(f"MHG{i}{int(held)}")
                sig = _sig(inst, SAT_NOON, direction="bullish",
                           entry="1.08500", stop="1.08000", target="1.09500")
                _switch(held)
                heard = _announce(sig, SAT_NOON)
                self.assertEqual(heard.said, not held)
                _quote(inst, mark, SUN_2217)
                with _at(SUN_2220):
                    got = evaluate_signal_outcome(
                        Signal.objects.select_related(
                            "instrument", "instrument__live_quote")
                        .get(pk=sig.pk))
                row = Signal.objects.get(pk=sig.pk)
                graded.append((got, row.outcome, row.realized_r,
                               row.expired_at, row.is_active, row.mfe,
                               row.mae, row.time_to_outcome_seconds))
            with self.subTest(mark=mark):
                self.assertEqual(graded[0], graded[1])
                self.assertEqual(graded[1][0], outcome)
                self.assertEqual(graded[1][2], r)

    def test_27_no_engine_file_names_the_hold(self):
        """A guard: it passes by construction. The bots, the book, the
        proving ground, the ladder, the grader and the rule engine never
        read the hold."""
        base = Path(settings.BASE_DIR)
        files = [p for top in ("bot_program", "portfolio", "backtester")
                 for p in sorted((base / top).rglob("*.py"))]
        files += [base / "signals" / name for name in (
            "promotion_pipeline.py", "performance.py", "tasks.py")]
        self.assertGreater(len(files), 150, "the guard read almost nothing")
        hits = []
        for path in files:
            text = path.read_text(encoding="utf-8", errors="replace")
            for word in ("SignalHold", "market_hold"):
                if word in text:
                    hits.append(f"{path.relative_to(base).as_posix()}: {word}")
        self.assertEqual(hits, [])

    def test_28_the_lifecycle_task_still_grades_when_the_release_raises(self):
        from market_data.models import LiveQuote
        from signals.models import Signal
        from signals.tasks_lifecycle import run_signal_lifecycle
        inst = _db_inst("BTCUSD", "crypto")
        sig = Signal.objects.create(
            instrument=inst, signal_type="technical", direction="bullish",
            urgency="medium", title="t", description="d", rule_name="mh_life",
            score=0.7, sub_scores={}, price_at_signal=Decimal("100"),
            suggested_entry=Decimal("100"), suggested_stop=Decimal("95"),
            suggested_target=Decimal("110"))
        LiveQuote.objects.create(instrument=inst, last=Decimal("111"),
                                 source="test")
        with patch("signals.market_hold.release_due",
                   side_effect=RuntimeError("release down")), \
                self.assertLogs("signals.tasks_lifecycle", "ERROR"):
            out = run_signal_lifecycle()
        self.assertEqual(out["closed"], 1)
        self.assertEqual(out["market_hold"], "failed")
        self.assertEqual(Signal.objects.get(pk=sig.pk).outcome, "hit_target")

    def test_the_lifecycle_task_runs_the_release_pass_after_its_loop(self):
        from signals.tasks_lifecycle import run_signal_lifecycle
        sig = self._held()
        _quote(self.inst, "1.08450", SUN_2217)
        with _listening(SUN_2220) as heard:
            out = run_signal_lifecycle()
        self.assertEqual(out["market_hold"]["released"], 1)
        self.assertEqual(heard.steps, [("banner", sig.pk),
                                       ("channels", sig.pk)])
        self.assertEqual(out["evaluated"], 1)


class TheSwitchTests(TestCase):
    def test_the_row_arrives_off_and_is_not_a_money_switch(self):
        from core import platform_control as pc
        rows = [c for c in pc.DEFAULT_COMPONENTS if c["key"] == SWITCH]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["name"], row["category"]),
                         ("Signal Market Hold", "pipeline"))
        self.assertNotIn("is_enabled", row)
        self.assertLess(len(row["description"]), 300)
        self.assertIn("no money", row["description"])
        self.assertNotIn(SWITCH, pc.LIVE_MONEY_SWITCHES)
        # A group's "all on" leaves it OFF (the review of 2026-11-12):
        # the operator keeps every signal live, so the hold is a decision
        # of his own, made by its own row. It is still no PIN switch.
        self.assertIn(SWITCH, pc.OPERATOR_CHOICE_SWITCHES)
        self.assertIn(SWITCH, pc.BULK_ENABLE_EXEMPT)
        self.assertNotIn(SWITCH, pc.PIN_SWITCHES)

    def test_the_seed_writes_it_off_and_a_missing_row_reads_off(self):
        from core import platform_control as pc
        from signals import market_hold
        self.assertEqual(market_hold.SWITCH, SWITCH)
        self.assertFalse(market_hold.enabled())
        pc.seed_components()
        self.assertFalse(pc.PlatformComponent.objects.get(key=SWITCH)
                         .is_enabled)
        self.assertFalse(market_hold.enabled())
        _switch(True)
        self.assertTrue(market_hold.enabled())

    def test_the_life_and_the_bounds_are_the_engines_own(self):
        from bot_program.manual_trade import SIGNAL_BACKING_HOURS
        from signals import market_hold
        from signals.performance import MAX_QUOTE_AGE_SECONDS
        self.assertEqual(market_hold.life(),
                         timedelta(hours=SIGNAL_BACKING_HOURS))
        self.assertEqual(market_hold.quote_max_age(),
                         timedelta(seconds=MAX_QUOTE_AGE_SECONDS))
        self.assertEqual(market_hold.NO_PRICE_GRACE, timedelta(minutes=30))
