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

@sync_to_async
def discover_symbols(override):
    if override: return [s.upper() for s in override]
    try:
        from instruments.models import Instrument
        syms = list(Instrument.objects.filter(
            asset_class__iexact="crypto", is_active=True).values_list("symbol", flat=True))
        clean = []
        for s in syms:
            s = s.upper().replace("-","").replace("/","").replace(":","")
            if s.endswith("USDT"): clean.append(s)
        return clean or ["BTCUSDT","ETHUSDT","SOLUSDT"]
    except Exception:
        return ["BTCUSDT","ETHUSDT","SOLUSDT"]

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
        streams = "/".join(f"{s.lower()}@forceOrder" for s in symbols) + "/" + \
                  "/".join(f"{s.lower()}@markPrice@1s" for s in symbols)
        url = WS + streams
        log.info("futures: connecting for %d symbols", len(symbols))
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
