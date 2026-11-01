"""ONE WRITE IN FLIGHT PER SYMBOL, THE NEWEST TICK BEHIND IT (2026-10-31).

The streamers (stream_finnhub, stream_binance, stream_oanda) broadcast only
a tick write_quote accepted. Waiting for that answer in the read loop
(`if await _fire(update_live_quote(...))`) paused the socket read on every
database write, and the writes run one at a time on asgiref's single
thread-sensitive executor: under a Finnhub open on fifty symbols the
websocket's frame queue filled, the library paused reading, the pong went
unread and the 20 s keepalive closed the stream, which then reconnected
and resubscribed in a loop while LiveQuote (which the mark checks also
read as a second opinion) went stale. The writes handed to the background
before that queued without bound and fell further behind under the same
load.

So the read loop hands each tick to LatestPerSymbol and reads on. One
write per symbol is in flight; a tick that arrives meanwhile waits, and a
newer one replaces it (the row keeps the newest price, which is what a
reader of LiveQuote wants). The backlog is at most one tick per symbol,
and the broadcast still follows only an accepted write: the job a
streamer submits is "write, then broadcast when written".
"""
import asyncio
import logging

log = logging.getLogger(__name__)


class LatestPerSymbol:
    """Runs one job per symbol at a time; the newest waiting job of a busy
    symbol replaces the one before it.

    `fire` is the streamer's own task owner (its `_fire`), so the task is
    held until it ends. A job is a zero-argument callable returning the
    coroutine to run."""

    def __init__(self, fire):
        self._fire = fire
        self._busy = set()
        self._waiting = {}
        #: Ticks replaced by a newer one before their write began.
        self.replaced = 0

    def submit(self, symbol, job):
        """Start `job` for `symbol`, or leave it waiting behind the write in
        flight. Never awaits: the caller's read loop goes on reading."""
        if symbol in self._busy:
            if symbol in self._waiting:
                self.replaced += 1
            self._waiting[symbol] = job
            return None
        self._busy.add(symbol)
        return self._fire(self._drain(symbol, job))

    async def _drain(self, symbol, job):
        try:
            while job is not None:
                try:
                    await job()
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 — one tick never wedges its symbol
                    log.warning("stream write for %s failed: %s: %s",
                                symbol, type(e).__name__, e)
                job = self._waiting.pop(symbol, None)
        finally:
            self._busy.discard(symbol)
            self._waiting.pop(symbol, None)
