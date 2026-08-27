"""Phase-19 live IBKR market-data feed.

Pulls historical klines + latest ticker from IBKR for instruments the user
has opted into via their `IBKRAccount.is_primary_for_<asset_class>` flags
plus the symbols on their enabled `AssetBotConfig` rows. Writes the bars
into `PriceData` and the latest quote into `LiveQuote` (with `source="ibkr"`).

This lets users drop external data vendors (Twelve Data / FMP) for the
asset classes they've routed through IBKR — one source for both data and
execution.

Multiple users → multiple TWS connections (each with a distinct `client_id`
on their `IBKRAccount`). The feed iterates per-user so the right credentials
+ host/port are used.

Graceful degrade:
  - No `ib_insync` installed → returns `{"skipped": "ib_insync_missing"}`
  - User has no IBKRAccount → `"no_ibkr_account"`
  - User has IBKRAccount but no flagged primary classes → `"no_primary_classes"`
  - User has flagged classes but no symbols on enabled configs → `"no_symbols"`
  - Per-symbol failures are caught + logged; the feed continues.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_tz
from decimal import Decimal

logger = logging.getLogger(__name__)


def _primary_classes(acct) -> set:
    """Asset classes this IBKRAccount is primary for. Maps to Instrument.asset_class."""
    classes = set()
    if acct.is_primary_for_stocks:
        classes.update({"stock", "etf", "index"})
    if acct.is_primary_for_forex:
        classes.add("forex")
    if acct.is_primary_for_options:
        classes.add("options")
    if acct.is_primary_for_commodity:
        classes.add("commodity")
    if acct.is_primary_for_cfd:
        classes.add("cfd")
    return classes


def refresh_ibkr_data_for_user(user_id: int, *,
                                 intervals: tuple = ("1h",),
                                 limit: int = 100,
                                 _client=None) -> dict:
    """Pull bars + ticker for one user. `_client` lets tests inject a mock."""
    from django.contrib.auth.models import User
    from instruments.models import Instrument
    from market_data.models import PriceData, LiveQuote
    from .models import IBKRAccount, AssetBotConfig

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return {"error": f"user {user_id} not found"}

    acct = getattr(user, "ibkr_account", None)
    if acct is None:
        return {"skipped": "no_ibkr_account"}

    classes = _primary_classes(acct)
    if not classes:
        return {"skipped": "no_primary_classes"}

    configs = AssetBotConfig.objects.filter(
        user=user, enabled=True, asset_class__in=classes,
    )
    symbols = sorted({s for cfg in configs for s in (cfg.symbols or [])})
    if not symbols:
        return {"skipped": "no_symbols"}

    if _client is None:
        from .engine.ibkr_client import (
            IBKRTrader, is_ibkr_available, purpose_client_id,
        )
        if not is_ibkr_available():
            return {"skipped": "ib_insync_missing"}
        # A bar refresh must never evict the trader — see
        # IBKRTrader.CLIENT_ID_PURPOSE_OFFSET.
        client = IBKRTrader(
            host=acct.host, port=acct.port,
            client_id=purpose_client_id(acct.client_id, "data"),
            account_id=acct.get_account_id() or "", paper=acct.paper,
        )
    else:
        client = _client

    bars_upserted = 0
    quotes_updated = 0
    errors = 0

    for symbol in symbols:
        try:
            inst = Instrument.objects.filter(symbol=symbol).first()
            if inst is None:
                continue

            for interval in intervals:
                try:
                    rows = client.klines(symbol, interval=interval, limit=limit) or []
                except Exception as e:
                    logger.warning("IBKR klines(%s, %s) failed: %s",
                                   symbol, interval, e)
                    errors += 1
                    continue

                for row in rows:
                    try:
                        if not row or len(row) < 6:
                            continue
                        ts_ms = int(row[0])
                        if ts_ms <= 0:
                            continue
                        timestamp = datetime.fromtimestamp(ts_ms / 1000, tz=dt_tz.utc)
                        PriceData.objects.update_or_create(
                            instrument=inst, timeframe=interval,
                            timestamp=timestamp,
                            defaults={
                                "open": Decimal(str(row[1])),
                                "high": Decimal(str(row[2])),
                                "low": Decimal(str(row[3])),
                                "close": Decimal(str(row[4])),
                                "volume": int(float(row[5] or 0)),
                                "source": "ibkr",
                            },
                        )
                        bars_upserted += 1
                    except Exception:
                        errors += 1

            # Live quote
            try:
                tk = client.ticker(symbol) or {}
                last_str = tk.get("lastPrice") or "0"
                last = Decimal(str(last_str))
                if last > 0:
                    bid_str = tk.get("bid") or "0"
                    ask_str = tk.get("ask") or "0"
                    LiveQuote.objects.update_or_create(
                        instrument=inst,
                        defaults={
                            "last": last,
                            "bid": Decimal(str(bid_str)) if bid_str and float(bid_str) > 0 else None,
                            "ask": Decimal(str(ask_str)) if ask_str and float(ask_str) > 0 else None,
                            "source": "ibkr",
                        },
                    )
                    quotes_updated += 1
            except Exception as e:
                logger.warning("IBKR ticker(%s) failed: %s", symbol, e)
                errors += 1

        except Exception as e:
            logger.warning("IBKR refresh failed for %s: %s", symbol, e)
            errors += 1

    return {
        "symbols": len(symbols),
        "bars_upserted": bars_upserted,
        "quotes_updated": quotes_updated,
        "errors": errors,
        "intervals": list(intervals),
    }


def refresh_ibkr_data_all_users(*, intervals=("1h",), limit=100) -> dict:
    """Walk every user with a connected IBKRAccount. Aggregates totals."""
    from .models import IBKRAccount

    user_ids = list(
        IBKRAccount.objects.filter(connected=True)
        .values_list("user_id", flat=True).distinct()
    )

    totals = {"users": 0, "bars_upserted": 0, "quotes_updated": 0,
               "errors": 0, "details": {}}
    for uid in user_ids:
        try:
            r = refresh_ibkr_data_for_user(uid, intervals=intervals, limit=limit)
            totals["users"] += 1
            totals["bars_upserted"] += int(r.get("bars_upserted", 0) or 0)
            totals["quotes_updated"] += int(r.get("quotes_updated", 0) or 0)
            totals["errors"] += int(r.get("errors", 0) or 0)
            totals["details"][uid] = r
        except Exception as e:
            logger.warning("IBKR feed user=%s failed: %s", uid, e)
            totals["errors"] += 1
            totals["details"][uid] = {"error": str(e)}
    return totals
