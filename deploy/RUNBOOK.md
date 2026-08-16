# Deploying Sauron Vision

One box, one compose file. Follow this top to bottom — every step is here
because skipping it breaks something later, and several steps exist because
skipping them breaks something *silently*.

**Target:** a Hetzner CX32 (4 vCPU / 8 GB, ~€8.50/mo) or equivalent. The 4 GB
CX22 works but is tight once backtests and the brain run alongside Postgres
and Redis.

> **Every `docker compose` command below starts with `--env-file .env`.** This
> is not decoration. Compose interpolates `${VAR}` from the *project*
> directory, which with `-f deploy/docker-compose.yml` is `deploy/` — not the
> repo root where your `.env` lives. Leave the flag off and the very first
> command aborts with `DB_PASSWORD must be set in .env` while `DB_PASSWORD` is
> plainly set in `.env`. Every subcommand re-interpolates, so `ps`, `logs` and
> `exec` need it too.

---

## 1. The box

```bash
# As root, on a fresh Debian 12 / Ubuntu 24.04:
adduser sauron && usermod -aG sudo sauron
```

Copy your SSH key to the new user, then **disable password login** in
`/etc/ssh/sshd_config` (`PasswordAuthentication no`) and `systemctl restart ssh`.

```bash
apt update && apt install -y docker.io docker-compose-v2 ufw fail2ban rclone
usermod -aG docker sauron
systemctl enable --now docker fail2ban

ufw default deny incoming && ufw default allow outgoing
ufw allow OpenSSH && ufw allow 80 && ufw allow 443
ufw enable

# Unattended security updates
apt install -y unattended-upgrades && dpkg-reconfigure -plow unattended-upgrades
```

## 2. DNS

Point an `A` record for your domain at the box's IP **before** starting the
stack — Caddy requests a certificate for that exact name on boot and cannot
succeed until DNS resolves.

Confirm it has propagated before you continue:

```bash
dig +short your-domain.com     # must print this box's IP
```

## 3. Code and configuration

```bash
su - sauron
git clone https://github.com/Zzcorp/Sauron_Vision.git
cd Sauron_Vision/SAURON_V/sauron_vision

cp .env.production.example .env
```

Fill in the REQUIRED block. Generate the two keys:

```bash
python3 -c "import secrets;print(secrets.token_urlsafe(64))"                       # SECRET_KEY
python3 -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"  # FERNET_KEY
```

> **Set `FERNET_KEY` now, before you ever store broker credentials, and keep it
> safe.** It encrypts them at rest. It is separate from `SECRET_KEY` on purpose:
> rotating that — or rebuilding on a new host — would otherwise make every
> stored broker credential permanently undecryptable, and the bots would
> silently fall back to paper trading.

`DOMAIN` and `ALLOWED_HOSTS` are read independently. Set **both** to your real
hostname; changing only `DOMAIN` gets you a valid certificate in front of a
site that answers every request with a bare `400`.

Then check you left no placeholders behind, and lock the file down:

```bash
grep -n 'example\.com' .env     # must print nothing
chmod 600 .env
```

## 4. Start

```bash
docker compose --env-file .env -f deploy/docker-compose.yml up -d --build
docker compose --env-file .env -f deploy/docker-compose.yml logs -f migrate   # should exit 0
```

The `migrate` service runs migrations, instrument seeding and component
seeding once; everything else waits for it to finish, so there is no start-up
race. Static files are baked into the image at build time.

Create your login:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml exec web \
  python manage.py createsuperuser
```

Open `https://your-domain/`. You should get the landing wall with a valid
certificate. Two checks the eyeball test cannot make for you:

```bash
# Static must be 200. The landing wall is inline-styled and looks fine even
# when static is broken -- but every page after login would be raw HTML.
curl -sI https://your-domain/static/css/sauron.css | head -1

# If the padlock is green but pages return a bare 400, ALLOWED_HOSTS is wrong:
docker compose --env-file .env -f deploy/docker-compose.yml logs web | grep DisallowedHost
```

Then set your **trading PIN**: Profile → Change PIN. Leave "current PIN" blank
on first set; 4–8 digits. Nothing can be armed live without it, and no PIN
exists until you create one.

## 5. Turn the platform on

**Everything ships OFF, including the master switch.** This is deliberate — a
freshly deployed trading platform should not start acting on its own — but it
means that until you do this, beat fires every scheduled task, both workers
consume them, and every one returns `skipped`. The site looks completely
healthy while doing nothing at all.

Log in, open `/admin-dashboard/`, press **START PLATFORM**, then enable:

- `scraper_live_quotes`, `scraper_crypto`, `scraper_forex`,
  `scraper_commodities`, `scraper_indices`
- `pipeline_indicators`, `pipeline_signals`, `pipeline_asset_bots`, `pipeline_exposure`

Leave OFF for now: `actuator_mode_live`, `meta_allocator_mode_live`,
`feature_ai_pretrade_gate`, and every `agent_*`.

> Do **not** use "Start All" on the *system* category — it flips
> `actuator_mode_live` alongside the master switch.

Confirm it took:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml logs --tail=50 worker-fast
# the "[GATE] Platform master switch OFF" stream must stop
```

## 6. Create your first bots

The fastest path is the seeded paper fleet — six configs (FX majors and
crosses, metals, energy, softs, megacap stocks), all paper:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml exec web \
  python manage.py seed_bots --activate
```

**No broker account is needed for paper trading.** Bars and marks arrive
keylessly for every asset class (Binance public for crypto, yfinance for the
rest) within ~10 minutes of enabling the bots and the scrapers from step 5.
Do **not** use `backfill_bars` for non-crypto symbols — it is Binance-only.

Broker credentials are for **live trading** and for real-time marks that beat
the delayed public feeds:

| Asset class      | Broker  | Notes                                        |
| ---------------- | ------- | -------------------------------------------- |
| stock, etf, index| Alpaca  | paper keys work                              |
| forex            | OANDA   | practice keys work (streamer uses them too)  |
| crypto           | Binance | live-endpoint spot key (read-only is enough) |
| options, cfd     | IBKR    | must be reachable from inside the container  |

> IBKR: `127.0.0.1:7497` means *the container itself*. Use
> `host.docker.internal` (add
> `extra_hosts: ["host.docker.internal:host-gateway"]` to the service) or the
> box's LAN address.

Symbols must match the seeded `Instrument.symbol` spelling exactly — `EURUSD`
not `EUR_USD`, `BTCUSD` not `BTCUSDT`, `GOOGL` not `GOOG`. An unrecognised
symbol produces zero bars forever *and* is routed to Binance as crypto.

Seeding instruments does **not** put them in the scan universe. The pipeline
scans watchlisted instruments plus every enabled bot's symbols — so until you
star instruments or create a bot, the scan correctly processes nothing.

## 7. Verify before trusting it

Go to **`/health/`** (as a staff user). On a virgin box the honest expected
state is *not* all-green:

| Check                         | Expected on day one                    |
| ----------------------------- | -------------------------------------- |
| Beat schedule                 | green — every task resolves            |
| Platform switches             | green once step 5 is done              |
| Bot bars, Bot activity        | amber "not set up yet" until step 6    |
| Quote feeds, Signal flow      | amber until streamers and the scan run |

```bash
docker compose --env-file .env -f deploy/docker-compose.yml ps
```

Every service `running`, nothing in `Restarting`. `web` should read `healthy`.

## 8. Backups

The `backup` service runs by default and is not optional. It dumps Postgres on
an interval into the `backups` volume.

> A dump on the same disk as the database is not a backup — it dies with the
> machine. Set `BACKUP_REMOTE` and the container verifies the remote is
> reachable **at start**, refusing to run rather than discovering at restore
> time that nothing was ever copied.

```bash
rclone config          # e.g. a Hetzner Storage Box or Backblaze B2 remote
# then set BACKUP_REMOTE in .env and RCLONE_CONF if the config is not at
# /home/sauron/.config/rclone/rclone.conf
docker compose --env-file .env -f deploy/docker-compose.yml up -d backup
docker compose --env-file .env -f deploy/docker-compose.yml logs backup | head
# must say: [backup] offsite target <remote> verified
```

Live market-data streamers are the genuinely optional part:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml --profile streamers up -d
```

## 9. Updating

```bash
git pull
docker compose --env-file .env -f deploy/docker-compose.yml up -d --build
```

Migrations and seeding re-run automatically; both are idempotent.

## 10. Restoring

Dumps live inside the `backups` volume, not on the host, so copy one out
first:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml \
  cp backup:/backups/sauron-<stamp>.dump .

docker compose --env-file .env -f deploy/docker-compose.yml exec -T postgres \
  pg_restore -U sauron -d sauron_vision --clean --if-exists < sauron-<stamp>.dump
```

## 11. After a reboot

`unattended-upgrades` will reboot this box. The Docker daemon restarts
containers without compose's `depends_on` ordering, so a service can come up
against a not-yet-ready Postgres or Redis. Re-apply the ordering:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml up -d
docker compose --env-file .env -f deploy/docker-compose.yml ps   # nothing Restarting
```

---

## Operating notes

**Going live is deliberate.** Bots ship in paper mode; flipping one to live
requires the trading PIN from step 4, and a live bot whose broker credentials
are missing refuses to trade rather than recording paper fills as real ones.

**Broker credentials are verified when you save them.** OANDA and Alpaca are
checked with an authenticated account call; Binance with the signed account
endpoint; IBKR verification only proves the TWS socket answers, not that the
account id is valid — the flash message says which was checked. A save that
fails verification keeps the row but leaves it `connected = False`, so
`/health/` → live-mode readiness tells the truth.

**Positions survive the box being down.** Entries attach broker-side stop and
target orders where the broker supports it (Alpaca brackets, OANDA on-fill), so
a reboot or a crashed worker does not leave a position unprotected. On restart,
reconciliation compares the broker's positions to the database and the
`retry_pending_closes` task drains anything stranded.

**Watch `/health/` and `/forensics/`** rather than tailing logs: the first
answers "is the machine running", the second answers "why did it do that".

**Resource pressure** shows up first as Celery workers being OOM-killed.
`docker stats` will show it; the fix is a bigger box, or lowering worker
concurrency from `-c 2` in the compose file.
