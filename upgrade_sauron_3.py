#!/usr/bin/env python3
"""
upgrade_sauron_3.py
===================
Third upgrade pass — real-time sub-second live data for crypto via
Binance WebSocket + Django Channels broadcast.

Drop into project root (next to manage.py) and run:

    python upgrade_sauron_3.py

Idempotent. No DB migrations.

What it does
------------
1. Adds `market_data/management/commands/stream_binance.py` — a
   long-lived asyncio worker that subscribes to Binance combined
   streams for every crypto instrument in your DB, writes updates
   into LiveQuote, and broadcasts them via the Channels channel
   layer to the already-existing `dashboard_live` group.

2. Adds a new handler method `quote_stream` to `DashboardConsumer`
   that forwards quote-stream events to connected browsers, plus
   a helper `push_stream_update()` used by the Binance worker.

3. Patches `base.html` with a small WebSocket client that opens
   `ws(s)://host/ws/dashboard/`, handles `quote_stream` frames,
   and updates headband + watchlist DOM instantly. Falls back to
   the 15s poller automatically if the socket closes.

4. Adds a Render worker entry example to a new `render.worker.md`
   file (Render-specific instructions, since you asked before).

5. Adds `websockets>=12` to requirements.txt.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent
if not (ROOT / "manage.py").exists():
    print("ERROR: run this script from the directory containing manage.py")
    sys.exit(1)

def write(rel: str, content: str, *, overwrite: bool = True):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and not overwrite:
        print(f"  skip: {rel}"); return
    p.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
    print(f"  wrote: {rel}")

def patch(rel: str, old: str, new: str):
    p = ROOT / rel
    if not p.exists(): print(f"  MISSING: {rel}"); return
    txt = p.read_text(encoding="utf-8")
    if new.strip()[:60] in txt:
        print(f"  already patched: {rel}"); return
    if old not in txt:
        print(f"  anchor not found: {rel}"); return
    p.write_text(txt.replace(old, new, 1), encoding="utf-8")
    print(f"  patched: {rel}")

print("━" * 60)
print(" SAURON VISION — UPGRADE PASS 3 (real-time crypto stream)")
print("━" * 60)

# =================================================================
# STEP 1 — Binance WebSocket streamer management command
# =================================================================
print("\n[1/5] Writing stream_binance management command …")

write("market_data/management/__init__.py", "", overwrite=False)
write("market_data/management/commands/__init__.py", "", overwrite=False)

write("market_data/management/commands/stream_binance.py", '''
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
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        try:
            inst = Instrument.objects.filter(symbol__iexact=symbol).first()
            if not inst:
                return
            LiveQuote.objects.update_or_create(
                instrument=inst,
                defaults=dict(
                    last=Decimal(str(last)),
                    change_pct=Decimal(str(round(change_pct, 4))),
                    bid=Decimal(str(bid)) if bid else None,
                    ask=Decimal(str(ask)) if ask else None,
                    volume=int(volume) if volume else 0,
                    source="binance_ws",
                ),
            )
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
''')

# =================================================================
# STEP 2 — Extend DashboardConsumer with quote_stream handler
# =================================================================
print("\n[2/5] Extending DashboardConsumer with quote_stream handler …")

patch("dashboard/consumers.py",
      '    async def strategy_update(self, event):',
      '''    async def quote_stream(self, event):
        """Push real-time quote tick from Binance streamer."""
        await self.send(text_data=json.dumps({
            "type": "quote_stream",
            "data": event["data"],
        }))

    async def strategy_update(self, event):''')

# Add a convenience helper at the end of the file
patch("dashboard/consumers.py",
      'def push_news_notification(article_data):',
      '''def push_stream_update(symbol, last, change_pct, bid=0, ask=0, volume=0):
    """Broadcast a single live tick to all connected browsers."""
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    layer = get_channel_layer()
    if not layer:
        return
    async_to_sync(layer.group_send)(
        "dashboard_live",
        {"type": "quote_stream",
         "data": {"symbol": symbol, "last": last, "change_pct": change_pct,
                  "bid": bid, "ask": ask, "volume": volume}},
    )


def push_news_notification(article_data):''')

# =================================================================
# STEP 3 — Browser-side WebSocket client in base.html
# =================================================================
print("\n[3/5] Injecting WebSocket client into base.html …")

WS_CLIENT = r'''
<script>
/* UPGRADE-3: WebSocket live ticks.
   Opens a persistent socket to /ws/dashboard/ and updates the headband
   + watchlist DOM in-place. Gracefully degrades to the 15s poller if
   the socket can't connect or drops permanently. */
(function(){
  if (window.__sauronWS) return;
  window.__sauronWS = true;

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${location.host}/ws/dashboard/`;
  let ws = null, retries = 0, alive = false;

  function applyTick(d) {
    if (!d || !d.symbol) return;
    const sym = (d.symbol || "").toUpperCase();
    const pct = +d.change_pct || 0;
    const last = +d.last || 0;

    // 1. Dashboard headband
    document.querySelectorAll(`.dh-item[data-symbol="${sym}"]`).forEach(el => {
      const val = el.querySelector('.dh-val');
      const chg = el.querySelector('.dh-chg');
      const dot = el.querySelector('.dh-dot');
      if (val) { val.textContent = last.toFixed(2); flash(val); }
      if (chg) {
        const sign = pct >= 0 ? '+' : '';
        chg.textContent = `${sign}${pct.toFixed(2)}%`;
        chg.className = 'dh-chg ' + (pct >= 0 ? 'up' : 'down');
      }
      if (dot) dot.className = 'dh-dot ' + (pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat');
    });

    // 2. Watchlist rail
    document.querySelectorAll('.wl-item').forEach(el => {
      const symEl = el.querySelector('.wl-sym');
      if (!symEl || symEl.textContent.trim().toUpperCase() !== sym) return;
      const lastEl = el.querySelector('.wl-last');
      const chgEl = el.querySelector('.wl-chg');
      if (lastEl) { lastEl.textContent = last.toFixed(4); flash(lastEl); }
      if (chgEl) {
        const sign = pct >= 0 ? '+' : '';
        chgEl.textContent = `${sign}${pct.toFixed(2)}%`;
        chgEl.className = 'wl-chg ' + (pct >= 0 ? 'up' : 'down');
      }
    });

    // 3. Ticker bar price items
    document.querySelectorAll('.ticker-item').forEach(el => {
      const s = el.querySelector('.t-sym');
      if (!s || s.textContent.trim().toUpperCase() !== sym) return;
      const p = el.querySelector('.t-price');
      const c = el.querySelector('.t-change');
      if (p) p.textContent = last.toFixed(2);
      if (c) {
        c.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
        c.className = 't-change ' + (pct >= 0 ? 'up' : 'down');
      }
    });
  }

  function flash(el) {
    el.style.transition = 'color .1s, text-shadow .1s';
    el.style.textShadow = '0 0 8px currentColor';
    setTimeout(() => { el.style.textShadow = ''; }, 250);
  }

  function connect() {
    try { ws = new WebSocket(url); } catch(e) { scheduleReconnect(); return; }
    ws.onopen = () => { retries = 0; alive = true;
      console.log('[sauron] live WS connected'); };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'quote_stream' || msg.type === 'quote') applyTick(msg.data);
      } catch(e) {}
    };
    ws.onclose = () => { alive = false; scheduleReconnect(); };
    ws.onerror = () => { try { ws.close(); } catch(e){} };
  }

  function scheduleReconnect() {
    retries = Math.min(retries + 1, 6);
    const delay = Math.min(30000, 1000 * Math.pow(2, retries)) + Math.random() * 500;
    setTimeout(connect, delay);
  }

  connect();
})();
</script>
'''

p = ROOT / "templates/base.html"
txt = p.read_text(encoding="utf-8")
if "UPGRADE-3: WebSocket live ticks" in txt:
    print("  WS client already present")
else:
    # Place it right after the UPGRADE-2 polling script — we find the closing
    # "})();" of that block and append after the enclosing </script>.
    marker = "/* UPGRADE-2: Live metrics poll every 15s */"
    if marker in txt:
        # Find the </script> that follows the marker
        idx = txt.find(marker)
        close = txt.find("</script>", idx)
        if close > 0:
            close += len("</script>")
            txt = txt[:close] + "\n\n" + WS_CLIENT.strip() + "\n" + txt[close:]
            p.write_text(txt, encoding="utf-8")
            print("  injected WS client")
        else:
            print("  could not find closing </script> after UPGRADE-2 marker")
    else:
        # Fallback: append before </body>
        if "</body>" in txt:
            txt = txt.replace("</body>", WS_CLIENT.strip() + "\n</body>", 1)
            p.write_text(txt, encoding="utf-8")
            print("  injected WS client (fallback before </body>)")

# =================================================================
# STEP 4 — Requirements
# =================================================================
print("\n[4/5] Ensuring 'websockets' in requirements.txt …")
req = ROOT / "requirements.txt"
if req.exists():
    txt = req.read_text(encoding="utf-8")
    if "websockets" not in txt:
        req.write_text(txt.rstrip() + "\nwebsockets>=12\n", encoding="utf-8")
        print("  added websockets>=12")
    else:
        print("  websockets already present")

# =================================================================
# STEP 5 — Render worker deployment note
# =================================================================
print("\n[5/5] Writing Render worker deployment note …")

write("render.worker.md", '''
    # Running the Binance streamer on Render

    The `stream_binance` command is a long-lived asyncio process.
    On Render, add it as a **Background Worker** service in
    `render.yaml`:

    ```yaml
    services:
      # ... your existing web service ...

      - type: worker
        name: sauron-binance-stream
        env: python
        plan: starter          # $7/mo, needed so it doesn't sleep
        buildCommand: "pip install -r requirements.txt"
        startCommand: "python manage.py stream_binance"
        envVars:
          - key: DJANGO_SETTINGS_MODULE
            value: config.settings
          - key: DATABASE_URL
            fromDatabase:
              name: sauron-postgres
              property: connectionString
          - key: REDIS_URL
            fromService:
              type: keyvalue
              name: sauron-redis
              property: connectionString
          - key: SECRET_KEY
            sync: false          # pin it; don't regenerate
    ```

    ## Requirements
    1. **Redis (Key Value)** add-on — required as the Channels layer
       so the streamer can broadcast to browsers connected to the web
       service. The web service and this worker must share the same
       Redis via `CHANNEL_LAYERS` (your settings.py already reads
       `REDIS_URL`).
    2. **Shared `SECRET_KEY`** — must match the web service or
       encrypted fields (Binance keys in bot_program) become unreadable.
    3. **websockets package** — added to requirements.txt automatically.

    ## Local dev
    Open a second terminal:
    ```
    python manage.py stream_binance
    ```
    You'll see `connecting to N stream(s): BTCUSDT, ETHUSDT, …` and
    prices update live in your browser as soon as you refresh.

    ## What symbols are streamed
    Every `Instrument` row with `asset_class="crypto"` and
    `is_active=True`. The worker refreshes this list every 60 seconds,
    so when you flag a new crypto in the Instruments page it joins the
    stream automatically without a restart.

    ## Custom symbol list
    ```
    python manage.py stream_binance --symbols BTCUSDT ETHUSDT SOLUSDT
    ```

    ## Limits
    - Binance public streams are free and unlimited for public market
      data. No API key needed.
    - For futures (liquidations, mark price, funding), replace
      `wss://stream.binance.com:9443` with
      `wss://fstream.binance.com` and subscribe to `<symbol>@markPrice`,
      `<symbol>@forceOrder`, etc. Tell me and I'll ship pass 4 for that.
    - Non-crypto assets (stocks, forex, commodities) need a different
      provider — Polygon, Finnhub, OANDA, Twelve Data. The same
      Channels pipeline will work for them; only the streamer worker
      changes.
''')

print("\n" + "━" * 60)
print(" ✓ UPGRADE PASS 3 COMPLETE")
print("━" * 60)
print("""
How to run:

  LOCAL:
    pip install websockets
    # Terminal 1:
    python manage.py runserver
    # Terminal 2:
    python manage.py stream_binance

  You should see in terminal 2:
    connecting to N stream(s): BTCUSDT, ETHUSDT, ...

  Open your browser and watch the headband prices tick in real time
  (sub-second). Open DevTools → Network → WS and you'll see the
  websocket frames flowing through /ws/dashboard/.

  RENDER:
    1. Add a "worker" service in render.yaml with startCommand
       `python manage.py stream_binance`. Template in render.worker.md.
    2. Make sure you have a Key Value (Redis) instance wired up as
       CHANNEL_LAYERS / REDIS_URL — the web service and the worker
       MUST share it so broadcasts reach connected browsers.
    3. git push → Render redeploys both services.

WHAT'S STREAMED:
  Every Instrument with asset_class="crypto" and is_active=True.
  Binance `@ticker` stream → price, 24h%, bid, ask, volume.
  Refreshed dynamically every 60s, so adding a new crypto to your
  instruments table joins the stream without a restart.

WHAT'S NEXT (pass 4 ideas if you want):
  • Stocks/forex streamers via Finnhub/OANDA with the same pipeline
  • Binance futures: liquidations, funding, open interest
  • Order book depth stream for the liquidity heatmap in the bot
""")
