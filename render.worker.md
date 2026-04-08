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
