"""Binance spot L2 order book streamer → OrderBookSnapshot.

Subscribes to <symbol>@depth20@100ms (top 20 levels, 100ms cadence).
Computes depth-weighted imbalance and stores rolling snapshots that
bot_program uses for liquidity scoring. Old snapshots are pruned
opportunistically (keep last 2000/sym) to bound storage.
"""
from __future__ import annotations
import asyncio, json, logging, random
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from asgiref.sync import sync_to_async

log = logging.getLogger("stream_binance_depth")
WS = "wss://stream.binance.com:9443/stream?streams="
WRITE_THROTTLE_MS = 500   # write to DB at most every 500ms/symbol

class Command(BaseCommand):
    help = "Stream Binance spot L2 depth into OrderBookSnapshot."
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
        return [s.upper().replace("-","").replace("/","") for s in syms
                if s.upper().endswith("USDT")][:20] or ["BTCUSDT","ETHUSDT"]
    except Exception:
        return ["BTCUSDT","ETHUSDT"]

def compute_metrics(bids_raw, asks_raw):
    """bids/asks: list of [price_str, qty_str]."""
    bids = [[float(p), float(q)] for p,q in bids_raw[:20]]
    asks = [[float(p), float(q)] for p,q in asks_raw[:20]]
    if not bids or not asks:
        return None
    bid_vol = sum(q for _,q in bids)
    ask_vol = sum(q for _,q in asks)
    mid = (bids[0][0] + asks[0][0]) / 2
    spread = asks[0][0] - bids[0][0]
    total = bid_vol + ask_vol
    imb = (bid_vol - ask_vol) / total if total else 0
    # Depth-weighted: levels closer to mid count more
    def dw(levels, side):
        s = 0
        for p, q in levels:
            dist = abs(p - mid) / mid if mid else 1
            w = max(0, 1 - dist * 20)  # weight fades as price departs
            s += q * w
        return s
    dw_bid = dw(bids, "bid"); dw_ask = dw(asks, "ask")
    dw_total = dw_bid + dw_ask
    depth_score = (dw_bid - dw_ask) / dw_total if dw_total else 0
    return {"mid": mid, "spread": spread, "bid_vol": bid_vol, "ask_vol": ask_vol,
            "imbalance": imb, "depth_score": depth_score, "bids": bids, "asks": asks}

@sync_to_async
def save_snapshot(symbol, m, ts):
    try:
        from market_data.models import OrderBookSnapshot
        OrderBookSnapshot.objects.create(
            symbol=symbol, timestamp=ts,
            mid_price=Decimal(str(m["mid"])),
            spread=Decimal(str(m["spread"])),
            bid_volume=Decimal(str(round(m["bid_vol"],4))),
            ask_volume=Decimal(str(round(m["ask_vol"],4))),
            imbalance=round(m["imbalance"],4),
            depth_score=round(m["depth_score"],4),
            bids=m["bids"], asks=m["asks"],
        )
        # Prune: keep last 2000 per symbol (runs once every ~100 writes)
        import random as _r
        if _r.random() < 0.01:
            keep_ids = list(OrderBookSnapshot.objects.filter(symbol=symbol)
                .order_by("-timestamp").values_list("id", flat=True)[:2000])
            OrderBookSnapshot.objects.filter(symbol=symbol).exclude(id__in=keep_ids).delete()
    except Exception as e:
        log.debug("save_snapshot failed: %s", e)

async def run(override):
    try: import websockets
    except ImportError:
        log.error("pip install websockets"); return

    backoff = 1
    last_write = {}  # symbol -> last ms
    while True:
        symbols = await discover_symbols(override)
        streams = "/".join(f"{s.lower()}@depth20@100ms" for s in symbols)
        url = WS + streams
        log.info("depth: connecting for %d symbols", len(symbols))
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=2**20) as ws:
                backoff = 1
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        stream = msg.get("stream","")
                        sym = stream.split("@")[0].upper() if stream else ""
                        d = msg.get("data") or {}
                        bids = d.get("bids") or []
                        asks = d.get("asks") or []
                        m = compute_metrics(bids, asks)
                        if not m or not sym: continue
                        now_ms = int(timezone.now().timestamp() * 1000)
                        if now_ms - last_write.get(sym, 0) < WRITE_THROTTLE_MS:
                            continue
                        last_write[sym] = now_ms
                        asyncio.create_task(save_snapshot(sym, m, timezone.now()))
                    except Exception as e:
                        log.debug("depth tick error: %s", e)
        except Exception as e:
            log.warning("depth disconnected: %s", e)
        delay = min(60, backoff + random.random()); backoff = min(60, backoff*2)
        log.info("reconnect in %.1fs", delay); await asyncio.sleep(delay)
