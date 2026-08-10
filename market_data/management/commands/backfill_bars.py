"""Backfill historical OHLCV bars from Binance's public klines endpoint.

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
    python manage.py backfill_bars --from-configs        # every enabled bot

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


def venue_symbol(symbol: str) -> str:
    """Platform spelling -> Binance spelling.

    The platform says BTCUSD; Binance lists BTCUSDT. Getting this wrong
    yields an empty response rather than an error, which looks exactly like
    "no history available".
    """
    s = symbol.upper()
    if s.endswith("USDT"):
        return s
    if s.endswith("USD"):
        return s[:-3] + "USDT"
    return s


class Command(BaseCommand):
    help = "Backfill historical bars from Binance public klines."

    def add_arguments(self, parser):
        parser.add_argument("--symbols", type=str, default="",
                            help="Comma-separated, platform spelling (BTCUSD,ETHUSD).")
        parser.add_argument("--from-configs", action="store_true",
                            help="Take symbols from every enabled crypto AssetBotConfig.")
        parser.add_argument("--intervals", type=str, default="1h,4h",
                            help="Comma-separated timeframes. Default 1h,4h.")
        parser.add_argument("--bars", type=int, default=600,
                            help="Target bars per symbol per interval. Default 600 "
                                 "— comfortably above the 210 an SMA200 needs.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Fetch and report, write nothing.")

    def handle(self, *args, **opts):
        from instruments.models import Instrument
        from market_data.bot_bars import _upsert_rows
        from bot_program.engine.binance_client import BinanceClient

        symbols = [s.strip().upper() for s in opts["symbols"].split(",") if s.strip()]
        if opts["from_configs"]:
            from bot_program.models import AssetBotConfig
            for cfg in AssetBotConfig.objects.filter(enabled=True,
                                                     asset_class="crypto"):
                symbols.extend(s.upper() for s in (cfg.symbols or []))
            symbols = sorted(set(symbols))
        if not symbols:
            raise CommandError(
                "No symbols. Pass --symbols BTCUSD,ETHUSD or --from-configs "
                "(which needs an enabled crypto bot config to read from).")

        intervals = [i.strip() for i in opts["intervals"].split(",") if i.strip()]
        for iv in intervals:
            if iv not in INTERVAL_MINUTES:
                raise CommandError(f"Unsupported interval {iv!r}. "
                                   f"Known: {', '.join(INTERVAL_MINUTES)}")

        target = int(opts["bars"])
        dry = opts["dry_run"]
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
                written = self._backfill_one(
                    client, inst, symbol, interval, target, dry, _upsert_rows)
                grand_total += written

        verb = "would write" if dry else "wrote"
        self.stdout.write(self.style.SUCCESS(
            f"\nBackfill complete — {verb} {grand_total} bars across "
            f"{len(symbols)} symbol(s) x {len(intervals)} interval(s)."))
        if not dry:
            self.stdout.write(
                "Next: python manage.py shell -c "
                "\"from indicators.tasks import recalculate_all_indicators as r; print(r())\"")

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
