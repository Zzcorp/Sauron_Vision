"""The Morgul guards: the orcs that save Sauron from itself (2026-09-26).

The operator, 2026-09-26/27: "we need a 'Morgul', or orcs to save Sauron
from itself". On Saturday 2026-09-26 at 13:53 UTC two paper forex
positions were closed while forex was shut, and nothing noticed. Pinned
here (bot_program/morgul.py):
  - every guard fires on a crafted row and stays quiet on a healthy one;
  - THE SATURDAY REPLAY: the EURCAD and GBPCAD closes of 13:53 UTC; the
    winter forex hour and the New York holidays, on the paper venue's
    own clock;
  - no false alarm the review measured: a live index CFD outside the cash
    session, a close the retry drained, a working fill noticed late, the
    demo world's proof positions, a stop-out the reconcile has not booked
    yet, stale or other-world margin cells, a close queued while the
    market is shut, a bot set never to halt on drawdown;
  - the frame: a raising guard is a finding, never silence; a finding is
    said once per three hours, at once when it turns critical, an event
    once; one "back to normal" line when it stops; a blind guard, or a
    subject a guard could not judge, keeps what it last saw; one run at a
    time;
  - the brake: OFF (or the guards off) says what it would stop; ON stops
    exactly the right configs, once, closes nothing, sends no order,
    changes no row; armed after a finding was said, stops it on the next
    run; says what the stopped bots leave unprotected; is
    announced even when Telegram refused or the run died after it; holds
    back when no staff chat can be told; is never switched on in bulk;
  - the command prints and sends nothing without --send;
  - the /health/ row, the Eye's /status line;
  - every message English (no French word, no snake_case, no None),
    escaped, inside Telegram's limits;
  - the wiring: two registry rows OFF on arrival, the beat entry, the fast
    route, the guarded task, the command in the ops registry (not on the
    web); the module carries no call that trades.

Run with:  python manage.py test tests.test_morgul
"""
import inspect
import re
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from bot_program import morgul
from bot_program import telegram_eye as eye

GROUP = "-5337454557"
SEND = "bot_program.notifications._send_telegram"
FAULTS = "core.component_digest.collect_faults"
CLEAR = {"errors": [], "warnings": [], "silent": [], "feeds": [],
         "checked": 54}
UTC = dt_tz.utc
FRI = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)
#: The incident as measured on the VPS (p58): manual_close.execute_close
#: booked #108 EURCAD and #109 GBPCAD at 13:53:54 UTC on a Saturday.
SAT_CLOSE = datetime(2026, 9, 26, 13, 53, 54, tzinfo=UTC)
SAT_NOW = datetime(2026, 9, 26, 14, 0, tzinfo=UTC)
#: A Wednesday afternoon: forex open, New York open since 13:30 UTC.
WED = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)
#: The Friday of the first real week: New York shuts at 20:00 UTC.
FRI_CLOSE = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
SNAKE = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")
ACCENTED = re.compile(r"[À-ÖØ-öø-ÿŒœ]")
FRENCH = (" le ", " la ", " les ", " des ", " est ", " pas ", " une ",
          " du ", " et ")
LIVE_ETORO = {"broker": "etoro", "broker_env": "live", "protected": True,
              "protective_trade_id": "3588477891"}
DEMO_ETORO = dict(LIVE_ETORO, broker_env="paper")


def _staff(name="operator", chat=GROUP):
    from alerts.models import UserNotificationPrefs
    from portfolio.trader_profile import TraderProfile
    user = User.objects.create_user(username=name, password="x",
                                    is_staff=True)
    profile, _ = TraderProfile.objects.get_or_create(user=user)
    profile.notify_channel = "telegram"
    profile.save()
    prefs, _ = UserNotificationPrefs.objects.get_or_create(user=user)
    prefs.telegram_chat_id = chat
    prefs.save()
    return user


def _cfg(user, name="Forex swing", asset_class="forex", *, enabled=True,
         mode="paper", capital="10000", daily=2.0, extras=None, symbols=(),
         **fields):
    from bot_program.asset_models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, enabled=enabled,
        mode=mode, capital=Decimal(capital), max_daily_loss_pct=daily,
        symbols=list(symbols), extras=dict(extras or {}), **fields)


def _trade(cfg, symbol="EURCAD", *, side="BUY", qty="1000", entry="1.6120",
           stop="1.6000", paper=True, status="OPEN", exit_price=None,
           pnl="0", metadata=None, opened=None, closed=None, reason=""):
    from bot_program.asset_models import AssetBotTrade
    trade = AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(qty), entry_price=Decimal(entry),
        stop_loss=None if stop is None else Decimal(stop),
        exit_price=None if exit_price is None else Decimal(exit_price),
        pnl=None if pnl is None else Decimal(pnl), paper=paper,
        status=status, metadata=dict(metadata or {}), closed_at=closed,
        reason=reason)
    if opened is not None:
        AssetBotTrade.objects.filter(pk=trade.pk).update(opened_at=opened)
        trade.refresh_from_db()
    return trade


def _component(key, on=True, last_run=None):
    from core.platform_control import PlatformComponent
    PlatformComponent.objects.update_or_create(
        key=key, defaults={"name": key, "category": "system",
                           "is_enabled": on, "last_run_at": last_run})


def _arm():
    """The brake armed: its own switch and the guards'."""
    _component(morgul.COMPONENT_KEY)
    _component(morgul.BRAKE_KEY)


def _etoro(user, **fields):
    from bot_program.models import EtoroAccount
    acct = EtoroAccount.objects.create(user=user, **fields)
    acct.set_credentials("the-api-key", "the-user-key")
    acct.save()
    return acct


def _mark(symbol, asset_class, at, source="oanda_stream", last="1.08"):
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    quote = LiveQuote.objects.create(instrument=inst, last=Decimal(last),
                                     source=source)
    LiveQuote.objects.filter(pk=quote.pk).update(updated_at=at)


def _check(key, now, persist=False):
    ctx = morgul.Context(now, persist)
    guard = morgul.GUARD[key]
    return ctx, guard.check(ctx, guard)


def _by_subject(found):
    return {f.subject: f for f in found}


def _texts(send):
    from bot_program.notifications import _telegram_text
    return [_telegram_text(c.args[1], c.args[2], lines=c.kwargs.get("lines"),
                           mark=c.kwargs.get("mark", ""))
            for c in send.call_args_list]


def _scripted(key="scripted", name="Scripted", severity="warning",
              brake=False):
    """A guard whose findings a test sets: box["subjects"], ["event"],
    ["severity"], ["user"], ["configs"], and ["blind"] (subjects it says
    it could not judge)."""
    box = {"subjects": [], "event": False, "severity": None, "user": None,
           "configs": (), "blind": []}

    def check(ctx, guard):
        if box["blind"]:
            ctx.blind(guard, box["blind"])
        return [guard.finding(s, label=f"Subject {s}",
                              facts=[f"Fact about {s}"], event=box["event"],
                              severity=box["severity"], user=box["user"],
                              configs=box["configs"])
                for s in box["subjects"]]
    return morgul.Guard(key, name, severity, f"Morgul — {name.lower()}",
                        check, brake=brake), box


def _loss(cfg, now, pnl="-900", metadata=None):
    return _trade(cfg, "AAPL", entry="336", stop="326", paper=False,
                  status="CLOSED", exit_price="300", pnl=pnl,
                  metadata=metadata, opened=now - timedelta(hours=3),
                  closed=now - timedelta(hours=1))


class _Case(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = _staff()


# ── G1: the Saturday replay ──────────────────────────────────────────────

class MarketShutTests(_Case):
    def test_the_saturday_eurcad_and_gbpcad_closes_are_caught(self):
        cfg = _cfg(self.user)
        # the two rows as they were booked: Friday's last OANDA price,
        # written under a fresh time by the stream's reconnect snapshot
        eurcad = _trade(cfg, "EURCAD", qty="7900", entry="1.60725571",
                        stop="1.5990", status="CLOSED",
                        exit_price="1.61035395", pnl="17.3817", opened=FRI,
                        closed=SAT_CLOSE, reason="manual | closed:MANUAL")
        gbpcad = _trade(cfg, "GBPCAD", qty="22600", entry="1.8718",
                        stop="1.8600", status="CLOSED",
                        exit_price="1.87265272", pnl="19.2555",
                        opened=FRI + timedelta(hours=1), closed=SAT_CLOSE,
                        reason="manual | closed:MANUAL")
        ctx, found = _check("market_shut", SAT_NOW)
        by = _by_subject(found)
        self.assertEqual(sorted(by), sorted([f"trade:{eurcad.pk}",
                                             f"trade:{gbpcad.pk}"]))
        first = by[f"trade:{eurcad.pk}"]
        self.assertEqual(first.severity, "critical")
        self.assertTrue(first.event)
        self.assertTrue(first.brakes)
        self.assertEqual(first.configs, [cfg.pk])
        self.assertIn("Closed 2026-09-26 13:53 UTC at 1.61035395",
                      first.facts)
        self.assertIn("Market shut then: Forex Market", first.facts)
        self.assertEqual(first.label,
                         f"EURCAD long #{eurcad.pk} · paper · "
                         f"Forex swing #{cfg.pk}")
        self.assertIn("Closed 2026-09-26 13:53 UTC at 1.87265272",
                      by[f"trade:{gbpcad.pk}"].facts)

    def test_a_healthy_week_is_quiet_and_what_was_not_judged_is_said(self):
        cfg = _cfg(self.user)
        friday = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)
        _trade(cfg, "EURUSD", status="CLOSED", exit_price="1.08",
               opened=friday - timedelta(hours=2), closed=friday)
        # 21:02 on Friday: two minutes past the close, a tick in flight
        _trade(cfg, "USDJPY", status="CLOSED", exit_price="150.1",
               opened=friday, closed=friday + timedelta(minutes=62))
        crypto = _cfg(self.user, "Crypto momentum", "crypto")
        _trade(crypto, "BTCUSDT", status="CLOSED", exit_price="60000",
               opened=SAT_CLOSE - timedelta(hours=2), closed=SAT_CLOSE)
        cfds = _cfg(self.user, "CFDs", "cfd")
        _trade(cfds, "UK100", status="CLOSED", exit_price="8000",
               opened=SAT_CLOSE - timedelta(hours=2), closed=SAT_CLOSE)
        live = _cfg(self.user, "Forex live", mode="live")
        _trade(live, "GBPUSD", paper=False, status="CLOSED",
               exit_price="1.27", opened=FRI, closed=SAT_CLOSE,
               reason="momentum | reconciled-orphan",
               metadata={"exit_price_inferred": True})
        ctx, found = _check("market_shut", SAT_NOW)
        self.assertEqual(found, [])
        notes = " ".join(ctx.notes)
        self.assertIn("does not model CFDs (1)", notes)
        self.assertIn("1 close booked by reconciliation or by the close "
                      "retry not judged", notes)

    def test_an_entry_is_judged_at_its_fill_and_a_weekend_paper_entry_is_caught(self):
        stocks = _cfg(self.user, "Stocks", "stock")
        monday = datetime(2026, 9, 28, 14, 0, tzinfo=UTC)
        # ordered at 02:00 on Monday, New York shut; filled at 13:35, open
        held = _trade(stocks, "AAPL", entry="336.10", stop="326.02",
                      paper=False, metadata={"entry_filled_at":
                                             "2026-09-28T13:35:00+00:00"},
                      opened=datetime(2026, 9, 28, 2, 0, tzinfo=UTC))
        ctx, found = _check("market_shut", monday)
        self.assertNotIn(f"trade:{held.pk}", _by_subject(found))
        paper = _trade(stocks, "MSFT", entry="420.00", stop="410.00",
                       opened=SAT_CLOSE)
        ctx, found = _check("market_shut", SAT_NOW)
        facts = _by_subject(found)[f"trade:{paper.pk}"].facts
        self.assertIn("Opened 2026-09-26 13:53 UTC at 420.00", facts)
        self.assertIn("Market shut then: New York Stock Exchange", facts)

    def test_a_live_fill_the_tick_noticed_late_is_given_a_tick_of_grace(self):
        stocks = _cfg(self.user, "Stocks live", "stock", mode="live")
        noticed = _trade(stocks, "AAPL", entry="336", stop="326",
                         paper=False, opened=FRI_CLOSE - timedelta(minutes=10),
                         metadata=dict(LIVE_ETORO, entry_filled_at=(
                             FRI_CLOSE + timedelta(minutes=8)).isoformat()))
        late = _trade(stocks, "MSFT", entry="420", stop="410", paper=False,
                      opened=FRI_CLOSE - timedelta(minutes=10),
                      metadata=dict(LIVE_ETORO, entry_filled_at=(
                          FRI_CLOSE + timedelta(minutes=20)).isoformat()))
        by = _by_subject(_check("market_shut",
                                FRI_CLOSE + timedelta(minutes=25))[1])
        self.assertNotIn(f"trade:{noticed.pk}", by)
        self.assertIn(f"trade:{late.pk}", by)

    def test_a_live_index_cfd_outside_the_cash_session_is_not_judged(self):
        from instruments.models import Instrument
        Instrument.objects.create(symbol="SPX500", name="S&P 500",
                                  asset_class="index", exchange="CME")
        cfg = _cfg(self.user, "Indices live", "index", mode="live")
        tuesday = datetime(2026, 9, 29, 7, 0, tzinfo=UTC)
        live = _trade(cfg, "SPX500", entry="6600", stop="6500", paper=False,
                      metadata=LIVE_ETORO, opened=tuesday)
        paper = _trade(_cfg(self.user, "Indices", "index"), "SPX500",
                       entry="6600", stop="6500", opened=tuesday)
        ctx, found = _check("market_shut", tuesday + timedelta(minutes=10))
        by = _by_subject(found)
        self.assertNotIn(f"trade:{live.pk}", by)
        self.assertIn(f"trade:{paper.pk}", by)
        self.assertIn("1 index booking at a broker not judged: the clock "
                      "keeps the cash session", " ".join(ctx.notes))

    def test_a_live_close_the_retry_drained_is_not_judged_a_paper_one_is(self):
        cfg = _cfg(self.user, "Stocks live", "stock", mode="live")
        drained = FRI_CLOSE + timedelta(minutes=6)
        live = _trade(cfg, "AAPL", entry="250", stop="245", paper=False,
                      status="CLOSED", exit_price="251", pnl="4",
                      metadata=dict(LIVE_ETORO, close_sent_at=(
                          FRI_CLOSE - timedelta(minutes=2)).isoformat()),
                      opened=FRI_CLOSE - timedelta(hours=5), closed=drained,
                      reason="momentum | closed:RETRY")
        paper = _trade(_cfg(self.user, "Stocks", "stock"), "MSFT",
                       entry="420", stop="410", status="CLOSED",
                       exit_price="421", opened=FRI_CLOSE - timedelta(hours=5),
                       closed=drained, reason="momentum | closed:RETRY")
        ctx, found = _check("market_shut", drained + timedelta(minutes=2))
        by = _by_subject(found)
        self.assertNotIn(f"trade:{live.pk}", by)
        self.assertIn(f"trade:{paper.pk}", by)
        self.assertIn("1 close booked by reconciliation or by the close "
                      "retry not judged", " ".join(ctx.notes))

    def test_the_winter_hour_is_judged_on_the_paper_venues_clock(self):
        """Sunday 2026-12-06 21:30 UTC is 16:30 New York: the strip's FOREX
        row reads open, the paper venue's market_clock shut until 22:00 --
        the hour in which a poller can re-stamp Friday's close. The gate
        refuses a paper close there; the guard judges it on the same
        clock, and is quiet once the week has opened."""
        cfg = _cfg(self.user)
        winter = datetime(2026, 12, 6, 21, 30, tzinfo=UTC)
        shut = _trade(cfg, "EURCAD", status="CLOSED", exit_price="1.6105",
                      opened=winter - timedelta(days=2), closed=winter)
        opened = _trade(cfg, "GBPCAD", status="CLOSED", exit_price="1.8740",
                        opened=winter - timedelta(days=2),
                        closed=winter + timedelta(hours=1))
        ctx, found = _check("market_shut", winter + timedelta(hours=1,
                                                             minutes=10))
        by = _by_subject(found)
        self.assertNotIn(f"trade:{opened.pk}", by)
        f = by[f"trade:{shut.pk}"]
        self.assertEqual(f.severity, "critical")
        self.assertTrue(f.brakes)
        self.assertIn("Closed 2026-12-06 21:30 UTC at 1.6105", f.facts)
        self.assertIn("Market shut then: Forex Market", f.facts)

    def test_a_new_york_holiday_and_an_early_close_are_judged_on_the_paper_venues_clock(self):
        """Friday 2026-12-25 is a NYSE holiday and Thursday 2026-12-24
        closes at 13:00 New York: the strip keeps neither, the paper
        venue's market_clock both. A paper stock booked at 10:00 New York
        on Christmas, or at 13:30 on the eve, is booked while shut."""
        stocks = _cfg(self.user, "Stocks", "stock")
        christmas = datetime(2026, 12, 25, 15, 0, tzinfo=UTC)
        holiday = _trade(stocks, "AAPL", entry="270.00", stop="260.00",
                         opened=christmas)
        early = _trade(stocks, "MSFT", entry="420.00", stop="410.00",
                       status="CLOSED", exit_price="421.00",
                       opened=christmas - timedelta(days=2),
                       closed=datetime(2026, 12, 24, 18, 30, tzinfo=UTC))
        session = _trade(stocks, "NVDA", entry="180.00", stop="170.00",
                         status="CLOSED", exit_price="181.00",
                         opened=christmas - timedelta(days=2),
                         closed=datetime(2026, 12, 24, 17, 30, tzinfo=UTC))
        ctx, found = _check("market_shut", christmas + timedelta(minutes=10))
        by = _by_subject(found)
        self.assertNotIn(f"trade:{session.pk}", by)
        self.assertIn("Opened 2026-12-25 15:00 UTC at 270.00",
                      by[f"trade:{holiday.pk}"].facts)
        self.assertIn("Market shut then: New York Stock Exchange",
                      by[f"trade:{holiday.pk}"].facts)
        self.assertIn("Closed 2026-12-24 18:30 UTC at 421.00",
                      by[f"trade:{early.pk}"].facts)
        self.assertIn("Market shut then: New York Stock Exchange",
                      by[f"trade:{early.pk}"].facts)


# ── G2: live without a stop ──────────────────────────────────────────────

class NoStopTests(_Case):
    def setUp(self):
        super().setUp()
        self.cfg = _cfg(self.user, "Forex live", mode="live")
        self.now = timezone.now()

    def test_a_bare_live_row_past_ten_minutes_is_critical(self):
        bare = _trade(self.cfg, "EURUSD", paper=False,
                      opened=self.now - timedelta(minutes=20),
                      metadata={"broker": "oanda", "protected": False,
                                "protection_note": "stop_leg refused"})
        ctx, found = _check("no_stop", self.now)
        f = _by_subject(found)[f"trade:{bare.pk}"]
        self.assertEqual(f.severity, "critical")
        self.assertFalse(f.brakes)
        self.assertTrue(f.facts[0].startswith("Live since "), f.facts)
        self.assertIn("No stop rests at the broker: the bot manages the "
                      "exit, and a stopped bot protects nothing", f.facts)
        self.assertIn("Broker note: stop leg refused", f.facts)
        self.assertIn("Stop the bot keeps: 1.60", f.facts)
        self.assertEqual(f.label, f"EURUSD long #{bare.pk} · live · "
                                  f"Forex live #{self.cfg.pk}")

    def test_a_stop_that_vanished_says_since_when_it_is_bare(self):
        gone = self.now - timedelta(minutes=30)
        row = _trade(self.cfg, "EURUSD", paper=False,
                     opened=self.now - timedelta(hours=5),
                     metadata={"protected": False,
                               "protection_vanished_at": gone.isoformat()})
        f = _by_subject(_check("no_stop", self.now)[1])[f"trade:{row.pk}"]
        self.assertEqual(f.facts[0], f"Without a stop since {eye.when(gone)} "
                                     f"(30 min ago)")

    def test_a_protected_a_young_a_paper_and_a_working_row_are_quiet(self):
        old = self.now - timedelta(minutes=20)
        _trade(self.cfg, "EURUSD", paper=False, opened=old,
               metadata={"protected": True})
        _trade(self.cfg, "GBPUSD", paper=False,
               opened=self.now - timedelta(minutes=5),
               metadata={"protected": False})
        _trade(_cfg(self.user), "USDJPY", opened=old)
        _trade(self.cfg, "AUDUSD", paper=False, opened=old,
               metadata={"entry_working": True, "protected": False})
        ctx, found = _check("no_stop", self.now)
        self.assertEqual(found, [])

    def test_a_demo_row_is_virtual_money_and_said_not_judged(self):
        _trade(self.cfg, "EURUSD", paper=False,
               opened=self.now - timedelta(hours=1),
               metadata=dict(DEMO_ETORO, protected=False))
        ctx, found = _check("no_stop", self.now)
        self.assertEqual(found, [])
        self.assertIn("1 demo position not judged", " ".join(ctx.notes))

    def test_etoro_echoing_no_stop_on_the_fill_is_a_bare_position(self):
        # an immediate fill: `protected` records the legs SENT, and eToro's
        # echo (the 0.0001 sentinel, or a zero) is the only trace
        rows = [_trade(self.cfg, sym, entry="100", stop="95", paper=False,
                       opened=self.now - timedelta(hours=1),
                       metadata=dict(LIVE_ETORO, stop_rewritten_by_venue={
                           "sent": 95.0, "held": held}))
                for sym, held in (("BTC", 0.0001), ("ETH", 0.0))]
        by = _by_subject(_check("no_stop", self.now)[1])
        self.assertEqual(sorted(by), sorted(f"trade:{t.pk}" for t in rows))
        for trade in rows:
            f = by[f"trade:{trade.pk}"]
            self.assertEqual(f.severity, "critical")
            self.assertIn("eToro holds no stop: sent 95.00", f.facts)
            self.assertNotIn("times the risk", " ".join(f.facts))

    def test_a_stop_the_broker_moved_farther_is_a_warning_with_both_prices(self):
        far = _trade(self.cfg, "BTC", entry="100", stop="95", paper=False,
                     opened=self.now - timedelta(hours=1),
                     metadata=dict(LIVE_ETORO, stop_rewritten_by_venue={
                         "sent": 95.0, "held": 90.0}))
        _trade(self.cfg, "ETH", side="SELL", entry="100", stop="105",
               paper=False, opened=self.now - timedelta(hours=1),
               metadata=dict(LIVE_ETORO, stop_rewritten_by_venue={
                   "sent": 105.0, "held": 103.0}))
        ctx, found = _check("no_stop", self.now)
        self.assertEqual([f.subject for f in found], [f"trade:{far.pk}:stop"])
        f = found[0]
        self.assertEqual(f.severity, "warning")
        self.assertEqual(f.title,
                         "Morgul — the broker moved a stop farther away")
        self.assertEqual(f.facts, ["Stop sent: 95.00",
                                   "Stop the broker holds: 90.00",
                                   "The loss at the stop is 2.0 times the "
                                   "risk budgeted"])


# ── G3: a stuck close ────────────────────────────────────────────────────

class StuckCloseTests(_Case):
    def setUp(self):
        super().setUp()
        self.cfg = _cfg(self.user, "Stocks live", "stock", mode="live")

    def test_thirty_minutes_warn_four_hours_are_critical_and_fresh_is_quiet(self):
        warn = _trade(self.cfg, "AAPL", paper=False, status="CLOSE_PENDING",
                      metadata={"close_retry_attempts": 8,
                                "close_retry_last_error": "HTTP_503 busy"})
        crit = _trade(self.cfg, "MSFT", paper=False, status="CLOSE_PENDING",
                      metadata={"close_retry_attempts": 50})
        fresh = _trade(self.cfg, "NVDA", paper=False, status="CLOSE_PENDING")
        ctx, found = _check("stuck_close", WED)
        by = _by_subject(found)
        self.assertEqual(by[f"trade:{warn.pk}"].severity, "warning")
        self.assertIn("Retries: 8", by[f"trade:{warn.pk}"].facts)
        self.assertIn("Last error: HTTP 503 busy", by[f"trade:{warn.pk}"].facts)
        self.assertEqual(by[f"trade:{crit.pk}"].severity, "critical")
        self.assertTrue(by[f"trade:{crit.pk}"].facts[0].startswith(
            "Close pending at least since "))
        self.assertNotIn(f"trade:{fresh.pk}", by)
        # nothing here reads the broker: nothing says the position is open
        for f in found:
            self.assertNotIn("still open", " ".join(f.facts))

    def test_a_measured_send_time_is_said_as_such(self):
        sent = WED - timedelta(minutes=45)
        row = _trade(self.cfg, "AAPL", paper=False, status="CLOSE_PENDING",
                     metadata={"close_sent_at": sent.isoformat()})
        f = _by_subject(_check("stuck_close", WED)[1])[f"trade:{row.pk}"]
        self.assertEqual(f.facts[0], "Close sent 2026-09-23 14:15 UTC "
                                     "(45 min ago)")

    def test_a_close_queued_while_the_market_is_shut_stays_a_warning(self):
        row = _trade(self.cfg, "AAPL", paper=False, status="CLOSE_PENDING",
                     metadata={"close_retry_attempts": 60})
        f = _by_subject(_check("stuck_close", SAT_NOW)[1])[f"trade:{row.pk}"]
        self.assertEqual(f.severity, "warning")
        self.assertIn("Market shut now: New York Stock Exchange; a close can "
                      "only fill when it opens", f.facts)

    def test_a_close_queued_on_a_new_york_holiday_stays_a_warning(self):
        """Christmas 2026 at 15:00 New York: a weekday the strip calls a
        session; the paper venue's market_clock keeps the NYSE holidays,
        and so does the guard -- the close can only fill on Monday."""
        row = _trade(self.cfg, "AAPL", paper=False, status="CLOSE_PENDING",
                     metadata={"close_retry_attempts": 60})
        christmas = datetime(2026, 12, 25, 20, 0, tzinfo=UTC)
        f = _by_subject(_check("stuck_close", christmas)[1])[f"trade:{row.pk}"]
        self.assertEqual(f.severity, "warning")
        self.assertIn("Market shut now: New York Stock Exchange; a close can "
                      "only fill when it opens", f.facts)

    def test_a_demo_row_says_demo(self):
        row = _trade(self.cfg, "AAPL", paper=False, status="CLOSE_PENDING",
                     metadata=dict(DEMO_ETORO, close_retry_attempts=8))
        f = _by_subject(_check("stuck_close", WED)[1])[f"trade:{row.pk}"]
        self.assertEqual(f.label, f"AAPL long #{row.pk} · demo · Stocks "
                                  f"live #{self.cfg.pk}")

    def test_the_guard_remembers_when_it_first_saw_a_pending_close(self):
        row = _trade(self.cfg, "AAPL", paper=False, status="CLOSE_PENDING")
        cache.set(morgul.SINCE_KEY.format(scope="stuck_close"),
                  {f"trade:{row.pk}":
                   (WED - timedelta(minutes=45)).isoformat()})
        ctx, found = _check("stuck_close", WED)
        self.assertEqual([f.severity for f in found], ["warning"])
        self.assertIn("Close pending at least since", found[0].facts[0])


# ── G4: price sanity ─────────────────────────────────────────────────────

class PriceSanityTests(_Case):
    def setUp(self):
        super().setUp()
        from instruments.models import Instrument
        from market_data.models import PriceData
        self.cfg = _cfg(self.user)
        inst = Instrument.objects.create(symbol="EURUSD", name="Euro",
                                         asset_class="forex")
        bar = WED - timedelta(minutes=30)
        PriceData.objects.create(
            instrument=inst, timeframe="1h", timestamp=bar,
            open=Decimal("1.08"), high=Decimal("1.081"),
            low=Decimal("1.079"), close=Decimal("1.0800"), source="test")

    def test_a_price_past_five_percent_on_forex_is_a_warning(self):
        far = _trade(self.cfg, "EURUSD", entry="1.1500", stop="1.14",
                     opened=WED)
        _trade(self.cfg, "EURUSD", entry="1.0850", stop="1.07", opened=WED)
        ctx, found = _check("price_sanity", WED + timedelta(minutes=5))
        self.assertEqual([f.subject for f in found], [f"trade:{far.pk}"])
        self.assertEqual(found[0].facts, [
            "Opened 2026-09-23 15:00 UTC at 1.15",
            "The one-hour bar of 2026-09-23 14:30 UTC closed at 1.08: 6.5% "
            "away",
            "The limit for Forex is 5.0%"])
        self.assertTrue(found[0].event)

    def test_no_bar_is_not_judged_and_said(self):
        _trade(self.cfg, "GBPUSD", entry="9.99", stop="9", opened=WED)
        ctx, found = _check("price_sanity", WED + timedelta(minutes=5))
        self.assertEqual(found, [])
        self.assertIn("1 booking with no one-hour or four-hour bar within "
                      "an hour: not judged", " ".join(ctx.notes))


# ── G5: proofs and ceilings ──────────────────────────────────────────────

class ProofTests(_Case):
    def setUp(self):
        super().setUp()
        from instruments.models import Instrument
        Instrument.objects.create(symbol="AAPL", name="Apple",
                                  asset_class="stock", exchange="NASDAQ")
        self.cfg = _cfg(self.user, "Stocks live", "stock", mode="live")
        self.now = timezone.now()

    def _found(self, proven, levels=None, shorts=()):
        from bot_program.asset_engine import base
        with patch.object(base, "ETORO_PROVEN", frozenset(proven)), \
                patch.object(base, "ETORO_SHORT_PROVEN", frozenset(shorts)), \
                patch.object(base, "ETORO_PROVEN_LEVERAGE", dict(levels or {})):
            return _check("proofs", self.now)[1]

    def test_an_unproven_class_and_an_unproven_short_are_critical_and_brake(self):
        row = _trade(self.cfg, "AAPL", entry="336.10", stop="326.02",
                     paper=False, metadata=LIVE_ETORO)
        f = _by_subject(self._found(()))[f"trade:{row.pk}"]
        self.assertEqual(f.facts, ["No fill-and-close proof pinned for: "
                                   "Stocks"])
        self.assertTrue(f.brakes)
        self.assertEqual(f.configs, [self.cfg.pk])
        self.assertEqual(self._found({"stock"}), [])
        short = _trade(self.cfg, "AAPL", side="SELL", entry="336.10",
                       stop="346", paper=False, metadata=LIVE_ETORO)
        self.assertEqual(_by_subject(self._found({"stock"}))[
            f"trade:{short.pk}"].facts,
            ["No fill-and-close proof pinned for: Short selling (stocks)"])
        # the class's own short proof (ETORO_SHORT_PROVEN) clears it, as
        # the global "short" token does
        self.assertNotIn(f"trade:{short.pk}", _by_subject(
            self._found({"stock"}, shorts={"stock"})))
        self.assertNotIn(f"trade:{short.pk}", _by_subject(
            self._found({"stock", "short"})))

    def test_a_multiplier_past_the_ceiling_or_the_attack_proof(self):
        over = _trade(self.cfg, "AAPL", entry="336.10", stop="326.02",
                      paper=False, metadata=dict(LIVE_ETORO, leverage=10))
        crypto = _cfg(self.user, "Crypto live", "crypto", mode="live")
        auto = _trade(crypto, "BTC", entry="60000", stop="58000",
                      paper=False, metadata=dict(
                          LIVE_ETORO, leverage=2, attack={"leverage": 2}))
        by = _by_subject(self._found({"stock", "crypto"}))
        self.assertEqual(by[f"trade:{over.pk}"].facts,
                         ["Multiplier 10x is above the Stocks ceiling of 5x"])
        self.assertEqual(by[f"trade:{auto.pk}"].facts,
                         ["The attack mode picked 2x, above the 1x proven "
                          "for Crypto"])
        self.assertNotIn(f"trade:{auto.pk}", _by_subject(
            self._found({"stock", "crypto"}, {"crypto": 2})))

    def test_a_paper_row_and_another_broker_are_not_judged(self):
        _trade(self.cfg, "AAPL", entry="336.10", stop="326", paper=True,
               metadata=LIVE_ETORO)
        _trade(self.cfg, "AAPL", entry="336.10", stop="326", paper=False,
               metadata={"broker": "alpaca", "protected": True})
        self.assertEqual(self._found(()), [])


# ── G6: the margin ───────────────────────────────────────────────────────

class MarginTests(_Case):
    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self.cfg = _cfg(self.user, "Stocks live", "stock", mode="live")

    def _acct(self, **fields):
        base = dict(demo=False, is_primary_for_stocks=True,
                    last_equity=Decimal("100"), last_equity_currency="USD",
                    last_used_margin=Decimal("40"),
                    last_margin_at=self.now - timedelta(minutes=5),
                    last_margin_world="live")
        base.update(fields)
        return _etoro(self.user, **base)

    def test_pledged_past_the_fraction_and_five_points_is_critical(self):
        # the brake's reach is every enabled live config of the user, the
        # one routed elsewhere included
        elsewhere = _cfg(self.user, "Crypto live", "crypto", mode="live")
        acct = self._acct(last_used_margin=Decimal("60"))
        ctx, found = _check("margin", self.now)
        f = _by_subject(found)[f"account:{acct.pk}:pledged"]
        self.assertEqual(f.severity, "critical")
        self.assertIn("Pledged: 60.0% of equity; the limit is 50.0%, the "
                      "alarm 55.0%", f.facts)
        self.assertEqual(f.configs, [self.cfg.pk, elsewhere.pk])
        self.assertTrue(f.brakes)

    def test_a_healthy_account_is_quiet(self):
        self._acct(last_used_margin=Decimal("50"))
        self.assertEqual(_check("margin", self.now)[1], [])

    def test_stale_cells_and_cells_from_the_other_world_are_warnings(self):
        acct = self._acct(last_margin_at=self.now - timedelta(hours=2),
                          last_margin_world="demo")
        by = _by_subject(_check("margin", self.now)[1])
        self.assertEqual(sorted(by), sorted([f"account:{acct.pk}:stale",
                                             f"account:{acct.pk}:world"]))
        self.assertEqual(by[f"account:{acct.pk}:stale"].severity, "warning")
        self.assertIn("Read in: demo", by[f"account:{acct.pk}:world"].facts)
        self.assertFalse(by[f"account:{acct.pk}:world"].brakes)

    def test_cells_the_gate_would_not_trust_never_brake(self):
        acct = self._acct(last_used_margin=Decimal("90"),
                          last_margin_at=self.now - timedelta(days=3),
                          last_margin_world="demo")
        f = _by_subject(_check("margin", self.now)[1])[
            f"account:{acct.pk}:pledged"]
        self.assertEqual(f.severity, "warning")
        self.assertFalse(f.brakes)
        self.assertEqual(f.configs, [])
        self.assertIn("A warning only, and no brake: read 3 d ago; read in "
                      "the demo world while the account is now live", f.facts)

    def test_an_account_no_running_bot_routes_to_never_brakes(self):
        from bot_program.asset_models import AssetBotConfig
        AssetBotConfig.objects.filter(pk=self.cfg.pk).update(
            asset_class="forex")
        _arm()
        acct = _etoro(self.user, demo=True, last_equity=Decimal("100"),
                      last_equity_currency="USD",
                      last_used_margin=Decimal("90"),
                      last_margin_at=self.now - timedelta(days=20),
                      last_margin_world="demo")
        with patch(SEND, return_value=True) as send:
            morgul.cycle(now=self.now, send=True,
                         guards=[morgul.GUARD["margin"]])
        self.cfg.refresh_from_db()
        self.assertTrue(self.cfg.enabled)
        text = "\n".join(_texts(send))
        self.assertIn(f"eToro demo account ({acct.label})", text)
        self.assertIn("no running live bot routes here", text)
        self.assertNotIn("Stopped:", text)


# ── G7: the daily loss ───────────────────────────────────────────────────

def _book_daily(pct):
    from portfolio.risk_gate import limits_book
    book = limits_book()
    book.max_daily_loss_pct = pct
    book.save(update_fields=["max_daily_loss_pct"])


class DailyLossTests(_Case):
    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self.live = _cfg(self.user, "Stocks live", "stock", mode="live")
        self.paper = _cfg(self.user, "Stocks paper", "stock")
        # MAX DAILY LOSS on /setup/: the one daily stop (2026-10-01)
        _book_daily(2.0)

    def _close(self, cfg, pnl, paper=False, metadata=None):
        return _trade(cfg, "AAPL", entry="336", stop="326", paper=paper,
                      status="CLOSED", exit_price="330", pnl=pnl,
                      metadata=metadata, opened=self.now - timedelta(hours=3),
                      closed=self.now - timedelta(hours=1))

    def test_live_losses_past_the_daily_stop_are_critical_and_say_the_number(self):
        self._close(self.live, "-150")
        self._close(self.live, "-100")
        self._close(self.live, None)
        found = _check("daily_loss", self.now)[1]
        self.assertEqual(len(found), 1)
        f = found[0]
        self.assertEqual(f.facts[:3], [
            "Realized live P&L, last 24 h: -250.00 USD over 3 closes "
            "(paper and demo excluded)",
            "Daily stop used: 2.0% of 10,000.00 USD = 200.00 USD",
            "That is MAX DAILY LOSS on /setup/, the one daily stop of every "
            "live bot"])
        self.assertIn("Elite entries only until the absolute stop at 3.0% = "
                      "300.00 USD: a measured edge, at 0.5x size, at most 2 "
                      "in 24 h", f.facts)
        self.assertIn("No bot is switched off: exits and stops keep running",
                      f.facts)
        self.assertIn("Closes without a price: 1 (not counted as zero)",
                      f.facts)
        self.assertEqual(f.configs, [self.live.pk])

    def test_paper_is_never_counted_nor_netted(self):
        self._close(self.paper, "-5000", paper=True)
        self.assertEqual(_check("daily_loss", self.now)[1], [])
        self._close(self.live, "-150")
        self._close(self.paper, "+900", paper=True)
        self.assertEqual(_check("daily_loss", self.now)[1], [])

    def test_demo_closes_are_virtual_money_and_said(self):
        self._close(self.live, "-5000", metadata=DEMO_ETORO)
        ctx, found = _check("daily_loss", self.now)
        self.assertEqual(found, [])
        self.assertIn("1 demo close not counted", " ".join(ctx.notes))

    def test_the_book_stop_binds_every_live_bot_whatever_their_own(self):
        """A bot set never to halt, or at 0%, is not left out of the one
        stop: it is the book's."""
        _cfg(self.user, "Stocks never", "stock", mode="live", daily=0.5,
             halt_on_drawdown=False)
        self._close(self.live, "-700")
        f = _check("daily_loss", self.now)[1][0]
        self.assertIn("Daily stop used: 2.0% of 20,000.00 USD = 400.00 USD",
                      f.facts)
        self.assertIn("Past the absolute stop at 3.0% = 600.00 USD: nothing "
                      "opens, elite entries included", f.facts)
        self.assertFalse(any("Left out" in x for x in f.facts))

    def test_a_bot_that_never_halts_or_stops_at_zero_sets_no_number(self):
        """Without a book limit, the bots' own percentages, as before."""
        _book_daily(0)
        never = _cfg(self.user, "Stocks never", "stock", mode="live",
                     daily=0.5, halt_on_drawdown=False)
        zero = _cfg(self.user, "Stocks zero", "stock", mode="live", daily=0)
        self._close(self.live, "-900")
        f = _check("daily_loss", self.now)[1][0]
        self.assertIn("Daily stop used: 2.0% of 30,000.00 USD = 600.00 USD",
                      f.facts)
        self.assertIn(f"Left out of that number: Stocks never #{never.pk} "
                      f"(never halts on drawdown), Stocks zero #{zero.pk} (a "
                      f"daily stop of 0%)", f.facts)
        from bot_program.asset_models import AssetBotConfig
        AssetBotConfig.objects.filter(pk=self.live.pk).update(
            halt_on_drawdown=False)
        ctx, found = _check("daily_loss", self.now)
        self.assertEqual(found, [])
        self.assertIn("no bot carries a daily stop", " ".join(ctx.notes))

    def test_a_currency_nothing_converts_is_said(self):
        from bot_program.asset_models import AssetBotConfig
        AssetBotConfig.objects.filter(pk=self.live.pk).update(
            base_currency="EUR")
        _etoro(self.user, demo=False, is_primary_for_stocks=True,
               last_equity_currency="USD")
        self._close(self.live, "-900")
        f = _check("daily_loss", self.now)[1][0]
        self.assertIn("Counted in EUR, the bots' base currency, as the "
                      "engine's daily gate counts it; the eToro account "
                      "reads USD and nothing converts", f.facts)


# ── G8: duplicates ───────────────────────────────────────────────────────

class DuplicateTests(_Case):
    def test_two_open_live_rows_on_one_config_symbol_and_side(self):
        cfg = _cfg(self.user, "Stocks live", "stock", mode="live")
        a = _trade(cfg, "AAPL", entry="336", stop="326", paper=False)
        b = _trade(cfg, "AAPL", entry="337", stop="327", paper=False)
        _trade(cfg, "AAPL", side="SELL", entry="336", stop="346", paper=False)
        _trade(cfg, "MSFT", entry="420", stop="410", paper=True)
        _trade(cfg, "MSFT", entry="420", stop="410", paper=True)
        found = _check("duplicates", timezone.now())[1]
        self.assertEqual([f.subject for f in found],
                         [f"config:{cfg.pk}:AAPL:BUY"])
        self.assertIn(f"Open live rows: 2 (#{a.pk}, #{b.pk})",
                      found[0].facts)
        self.assertEqual(found[0].label, f"AAPL long · live · Stocks live "
                                         f"#{cfg.pk}")
        self.assertEqual(found[0].severity, "warning")

    def test_demo_duplicates_are_said_apart_as_demo(self):
        cfg = _cfg(self.user, "Stocks live", "stock", mode="live")
        a = _trade(cfg, "AAPL", entry="336", stop="326", paper=False,
                   metadata=DEMO_ETORO)
        b = _trade(cfg, "AAPL", entry="337", stop="327", paper=False,
                   metadata=DEMO_ETORO)
        _trade(cfg, "AAPL", entry="338", stop="328", paper=False,
               metadata=LIVE_ETORO)
        found = _check("duplicates", timezone.now())[1]
        self.assertEqual([f.subject for f in found],
                         [f"config:{cfg.pk}:AAPL:BUY:demo"])
        self.assertEqual(found[0].label, f"AAPL long · demo · Stocks live "
                                         f"#{cfg.pk}")
        self.assertIn(f"Open demo rows: 2 (#{a.pk}, #{b.pk})",
                      found[0].facts)


# ── G9: drift ────────────────────────────────────────────────────────────

class DriftTests(_Case):
    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self.cfg = _cfg(self.user, "Stocks live", "stock", mode="live")
        self.row = _trade(self.cfg, "AAPL", entry="336", stop="326",
                          paper=False, metadata=LIVE_ETORO,
                          opened=self.now - timedelta(hours=1))

    def _acct(self, held, age_min=5, **fields):
        return _etoro(self.user, **dict(dict(
            demo=False, broker_positions=held,
            broker_positions_at=self.now - timedelta(minutes=age_min)),
            **fields))

    def _seen(self, subject, minutes=20):
        cache.set(morgul.SINCE_KEY.format(scope="drift"),
                  {subject: (self.now - timedelta(minutes=minutes))
                   .isoformat()})

    def test_a_row_the_broker_does_not_hold_is_critical_after_fifteen_minutes(self):
        self._acct([])
        # a stop filled at the broker minutes ago: the reconcile may not
        # have booked it yet, so the first sighting is only noted
        ctx, found = _check("drift", self.now)
        self.assertEqual(found, [])
        self.assertIn("said after 15 min", " ".join(ctx.notes))
        self._seen(f"trade:{self.row.pk}")
        found = _check("drift", self.now)[1]
        self.assertEqual([f.subject for f in found],
                         [f"trade:{self.row.pk}"])
        self.assertEqual(found[0].severity, "critical")
        self.assertIn("Not in the holdings eToro reported (Synced: 5 min "
                      "ago)", found[0].facts)

    def test_an_unnamed_book_is_compared_by_count(self):
        self._acct([{"symbol": "ETORO:1001", "qty": 0.04}])
        self.assertEqual(_check("drift", self.now)[1], [])

    def test_a_position_no_row_claims_is_said_after_fifteen_minutes(self):
        acct = self._acct([{"symbol": "ETORO:1001"}, {"symbol": "ETORO:1002"}])
        ctx, found = _check("drift", self.now)
        self.assertEqual(found, [])
        self.assertIn("said after 15 min", " ".join(ctx.notes))
        self._seen(f"account:{acct.pk}:unclaimed")
        found = _check("drift", self.now)[1]
        self.assertEqual([f.subject for f in found],
                         [f"account:{acct.pk}:unclaimed"])
        self.assertIn("Held at eToro: 2 (Synced: 5 min ago)", found[0].facts)
        self.assertIn("Open live rows that claim them: 1", found[0].facts)

    def test_the_demo_worlds_proof_positions_are_never_an_alarm(self):
        from bot_program.asset_models import AssetBotTrade
        AssetBotTrade.objects.all().delete()
        acct = _etoro(self.user, demo=True,
                      broker_positions=[{"symbol": "ETORO:3190", "qty": 1.0}],
                      broker_positions_at=self.now - timedelta(minutes=3))
        self._seen(f"account:{acct.pk}:unclaimed", minutes=600)
        ctx, found = _check("drift", self.now)
        self.assertEqual(found, [])
        self.assertIn("the demo world is virtual money", " ".join(ctx.notes))

    def test_no_snapshot_a_stale_one_or_the_other_worlds_is_not_judged(self):
        from bot_program.models import EtoroAccount
        acct = self._acct([], age_min=120)
        ctx, found = _check("drift", self.now)
        self.assertEqual(found, [])
        self.assertIn("not judged", " ".join(ctx.notes))
        self.assertIn(f"trade:{self.row.pk}", ctx.unjudged["drift"])
        read = self.now - timedelta(minutes=5)
        EtoroAccount.objects.filter(pk=acct.pk).update(
            broker_positions_at=read, last_margin_at=read,
            last_margin_world="demo")
        self._seen(f"trade:{self.row.pk}")
        ctx, found = _check("drift", self.now)
        self.assertEqual(found, [])
        self.assertIn("read in the demo world; not judged",
                      " ".join(ctx.notes))
        EtoroAccount.objects.filter(pk=acct.pk).update(
            broker_positions_at=None)
        ctx, found = _check("drift", self.now)
        self.assertEqual(found, [])
        self.assertIn("no holdings snapshot stored", " ".join(ctx.notes))

    def test_a_snapshot_gone_stale_is_never_back_to_normal(self):
        from bot_program.models import EtoroAccount
        acct = self._acct([])
        self._seen(f"trade:{self.row.pk}")
        guards = [morgul.GUARD["drift"]]
        with patch(SEND, return_value=True) as send:
            morgul.cycle(now=self.now, send=True, guards=guards)
        self.assertIn("the platform and the broker disagree",
                      _texts(send)[0])
        EtoroAccount.objects.filter(pk=acct.pk).update(
            broker_positions_at=self.now - timedelta(hours=1))
        with patch(SEND, return_value=True) as send:
            report = morgul.cycle(now=self.now + timedelta(hours=2),
                                  send=True, guards=guards)
        self.assertEqual(_texts(send), [])
        self.assertIn(f"drift|trade:{self.row.pk}",
                      cache.get(morgul.STATE_KEY))
        self.assertIn("not judged", " ".join(report.ctx.notes))
        # the memory of when it was first seen is kept too
        self.assertIn(f"trade:{self.row.pk}",
                      cache.get(morgul.SINCE_KEY.format(scope="drift")))


# ── G10: the heartbeat ───────────────────────────────────────────────────

class HeartbeatTests(_Case):
    def setUp(self):
        super().setUp()
        from bot_program.asset_models import AssetBotConfig
        _component("platform_master")
        self.cfg = _cfg(self.user, "Forex live", mode="live",
                        symbols=["EURUSD"], extras={
                            "last_tick_at": (WED - timedelta(minutes=40))
                            .isoformat()})
        AssetBotConfig.objects.filter(pk=self.cfg.pk).update(
            updated_at=WED - timedelta(hours=2))

    def _ticking(self):
        from bot_program.asset_models import AssetBotConfig
        AssetBotConfig.objects.filter(enabled=True, mode="live").update(
            extras={"last_tick_at": (WED - timedelta(minutes=2)).isoformat()})
        _component("pipeline_asset_bots", last_run=WED - timedelta(minutes=2))

    def test_a_tick_quiet_for_forty_minutes_is_critical(self):
        _component("pipeline_asset_bots", last_run=WED - timedelta(minutes=40))
        _mark("EURUSD", "forex", WED - timedelta(minutes=1))
        found = _check("heartbeat", WED)[1]
        f = _by_subject(found)["tick"]
        self.assertEqual(f.severity, "critical")
        self.assertIn("The bot tick last ran 40 min ago", f.facts)
        self.assertIn(f"Forex live #{self.cfg.pk}: last tick 40 min ago",
                      f.facts)
        self.assertNotIn("feeds:forex", _by_subject(found))

    def test_a_ticking_fleet_with_fresh_marks_is_quiet(self):
        self._ticking()
        _mark("EURUSD", "forex", WED - timedelta(minutes=1))
        self.assertEqual(_check("heartbeat", WED)[1], [])

    def test_stale_marks_in_an_open_market_are_critical_and_a_weekend_is_not(self):
        self._ticking()
        _mark("EURUSD", "forex", WED - timedelta(hours=3))
        by = _by_subject(_check("heartbeat", WED)[1])
        f = by["feeds:forex"]
        self.assertEqual(f.title, "Morgul — no fresh quotes for a live market")
        self.assertIn("Freshest mark of the live bots' 1 symbol: EURUSD, "
                      "3 h ago (OANDA (stream))", f.facts)
        ctx, found = _check("heartbeat", SAT_NOW)
        self.assertNotIn("feeds:forex", _by_subject(found))
        self.assertIn("feeds:forex", ctx.unjudged["heartbeat"])

    def test_a_fresh_class_never_hides_a_dead_one(self):
        self._ticking()
        stocks = _cfg(self.user, "Stocks live", "stock", mode="live",
                      symbols=["AAPL"])
        self._ticking()
        _mark("EURUSD", "forex", WED - timedelta(minutes=1))
        _mark("AAPL", "stock", WED - timedelta(hours=20), source="yfinance",
              last="336")
        by = _by_subject(_check("heartbeat", WED)[1])
        self.assertEqual(sorted(by), ["feeds:stock"])
        self.assertIn("AAPL, 20 h ago (Yahoo Finance)", by["feeds:stock"]
                      .facts[0])
        self.assertTrue(stocks.enabled)

    def test_a_class_with_no_mark_is_said_not_judged(self):
        self._ticking()
        ctx, found = _check("heartbeat", WED)
        self.assertEqual(found, [])
        self.assertIn("no mark stored for the live bots' 1 symbol",
                      " ".join(ctx.notes))

    def test_no_live_config_no_heartbeat(self):
        self.cfg.enabled = False
        self.cfg.save()
        self.assertEqual(_check("heartbeat", WED)[1], [])


# ── G0: the frame ────────────────────────────────────────────────────────

class FrameTests(_Case):
    def setUp(self):
        super().setUp()
        self.t0 = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)

    def _run(self, guards, at):
        with patch(SEND, return_value=True) as send:
            report = morgul.cycle(now=at, send=True, guards=guards)
        return report, _texts(send)

    def test_a_guard_that_raises_is_a_finding_never_silence(self):
        def boom(ctx, guard):
            return 1 / 0
        guard = morgul.Guard("boom", "Boom test", "critical",
                             "Morgul — boom", boom, brake=True)
        report, texts = self._run([guard], self.t0)
        self.assertEqual(report.failed, ["boom"])
        f = report.findings[0]
        self.assertEqual(f.title, "Morgul — a guard could not run")
        self.assertEqual(f.facts[0],
                         "Guard boom test could not run: ZeroDivisionError")
        self.assertEqual(f.severity, "warning")
        self.assertFalse(f.brakes)
        self.assertEqual(len(texts), 1)
        self.assertIn("Guard boom test could not run: ZeroDivisionError",
                      texts[0])

    def test_said_once_per_three_hours_then_back_to_normal_once(self):
        guard, box = _scripted()
        box["subjects"] = ["one"]
        _r, texts = self._run([guard], self.t0)
        self.assertEqual(len(texts), 1)
        self.assertTrue(texts[0].startswith(
            f"<b>{morgul.MARK} Morgul — scripted</b>"))
        self.assertEqual(self._run([guard], self.t0 + timedelta(hours=1))[1],
                         [])
        self.assertEqual(len(self._run(
            [guard], self.t0 + timedelta(hours=3))[1]), 1)
        box["subjects"] = []
        _r, texts = self._run([guard], self.t0 + timedelta(hours=4))
        self.assertEqual(len(texts), 1)
        self.assertIn("Morgul — back to normal", texts[0])
        self.assertIn("Scripted: Subject one — back to normal", texts[0])
        self.assertEqual(self._run([guard], self.t0 + timedelta(hours=5))[1],
                         [])

    def test_an_event_is_said_once_and_never_back_to_normal(self):
        guard, box = _scripted()
        box.update(subjects=["one"], event=True)
        self.assertEqual(len(self._run([guard], self.t0)[1]), 1)
        self.assertEqual(self._run([guard], self.t0 + timedelta(hours=4))[1],
                         [])
        box["subjects"] = []
        self.assertEqual(self._run([guard], self.t0 + timedelta(hours=5))[1],
                         [])

    def test_a_warning_turned_critical_is_said_at_once(self):
        guard, box = _scripted()
        box["subjects"] = ["one"]
        self._run([guard], self.t0)
        box["severity"] = "critical"
        _r, texts = self._run([guard], self.t0 + timedelta(minutes=10))
        self.assertEqual(len(texts), 1)
        self.assertIn("Severity: critical", texts[0])

    def test_a_blind_guard_keeps_what_it_last_saw(self):
        guard, box = _scripted()
        box["subjects"] = ["one"]
        self._run([guard], self.t0)

        def blind(ctx, g):
            raise RuntimeError("database gone")
        blinded = morgul.Guard("scripted", "Scripted", "warning",
                               "Morgul — scripted", blind)
        _r, texts = self._run([blinded], self.t0 + timedelta(hours=1))
        self.assertEqual(len(texts), 1)
        self.assertNotIn("back to normal", texts[0])
        self.assertIn("scripted|one", cache.get(morgul.STATE_KEY))
        _r, texts = self._run([guard], self.t0 + timedelta(hours=2))
        self.assertEqual(len(texts), 1)
        self.assertIn("Scripted: the guard runs again — back to normal",
                      texts[0])
        self.assertNotIn("Subject one — back to normal", texts[0])

    def test_a_subject_a_guard_could_not_judge_is_never_back_to_normal(self):
        guard, box = _scripted()
        box["subjects"] = ["one"]
        self._run([guard], self.t0)
        box.update(subjects=[], blind=["one"])
        self.assertEqual(self._run([guard], self.t0 + timedelta(hours=4))[1],
                         [])
        self.assertIn("scripted|one", cache.get(morgul.STATE_KEY))
        box["blind"] = []
        _r, texts = self._run([guard], self.t0 + timedelta(hours=5))
        self.assertIn("Scripted: Subject one — back to normal", texts[0])

    def test_a_message_telegram_refused_goes_out_on_the_next_run(self):
        guard, box = _scripted()
        box["subjects"] = ["one"]
        with patch(SEND, return_value=False) as send:
            report = morgul.cycle(now=self.t0, send=True, guards=[guard])
        self.assertEqual(send.call_count, 1)
        self.assertEqual(report.result["sent"], 0)
        _r, texts = self._run([guard], self.t0 + timedelta(minutes=5))
        self.assertEqual(len(texts), 1)
        self.assertEqual(self._run([guard], self.t0 + timedelta(minutes=10))[1],
                         [])

    def test_no_telegram_chat_is_said_to_the_gate(self):
        from alerts.models import UserNotificationPrefs
        UserNotificationPrefs.objects.update(telegram_chat_id="")
        guard, box = _scripted()
        box["subjects"] = ["one"]
        report, texts = self._run([guard], self.t0)
        self.assertEqual(texts, [])
        self.assertEqual(report.result["skipped"],
                         "no staff Telegram chat is configured")

    def test_one_run_at_a_time(self):
        guard, box = _scripted()
        box["subjects"] = ["one"]
        cache.add(morgul.LOCK_KEY, "held", 60)
        report, texts = self._run([guard], self.t0)
        self.assertEqual(texts, [])
        self.assertEqual(report.result["idle"],
                         "another Morgul run is in progress")
        self.assertIsNone(cache.get(morgul.STATE_KEY))
        cache.clear()
        _r, texts = self._run([guard], self.t0)
        self.assertEqual(len(texts), 1)
        self.assertIsNone(cache.get(morgul.LOCK_KEY))


# ── G11: the brake ───────────────────────────────────────────────────────

class BrakeTests(_Case):
    def setUp(self):
        super().setUp()
        from bot_program.asset_models import AssetBotTrade
        self.cfg = _cfg(self.user)
        self.other = _cfg(self.user, "Stocks", "stock")
        self.live_other = _cfg(self.user, "Forex live", mode="live")
        _trade(self.cfg, "EURCAD", side="SELL", status="CLOSED",
               exit_price="1.6123", opened=FRI, closed=SAT_CLOSE)
        _trade(self.cfg, "GBPCAD", status="CLOSED", exit_price="1.874",
               opened=FRI, closed=SAT_CLOSE)
        self.open_row = _trade(self.cfg, "EURUSD", entry="1.08", stop="1.07",
                               opened=FRI)
        self.before = sorted(AssetBotTrade.objects.values_list(
            "pk", "status", "exit_price", "closed_at"))
        self.now = timezone.now()

    def _cycle(self, guards, at=SAT_NOW, sent=True):
        with patch(SEND, return_value=sent) as send, \
                patch("bot_program.engine.broker_router.client_for_symbol") \
                as router, \
                patch("bot_program.engine.etoro_client.EtoroTrader") as trader:
            report = morgul.cycle(now=at, send=True, guards=guards)
        router.assert_not_called()
        trader.assert_not_called()
        return report, _texts(send)

    def _rows_unchanged(self):
        from bot_program.asset_models import AssetBotTrade
        self.assertEqual(sorted(AssetBotTrade.objects.values_list(
            "pk", "status", "exit_price", "closed_at")), self.before)

    def _enabled(self, *cfgs):
        for cfg in cfgs:
            cfg.refresh_from_db()
        return [cfg.enabled for cfg in cfgs]

    def _account_brake(self, *cfgs):
        """A braking guard naming every live config of the user, as G6
        (margin) does. The daily loss was this vehicle until 2026-10-01,
        when it stopped braking (test_the_daily_loss_never_brakes)."""
        guard, box = _scripted("account", "Account", "critical", brake=True)
        box["subjects"] = ["account"]
        box["user"] = self.user
        box["configs"] = [c.pk for c in cfgs]
        return guard

    def test_off_it_says_what_it_would_stop_and_stops_nothing(self):
        report, texts = self._cycle([morgul.GUARD["market_shut"]])
        self.assertEqual(len(texts), 1)
        self.assertIn(f"Would stop: Forex swing #{self.cfg.pk} — the brake "
                      f"is off; nothing was stopped", texts[0])
        self.assertEqual(self._enabled(self.cfg), [True])
        self.assertEqual(report.result["stopped"], [])
        self._rows_unchanged()

    def test_with_the_guards_off_the_brake_only_says_what_it_would_stop(self):
        _component(morgul.BRAKE_KEY)
        _component(morgul.COMPONENT_KEY, on=False)
        report, texts = self._cycle([morgul.GUARD["market_shut"]])
        self.assertIn(f"Would stop: Forex swing #{self.cfg.pk} — the brake "
                      f"is off", texts[0])
        self.assertEqual(self._enabled(self.cfg), [True])

    def test_on_it_stops_exactly_the_offending_config_and_closes_nothing(self):
        _arm()
        report, texts = self._cycle([morgul.GUARD["market_shut"]])
        self.assertEqual(self._enabled(self.cfg, self.other, self.live_other),
                         [False, True, True])
        # the stopped config holds an open PAPER row: its stop is the bot's
        # own and pauses, so "the stops stay at the broker" is not said
        self.assertIn(f"Stopped: Forex swing #{self.cfg.pk} — no position "
                      f"was closed; to re-arm: the server", texts[0])
        self.assertIn("Paper positions: 1 — their stops are simulated by the "
                      "bot and pause while it is stopped", texts[0])
        self.assertNotIn("the stops stay at the broker", texts[0])
        self.assertEqual(report.result["stopped"],
                         [f"Forex swing #{self.cfg.pk}"])
        self._rows_unchanged()
        self.open_row.refresh_from_db()
        self.assertEqual(self.open_row.status, "OPEN")

    def test_the_stops_stay_at_the_broker_is_said_only_when_true(self):
        _arm()
        live = _cfg(self.user, "Stocks live", "stock", mode="live")
        guarded = _trade(live, "MSFT", entry="420", stop="410", paper=False,
                         metadata=LIVE_ETORO, opened=self.now - timedelta(hours=2))
        _loss(live, self.now)
        guard = self._account_brake(self.live_other, live)
        report, texts = self._cycle([guard], at=self.now)
        self.assertIn(f"Stopped: Forex live #{self.live_other.pk}, Stocks "
                      f"live #{live.pk} — no position was closed; the "
                      f"stops stay at the broker; to re-arm: the server",
                      texts[0])
        # the same bot, re-armed, with its stop gone at the broker
        from bot_program.asset_models import AssetBotTrade
        AssetBotTrade.objects.filter(pk=guarded.pk).update(
            metadata=dict(LIVE_ETORO, protected=False))
        cache.clear()
        live.enabled = True
        live.save()
        report, texts = self._cycle([guard],
                                    at=self.now + timedelta(minutes=5))
        self.assertIn(f"Stopped: Stocks live #{live.pk} — no position was "
                      f"closed; to re-arm: the server", texts[0])
        self.assertIn("At the broker without a stop: 1 — while the bot is "
                      "stopped, nothing protects them", texts[0])
        self.assertNotIn("the stops stay at the broker", texts[0])
        guarded.refresh_from_db()
        self.assertEqual(guarded.status, "OPEN")

    def test_a_braking_finding_stops_every_live_config_of_the_user_once(self):
        _arm()
        now = self.now
        live = _cfg(self.user, "Stocks live", "stock", mode="live")
        live2 = self.live_other
        stranger = _cfg(_staff("stranger", chat="-1"), "Their live", "stock",
                        mode="live")
        guard = self._account_brake(live2, live)
        report, texts = self._cycle([guard], at=now)
        for cfg, enabled in ((live, False), (live2, False), (self.cfg, True),
                             (self.other, True), (stranger, True)):
            cfg.refresh_from_db()
            self.assertEqual(cfg.enabled, enabled, cfg.name)
        # the operator re-arms on the server: the same finding never
        # stops them again, and its reminder says the brake acted earlier
        live.enabled = live2.enabled = True
        live.save()
        live2.save()
        report, texts = self._cycle([guard], at=now + timedelta(hours=3))
        live.refresh_from_db()
        self.assertTrue(live.enabled)
        self.assertIn(f"Stopped earlier by the brake: Forex live #{live2.pk}, "
                      f"Stocks live #{live.pk} — to re-arm: the server",
                      texts[0])

    def test_the_daily_loss_never_brakes(self):
        """2026-10-01: past MAX DAILY LOSS the engine's gate lets only
        elite entries through and stops at the absolute stop by itself;
        switching the bots off would stop their exits too. The finding is
        said, critical, and nothing is stopped — past the absolute stop
        as well."""
        _arm()
        live = _cfg(self.user, "Stocks live", "stock", mode="live")
        _loss(live, self.now, pnl="-5000")
        report, texts = self._cycle([morgul.GUARD["daily_loss"]], at=self.now)
        self.assertEqual(self._enabled(live, self.live_other), [True, True])
        self.assertEqual(report.result["stopped"], [])
        self.assertIn("Past the absolute stop", texts[0])
        self.assertIn("No bot is switched off: exits and stops keep running",
                      texts[0])
        self.assertNotIn("Would stop", texts[0])

    def test_a_stop_telegram_refused_is_announced_by_the_next_message(self):
        _arm()
        self.live_other.enabled = False
        self.live_other.save()
        live = _cfg(self.user, "Stocks live", "stock", mode="live")
        _loss(live, self.now)
        guards = [self._account_brake(live)]
        _r, refused = self._cycle(guards, at=self.now, sent=False)
        self.assertEqual(self._enabled(live), [False])
        _r, texts = self._cycle(guards, at=self.now + timedelta(minutes=5))
        self.assertEqual(len(texts), 1)
        self.assertIn(f"Stopped: Stocks live #{live.pk}", texts[0])
        # the reminder three hours on, the bots still off, says it too
        _r, texts = self._cycle(guards, at=self.now + timedelta(hours=3,
                                                                minutes=5))
        self.assertIn(f"Stopped earlier by the brake: Stocks live "
                      f"#{live.pk}", texts[0])

    def test_a_run_that_dies_after_the_brake_leaves_the_next_announcing_it(self):
        _arm()
        self.live_other.enabled = False
        self.live_other.save()
        live = _cfg(self.user, "Stocks live", "stock", mode="live")
        _loss(live, self.now)
        guards = [self._account_brake(live)]
        with patch("bot_program.morgul.build_messages",
                   side_effect=RuntimeError("gone")):
            with self.assertRaises(RuntimeError):
                self._cycle(guards, at=self.now)
        self.assertEqual(self._enabled(live), [False])
        self.assertIsNone(cache.get(morgul.LOCK_KEY))
        _r, texts = self._cycle(guards, at=self.now + timedelta(minutes=5))
        self.assertIn(f"Stopped: Stocks live #{live.pk}", texts[0])
        self.assertNotIn("Nothing to stop", texts[0])

    def test_no_staff_chat_holds_the_brake_back(self):
        from alerts.models import UserNotificationPrefs
        _arm()
        UserNotificationPrefs.objects.update(telegram_chat_id="")
        report, texts = self._cycle([morgul.GUARD["market_shut"]])
        self.assertEqual(texts, [])
        self.assertEqual(self._enabled(self.cfg), [True])
        self.assertEqual(report.result["stopped"], [])
        self.assertEqual(report.result["skipped"],
                         "no staff Telegram chat is configured; the brake "
                         "held back")

    def test_armed_after_the_finding_was_said_it_stops_the_config_on_the_next_run(self):
        """The documented arrival: the guards on, the brake off. The
        Saturday finding is said once ("Would stop") -- an event, never due
        again. The brake armed a quarter hour on reads every finding of
        the run, not only those due: it stops the config on the next run
        and says so, once; and with nobody to tell it still holds back."""
        from alerts.models import UserNotificationPrefs
        _component(morgul.COMPONENT_KEY)
        guards = [morgul.GUARD["market_shut"]]
        _r, texts = self._cycle(guards)
        self.assertIn(f"Would stop: Forex swing #{self.cfg.pk} — the brake "
                      f"is off; nothing was stopped", texts[0])
        self.assertEqual(self._enabled(self.cfg), [True])
        _component(morgul.BRAKE_KEY)
        # armed, but no staff chat could be told: it holds back
        UserNotificationPrefs.objects.update(telegram_chat_id="")
        report, texts = self._cycle(guards, at=SAT_NOW + timedelta(minutes=15))
        self.assertEqual(texts, [])
        self.assertEqual(self._enabled(self.cfg), [True])
        self.assertEqual(report.result["stopped"], [])
        UserNotificationPrefs.objects.update(telegram_chat_id=GROUP)
        report, texts = self._cycle(guards, at=SAT_NOW + timedelta(minutes=20))
        self.assertEqual(self._enabled(self.cfg, self.other, self.live_other),
                         [False, True, True])
        self.assertEqual(report.result["stopped"],
                         [f"Forex swing #{self.cfg.pk}"])
        self.assertEqual(len(texts), 1)
        self.assertIn(f"Stopped: Forex swing #{self.cfg.pk} — no position "
                      f"was closed; to re-arm: the server", texts[0])
        self._rows_unchanged()
        # once: the next run stops nothing more and says nothing
        report, texts = self._cycle(guards, at=SAT_NOW + timedelta(minutes=25))
        self.assertEqual(texts, [])
        self.assertEqual(report.result["stopped"], [])

    def test_armed_within_the_three_hours_a_standing_finding_is_stopped_at_once(self):
        """A standing braking finding said at 10:00 with the brake off is
        not due again before 13:00; the brake armed at 10:30 does not wait
        for the reminder."""
        from bot_program.asset_models import AssetBotTrade
        _component(morgul.COMPONENT_KEY)
        live = _cfg(self.user, "Stocks live", "stock", mode="live")
        _loss(live, self.now)
        before = sorted(AssetBotTrade.objects.values_list(
            "pk", "status", "exit_price", "closed_at"))
        guards = [self._account_brake(self.live_other, live)]
        _r, texts = self._cycle(guards, at=self.now)
        self.assertIn(f"Would stop: Forex live #{self.live_other.pk}, Stocks "
                      f"live #{live.pk} — the brake is off", texts[0])
        _component(morgul.BRAKE_KEY)
        report, texts = self._cycle(guards, at=self.now + timedelta(minutes=30))
        self.assertEqual(self._enabled(live, self.live_other, self.cfg),
                         [False, False, True])
        self.assertIn(f"Stopped: Forex live #{self.live_other.pk}, Stocks "
                      f"live #{live.pk} — no position was closed", texts[0])
        # the reminder, three hours after "Stopped" was said, says the
        # brake acted earlier
        _r, texts = self._cycle(guards, at=self.now + timedelta(hours=3,
                                                                minutes=30))
        self.assertIn(f"Stopped earlier by the brake: Forex live "
                      f"#{self.live_other.pk}, Stocks live #{live.pk}",
                      texts[0])
        self.assertEqual(sorted(AssetBotTrade.objects.values_list(
            "pk", "status", "exit_price", "closed_at")), before)


# ── the command ──────────────────────────────────────────────────────────

class CommandTests(_Case):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.cfg = _cfg(self.user, "Stocks live", "stock", mode="live")
        _trade(self.cfg, "AAPL", entry="336", stop="326", paper=False,
               metadata={"protected": True})
        _trade(self.cfg, "AAPL", entry="337", stop="327", paper=False,
               metadata={"protected": True})
        _trade(self.cfg, "MSFT", entry="420", stop="410", paper=False,
               status="CLOSED", exit_price="380", pnl="-900",
               metadata={"protected": True},
               opened=now - timedelta(hours=3),
               closed=now - timedelta(hours=1))
        _trade(self.cfg, "NVDA", entry="180", stop="170", paper=False,
               status="CLOSE_PENDING", metadata={"protected": True})
        _arm()

    def _pledged_past_the_limit(self):
        """A braking finding (G6) — the daily loss stopped braking on
        2026-10-01."""
        _etoro(self.user, demo=False, is_primary_for_stocks=True,
               last_equity=Decimal("100"), last_equity_currency="USD",
               last_used_margin=Decimal("90"),
               last_margin_at=timezone.now() - timedelta(minutes=5),
               last_margin_world="live")

    def test_it_prints_the_findings_and_sends_and_stops_nothing(self):
        self._pledged_past_the_limit()
        out = StringIO()
        with patch(SEND, return_value=True) as send:
            call_command("morgul", stdout=out)
        text = out.getvalue()
        self.assertIn("[warning] Duplicates · AAPL long · live · Stocks live "
                      "#", text)
        self.assertIn("[critical] Daily loss · Live bots of account #", text)
        self.assertIn(f"Brake: on — it would stop Stocks live "
                      f"#{self.cfg.pk}", text)
        self.assertIn("Read only: nothing was sent and nothing was stopped",
                      text)
        send.assert_not_called()
        self.cfg.refresh_from_db()
        self.assertTrue(self.cfg.enabled)
        self.assertIsNone(cache.get(morgul.STATE_KEY))
        self.assertIsNone(cache.get(morgul.SUMMARY_KEY))
        self.assertIsNone(cache.get(
            morgul.SINCE_KEY.format(scope="stuck_close")))
        self.assertIsNone(cache.get(morgul.LOCK_KEY))

    def test_send_runs_the_beat_cycle(self):
        self._pledged_past_the_limit()
        out = StringIO()
        with patch(SEND, return_value=True) as send:
            call_command("morgul", "--send", stdout=out)
        self.assertGreaterEqual(send.call_count, 2)
        self.cfg.refresh_from_db()
        self.assertFalse(self.cfg.enabled)
        self.assertIn(f"stopped: Stocks live #{self.cfg.pk}", out.getvalue())
        self.assertIsNotNone(cache.get(morgul.SUMMARY_KEY))
        self.assertIsNotNone(cache.get(
            morgul.SINCE_KEY.format(scope="stuck_close")))

    def test_send_with_the_guards_off_stops_nothing(self):
        _component(morgul.COMPONENT_KEY, on=False)
        out = StringIO()
        with patch(SEND, return_value=True):
            call_command("morgul", "--send", stdout=out)
        self.cfg.refresh_from_db()
        self.assertTrue(self.cfg.enabled)
        self.assertIn("stopped: nothing", out.getvalue())

    def test_a_held_lock_is_said_and_nothing_runs(self):
        cache.add(morgul.LOCK_KEY, "held", 60)
        out = StringIO()
        with patch(SEND, return_value=True) as send:
            call_command("morgul", "--send", stdout=out)
        send.assert_not_called()
        self.assertIn("Nothing done: another Morgul run is in progress",
                      out.getvalue())


# ── what the platform shows ──────────────────────────────────────────────

class ShowTests(_Case):
    def _summary(self, findings, at=None):
        cache.set(morgul.SUMMARY_KEY, {
            "at": (at or timezone.now()).isoformat(), "guards": 10,
            "failed": [], "findings": findings})

    def test_the_health_row(self):
        from dashboard.views_system_health import (check_morgul_guards,
                                                   system_health)
        row = check_morgul_guards()
        # off is "not set up", never a fault that turns the page DEGRADED
        self.assertEqual((row["label"], row["state"], row["detail"],
                          row["configured"]),
                         ("Morgul guards", "ok",
                          "off — nothing watches the book", False))
        _component(morgul.COMPONENT_KEY)
        self._summary([])
        row = check_morgul_guards()
        self.assertEqual((row["state"], row["detail"]),
                         ("ok", "quiet — 10 guards, last run just now"))
        self._summary([{"name": "Daily loss", "severity": "critical",
                        "label": "x"}])
        row = check_morgul_guards()
        self.assertEqual((row["state"], row["detail"]),
                         ("fail", "1 finding: Daily loss (last run just now)"))
        self.assertIn("(check_morgul_guards, False, True)",
                      inspect.getsource(system_health))
        self.client.force_login(self.user)
        page = self.client.get("/health/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Morgul guards")
        self.assertContains(page, "1 finding: Daily loss")

    def test_the_eye_status_line(self):
        def lines():
            with patch(FAULTS, return_value=CLEAR):
                return [str(ln) for ln in eye.build_status(self.user).lines]
        self.assertIn("Guards: off", lines())
        _component(morgul.COMPONENT_KEY)
        self.assertIn("Guards: no run recorded yet", lines())
        self._summary([])
        self.assertIn("Guards: all quiet", lines())
        self._summary([{"name": "Daily loss", "severity": "critical"},
                       {"name": "Duplicates", "severity": "warning"}])
        self.assertIn("Guards: 2 findings — Daily loss, Duplicates", lines())
        self._summary([], at=timezone.now() - timedelta(hours=1))
        self.assertIn("Guards: all quiet (last ran 1 h ago)", lines())


# ── the house style ──────────────────────────────────────────────────────

class StyleTests(_Case):
    def test_every_message_is_english_escaped_and_fits(self):
        now = timezone.now()
        live = _cfg(self.user, "Stocks <live>", "stock", mode="live")
        paper = _cfg(self.user)
        _trade(paper, "EURCAD", status="CLOSED", exit_price="1.61",
               opened=FRI, closed=SAT_CLOSE)
        _trade(live, "AAPL", entry="336", stop="326", paper=False,
               opened=now - timedelta(hours=1),
               metadata={"protected": False, "protection_note":
                         "PaperTrader said stop_leg None"})
        _trade(live, "AAPL", entry="336", stop="326", paper=False,
               metadata={"protected": True})
        _trade(live, "NVDA", entry="180", stop="170", paper=False,
               opened=now - timedelta(hours=1),
               metadata=dict(LIVE_ETORO, stop_rewritten_by_venue={
                   "sent": 170.0, "held": 0.0001}))
        _trade(live, "MSFT", entry="420", stop="410", paper=False,
               status="CLOSE_PENDING",
               metadata={"close_retry_attempts": 60, "protected": True})
        _trade(live, "TSLA", entry="250", stop="240", paper=False,
               status="CLOSED", exit_price="200", pnl="-900",
               opened=now - timedelta(hours=3),
               closed=now - timedelta(hours=1))
        _cfg(self.user, "Never halts", "stock", mode="live",
             halt_on_drawdown=False)
        _etoro(self.user, demo=False, is_primary_for_stocks=True,
               last_equity=Decimal("100"), last_equity_currency="EUR",
               last_used_margin=Decimal("90"),
               last_margin_at=now - timedelta(days=3),
               last_margin_world="demo", broker_positions=[
                   {"symbol": "ETORO:1001"}],
               broker_positions_at=now - timedelta(minutes=5))
        findings = []
        for key, at in (("market_shut", SAT_NOW), ("no_stop", now),
                        ("stuck_close", WED), ("duplicates", now),
                        ("margin", now), ("daily_loss", now)):
            findings += _check(key, at)[1]
        findings += morgul.collect(now=now, guards=[morgul.Guard(
            "boom", "Boom", "critical", "Morgul — boom",
            lambda c, g: 1 / 0)])[1]
        self.assertGreaterEqual(len(findings), 8)
        left = {"broker": 3, "bare": 2, "paper": 1}
        outcomes = {}
        kinds = [("would", ["Forex swing #1"]),
                 ("stopped", ["Forex swing #1"], [], left),
                 ("earlier", ["Forex swing #1"], [], left),
                 ("held", ["Forex swing #1"]),
                 ("failed", ["Forex swing #1"], "RuntimeError")]
        for i, f in enumerate(findings):
            outcomes[f.key] = kinds[i % len(kinds)]
        replies = morgul.build_messages(findings, outcomes, now)
        replies.append(morgul.back_to_normal(
            [{"name": "Stuck close", "label": "MSFT long #9"},
             {"name": "Daily loss", "label": "Live bots of account #1 · USD",
              "braked": True}], now))
        self.assertGreaterEqual(len(replies), 7)
        for reply in replies:
            text = eye.fit(reply).text()
            with self.subTest(title=reply.title):
                self.assertTrue(text.startswith(f"<b>{morgul.MARK} Morgul — "),
                                text)
                self.assertNotIn("None", text)
                self.assertNotIn("Decimal(", text)
                self.assertEqual(SNAKE.findall(text), [])
                self.assertIsNone(ACCENTED.search(text), text)
                for word in FRENCH:
                    self.assertNotIn(word, text.lower())
                self.assertLessEqual(len(text.split("\n")), eye.MAX_LINES + 1)
                self.assertLessEqual(len(text), eye.TELEGRAM_MAX_CHARS)
                self.assertNotIn("<live>", text)
        joined = "\n".join(eye.fit(r).text() for r in replies)
        self.assertIn("Stocks &lt;live&gt;", joined)
        self.assertIn("Broker note: paper trader said stop leg —", joined)
        self.assertIn("eToro holds no stop: sent 170.00", joined)
        self.assertIn("At the broker without a stop: 2", joined)
        self.assertIn("the brake held back", joined)


# ── the wiring ───────────────────────────────────────────────────────────

class WiringTests(TestCase):
    def test_the_two_registry_rows_arrive_off_and_fit(self):
        from core.platform_control import (DEFAULT_COMPONENTS,
                                           PlatformComponent, seed_components)
        seed_components()
        for key in (morgul.COMPONENT_KEY, morgul.BRAKE_KEY):
            entry = next(c for c in DEFAULT_COMPONENTS if c["key"] == key)
            self.assertLessEqual(len(entry["description"]), 300)
            self.assertLessEqual(len(entry["name"]), 100)
            self.assertEqual(entry["category"], "system")
            self.assertNotIn("is_enabled", entry)
            self.assertFalse(PlatformComponent.objects.get(key=key).is_enabled)

    def test_the_systems_all_on_button_never_arms_the_brake(self):
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           PlatformComponent, seed_components)
        # The brake was the first exempt switch; the live-money switches
        # joined it on 2026-09-28 (tests/test_ops_cockpit.py names them).
        self.assertIn(morgul.BRAKE_KEY, BULK_ENABLE_EXEMPT)
        seed_components()
        admin = User.objects.create_superuser("root", "root@example.test", "x")
        self.client.force_login(admin)

        def state():
            return {k: PlatformComponent.objects.get(key=k).is_enabled
                    for k in (morgul.COMPONENT_KEY, morgul.BRAKE_KEY)}
        self.client.post("/admin-dashboard/bulk-toggle/",
                         {"category": "system", "action": "enable",
                          "next": "ops"})
        self.assertEqual(state(), {morgul.COMPONENT_KEY: True,
                                   morgul.BRAKE_KEY: False})
        PlatformComponent.objects.filter(key=morgul.BRAKE_KEY).update(
            is_enabled=True)
        self.client.post("/admin-dashboard/bulk-toggle/",
                         {"category": "system", "action": "disable",
                          "next": "ops"})
        self.assertEqual(state(), {morgul.COMPONENT_KEY: False,
                                   morgul.BRAKE_KEY: False})

    def test_the_beat_entry_and_the_fast_route(self):
        from celery.app.routes import MapRoute
        from config.celery import app
        entry = app.conf.beat_schedule["run-morgul-guards"]
        self.assertEqual(entry["task"], "bot_program.tasks.run_morgul_guards")
        self.assertEqual(entry["schedule"], 300.0)
        self.assertEqual(entry["options"], {"expires": 240})
        route = MapRoute(app.conf.task_routes)
        self.assertEqual(
            (route("bot_program.tasks.run_morgul_guards") or {}).get("queue"),
            "fast")

    def test_the_command_is_in_the_ops_registry_and_not_on_the_web(self):
        from core import ops_commands
        entry = ops_commands.get("morgul")
        self.assertEqual(entry["category"], "decide")
        self.assertFalse(entry["read_only"])
        self.assertFalse(ops_commands.is_runnable(entry))
        self.assertNotIn("morgul", ops_commands.runnable_names())

    def test_the_guarded_task_runs_only_while_its_component_is_on(self):
        from bot_program.tasks import run_morgul_guards
        from core.platform_control import PlatformComponent
        cache.clear()
        self.addCleanup(cache.clear)
        _component("platform_master")
        _component(morgul.COMPONENT_KEY, on=False)
        with patch(SEND, return_value=True) as send:
            self.assertEqual(run_morgul_guards()["status"], "skipped")
            send.assert_not_called()
            _component(morgul.COMPONENT_KEY, on=True)
            result = run_morgul_guards()
            # a run that finds the lock held is idle: the row keeps its
            # verdict, nothing is sent
            cache.add(morgul.LOCK_KEY, "held", 60)
            idle = run_morgul_guards()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["guards"], 11)
        self.assertEqual(idle["idle"], "another Morgul run is in progress")
        row = PlatformComponent.objects.get(key=morgul.COMPONENT_KEY)
        self.assertEqual(row.last_status, "success")
        self.assertEqual(row.run_count, 1)

    def test_the_module_carries_no_call_that_trades_or_writes(self):
        src = inspect.getsource(morgul)
        for needle in ("enabled = True", "update(enabled", "market_order",
                       "close_position", "cancel_order", "modify_protective",
                       "requests.", "EtoroTrader(", "client_for_symbol",
                       "set_credentials", "is_enabled =", "select_for_update",
                       "objects.create(", ".delete()", "update_or_create",
                       "bulk_update", "mark_run"):
            self.assertNotIn(needle, src)
        self.assertEqual(re.findall(r"\.save\(", src), [])
        self.assertEqual(src.count("apply_brake("), 1)
        # G12 stop overshoot joined on 2026-10-02 (tests/test_morgul_overshoot.py).
        self.assertEqual(len(morgul.GUARDS), 11)
        # The daily loss never brakes (2026-10-01): the engine's gate lets
        # only elite entries past the stop, and stops at the absolute one.
        self.assertEqual({g.key for g in morgul.GUARDS if g.brake},
                         {"market_shut", "proofs", "margin"})
