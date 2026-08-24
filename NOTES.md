# Sauron Vision — operational notes

Consolidated caveats across all upgrade passes. Read once before
arming anything that costs real money.

## Live data

- **Binance public WebSockets are free and unauthenticated** for
  market data. No API key needed for `stream_binance`,
  `stream_binance_futures`, or `stream_binance_depth`. You only
  need API keys when the bot actually places orders.
- **Finnhub free tier** is ~1s latency with holes during US market
  close and a soft limit around 50 symbol subscriptions per socket.
  Good enough for a dashboard; not for an algo-trading stock bot.
  For serious use: Polygon.io or Alpaca (both paid, both real-time).
- **OANDA demo accounts never expire.** The demo and live feeds
  are the same data — you can build and test forex logic for free
  indefinitely. Switch to live by setting `OANDA_ENV=live` and
  using a funded-account API key.
- **Stream disconnects are normal.** All streamers auto-reconnect
  with exponential backoff (max 60s). If you see repeated
  disconnects from Binance, check your VPS's outbound IP isn't
  rate-limited — Binance throttles connections per IP globally.

## Storage growth

- **LiquidationEvent** is the fastest-growing table. BTCUSDT alone
  produces thousands of rows per day during volatile periods.
  The nightly `cleanup_liquidations` task (pass 5) keeps the last
  30 days by default; override with `RETAIN_LIQUIDATIONS_DAYS` env.
- **OrderBookSnapshot** is bounded by the streamer itself: max 2000
  rows per symbol via opportunistic pruning on ~1% of writes, plus
  the nightly `cleanup_orderbook` task as a safety net.
- **FundingRate** is throttled to one row per symbol every 30s by
  the streamer, so even running 24/7 it produces ~2880 rows/day
  per symbol. Retention default: 60 days.
- **PriceData intraday bars** (1m/5m/15m/1h/4h) are pruned to the
  last 90 days by `cleanup_price_data`. Daily and weekly bars are
  preserved regardless — don't delete your backtest data.

## Channels / Redis

- **All streamers and the web service MUST share the same Redis
  instance** as the Channels layer. This is non-negotiable: the
  streamers broadcast into a Redis pub/sub channel, the web
  service's Daphne process subscribes to that channel to relay
  events to connected browser WebSockets. Point them at different
  Redis instances and browser updates simply don't arrive.
- `REDIS_URL` env var controls this (your `settings.py` reads it).

## Security

- **SECRET_KEY must be pinned and stable.** Binance API keys and
  any future encrypted fields use Fernet derived from SECRET_KEY.
  If it changes, those fields become unreadable. On Render: set
  it explicitly with `sync: false`, not `generateValue: true`.
- **Binance API keys should have withdrawals DISABLED.** The bot
  only needs trading + read permissions. Enable IP whitelist if
  you're running from a static IP.
- **Start on testnet.** `BinanceAccount.testnet=True` is the
  default. The bot arming flow in pass 1 requires a PIN to flip
  to LIVE mode — don't bypass it, and don't share the PIN.
- **`set_default_pin.py` is gone.** It set PIN "0000" on every user
  lacking one — a Render-era convenience that, run against production,
  would trivialize the trading-PIN gate on every account at once. PINs
  are set per user from the profile page (`/profile/?modal=pin`); if you
  ever ran the script, change every 0000 PIN before exposing the site.

## Bot behaviour

- **PAPER mode by default.** `BotConfig.mode="paper"` and
  `BotConfig.enabled=False` on creation. Every flip to live
  requires the PIN. Toggles happen only from the Bot Program UI.
- **Daily loss cutoff** — the risk manager halts new entries when
  24h realized P&L breaches `max_daily_loss_pct`. The bot does NOT
  force-close existing positions, only stops opening new ones.
- **Futures mode** (pass 5): the bot sets leverage and margin mode
  once per symbol via `ensure_config()` on the first order. If you
  change leverage in BotConfig, restart the bot for the new value
  to take effect — the client caches "already set" to avoid
  hitting the API on every tick.
- **Composite strategy is a starting point, not alpha.** The point
  of the scenarios / backtester is to tune weights and thresholds
  per symbol BEFORE going live. Run each configuration through
  backtest → paper → live at small size → live at full size.
- **Impressively lucrative trading** cannot be promised by any
  framework, and shouldn't be expected from default weights. What
  the code gives you is a disciplined, auditable pipeline with
  real risk management — that's necessary but not sufficient.

## Cost reality

- **Render full deployment** with all 5 streamers = 5 × $7 workers
  + web + celery worker + celery beat + Redis + Postgres ≈ $60/mo
  minimum.
- **Hetzner VPS equivalent**: CX22 at €4.51/mo runs everything on
  one box. 13× cheaper for the same behaviour. Tradeoff: you
  manage OS updates, backups, and uptime yourself.
- **Render free tier won't work** — web services sleep, celery
  workers aren't available, and the streamers need always-on.

## What's NOT here

- **Real trading of stocks or forex** — the bot is crypto-only
  (spot + futures via Binance). Finnhub/OANDA streams only feed
  the dashboard, not the bot.
- **Tax reporting / cost basis** — not modelled. Use a dedicated
  tool (Koinly, CoinTracker) if you trade enough to care.
- **Multi-user isolation** — all users on the same instance share
  the same data (instruments, news, quotes). Only BotConfig,
  BotTrade, and Binance credentials are per-user. This is fine
  for the "me + friends" use case you described, not for a SaaS.
- **Guarantees of anything.** This is code that works as designed;
  it is not investment advice, and nothing in it should be
  interpreted as a recommendation to trade. You know this.
