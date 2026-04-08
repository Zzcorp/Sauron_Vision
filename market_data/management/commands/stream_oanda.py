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
