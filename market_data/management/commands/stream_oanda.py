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
    """Every streamable forex pair, MOST-WANTED FIRST.

    Order is load-bearing, not cosmetic. A single OANDA pricing stream is
    capped, and the catalogue carries 47 pairs — so whatever the cap drops
    is decided here. Sorted alphabetically, the first twenty are AUD_CAD
    through EUR_USD, which streams CHF_HUF and EUR_PLN in real time while
    leaving GBP_USD, USD_JPY, USD_CHF, USD_CAD, NZD_USD, GBP_JPY and
    GBP_CHF — seven of the thirteen pairs the seeded fleet actually trades
    — on fifteen-minute yfinance marks.

    So the bots' own symbols come first, then the rest of the catalogue.
    A pair no config watches is still worth streaming if there is room;
    it is simply the first thing to lose.
    """
    if override: return [s.upper() for s in override]

    def _oanda(sym):
        sym = (sym or "").upper().replace("/", "_").replace("-", "_")
        if len(sym) == 6 and "_" not in sym:
            sym = f"{sym[:3]}_{sym[3:]}"
        return sym if "_" in sym else ""

    try:
        from instruments.models import Instrument
        syms = list(Instrument.objects.filter(
            asset_class__iexact="forex", is_active=True
        ).values_list("symbol", flat=True))
        catalogue = [x for x in (_oanda(s) for s in syms) if x]

        wanted = []
        try:
            from bot_program.models import AssetBotConfig
            for cfg in AssetBotConfig.objects.filter(
                    asset_class="forex", enabled=True):
                for sym in (cfg.symbols or []):
                    pair = _oanda(sym)
                    if pair and pair not in wanted:
                        wanted.append(pair)
        except Exception as e:  # noqa: BLE001 - ordering is an optimisation
            log.debug("discover_instruments: fleet order unavailable: %s", e)

        ordered = ([p for p in wanted if p in catalogue]
                   + [p for p in sorted(catalogue) if p not in wanted])
        return ordered or ["EUR_USD","GBP_USD","USD_JPY","AUD_USD"]
    except Exception:
        return ["EUR_USD","GBP_USD","USD_JPY","AUD_USD"]

@sync_to_async
def update_live_quote(symbol_display, bid, ask):
    """Through the one writer, as source 'oanda_stream'.

    This was the last streamer writing LiveQuote directly — skipping the
    source-precedence guard, the zero/NaN price refusal and the shared
    symbol resolution. It also stamped source='oanda', the REST tier
    (priority 70): a real-time broker tick that ranked below finnhub_ws
    and could itself be clobbered. 'oanda_stream' is the tier the priority
    table always reserved for it.
    """
    from market_data.quotes import resolve_instrument, write_quote
    try:
        inst = resolve_instrument(symbol_display)
        if not inst:
            # Loud, because a silent drop here once cost every tick: the
            # dashboard broadcast kept animating while LiveQuote starved.
            log.warning("update_live_quote: no Instrument for %r — tick "
                        "dropped", symbol_display)
            return
        mid = (bid + ask) / 2
        # NO change_pct. What this stream can compute is the move since
        # the LAST TICK, and `change_pct` is the field every reader on
        # this platform renders as the change on the DAY - the headband
        # cells, the watchlist rail, the ticker bar. A tick-over-tick
        # delta on a forex mid is a pip or two, so writing it here
        # flattened the day column to +0.00% for every pair the moment
        # the stream came up, and kept it there for as long as ticks
        # arrived. write_quote leaves the column alone when it is None,
        # so the poller - which reads a real daily open and therefore
        # actually knows - keeps owning it. Binance is the shape to
        # copy: its @ticker payload carries a true 24h "P", so it has
        # something honest to write and writes it.
        write_quote(inst.symbol, last=mid, source="oanda_stream",
                    bid=bid, ask=ask, instrument=inst)
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

#: OANDA rejects the WHOLE subscription if any one instrument is not
#: available to the account, and it does so with a bare 400 that names no
#: culprit. The catalogue carries 47 forex pairs including CHF_HUF,
#: USD_CNH, USD_CZK, USD_RON, USD_TRY and ZAR_JPY; a demo account — a US
#: one especially, where CFTC rules cut the list hard — carries far fewer.
#: One absent pair and the stream never opens at all, which reads on the
#: health panel as a feed that has never delivered.
async def account_instruments(session, base_rest, account_id):
    """The instrument names this account may actually stream, or None.

    None means "could not ask" — the caller then subscribes to the
    catalogue as before, because refusing to stream on a failed lookup
    would turn a working feed off.
    """
    try:
        url = f"{base_rest}/v3/accounts/{account_id}/instruments"
        async with session.get(url) as r:
            if r.status != 200:
                log.warning("oanda: could not list account instruments "
                            "(%s) — subscribing to the catalogue", r.status)
                return None
            payload = await r.json()
        names = {i.get("name") for i in (payload.get("instruments") or [])
                 if i.get("name")}
        return names or None
    except Exception as e:  # noqa: BLE001 - never let this stop the stream
        log.warning("oanda: instrument list failed (%s) — subscribing to "
                    "the catalogue", e)
        return None


#: A single stream request carries every instrument in one query string.
#: Chunking keeps one connection per group, so a pair that becomes
#: unavailable later costs its own group rather than every pair.
STREAM_CHUNK = 20


async def run(api_key, account_id, env, override):
    try: import aiohttp
    except ImportError:
        log.error("pip install aiohttp"); return

    base = "https://stream-fxtrade.oanda.com" if env == "live" else "https://stream-fxpractice.oanda.com"
    base_rest = ("https://api-fxtrade.oanda.com" if env == "live"
                 else "https://api-fxpractice.oanda.com")
    headers = {"Authorization": f"Bearer {api_key}", "Accept-Datetime-Format": "RFC3339"}
    backoff = 1
    allowed = None          # what this account may stream; None = not asked yet

    while True:
        instruments = await discover_instruments(override)
        url = f"{base}/v3/accounts/{account_id}/pricing/stream"
        try:
            timeout = aiohttp.ClientTimeout(total=None, sock_read=60)
            async with aiohttp.ClientSession(headers=headers, timeout=timeout) as s:
                # Asked once per connection, not once per process: an
                # account's instrument set can change (a new region, a
                # closed sub-account) and a reconnect is the natural moment
                # to re-read it.
                if allowed is None:
                    allowed = await account_instruments(s, base_rest,
                                                        account_id)
                if allowed:
                    keep = [i for i in instruments if i in allowed]
                    dropped = [i for i in instruments if i not in allowed]
                    if dropped:
                        # Named, not counted. "38 of 47" tells an operator
                        # nothing they can act on; the list tells them
                        # whether the catalogue or the account is wrong.
                        log.warning(
                            "oanda: %d of %d catalogue pairs are not "
                            "available on this account and were dropped "
                            "from the subscription: %s",
                            len(dropped), len(instruments),
                            ", ".join(sorted(dropped)))
                    instruments = keep
                if not instruments:
                    log.error("oanda: this account can stream NONE of the "
                              "catalogue's forex pairs — nothing to "
                              "subscribe to")
                    raise RuntimeError("no streamable instruments")
                # One request per chunk would need one task per chunk; the
                # stream is a single long-lived response, so the cap is
                # applied instead and the remainder logged rather than
                # silently dropped.
                if len(instruments) > STREAM_CHUNK:
                    log.warning(
                        "oanda: subscribing to the first %d of %d available "
                        "pairs (OANDA caps a single pricing stream); the "
                        "rest keep their poller marks: %s",
                        STREAM_CHUNK, len(instruments),
                        ", ".join(sorted(instruments[STREAM_CHUNK:])))
                    instruments = instruments[:STREAM_CHUNK]
                params = {"instruments": ",".join(instruments)}
                log.info("oanda: connecting for %d instruments (%s)",
                         len(instruments), ", ".join(instruments))
                async with s.get(url, params=params) as r:
                    if r.status == 400:
                        # OANDA's 400 names no culprit, so say what was
                        # asked for — this is the message that turns "the
                        # feed is dead" into "these pairs are wrong".
                        body = (await r.text())[:300]
                        log.error("oanda REFUSED the subscription (400). "
                                  "Asked for: %s. Response: %s",
                                  ", ".join(instruments), body)
                        allowed = None   # re-ask on the next attempt
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
                            # None, not 0: a hardcoded zero painted
                            # "+0.00%" over the real day change in the
                            # headband and the rail on every tick.
                            await broadcast(sym, mid, None, bid, ask)
                        except Exception as e:
                            log.debug("tick: %s", e)
        except Exception as e:
            log.warning("oanda disconnected: %s", e)
        delay = min(60, backoff + random.random()); backoff = min(60, backoff*2)
        log.info("reconnect in %.1fs", delay); await asyncio.sleep(delay)
