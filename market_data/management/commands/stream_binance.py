"""
stream_binance — long-lived asyncio worker that subscribes to Binance
public combined WebSocket streams for every crypto Instrument in the DB
and broadcasts each tick to connected browsers via Django Channels.

Run locally:   python manage.py stream_binance
Run on Render: create a "worker" service with this as its startCommand.

The command is restart-safe. It:
  • discovers crypto symbols from Instrument rows (asset_class="crypto")
  • auto-reconnects with exponential backoff on disconnect
  • refreshes its symbol list every 60s so new watchlist entries
    are picked up without a restart
  • writes the latest price into market_data.LiveQuote
  • broadcasts to Channels group "dashboard_live" with type
    "quote_stream" (handled by DashboardConsumer.quote_stream)
"""
from __future__ import annotations
import asyncio
import json
import logging
import random
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone
from asgiref.sync import sync_to_async

log = logging.getLogger("stream_binance")

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream?streams="
REFRESH_SYMBOLS_EVERY = 60  # seconds


class Command(BaseCommand):
    help = "Stream live Binance tickers into LiveQuote and broadcast to WebSockets."

    def add_arguments(self, parser):
        parser.add_argument("--symbols", nargs="*", default=None,
            help="Override symbol list (e.g. --symbols BTCUSDT ETHUSDT). "
                 "If omitted, symbols are pulled from Instrument table.")
        parser.add_argument("--quiet", action="store_true")

    def handle(self, *args, **opts):
        if opts["quiet"]:
            logging.basicConfig(level=logging.WARNING)
        else:
            logging.basicConfig(level=logging.INFO,
                format="%(asctime)s %(levelname)s %(message)s")
        try:
            asyncio.run(run(opts.get("symbols")))
        except KeyboardInterrupt:
            log.info("stopped by user")


# ───────────────────────────────────────────────────────────
# Symbol discovery
# ───────────────────────────────────────────────────────────
@sync_to_async
def discover_symbols(override: list[str] | None) -> list[str]:
    if override:
        return [s.upper() for s in override]
    try:
        from instruments.models import Instrument
        syms = list(Instrument.objects.filter(
            asset_class__iexact="crypto", is_active=True
        ).values_list("symbol", flat=True))
        # Normalise: Binance expects BTCUSDT format (no slashes, no dashes)
        cleaned = []
        for s in syms:
            s = s.upper().replace("-", "").replace("/", "").replace(":", "")
            if s.endswith("USDT") or s.endswith("BUSD") or s.endswith("USDC") or s.endswith("BTC"):
                cleaned.append(s)
        return cleaned or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    except Exception as e:
        log.warning("symbol discovery failed, using defaults: %s", e)
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]


@sync_to_async
def update_live_quote(symbol: str, last: float, change_pct: float,
                      bid: float, ask: float, volume: float):
    from market_data.quotes import write_quote
    try:
        # Binance streams BTCUSDT while the Instrument row is BTCUSD, so a
        # direct symbol match silently dropped every tick. write_quote()
        # resolves the equivalent symbol and applies source precedence.
        write_quote(symbol, last=last, source="binance_ws",
                    change_pct=change_pct, bid=bid or None, ask=ask or None,
                    volume=volume or 0)
    except Exception as e:
        log.debug("update_live_quote(%s) failed: %s", symbol, e)


async def broadcast(symbol: str, last: float, change_pct: float,
                    bid: float, ask: float, volume: float):
    """Push to Channels group so all browsers receive it."""
    try:
        from channels.layers import get_channel_layer
        layer = get_channel_layer()
        if not layer:
            return
        await layer.group_send("dashboard_live", {
            "type": "quote_stream",
            "data": {
                "symbol": symbol,
                "last": last,
                "change_pct": round(change_pct, 4),
                "bid": bid,
                "ask": ask,
                "volume": volume,
                "ts": timezone.now().isoformat(),
            },
        })
    except Exception as e:
        log.debug("broadcast(%s) failed: %s", symbol, e)


# ───────────────────────────────────────────────────────────
# Main loop
# ───────────────────────────────────────────────────────────
async def run(override_symbols: list[str] | None):
    try:
        import websockets
    except ImportError:
        log.error("The 'websockets' package is required. Install with: pip install websockets")
        return

    backoff = 1
    current_task: asyncio.Task | None = None
    current_symbols: list[str] = []

    async def stream_loop(symbols: list[str]):
        nonlocal backoff
        streams = "/".join(f"{s.lower()}@ticker" for s in symbols)
        url = BINANCE_WS_BASE + streams
        log.info("connecting to %d stream(s): %s", len(symbols), ", ".join(symbols[:10]) + ("…" if len(symbols) > 10 else ""))
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=2**20) as ws:
                backoff = 1
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        d = msg.get("data") or msg
                        sym = (d.get("s") or "").upper()
                        if not sym:
                            continue
                        last = float(d.get("c") or 0)           # last price
                        change_pct = float(d.get("P") or 0)     # 24h %
                        bid = float(d.get("b") or 0)
                        ask = float(d.get("a") or 0)
                        volume = float(d.get("v") or 0)         # base volume 24h
                        # Fire and forget DB write; broadcast inline.
                        asyncio.create_task(
                            update_live_quote(sym, last, change_pct, bid, ask, volume)
                        )
                        await broadcast(sym, last, change_pct, bid, ask, volume)
                    except Exception as e:
                        log.debug("tick parse failed: %s", e)
        except Exception as e:
            log.warning("stream disconnected: %s", e)
            return

    while True:
        symbols = await discover_symbols(override_symbols)
        if not symbols:
            log.warning("no crypto symbols to stream; retrying in 30s")
            await asyncio.sleep(30); continue

        # If symbol list changed, restart the inner stream.
        if set(symbols) != set(current_symbols):
            current_symbols = symbols
            if current_task and not current_task.done():
                current_task.cancel()
                try: await current_task
                except (asyncio.CancelledError, Exception): pass
            current_task = asyncio.create_task(stream_loop(symbols))

        # Wait before checking symbol list again; reconnect with backoff on failure.
        try:
            await asyncio.wait_for(asyncio.shield(current_task), timeout=REFRESH_SYMBOLS_EVERY)
            # If the stream task exited, it disconnected — back off and retry.
            delay = min(60, backoff + random.random())
            backoff = min(60, backoff * 2)
            log.info("reconnecting in %.1fs …", delay)
            await asyncio.sleep(delay)
            current_task = None
            current_symbols = []
        except asyncio.TimeoutError:
            # Still streaming — loop around and refresh symbol list.
            continue
