"""Binance USDT-M futures streamer — liquidations + mark/funding.

Endpoints:
  wss://fstream.binance.com/stream?streams=btcusdt@forceOrder/btcusdt@markPrice@1s/...

Writes:
  - market_data.LiquidationEvent for every @forceOrder tick
  - market_data.FundingRate every @markPrice tick (throttled to ~1/min)
Broadcasts:
  - "liquidation" frames to the dashboard_live Channels group
  - "funding" frames idem

WHY THIS PROCESS COULD NOT BE TRUSTED (2026-09-14)
--------------------------------------------------

`FundingRate` held 0 rows on the live box while this worker reported a
healthy connection and `funding_carry` refused all 15 crypto instruments
for want of the snapshots it was supposed to write.

Both write paths swallowed every exception into `log.debug`, and
`core.logging_config` puts the root logger at WARNING when DEBUG is off.
So a stream that connected, subscribed, received ticks and failed EVERY
insert was indistinguishable from a healthy one: container Up, socket
open, table empty, `docker logs` silent. The writes were also handed to
`asyncio.create_task` with the task dropped on the floor — an unreferenced
task can be collected before it runs, and its exception is never
retrieved.

Three changes, none of which touch what is written:

  - The FIRST failure on either path is a WARNING carrying the exception
    type and the symbol. After that one per hundred, so a persistently
    broken feed is visible without flooding the log.
  - `STATS` counts what landed and what did not, and a heartbeat prints it
    every HEARTBEAT_SEC. The heartbeat runs on its own task, so it fires
    even when no tick ever arrives — and says so explicitly, because
    silence on an open socket is this process's worst failure mode and the
    one it was least able to show.
  - `_fire` keeps a reference to each write task until it completes.

Unmeasured is not zero: an empty table with no failure count says nothing
about whether the feed works. A table with 0 written and 4,812 failed says
everything.
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

#: Seconds between heartbeat lines. Long enough to cost nothing, short
#: enough that an operator who runs `docker logs --tail 20` on a broken
#: feed sees the problem in the window they actually look at.
HEARTBEAT_SEC = 300

#: After the first, one failure report per this many. A feed that is broken
#: for an hour should not be able to hide, and should not be able to fill
#: the disk either.
FAILURE_REPORT_EVERY = 100

#: What this process has DONE, not what it was asked to do. Read by the
#: heartbeat. Module-level on purpose: there is one streamer per container
#: and the numbers have to outlive every reconnection, since a stream that
#: reconnects cleanly every 30s and writes nothing is the case that matters.
STATS = {
    "ticks": 0, "tick_errors": 0,
    "funding_written": 0, "funding_failed": 0,
    "liquidations_written": 0, "liquidations_failed": 0,
}

#: `asyncio.create_task` returns a task the event loop only weakly holds.
#: Dropping it permits collection before the coroutine runs and discards any
#: exception it raises. Own it until it is done.
_PENDING: set = set()


def _fire(coro):
    """Run `coro` in the background, keeping the task alive until it ends."""
    task = asyncio.create_task(coro)
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)
    return task


def _report_failure(where: str, symbol: str, exc: Exception, count: int):
    """The first failure is loud. The hundredth is a footnote.

    This was a `log.debug`, which in production is not a volume choice but
    a deletion: the root logger sits at WARNING when DEBUG is off. A broken
    write path is allowed to be quiet about its hundredth failure; it is
    not allowed to be quiet about its first.
    """
    if count == 1 or count % FAILURE_REPORT_EVERY == 0:
        log.warning("futures: %s failed for %s (failure #%d) — %s: %s",
                    where, symbol or "?", count, type(exc).__name__, exc)


def heartbeat_line() -> str:
    """One line an operator can act on: what landed, and what did not."""
    return (f"{STATS['ticks']} ticks · "
            f"funding {STATS['funding_written']} written / "
            f"{STATS['funding_failed']} failed · "
            f"liquidations {STATS['liquidations_written']} written / "
            f"{STATS['liquidations_failed']} failed · "
            f"{STATS['tick_errors']} unparsed")


async def _heartbeat(stop: "asyncio.Event"):
    """Print `heartbeat_line()` every HEARTBEAT_SEC until `stop` is set.

    On its own task rather than inside the message loop, so it still fires
    when no message ever arrives — which is precisely the state that used to
    be indistinguishable from a working feed.
    """
    last_ticks = STATS["ticks"]
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_SEC)
            return
        except asyncio.TimeoutError:
            pass
        silent = STATS["ticks"] == last_ticks
        last_ticks = STATS["ticks"]
        log.warning(
            "futures: %s%s", heartbeat_line(),
            " — NOTHING RECEIVED SINCE THE LAST LINE, the subscription is "
            "open and empty" if silent else "")

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
        STATS["liquidations_failed"] += 1
        _report_failure("save_liquidation", symbol, e,
                        STATS["liquidations_failed"])
        return False
    STATS["liquidations_written"] += 1
    return True

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
        STATS["funding_failed"] += 1
        _report_failure("save_funding", symbol, e, STATS["funding_failed"])
        return False
    STATS["funding_written"] += 1
    return True

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
                stop = asyncio.Event()
                beat = _fire(_heartbeat(stop))
                async for raw in ws:
                    STATS["ticks"] += 1
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
                            _fire(save_liquidation(sym, side, qty, price, notional, ts))
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
                                _fire(save_funding(sym, mark, index, rate, nft, now_ts))
                                await broadcast("funding", {
                                    "symbol": sym, "mark": mark, "index": index,
                                    "rate": rate, "next_funding": nft.isoformat() if nft else None})
                    except Exception as e:
                        # Was log.debug, i.e. discarded in production. A tick
                        # this process cannot parse is a tick it does not
                        # write, and a feed that changed shape would have
                        # emptied both tables in silence.
                        STATS["tick_errors"] += 1
                        _report_failure("tick", "", e, STATS["tick_errors"])
        except Exception as e:
            log.warning("futures disconnected: %s", e)
        finally:
            # The heartbeat belongs to the connection. Left running across a
            # reconnect it would print the same counts twice a cycle.
            try:
                stop.set()
                beat.cancel()
            except (NameError, UnboundLocalError):
                pass  # connect() itself failed; there is no heartbeat yet
        delay = min(60, backoff + random.random()); backoff = min(60, backoff*2)
        # WARNING for the same reason as the connect line: the root logger
        # drops INFO in production, so a worker reconnecting every second was
        # silent. The counts come with it, because a reconnect loop that
        # writes nothing is the failure this file exists to make visible.
        log.warning("futures: reconnect in %.1fs — %s", delay, heartbeat_line())
        await asyncio.sleep(delay)
