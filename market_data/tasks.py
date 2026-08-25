"""Celery tasks for market data — REAL implementations."""
import os
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)

# ── daily API budgets ───────────────────────────────────────────────────
# Free tiers are per-day, not per-minute; a per-minute limiter happily
# burns a 25/day allowance before breakfast.
AV_DAILY_LIMIT = int(os.getenv("ALPHA_VANTAGE_DAILY_LIMIT", "20"))


def _budget_key(provider: str) -> str:
    from django.utils import timezone
    return f"apibudget:{provider}:{timezone.now():%Y%m%d}"


def _daily_budget_remaining(provider: str, *, limit: int) -> int:
    from django.core.cache import cache
    used = cache.get(_budget_key(provider), 0)
    return max(0, limit - int(used))


def _record_api_call(provider: str, n: int = 1) -> None:
    from django.core.cache import cache
    key = _budget_key(provider)
    cache.set(key, int(cache.get(key, 0)) + n, 60 * 60 * 26)


def _finite(value):
    """float(value) when it is a real, finite number — else None.

    Yahoo genuinely serves NaN: an in-progress FX candle keeps a null Close
    that survives yfinance's row cleanup, and NaN is truthy, parses cleanly
    into Decimal, and then raises InvalidOperation on the first comparison.
    A NaN must die here, not three frames deeper inside a task loop.
    """
    import math
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _yf_market_quote(ysym: str) -> dict | None:
    """Last price for a Yahoo symbol, keyless. None when Yahoo has nothing.

    `.info` carries the change percent the headband shows; when it is missing
    or empty (FX pairs sometimes return a hollow dict) the 1-minute history
    still has a last print.
    """
    import yfinance as yf

    try:
        info = yf.Ticker(ysym).info or {}
        price = (_finite(info.get("regularMarketPrice"))
                 or _finite(info.get("previousClose")))
        if price:
            return {"last": price,
                    "change_pct": _finite(info.get("regularMarketChangePercent")),
                    "volume": info.get("volume")}
    except Exception as e:
        logger.debug("[yf quote] info(%s) failed: %s", ysym, e)
    try:
        df = yf.Ticker(ysym).history(period="1d", interval="1m")
        if df is not None and not df.empty:
            last = _finite(df["Close"].iloc[-1])
            if last:
                return {"last": last, "change_pct": None, "volume": None}
    except Exception as e:
        logger.warning("[yf quote] history(%s) failed: %s", ysym, e)
    return None


def _held_symbols(instruments, source: str) -> set[str]:
    """Symbols whose LiveQuote a fresher, higher-priority feed currently holds.

    Polling them is pure waste three times over: the network call is spent,
    the write is refused by source precedence, and the run is then scored
    'handled N rows and stored none' — a warning earned for having BETTER
    data than this poller provides. Skip them before the request goes out.
    """
    from market_data.models import LiveQuote
    from market_data.quotes import should_write

    held = set()
    for lq in LiveQuote.objects.filter(
            instrument__in=list(instruments)).select_related("instrument"):
        if not should_write(lq, source):
            held.add(lq.instrument.symbol)
    return held


def _rotation_offset(asset_class: str, length: int) -> int:
    """One step forward per run, counted — never derived from the clock.

    A wall-clock offset aliases against the beat cadence: a 300s beat
    advances a minute-keyed offset by exactly 5, and whenever gcd(5, length)
    is not 1 the offset is pinned to a residue class — with 15 rotating
    commodities, six of them were unreachable on every run, forever. A
    counter cannot alias.
    """
    from django.core.cache import cache
    key = f"quoterot:{asset_class}"
    try:
        counter = cache.incr(key)
    except ValueError:
        cache.set(key, 1, None)
        counter = 1
    return counter % length


def _quote_universe(asset_class: str, limit: int) -> list:
    """Instruments to poll: the scan universe first, topped up from the
    catalogue.

    quote_targets alone is watchlist + enabled-bot symbols, which on a fresh
    install is empty for commodities and indices — and the headband reads
    those quotes, so an empty universe would mean a permanently blank band.
    The top-up rotates one step per run so a truncated tail still cycles
    through the cadence rather than leaving the same symbols unpolled.
    """
    from instruments.models import Instrument
    from signals.universe import quote_targets

    targets = quote_targets(asset_class, limit=limit)
    if len(targets) < limit:
        have = {i.symbol for i in targets}
        extra = [i for i in Instrument.objects.filter(
                     is_active=True, asset_class=asset_class).order_by("symbol")
                 if i.symbol not in have]
        if extra:
            offset = _rotation_offset(asset_class, len(extra))
            extra = extra[offset:] + extra[:offset]
        targets = list(targets) + extra[:limit - len(targets)]
    return targets



@shared_task(bind=True, max_retries=3)
@guarded_task("scraper_live_quotes")
def fetch_live_quotes(self, watchlist_only=True):
    """Tier 1: Fetch live quotes using yfinance (free, no key needed)."""
    from instruments.models import Instrument
    from core.market_calendar import is_any_market_open
    from market_data.adapters.yfinance_adapter import save_quote_to_db

    if not is_any_market_open():
        return {"status": "skipped", "reason": "markets_closed"}

    from signals.universe import quote_targets

    if watchlist_only:
        # "watchlist_only" now means "the scan universe" — the watchlist plus
        # every enabled bot's symbols. A quote is what the mark and the paper
        # fill path read, so a traded symbol without one is a bot that can
        # decide but never act. ETFs ride along: SPY is asset_class="etf" in
        # the catalogue, and a StockBot trading it would otherwise have bars
        # and no mark.
        targets = quote_targets(("stock", "etf"), limit=20)
    else:
        # Split the budget per class: a single __in filter inherits the
        # model ordering (asset_class first), and the catalogue's 20 ETFs
        # would exactly fill the window with zero stocks polled.
        targets = (list(Instrument.objects.filter(
                       is_active=True, asset_class="stock")[:14])
                   + list(Instrument.objects.filter(
                       is_active=True, asset_class="etf")[:6]))

    fetched = 0
    for inst in targets:
        try:
            result = save_quote_to_db(inst.symbol)
            if result:
                fetched += 1
                # Push WebSocket update
                from dashboard.consumers import push_quote_update
                push_quote_update(inst.symbol, result.last, result.change_pct)
        except Exception as e:
            logger.warning(f"Quote fetch failed for {inst.symbol}: {e}")

    return {"status": "success", "fetched": fetched}


@shared_task
@guarded_task("scraper_forex")
def fetch_forex_quotes():
    """Tier 1: forex marks — Alpha Vantage when configured, yfinance always.

    A forex bot's paper mark comes from LiveQuote, and for months the only
    writer of forex rows was Alpha Vantage behind a key nobody had set — so
    every forex pair had bars, signals, even a bot, and no price to measure
    a stop against. Yahoo quotes every pair in the catalogue keylessly
    (EURUSD -> EURUSD=X), so the free feed now covers whatever the paid one
    does not, and "no key" stopped being "no marks".

    Alpha Vantage still goes first when a key exists: it is the better print
    (real bid/ask) and outranks yfinance in the source-precedence table.
    """
    from core.market_calendar import is_forex_open
    from market_data.public_feed import yf_symbol

    if not is_forex_open():
        return {"status": "skipped", "reason": "forex_closed"}

    from market_data.quotes import write_quote
    from market_data.adapters.alpha_vantage import API_KEY as AV_KEY
    from market_data.adapters.alpha_vantage import fetch_forex_rate

    fetched = attempted = av_used = held_n = 0
    covered: set[str] = set()

    # Alpha Vantage's free tier allows 25 requests A DAY. Budget the day's
    # calls, and never charge the budget for a request that was not made:
    # the unconfigured case used to burn ~20 phantom calls a day and then
    # report "budget spent" — an exhausted quota and a missing key are two
    # very different problems that must not wear the same words.
    # A zero limit means "no limit" to quote_targets, so a spent budget must
    # short-circuit here rather than be passed down as a cap.
    budget = _daily_budget_remaining("alpha_vantage", limit=AV_DAILY_LIMIT)
    if AV_KEY and budget > 0:
        from signals.universe import quote_targets
        targets = quote_targets("forex", limit=budget)
        held = _held_symbols(targets, "alpha_vantage")
        held_n += len(held)
        for inst in targets:
            if inst.symbol in held:
                # A streamer owns this row right now. Spending one of the 20
                # daily calls on a print that precedence will refuse is the
                # budget subsidising a worse feed.
                continue
            # One bad pair must cost that pair, not the run: everything
            # after an unguarded raise would silently lose its mark update,
            # and the yfinance phase below would never execute at all.
            try:
                rate = fetch_forex_rate(inst.symbol[:3], inst.symbol[3:])
                if rate and write_quote(inst.symbol, last=rate["rate"],
                                        source="alpha_vantage",
                                        bid=rate.get("bid"),
                                        ask=rate.get("ask"),
                                        instrument=inst):
                    fetched += 1
                    covered.add(inst.symbol)
            except Exception as e:
                logger.warning("[forex quotes] %s via alpha_vantage "
                               "failed: %s", inst.symbol, e)
            finally:
                # Charge for a request that actually went out (or plausibly
                # did before failing). A None can still mean a spent call —
                # throttled, bad symbol — but never one that was not made.
                _record_api_call("alpha_vantage")
                attempted += 1
                av_used += 1

    # Keyless coverage for every pair the budget did not reach. Priority 20
    # vs Alpha Vantage's 30, so a fresher paid print is never clobbered.
    yf_targets = [i for i in _quote_universe("forex", limit=50)
                  if i.symbol not in covered]
    held = _held_symbols(yf_targets, "yfinance")
    held_n += len(held)
    for inst in yf_targets:
        if inst.symbol in held:
            continue
        try:
            attempted += 1
            quote = _yf_market_quote(yf_symbol(inst.symbol, "forex"))
            if quote and write_quote(inst.symbol, last=quote["last"],
                                     source="yfinance",
                                     change_pct=quote.get("change_pct"),
                                     instrument=inst):
                fetched += 1
        except Exception as e:
            logger.warning("[forex quotes] %s via yfinance failed: %s",
                           inst.symbol, e)

    if attempted == 0 and fetched == 0 and held_n:
        # Every symbol is held by a fresher, higher-priority feed — the
        # streamers are doing this task's job better than it can. That is
        # an intentional skip, not 'ran and produced nothing'.
        return {"status": "skipped",
                "reason": f"{held_n} symbol(s) held by fresher "
                          f"higher-priority sources"}

    result = {"status": "success", "fetched": fetched, "attempted": attempted,
              "av_used": av_used, "held": held_n}
    if not AV_KEY:
        result["note"] = ("ALPHA_VANTAGE_API_KEY is not set — forex marks "
                          "come from keyless yfinance. OANDA practice "
                          "streaming is free and broker-grade.")
    return result


@shared_task
@guarded_task("scraper_commodities")
def fetch_commodity_quotes():
    """Tier 1: Fetch commodity prices via yfinance.

    The universe is the catalogue, not a hardcoded list. The old six-symbol
    dict meant 26 of the 32 seeded commodities could never have a mark, and
    a commodity bot on corn or coffee would have had bars and no price. The
    shared symbol map carries the spelling translation (CORNUSD -> ZC=F),
    and the symbols with no free source are skipped by name rather than
    warned about forever.

    Through write_quote, not straight into LiveQuote: yfinance is the
    lowest-priority source on the platform, and a five-minute poll must not
    overwrite a live broker tick with a fifteen-minute-delayed print.
    """
    from market_data.public_feed import YF_UNAVAILABLE, yf_symbol
    from market_data.quotes import write_quote

    targets = [i for i in _quote_universe("commodity", limit=20)
               if i.symbol not in YF_UNAVAILABLE]
    held = _held_symbols(targets, "yfinance")
    fetched = attempted = 0
    for inst in targets:
        if inst.symbol in held:
            continue
        try:
            quote = _yf_market_quote(yf_symbol(inst.symbol, "commodity"))
            if not quote:
                continue
            attempted += 1
            if write_quote(inst.symbol, last=quote["last"], source="yfinance",
                           change_pct=quote.get("change_pct"),
                           volume=quote.get("volume"), instrument=inst):
                fetched += 1
        except Exception as e:
            logger.warning(f"Commodity fetch failed for {inst.symbol}: {e}")

    if attempted == 0 and fetched == 0 and held:
        return {"status": "skipped",
                "reason": f"{len(held)} symbol(s) held by fresher "
                          f"higher-priority sources"}
    return {"status": "success", "fetched": fetched, "attempted": attempted,
            "held": len(held)}


@shared_task
@guarded_task("scraper_indices")
def fetch_index_quotes():
    """Tier 1: index levels via yfinance.

    The last piece of the headband: SPX500, DAX40 and friends had Instrument
    rows, a symbol map entry and no task that ever wrote their LiveQuote, so
    the dashboard's index strip rendered em-dashes forever. Indices have no
    bot class, so nothing here feeds execution — this is measurement.
    """
    from core.market_calendar import is_any_market_open
    from market_data.public_feed import yf_symbol
    from market_data.quotes import write_quote

    if not is_any_market_open():
        return {"status": "skipped", "reason": "markets_closed"}

    targets = _quote_universe("index", limit=13)
    held = _held_symbols(targets, "yfinance")
    fetched = attempted = 0
    for inst in targets:
        if inst.symbol in held:
            continue
        try:
            quote = _yf_market_quote(yf_symbol(inst.symbol, "index"))
            if not quote:
                continue
            attempted += 1
            if write_quote(inst.symbol, last=quote["last"], source="yfinance",
                           change_pct=quote.get("change_pct"),
                           volume=quote.get("volume"), instrument=inst):
                fetched += 1
        except Exception as e:
            logger.warning(f"Index fetch failed for {inst.symbol}: {e}")

    if attempted == 0 and fetched == 0 and held:
        return {"status": "skipped",
                "reason": f"{len(held)} symbol(s) held by fresher "
                          f"higher-priority sources"}
    return {"status": "success", "fetched": fetched, "attempted": attempted,
            "held": len(held)}


@shared_task
@guarded_task("scraper_fred")
def fetch_fred_updates():
    """Tier 4: Fetch latest FRED macro data.

    Reports parsed (observations SEEN) alongside observations_saved (rows
    upserted, the fetch_cot_reports convention), and the not-configured
    marker when there is no key. Without those, a missing FRED_API_KEY and a
    healthy run over series that had nothing new both returned
    observations_saved=0 — one is a broken integration, the other is a
    Tuesday, and task_gate could not tell them apart or say which it was
    looking at.
    """
    from core.constants import FRED_SERIES
    from market_data.adapters.fred_adapter import save_series_to_db

    parsed = saved = 0
    skipped = None
    for series_id in FRED_SERIES:
        try:
            out = save_series_to_db(series_id)
        except Exception as e:
            logger.warning(f"FRED fetch failed for {series_id}: {e}")
            continue
        parsed += int(out.get("parsed") or 0)
        saved += int(out.get("observations_saved") or 0)
        if out.get("skipped"):
            skipped = out["skipped"]

    result = {"status": "success", "parsed": parsed, "observations_saved": saved}
    if skipped:
        result["skipped"] = skipped
    return result


@shared_task
@guarded_task("scraper_eod")
def fetch_eod_all_instruments():
    """Tier 5: End-of-day daily bars for the whole yfinance universe.

    This was stock-only for its whole life, which is half of why every
    chart on a fresh deployment rendered blank: charts draw DAILY candles,
    and nothing ever wrote a daily bar for forex, commodities or indices.
    The shared symbol map carries the spelling translation now, so daily
    history accumulates for every class Yahoo serves.
    """
    from instruments.models import Instrument
    from market_data.adapters.yfinance_adapter import save_history_to_db
    from market_data.public_feed import (SUPPORTED_ASSET_CLASSES,
                                         YF_UNAVAILABLE, yf_symbol)

    instruments = Instrument.objects.filter(
        is_active=True, asset_class__in=sorted(SUPPORTED_ASSET_CLASSES))
    total = 0

    for inst in instruments:
        if inst.symbol in YF_UNAVAILABLE:
            continue
        try:
            count = save_history_to_db(
                inst.symbol, period="5d",
                fetch_symbol=yf_symbol(inst.symbol, inst.asset_class))
            total += count
        except Exception as e:
            logger.warning(f"EOD fetch failed for {inst.symbol}: {e}")

    return {"status": "success", "bars_saved": total}


@shared_task
@guarded_task("scraper_crypto")
def fetch_crypto_quotes():
    """Mark crypto from the venue the orders fill on.

    This used to read CoinGecko's cross-exchange aggregate, which had two
    problems. The smaller one is that a blended price never printed on the
    book you actually trade against, so a stop could be evaluated against a
    level that did not exist at your venue. The larger one, measured: the
    call returned ZERO symbols — CoinGecko's free tier now rate-limits it —
    so `LiveQuote` was never written for any crypto pair at all, and a paper
    crypto bot had no mark price, which means its positions could never
    reach a stop or a target.

    Binance's public ticker is free, keyless, and is the venue. CoinGecko
    stays as a fallback for pairs Binance does not list.
    """
    from instruments.models import Instrument
    from market_data.public_feed import public_feed_for
    from market_data.quotes import write_quote

    feed = public_feed_for("crypto")
    fetched, failed = 0, []
    if feed is not None:
        from market_data.management.commands.backfill_bars import venue_symbol
        for inst in Instrument.objects.filter(asset_class="crypto",
                                              is_active=True):
            try:
                tk = feed.ticker(venue_symbol(inst.symbol)) or {}
                last = float(tk.get("lastPrice", 0) or 0)
            except Exception:
                last = 0
            if last <= 0:
                failed.append(inst.symbol)
                continue
            change = 0.0
            try:
                change = float(tk.get("priceChangePercent", 0) or 0)
            except (TypeError, ValueError):
                pass
            if write_quote(inst.symbol, last=last, source="binance_public",
                            change_pct=change, instrument=inst):
                fetched += 1

    # Anything Binance does not list falls back to the aggregate.
    if failed:
        try:
            from market_data.adapters.crypto_adapter import save_crypto_quotes_to_db
            fetched += save_crypto_quotes_to_db(symbols=failed) or 0
        except Exception as e:
            logger.warning("[crypto quotes] CoinGecko fallback failed: %s", e)

    return {"status": "success", "fetched": fetched,
            "not_on_binance": len(failed)}


@shared_task
@guarded_task("scraper_crypto_news")
def fetch_crypto_news_task():
    """Fetch crypto news from RSS feeds."""
    from market_data.adapters.crypto_news import fetch_crypto_news
    result = fetch_crypto_news()
    if not isinstance(result, dict):
        # The scraper used to hand back a bare count of rows created. Accept
        # it rather than raising: a stub or an older adapter must not turn a
        # reporting task into a crash.
        result = {"parsed": int(result or 0), "stored": int(result or 0)}
    count = int(result.get("stored") or 0)
    if count > 0:
        # Same announcement fetch_breaking_news makes — the browsers'
        # ticker listens for it and pulls the fresh headlines in live.
        try:
            from dashboard.consumers import push_news_notification
            push_news_notification({"count": count,
                                    "message": f"{count} new crypto articles"})
        except Exception as e:  # noqa: BLE001 — a WS hiccup must not fail the scrape
            logger.warning("[crypto news] WS push failed: %s", e)
    # One done key, not two: judge_result sums every DONE_KEYS name it finds,
    # so reporting the same rows as both "stored" and "articles" would double
    # the count on the health page. parsed/feeds_dead ride alongside because
    # three of the five feeds are URLs fetch_rss_news already polls — no new
    # rows is the normal outcome, and "the feeds answered" is what actually
    # separates a quiet beat from a dead one.
    return {"status": "success", "articles": count,
            "parsed": int(result.get("parsed") or 0),
            "feeds_ok": int(result.get("feeds_ok") or 0),
            "feeds_dead": result.get("feeds_dead", [])}


@shared_task
def refresh_bot_bars_task():
    """Write 1h/4h OHLCV bars for every symbol an enabled bot trades.

    The rule layer reads 4h bars; without this task nothing produces them,
    every rule returns None, and the bots can only ever HOLD. Bars come
    from each bot's own broker so there is no feed/execution basis.
    """
    from market_data.bot_bars import refresh_bot_bars
    return refresh_bot_bars()
