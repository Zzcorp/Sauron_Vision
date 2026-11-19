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
while its instrument is inside a shut of 24 hours or more on eToro's own
published edges (market_data/shut_bars.shut_for_a_day_now: a pair from
Friday 16:30 to Sunday 17:05 New York; copper from 30 minutes before
Globex's Friday close to its Sunday reopen; Christmas Day and New Year's
Day stretch the weekend), is HELD: the tick reads nothing and sends nothing
for it, and the drain neither resends its close nor counts an attempt.
eToro's all-week instruments (gold here), EURUSD (whose weekend hours at
eToro are unsettled: a hold would leave it only eToro's resting stop),
crypto, stocks and paper rows are managed as before, and so is everything
the operator does himself: the kill switch and the CLOSE button.

Fakes only: the feed harness's fake eToro (tests/feed/harness.py) records
every request and refuses every write unless a scenario accepts it.
Invented prices; public catalogue symbols only.

Clocks, UTC, in winter (New York on EST since 1 November):
  FRI_2125  Fri 20 Nov 21:25  eToro still trades its pairs and copper
  FRI_2130  Fri 20 Nov 21:30  eToro's own close of both (its market-hours
                              page), half an hour before the FX week and
                              Globex, which the bar rule keeps
  FRI_2200  Fri 20 Nov 22:00  the FX week and Globex shut
  SAT       Sat 21 Nov 12:00  inside both shuts
  SUN_2210  Sun 22 Nov 22:10  pairs reopened at 22:05; Globex still shut
  CME_BACK  Sun 22 Nov 23:05  Globex reopened at 23:00
  XMAS      Fri 25 Dec 12:00  Christmas Day: the weekend began on Thursday

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

FRI_2125 = datetime(2026, 11, 20, 21, 25, tzinfo=UTC)
FRI_2130 = datetime(2026, 11, 20, 21, 30, tzinfo=UTC)
FRI_2200 = datetime(2026, 11, 20, 22, 0, tzinfo=UTC)
SAT = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
SUN_2210 = datetime(2026, 11, 22, 22, 10, tzinfo=UTC)
CME_BACK = datetime(2026, 11, 22, 23, 5, tzinfo=UTC)
XMAS = datetime(2026, 12, 25, 12, 0, tzinfo=UTC)
#: eToro's own edges of this weekend (its market-hours page, winter UTC):
#: pairs shut Friday 21:30 to Sunday 22:05, copper Friday 21:30 to Sunday
#: 23:00.
PAIR_WEEKEND = (FRI_2130, datetime(2026, 11, 22, 22, 5, tzinfo=UTC))
COPPER_WEEKEND = (FRI_2130, datetime(2026, 11, 22, 23, 0, tzinfo=UTC))

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

    def test_a_pair_reads_etoros_published_week(self):
        """Winter: eToro shuts its pairs at Friday 21:30 UTC and reopens
        them at Sunday 22:05 UTC ("Market Opens: Sunday 22:05; Market
        Closes: Friday 21:30", its market-hours page), half an hour before
        the FX week's 17:00 New York close and five minutes after its
        reopen."""
        fx = _inst("forex", "FOREX", "GBPUSD")
        self.assertIsNone(self._shut(fx, FRI_2125))
        self.assertEqual(self._shut(fx, FRI_2130), PAIR_WEEKEND)
        self.assertEqual(self._shut(fx, FRI_2200), PAIR_WEEKEND)
        self.assertEqual(self._shut(fx, SAT), PAIR_WEEKEND)
        self.assertEqual(self._shut(fx, _at(2026, 11, 22, 22, 4)),
                         PAIR_WEEKEND)
        self.assertIsNone(self._shut(fx, _at(2026, 11, 22, 22, 5)))
        self.assertIsNone(self._shut(fx, _at(2026, 11, 18, 12)))

    def test_a_pair_in_summer(self):
        """New York on EDT: Friday 20:30 to Sunday 21:05 UTC."""
        fx = _inst("forex", "FOREX", "GBPUSD")
        self.assertIsNone(self._shut(fx, _at(2026, 7, 10, 20, 29)))
        self.assertEqual(self._shut(fx, _at(2026, 7, 11, 12)),
                         (_at(2026, 7, 10, 20, 30), _at(2026, 7, 12, 21, 5)))
        self.assertIsNone(self._shut(fx, _at(2026, 7, 12, 21, 5)))

    def test_a_weekday_commodity_reads_etoros_edges_on_globex(self):
        """Copper keeps Globex's week at eToro, shut half an hour earlier:
        Friday 21:30 to Sunday 23:00 UTC in winter (eToro's COPPER.FUT row:
        "Market Opens: Sunday 23:00; Market Closes: Friday 21:30"); the
        daily hour's break is no shut of a day and holds nothing."""
        copper = _inst("commodity", "COMEX", "HGUSD")
        self.assertIsNone(self._shut(copper, FRI_2125))
        self.assertEqual(self._shut(copper, FRI_2130), COPPER_WEEKEND)
        self.assertEqual(self._shut(copper, SAT), COPPER_WEEKEND)
        self.assertEqual(self._shut(copper, SUN_2210), COPPER_WEEKEND)
        self.assertIsNone(self._shut(copper, CME_BACK))
        self.assertIsNone(self._shut(copper, _at(2026, 11, 17, 22, 30)))

    def test_the_bar_rule_keeps_the_wider_week(self):
        """Between eToro's close and the FX week's or Globex's, the guard
        holds while the bar rule still keeps the bars: a bar it keeps there
        is a flat candle at most, while a row held from eToro's own close is
        never sent an order eToro cannot fill."""
        from market_data.shut_bars import holds_no_open_time
        for inst in (_inst("forex", "FOREX", "GBPUSD"),
                     _inst("commodity", "COMEX", "HGUSD")):
            for minute in (30, 45):
                at = FRI_2125.replace(minute=minute)
                self.assertIsNotNone(self._shut(inst, at), inst.symbol)
                self.assertFalse(holds_no_open_time(inst, "15m", at),
                                 inst.symbol)

    def test_an_unknown_exchange_reads_the_class_clock(self):
        """"" (/setup/) and "ETORO" (the legacy sync) name no table: the
        class's default clock, CME."""
        for exch in ("", "ETORO"):
            other = _inst("commodity", exch, "HGUSD")
            self.assertEqual(self._shut(other, SAT), COPPER_WEEKEND, exch)
            self.assertIsNone(self._shut(other, _at(2026, 11, 17, 22, 30)))

    def test_a_friday_holiday_stretches_the_hold_back_to_thursday(self):
        """Christmas Day 2026 and New Year's Day 2027 are Fridays on which
        the FX market and Globex hold no session: a pair and copper are held
        from Thursday at eToro's usual hour, 21:30 UTC, to the weekend's
        reopen."""
        fx = _inst("forex", "FOREX", "GBPUSD")
        copper = _inst("commodity", "COMEX", "HGUSD")
        for thursday in (_at(2026, 12, 24), _at(2026, 12, 31)):
            closed = thursday + timedelta(hours=21, minutes=30)
            sunday = thursday + timedelta(days=3)
            for at in (closed, thursday + timedelta(days=1, hours=12),
                       sunday + timedelta(hours=21)):
                self.assertEqual(
                    self._shut(fx, at),
                    (closed, sunday + timedelta(hours=22, minutes=5)), at)
                self.assertEqual(self._shut(copper, at),
                                 (closed, sunday + timedelta(hours=23)), at)
            before = closed - timedelta(minutes=5)
            self.assertIsNone(self._shut(fx, before))
            self.assertIsNone(self._shut(copper, before))

    def test_eurusd_is_never_held_while_its_weekend_bars_still_go(self):
        """eToro's weekend hours for EURUSD are unsettled (one page lists
        it 24/7, another weekday-only). A hold would leave it only eToro's
        resting stop for two days if eToro trades it, so the guard never
        holds it; the bar rule still drops its weekend candles, its safe
        side either way."""
        from market_data.shut_bars import holds_no_open_time
        for exch in ("FOREX", ""):
            eur = _inst("forex", exch, "EURUSD")
            for at in (FRI_2130, SAT, XMAS):
                self.assertIsNone(self._shut(eur, at), (exch, at))
            self.assertTrue(holds_no_open_time(eur, "4h", SAT))
            self.assertTrue(holds_no_open_time(eur, "4h", XMAS))

    def test_an_lme_commodity_is_never_held(self):
        """LME's clock is not one the venue keeps (LSE's hours stand in for
        it): a commodity filed under it is never held."""
        for at in (SAT, _at(2026, 11, 20, 17), _at(2026, 11, 23, 7)):
            self.assertIsNone(self._shut(_inst("commodity", "LME", "X"),
                                         at), at)

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
        fx = _inst(" Forex ", "", "GBPUSD")
        self.assertEqual(self._shut(fx, SAT.replace(tzinfo=None)),
                         PAIR_WEEKEND, "naive is UTC")
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
                     "holidays too", "pending close", "until the reopen",
                     "EURUSD, gold, oil, crypto, stocks: as before."):
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
        from bot_program.models import AssetBotTrade
        self.guard(False)
        for symbol in ("EURUSD", "HGUSD"):
            for name in SCENARIOS:
                with self.subTest(symbol=symbol, scenario=name):
                    AssetBotTrade.objects.all().delete()
                    _switch("aragorn", True)
                    t, etoro, write = self._scenario(name, symbol)
                    self.tick(etoro)
                    self.assertIn(write, [w[0] for w in self.sent(etoro)])

    def test_on_nothing_is_sent_on_a_saturday_for_a_pair_or_copper(self):
        """Held before anything that can send: no write, no read either,
        the row OPEN, its stop, target and care as they were."""
        from bot_program.models import AssetBotTrade
        self.guard(True)
        for symbol in ("GBPUSD", "HGUSD"):
            for name in SCENARIOS:
                for demo in (False, True):
                    with self.subTest(symbol=symbol, scenario=name,
                                      demo=demo):
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
        fx = self.row("GBPUSD", protected=True, care=(1.5, 0.1))
        copper = self.row("HGUSD", protected=True, care=(1.5, 0.1))
        etoro = self.etoro({"GBPUSD": 0.0, "HGUSD": 0.0})
        with self.assertLogs("bot_program.shut_guard", level="INFO") as logs:
            self.tick(etoro)
        said = "\n".join(logs.output)
        fx_words = ("held: market shut until Sun 22 Nov 22:05 UTC (the "
                    "guard): nothing is sent to eToro; the row is managed "
                    "again at the reopen")
        copper_words = ("held: market shut until Sun 22 Nov 23:00 UTC (the "
                        "guard): nothing is sent to eToro; the row is "
                        "managed again at the reopen")
        self.assertIn(f"GBPUSD #{fx.id}: {fx_words}", said)
        self.assertIn(f"HGUSD #{copper.id}: {copper_words}", said)
        note = self.note(fx)
        self.assertEqual(note["words"], fx_words)
        self.assertEqual(note["until"], "2026-11-22T22:05:00+00:00")
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
        t = self.row("GBPUSD", opened_days_ago=26)       # 624 h of 720
        etoro = self.etoro({"GBPUSD": 0.2})
        self.tick(etoro)
        self.assertEqual(etoro.requests, [], "held: not even its mark read")
        self.assertTrue(Notification.objects.filter(
            title__startswith="⧗ Time stop nearing: GBPUSD").exists())
        self.assertEqual(self.note(t)["until"], "2026-11-22T22:05:00+00:00")
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN")

    def test_on_a_eurusd_row_is_managed_on_saturday_beside_a_held_pair(
            self):
        """EURUSD's weekend hours at eToro are unsettled: its row is
        managed as before (its soft-stop close goes on a Saturday), in the
        very walk that holds GBPUSD's."""
        self.guard(True)
        eur = self.row("EURUSD", protected=True, care=(1.5, 0.1))
        gbp = self.row("GBPUSD", protected=True, care=(1.5, 0.1))
        etoro = self.etoro({"EURUSD": 0.0, "GBPUSD": 0.0})
        self.tick(etoro)
        self.assertEqual([w[0] for w in self.sent(etoro, "EURUSD")],
                         ["close_position"])
        self.assertEqual(self.sent(etoro, "GBPUSD"), [])
        self.assertEqual(self.note(eur), {})
        self.assertNotEqual(self.note(gbp), {})


# ── the reopen, on each instrument's own clock ───────────────────────────

class TheReopenTests(_Guard):

    def test_friday_a_pair_and_copper_are_managed_to_2130_utc_then_held(
            self):
        """eToro closes its pairs and copper at Friday 21:30 UTC in winter
        (its market-hours page), half an hour before the FX week and
        Globex: at 21:25 both rows are still managed, from 21:30 held."""
        from bot_program.models import AssetBotTrade
        self.guard(True)
        for symbol in ("GBPUSD", "HGUSD"):
            with self.subTest(symbol=symbol):
                AssetBotTrade.objects.all().delete()
                self.clock.now = FRI_2125
                managed = self.row(symbol, protected=True, care=(1.5, 0.1))
                etoro = self.etoro({symbol: 0.0})
                self.tick(etoro)
                self.assertEqual([w[0] for w in self.sent(etoro, symbol)],
                                 ["close_position"])
                managed.refresh_from_db()
                self.assertEqual(managed.status, "CLOSE_PENDING")
                AssetBotTrade.objects.all().delete()
                self.clock.now = FRI_2130
                held = self.row(symbol, protected=True, care=(1.5, 0.1))
                etoro = self.etoro({symbol: 0.0})
                self.tick(etoro)
                self.assertEqual(self.sent(etoro, symbol), [])
                held.refresh_from_db()
                self.assertEqual(held.status, "OPEN")

    def test_the_first_tick_after_the_reopen_manages_the_row(self):
        """Saturday held; Sunday 22:10 UTC the pair is managed again (eToro
        reopened it at 22:05) while copper, on Globex, still waits; at
        23:05 copper is managed too. The time stop that fell due while held
        fires then, at the reopen's price."""
        self.guard(True)
        fx = self.row("GBPUSD", protected=True, care=(1.5, 0.1))
        copper = self.row("HGUSD", opened_days_ago=40)
        etoro = self.etoro({"GBPUSD": 0.0, "HGUSD": 0.2})
        self.tick(etoro)
        self.assertEqual(etoro.writes_sent, [])
        self.clock.now = SUN_2210
        etoro = self.etoro({"GBPUSD": 0.0, "HGUSD": 0.2})
        self.tick(etoro)
        self.assertEqual([w[0] for w in self.sent(etoro, "GBPUSD")],
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


# ── a holiday: Christmas Day 2026 is a Friday ────────────────────────────

class TheHolidayTests(_Guard):
    """The FX market and Globex hold no session on Christmas Day: eToro's
    pairs and copper are shut from Thursday 24 December at 21:30 UTC to the
    weekend's reopen. Before the holiday table the guard read the day as
    open and sent."""

    START = XMAS

    def test_off_christmas_day_is_managed_as_before(self):
        self.guard(False)
        self.row("GBPUSD", protected=True, care=(1.5, 0.1))
        etoro = self.etoro({"GBPUSD": 0.0})
        self.tick(etoro)
        self.assertEqual([w[0] for w in self.sent(etoro, "GBPUSD")],
                         ["close_position"])

    def test_on_nothing_is_sent_on_christmas_day_for_a_pair_or_copper(self):
        """Held as on a Saturday, to the weekend's reopen; EURUSD, whose
        weekend hours are unsettled, is managed as before."""
        self.guard(True)
        fx = self.row("GBPUSD", protected=True, care=(1.5, 0.1))
        copper = self.row("HGUSD", protected=True, care=(1.5, 0.1))
        eur = self.row("EURUSD", protected=True, care=(1.5, 0.1))
        etoro = self.etoro({"GBPUSD": 0.0, "HGUSD": 0.0, "EURUSD": 0.0})
        self.tick(etoro)
        self.assertEqual(self.sent(etoro, "GBPUSD"), [])
        self.assertEqual(self.sent(etoro, "HGUSD"), [])
        self.assertEqual([w[0] for w in self.sent(etoro, "EURUSD")],
                         ["close_position"])
        self.assertEqual(self.note(fx)["until"], "2026-12-27T22:05:00+00:00")
        self.assertEqual(self.note(copper)["until"],
                         "2026-12-27T23:00:00+00:00")
        self.assertEqual(self.note(eur), {})


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
        paper = self.row("EURUSD", paper=True)
        fx = self.row("GBPUSD")
        etoro = self.etoro({"BTCUSD": -1.5, "AAPL": -1.5, "GBPUSD": -1.5,
                            "EURUSD": -1.5})
        self.tick(etoro)
        self.assertEqual([w[0] for w in self.sent(etoro, "BTCUSD")],
                         ["close_position"])
        self.assertEqual([w[0] for w in self.sent(etoro, "AAPL")],
                         ["close_position"])
        self.assertEqual(self.sent(etoro, "GBPUSD"), [])
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
        fx = self.row("GBPUSD", protected=True, care=(1.5, 0.1))
        etoro = self.etoro({"GBPUSD": 0.0})
        self.tick(etoro)
        self.assertEqual(etoro.writes_sent, [])
        with H.route_to(etoro):
            execute_close(self.owner, fx, pin_ok=True)
        self.assertEqual([w[0] for w in self.sent(etoro, "GBPUSD")],
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

    def _pending(self, symbol="GBPUSD"):
        return self.row(symbol, status="CLOSE_PENDING")

    def test_off_a_saturday_pass_resends_and_spends_an_attempt(self):
        """Today: eToro refuses the close on its shut market, the attempt
        is counted, and twelve such passes put the row in ERROR."""
        self.guard(False)
        t = self._pending()
        etoro = self.etoro({"GBPUSD": 0.0}, writes="fail")
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
        etoro = self.etoro({"GBPUSD": 0.0}, writes="fail")
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
        words = ("held: market shut until Sun 22 Nov 22:05 UTC (the guard): "
                 "the close is not resent and no attempt is spent; the "
                 "drain resumes at the reopen")
        self.assertEqual(self.note(t)["words"], words)
        self.assertIn(f"GBPUSD #{t.id}: {words}", "\n".join(logs.output))
        self.assertNotIn("manual_close_claim", t.metadata)

    def test_on_a_eurusd_pending_close_is_drained_as_before(self):
        """EURUSD is never held: its pending close is resent on a Saturday
        and the attempt counted, as with the switch OFF."""
        self.guard(True)
        t = self._pending("EURUSD")
        etoro = self.etoro({"EURUSD": 0.0}, writes="fail")
        out = self.drain(etoro)
        self.assertNotIn("held", out)
        self.assertEqual([w[0] for w in self.sent(etoro)], ["close_position"])
        t.refresh_from_db()
        self.assertEqual(t.metadata.get("close_retry_attempts"), 1)

    def test_on_the_drain_resumes_at_the_reopen(self):
        self.guard(True)
        t = self._pending()
        etoro = self.etoro({"GBPUSD": 0.0}, writes="fail")
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
        etoro = self.etoro({"GBPUSD": 0.0}, writes="accept")
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
        fx = self.row("GBPUSD")
        gold = self.row("XAUUSD")
        eur = self.row("EURUSD")
        paper = self.row("HGUSD", paper=True)
        btc = self.row("BTCUSD")
        etoro = self.etoro({})
        out = held(fx, etoro)
        self.assertEqual((out["closed"], out["reopens"]), PAIR_WEEKEND)
        self.assertEqual(out["until"], "Sun 22 Nov 22:05 UTC")
        for t in (gold, eur, paper, btc):
            self.assertIsNone(held(t, etoro), t.symbol)
        self.assertIsNone(held(fx, etoro, now=FRI_2125))
        self.assertIsNotNone(held(fx, etoro, now=FRI_2130))
        self.guard(False)
        self.assertIsNone(held(fx, etoro))

    def test_a_row_another_venue_carries_is_never_held(self):
        from bot_program.shut_guard import held
        self.guard(True)
        fx = self.row("GBPUSD")
        fx.metadata = {**fx.metadata, "broker": "oanda"}
        fx.save(update_fields=["metadata"])
        self.assertIsNone(held(fx, self.etoro({})))
        bare = self.row("HGUSD")
        bare.metadata = {k: v for k, v in bare.metadata.items()
                         if k != "broker"}
        bare.save(update_fields=["metadata"])
        self.assertIsNotNone(held(bare, self.etoro({})),
                             "no carrier stamp: the eToro client answers")
        self.assertIsNone(held(bare, mock.MagicMock()),
                          "no carrier stamp, another client: not eToro's")
