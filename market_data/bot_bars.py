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
from datetime import datetime, timezone as dt_tz
from decimal import Decimal, InvalidOperation

from django.core.cache import cache

logger = logging.getLogger(__name__)

# The timeframes the rule layer actually reads.
DEFAULT_INTERVALS = ("1h", "4h")
DEFAULT_LIMIT = 200

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


def _upsert_rows(inst, interval, rows, source) -> tuple[int, int]:
    """Persist Binance-style kline rows. Returns (written, skipped)."""
    from market_data.models import PriceData

    written = skipped = 0
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
                    "volume": int(float(row[5] or 0)),
                    "source": source,
                },
            )
            written += 1
        except (ValueError, TypeError, InvalidOperation, IndexError):
            skipped += 1
    return written, skipped


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

        source = type(client).__name__.replace("Trader", "").replace(
            "Client", "").lower() or "broker"
        if getattr(client, "_sv_public_feed", False):
            source += "_public"
        out["symbols"] += 1
        fetch_symbol = _venue_symbol(client, symbol)
        for interval in intervals:
            row_source = source
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
            if not rows and not getattr(client, "_sv_public_feed", False):
                # THE VENUE IS MUTE, NOT THE MARKET. An execution venue
                # that answers a bar request with nothing — a historical
                # farm that never replies (the IBKR forex case that aged
                # every pair's bars 36 hours), a pacing refusal, a symbol
                # it will not serve history for — must not leave the bot
                # blind when the same candles are one keyless request
                # away. The rows are tagged as the public feed's, so a
                # bar's provenance still says where it came from.
                rows, row_source = _fallback_rows(cfg, symbol, interval,
                                                  limit)
                if rows:
                    out["fallback"] += 1
                    if asked:
                        _remember_mute(source, symbol, interval)
                        logger.warning("[bars] %s %s: %s returned no bars "
                                       "— written from the public feed "
                                       "instead, and not asked again for "
                                       "%dh", symbol, interval, source,
                                       MUTE_VENUE_MEMO_S // 3600)
            written, skipped = _upsert_rows(inst, interval, rows, row_source)
            out["bars"] += written
            out["skipped"] += skipped
    return out


def _fallback_rows(cfg, symbol, interval, limit) -> "tuple[list, str]":
    """Bars from the keyless feed when the venue gave none, or ([], '')."""
    feed = _public_market_data_client(cfg)
    if feed is None:
        return [], ""
    try:
        rows = feed.klines(symbol, interval=interval, limit=limit) or []
    except Exception as e:  # noqa: BLE001 — the fallback must not raise
        logger.warning("[bars] public feed klines(%s, %s) failed: %s",
                       symbol, interval, e)
        return [], ""
    tag = (type(feed).__name__.replace("Feed", "").replace("Client", "")
           .lower() or "public") + "_public"
    return rows, tag


# Starred instruments beyond the fleet get bars too, capped per pass —
# keyless requests are cheap, not free.
WATCHLIST_BAR_CAP = 30


def refresh_watchlist_bars(*, intervals=DEFAULT_INTERVALS,
                           limit=DEFAULT_LIMIT, covered=None) -> dict:
    """Bars for STARRED instruments no enabled bot already covers.

    The star used to bring quotes and signal scans but not bars — so a
    starred instrument's chart stayed blank and its rules could never
    fire, which quietly contradicted what the star promises. The keyless
    public feeds close the gap; symbols with no free source are skipped
    by name.
    """
    from instruments.models import Instrument
    from market_data.public_feed import (SUPPORTED_ASSET_CLASSES,
                                         YF_UNAVAILABLE, public_feed_for)

    out = {"symbols": 0, "bars": 0, "skipped": 0, "errors": 0, "no_client": 0}
    covered = covered or set()
    classes = sorted(SUPPORTED_ASSET_CLASSES | {"crypto"})
    qs = (Instrument.objects.filter(is_watchlist=True, is_active=True,
                                    asset_class__in=classes)
          .order_by("symbol"))
    for inst in qs[:WATCHLIST_BAR_CAP]:
        if inst.symbol in covered or inst.symbol in YF_UNAVAILABLE:
            continue
        client = public_feed_for(inst.asset_class)
        if client is None:
            out["no_client"] += 1
            continue
        fetch_symbol = _venue_symbol(client, inst.symbol)
        source = type(client).__name__.replace("Trader", "").replace(
            "Client", "").lower() or "broker"
        if getattr(client, "_sv_public_feed", False):
            source += "_public"
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
            written, skipped = _upsert_rows(inst, interval, rows, source)
            out["bars"] += written
            out["skipped"] += skipped
    return out


def refresh_bot_bars(*, intervals=DEFAULT_INTERVALS, limit=DEFAULT_LIMIT) -> dict:
    """Refresh bars for every enabled AssetBotConfig, then for starred
    instruments the fleet does not already cover."""
    from bot_program.models import AssetBotConfig

    totals = {"configs": 0, "symbols": 0, "bars": 0, "skipped": 0, "errors": 0,
              "no_client": 0}
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
        for k in ("symbols", "bars", "skipped", "errors", "no_client"):
            totals[k] += res.get(k, 0)

    try:
        wl = refresh_watchlist_bars(intervals=intervals, limit=limit,
                                    covered=covered)
        for k in ("symbols", "bars", "skipped", "errors", "no_client"):
            totals[k] += wl.get(k, 0)
    except Exception as e:
        logger.exception("[bars] watchlist pass failed: %s", e)
        totals["errors"] += 1

    logger.info("[bars] refresh complete: %s", totals)
    return totals
