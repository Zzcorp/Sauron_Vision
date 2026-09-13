"""Binance USDT-M futures streamer — liquidations + mark/funding.

Endpoints:
  wss://fstream.binance.com/stream?streams=btcusdt@forceOrder/btcusdt@markPrice@1s/...

Writes:
  - market_data.LiquidationEvent for every @forceOrder tick
  - market_data.FundingRate every @markPrice tick (throttled to ~1/min)
Broadcasts:
  - "liquidation" frames to the dashboard_live Channels group
  - "funding" frames idem
"""
from __future__ import annotations
import asyncio, json, logging, random
from decimal import Decimal
from datetime import datetime, timezone as dtz

from django.core.management.base import BaseCommand
from django.utils import timezone
from asgiref.sync import sync_to_async

log = logging.getLogger("stream_binance_futures")
WS = "wss://fstream.binance.com/stream?streams="
FUNDING_THROTTLE_SEC = 30

class Command(BaseCommand):
    help = "Stream Binance futures liquidations + mark/funding."
    def add_arguments(self, parser):
        parser.add_argument("--symbols", nargs="*", default=None)
        parser.add_argument("--quiet", action="store_true")
    def handle(self, *args, **opts):
        logging.basicConfig(level=logging.WARNING if opts["quiet"] else logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
        try: asyncio.run(run(opts.get("symbols")))
        except KeyboardInterrupt: log.info("stopped")

# USDT-margined perps only — that is what fstream lists.
FUTURES_QUOTE_ASSETS = ("USDT",)
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


@sync_to_async
def discover_symbols(override):
    """Perp symbols to subscribe to, in Binance futures spelling.

    This used to KEEP only catalogue symbols already spelled *USDT and the
    catalogue spells every crypto row *USD, so the match was always empty
    and the worker fell through to three hardcoded defaults forever. Every
    FundingRate and LiquidationEvent on the platform came from BTC, ETH and
    SOL no matter what the operator held or watched.
    """
    if override: return [s.upper() for s in override]
    try:
        from instruments.models import Instrument
        from market_data.management.commands.stream_binance import binance_symbols
        syms = list(Instrument.objects.filter(
            asset_class__iexact="crypto", is_active=True
        ).order_by("symbol").values_list("symbol", flat=True))
        return binance_symbols(syms, FUTURES_QUOTE_ASSETS) or list(DEFAULT_SYMBOLS)
    except Exception as e:
        log.warning("futures symbol discovery failed, using defaults: %s", e)
        return list(DEFAULT_SYMBOLS)

@sync_to_async
def save_liquidation(symbol, side, qty, price, notional, ts):
    try:
        from market_data.models import LiquidationEvent
        LiquidationEvent.objects.create(
            symbol=symbol, side=side,
            qty=Decimal(str(qty)), price=Decimal(str(price)),
            notional_usd=Decimal(str(round(notional, 2))), timestamp=ts)
    except Exception as e:
        log.debug("save_liquidation failed: %s", e)

@sync_to_async
def save_funding(symbol, mark, index, rate, nft, ts):
    try:
        from market_data.models import FundingRate
        FundingRate.objects.create(
            symbol=symbol, mark_price=Decimal(str(mark)),
            index_price=Decimal(str(index or 0)),
            funding_rate=Decimal(str(rate or 0)),
            next_funding_time=nft, timestamp=ts)
    except Exception as e:
        log.debug("save_funding failed: %s", e)

async def broadcast(kind, data):
    try:
        from channels.layers import get_channel_layer
        layer = get_channel_layer()
        if layer:
            await layer.group_send("dashboard_live", {"type": kind, "data": data})
    except Exception as e:
        log.debug("broadcast failed: %s", e)

async def run(override):
    try: import websockets
    except ImportError:
        log.error("pip install websockets"); return

    backoff = 1
    last_funding = {}
    while True:
        symbols = await discover_symbols(override)
        # AN EMPTY LIST MUST NOT LOOK LIKE A QUIET MARKET (2026-09-13).
        # With no symbols the joins below both collapse to "" and the url
        # becomes WS + "/" — a subscription to nothing. Binance accepts it and
        # sends no message, ever. The container then sits Up for days with a
        # HEALTHY status, no disconnect, no warning and an empty FundingRate
        # table, which is exactly what was measured on the live box: `docker
        # logs` returned not one line, and funding_carry refused all 15 crypto
        # instruments for want of the snapshots this loop was supposed to
        # write. Silence is the one thing this must never do.
        if not symbols:
            log.warning(
                "futures: discover_symbols returned NOTHING — not subscribing. "
                "Nothing will be written to FundingRate or LiquidationEvent "
                "until the catalogue holds a crypto instrument that maps to a "
                "USDT perp. Check: manage.py shell -c \"from asgiref.sync "
                "import async_to_sync; from market_data.management.commands"
                ".stream_binance_futures import discover_symbols; "
                "print(async_to_sync(discover_symbols)(None))\"")
            await asyncio.sleep(60)
            continue
        streams = "/".join(f"{s.lower()}@forceOrder" for s in symbols) + "/" + \
                  "/".join(f"{s.lower()}@markPrice@1s" for s in symbols)
        url = WS + streams
        # WARNING, not INFO, and deliberately. `core.logging_config` puts the
        # root logger at WARNING when DEBUG is off, so the INFO this line used
        # to be was dropped in production — which is why `docker logs` on a
        # twelve-minute-old container returned nothing at all and there was no
        # way to tell a healthy subscription from a subscription to nothing.
        # It fires once per connection, not per tick, so it costs nothing and
        # it is the single line that makes this process observable at all.
        log.warning("futures: connecting for %d symbols: %s",
                    len(symbols), ",".join(symbols))
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=2**20) as ws:
                backoff = 1
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        stream = msg.get("stream","")
                        d = msg.get("data") or {}
                        if "@forceorder" in stream.lower():
                            o = d.get("o") or {}
                            sym = (o.get("s") or "").upper()
                            # Binance: side "SELL" = long liquidated; "BUY" = short liquidated
                            raw_side = (o.get("S") or "").upper()
                            side = "LONG" if raw_side == "SELL" else "SHORT"
                            qty = float(o.get("q") or 0)
                            price = float(o.get("p") or o.get("ap") or 0)
                            notional = qty * price
                            ts = datetime.fromtimestamp((o.get("T") or 0)/1000, tz=dtz.utc)
                            asyncio.create_task(save_liquidation(sym, side, qty, price, notional, ts))
                            await broadcast("liquidation", {
                                "symbol": sym, "side": side, "qty": qty,
                                "price": price, "notional": notional,
                                "ts": ts.isoformat()})
                        elif "@markprice" in stream.lower():
                            sym = (d.get("s") or "").upper()
                            mark = float(d.get("p") or 0)
                            index = float(d.get("i") or 0)
                            rate = float(d.get("r") or 0)
                            nft_ms = d.get("T") or 0
                            nft = datetime.fromtimestamp(nft_ms/1000, tz=dtz.utc) if nft_ms else None
                            now_ts = timezone.now()
                            if now_ts.timestamp() - last_funding.get(sym, 0) >= FUNDING_THROTTLE_SEC:
                                last_funding[sym] = now_ts.timestamp()
                                asyncio.create_task(save_funding(sym, mark, index, rate, nft, now_ts))
                                await broadcast("funding", {
                                    "symbol": sym, "mark": mark, "index": index,
                                    "rate": rate, "next_funding": nft.isoformat() if nft else None})
                    except Exception as e:
                        log.debug("tick error: %s", e)
        except Exception as e:
            log.warning("futures disconnected: %s", e)
        delay = min(60, backoff + random.random()); backoff = min(60, backoff*2)
        log.info("reconnect in %.1fs", delay); await asyncio.sleep(delay)
