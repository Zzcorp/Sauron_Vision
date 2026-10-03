"""Write OHLCV bars for every symbol an enabled bot trades, from the broker
that bot trades through.

Why this exists: every technical rule loads 4h bars (signals/rules/
technical_rules.py) and the SMC composite rule is hard-coded to 4h, but no
code path ever wrote a 4h row. `load_ohlcv` returned None, every rule
returned None, and `AssetBot.decide()` fell through to
HOLD "no active signals" — the multi-asset bots were structurally
incapable of opening a position.

Design notes:
  * Bars come from the SAME venue the order fills on (Alpaca for stocks,
    OANDA for forex, Binance for crypto), so there is no feed/execution
    basis. This is also why it is preferred over buying a vendor feed.
  * Only symbols on enabled AssetBotConfigs are fetched — the universe
    stays small enough to run beside the 5-minute bot tick.
  * Paper-mode configs still get bars: paper bots must be able to decide,
    and the router returns a real market-data client for them anyway when
    credentials exist (falling back to PaperTrader, which is skipped).
"""
from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone as dt_tz
from decimal import Decimal, InvalidOperation

from django.core.cache import cache

logger = logging.getLogger(__name__)

# The timeframes the rule layer actually reads. The LARGER one first: the
# keyless feed builds 4h from a single hourly download and remembers that
# frame for a few minutes, so the 1h request that follows is served from
# it — one download per symbol per pass instead of two.
DEFAULT_INTERVALS = ("4h", "1h")
DEFAULT_LIMIT = 200

# A breath between symbols on the keyless feed. Yahoo tolerates a steady
# trickle and cuts off a burst; a research fleet of 150 symbols is a burst
# without this, and 30 seconds of a ten-minute pass with it.
PUBLIC_FEED_PACE_S = 0.2


def _pace() -> None:
    time.sleep(PUBLIC_FEED_PACE_S)

# A venue that gave no bars for a symbol is not asked again for a while.
# One IBKR historical request the Gateway never answers costs the whole
# request timeout, and seven forex CFDs times two intervals is most of a
# ten-minute refresh spent waiting on a venue that has already said no —
# which is how the 2026-09-10 bar writer spent its afternoon. The memo
# is written only when the venue was actually asked and stayed mute, so
# it expires on its own and the venue gets one fresh chance per window.
MUTE_VENUE_MEMO_S = 6 * 3600


def _mute_key(source: str, symbol: str, interval: str) -> str:
    return f"bars:mute:{source}:{symbol}:{interval}"


def _venue_is_mute(source: str, symbol: str, interval: str) -> bool:
    try:
        return bool(cache.get(_mute_key(source, symbol, interval)))
    except Exception:  # noqa: BLE001 — a dead cache costs one request
        return False


def _remember_mute(source: str, symbol: str, interval: str) -> None:
    try:
        cache.set(_mute_key(source, symbol, interval), 1, MUTE_VENUE_MEMO_S)
    except Exception:  # noqa: BLE001
        pass


# WHAT THE SOURCE SAID, AND WHEN (2026-10-02). A 4h bar hours old while the
# market is open reads as a dead feed — and on a thin contract it is not:
# CBOT oats can go hours overnight without a print, and Yahoo writes no
# hourly bar for an hour that traded nothing. The writer asked, the source
# answered, it simply had nothing newer. Recorded per symbol and interval
# on every answer that carried rows, so the readiness checks
# (preflight_live._bar_verdict) can tell "the feed stopped" from "the
# market printed nothing": the first is a blocker, the second a note.
ANSWER_MEMO_S = 6 * 3600


def _answer_key(symbol: str, interval: str) -> str:
    return f"bars:answered:{symbol}:{interval}"


def _note_answer(symbol: str, interval: str, rows) -> None:
    """Remember that a source answered for (symbol, interval) now, and the
    newest bar it had. An empty answer is not an answer: nothing is
    written, and an old note runs out on its own."""
    try:
        newest = max(int(r[0]) for r in (rows or []) if r and len(r) >= 6)
    except (ValueError, TypeError):
        return
    try:
        prev = cache.get(_answer_key(symbol, interval)) or {}
        if prev.get("at") and time.time() - float(prev["at"]) < 60 \
                and int(prev.get("newest_ms") or 0) > newest:
            newest = int(prev["newest_ms"])   # two sources in one pass
        cache.set(_answer_key(symbol, interval),
                  {"at": time.time(), "newest_ms": newest}, ANSWER_MEMO_S)
    except Exception:  # noqa: BLE001 — a dead cache costs the note only
        pass


def last_answer(symbol: str, interval: str) -> "dict | None":
    """{"at": epoch seconds, "newest_ms": the newest bar's open, epoch ms}
    of the last source answer for (symbol, interval), or None."""
    try:
        return cache.get(_answer_key(symbol, interval)) or None
    except Exception:  # noqa: BLE001
        return None


def _client_for(user, symbol, cfg):
    """Market-data client for a symbol, or None when only paper is available.

    PaperTrader reads bars back out of PriceData, so using it here would be
    a no-op loop that writes nothing.
    """
    from bot_program.engine.broker_router import client_for_symbol
    from bot_program.engine.paper_trader import PaperTrader

    # purpose="data": this writer only reads bars, and on IBKR it must not
    # share the trader's clientId — see bot_program/engine/ibkr_sessions.
    client = client_for_symbol(user, symbol, cfg, purpose="data")
    if isinstance(client, PaperTrader):
        # Paper configs short-circuit the router; retry with mode ignored so
        # market data still comes from the real venue when creds exist.
        if getattr(cfg, "mode", "paper") == "paper":
            client = client_for_symbol(user, symbol, None, purpose="data")
        if isinstance(client, PaperTrader):
            return _public_market_data_client(cfg)
    return client


def _public_market_data_client(cfg):
    """A keyless client for venues whose market data is public.

    Requiring broker credentials for BARS was a structural dead end on a
    fresh install: no keys meant no bars, no bars meant no indicators and no
    rule could ever fire, so the platform could not produce the evidence it
    needed to justify connecting a broker in the first place.

    Crypto uses Binance public klines; stocks, ETFs, indices, commodity
    futures and FX majors use Yahoo. Options are absent deliberately —
    there is no free chain source worth trusting.

    Deliberately the LIVE endpoint even for paper configs: testnet klines
    are synthetic, and a strategy validated against invented candles has
    been validated against nothing.
    """
    try:
        from market_data.public_feed import public_feed_for
        return public_feed_for(getattr(cfg, "asset_class", "") or "")
    except Exception as e:
        logger.warning("[bars] public market-data client unavailable: %s", e)
        return None


def _venue_symbol(client, symbol: str) -> str:
    """Platform spelling -> the spelling THIS client's venue lists.

    Binance is the only wired venue whose client maps nothing of its own:
    OANDA translates inside `klines` (`_to_oanda_symbol`), Alpaca and Yahoo
    take the platform symbol as-is. Asking Binance for BTCUSD is not an
    error — /api/v3/klines answers an empty list or a 400 — so an
    untranslated crypto config quietly received no bars at all, every rule
    on it returned None, and the bot could only ever HOLD. That is exactly
    the failure this module exists to prevent, reintroduced one symbol
    spelling at a time.
    """
    try:
        from bot_program.engine.binance_client import BinanceClient
        from bot_program.engine.binance_futures_client import (
            BinanceFuturesClient,
        )
    except Exception:      # pragma: no cover - import-time breakage only
        return symbol
    if not isinstance(client, (BinanceClient, BinanceFuturesClient)):
        return symbol
    from market_data.management.commands.backfill_bars import venue_symbol
    return venue_symbol(symbol)


def _source_tag(client) -> str:
    """The provenance a client's bars are written under.

    One feed, one spelling. The scheduled path stripped "Trader" and
    "Client" from the class name but not "Feed", so the same Yahoo feed
    wrote `yfinancefeed_public` for a config with no broker and
    `yfinance_public` from the fallback and from backfill_bars — and an
    audit of the keyless rows by either spelling missed the other half.
    """
    name = type(client).__name__
    for word in ("Trader", "Client", "Feed"):
        name = name.replace(word, "")
    tag = name.lower() or "broker"
    if getattr(client, "_sv_public_feed", False):
        tag += "_public"
    return tag


#: PriceData.volume is a BigIntegerField.
_BIGINT_MAX = 2 ** 63 - 1


def _volume(raw) -> int:
    """A bar's volume as the column stores it; 0 when the venue gave none.

    The volume is never the reason a bar is lost (2026-09-29). A venue
    candle can carry `"volume": null`; eToro's adapter turned it into the
    text "None", `int(float("None"))` raised, and the whole bar was
    counted as skipped, its price with it. A bar without a volume still
    has a price.
    """
    if raw is None:
        return 0
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(value) or value <= 0:
        return 0
    return min(int(value), _BIGINT_MAX)


def _upsert_rows(inst, interval, rows, source) -> tuple[int, int]:
    """Persist Binance-style kline rows. Returns (written, skipped).

    A row the database refuses is skipped and said, never raised: one
    unwritable bar used to abort the refresh of the whole config."""
    from django.db import DatabaseError

    from market_data.models import PriceData

    written = skipped = 0
    refused = None
    for row in rows or []:
        try:
            if not row or len(row) < 6:
                skipped += 1
                continue
            ts_ms = int(row[0])
            close = Decimal(str(row[4]))
            if ts_ms <= 0 or close <= 0:
                skipped += 1
                continue
            PriceData.objects.update_or_create(
                instrument=inst, timeframe=interval,
                timestamp=datetime.fromtimestamp(ts_ms / 1000, tz=dt_tz.utc),
                defaults={
                    "open": Decimal(str(row[1])),
                    "high": Decimal(str(row[2])),
                    "low": Decimal(str(row[3])),
                    "close": close,
                    "volume": _volume(row[5]),
                    "source": source,
                },
            )
            written += 1
        except (ValueError, TypeError, InvalidOperation, IndexError):
            skipped += 1
        except (DatabaseError, OverflowError) as e:
            skipped += 1
            refused = refused or e
    if refused is not None:
        logger.warning("[bars] %s %s: the database refused %d %s bar(s): %s",
                       getattr(inst, "symbol", inst), interval, skipped,
                       source, refused)
    return written, skipped


def _write_venue_window(inst, interval, rows, source) -> tuple[int, int, int]:
    """Write a venue's answer, THEN give its window back to it.

    Returns (written, skipped, evicted). The public feed's stand-in rows
    inside the venue's window go only once the venue's own bars are in the
    table, in the same transaction. 2026-09-29: the eviction ran first,
    none of eToro's 200 fresh BTCUSD bars reached the table, and every ten
    minutes the refresh deleted the stand-ins and wrote nothing in their
    place. The table kept the bars from before the venue's window and
    nothing after, so an armed bot read a 4h candle 33 days old. A venue
    answer that writes nothing now evicts nothing, and the caller falls
    back to the public feed as for a mute venue.
    """
    from django.db import DatabaseError, transaction

    try:
        with transaction.atomic():
            written, skipped = _upsert_rows(inst, interval, rows, source)
            evicted = (_evict_stand_in_rows(inst, interval, rows)
                       if written else 0)
    except DatabaseError as e:
        logger.warning("[bars] %s %s: writing %s's window failed, nothing "
                       "changed: %s", getattr(inst, "symbol", inst), interval,
                       source, e)
        return 0, len(rows or []), 0
    return written, skipped, evicted


def refresh_bars_for_config(cfg, *, intervals=DEFAULT_INTERVALS,
                            limit=DEFAULT_LIMIT) -> dict:
    """Fetch and persist bars for every symbol on one bot config."""
    from instruments.models import Instrument

    out = {"symbols": 0, "bars": 0, "skipped": 0, "errors": 0, "no_client": 0,
           "fallback": 0}
    for symbol in (cfg.symbols or []):
        inst = Instrument.objects.filter(symbol=symbol).first()
        if inst is None:
            logger.warning("[bars] no Instrument row for %s — skipping", symbol)
            out["errors"] += 1
            continue

        client = _client_for(cfg.user, symbol, cfg)
        if client is None:
            # Distinct from `errors`, which means "no Instrument row".
            # Operators scan errors for real breakage; a missing broker is a
            # configuration state with a different remedy, and at WARNING
            # because it means this symbol can never produce a decision.
            logger.warning(
                "[bars] no market-data client for %s (%s) — this symbol will "
                "produce no bars, no indicators and no signals until broker "
                "credentials exist for that asset class", symbol, cfg.asset_class)
            out["no_client"] += 1
            continue

        source = _source_tag(client)
        out["symbols"] += 1
        fetch_symbol = _venue_symbol(client, symbol)
        for interval in intervals:
            rows = []
            asked = False
            if _venue_is_mute(source, symbol, interval):
                logger.info("[bars] %s %s: %s gave no bars within the last "
                            "%dh — public feed directly", symbol, interval,
                            source, MUTE_VENUE_MEMO_S // 3600)
            else:
                asked = True
                try:
                    rows = client.klines(fetch_symbol, interval=interval,
                                         limit=limit)
                except Exception as e:
                    logger.warning("[bars] klines(%s, %s) failed: %s",
                                   symbol, interval, e)
                    out["errors"] += 1
                    rows = []
                _note_answer(symbol, interval, rows)
            if getattr(client, "_sv_public_feed", False):
                # The keyless feed IS the fallback: what it gave is written
                # as it is, and nothing backs it up.
                written, skipped = _upsert_rows(inst, interval, rows, source)
                out["bars"] += written
                out["skipped"] += skipped
                continue

            written = 0
            if rows:
                # THE VENUE ANSWERED: ITS WINDOW IS ITS OWN. Its bars are
                # written, then the stand-in rows inside the window it
                # returned go, so that window holds one grid, the venue's.
                # History behind the window (a backfilled year) stays, and
                # so does anything newer than it (see _evict_stand_in_rows).
                written, skipped, evicted = _write_venue_window(
                    inst, interval, rows, source)
                out["bars"] += written
                out["skipped"] += skipped
                if evicted:
                    logger.info("[bars] %s %s: %s answered — %d public-feed "
                                "stand-in bars in its window gave way to "
                                "the venue's", symbol, interval, source,
                                evicted)
                if not written:
                    logger.warning("[bars] %s %s: %s answered %d bars and "
                                   "none could be written — the public feed "
                                   "instead", symbol, interval, source,
                                   len(rows))

            if not written:
                # THE VENUE IS MUTE, NOT THE MARKET. An execution venue
                # that answers a bar request with nothing — a historical
                # farm that never replies (the IBKR forex case that aged
                # every pair's bars 36 hours), a pacing refusal, a symbol
                # it will not serve history for — or with bars that cannot
                # be written must not leave the bot blind when the same
                # candles are one keyless request away. The rows are tagged
                # as the public feed's, so a bar's provenance still says
                # where it came from.
                pub, pub_source = _fallback_rows(cfg, symbol, interval, limit)
                _note_answer(symbol, interval, pub)
                if pub:
                    out["fallback"] += 1
                    if asked:
                        _remember_mute(source, symbol, interval)
                        logger.warning("[bars] %s %s: %s gave no usable bars "
                                       "— written from the public feed "
                                       "instead, and not asked again for "
                                       "%dh", symbol, interval, source,
                                       MUTE_VENUE_MEMO_S // 3600)
                    # THE STAND-IN FILLS THE GAP, NOT THE HISTORY. Yahoo's
                    # 4h grid is anchored at exchange midnight and a
                    # venue's at its own session close (OANDA: 17:00 New
                    # York), so the two never share a timestamp, and a
                    # stand-in written across the venue's window sat
                    # BESIDE its bars: one series at twice the density,
                    # read by every ATR stop and IPDA range on the pair.
                    # Only the bars after the venue's newest are written.
                    pub = _after_the_venues_last_bar(inst, interval, pub)
                    w2, s2 = _upsert_rows(inst, interval, pub, pub_source)
                    out["bars"] += w2
                    out["skipped"] += s2
                continue

            stale_age = _venue_window_is_stale(inst, interval, rows)
            if stale_age is not None:
                # A VENUE THAT ANSWERS WITH THE PAST. A window whose newest
                # bar the market has long left behind (a history farm that
                # lags, a symbol the venue stopped quoting) is written, and
                # the public feed fills AFTER its newest bar, exactly as it
                # does for a venue that said nothing. When the feed has
                # nothing newer either, the market is shut and nothing is
                # said.
                pub, pub_source = _fallback_rows(cfg, symbol, interval, limit)
                _note_answer(symbol, interval, pub)
                pub = _after_the_venues_last_bar(inst, interval, pub)
                if pub:
                    w2, s2 = _upsert_rows(inst, interval, pub, pub_source)
                    out["bars"] += w2
                    out["skipped"] += s2
                    out["fallback"] += 1
                    if not _venue_is_mute(source + ":stale", symbol, interval):
                        _remember_mute(source + ":stale", symbol, interval)
                        logger.warning(
                            "[bars] %s %s: %s answered with a window whose "
                            "newest bar is %.1f h old — the public feed fills "
                            "after it (%d bars)", symbol, interval, source,
                            stale_age / 3600, len(pub))
        if getattr(client, "_sv_public_feed", False) is True:
            _pace()
    return out


def _fallback_rows(cfg, symbol, interval, limit) -> "tuple[list, str]":
    """Bars from the keyless feed when the venue gave none, or ([], '')."""
    feed = _public_market_data_client(cfg)
    if feed is None:
        return [], ""
    try:
        # In the FEED's spelling (2026-10-03): the fallback asked Binance
        # for AAVEUSD, which answers nothing for a symbol it does not list,
        # so every crypto pair the venue (eToro) would not serve candles
        # for — AAVE, ADA, ATOM, AVAX, DOGE, DOT, MATIC, NEAR, UNI — sat on
        # a 4h bar four days old while the primary path, one branch up,
        # translated correctly. paper_readiness: "an armed bot is deciding
        # on a stale candle".
        rows = feed.klines(_venue_symbol(feed, symbol), interval=interval,
                           limit=limit) or []
    except Exception as e:  # noqa: BLE001 — the fallback must not raise
        logger.warning("[bars] public feed klines(%s, %s) failed: %s",
                       symbol, interval, e)
        return [], ""
    return rows, _source_tag(feed)


def _after_the_venues_last_bar(inst, interval, rows) -> list:
    """The stand-in's rows newer than the venue's newest bar — all of them
    when no venue has ever written this frame."""
    from market_data.models import PriceData

    last = (PriceData.objects
            .filter(instrument=inst, timeframe=interval)
            .exclude(source__endswith="_public")
            .order_by("-timestamp")
            .values_list("timestamp", flat=True).first())
    if last is None:
        return rows
    last_ms = int(last.timestamp() * 1000)
    kept = []
    for row in rows:
        try:
            if int(row[0]) > last_ms:
                kept.append(row)
        except (TypeError, ValueError, IndexError):
            kept.append(row)        # _upsert_rows counts it as skipped
    return kept


def _evict_stand_in_rows(inst, interval, rows) -> int:
    """Delete the public feed's rows INSIDE the venue's returned window —
    from its oldest bar to one interval past its newest. Returns how many
    went.

    The window, not "from the oldest bar onward" (2026-09-29). Stand-ins
    beyond the venue's newest bar are a stretch the venue does not cover,
    and "onward" deleted them too: with a venue whose bars never reached
    the table (see _write_venue_window), every public bar from the window's
    start to the present went, every ten minutes. The interval of slack
    past the venue's newest bar keeps the tail on one grid (a Yahoo bar two
    hours after the venue's last would otherwise sit beside it). Called
    only after the venue's own bars are written."""
    from market_data.models import PriceData

    stamps = []
    for row in rows:
        try:
            stamps.append(int(row[0]))
        except (TypeError, ValueError, IndexError):
            continue
    if not stamps:
        return 0
    since = datetime.fromtimestamp(min(stamps) / 1000, tz=dt_tz.utc)
    until = datetime.fromtimestamp(
        (max(stamps) + INTERVAL_SECONDS.get(interval, 3600) * 1000) / 1000,
        tz=dt_tz.utc)
    deleted, _ = (PriceData.objects
                  .filter(instrument=inst, timeframe=interval,
                          timestamp__gte=since, timestamp__lt=until,
                          source__endswith="_public")
                  .delete())
    return deleted


#: Seconds per bar, for the eviction window and the staleness judgement.
INTERVAL_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
                    "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}

#: A venue whose newest bar is older than this answered with a STALE
#: window. Crypto trades round the clock, so three bars behind is stale;
#: every other class closes for weekends and holidays, so a Monday-morning
#: window three days old is only the market being shut.
STALE_VENUE_BARS_CRYPTO = 3
STALE_VENUE_AFTER_S = 72 * 3600


def _venue_window_is_stale(inst, interval, rows, now=None) -> "float | None":
    """Age in seconds of the venue's newest returned bar when that is
    stale for this instrument's class, else None."""
    stamps = []
    for row in rows or []:
        try:
            stamps.append(int(row[0]))
        except (TypeError, ValueError, IndexError):
            continue
    if not stamps:
        return None
    now = now or datetime.now(dt_tz.utc)
    age = now.timestamp() - max(stamps) / 1000
    if (getattr(inst, "asset_class", "") or "") == "crypto":
        limit = STALE_VENUE_BARS_CRYPTO * INTERVAL_SECONDS.get(interval, 3600)
    else:
        limit = STALE_VENUE_AFTER_S
    return age if age > limit else None


# Starred instruments beyond the fleet get bars too, capped per pass —
# keyless requests are cheap, not free. Held symbols are never capped.
WATCHLIST_BAR_CAP = 30


def refresh_watchlist_bars(*, intervals=DEFAULT_INTERVALS,
                           limit=DEFAULT_LIMIT, covered=None) -> dict:
    """Bars for HELD and STARRED instruments no enabled bot already covers.

    The star used to bring quotes and signal scans but not bars — so a
    starred instrument's chart stayed blank and its rules could never
    fire, which quietly contradicted what the star promises. The keyless
    public feeds close the gap; symbols with no free source are skipped
    by name.

    HELD symbols come first and outside the cap. The manual TAKE TRADE
    config carries `symbols=[]` by design, so a pair held only through the
    manual lane is covered by no config — and the cap used to be taken
    BEFORE covered symbols were skipped, so fleet symbols spent the thirty
    slots and a held pair starred past them got no 4h/1h bars at all. The
    held set is the one the brain's regime probe reads
    (`brain.synthesizer._held_symbols`), so every probe on the book has a
    frame to read. The cap now counts only symbols this pass will fetch.
    """
    from brain.synthesizer import _held_symbols
    from instruments.models import Instrument
    from market_data.public_feed import (SUPPORTED_ASSET_CLASSES,
                                         YF_UNAVAILABLE, public_feed_for)

    out = {"symbols": 0, "bars": 0, "skipped": 0, "errors": 0, "no_client": 0}
    covered = covered or set()
    classes = sorted(SUPPORTED_ASSET_CLASSES | {"crypto"})
    skip = set(covered) | set(YF_UNAVAILABLE)
    held = [i for i in (Instrument.objects
                        .filter(symbol__in=_held_symbols(),
                                asset_class__in=classes)
                        .order_by("symbol"))
            if i.symbol not in skip]
    skip.update(i.symbol for i in held)
    starred = [i for i in (Instrument.objects
                           .filter(is_watchlist=True, is_active=True,
                                   asset_class__in=classes)
                           .order_by("symbol"))
               if i.symbol not in skip][:WATCHLIST_BAR_CAP]
    for inst in held + starred:
        client = public_feed_for(inst.asset_class)
        if client is None:
            out["no_client"] += 1
            continue
        fetch_symbol = _venue_symbol(client, inst.symbol)
        source = _source_tag(client)
        out["symbols"] += 1
        for interval in intervals:
            try:
                rows = client.klines(fetch_symbol, interval=interval,
                                     limit=limit)
            except Exception as e:
                logger.warning("[bars] watchlist klines(%s, %s) failed: %s",
                               inst.symbol, interval, e)
                out["errors"] += 1
                continue
            _note_answer(inst.symbol, interval, rows)
            written, skipped = _upsert_rows(inst, interval, rows, source)
            out["bars"] += written
            out["skipped"] += skipped
        # The same breath as the config pass: this pass runs straight
        # after it, on the same keyless feed, for up to thirty more.
        if getattr(client, "_sv_public_feed", False) is True:
            _pace()
    return out


def refresh_bot_bars(*, intervals=DEFAULT_INTERVALS, limit=DEFAULT_LIMIT) -> dict:
    """Refresh bars for every enabled AssetBotConfig, then for held and
    starred instruments the fleet does not already cover."""
    from bot_program.models import AssetBotConfig

    totals = {"configs": 0, "symbols": 0, "bars": 0, "skipped": 0, "errors": 0,
              "no_client": 0, "fallback": 0}
    covered: set = set()
    for cfg in (AssetBotConfig.objects.filter(enabled=True)
                .select_related("user")):
        totals["configs"] += 1
        covered.update(s for s in (cfg.symbols or []) if s)
        try:
            res = refresh_bars_for_config(cfg, intervals=intervals, limit=limit)
        except Exception as e:
            logger.exception("[bars] config %s failed: %s", cfg.id, e)
            totals["errors"] += 1
            continue
        for k in ("symbols", "bars", "skipped", "errors", "no_client",
                  "fallback"):
            totals[k] += res.get(k, 0)

    try:
        wl = refresh_watchlist_bars(intervals=intervals, limit=limit,
                                    covered=covered)
        for k in ("symbols", "bars", "skipped", "errors", "no_client",
                  "fallback"):
            totals[k] += wl.get(k, 0)
    except Exception as e:
        logger.exception("[bars] watchlist pass failed: %s", e)
        totals["errors"] += 1

    logger.info("[bars] refresh complete: %s", totals)
    return totals
