# Deploying Sauron Vision

One box, one compose file, one command. Follow this top to bottom — every
step is here because skipping it breaks something later.

**Target:** a Hetzner CX32 (4 vCPU / 8 GB, ~€8.50/mo) or equivalent. The
4 GB CX22 works but is tight once backtests and the brain run alongside
Postgres and Redis.

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
stack — Caddy requests a certificate for that exact name on boot, and it
cannot succeed until DNS resolves.

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

> **Set `FERNET_KEY` now, before you ever store broker credentials, and keep
> it safe.** It encrypts them at rest. It is separate from `SECRET_KEY` on
> purpose: rotating that — or rebuilding on a new host — would otherwise
> make every stored broker credential permanently undecryptable, and the
> bots would silently fall back to paper trading.

```bash
chmod 600 .env
```

## 4. Start

```bash
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml logs -f migrate   # should exit 0
```

The `migrate` service runs migrations, `collectstatic` and component seeding
once; everything else waits for it to finish, so there is no start-up race.

Create your login:

```bash
docker compose -f deploy/docker-compose.yml exec web python manage.py createsuperuser
```

Then open `https://your-domain/` — you should get the landing wall with a
valid certificate.

## 5. Verify before trusting it

Go to **`/health/`** (as a staff user). Every check should be green. The
ones that matter most on a fresh box:

- **Beat schedule** — every scheduled task resolves to a registered task.
- **Bot bars (4h)** — the bars the rule layer reads. Red until the bar feed
  has run at least once; give it 10 minutes.
- **Quote feeds** — nothing here until you enable streamers or a poller.

Then check `docker compose -f deploy/docker-compose.yml ps` — every service
`running`, none restarting in a loop.

## 6. Optional extras

```bash
# Live market-data streamers (Binance needs no key)
docker compose -f deploy/docker-compose.yml --profile streamers up -d

# Nightly offsite backups — configure rclone first, then set BACKUP_REMOTE
rclone config          # e.g. a Hetzner Storage Box or Backblaze B2 remote
docker compose -f deploy/docker-compose.yml --profile backup up -d
```

> Backups without `BACKUP_REMOTE` stay on the same disk as the database.
> That is not a backup — it dies with the machine.

## 7. Updating

```bash
git pull
docker compose -f deploy/docker-compose.yml up -d --build
```

Migrations re-run automatically as part of the `migrate` service.

## 8. Restoring

```bash
docker compose -f deploy/docker-compose.yml exec -T postgres \
  pg_restore -U sauron -d sauron_vision --clean --if-exists < sauron-<stamp>.dump
```

---

## Operating notes

**Going live is deliberate.** Bots ship in paper mode; flipping one to live
requires the trading PIN, and a live bot whose broker credentials are
missing refuses to trade rather than recording paper fills as real ones.

**Positions survive the box being down.** Entries attach broker-side stop
and target orders where the broker supports it (Alpaca brackets, OANDA
on-fill), so a reboot or a crashed worker does not leave a position
unprotected. On restart, reconciliation compares the broker's positions to
the database and the `retry_pending_closes` task drains anything stranded.

**Watch `/health/` and `/forensics/`** rather than tailing logs: the first
answers "is the machine running", the second answers "why did it do that".

**Resource pressure** shows up first as Celery workers being OOM-killed.
`docker stats` will show it; the fix is a bigger box, or lowering worker
concurrency from `-c 2` in the compose file.
