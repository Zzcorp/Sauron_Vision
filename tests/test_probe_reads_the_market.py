"""A regime probe is stale when it is behind its MARKET, not when it is old
(2026-09-26).

The brain's probe used one flat 30-hour limit, measured from the newest
bar's stamp, with no market clock. Daily bars are written once a day at
22:30 UTC and stamped at the START of their day, so a perfectly fed 1d
forex probe read "stale" every weekday from about 05:00 UTC until the next
run, and all weekend. "Probes 7 of 9 stale at 35h" was a healthy Saturday
morning; "Sauron's mind is not synthesizing: the bars are stale" was a
false claim about a live feed.

And the bar writer took its thirty starred slots BEFORE skipping the
symbols a bot config already covers, so a pair held only through the
manual lane — whose config carries no symbols by design — could get no
4h/1h bars at all.

The fixed clock is Saturday 2026-09-26, 10:00 UTC: British and US summer
time, so the Friday daily forex bar is stamped Thursday 23:00 UTC (Friday
00:00 London) and the FX week shut at 21:00 UTC on Friday.

Run with:  python manage.py test tests.test_probe_reads_the_market
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

SATURDAY = datetime(2026, 9, 26, 10, 0, tzinfo=dt_timezone.utc)
# Friday 00:00 London — the stamp yfinance gives Friday's daily forex bar.
FRIDAY_FX_DAY = SATURDAY - timedelta(hours=35)
# Friday 00:00 New York — the stamp of Friday's daily stock bar.
FRIDAY_STOCK_DAY = SATURDAY - timedelta(hours=30)
# The 4h bar that opened at 01:00 UTC on Friday.
FRIDAY_0100 = SATURDAY - timedelta(hours=33)

_WIDTH = {"1d": timedelta(days=1), "4h": timedelta(hours=4),
          "1h": timedelta(hours=1)}
_NO_COST = ("{}", {"input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0})


def _instrument(symbol, asset_class, *, star=True):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    Instrument.objects.filter(pk=inst.pk).update(
        asset_class=asset_class, is_active=True, is_watchlist=star)
    inst.refresh_from_db()
    return inst


def _frame(inst, *, newest, timeframe, n=40):
    """`n` bars on one frame, the newest stamped `newest` (its START)."""
    from market_data.models import PriceData
    PriceData.objects.bulk_create([
        PriceData(instrument=inst, timeframe=timeframe,
                  timestamp=newest - _WIDTH[timeframe] * i,
                  open=Decimal("1.1"), high=Decimal("1.2"),
                  low=Decimal("1.0"),
                  close=Decimal(110 + i % 7 - i % 3) / 100,
                  volume=1, source="test")
        for i in range(n)])


def _probes_at(now):
    from brain.synthesizer import _build_world_snapshot
    with mock.patch("django.utils.timezone.now", return_value=now):
        snap = _build_world_snapshot()
    return {p["symbol"]: p for p in snap["regime_probes"]}


def _synthesize_at(now):
    from brain.synthesizer import synthesize_now
    with mock.patch("django.utils.timezone.now", return_value=now), \
            mock.patch("ai_agents.providers.claude_provider.ClaudeProvider"
                       ".complete", return_value=_NO_COST) as complete:
        out = synthesize_now()
    return out, complete


class ASaturdayReadOfAHealthyFridayFeedIsFreshTests(TestCase):

    def test_the_friday_daily_forex_bar_is_fresh_on_saturday_morning(self):
        """The exact read that was reported as "stale at 35h"."""
        _frame(_instrument("EURUSD", "forex"), newest=FRIDAY_FX_DAY,
               timeframe="1d")
        probe = _probes_at(SATURDAY)["EURUSD"]
        self.assertEqual(probe["timeframe"], "1d")
        self.assertFalse(probe["stale"], probe)
        # Counted from the bar's CLOSE (Friday 23:00 UTC), not its stamp.
        self.assertEqual(probe["last_bar_age_hours"], 11.0)
        self.assertEqual(probe["market"], "forex")
        self.assertFalse(probe["market_open"])

    def test_it_stays_fresh_all_weekend_and_until_mondays_run(self):
        _frame(_instrument("EURUSD", "forex"), newest=FRIDAY_FX_DAY,
               timeframe="1d")
        for label, now in (("Saturday 10:00", SATURDAY),
                           ("Sunday 20:00", SATURDAY + timedelta(hours=34)),
                           ("Monday 22:00", SATURDAY + timedelta(hours=60))):
            with self.subTest(label):
                self.assertFalse(_probes_at(now)["EURUSD"]["stale"])

    def test_a_weekday_daily_frame_is_fresh_all_day_before_the_run(self):
        """Wednesday, from 05:00 UTC to just before 22:30, holding Tuesday's
        bar — the hours the flat limit called stale every weekday."""
        wednesday = SATURDAY - timedelta(days=3)          # 10:00 UTC
        tuesday_fx_day = wednesday - timedelta(hours=35)  # Tue 00:00 London
        _frame(_instrument("EURUSD", "forex"), newest=tuesday_fx_day,
               timeframe="1d")
        for hour in (5, 12, 22):
            now = wednesday.replace(hour=hour, minute=29)
            with self.subTest(f"Wednesday {hour}:29"):
                self.assertFalse(_probes_at(now)["EURUSD"]["stale"])

    def test_the_friday_daily_stock_bar_is_fresh_on_saturday(self):
        _frame(_instrument("AAPL", "stock"), newest=FRIDAY_STOCK_DAY,
               timeframe="1d")
        probe = _probes_at(SATURDAY)["AAPL"]
        self.assertFalse(probe["stale"], probe)
        self.assertEqual(probe["market"], "us_equity")

    def test_a_healthy_saturday_is_synthesized_not_skipped(self):
        for sym in ("EURUSD", "GBPUSD"):
            _frame(_instrument(sym, "forex"), newest=FRIDAY_FX_DAY,
                   timeframe="1d")
        out, complete = _synthesize_at(SATURDAY)
        complete.assert_called_once()
        self.assertNotEqual(out.get("status"), "skipped", out)


class AFrameThatStoppedIsStaleTests(TestCase):

    def test_a_4h_frame_that_stopped_friday_0100_is_stale_on_saturday(self):
        """The FX week ran until 21:00 UTC on Friday. A frame that stopped
        at 01:00 is sixteen hours short of that close — the shut market
        does not cover for it."""
        _frame(_instrument("EURUSD", "forex"), newest=FRIDAY_0100,
               timeframe="4h")
        probe = _probes_at(SATURDAY)["EURUSD"]
        self.assertEqual(probe["timeframe"], "4h")
        self.assertTrue(probe["stale"], probe)
        self.assertEqual(probe["last_bar_age_hours"], 29.0)

    def test_it_was_already_stale_on_friday_while_the_market_traded(self):
        _frame(_instrument("EURUSD", "forex"), newest=FRIDAY_0100,
               timeframe="4h")
        friday_noon = SATURDAY - timedelta(hours=22)
        probe = _probes_at(friday_noon)["EURUSD"]
        self.assertTrue(probe["market_open"])
        self.assertTrue(probe["stale"], probe)

    def test_a_daily_frame_that_missed_its_run_is_stale(self):
        """Thursday 10:00 UTC holding Tuesday's bar: Wednesday's 22:30 run
        never wrote Wednesday's."""
        thursday = SATURDAY - timedelta(days=2)
        tuesday_fx_day = thursday - timedelta(days=1, hours=35)
        _frame(_instrument("EURUSD", "forex"), newest=tuesday_fx_day,
               timeframe="1d")
        self.assertTrue(_probes_at(thursday)["EURUSD"]["stale"])

    def test_a_stale_daily_frame_gives_way_to_a_fed_4h_frame(self):
        thursday = SATURDAY - timedelta(days=2)
        inst = _instrument("EURUSD", "forex")
        _frame(inst, newest=thursday - timedelta(days=1, hours=35),
               timeframe="1d")
        _frame(inst, newest=thursday - timedelta(hours=1), timeframe="4h")
        probe = _probes_at(thursday)["EURUSD"]
        self.assertEqual(probe["timeframe"], "4h")
        self.assertFalse(probe["stale"], probe)

    def test_crypto_never_shuts_so_three_hours_behind_is_stale(self):
        _frame(_instrument("BTCUSD", "crypto"),
               newest=SATURDAY - timedelta(hours=7), timeframe="4h")
        probe = _probes_at(SATURDAY)["BTCUSD"]
        self.assertTrue(probe["market_open"])
        self.assertTrue(probe["stale"], probe)

    def test_the_gate_skips_and_names_what_is_behind(self):
        User.objects.create_user("probe_staff", password="x", is_staff=True)
        for sym in ("EURUSD", "GBPUSD"):
            _frame(_instrument(sym, "forex"), newest=FRIDAY_0100,
                   timeframe="4h")
        out, complete = _synthesize_at(SATURDAY)
        complete.assert_not_called()
        self.assertEqual(out["status"], "skipped")
        self.assertIn("stale", out["reason"])
        self.assertIn("EURUSD 4h closed 29h ago", out["reason"])


class AHeldManualPairGetsBarsTests(TestCase):
    """Thirty starred stocks sort ahead of the pair the book holds."""

    def setUp(self):
        from bot_program.manual_trade import manual_config_for
        from bot_program.models import AssetBotTrade
        self.user = User.objects.create_user("bars_manual", password="x")
        cfg = manual_config_for(self.user, "forex")
        self.assertEqual(cfg.symbols, [])
        self.starred = [f"AAA{i:02d}" for i in range(30)]
        for sym in self.starred:
            _instrument(sym, "stock")
        # Thirty-one keyless symbols would each breathe PUBLIC_FEED_PACE_S.
        pacer = mock.patch("market_data.bot_bars._pace")
        pacer.start()
        self.addCleanup(pacer.stop)
        AssetBotTrade.objects.create(
            config=cfg, asset_class="forex", symbol="USDCHF", side="BUY",
            qty=Decimal("1000"), entry_price=Decimal("0.8116"),
            status="OPEN", paper=True, rule_name="manual_take",
            opened_at=SATURDAY)
        self.feed = mock.MagicMock()
        self.feed._sv_public_feed = True
        base = int(SATURDAY.timestamp() * 1000) - 3 * 3600_000
        self.feed.klines = mock.MagicMock(return_value=[
            [base + i * 3600_000, "0.81", "0.82", "0.80", "0.81", "0"]
            for i in range(3)])

    def _fetched(self):
        return [c.args[0] for c in self.feed.klines.call_args_list]

    def _refresh(self, **kwargs):
        from market_data import bot_bars
        with mock.patch("market_data.public_feed.public_feed_for",
                        return_value=self.feed):
            if kwargs:
                return bot_bars.refresh_watchlist_bars(**kwargs)
            return bot_bars.refresh_bot_bars()

    def _frames(self, symbol):
        from market_data.models import PriceData
        return set(PriceData.objects.filter(instrument__symbol=symbol)
                   .values_list("timeframe", flat=True))

    def test_a_held_manual_only_pair_past_the_thirtieth_star_gets_bars(self):
        _instrument("USDCHF", "forex")          # starred, and 31st in line
        self._refresh()
        self.assertEqual(self._frames("USDCHF"), {"4h", "1h"})

    def test_an_unstarred_held_pair_gets_bars_too(self):
        _instrument("USDCHF", "forex", star=False)
        self._refresh()
        self.assertEqual(self._frames("USDCHF"), {"4h", "1h"})

    def test_the_held_pair_does_not_spend_a_starred_slot(self):
        from market_data.bot_bars import WATCHLIST_BAR_CAP
        _instrument("USDCHF", "forex")
        out = self._refresh(covered=set())
        self.assertEqual(out["symbols"], WATCHLIST_BAR_CAP + 1)
        self.assertIn("AAA29", self._fetched())

    def test_covered_symbols_no_longer_spend_the_cap(self):
        """Every starred stock is on a bot config; the one star after them
        used to fall outside the first thirty and get nothing."""
        _instrument("ZZZLATE", "stock")
        self._refresh(covered=set(self.starred))
        fetched = self._fetched()
        self.assertIn("ZZZLATE", fetched)
        self.assertFalse(set(self.starred) & set(fetched))
