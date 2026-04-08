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
