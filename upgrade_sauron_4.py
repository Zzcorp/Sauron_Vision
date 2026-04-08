#!/usr/bin/env python3
"""
upgrade_sauron_4.py
===================
Pass 4 — real-time data for ALL asset classes + liquidation heatmap
+ depth-weighted liquidity scoring for the bot.

Drop next to manage.py and run:

    python upgrade_sauron_4.py

Idempotent. Adds DB migrations (auto-applied).

Covers the three directions from pass 3's closing notes:

 A. BINANCE FUTURES + LIQUIDATION HEATMAP
    • New streamer: stream_binance_futures
      subscribes to fstream.binance.com for @forceOrder (liquidations),
      @markPrice (mark + funding), @aggTrade.
    • New models: LiquidationEvent, FundingRate.
    • New page: /liquidations/ — canvas-based heatmap with live updates,
      symbol & window selector, long/short totals, biggest liq, net flow.

 B. STOCKS (FINNHUB) + FOREX (OANDA) REAL-TIME
    • stream_finnhub   — wss://ws.finnhub.io for US stock trades.
    • stream_oanda     — OANDA v20 pricing HTTP stream for FX.
    • Both feed LiveQuote and broadcast via the same Channels pipeline
      you built in pass 3, so the dashboard headband / watchlist /
      ticker update in-place for non-crypto too.

 C. ORDER BOOK DEPTH → LIQUIDITY SCORER
    • New streamer: stream_binance_depth subscribes to @depth20@100ms
      and writes L2 snapshots.
    • New model: OrderBookSnapshot.
    • bot_program/engine/strategy.py._score_liquidity() is upgraded to
      read the latest snapshot from DB (depth-weighted imbalance),
      with automatic fallback to the REST order book.

Also updates requirements (aiohttp) and render.worker.md with the new
worker blocks.
"""
from __future__ import annotations
import os, sys, subprocess
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent
if not (ROOT / "manage.py").exists():
    print("ERROR: run this from the directory containing manage.py"); sys.exit(1)

def write(rel, content, overwrite=True):
    p = ROOT / rel; p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and not overwrite:
        print(f"  skip: {rel}"); return
    p.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
    print(f"  wrote: {rel}")

def patch(rel, old, new):
    p = ROOT / rel
    if not p.exists(): print(f"  MISSING: {rel}"); return
    txt = p.read_text(encoding="utf-8")
    if new.strip()[:60] in txt: print(f"  already patched: {rel}"); return
    if old not in txt: print(f"  anchor not found: {rel}"); return
    p.write_text(txt.replace(old, new, 1), encoding="utf-8")
    print(f"  patched: {rel}")

print("━" * 60)
print(" SAURON VISION — UPGRADE PASS 4")
print(" (futures · liquidations · stocks · forex · L2 depth)")
print("━" * 60)

# =================================================================
# STEP 1 — New models in market_data
# =================================================================
print("\n[1/11] Adding LiquidationEvent, FundingRate, OrderBookSnapshot …")

write("market_data/models_live.py", '''
    """Live streaming data models — liquidations, funding, L2 snapshots."""
    from django.db import models

    class LiquidationEvent(models.Model):
        """Forced liquidations from Binance futures @forceOrder stream."""
        SIDE = [("LONG","Long liquidated"),("SHORT","Short liquidated")]
        symbol       = models.CharField(max_length=20, db_index=True)
        side         = models.CharField(max_length=6, choices=SIDE)
        qty          = models.DecimalField(max_digits=24, decimal_places=8)
        price        = models.DecimalField(max_digits=24, decimal_places=8)
        notional_usd = models.DecimalField(max_digits=24, decimal_places=2, default=0)
        timestamp    = models.DateTimeField(db_index=True)
        source       = models.CharField(max_length=24, default="binance_futures")
        class Meta:
            indexes  = [models.Index(fields=["symbol","-timestamp"])]
            ordering = ["-timestamp"]

    class FundingRate(models.Model):
        """Funding snapshots from Binance futures @markPrice stream."""
        symbol            = models.CharField(max_length=20, db_index=True)
        mark_price        = models.DecimalField(max_digits=24, decimal_places=8)
        index_price       = models.DecimalField(max_digits=24, decimal_places=8, default=0)
        funding_rate      = models.DecimalField(max_digits=12, decimal_places=8, default=0)
        next_funding_time = models.DateTimeField(null=True, blank=True)
        timestamp         = models.DateTimeField(db_index=True)
        class Meta:
            indexes  = [models.Index(fields=["symbol","-timestamp"])]
            ordering = ["-timestamp"]

    class OrderBookSnapshot(models.Model):
        """L2 order book snapshots from Binance @depth20@100ms."""
        symbol      = models.CharField(max_length=20, db_index=True)
        timestamp   = models.DateTimeField(db_index=True)
        mid_price   = models.DecimalField(max_digits=24, decimal_places=8)
        spread      = models.DecimalField(max_digits=24, decimal_places=8, default=0)
        bid_volume  = models.DecimalField(max_digits=24, decimal_places=4, default=0)
        ask_volume  = models.DecimalField(max_digits=24, decimal_places=4, default=0)
        imbalance   = models.FloatField(default=0)   # (bid-ask)/(bid+ask)
        depth_score = models.FloatField(default=0)   # depth-weighted imbalance
        bids        = models.JSONField(default=list) # [[price,qty],...] top 20
        asks        = models.JSONField(default=list)
        class Meta:
            indexes  = [models.Index(fields=["symbol","-timestamp"])]
            ordering = ["-timestamp"]
''')

# Make them importable from market_data.models
patch("market_data/models.py",
      'from core.constants import Timeframe',
      'from core.constants import Timeframe\nfrom .models_live import LiquidationEvent, FundingRate, OrderBookSnapshot  # noqa: F401')

# Migration file
write("market_data/migrations/0002_live_extras.py", '''
    from django.db import migrations, models

    class Migration(migrations.Migration):
        dependencies = [("market_data", "0001_initial")]
        operations = [
            migrations.CreateModel(
                name="LiquidationEvent",
                fields=[
                    ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                    ("symbol", models.CharField(db_index=True, max_length=20)),
                    ("side", models.CharField(choices=[("LONG","Long liquidated"),("SHORT","Short liquidated")], max_length=6)),
                    ("qty", models.DecimalField(decimal_places=8, max_digits=24)),
                    ("price", models.DecimalField(decimal_places=8, max_digits=24)),
                    ("notional_usd", models.DecimalField(decimal_places=2, default=0, max_digits=24)),
                    ("timestamp", models.DateTimeField(db_index=True)),
                    ("source", models.CharField(default="binance_futures", max_length=24)),
                ],
                options={"ordering": ["-timestamp"]},
            ),
            migrations.AddIndex(
                model_name="liquidationevent",
                index=models.Index(fields=["symbol","-timestamp"], name="md_liq_sym_ts_idx"),
            ),
            migrations.CreateModel(
                name="FundingRate",
                fields=[
                    ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                    ("symbol", models.CharField(db_index=True, max_length=20)),
                    ("mark_price", models.DecimalField(decimal_places=8, max_digits=24)),
                    ("index_price", models.DecimalField(decimal_places=8, default=0, max_digits=24)),
                    ("funding_rate", models.DecimalField(decimal_places=8, default=0, max_digits=12)),
                    ("next_funding_time", models.DateTimeField(blank=True, null=True)),
                    ("timestamp", models.DateTimeField(db_index=True)),
                ],
                options={"ordering": ["-timestamp"]},
            ),
            migrations.AddIndex(
                model_name="fundingrate",
                index=models.Index(fields=["symbol","-timestamp"], name="md_fund_sym_ts_idx"),
            ),
            migrations.CreateModel(
                name="OrderBookSnapshot",
                fields=[
                    ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                    ("symbol", models.CharField(db_index=True, max_length=20)),
                    ("timestamp", models.DateTimeField(db_index=True)),
                    ("mid_price", models.DecimalField(decimal_places=8, max_digits=24)),
                    ("spread", models.DecimalField(decimal_places=8, default=0, max_digits=24)),
                    ("bid_volume", models.DecimalField(decimal_places=4, default=0, max_digits=24)),
                    ("ask_volume", models.DecimalField(decimal_places=4, default=0, max_digits=24)),
                    ("imbalance", models.FloatField(default=0)),
                    ("depth_score", models.FloatField(default=0)),
                    ("bids", models.JSONField(default=list)),
                    ("asks", models.JSONField(default=list)),
                ],
                options={"ordering": ["-timestamp"]},
            ),
            migrations.AddIndex(
                model_name="orderbooksnapshot",
                index=models.Index(fields=["symbol","-timestamp"], name="md_ob_sym_ts_idx"),
            ),
        ]
''')

# =================================================================
# STEP 2 — Binance Futures streamer (liquidations + funding)
# =================================================================
print("\n[2/11] stream_binance_futures …")

write("market_data/management/commands/stream_binance_futures.py", '''
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
            streams = "/".join(f"{s.lower()}@forceOrder" for s in symbols) + "/" + \\
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
''')

# =================================================================
# STEP 3 — Binance depth streamer (L2 order book snapshots)
# =================================================================
print("\n[3/11] stream_binance_depth …")

write("market_data/management/commands/stream_binance_depth.py", '''
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
''')

# =================================================================
# STEP 4 — Finnhub US stocks streamer
# =================================================================
print("\n[4/11] stream_finnhub …")

write("market_data/management/commands/stream_finnhub.py", '''
    """Finnhub US stocks real-time trades → LiveQuote + broadcast.

    Requires FINNHUB_API_KEY env var. Free tier supports up to ~50
    symbol subscriptions with ~1s latency.

    Run:  python manage.py stream_finnhub
    """
    from __future__ import annotations
    import asyncio, json, logging, os, random
    from decimal import Decimal
    from django.core.management.base import BaseCommand
    from django.utils import timezone
    from asgiref.sync import sync_to_async

    log = logging.getLogger("stream_finnhub")

    class Command(BaseCommand):
        help = "Finnhub WebSocket streamer for US stocks."
        def add_arguments(self, parser):
            parser.add_argument("--symbols", nargs="*", default=None)
            parser.add_argument("--quiet", action="store_true")
        def handle(self, *args, **opts):
            logging.basicConfig(level=logging.WARNING if opts["quiet"] else logging.INFO,
                                format="%(asctime)s %(levelname)s %(message)s")
            key = os.environ.get("FINNHUB_API_KEY")
            if not key:
                log.error("FINNHUB_API_KEY is not set — aborting."); return
            try: asyncio.run(run(key, opts.get("symbols")))
            except KeyboardInterrupt: log.info("stopped")

    @sync_to_async
    def discover_symbols(override):
        if override: return [s.upper() for s in override]
        try:
            from instruments.models import Instrument
            syms = list(Instrument.objects.filter(
                asset_class__iexact="stock", is_active=True
            ).values_list("symbol", flat=True))[:50]
            return [s.upper() for s in syms] or ["AAPL","MSFT","NVDA","TSLA","SPY"]
        except Exception:
            return ["AAPL","MSFT","NVDA","TSLA","SPY"]

    @sync_to_async
    def update_live_quote(symbol, last, volume):
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        try:
            inst = Instrument.objects.filter(symbol__iexact=symbol).first()
            if not inst: return
            prev = LiveQuote.objects.filter(instrument=inst).first()
            prev_last = float(prev.last) if prev and prev.last else last
            change_pct = ((last - prev_last) / prev_last * 100) if prev_last else 0
            LiveQuote.objects.update_or_create(
                instrument=inst,
                defaults=dict(last=Decimal(str(last)),
                              change_pct=Decimal(str(round(change_pct, 4))),
                              volume=int(volume or 0), source="finnhub"),
            )
        except Exception as e:
            log.debug("update_live_quote: %s", e)

    async def broadcast(symbol, last, change_pct, volume):
        try:
            from channels.layers import get_channel_layer
            layer = get_channel_layer()
            if layer:
                await layer.group_send("dashboard_live", {
                    "type": "quote_stream",
                    "data": {"symbol": symbol, "last": last,
                             "change_pct": change_pct, "volume": volume}})
        except Exception as e:
            log.debug("broadcast: %s", e)

    async def run(api_key, override):
        try: import websockets
        except ImportError:
            log.error("pip install websockets"); return

        backoff = 1
        while True:
            symbols = await discover_symbols(override)
            url = f"wss://ws.finnhub.io?token={api_key}"
            log.info("finnhub: connecting for %d symbols", len(symbols))
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    backoff = 1
                    for s in symbols:
                        await ws.send(json.dumps({"type":"subscribe","symbol": s}))
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            if msg.get("type") != "trade": continue
                            for t in msg.get("data") or []:
                                sym = (t.get("s") or "").upper()
                                last = float(t.get("p") or 0)
                                vol = float(t.get("v") or 0)
                                if not sym or not last: continue
                                # We don't have change_pct from finnhub trades; compute on save
                                asyncio.create_task(update_live_quote(sym, last, vol))
                                await broadcast(sym, last, 0, vol)
                        except Exception as e:
                            log.debug("tick: %s", e)
            except Exception as e:
                log.warning("finnhub disconnected: %s", e)
            delay = min(60, backoff + random.random()); backoff = min(60, backoff*2)
            log.info("reconnect in %.1fs", delay); await asyncio.sleep(delay)
''')

# =================================================================
# STEP 5 — OANDA forex HTTP pricing stream
# =================================================================
print("\n[5/11] stream_oanda …")

write("market_data/management/commands/stream_oanda.py", '''
    """OANDA v20 pricing streamer — real-time forex bid/ask.

    Requires: OANDA_API_KEY, OANDA_ACCOUNT_ID
    Optional: OANDA_ENV=practice|live (default practice)

    This is an HTTP chunked stream (not WebSocket) — we use aiohttp.
    """
    from __future__ import annotations
    import asyncio, json, logging, os, random
    from decimal import Decimal
    from django.core.management.base import BaseCommand
    from django.utils import timezone
    from asgiref.sync import sync_to_async

    log = logging.getLogger("stream_oanda")

    class Command(BaseCommand):
        help = "OANDA v20 pricing HTTP streamer for forex."
        def add_arguments(self, parser):
            parser.add_argument("--instruments", nargs="*", default=None)
            parser.add_argument("--quiet", action="store_true")
        def handle(self, *args, **opts):
            logging.basicConfig(level=logging.WARNING if opts["quiet"] else logging.INFO,
                                format="%(asctime)s %(levelname)s %(message)s")
            key = os.environ.get("OANDA_API_KEY")
            acct = os.environ.get("OANDA_ACCOUNT_ID")
            env = os.environ.get("OANDA_ENV", "practice").lower()
            if not key or not acct:
                log.error("Need OANDA_API_KEY and OANDA_ACCOUNT_ID — aborting."); return
            try: asyncio.run(run(key, acct, env, opts.get("instruments")))
            except KeyboardInterrupt: log.info("stopped")

    @sync_to_async
    def discover_instruments(override):
        if override: return [s.upper() for s in override]
        try:
            from instruments.models import Instrument
            syms = list(Instrument.objects.filter(
                asset_class__iexact="forex", is_active=True
            ).values_list("symbol", flat=True))
            out = []
            for s in syms:
                s = s.upper().replace("/", "_").replace("-", "_")
                if len(s) == 6 and "_" not in s: s = f"{s[:3]}_{s[3:]}"
                if "_" in s: out.append(s)
            return out or ["EUR_USD","GBP_USD","USD_JPY","AUD_USD"]
        except Exception:
            return ["EUR_USD","GBP_USD","USD_JPY","AUD_USD"]

    @sync_to_async
    def update_live_quote(symbol_display, bid, ask):
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        try:
            inst = (Instrument.objects.filter(symbol__iexact=symbol_display).first()
                    or Instrument.objects.filter(symbol__iexact=symbol_display.replace("_","")).first()
                    or Instrument.objects.filter(symbol__iexact=symbol_display.replace("_","/")).first())
            if not inst: return
            mid = (bid + ask) / 2
            prev = LiveQuote.objects.filter(instrument=inst).first()
            prev_last = float(prev.last) if prev and prev.last else mid
            change_pct = ((mid - prev_last) / prev_last * 100) if prev_last else 0
            LiveQuote.objects.update_or_create(
                instrument=inst,
                defaults=dict(last=Decimal(str(mid)),
                              bid=Decimal(str(bid)), ask=Decimal(str(ask)),
                              change_pct=Decimal(str(round(change_pct,4))),
                              source="oanda"),
            )
        except Exception as e:
            log.debug("update_live_quote: %s", e)

    async def broadcast(symbol, last, change_pct, bid, ask):
        try:
            from channels.layers import get_channel_layer
            layer = get_channel_layer()
            if layer:
                await layer.group_send("dashboard_live", {
                    "type": "quote_stream",
                    "data": {"symbol": symbol, "last": last,
                             "change_pct": change_pct, "bid": bid, "ask": ask}})
        except Exception as e:
            log.debug("broadcast: %s", e)

    async def run(api_key, account_id, env, override):
        try: import aiohttp
        except ImportError:
            log.error("pip install aiohttp"); return

        base = "https://stream-fxtrade.oanda.com" if env == "live" else "https://stream-fxpractice.oanda.com"
        headers = {"Authorization": f"Bearer {api_key}", "Accept-Datetime-Format": "RFC3339"}
        backoff = 1

        while True:
            instruments = await discover_instruments(override)
            url = f"{base}/v3/accounts/{account_id}/pricing/stream"
            params = {"instruments": ",".join(instruments)}
            log.info("oanda: connecting for %d instruments", len(instruments))
            try:
                timeout = aiohttp.ClientTimeout(total=None, sock_read=60)
                async with aiohttp.ClientSession(headers=headers, timeout=timeout) as s:
                    async with s.get(url, params=params) as r:
                        r.raise_for_status()
                        backoff = 1
                        async for line in r.content:
                            line = line.strip()
                            if not line: continue
                            try:
                                msg = json.loads(line)
                                if msg.get("type") != "PRICE": continue
                                sym = msg.get("instrument","")
                                bids = msg.get("bids") or []
                                asks = msg.get("asks") or []
                                if not bids or not asks: continue
                                bid = float(bids[0]["price"])
                                ask = float(asks[0]["price"])
                                mid = (bid + ask) / 2
                                asyncio.create_task(update_live_quote(sym, bid, ask))
                                await broadcast(sym, mid, 0, bid, ask)
                            except Exception as e:
                                log.debug("tick: %s", e)
            except Exception as e:
                log.warning("oanda disconnected: %s", e)
            delay = min(60, backoff + random.random()); backoff = min(60, backoff*2)
            log.info("reconnect in %.1fs", delay); await asyncio.sleep(delay)
''')

# =================================================================
# STEP 6 — Liquidation heatmap page
# =================================================================
print("\n[6/11] Liquidation heatmap view + template + URL + nav …")

write("dashboard/liquidations_view.py", '''
    """Liquidation heatmap page — aggregates LiquidationEvent rows into
    price buckets for visualisation."""
    from datetime import timedelta
    from django.contrib.auth.decorators import login_required
    from django.shortcuts import render
    from django.http import JsonResponse
    from django.utils import timezone
    from django.views.decorators.cache import never_cache

    WINDOWS = {"1h": 1, "4h": 4, "24h": 24, "7d": 168}
    BUCKETS = 60

    def _aggregate(symbol: str, hours: int):
        from market_data.models import LiquidationEvent
        qs = LiquidationEvent.objects.filter(
            symbol=symbol, timestamp__gte=timezone.now() - timedelta(hours=hours))
        events = list(qs.values("side","price","qty","notional_usd","timestamp"))
        if not events:
            return {"buckets": [], "stats": {"long": 0, "short": 0, "biggest": 0,
                                             "count": 0, "net": 0}}
        prices = [float(e["price"]) for e in events]
        lo, hi = min(prices), max(prices)
        if lo == hi: hi = lo + 1
        step = (hi - lo) / BUCKETS
        buckets = [{"price": lo + i*step, "long": 0.0, "short": 0.0, "count": 0}
                   for i in range(BUCKETS)]
        long_tot = short_tot = biggest = 0
        for e in events:
            idx = min(BUCKETS-1, max(0, int((float(e["price"]) - lo) / step)))
            notional = float(e["notional_usd"] or 0)
            if e["side"] == "LONG":
                buckets[idx]["long"] += notional; long_tot += notional
            else:
                buckets[idx]["short"] += notional; short_tot += notional
            buckets[idx]["count"] += 1
            if notional > biggest: biggest = notional
        return {"buckets": buckets, "stats": {
            "long": round(long_tot, 2), "short": round(short_tot, 2),
            "biggest": round(biggest, 2), "count": len(events),
            "net": round(long_tot - short_tot, 2), "lo": lo, "hi": hi}}

    @login_required
    def liquidations_page(request):
        from market_data.models import LiquidationEvent
        symbol = (request.GET.get("symbol") or "BTCUSDT").upper()
        window = request.GET.get("window", "24h")
        hours = WINDOWS.get(window, 24)
        agg = _aggregate(symbol, hours)
        # Symbol choices: distinct symbols that have liquidations in last 7d
        symbols = list(LiquidationEvent.objects.filter(
            timestamp__gte=timezone.now() - timedelta(days=7)
        ).values_list("symbol", flat=True).distinct()[:30])
        if symbol not in symbols: symbols.insert(0, symbol)
        recent = list(LiquidationEvent.objects.filter(symbol=symbol).values(
            "side","price","qty","notional_usd","timestamp")[:30])
        return render(request, "dashboard/liquidations.html", {
            "page_id": "liquidations", "symbol": symbol, "window": window,
            "hours": hours, "agg": agg, "symbols": symbols, "recent": recent,
            "windows": list(WINDOWS.keys()),
        })

    @never_cache
    @login_required
    def liquidations_json(request):
        symbol = (request.GET.get("symbol") or "BTCUSDT").upper()
        window = request.GET.get("window", "24h")
        hours = WINDOWS.get(window, 24)
        return JsonResponse(_aggregate(symbol, hours))
''')

# URL wiring
patch("dashboard/urls.py",
      'path("news/", views.news_feed, name="news_feed"),',
      '''path("news/", views.news_feed, name="news_feed"),
    path("liquidations/", __import__("dashboard.liquidations_view", fromlist=["liquidations_page"]).liquidations_page, name="liquidations_page"),
    path("api/liquidations/", __import__("dashboard.liquidations_view", fromlist=["liquidations_json"]).liquidations_json, name="liquidations_json"),''')

# Template
write("templates/dashboard/liquidations.html", '''
    {% extends "base.html" %}
    {% block title %}Liquidation Heatmap — Sauron Vision{% endblock %}
    {% block page_title %}⚡ LIQUIDATION HEATMAP{% endblock %}
    {% block content %}
    <div class="page-content fade-in">

      <!-- Controls -->
      <div class="card" style="margin-bottom:18px;">
        <form method="get" style="display:flex;gap:14px;align-items:end;flex-wrap:wrap;">
          <div class="input-group" style="margin-bottom:0;">
            <label class="input-label">SYMBOL</label>
            <select name="symbol" class="input" style="min-width:160px;"
                    onchange="this.form.submit()">
              {% for s in symbols %}
                <option value="{{ s }}" {% if s == symbol %}selected{% endif %}>{{ s }}</option>
              {% endfor %}
            </select>
          </div>
          <div class="input-group" style="margin-bottom:0;">
            <label class="input-label">WINDOW</label>
            <div style="display:flex;gap:6px;">
              {% for w in windows %}
                <a href="?symbol={{ symbol }}&window={{ w }}"
                   class="btn btn-sm {% if w == window %}btn-primary{% endif %}">{{ w }}</a>
              {% endfor %}
            </div>
          </div>
          <div style="margin-left:auto;font-family:var(--font-mono);font-size:10px;color:var(--text-muted);">
            LIVE · updates as liquidations stream in
          </div>
        </form>
      </div>

      <!-- Stats -->
      <div class="grid grid-5" style="margin-bottom:18px;">
        <div class="metric">
          <div class="metric-label">LONGS LIQUIDATED</div>
          <div class="metric-value" style="color:var(--accent-red);" id="statLong">${{ agg.stats.long|floatformat:0 }}</div>
          <div class="metric-sub">total notional</div>
        </div>
        <div class="metric">
          <div class="metric-label">SHORTS LIQUIDATED</div>
          <div class="metric-value" style="color:var(--accent);" id="statShort">${{ agg.stats.short|floatformat:0 }}</div>
          <div class="metric-sub">total notional</div>
        </div>
        <div class="metric">
          <div class="metric-label">NET FLOW</div>
          <div class="metric-value" id="statNet" style="color:{% if agg.stats.net >= 0 %}var(--accent-red){% else %}var(--accent){% endif %};">
            ${{ agg.stats.net|floatformat:0 }}
          </div>
          <div class="metric-sub">long − short</div>
        </div>
        <div class="metric">
          <div class="metric-label">BIGGEST</div>
          <div class="metric-value" id="statBig">${{ agg.stats.biggest|floatformat:0 }}</div>
          <div class="metric-sub">single liquidation</div>
        </div>
        <div class="metric">
          <div class="metric-label">COUNT</div>
          <div class="metric-value" id="statCount">{{ agg.stats.count }}</div>
          <div class="metric-sub">events in window</div>
        </div>
      </div>

      <!-- Heatmap canvas -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">{{ symbol }} · {{ window|upper }} HEATMAP</div>
          <div style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);">
            <span style="color:var(--accent-red);">■</span> LONGS REKT
            &nbsp;&nbsp;
            <span style="color:var(--accent);">■</span> SHORTS REKT
          </div>
        </div>
        <canvas id="heat" style="width:100%;height:480px;"></canvas>
      </div>

      <!-- Recent liquidations feed -->
      <div class="card" style="margin-top:18px;">
        <div class="card-header"><div class="card-title">RECENT LIQUIDATIONS</div></div>
        <div id="liqFeed" style="max-height:320px;overflow-y:auto;">
          {% for e in recent %}
          <div class="signal-item">
            <div class="signal-header">
              <span class="signal-symbol" style="color:{% if e.side == 'LONG' %}var(--accent-red){% else %}var(--accent){% endif %};">
                {{ e.side }} REKT
              </span>
              <span>${{ e.notional_usd|floatformat:0 }}</span>
            </div>
            <div class="signal-desc">
              {{ e.qty|floatformat:4 }} @ ${{ e.price|floatformat:2 }} · {{ e.timestamp|timesince }} ago
            </div>
          </div>
          {% empty %}
          <div style="padding:16px;color:var(--text-muted);text-align:center;">
            No liquidations yet. Make sure <code>stream_binance_futures</code> is running.
          </div>
          {% endfor %}
        </div>
      </div>
    </div>

    <script>
    (function(){
      const SYMBOL = "{{ symbol }}";
      const WINDOW = "{{ window }}";
      const cvs = document.getElementById('heat');
      if (!cvs) return;
      const ctx = cvs.getContext('2d');
      let data = {{ agg.buckets|default:"[]"|safe }};
      let stats = {long: {{ agg.stats.long|default:0 }}, short: {{ agg.stats.short|default:0 }},
                   biggest: {{ agg.stats.biggest|default:0 }}, count: {{ agg.stats.count|default:0 }},
                   net: {{ agg.stats.net|default:0 }}};

      function resize(){ cvs.width = cvs.offsetWidth; cvs.height = 480; draw(); }
      function draw(){
        const W = cvs.width, H = cvs.height;
        ctx.clearRect(0,0,W,H);
        if (!data.length) { ctx.fillStyle = '#2a5038'; ctx.font = '12px monospace';
          ctx.fillText('No data', 20, 40); return; }
        const maxVol = Math.max(1, ...data.map(b => Math.max(b.long, b.short)));
        const barH = H / data.length;
        // Y axis: price high at top
        const reversed = [...data].reverse();
        reversed.forEach((b, i) => {
          const y = i * barH;
          // Long (red) bar to the right of center
          const longW = (b.long / maxVol) * (W * 0.47);
          const shortW = (b.short / maxVol) * (W * 0.47);
          ctx.fillStyle = 'rgba(232,48,48,' + (0.3 + 0.7*b.long/maxVol) + ')';
          ctx.fillRect(W/2, y + 0.5, longW, Math.max(1, barH - 1));
          ctx.fillStyle = 'rgba(0,232,104,' + (0.3 + 0.7*b.short/maxVol) + ')';
          ctx.fillRect(W/2 - shortW, y + 0.5, shortW, Math.max(1, barH - 1));
        });
        // Center line
        ctx.strokeStyle = '#133020'; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(W/2, 0); ctx.lineTo(W/2, H); ctx.stroke();
        // Price labels (top, middle, bottom)
        ctx.fillStyle = '#5a8a6a'; ctx.font = '10px "Share Tech Mono"';
        const hi = reversed[0]?.price || 0, lo = reversed[reversed.length-1]?.price || 0;
        ctx.fillText('$' + hi.toFixed(2), 6, 12);
        ctx.fillText('$' + ((hi+lo)/2).toFixed(2), 6, H/2);
        ctx.fillText('$' + lo.toFixed(2), 6, H - 4);
      }
      window.addEventListener('resize', resize); resize();

      // Poll every 5s to refresh from DB (cheap)
      async function refresh(){
        try {
          const r = await fetch(`/api/liquidations/?symbol=${SYMBOL}&window=${WINDOW}`, {credentials:'same-origin'});
          if (!r.ok) return;
          const j = await r.json();
          data = j.buckets || []; stats = j.stats || stats;
          draw();
          document.getElementById('statLong').textContent  = '$' + Math.round(stats.long).toLocaleString();
          document.getElementById('statShort').textContent = '$' + Math.round(stats.short).toLocaleString();
          document.getElementById('statNet').textContent   = '$' + Math.round(stats.net).toLocaleString();
          document.getElementById('statBig').textContent   = '$' + Math.round(stats.biggest).toLocaleString();
          document.getElementById('statCount').textContent = stats.count;
        } catch(e) {}
      }
      setInterval(refresh, 5000);

      // Listen for live liquidation frames from the existing WS channel
      // (we rely on the base.html WS client already being connected)
      const origOnMessage = window.__sauronWSHandler;
      window.addEventListener('sauron:liquidation', e => {
        const d = e.detail;
        if (!d || d.symbol !== SYMBOL) return;
        // Prepend to feed
        const feed = document.getElementById('liqFeed');
        if (feed) {
          const row = document.createElement('div');
          row.className = 'signal-item';
          const color = d.side === 'LONG' ? 'var(--accent-red)' : 'var(--accent)';
          row.innerHTML = `<div class="signal-header">
            <span class="signal-symbol" style="color:${color};">${d.side} REKT</span>
            <span>$${Math.round(d.notional).toLocaleString()}</span></div>
            <div class="signal-desc">${d.qty.toFixed(4)} @ $${d.price.toFixed(2)} · just now</div>`;
          row.style.animation = 'flash 1s';
          feed.prepend(row);
          while (feed.children.length > 30) feed.lastElementChild.remove();
        }
      });
    })();
    </script>
    {% endblock %}
''')

# Add liquidation link to sidebar nav under Intelligence section
patch("templates/base.html",
      '<a href="{% url \'news_feed\' %}" class="nav-link {% if page_id == \'news\' %}active{% endif %}"><span class="icon">▤</span> <span class="label-text">News & Sentiment</span></a>',
      '<a href="{% url \'news_feed\' %}" class="nav-link {% if page_id == \'news\' %}active{% endif %}"><span class="icon">▤</span> <span class="label-text">News & Sentiment</span></a>\n            <a href="{% url \'liquidations_page\' %}" class="nav-link {% if page_id == \'liquidations\' %}active{% endif %}"><span class="icon">⚡</span> <span class="label-text">Liquidations</span></a>')

# =================================================================
# STEP 7 — DashboardConsumer: liquidation + funding handlers
# =================================================================
print("\n[7/11] Extending consumer with liquidation + funding handlers …")

patch("dashboard/consumers.py",
      '    async def quote_stream(self, event):',
      '''    async def liquidation(self, event):
        """Push liquidation event to browsers."""
        await self.send(text_data=json.dumps({"type":"liquidation","data":event["data"]}))

    async def funding(self, event):
        """Push funding/mark-price tick."""
        await self.send(text_data=json.dumps({"type":"funding","data":event["data"]}))

    async def quote_stream(self, event):''')

# =================================================================
# STEP 8 — Extend base.html WS client to dispatch liquidation events
# =================================================================
print("\n[8/11] Dispatching liquidation events from WS client …")

patch("templates/base.html",
      "if (msg.type === 'quote_stream' || msg.type === 'quote') applyTick(msg.data);",
      '''if (msg.type === 'quote_stream' || msg.type === 'quote') applyTick(msg.data);
        else if (msg.type === 'liquidation') window.dispatchEvent(new CustomEvent('sauron:liquidation', {detail: msg.data}));
        else if (msg.type === 'funding') window.dispatchEvent(new CustomEvent('sauron:funding', {detail: msg.data}));''')

# =================================================================
# STEP 9 — Bot strategy: upgrade _score_liquidity to use L2 snapshots
# =================================================================
print("\n[9/11] Upgrading bot liquidity scorer …")

patch("bot_program/engine/strategy.py",
      '''def _score_liquidity(order_book: dict) -> tuple[float, list[str]]:
    """Order book imbalance → short-term pressure."""
    try:
        bids = sum(float(q) for _, q in order_book.get("bids", [])[:20])
        asks = sum(float(q) for _, q in order_book.get("asks", [])[:20])
        total = bids + asks
        if not total: return (0, [])
        imb = (bids - asks) / total  # [-1, +1]
        return (imb, [f"book imbalance {imb:+.2f}"])
    except Exception:
        return (0, [])''',
      '''def _score_liquidity(order_book: dict, symbol: str = "") -> tuple[float, list[str]]:
    """Order book pressure.

    Priority:
      1. Fresh L2 snapshot from DB (depth-weighted, <30s old).
      2. Fall back to REST order book passed in.
    """
    # 1. Try the live L2 snapshot from stream_binance_depth
    try:
        from market_data.models import OrderBookSnapshot
        from django.utils import timezone
        from datetime import timedelta
        snap = (OrderBookSnapshot.objects
                .filter(symbol__iexact=symbol,
                        timestamp__gte=timezone.now() - timedelta(seconds=30))
                .order_by("-timestamp").first())
        if snap:
            return (float(snap.depth_score),
                    [f"L2 depth {snap.depth_score:+.2f} (imb {snap.imbalance:+.2f})"])
    except Exception:
        pass
    # 2. Fallback to REST order book
    try:
        bids = sum(float(q) for _, q in order_book.get("bids", [])[:20])
        asks = sum(float(q) for _, q in order_book.get("asks", [])[:20])
        total = bids + asks
        if not total: return (0, [])
        imb = (bids - asks) / total
        return (imb, [f"REST imbalance {imb:+.2f}"])
    except Exception:
        return (0, [])''')

# Patch the caller in decide() to pass symbol
patch("bot_program/engine/strategy.py",
      'parts["liquidity"], r = _score_liquidity(order_book);     reasons += r',
      'parts["liquidity"], r = _score_liquidity(order_book, symbol); reasons += r')

# =================================================================
# STEP 10 — Requirements + env example
# =================================================================
print("\n[10/11] Updating requirements.txt + .env.example …")

req = ROOT / "requirements.txt"
if req.exists():
    t = req.read_text(encoding="utf-8")
    if "aiohttp" not in t:
        req.write_text(t.rstrip() + "\naiohttp>=3.9\n", encoding="utf-8")
        print("  added aiohttp")

env_ex = ROOT / ".env.example"
if env_ex.exists():
    t = env_ex.read_text(encoding="utf-8")
    additions = []
    if "FINNHUB_API_KEY" not in t: additions.append("FINNHUB_API_KEY=")
    if "OANDA_API_KEY" not in t:
        additions += ["OANDA_API_KEY=", "OANDA_ACCOUNT_ID=", "OANDA_ENV=practice"]
    if additions:
        env_ex.write_text(t.rstrip() + "\n\n# UPGRADE-4 streamers\n" + "\n".join(additions) + "\n", encoding="utf-8")
        print(f"  added {len(additions)} env vars to .env.example")

# =================================================================
# STEP 11 — Render worker doc + migrations
# =================================================================
print("\n[11/11] Updating render.worker.md + running migrations …")

rw = ROOT / "render.worker.md"
if rw.exists():
    t = rw.read_text(encoding="utf-8")
    if "stream_binance_futures" not in t:
        t += dedent('''

            ---

            ## Pass 4 additional workers

            Each streamer runs as its own Render worker. All of them must
            share the same Redis URL as the web service so broadcasts
            reach connected browsers. Add blocks to `render.yaml`:

            ```yaml
              - type: worker
                name: sauron-binance-futures
                startCommand: "python manage.py stream_binance_futures"
              - type: worker
                name: sauron-binance-depth
                startCommand: "python manage.py stream_binance_depth"
              - type: worker
                name: sauron-finnhub
                startCommand: "python manage.py stream_finnhub"
                envVars:
                  - key: FINNHUB_API_KEY
                    sync: false
              - type: worker
                name: sauron-oanda
                startCommand: "python manage.py stream_oanda"
                envVars:
                  - key: OANDA_API_KEY
                    sync: false
                  - key: OANDA_ACCOUNT_ID
                    sync: false
                  - key: OANDA_ENV
                    value: practice
            ```

            Each worker is its own $7/mo Starter dyno on Render. If that
            adds up, you can run all the streamers on one cheap VPS
            instead: each `stream_*` command is just `python manage.py
            stream_...` with the DATABASE_URL + REDIS_URL env vars set.

            ## Storage notes
            - **LiquidationEvent** rows grow quickly. Add a nightly
              cleanup to keep only the last 30 days:
              ```python
              # scraping/tasks.py or a new cleanup task
              LiquidationEvent.objects.filter(
                  timestamp__lt=timezone.now() - timedelta(days=30)
              ).delete()
              ```
            - **OrderBookSnapshot** is auto-pruned to last 2000 rows per
              symbol by the streamer itself (opportunistic, random 1%
              probability per write).
            - **FundingRate** is throttled to one write per symbol every
              30s, so growth is bounded.
        ''')
        rw.write_text(t, encoding="utf-8")
        print("  appended pass-4 worker blocks to render.worker.md")

print("\n  running: python manage.py makemigrations market_data")
subprocess.run([sys.executable, "manage.py", "makemigrations", "market_data"],
               cwd=str(ROOT))
print("  running: python manage.py migrate")
subprocess.run([sys.executable, "manage.py", "migrate"], cwd=str(ROOT))

print("\n" + "━" * 60)
print(" ✓ UPGRADE PASS 4 COMPLETE")
print("━" * 60)
print("""
Four new streamers are now available. Run each one in its own terminal
(or as its own Render worker). All four broadcast to the same Channels
group so your browser updates from all of them simultaneously.

  python manage.py stream_binance                 # spot crypto ticks  (pass 3)
  python manage.py stream_binance_futures         # liquidations + funding
  python manage.py stream_binance_depth           # L2 order book → bot
  FINNHUB_API_KEY=... python manage.py stream_finnhub
  OANDA_API_KEY=... OANDA_ACCOUNT_ID=... python manage.py stream_oanda

NEW PAGE:
  /liquidations/
    • Symbol selector
    • Time window: 1h / 4h / 24h / 7d
    • Canvas heatmap: long (red) right of center, short (green) left
    • Live stats: long total, short total, net flow, biggest, count
    • Live feed of recent liquidations (streams in as they happen)
    • 5s background poll + WebSocket live updates

BOT UPGRADE:
  The liquidity scorer in bot_program/engine/strategy.py now prefers
  the DB L2 snapshot written by stream_binance_depth (depth-weighted,
  <30s old), falling back to REST order book. Your bot's composite
  score is now directly informed by real-time order book pressure.

FREE API KEYS:
  • Finnhub: https://finnhub.io/ → free tier, 50 symbols, ~1s ticks
  • OANDA:   https://www.oanda.com/demo-account/ → free forex streaming

PASS-3 ENVIRONMENT (reminder):
  pip install -r requirements.txt   # pulls aiohttp + websockets
  python manage.py runserver
""")
