"""THE GUARD (2026-11-19): nothing is sent to eToro for a live row while its
market is shut for 24 hours or more; management and the pending-close
drain take the row up again at the reopen.

The operator, 2026-11-19: "oui pour le garde-fou". A live row has no market
clock in the manage tick (bot_program/asset_engine/base.py manage_positions:
only paper rows wait while their market is shut). On a weekend the time
stop, the care's soft-stop close and its mirrored stop PATCH, the config
knobs' stop PATCH and the bot-side SL/TP close could each send an order to
eToro for a market eToro has shut, and the pending-close drain resent a
refused close every five minutes until the twelfth refusal put the row in
ERROR, out of every reader (bot_program/pending_closes.py).

The switch care_holds_while_shut, "Hold management while the market is
shut": OFF on arrival, and OFF is the tick and the drain exactly as they
were; its ON takes the trading PIN at /ops/. ON, a LIVE eToro row, real or
demo, of a currency pair or of a commodity eToro trades on weekdays only,
while its instrument is inside a shut of 24 hours or more on the bar rule's
own clocks (market_data/shut_bars.shut_for_a_day_now: eToro's FX week,
Friday 17:00 to Sunday 17:00 New York, for a pair; the instrument's clock
for a commodity), is HELD: the tick reads nothing and sends nothing for it,
and the drain neither resends its close nor counts an attempt. eToro's
all-week instruments (gold here), crypto, stocks and paper rows are managed
as before, and so is everything the operator does himself: the kill switch
and the CLOSE button.

Fakes only: the feed harness's fake eToro (tests/feed/harness.py) records
every request and refuses every write unless a scenario accepts it.
Invented prices; public catalogue symbols only.

Clocks, UTC, in winter (New York on EST since 1 November):
  FRI_2130  Fri 20 Nov 21:30  eToro's FX week still runs, to 22:00
  FRI_2200  Fri 20 Nov 22:00  the FX week and Globex shut
  SAT       Sat 21 Nov 12:00  inside both shuts
  SUN_2210  Sun 22 Nov 22:10  the FX week reopened at 22:00; Globex still shut
  CME_BACK  Sun 22 Nov 23:05  Globex reopened at 23:00

Run with:  python manage.py test tests.test_weekend_guard
"""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from tests.feed import harness as H

UTC = dt_tz.utc
KEY = "care_holds_while_shut"
NAME = "Hold management while the market is shut"
TEST_PIN = "583920"     # a test-only value

FRI_2130 = datetime(2026, 11, 20, 21, 30, tzinfo=UTC)
FRI_2200 = datetime(2026, 11, 20, 22, 0, tzinfo=UTC)
SAT = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
SUN_2210 = datetime(2026, 11, 22, 22, 10, tzinfo=UTC)
CME_BACK = datetime(2026, 11, 22, 23, 5, tzinfo=UTC)

#: symbol -> (class, exchange, invented entry, invented 1R)
BOOK = {
    "EURUSD": ("forex", "FOREX", Decimal("1.1000"), Decimal("0.0100")),
    "GBPUSD": ("forex", "FOREX", Decimal("1.3000"), Decimal("0.0100")),
    "HGUSD": ("commodity", "COMEX", Decimal("4.5000"), Decimal("0.1000")),
    "XAUUSD": ("commodity", "COMEX", Decimal("2000.00"), Decimal("20.00")),
    "BTCUSD": ("crypto", "CRYPTO", Decimal("50000"), Decimal("1000")),
    "AAPL": ("stock", "NASDAQ", Decimal("150.00"), Decimal("2.00")),
}

#: The managed sends of the tick, one scenario each: the row it needs, its
#: mark in R from the entry, and the write it makes with the switch OFF.
SCENARIOS = {
    "the soft stop is crossed": (
        dict(protected=True, care=(1.5, 0.1)), 0.0, "close_position"),
    "the time stop is due": (dict(opened_days_ago=40), 0.2,
                             "close_position"),
    "the mirror is due": (dict(protected=True), 1.2, "modify_protective"),
    "a knob moves the stop": (dict(protected=True, knob=True), 1.2,
                              "modify_protective"),
    "the bot-side stop is hit": (dict(), -1.5, "close_position"),
}


def _switch(key, on):
    from core.platform_control import PlatformComponent
    PlatformComponent.objects.update_or_create(
        key=key, defaults={"name": key, "category": "system",
                           "is_enabled": on})


def _price(symbol, r):
    """`symbol`'s invented entry plus `r` of its invented 1R."""
    _cls, _ex, entry, one_r = BOOK[symbol]
    return entry + one_r * Decimal(str(r))


def _at(*a):
    return datetime(*a, tzinfo=UTC)


def _inst(cls, exchange="", symbol="X"):
    return SimpleNamespace(asset_class=cls, exchange=exchange, symbol=symbol)


# ── the clock: shut_bars.shut_for_a_day_now ─────────────────────────────

class TheClockTests(SimpleTestCase):
    """shut_for_a_day_now(instrument, now): the shut of 24 hours or more
    that holds `now` on the bar rule's own clocks, as (closed, reopens) in
    UTC, or None. The instants are worked by hand."""

    def _shut(self, inst, now):
        from market_data.shut_bars import shut_for_a_day_now
        return shut_for_a_day_now(inst, now)

    def test_the_classes_it_holds_are_one_constant(self):
        from market_data.shut_bars import HELD_CLASSES
        self.assertEqual(HELD_CLASSES, frozenset({"forex", "commodity"}))

    def test_a_pair_reads_etoros_new_york_week(self):
        """Winter: eToro's week shuts at Friday 22:00 UTC and reopens at
        Sunday 22:00 UTC, an hour after the FOREX row's own hours."""
        week = (FRI_2200, _at(2026, 11, 22, 22))
        for sym in ("EURUSD", "GBPUSD"):
            fx = _inst("forex", "FOREX", sym)
            self.assertIsNone(self._shut(fx, FRI_2130), sym)
            self.assertEqual(self._shut(fx, FRI_2200), week, sym)
            self.assertEqual(self._shut(fx, SAT), week, sym)
            self.assertEqual(self._shut(fx, _at(2026, 11, 22, 21, 59)), week)
            self.assertIsNone(self._shut(fx, _at(2026, 11, 22, 22)), sym)
            self.assertIsNone(self._shut(fx, _at(2026, 11, 18, 12)), sym)

    def test_a_pair_in_summer(self):
        """New York on EDT: Friday 21:00 to Sunday 21:00 UTC."""
        fx = _inst("forex", "FOREX", "EURUSD")
        self.assertIsNone(self._shut(fx, _at(2026, 7, 10, 20, 59)))
        self.assertEqual(self._shut(fx, _at(2026, 7, 11, 12)),
                         (_at(2026, 7, 10, 21), _at(2026, 7, 12, 21)))
        self.assertIsNone(self._shut(fx, _at(2026, 7, 12, 21)))

    def test_a_weekday_commodity_reads_its_exchange_clock(self):
        """Copper on COMEX keeps Globex at eToro: shut Friday 22:00 to
        Sunday 23:00 UTC in winter; the daily hour's break is no shut of a
        day and holds nothing."""
        copper = _inst("commodity", "COMEX", "HGUSD")
        shut = (FRI_2200, _at(2026, 11, 22, 23))
        self.assertIsNone(self._shut(copper, FRI_2130))
        self.assertEqual(self._shut(copper, SAT), shut)
        self.assertEqual(self._shut(copper, SUN_2210), shut)
        self.assertIsNone(self._shut(copper, CME_BACK))
        self.assertIsNone(self._shut(copper, _at(2026, 11, 17, 22, 30)))

    def test_an_unknown_exchange_reads_the_class_clock(self):
        """"" (/setup/) and "ETORO" (the legacy sync) name no table: the
        class's default clock, CME."""
        for exch in ("", "ETORO"):
            other = _inst("commodity", exch, "HGUSD")
            self.assertEqual(self._shut(other, SAT),
                             (FRI_2200, _at(2026, 11, 22, 23)), exch)
            self.assertIsNone(self._shut(other, _at(2026, 11, 17, 22, 30)))

    def test_etoros_all_week_instruments_are_never_shut(self):
        """Gold and silver trade at eToro on Saturday and Sunday too (its
        market-hours page: 24/7, short breaks only), whatever exchange
        their row names."""
        for sym in ("XAUUSD", "XAGUSD"):
            for exch in ("COMEX", "NYMEX", "", "ETORO"):
                self.assertIsNone(
                    self._shut(_inst("commodity", exch, sym), SAT),
                    (sym, exch))

    def test_every_other_class_is_never_held(self):
        for cls, exch, sym in (("crypto", "CRYPTO", "BTCUSD"),
                               ("stock", "NASDAQ", "AAPL"),
                               ("etf", "NYSE", "X"), ("index", "", "X"),
                               ("cfd", "", "X"), ("", "", "X")):
            self.assertIsNone(self._shut(_inst(cls, exch, sym), SAT), cls)

    def test_what_cannot_be_read_is_never_held(self):
        fx = _inst(" Forex ", "", "EURUSD")
        self.assertEqual(self._shut(fx, SAT.replace(tzinfo=None)),
                         (FRI_2200, _at(2026, 11, 22, 22)), "naive is UTC")
        self.assertIsNone(self._shut(None, SAT))
        self.assertIsNone(self._shut(fx, "Saturday"))


# ── the switch ───────────────────────────────────────────────────────────

def _flashes(resp) -> str:
    return " | ".join(str(m) for m in get_messages(resp.wsgi_request))


def _row():
    from core.platform_control import PlatformComponent
    return PlatformComponent.objects.get(key=KEY)


class TheSwitchTests(TestCase):
    """A live-money switch, as the venue floor's (PR #102): named by hand
    in LIVE_MONEY_SWITCHES, so its ON takes the trading PIN at /ops/, the
    shell and the Django admin refuse it, "all on" never arms it, and it
    arrives OFF. A row that is missing reads OFF."""

    def setUp(self):
        from core.platform_control import seed_components
        cache.clear()
        seed_components()
        self.admin = User.objects.create_superuser("guard_admin", "a@x", "x")
        self.client.force_login(self.admin)

    def test_it_is_a_live_money_switch_named_by_hand(self):
        from bot_program.shut_guard import SWITCH_KEY
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           LIVE_MONEY_SWITCHES,
                                           ORC_MIND_SWITCHES, PIN_SWITCHES)
        from core.switch_pin import is_live, needs_pin
        self.assertEqual(SWITCH_KEY, KEY)
        self.assertIn(KEY, LIVE_MONEY_SWITCHES)
        self.assertNotIn(KEY, ORC_MIND_SWITCHES)
        self.assertIn(KEY, PIN_SWITCHES)
        self.assertIn(KEY, BULK_ENABLE_EXEMPT)
        self.assertTrue(is_live(KEY))
        self.assertTrue(needs_pin(KEY, was_on=False, want_on=True))
        self.assertFalse(needs_pin(KEY, was_on=True, want_on=False))

    def test_it_arrives_off_in_the_system_group(self):
        from core.platform_control import DEFAULT_COMPONENTS
        (seed,) = [c for c in DEFAULT_COMPONENTS if c["key"] == KEY]
        self.assertNotIn("is_enabled", seed)
        self.assertEqual((seed["category"], seed["name"]), ("system", NAME))
        row = _row()
        self.assertEqual((row.category, row.is_enabled, row.name),
                         ("system", False, NAME))

    def test_its_words_read_plainly_and_fit_the_column(self):
        from core.platform_control import DEFAULT_COMPONENTS
        (seed,) = [c for c in DEFAULT_COMPONENTS if c["key"] == KEY]
        words = seed["description"]
        self.assertLessEqual(len(words), 300, len(words))
        self.assertTrue(words.startswith(
            "Off (default): live rows are managed through weekends as "
            "before."), words)
        for said in ("nothing is sent to eToro", "forex",
                     "weekday-only commodity", "shut a day or more",
                     "pending close", "resumes at the reopen",
                     "Gold, oil, crypto, stocks: as before."):
            self.assertIn(said, words)

    def test_a_missing_row_reads_off(self):
        from bot_program.shut_guard import switch_on
        from core.platform_control import PlatformComponent
        self.assertFalse(switch_on())
        PlatformComponent.objects.filter(key=KEY).delete()
        self.assertFalse(switch_on())
        _switch(KEY, True)
        self.assertTrue(switch_on())

    def test_all_on_never_arms_it(self):
        resp = self.client.post("/admin-dashboard/bulk-toggle/",
                                {"category": "system", "action": "enable",
                                 "next": "ops"})
        self.assertRedirects(resp, "/ops/", fetch_redirect_response=False)
        self.assertFalse(_row().is_enabled)
        from core.platform_control import PlatformComponent
        self.assertTrue(PlatformComponent.objects.get(
            key="platform_master").is_enabled)

    def test_turning_it_on_takes_the_trading_pin(self):
        from bot_program.shut_guard import switch_on
        from portfolio.trader_profile import get_or_create_profile
        resp = self.client.post("/admin-dashboard/toggle/",
                                {"key": KEY, "next": "ops"})
        self.assertIn("trading PIN", _flashes(resp))
        self.assertFalse(_row().is_enabled)
        prof = get_or_create_profile(self.admin)
        prof.set_pin(TEST_PIN)
        prof.save()
        self.client.force_login(self.admin)   # the login after the PIN
        self.client.post("/admin-dashboard/toggle/",
                         {"key": KEY, "next": "ops", "want": "on",
                          "pin": "104729"})
        self.assertFalse(_row().is_enabled)
        resp = self.client.post("/admin-dashboard/toggle/",
                                {"key": KEY, "next": "ops", "want": "on",
                                 "pin": TEST_PIN})
        self.assertRedirects(resp, "/ops/", fetch_redirect_response=False)
        self.assertTrue(_row().is_enabled)
        self.assertTrue(switch_on())

    def test_turning_it_off_is_free(self):
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.filter(key=KEY).update(is_enabled=True)
        self.client.post("/admin-dashboard/toggle/",
                         {"key": KEY, "next": "ops", "want": "off"})
        self.assertFalse(_row().is_enabled)

    def test_the_shell_never_turns_it_on(self):
        out, err = StringIO(), StringIO()
        try:
            call_command("component", "on", KEY, stdout=out, stderr=err)
        except SystemExit:
            pass
        except Exception as e:  # noqa: BLE001 — a CommandError is a refusal
            err.write(str(e))
        self.assertFalse(_row().is_enabled)
        self.assertIn("trading PIN", out.getvalue() + err.getvalue())

    def test_ops_lists_it_with_its_pin_field(self):
        resp = self.client.get("/ops/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(f"<code>{KEY}</code>", body)
        self.assertIn(NAME, body)
        self.assertIn(f'aria-label="Trading PIN to turn {KEY} on"', body)


# ── the tick and the drain on the fake eToro ─────────────────────────────

class _Guard(TestCase):
    """The REAL manage tick and drain on the fake eToro, its clock pinned."""

    START = SAT

    def setUp(self):
        self.clock = H.FakeClock(start=self.START)
        self.clock.__enter__()
        self.addCleanup(self.clock.__exit__, None, None, None)
        _switch("aragorn", True)              # the care runs
        self.owner = H.user("guard_owner")
        self.cfgs = {}

    def guard(self, on=True):
        _switch(KEY, on)

    def cfg(self, cls, *, paper=False):
        name = f"{cls}-{'paper' if paper else 'live'}"
        if name not in self.cfgs:
            from bot_program.models import AssetBotConfig
            self.cfgs[name] = AssetBotConfig.objects.create(
                user=self.owner, asset_class=cls, name=name, enabled=True,
                mode="paper" if paper else "live", symbols=[],
                capital=Decimal("10000"))
        return self.cfgs[name]

    def row(self, symbol, *, protected=False, care=None, knob=False,
            opened_days_ago=None, status="OPEN", paper=False, demo=False):
        from bot_program.models import AssetBotTrade
        from instruments.models import Instrument
        cls, exch, entry, one_r = BOOK[symbol]
        Instrument.objects.get_or_create(
            symbol=symbol, defaults={"name": symbol, "asset_class": cls,
                                     "exchange": exch})
        cfg = self.cfg(cls, paper=paper)
        if knob:
            cfg.extras = {**(cfg.extras or {}), "breakeven_at_r": 1.0}
            cfg.save(update_fields=["extras"])
        # the world the row was filled in (base.AssetBot.VENUE_WORLDS: eToro's
        # demo answers "paper"), read by the close path against the client's
        meta = {"broker_env": "paper" if demo else "live"}
        if protected:
            meta.update(protected=True, protective_trade_id=f"p-{symbol}")
        if care is not None:
            peak_r, soft_r = care
            meta["care"] = {"peak": float(_price(symbol, peak_r)),
                            "soft_stop": float(_price(symbol, soft_r)),
                            "soft_why": "breakeven"}
        t = H.real_row(cfg, symbol, entry=entry, stop=entry - one_r,
                       target=entry + 3 * one_r, meta=meta, status=status,
                       position_id=f"p-{symbol}")
        if paper:
            t.paper = True
            t.metadata = {k: v for k, v in t.metadata.items()
                          if k not in ("broker", "broker_env",
                                       "broker_position_id")}
            t.save(update_fields=["paper", "metadata"])
        if opened_days_ago is not None:
            AssetBotTrade.objects.filter(pk=t.pk).update(
                opened_at=self.clock.now - timedelta(days=opened_days_ago))
            t.refresh_from_db()
        return t

    def etoro(self, marks, *, demo=False, writes="accept"):
        """The fake eToro: `marks` {symbol: R from the entry}; its book
        holds every row's position."""
        from bot_program.models import AssetBotTrade
        e = H.EtoroTrader({s: H.tick(_price(s, r)) for s, r in marks.items()},
                          writes=writes,
                          positions=[{"position_id": f"p-{t.symbol}",
                                      "symbol": t.symbol, "qty": str(t.qty),
                                      "side": t.side}
                                     for t in AssetBotTrade.objects.all()])
        if demo:
            e.demo, e.env = True, "demo"
        return e

    def tick(self, etoro):
        """One manage pass of every config, every client the fake eToro."""
        from bot_program.asset_engine.base import make_bot
        with H.route_to(etoro):
            for cfg in self.cfgs.values():
                make_bot(cfg).manage_positions()

    def drain(self, etoro):
        from bot_program.pending_closes import retry_all_pending_closes
        with H.route_to(etoro):
            return retry_all_pending_closes()

    @staticmethod
    def sent(etoro, symbol=None):
        """The writes the fake eToro was asked for, of `symbol`'s row."""
        return [w for w in etoro.writes_sent
                if symbol is None or f"p-{symbol}" in w or symbol in w]

    @staticmethod
    def note(trade):
        trade.refresh_from_db()
        return (trade.metadata or {}).get("shut_hold") or {}


# ── the manage tick ──────────────────────────────────────────────────────

class TheTickTests(_Guard):

    def _scenario(self, name, symbol, *, demo=False):
        kw, mark_r, write = SCENARIOS[name]
        if kw.get("knob"):
            _switch("aragorn", False)       # the knobs, not the care
        t = self.row(symbol, demo=demo, **kw)
        return t, self.etoro({symbol: mark_r}, demo=demo), write

    def test_off_a_saturday_forex_row_whose_soft_stop_is_crossed_sends_a_close(
            self):
        """Today: the care closes the row at eToro on a Saturday."""
        self.guard(False)
        t, etoro, write = self._scenario("the soft stop is crossed",
                                         "EURUSD")
        self.tick(etoro)
        self.assertEqual([w[0] for w in self.sent(etoro)], ["close_position"])
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSE_PENDING")
        self.assertEqual(self.note(t), {})

    def test_off_every_scenario_sends_on_a_saturday(self):
        """Today, for a pair and for copper alike: the soft-stop close, the
        time stop, the mirror, the knobs' stop move and the bot-side stop
        each reach eToro on a Saturday."""
        self.guard(False)
        for symbol in ("EURUSD", "HGUSD"):
            for name in SCENARIOS:
                with self.subTest(symbol=symbol, scenario=name):
                    from bot_program.models import AssetBotTrade
                    AssetBotTrade.objects.all().delete()
                    _switch("aragorn", True)
                    t, etoro, write = self._scenario(name, symbol)
                    self.tick(etoro)
                    self.assertIn(write, [w[0] for w in self.sent(etoro)])

    def test_on_nothing_is_sent_on_a_saturday_for_a_pair_or_copper(self):
        """Held before anything that can send: no write, no read either,
        the row OPEN, its stop, target and care as they were."""
        self.guard(True)
        for symbol in ("EURUSD", "HGUSD"):
            for name in SCENARIOS:
                for demo in (False, True):
                    with self.subTest(symbol=symbol, scenario=name,
                                      demo=demo):
                        from bot_program.models import AssetBotTrade
                        AssetBotTrade.objects.all().delete()
                        _switch("aragorn", True)
                        t, etoro, _write = self._scenario(name, symbol,
                                                          demo=demo)
                        before = (t.status, t.stop_loss, t.take_profit,
                                  (t.metadata or {}).get("care"))
                        self.tick(etoro)
                        self.assertEqual(etoro.writes_sent, [])
                        self.assertEqual(etoro.requests, [])
                        t.refresh_from_db()
                        self.assertEqual(
                            (t.status, t.stop_loss, t.take_profit,
                             (t.metadata or {}).get("care")), before)

    def test_on_the_held_row_says_so_in_one_plain_line(self):
        """On the row (metadata["shut_hold"], written once for the shut)
        and in the log, every tick."""
        self.guard(True)
        fx = self.row("EURUSD", protected=True, care=(1.5, 0.1))
        copper = self.row("HGUSD", protected=True, care=(1.5, 0.1))
        etoro = self.etoro({"EURUSD": 0.0, "HGUSD": 0.0})
        with self.assertLogs("bot_program.shut_guard", level="INFO") as logs:
            self.tick(etoro)
        said = "\n".join(logs.output)
        fx_words = ("held: market shut until Sun 22 Nov 22:00 UTC (the "
                    "guard): nothing is sent to eToro; the row is managed "
                    "again at the reopen")
        copper_words = ("held: market shut until Sun 22 Nov 23:00 UTC (the "
                        "guard): nothing is sent to eToro; the row is "
                        "managed again at the reopen")
        self.assertIn(f"EURUSD #{fx.id}: {fx_words}", said)
        self.assertIn(f"HGUSD #{copper.id}: {copper_words}", said)
        note = self.note(fx)
        self.assertEqual(note["words"], fx_words)
        self.assertEqual(note["until"], "2026-11-22T22:00:00+00:00")
        self.assertEqual(note["since"], SAT.isoformat())
        self.assertEqual(self.note(copper)["until"],
                         "2026-11-22T23:00:00+00:00")
        # the next tick logs again and leaves the note as it was
        self.clock.advance(minutes=5)
        with self.assertLogs("bot_program.shut_guard", level="INFO"):
            self.tick(etoro)
        self.assertEqual(self.note(fx)["since"], SAT.isoformat())
        self.assertEqual(etoro.writes_sent, [])

    def test_on_the_time_stop_warning_still_runs_while_held(self):
        """A ceiling that falls due over the weekend is still announced, as
        for a paper row; the close itself waits for the reopen."""
        from alerts.models import Notification
        self.guard(True)
        t = self.row("EURUSD", opened_days_ago=26)       # 624 h of 720
        etoro = self.etoro({"EURUSD": 0.2})
        self.tick(etoro)
        self.assertEqual(etoro.requests, [], "held: not even its mark read")
        self.assertTrue(Notification.objects.filter(
            title__startswith="⧗ Time stop nearing: EURUSD").exists())
        self.assertEqual(self.note(t)["until"], "2026-11-22T22:00:00+00:00")
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN")


# ── the reopen, on each instrument's own clock ───────────────────────────

class TheReopenTests(_Guard):

    def test_friday_2130_utc_a_pair_is_still_managed_and_held_from_2200(self):
        """eToro's FX week runs to 17:00 New York, 22:00 UTC in winter: the
        FOREX row's 21:00 UTC close is not the venue's."""
        self.guard(True)
        self.clock.now = FRI_2130
        managed = self.row("EURUSD", protected=True, care=(1.5, 0.1))
        etoro = self.etoro({"EURUSD": 0.0})
        self.tick(etoro)
        self.assertEqual([w[0] for w in self.sent(etoro, "EURUSD")],
                         ["close_position"])
        managed.refresh_from_db()
        self.assertEqual(managed.status, "CLOSE_PENDING")
        self.clock.now = FRI_2200
        held = self.row("GBPUSD", protected=True, care=(1.5, 0.1))
        etoro = self.etoro({"GBPUSD": 0.0})
        self.tick(etoro)
        self.assertEqual(self.sent(etoro, "GBPUSD"), [])
        held.refresh_from_db()
        self.assertEqual(held.status, "OPEN")

    def test_the_first_tick_after_the_reopen_manages_the_row(self):
        """Saturday held; Sunday 22:10 UTC the pair is managed again (its
        week reopened at 22:00) while copper, on Globex, still waits; at
        23:05 copper is managed too. The time stop that fell due while held
        fires then, at the reopen's price."""
        self.guard(True)
        fx = self.row("EURUSD", protected=True, care=(1.5, 0.1))
        copper = self.row("HGUSD", opened_days_ago=40)
        etoro = self.etoro({"EURUSD": 0.0, "HGUSD": 0.2})
        self.tick(etoro)
        self.assertEqual(etoro.writes_sent, [])
        self.clock.now = SUN_2210
        etoro = self.etoro({"EURUSD": 0.0, "HGUSD": 0.2})
        self.tick(etoro)
        self.assertEqual([w[0] for w in self.sent(etoro, "EURUSD")],
                         ["close_position"])
        self.assertEqual(self.sent(etoro, "HGUSD"), [])
        self.clock.now = CME_BACK
        etoro = self.etoro({"HGUSD": 0.2})
        self.tick(etoro)
        self.assertEqual([w[0] for w in self.sent(etoro, "HGUSD")],
                         ["close_position"])
        copper.refresh_from_db()
        self.assertEqual(copper.status, "CLOSE_PENDING")
        fx.refresh_from_db()
        self.assertEqual(fx.status, "CLOSE_PENDING")


# ── what the guard never touches ─────────────────────────────────────────

class TheUntouchedTests(_Guard):

    def test_on_a_gold_row_is_managed_on_saturday_beside_a_held_copper_row(
            self):
        """eToro trades GOLD all week: its soft-stop close goes on a
        Saturday, in the very walk that holds copper's."""
        self.guard(True)
        gold = self.row("XAUUSD", protected=True, care=(1.5, 0.1))
        copper = self.row("HGUSD", protected=True, care=(1.5, 0.1))
        etoro = self.etoro({"XAUUSD": 0.0, "HGUSD": 0.0})
        self.tick(etoro)
        self.assertEqual([w[0] for w in self.sent(etoro, "XAUUSD")],
                         ["close_position"])
        self.assertEqual(self.sent(etoro, "HGUSD"), [])
        self.assertEqual(self.note(gold), {})
        self.assertNotEqual(self.note(copper), {})

    def test_on_crypto_stock_and_paper_rows_are_managed_as_before(self):
        """Their bot-side stops are hit on a Saturday: each is closed as
        before (crypto and the stock at eToro, the paper row on paper),
        while the live pair beside them is held."""
        self.guard(True)
        btc = self.row("BTCUSD")
        aapl = self.row("AAPL")
        paper = self.row("GBPUSD", paper=True)
        fx = self.row("EURUSD")
        etoro = self.etoro({"BTCUSD": -1.5, "AAPL": -1.5, "GBPUSD": -1.5,
                            "EURUSD": -1.5})
        self.tick(etoro)
        self.assertEqual([w[0] for w in self.sent(etoro, "BTCUSD")],
                         ["close_position"])
        self.assertEqual([w[0] for w in self.sent(etoro, "AAPL")],
                         ["close_position"])
        self.assertEqual(self.sent(etoro, "EURUSD"), [])
        paper.refresh_from_db()
        self.assertEqual(paper.status, "CLOSED")
        for t in (btc, aapl, paper):
            self.assertEqual(self.note(t), {}, t.symbol)
        fx.refresh_from_db()
        self.assertEqual(fx.status, "OPEN")

    def test_on_the_kill_switch_and_the_close_button_still_send(self):
        """The operator's own acts go through while the tick holds."""
        from bot_program.engine.kill_switch import execute_kill_switch
        from bot_program.manual_close import execute_close
        self.guard(True)
        fx = self.row("EURUSD", protected=True, care=(1.5, 0.1))
        etoro = self.etoro({"EURUSD": 0.0})
        self.tick(etoro)
        self.assertEqual(etoro.writes_sent, [])
        with H.route_to(etoro):
            execute_close(self.owner, fx, pin_ok=True)
        self.assertEqual([w[0] for w in self.sent(etoro, "EURUSD")],
                         ["close_position"])
        copper = self.row("HGUSD", protected=True, care=(1.5, 0.1))
        etoro = self.etoro({"HGUSD": 0.0})
        with H.route_to(etoro):
            execute_kill_switch(self.owner, reason="guard test")
        self.assertIn("close_position",
                      [w[0] for w in self.sent(etoro, "HGUSD")])
        copper.refresh_from_db()
        self.assertNotEqual(copper.status, "OPEN")


# ── the pending-close drain ──────────────────────────────────────────────

class TheDrainTests(_Guard):

    def _pending(self, symbol="EURUSD"):
        return self.row(symbol, status="CLOSE_PENDING")

    def test_off_a_saturday_pass_resends_and_spends_an_attempt(self):
        """Today: eToro refuses the close on its shut market, the attempt
        is counted, and twelve such passes put the row in ERROR."""
        self.guard(False)
        t = self._pending()
        etoro = self.etoro({"EURUSD": 0.0}, writes="fail")
        self.drain(etoro)
        self.assertEqual([w[0] for w in self.sent(etoro)], ["close_position"])
        t.refresh_from_db()
        self.assertEqual(t.metadata.get("close_retry_attempts"), 1)
        for _ in range(11):
            self.clock.advance(minutes=5)
            self.drain(etoro)
        t.refresh_from_db()
        self.assertEqual(t.status, "ERROR")

    def test_on_a_saturday_pass_sends_nothing_and_spends_no_attempt(self):
        """Thirteen passes over a Saturday: nothing asked of eToro, no
        attempt, no ERROR, no "stranded" alert; the row says why."""
        from alerts.models import Notification
        self.guard(True)
        t = self._pending()
        etoro = self.etoro({"EURUSD": 0.0}, writes="fail")
        with self.assertLogs("bot_program.shut_guard", level="INFO") as logs:
            out = self.drain(etoro)
        self.assertEqual(out, {"pending": 1, "closed": 0, "still_pending": 1,
                               "held": 1})
        for _ in range(12):
            self.clock.advance(minutes=5)
            self.drain(etoro)
        self.assertEqual(etoro.requests, [])
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSE_PENDING")
        self.assertNotIn("close_retry_attempts", t.metadata)
        self.assertFalse(Notification.objects.filter(
            title__icontains="stranded").exists())
        words = ("held: market shut until Sun 22 Nov 22:00 UTC (the guard): "
                 "the close is not resent and no attempt is spent; the "
                 "drain resumes at the reopen")
        self.assertEqual(self.note(t)["words"], words)
        self.assertIn(f"EURUSD #{t.id}: {words}", "\n".join(logs.output))
        self.assertNotIn("manual_close_claim", t.metadata)

    def test_on_the_drain_resumes_at_the_reopen(self):
        self.guard(True)
        t = self._pending()
        etoro = self.etoro({"EURUSD": 0.0}, writes="fail")
        self.drain(etoro)
        self.assertEqual(etoro.writes_sent, [])
        self.clock.now = SUN_2210
        out = self.drain(etoro)
        self.assertNotIn("held", out)
        self.assertEqual([w[0] for w in self.sent(etoro)], ["close_position"])
        t.refresh_from_db()
        self.assertEqual(t.metadata.get("close_retry_attempts"), 1)

    def test_on_a_copper_row_waits_for_globex_and_a_gold_row_is_drained(self):
        self.guard(True)
        copper = self._pending("HGUSD")
        gold = self._pending("XAUUSD")
        etoro = self.etoro({"HGUSD": 0.0, "XAUUSD": 0.0}, writes="fail")
        out = self.drain(etoro)
        self.assertEqual(out["held"], 1)
        self.assertEqual(self.sent(etoro, "HGUSD"), [])
        self.assertEqual([w[0] for w in self.sent(etoro, "XAUUSD")],
                         ["close_position"])
        gold.refresh_from_db()
        copper.refresh_from_db()
        self.assertEqual(gold.metadata.get("close_retry_attempts"), 1)
        self.assertNotIn("close_retry_attempts", copper.metadata)
        self.clock.now = SUN_2210
        self.drain(etoro)
        self.assertEqual(self.sent(etoro, "HGUSD"), [])

    def test_on_the_close_button_still_retries_a_held_row(self):
        """The drain holds the row; the operator's CLOSE on it goes."""
        from bot_program.manual_close import execute_close
        self.guard(True)
        t = self._pending()
        etoro = self.etoro({"EURUSD": 0.0}, writes="accept")
        self.drain(etoro)
        self.assertEqual(etoro.writes_sent, [])
        with H.route_to(etoro):
            execute_close(self.owner, t, pin_ok=True)
        self.assertEqual([w[0] for w in self.sent(etoro)], ["close_position"])


class TheGuardsOwnReadTests(_Guard):
    """shut_guard.held(trade, client): the one test the tick and the drain
    share, readable on its own."""

    def test_held_names_the_reopen_only_for_rows_in_scope(self):
        from bot_program.shut_guard import held
        self.guard(True)
        fx = self.row("EURUSD")
        gold = self.row("XAUUSD")
        paper = self.row("GBPUSD", paper=True)
        btc = self.row("BTCUSD")
        etoro = self.etoro({})
        out = held(fx, etoro)
        self.assertEqual((out["closed"], out["reopens"]),
                         (FRI_2200, _at(2026, 11, 22, 22)))
        for t in (gold, paper, btc):
            self.assertIsNone(held(t, etoro), t.symbol)
        self.assertIsNone(held(fx, etoro, now=FRI_2130))
        self.guard(False)
        self.assertIsNone(held(fx, etoro))

    def test_a_row_another_venue_carries_is_never_held(self):
        from bot_program.shut_guard import held
        self.guard(True)
        fx = self.row("EURUSD")
        fx.metadata = {**fx.metadata, "broker": "oanda"}
        fx.save(update_fields=["metadata"])
        self.assertIsNone(held(fx, self.etoro({})))
        bare = self.row("GBPUSD")
        bare.metadata = {k: v for k, v in bare.metadata.items()
                         if k != "broker"}
        bare.save(update_fields=["metadata"])
        self.assertIsNotNone(held(bare, self.etoro({})),
                             "no carrier stamp: the eToro client answers")
        self.assertIsNone(held(bare, mock.MagicMock()),
                          "no carrier stamp, another client: not eToro's")
