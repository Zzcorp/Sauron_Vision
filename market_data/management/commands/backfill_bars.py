"""Backfill historical OHLCV bars for every asset class, keylessly.

Crypto comes from Binance's public klines endpoint, paginated; everything
else — stocks, ETFs, indices, commodities, forex — from the same keyless
Yahoo feed `refresh_bot_bars` falls back to (market_data.public_feed), in
one call, because Yahoo serves ten years of daily bars at once.

WHY EVERY CLASS. The signal scanner reads DAILY closes, and every evaluator
needs a lookback — twenty bars, fifty, two hundred. The scheduled feeds
write one daily bar per day, so an instrument created on Monday had six by
Thursday, no evaluator could compute, and the ETF bot that could afford its
symbols sat on `no_signals` for what would have been a month. That was the
2026-09-10 state of this platform's first live deployment: the bars
arrived, and nothing could use them.

The scheduled feed (`refresh_bot_bars`) fetches the most recent 200 bars per
symbol every ten minutes. That is the right shape for keeping current and the
wrong shape for starting: 200 4h bars is ~33 days, while `scan_symbol` asks
for 500, `_load_df` asks for 300, and GoldenCrossRule needs 210 before it can
compute an SMA200 at all. A fresh install therefore sits below the threshold
of every long-window rule indefinitely — the bars arrive, and nothing can use
them.

This command paginates backwards with `startTime` until it has the history
the rule layer actually needs.

No API key is required and no account is involved: Binance spot klines are
public. It uses the LIVE endpoint deliberately, even for paper configs —
testnet kline history is synthetic, and a rule validated against invented
candles has been validated against nothing.

    python manage.py backfill_bars --symbols BTCUSD,ETHUSD
    python manage.py backfill_bars --symbols BTCUSD --intervals 4h --bars 800
    python manage.py backfill_bars --symbols GLDM,SLV --intervals 1d --bars 300
    python manage.py backfill_bars --from-configs        # every enabled bot
    python manage.py backfill_bars --proving             # THE PROVING RUN's history

THE PROVING RUN (2026-10-05, `--proving`). The proving ground
(backtester/proving) refuses to judge a symbol on less than
MIN_SPAN_DAYS / MIN_BARS of 4h history (540 days, 800 bars), and nothing
on the platform ever fetched that much: refresh_bot_bars keeps the newest
200 bars, and this command's default of 600 4h bars is 100 days — so
every verdict read INSUFFICIENT and the proof-first gates had nothing to
read. `--proving` takes every symbol the proving ground would judge (the
enabled bots' symbols, the symbols of open positions, and every active
instrument of a traded class that already has 4h bars), at 4h, PROVING_BARS
deep: Yahoo answers two years of hourly bars resampled to 4h (a US stock
~1,000 bars over 730 days, a forex pair ~3,100), Binance paginates. Retention
for 1h/4h bars is three years, so the history stays. A hand-typed
--intervals or --bars still wins. Nothing trades; no key is needed.

Symbols are the platform's own spelling (BTCUSD), translated to the venue's
(BTCUSDT) on the way out — the same mapping `market_data.quotes` uses, so a
backfilled bar and a live quote agree about what instrument they describe.
"""
from __future__ import annotations

import time
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

# Binance caps a single klines response at 1000 rows.
PAGE_LIMIT = 1000
# Be a good citizen on a public endpoint. The weight limit is generous but
# a tight loop over several symbols is still rude.
SLEEP_BETWEEN_PAGES = 0.25

INTERVAL_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480, "12h": 720,
    "1d": 1440, "3d": 4320, "1w": 10080,
}

#: The default target bars per symbol per interval, and the proving run's
#: (`--proving`, 4h only): 4000 4h bars is 667 calendar days — past the
#: proving ground's MIN_SPAN_DAYS (540) with a margin, and past what Yahoo
#: can answer (730 days of hourly), so the feed's cap is the limit there.
DEFAULT_BARS = 600
PROVING_BARS = 4000
PROVING_INTERVALS = "4h"
DEFAULT_INTERVALS = "1h,4h"


# Renames Binance made under the platform's feet. MATIC became POL in
# September 2024 and MATICUSDT stopped answering; the fleet-wide backfill
# of 2026-09-10 got zero pages for it.
BINANCE_RENAMES = {"MATICUSD": "POLUSDT"}
_CATALOGUE_SPELLING = {venue: ours for ours, venue in BINANCE_RENAMES.items()}


def venue_symbol(symbol: str) -> str:
    """Platform spelling -> Binance spelling.

    The platform says BTCUSD; Binance lists BTCUSDT. Getting this wrong
    yields an empty response rather than an error, which looks exactly like
    "no history available".
    """
    s = symbol.upper()
    if s in BINANCE_RENAMES:
        return BINANCE_RENAMES[s]
    if s.endswith("USDT"):
        return s
    if s.endswith("USD"):
        return s[:-3] + "USDT"
    return s


def catalogue_symbol(symbol: str) -> str:
    """Binance spelling -> platform spelling, for the pairs Binance renamed.

    The reverse of `venue_symbol` for BINANCE_RENAMES only; the stablecoin
    suffix stays the business of `market_data.quotes` (BTCUSDT resolves to
    BTCUSD there). Nothing can infer that POLUSDT is the catalogue's
    MATICUSD, so a tick that arrived under the venue's spelling resolved
    to no instrument and was dropped, and the headband's MATICUSD card
    never saw the stream that ticked for it every second.
    """
    s = (symbol or "").upper()
    return _CATALOGUE_SPELLING.get(s, s)


class Command(BaseCommand):
    help = ("Backfill historical bars for every asset class: Binance public "
            "klines for crypto, the keyless Yahoo feed for the rest.")

    def add_arguments(self, parser):
        parser.add_argument("--symbols", type=str, default="",
                            help="Comma-separated, platform spelling (BTCUSD,ETHUSD).")
        parser.add_argument("--from-configs", action="store_true",
                            help="Take symbols from every enabled AssetBotConfig.")
        parser.add_argument("--proving", action="store_true",
                            help="THE PROVING RUN's history: every symbol the "
                                 "proving ground would judge (enabled bots, open "
                                 "positions, every active instrument of a traded "
                                 "class with 4h bars), at 4h, "
                                 f"{PROVING_BARS} bars deep.")
        parser.add_argument("--intervals", type=str, default=None,
                            help=f"Comma-separated timeframes. Default "
                                 f"{DEFAULT_INTERVALS}; {PROVING_INTERVALS} with "
                                 f"--proving.")
        parser.add_argument("--bars", type=int, default=None,
                            help=f"Target bars per symbol per interval. Default "
                                 f"{DEFAULT_BARS} — comfortably above the 210 an "
                                 f"SMA200 needs; {PROVING_BARS} with --proving.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Fetch and report, write nothing.")

    @staticmethod
    def proving_symbols() -> list:
        """The proving run's symbols (2026-10-05): the enabled bots', the
        open positions', and every active instrument of a traded class
        that already has 4h bars (backtester.proving.run.universe — the
        set the nightly judge walks). Sorted, unique, platform spelling."""
        from backtester.proving.run import universe
        from bot_program.models import AssetBotConfig, AssetBotTrade
        out = set()
        for cfg in AssetBotConfig.objects.filter(enabled=True):
            out.update(s.upper() for s in (cfg.symbols or []))
        out.update(s.upper() for s in AssetBotTrade.objects.filter(
            status__in=("OPEN", "CLOSE_PENDING")).values_list("symbol",
                                                             flat=True))
        for syms in universe(timeframe="4h").values():
            out.update(s.upper() for s in syms)
        return sorted(out)

    def handle(self, *args, **opts):
        from instruments.models import Instrument
        from market_data.bot_bars import _upsert_rows
        from bot_program.engine.binance_client import BinanceClient

        proving = bool(opts.get("proving"))
        symbols = [s.strip().upper() for s in opts["symbols"].split(",") if s.strip()]
        if opts["from_configs"]:
            from bot_program.models import AssetBotConfig
            for cfg in AssetBotConfig.objects.filter(enabled=True):
                symbols.extend(s.upper() for s in (cfg.symbols or []))
            symbols = sorted(set(symbols))
        if proving:
            symbols = sorted(set(symbols) | set(self.proving_symbols()))
        if not symbols:
            raise CommandError(
                "No symbols. Pass --symbols GLDM,EURUSD, --from-configs "
                "(which needs an enabled bot config to read from) or "
                "--proving (which needs a bot, a position or an instrument "
                "with 4h bars).")

        raw_intervals = opts.get("intervals") or (
            PROVING_INTERVALS if proving else DEFAULT_INTERVALS)
        intervals = [i.strip() for i in raw_intervals.split(",") if i.strip()]
        for iv in intervals:
            if iv not in INTERVAL_MINUTES:
                raise CommandError(f"Unsupported interval {iv!r}. "
                                   f"Known: {', '.join(INTERVAL_MINUTES)}")

        target = int(opts.get("bars") or (PROVING_BARS if proving
                                          else DEFAULT_BARS))
        dry = opts["dry_run"]
        if proving:
            self.stdout.write(
                f"THE PROVING RUN: {len(symbols)} symbol(s) at "
                f"{', '.join(intervals)}, {target} bars deep"
                + (" (dry run)" if dry else ""))
        client = BinanceClient("", "", testnet=False)

        grand_total = 0
        for symbol in symbols:
            inst = Instrument.objects.filter(symbol=symbol).first()
            if inst is None:
                self.stderr.write(self.style.WARNING(
                    f"  {symbol}: no Instrument row — run seed_instruments first, "
                    f"or check the spelling against the seeded set"))
                continue

            for interval in intervals:
                if inst.asset_class == "crypto":
                    written = self._backfill_one(
                        client, inst, symbol, interval, target, dry,
                        _upsert_rows)
                else:
                    written = self._backfill_public(
                        inst, symbol, interval, target, dry, _upsert_rows)
                grand_total += written

        verb = "would write" if dry else "wrote"
        self.stdout.write(self.style.SUCCESS(
            f"\nBackfill complete — {verb} {grand_total} bars across "
            f"{len(symbols)} symbol(s) x {len(intervals)} interval(s)."))
        if proving:
            from backtester.proving.data import MIN_BARS, MIN_SPAN_DAYS
            self.stdout.write(
                f"The proving ground needs {MIN_SPAN_DAYS['4h']} days and "
                f"{MIN_BARS['4h']} bars at 4h per symbol. Next: "
                f"`python manage.py prove data` says who is still short; "
                f"`python manage.py component on proving_ground` arms the "
                f"nightly judge (03:40 UTC); `python manage.py prove rules "
                f"--save` judges the live rules now. Nothing trades.")
        if not dry:
            self.stdout.write(
                "Next: python manage.py shell -c "
                "\"from indicators.tasks import recalculate_all_indicators as r; print(r())\"")

    def _backfill_public(self, inst, symbol, interval, target, dry,
                         upsert) -> int:
        """Every non-crypto class, through the keyless feed, in ONE call.

        Yahoo answers with the whole window (ten years of daily bars, two
        of hourly) and the feed trims to `limit`, so there is nothing to
        paginate. A class with no keyless source is named and skipped,
        never invented.
        """
        from market_data.public_feed import public_feed_for

        feed = public_feed_for(inst.asset_class)
        if feed is None:
            self.stderr.write(self.style.WARNING(
                f"  {symbol} {interval}: no keyless source for asset class "
                f"{inst.asset_class!r} — nothing written"))
            return 0
        try:
            rows = feed.klines(symbol, interval=interval, limit=target)
        except Exception as e:  # noqa: BLE001 — one symbol must not end the run
            self.stderr.write(self.style.ERROR(
                f"  {symbol} {interval}: public feed failed: {e}"))
            return 0
        written = 0
        if rows and not dry:
            written, _skipped = upsert(inst, interval, rows, "yfinance_public")
        self.stdout.write(
            f"  {symbol:10} {interval:4} {len(rows):5} bars fetched "
            f"(public feed){'' if dry else f', {written} written'}")
        return written if not dry else len(rows)

    def _backfill_one(self, client, inst, symbol, interval, target, dry,
                      upsert) -> int:
        vsym = venue_symbol(symbol)
        minutes = INTERVAL_MINUTES[interval]
        span = timedelta(minutes=minutes * target)
        cursor = int((timezone.now() - span).timestamp() * 1000)
        now_ms = int(timezone.now().timestamp() * 1000)

        collected = 0
        written_total = 0
        pages = 0
        while cursor < now_ms and collected < target:
            try:
                rows = client.klines(vsym, interval=interval,
                                     limit=PAGE_LIMIT, start_time=cursor)
            except Exception as e:
                self.stderr.write(self.style.ERROR(
                    f"  {symbol} {interval}: klines failed at page {pages + 1}: {e}"))
                break
            if not rows:
                break

            pages += 1
            collected += len(rows)
            if not dry:
                written, _skipped = upsert(inst, interval, rows,
                                           "binance_public")
                written_total += written

            # Advance past the last bar's OPEN time. Binance is inclusive on
            # startTime, so reusing it would refetch the same page forever.
            last_open = int(rows[-1][0])
            if last_open <= cursor:
                break
            cursor = last_open + minutes * 60 * 1000
            time.sleep(SLEEP_BETWEEN_PAGES)

        self.stdout.write(
            f"  {symbol:10} {interval:4} {collected:5} bars fetched "
            f"({pages} page(s)){'' if dry else f', {written_total} written'}")
        return written_total if not dry else collected
