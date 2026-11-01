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
--intervals or --bars still wins. The backfill places no order and needs no
key; the verdicts it feeds do size real money (backtester/proving/proof.py).

Symbols are the platform's own spelling (BTCUSD), translated to the venue's
(BTCUSDT) on the way out — the same mapping `market_data.quotes` uses, so a
backfilled bar and a live quote agree about what instrument they describe.

THE VENUE'S BARS ARE NEVER WRITTEN OVER, NOR BESIDE (2026-11-01). Every
row went to bot_bars._upsert_rows, which replaces the OHLC and the source
of a row already at that timestamp, and nothing here asked whose row it
was, unlike the bar pass and the watchlist pass. `--proving` takes every
enabled bot's symbols and every open row, so on an eToro-routed live
symbol it relabelled eToro's own candles as the public feed's where the
hours met (XAUUSD became Yahoo's GC=F future, BTCUSD Binance's BTCUSDT)
and wrote Yahoo's :30 bars beside eToro's :00 bars for US stocks and
indices, under the bars a real row's exit booking, ATR stops and fill
checks read. Now, for every interval, a series a venue wrote (any source
that is not a public feed's: bot_bars._venue_rows, the pass's own test)
gets public rows only OUTSIDE the venue's span: bars that have ended by
the time its first bar opens, and bars after its newest one by the pass's
rule once that bar is stale by the pass's own bound; while the venue is
live, its next bars are the bar pass's (bot_bars._outside_the_venues_span).
The writer itself never lets a public row replace a venue's
(bot_bars._upsert_rows), so a bar the bar pass writes while this command
runs stays the venue's. The Yahoo EOD's daily bars ("yfinance") are the
public feed's own series, not a venue's: a 1d run still fills a hole and
rewrites a partial bar inside their span. The run says per symbol how
many it kept out, and why. A series no venue ever wrote is unchanged.

The dry run downloads everything a real run would and writes nothing.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone as dt_tz

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


def _after_the_last(rows, venue) -> int:
    """How many of `rows` open after the venue's newest bar (`venue`,
    bot_bars._venue_span); 0 without a venue (2026-11-01)."""
    if not venue:
        return 0
    n = 0
    for row in rows or []:
        try:
            n += int(row[0]) > venue["last_ms"]
        except (TypeError, ValueError, IndexError):
            continue
    return n


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
                            help="Fetch and report, write nothing. It still "
                                 "downloads everything a real run would "
                                 "(the whole history asked, from Yahoo or "
                                 "page by page from Binance); only the "
                                 "writes are skipped.")

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
        grand_kept_out = 0
        for symbol in symbols:
            inst = Instrument.objects.filter(symbol=symbol).first()
            if inst is None:
                self.stderr.write(self.style.WARNING(
                    f"  {symbol}: no Instrument row — run seed_instruments first, "
                    f"or check the spelling against the seeded set"))
                continue

            for interval in intervals:
                if inst.asset_class == "crypto":
                    written, kept_out = self._backfill_one(
                        client, inst, symbol, interval, target, dry,
                        _upsert_rows)
                else:
                    written, kept_out = self._backfill_public(
                        inst, symbol, interval, target, dry, _upsert_rows)
                grand_total += written
                grand_kept_out += kept_out

        verb = "would write" if dry else "wrote"
        self.stdout.write(self.style.SUCCESS(
            f"\nBackfill complete — {verb} {grand_total} bars across "
            f"{len(symbols)} symbol(s) x {len(intervals)} interval(s)."
            + (f" {grand_kept_out} public bar(s) skipped for a venue's bars "
               f"(said above, per symbol)." if grand_kept_out else "")))
        if proving:
            self._proving_footer(intervals)
        if not dry:
            self.stdout.write(
                "Next: python manage.py shell -c "
                "\"from indicators.tasks import recalculate_all_indicators as r; print(r())\"")

    def _proving_footer(self, intervals) -> None:
        """What the proving ground needs at each interval THIS run filled,
        and what follows (2026-11-01). The footer cited the 4h minimums
        whatever was backfilled (a 1h run read 540 days and 800 bars; the
        judge wants backtester.proving.data's 365 and 2000 at 1h), and it
        ended on "Next: ... `prove rules --save` judges the live rules
        now": a step that sizes real money, offered as routine."""
        from backtester.proving.data import MIN_BARS, MIN_SPAN_DAYS
        for iv in intervals:
            if iv in MIN_SPAN_DAYS and iv in MIN_BARS:
                flag = "" if iv == "4h" else f" --timeframe {iv}"
                self.stdout.write(
                    f"The proving ground needs {MIN_SPAN_DAYS[iv]} days and "
                    f"{MIN_BARS[iv]} bars at {iv} per symbol. `python "
                    f"manage.py prove data{flag}` (read only) says who is "
                    f"still short.")
            else:
                self.stdout.write(
                    f"The proving ground judges no {iv} bars (only "
                    f"{', '.join(sorted(MIN_BARS))}).")
        self.stdout.write(
            "The nightly judge (03:40 UTC) runs on its own while the "
            "proving_ground component is on, and its saved verdicts size "
            "real money. `python manage.py prove rules --save` changes "
            "real-money sizing. A saved verdict binds real money from the "
            "next live entry: FAILED refuses the rule on that class and "
            "side, PROVEN allows full size. It is the operator's decision, "
            "never a routine next step; `prove rules` without --save "
            "previews and writes nothing.")

    def _say_the_venue(self, inst, symbol, interval, venue, *, at, held,
                       beside, after, tail, dry) -> None:
        """What a (symbol, interval) a venue wrote got of the public feed,
        and why (2026-11-01). One line when public rows were kept out of
        its span: `at` its own timestamps (`held` of them because the
        venue wrote that bar while this run went, bot_bars._upsert_rows),
        `beside` its bars, `after` its newest bar while the venue is live.
        One more when that newest bar is stale and `tail` rows after it
        went to the writer, the pass's rule."""
        from market_data.bot_bars import (STALE_VENUE_AFTER_S,
                                          STALE_VENUE_BARS_CRYPTO)
        if not venue:
            return
        sources = ", ".join(venue["sources"])
        last = datetime.fromtimestamp(venue["last_ms"] / 1000, tz=dt_tz.utc)
        if at or beside or after:
            first = datetime.fromtimestamp(venue["first_ms"] / 1000,
                                           tz=dt_tz.utc)
            bound = (f"{STALE_VENUE_BARS_CRYPTO} bars"
                     if inst.asset_class == "crypto"
                     else f"{STALE_VENUE_AFTER_S // 3600} h")
            during = (f", {held} of them written by the venue during this "
                      f"run" if held else "")
            self.stdout.write(
                f"    {symbol} {interval}: {at + beside + after} public "
                f"bar(s) skipped for the venue: {sources} wrote this series "
                f"from {first:%Y-%m-%d %H:%M} to {last:%Y-%m-%d %H:%M} UTC "
                f"({at} at its own timestamps{during}, {beside} beside its "
                f"bars, {after} after its newest bar); public bars go only "
                f"before its first bar, and after its last once that bar is "
                f"stale ({bound}, the bar pass's bound): while the venue is "
                f"live, its next bars are the bar pass's")
        if tail and venue.get("stale_s") is not None:
            self.stdout.write(
                f"    {symbol} {interval}: the venue's newest bar ({sources}, "
                f"{last:%Y-%m-%d %H:%M} UTC) is stale, "
                f"{int(venue['stale_s'] // 3600)} h old: the public feed's "
                f"bars after it {'would be' if dry else 'are'} written, the "
                f"bar pass's own rule")

    def _backfill_public(self, inst, symbol, interval, target, dry,
                         upsert) -> tuple:
        """Every non-crypto class, through the keyless feed, in ONE call.

        Yahoo answers with the whole window (ten years of daily bars, two
        of hourly) and the feed trims to `limit`, so there is nothing to
        paginate. A class with no keyless source is named and skipped,
        never invented. Returns (bars written, or in a dry run the bars it
        would write; bars kept out for a venue's, 2026-11-01).
        """
        from market_data.bot_bars import _outside_the_venues_span, _venue_span
        from market_data.public_feed import public_feed_for

        feed = public_feed_for(inst.asset_class)
        if feed is None:
            self.stderr.write(self.style.WARNING(
                f"  {symbol} {interval}: no keyless source for asset class "
                f"{inst.asset_class!r} — nothing written"))
            return 0, 0
        try:
            rows = feed.klines(symbol, interval=interval, limit=target) or []
        except Exception as e:  # noqa: BLE001 — one symbol must not end the run
            self.stderr.write(self.style.ERROR(
                f"  {symbol} {interval}: public feed failed: {e}"))
            return 0, 0
        venue = _venue_span(inst, interval)
        kept, at, beside, after = _outside_the_venues_span(
            rows, venue, INTERVAL_MINUTES[interval] * 60_000)
        written = 0
        held = []          # a venue's bars that landed after the span read
        if kept and not dry:
            written, _skipped = upsert(inst, interval, kept, "yfinance_public",
                                       held=held)
        if held and venue is None:
            venue = _venue_span(inst, interval)
        self.stdout.write(
            f"  {symbol:10} {interval:4} {len(rows):5} bars fetched "
            f"(public feed){'' if dry else f', {written} written'}")
        self._say_the_venue(inst, symbol, interval, venue, at=at + len(held),
                            held=len(held), beside=beside, after=after,
                            tail=_after_the_last(kept, venue), dry=dry)
        return ((written if not dry else len(kept)),
                at + len(held) + beside + after)

    def _backfill_one(self, client, inst, symbol, interval, target, dry,
                      upsert) -> tuple:
        """Crypto, Binance's public klines, paged forward. Returns (bars
        written, or in a dry run the bars it would write; bars kept out
        for a venue's, 2026-11-01)."""
        from market_data.bot_bars import _outside_the_venues_span, _venue_span

        vsym = venue_symbol(symbol)
        minutes = INTERVAL_MINUTES[interval]
        span = timedelta(minutes=minutes * target)
        cursor = int((timezone.now() - span).timestamp() * 1000)
        now_ms = int(timezone.now().timestamp() * 1000)
        # The venue's span, read once: this run writes public rows only,
        # and those never move it. A bar the venue writes while the pages
        # run is kept by the writer itself (bot_bars._upsert_rows never
        # lets a public row replace a venue's), and counted in `held`.
        venue = _venue_span(inst, interval)

        collected = 0
        kept_total = 0
        written_total = 0
        at_total = beside_total = after_total = tail_total = 0
        held = []
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
            kept, at, beside, after = _outside_the_venues_span(
                rows, venue, minutes * 60 * 1000)
            kept_total += len(kept)
            at_total += at
            beside_total += beside
            after_total += after
            tail_total += _after_the_last(kept, venue)
            if kept and not dry:
                written, _skipped = upsert(inst, interval, kept,
                                           "binance_public", held=held)
                written_total += written

            # Advance past the last bar's OPEN time. Binance is inclusive on
            # startTime, so reusing it would refetch the same page forever.
            last_open = int(rows[-1][0])
            if last_open <= cursor:
                break
            cursor = last_open + minutes * 60 * 1000
            time.sleep(SLEEP_BETWEEN_PAGES)

        if held and venue is None:
            venue = _venue_span(inst, interval)
        self.stdout.write(
            f"  {symbol:10} {interval:4} {collected:5} bars fetched "
            f"({pages} page(s)){'' if dry else f', {written_total} written'}")
        self._say_the_venue(inst, symbol, interval, venue,
                            at=at_total + len(held), held=len(held),
                            beside=beside_total, after=after_total,
                            tail=tail_total, dry=dry)
        return ((written_total if not dry else kept_total),
                at_total + len(held) + beside_total + after_total)
