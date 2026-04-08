# Single-VPS deployment

Two options: Docker Compose (simplest) or systemd (more control,
no Docker overhead).

## Option A — Docker Compose (recommended)

Any Linux box with Docker + Compose v2. A Hetzner CX22 (€4.51/mo,
2 vCPU, 4 GB) is enough to run web + celery + all five streamers.

```bash
# 1. Install docker (once)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# log out and back in

# 2. Clone your repo
git clone https://github.com/YOU/sauron_vision.git
cd sauron_vision

# 3. Create .env
cp .env.example .env
nano .env
# fill in at minimum:
#   SECRET_KEY=...               (long random string; MUST be pinned)
#   POSTGRES_PASSWORD=...
#   ALLOWED_HOSTS=your.domain.com
# optional for streamers:
#   FINNHUB_API_KEY=...
#   OANDA_API_KEY=... OANDA_ACCOUNT_ID=... OANDA_ENV=practice

# 4. Bring it up (crypto-only)
docker compose -f deploy/docker-compose.yml up -d --build

# Or with stocks + forex streamers as well
docker compose -f deploy/docker-compose.yml \
    --profile finnhub --profile oanda up -d --build

# 5. First-time setup
docker compose -f deploy/docker-compose.yml exec web python manage.py createsuperuser
docker compose -f deploy/docker-compose.yml exec web python set_default_pin.py

# 6. Follow logs
docker compose -f deploy/docker-compose.yml logs -f stream-binance
```

Put Caddy / nginx / Cloudflare Tunnel in front for HTTPS. Caddy
config example (sudo apt install caddy, /etc/caddy/Caddyfile):
```
your.domain.com {
    reverse_proxy localhost:8000
}
```

## Option B — systemd (no Docker)

```bash
# 1. System user and venv
sudo useradd -r -m -d /opt/sauron -s /bin/bash sauron
sudo -u sauron bash
cd ~
git clone https://github.com/YOU/sauron_vision.git
python3 -m venv venv
source venv/bin/activate
pip install -r sauron_vision/requirements.txt
cd sauron_vision
cp .env.example .env && nano .env
python manage.py migrate && python manage.py collectstatic --noinput
exit

# 2. Install unit files
sudo cp /opt/sauron/sauron_vision/deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload

# 3. Core services
sudo systemctl enable --now sauron-web sauron-celery-worker sauron-celery-beat

# 4. Streamers (one enable line per streamer)
sudo systemctl enable --now sauron-streamer@binance
sudo systemctl enable --now sauron-streamer@binance_futures
sudo systemctl enable --now sauron-streamer@binance_depth
sudo systemctl enable --now sauron-streamer@finnhub
sudo systemctl enable --now sauron-streamer@oanda

# 5. Check
systemctl status sauron-streamer@binance
journalctl -u sauron-streamer@binance -f
```

The `sauron-streamer@.service` template is parameterised: the bit
after the `@` is passed as `%i` and becomes the command suffix.
`sauron-streamer@binance` runs `python manage.py stream_binance`,
`sauron-streamer@binance_futures` runs `stream_binance_futures`,
etc. Add new streamers with just an enable command — no new unit
file needed.

## Resource sizing

- **CX22 (€4.51/mo, 2c/4G)** — runs everything except finnhub+oanda
  comfortably. ~20% average CPU with all three Binance streamers.
- **CX32 (€6.86/mo, 4c/8G)** — comfortable with all five streamers
  + Celery under full load.
- **Redis memory** — the Channels layer uses trivial amounts (<50MB).
- **Postgres disk** — the biggest hog. LiquidationEvent rows for
  top crypto symbols = ~200MB/month without retention. The nightly
  cleanup task from pass 5 keeps 30 days → ~200MB steady state.

## Health checks

```bash
# Are all containers up?
docker compose -f deploy/docker-compose.yml ps

# Is the streamer actually receiving ticks?
docker compose -f deploy/docker-compose.yml logs --tail=20 stream-binance
# should show: "connecting to N stream(s): BTCUSDT, ETHUSDT, ..."

# Are liquidations being stored?
docker compose -f deploy/docker-compose.yml exec web python manage.py shell -c \
    "from market_data.models import LiquidationEvent; print(LiquidationEvent.objects.count())"
```
