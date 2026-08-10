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

logger = logging.getLogger(__name__)

# The timeframes the rule layer actually reads.
DEFAULT_INTERVALS = ("1h", "4h")
DEFAULT_LIMIT = 200


def _client_for(user, symbol, cfg):
    """Market-data client for a symbol, or None when only paper is available.

    PaperTrader reads bars back out of PriceData, so using it here would be
    a no-op loop that writes nothing.
    """
    from bot_program.engine.broker_router import client_for_symbol
    from bot_program.engine.paper_trader import PaperTrader

    client = client_for_symbol(user, symbol, cfg)
    if isinstance(client, PaperTrader):
        # Paper configs short-circuit the router; retry with mode ignored so
        # market data still comes from the real venue when creds exist.
        if getattr(cfg, "mode", "paper") == "paper":
            client = client_for_symbol(user, symbol, None)
        if isinstance(client, PaperTrader):
            return _public_market_data_client(cfg)
    return client


def _public_market_data_client(cfg):
    """A keyless client for venues whose market data is public.

    Requiring broker credentials for BARS was a structural dead end on a
    fresh install: no keys meant no bars, no bars meant no indicators and no
    rule could ever fire, so the platform could not produce the evidence it
    needed to justify connecting a broker in the first place. Binance spot
    klines need no key and no account.

    Deliberately the LIVE endpoint even for paper configs: testnet klines are
    synthetic, and a strategy validated against invented candles has been
    validated against nothing.
    """
    if getattr(cfg, "asset_class", None) != "crypto":
        return None
    try:
        from bot_program.engine.binance_client import BinanceClient
        client = BinanceClient("", "", testnet=False)
        # Tagged so a data-only bar is never mistaken for one from the venue
        # the order actually filled on.
        client._sv_public_feed = True
        return client
    except Exception as e:
        logger.warning("[bars] public market-data client unavailable: %s", e)
        return None


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

    out = {"symbols": 0, "bars": 0, "skipped": 0, "errors": 0, "no_client": 0}
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
        for interval in intervals:
            try:
                rows = client.klines(symbol, interval=interval, limit=limit)
            except Exception as e:
                logger.warning("[bars] klines(%s, %s) failed: %s",
                               symbol, interval, e)
                out["errors"] += 1
                continue
            written, skipped = _upsert_rows(inst, interval, rows, source)
            out["bars"] += written
            out["skipped"] += skipped
    return out


def refresh_bot_bars(*, intervals=DEFAULT_INTERVALS, limit=DEFAULT_LIMIT) -> dict:
    """Refresh bars for every enabled AssetBotConfig across all users."""
    from bot_program.models import AssetBotConfig

    totals = {"configs": 0, "symbols": 0, "bars": 0, "skipped": 0, "errors": 0,
              "no_client": 0}
    for cfg in (AssetBotConfig.objects.filter(enabled=True)
                .select_related("user")):
        totals["configs"] += 1
        try:
            res = refresh_bars_for_config(cfg, intervals=intervals, limit=limit)
        except Exception as e:
            logger.exception("[bars] config %s failed: %s", cfg.id, e)
            totals["errors"] += 1
            continue
        for k in ("symbols", "bars", "skipped", "errors", "no_client"):
            totals[k] += res.get(k, 0)
    logger.info("[bars] refresh complete: %s", totals)
    return totals
