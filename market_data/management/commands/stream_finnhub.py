"""Finnhub US stocks real-time trades → LiveQuote + broadcast.

Requires FINNHUB_API_KEY env var. Free tier supports up to ~50
symbol subscriptions with ~1s latency.

Run:  python manage.py stream_finnhub

A FEED THAT WRITES NOTHING MUST NOT LOOK LIKE A QUIET MARKET (2026-10-06).
The health digest called this stream silent since before the close; the
container was Up and its log had nothing to say. Every LiveQuote write
failure here went to `log.debug` — a deletion in production, where the
root logger sits at WARNING — and the write was handed to
`asyncio.create_task` and dropped, so a database connection that died
under the stream (a postgres restart, an idle timeout) failed every write
from then on, in silence, while the socket kept receiving and the
headband kept animating from the same ticks. The shape is the futures and
spot streamers' (stream_binance_futures, 2026-09-14; stream_binance):

  * the first failed write is a WARNING naming the symbol and the
    exception, every hundredth after it a footnote (_report_failure);
  * a failed write closes the thread's database connection, so the next
    write reconnects instead of failing for the life of the process
    (_reconnect_db);
  * a heartbeat on its own task says every HEARTBEAT_SEC what was
    received and what landed, so a socket that receives nothing and a
    socket whose writes all fail read differently in `docker logs`;
  * the connect line is a WARNING, once per connection, so a twelve-hour
    -old container's log is never empty.
"""
from __future__ import annotations
import asyncio, json, logging, os, random
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from asgiref.sync import sync_to_async

log = logging.getLogger("stream_finnhub")

#: How often the heartbeat speaks, in seconds. Ten minutes rather than the
#: futures sibling's five: this market is shut two thirds of the day, and
#: a `docker logs --tail 50` still covers eight hours.
HEARTBEAT_SEC = 600

#: After the first, one failure report per this many. A feed broken for
#: an hour must not hide, and must not fill the disk either.
FAILURE_REPORT_EVERY = 100

#: What this process has DONE. Module-level on purpose: one streamer per
#: container, and the numbers outlive every reconnection.
STATS = {"ticks": 0, "tick_errors": 0, "quotes_written": 0, "quotes_failed": 0}

#: `asyncio.create_task` returns a task the event loop only weakly holds.
#: Dropping it permits collection before the coroutine runs and discards
#: any exception it raises. Own it until it is done.
_PENDING: set = set()


def _fire(coro):
    """Run `coro` in the background, keeping the task alive until it ends."""
    task = asyncio.create_task(coro)
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)
    return task


def _report_failure(where: str, symbol: str, exc: Exception, count: int):
    """The first failure is loud. The hundredth is a footnote."""
    if count == 1 or count % FAILURE_REPORT_EVERY == 0:
        log.warning("finnhub: %s failed for %s (failure #%d) — %s: %s",
                    where, symbol or "?", count, type(exc).__name__, exc)


def _reconnect_db():
    """Close the thread's database connection after a failed write.

    `sync_to_async` runs every write on one thread, whose connection is
    reused for the life of the process; once it has died under the stream
    every write raises the same InterfaceError until something closes it.
    `close_old_connections` closes a connection that erred, and the next
    write opens a fresh one.
    """
    try:
        from django.db import close_old_connections
        close_old_connections()
    except Exception as e:  # noqa: BLE001 — a reconnect must not take the loop down
        log.debug("close_old_connections: %s", e)


def heartbeat_line() -> str:
    """One line an operator can act on: what arrived, and what landed."""
    return (f"{STATS['ticks']} trade prints · quotes "
            f"{STATS['quotes_written']} written / "
            f"{STATS['quotes_failed']} failed · "
            f"{STATS['tick_errors']} unparsed")


async def _heartbeat(stop: "asyncio.Event"):
    """Print `heartbeat_line()` every HEARTBEAT_SEC until `stop` is set.

    On its own task rather than inside the message loop, so it still
    fires when no message ever arrives — which is precisely the state
    that used to be indistinguishable from a working feed.
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
            "finnhub: %s%s", heartbeat_line(),
            " — no trade print since the last line (the US session may be "
            "shut; in session, the subscription is open and empty)"
            if silent else "")


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
    except Exception as e:
        # Said, not swallowed: a catalogue that cannot be read streams five
        # defaults, and the forty-five the bots trade keep their poller
        # marks. The database is closed so the next discovery reconnects.
        log.warning("finnhub: symbol discovery failed, streaming defaults "
                    "— %s: %s", type(e).__name__, e)
        _reconnect_db()
        return ["AAPL","MSFT","NVDA","TSLA","SPY"]

@sync_to_async
def update_live_quote(symbol, last, volume) -> bool:
    """Through the one writer, as source `finnhub_ws`. True when written.

    Two things were wrong here. It wrote LiveQuote DIRECTLY, so it
    skipped both guards that make the quote table trustworthy - the
    source-precedence check and the zero/negative price refusal. And
    it stamped source "finnhub", which is not a key in
    SOURCE_PRIORITY: a real-time exchange trade landed on the default
    tier of 50 instead of the 90 the table reserves for `finnhub_ws`,
    below ibkr and alpaca, so a delayed REST poll could overwrite a
    live trade print.

    It also computed change_pct as the move since the LAST TICK and
    wrote it into the field every reader renders as the change on the
    DAY. On a liquid name that is a rounding error, so the day column
    read +0.00% for as long as the stream was up. A streamer with no
    daily open has nothing honest to say there; write_quote leaves the
    column alone when it is None and the poller keeps owning it.

    A failure is REPORTED (the first at WARNING, every hundredth after)
    and closes the thread's database connection, so a connection that
    died under the stream is reopened by the next write instead of
    failing every write for the life of the process in silence
    (2026-10-06).
    """
    from market_data.quotes import write_quote
    try:
        written = write_quote(symbol, last=last, source="finnhub_ws",
                              volume=volume or 0)
    except Exception as e:
        STATS["quotes_failed"] += 1
        _report_failure("update_live_quote", symbol, e, STATS["quotes_failed"])
        _reconnect_db()
        return False
    if written:
        STATS["quotes_written"] += 1
    return bool(written)

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
        # WARNING, not INFO: the root logger sits at WARNING in production,
        # so the INFO this was never reached `docker logs`. Once per
        # connection, not per tick.
        log.warning("finnhub: connecting for %d symbols", len(symbols))
        stop = beat = None
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                backoff = 1
                stop = asyncio.Event()
                beat = _fire(_heartbeat(stop))
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
                            STATS["ticks"] += 1
                            # A finnhub trade print carries no daily
                            # open, so there is no day change to send.
                            # None leaves the column as the poller set
                            # it; 0 painted "+0.00%" over it.
                            _fire(update_live_quote(sym, last, vol))
                            await broadcast(sym, last, None, vol)
                    except Exception as e:
                        # Was log.debug, i.e. discarded in production. A
                        # tick this process cannot parse is a tick it does
                        # not write.
                        STATS["tick_errors"] += 1
                        _report_failure("tick", "", e, STATS["tick_errors"])
        except Exception as e:
            log.warning("finnhub disconnected: %s", e)
        finally:
            # The heartbeat belongs to the connection. Left running across
            # a reconnect it would print the same counts twice a cycle.
            if beat is not None:
                stop.set()
                beat.cancel()
        delay = min(60, backoff + random.random()); backoff = min(60, backoff*2)
        log.info("reconnect in %.1fs", delay); await asyncio.sleep(delay)
