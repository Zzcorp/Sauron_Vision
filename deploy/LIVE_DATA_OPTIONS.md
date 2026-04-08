# Live Market Data — your options, ranked

The honest answer to "what's the best provider for live prices,
paid or not, easy to set up and good quality?"

## TL;DR per asset class

| Asset class | Best free | Best paid | Already wired in Sauron? |
|-------------|-----------|-----------|--------------------------|
| **Crypto spot/futures** | **Binance public WS** (no key, unlimited) | Binance Pro / Coinbase Advanced | ✅ stream_binance, stream_binance_futures, stream_binance_depth |
| **US stocks** | **Finnhub** (~50 symbols, ~1s, free key) | **Polygon.io** ($29/mo Starter, real-time) | ✅ stream_finnhub |
| **Forex** | **Finnhub** (majors only) or **OANDA demo** (broker-grade, never expires) | **OANDA live** (when you actually trade) or **TraderMade** | ✅ stream_finnhub (forex flag), stream_oanda |
| **Indices/futures** | **TradingView** (unofficial) | **Databento** ($/mo per stream) | ⚠ via Yahoo polling only |
| **Commodities** | **Yahoo Finance** (15-min delay) | **Barchart** or **Polygon** | ⚠ via Yahoo polling only |
| **Macro / FRED** | **FRED API** (free, instant) | n/a | ✅ via existing fred_adapter |

---

## Recommended setup (the one I'd actually use)

For "me and friends" use, free everything works fine and is genuinely
real-time for crypto:

```
1. stream_binance              ← crypto spot ticks         (no key)
2. stream_binance_futures      ← liquidations + funding   (no key)
3. stream_binance_depth        ← L2 order book → bot      (no key)
4. stream_finnhub              ← US stocks + forex        (free key)
```

Total monthly cost: **$0**. Latency: <1s for crypto, ~1s for stocks/fx.
Coverage: every meaningful asset on the dashboard.

The only thing you don't get on free tiers is:
- **Real-time futures** (CME, ES, NQ): need Polygon or Databento
- **More than 50 symbols** on Finnhub: need their Basic plan ($49/mo)
  or split across multiple keys
- **Real-time forex through your actual broker**: get OANDA live keys
  when you decide to trade forex with money

## Detailed comparison

### Crypto — Binance public streams
**Free, no signup, sub-second latency, unlimited connections.** This
is genuinely the best option for crypto live data, paid or not.
Binance's public WebSocket streams (`wss://stream.binance.com:9443`)
require zero authentication and have no documented rate limit for
market data. You can stream 100+ symbols on a single connection
using their combined-stream syntax. Already wired up in
`stream_binance`, `stream_binance_futures`, and `stream_binance_depth`.

### US stocks — Finnhub vs Polygon vs Alpaca
- **Finnhub free** — ~50 symbols max per WebSocket, ~1s latency,
  WebSocket-based, zero cost. Holes during pre-market and after-hours.
  Perfect for a personal dashboard. **Already wired.**
- **Polygon.io Starter** — $29/mo, full real-time NBBO, every trade,
  every quote. Used by funds. Best paid option for stocks.
- **Alpaca free** — IEX-only feed (≈3% of US volume), real-time but
  thin. Free if you also want their broker. Better for paper trading
  than dashboard display.
- **IEX Cloud** — shut down November 2024. Don't use.

Recommendation: **stay on Finnhub free until you outgrow it.** You
won't outgrow it for personal use.

### Forex — Finnhub vs OANDA vs Twelve Data
- **Finnhub free** — major pairs only (EUR/USD, GBP/USD, etc.),
  ~1s latency, same WebSocket as stocks. **Use this if you don't
  already have an OANDA account.**
- **OANDA demo** — broker-grade tick feed, every price update,
  tighter than Finnhub. Free demo account never expires. Different
  protocol (HTTP chunked streaming). Best free option if you're
  willing to do the OANDA signup.
- **Twelve Data** — paid only ($29/mo) but covers crypto, stocks,
  forex, and indices in one API. Worth it if you want one provider.

Recommendation: **Finnhub for simplicity, OANDA when you start
trading forex for real.** Both are wired in Sauron via
`stream_finnhub` and `stream_oanda` respectively.

### Indices and futures (SPX, NDX, ES, NQ, VIX)
This is the hard one.
- **CBOE / CME require paid licensing** for real-time. There's no
  free real-time SPX feed that's legal.
- **Yahoo Finance** has 15-minute delayed indices, free, easy. Your
  existing `yfinance_adapter` handles this. Good enough for a
  dashboard, useless for trading.
- **TradingView** has unofficial WebSocket feeds people scrape, but
  it's against their TOS and your access can be revoked.
- **Databento** ($199/mo and up) is the proper paid solution.
- **Polygon.io** offers real-time CME futures on their Stocks
  Advanced plan ($199/mo).

Recommendation: **stick with delayed Yahoo for indices on the
dashboard, don't trade them through Sauron.** If you really want
real-time SPX, the cheapest legal path is Polygon Indices ($79/mo
add-on) or Databento.

### Commodities (Gold, Silver, Oil)
- **Yahoo Finance** delayed quotes, free, already wired
  (`commodities_api.py`)
- **Metals-API** / **OilPriceAPI** — both have free tiers (60-100
  requests/day), already wired (`commodities_api.py`,
  `oil_price_api.py`)
- **TradingView Lightweight** unofficial feeds — TOS violation
- **Barchart** — paid, the institutional standard

Recommendation: **the existing Yahoo + Metals-API polling is fine.**
Commodities don't move fast enough to need WebSocket.

### Macro data (FRED, ECB, BoE)
- **FRED API** — free, instant, no rate limit, gold standard. You
  already have it via `fred_adapter.py`. Don't change anything.

## Easy setup checklist

For the recommended free setup, in your `.env`:
```
# Binance — no keys needed for streaming, only for trading
# Optional: BINANCE_TESTNET=1 (testnet for the bot)

# Finnhub — free key from https://finnhub.io
FINNHUB_API_KEY=your_finnhub_key_here

# FRED — free key from https://fred.stlouisfed.org/docs/api/api_key.html
FRED_API_KEY=your_fred_key_here
```

Then start the streamers:
```bash
python manage.py stream_binance &
python manage.py stream_binance_futures &
python manage.py stream_binance_depth &
python manage.py stream_finnhub &
```

Or via Docker Compose, all five start automatically:
```bash
docker compose -f deploy/docker-compose.yml --profile finnhub up -d
```

## When to upgrade to paid

| If you... | Upgrade to |
|-----------|-----------|
| Need >50 stock symbols live | Finnhub Basic ($49/mo) or Polygon Starter ($29/mo) |
| Want every US stock trade | Polygon Stocks Advanced ($199/mo) |
| Trade forex with real money | OANDA live (free, just live API key) |
| Want real-time CME futures | Polygon Indices add-on ($79/mo) or Databento ($199+/mo) |
| Want one API for everything | Twelve Data Pro ($79/mo) |

For the "me and friends" use case described in your project,
**none of these are necessary.** Free Binance + free Finnhub +
free FRED gives you a genuinely high-quality dashboard.
