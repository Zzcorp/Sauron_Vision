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
