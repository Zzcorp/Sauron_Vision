# 🔴 SAURON VISION

**Trading Intelligence Platform — Stocks · Commodities · Forex**

## Local Development (Quick Start)

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Edit .env with your API keys
# (SQLite + in-memory cache used automatically if no PostgreSQL/Redis)

# 4. Run migrations
python manage.py migrate

# 5. Create admin user
python manage.py createsuperuser

# 6. Seed initial instruments
python manage.py seed_instruments

# 7. Start development server
python manage.py runserver

# 8. (Optional) Start Celery workers in separate terminals
celery -A config worker -l info -Q fast,default -c 4
celery -A config worker -l info -Q slow,ai -c 2
celery -A config beat -l info
```

## Deploy to Render.com

### Option A: One-Click Blueprint (Recommended)

1. Push this project to a GitHub or GitLab repository
2. Go to [render.com/blueprints](https://render.com/blueprints)
3. Click **New Blueprint Instance**
4. Select your repository — Render reads `render.yaml` automatically
5. Give it a name and click **Apply**
6. Render creates all 5 services:
   - `sauron-vision-web` (Django)
   - `sauron-vision-celery-fast` (Tier 1-2 worker)
   - `sauron-vision-celery-slow` (Tier 3-6 + AI worker)
   - `sauron-vision-celery-beat` (Scheduler)
   - `sauron-vision-redis` (Broker + cache)
   - `sauron-vision-db` (PostgreSQL)
7. Once deployed, add your API keys in Render Dashboard → Environment

### Option B: Manual Setup

1. **Create a PostgreSQL database** on Render
2. **Create a Redis instance** on Render
3. **Create a Web Service**:
   - Runtime: Python
   - Build command: `./build.sh`
   - Start command: `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
   - Add env vars: `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS=.onrender.com`
4. **Create Background Workers** for Celery fast, slow, and beat
5. Add API keys as environment variables

### Required Environment Variables on Render

Set these in the Render Dashboard under each service's Environment tab:

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API for AI agents |
| `ALPHA_VANTAGE_API_KEY` | Yes | Primary market data |
| `TWELVE_DATA_API_KEY` | Recommended | Multi-asset data |
| `FINNHUB_API_KEY` | Recommended | News + sentiment |
| `FMP_API_KEY` | Optional | Fundamentals |
| `FRED_API_KEY` | Recommended | Macro data (free) |
| `TELEGRAM_BOT_TOKEN` | Optional | Alert notifications |
| `TELEGRAM_CHAT_ID` | Optional | Alert notifications |

### Render Pricing Estimate

| Service | Plan | Cost/month |
|---|---|---|
| Web Service | Starter | $7 |
| Celery Fast Worker | Starter | $7 |
| Celery Slow Worker | Starter | $7 |
| Celery Beat | Starter | $7 |
| PostgreSQL | Starter | $7 |
| Redis | Starter | $0 (free tier) |
| **Total** | | **~$35/month** |

## Architecture

- **Django** — Web framework & ORM
- **Celery** — Task scheduling (6-tier system from 1min to weekly)
- **PostgreSQL** — Primary database (Render managed)
- **Redis** — Cache & message broker (Render Key Value)
- **Claude API** — AI agents (news analysis, strategy, weekly review)
- **React** — Frontend dashboard (dark hacker aesthetic)

## API Endpoints

- `GET /api/instruments/` — List tracked instruments
- `GET /api/quotes/` — Live quotes
- `GET /api/signals/active/` — Active trading signals
- `GET /api/strategies/` — Trading strategies
- `GET /api/portfolio/` — Portfolio overview
- `GET /api/ai/briefing/` — Latest AI briefing
- `WS /ws/dashboard/` — Real-time WebSocket updates

---
*Built with the all-seeing eye of Sauron. Not financial advice.*
