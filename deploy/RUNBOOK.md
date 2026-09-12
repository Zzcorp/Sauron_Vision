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
>
> Because a flag needed on *every* command is exactly what a hand-typed alias
> drops, `deploy/dc` wraps it: `./deploy/dc up -d --build`,
> `./deploy/dc logs -f web`, `./deploy/dc exec web python manage.py migrate`.
> Same arguments as `docker compose`, minus the trap.

---

## 1. The box

```bash
# As root, on a fresh Debian 12 / Ubuntu 24.04:
adduser sauron && usermod -aG sudo sauron
```

Copy your SSH key to the new user, then **disable password login** in
`/etc/ssh/sshd_config` (`PasswordAuthentication no`) and `systemctl restart ssh`.

```bash
# git and python3-cryptography are NOT on minimal cloud images, and both are
# needed below: git for the clone, cryptography for the FERNET_KEY one-liner.
apt update && apt install -y git docker.io docker-compose-v2 ufw fail2ban rclone python3-cryptography
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
cd Sauron_Vision

cp .env.production.example .env
```

The clone root IS the project root — `manage.py` sits directly inside
`~/Sauron_Vision`. (An earlier version of this file said
`cd Sauron_Vision/SAURON_V/sauron_vision`, a nesting that exists only on the
development machine; it failed on every fresh clone.)

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

**News & sentiment** are their own set — enable when you want them:

- `scraper_news` — RSS + MarketAux headlines every 3 min. The RSS side is
  keyless and includes crypto (CoinDesk, Cointelegraph, Decrypt);
  `MARKETAUX_API_KEY` in `.env` widens it.
- `scraper_crypto_news` — the dedicated crypto RSS pass every 10 min
  (CoinDesk, Cointelegraph, The Block, Decrypt). Overlaps the above
  harmlessly — articles dedupe by URL.
- `scraper_sentiment` — Reddit + StockTwits every 30 min. Reddit REQUIRES
  `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` in `.env` (create a free
  "script" app at reddit.com/prefs/apps); without them it silently stores
  nothing. Covers r/wallstreetbets, r/investing, r/stocks,
  r/CryptoCurrency, r/Bitcoin.
- `pipeline_sentiment_agg` — hourly aggregation into per-instrument scores.
- `agent_news_analyst` — AI turns headlines into structured sentiment.
  Needs `ANTHROPIC_API_KEY` and spends tokens; enable deliberately.

After editing `.env`, run `dc up -d` — **not** `restart`, which keeps the
old environment.

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

> IBKR: `127.0.0.1:7497` means *the container itself* — the one place
> nothing is listening. Two ways to give it a real address:

**Run Gateway in the stack (recommended).** Put your IBKR login in `.env`
and start the profile:

```bash
./deploy/dc --profile ibkr up -d
```

The admin form's host field is then just `ibgateway`, with port **`4004`
for paper or `4003` for live — NOT 4001/4002.** The image binds the
Gateway's own API ports to the container's `127.0.0.1` and relays them
out through socat: container port 4003 fronts the internal live 4001,
4004 fronts the internal paper 4002. From another container, 4001/4002
answer CONNECTION REFUSED forever — even after a perfect login — which
looks exactly like "Gateway is down" and is not. (An earlier revision of
this runbook said 4001/4002 here; the first real Gateway proved it
wrong.) No bridge address to look up, no `ufw` rule for the docker
subnet, no virtual display, no trusted-IP list. The image bundles IB
Gateway with IBC, which performs the login the dialog would otherwise
wait on forever. The socket is reachable from the compose network and
from nowhere else — these ports accept unauthenticated, unencrypted
orders, so they are deliberately never published to the host.

**Or run Gateway on the box.** The host field is then
`host.docker.internal` (the compose anchor declares it), or the compose
network's gateway address:

```bash
docker network inspect sauron_default --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}'
```

Note this is NOT the `docker0` address from `ip addr` — compose builds its
own network. Gateway must also accept it: **Configuration → API →
Settings**, untick *Allow connections from localhost only*, and add that
address to **Trusted IPs**. A host firewall that DROPs the docker subnet
shows up as a connection TIMEOUT rather than a refusal.

Either way, verify from inside the container before trusting the form —
this is the only test that answers the question:

```bash
./deploy/dc exec web python -c "import socket; socket.create_connection(('ibgateway', 4004), 5); print('reachable')"
```

**One session per IBKR username.** Logging into the IBKR portal or the
mobile app with the same credentials kicks Gateway out mid-session, and
the newcomer is shown "Existing session detected" and asked to choose.
IBC's default for that dialog is MANUAL — it waits for a click that never
comes: on 2026-09-11 the Gateway logged in, passed 2FA, reached the dialog
and sat on it, container "Up", reading 19h old. The compose now sets
`EXISTING_SESSION_DETECTED_ACTION: primary`: the Gateway takes the session
and the other one drops. A container created before that line keeps its
old environment — recreate it (`./deploy/dc --profile ibkr up -d
ibgateway`), a restart is not enough. The fight stays symmetric: the human
logging in with the same name still kicks the Gateway out, and every
re-login costs an IB Key push; unanswered, that is the `Authorization
failed` loop with a stale reading (converting currency in the portal did
exactly this). The
fix is structural: a SECOND username on the same account for the
Gateway (Client Portal → Settings → User Settings → Users & Access
Rights → add a user with trading rights and its own IB Key), applied
with `./deploy/ibkr-apply`; the human keeps the first username for the
portal and the mobile app. Until then: log out of the portal before
the Gateway logs in, and expect a push after every portal visit. For
paper, use the paper username for Gateway and keep the live one for
the portal.
`TRADING_MODE` decides which account Gateway logs into and the PORT
decides which one Sauron talks to — paper with 4004, live with 4003 (the
socat relays for the internal 4002/4001). Set one without the other and
the socket never answers, which looks exactly like a network fault. A
LIVE login also demands IB Key two-factor on the phone at every start and
roughly daily after — IBC types the password but cannot answer 2FA, so an
unattended live Gateway drops and re-prompts. Paper logs in headless.

**Apply a stored login in one command.** The login lives encrypted in the
database (the UI); the Gateway reads it from `.env` at boot. Do not paste
between the two by hand — that is how a password with `$$` in it lost a
character. From the repo root:

```bash
./deploy/ibkr-apply              # render -> splice into .env -> recreate the gateway
./deploy/ibkr-apply --slot 2     # a second login's container
```

It keeps `.env.bak`, locks `.env` to 600, and RECREATES the container
(`restart` keeps the old environment; only recreate re-reads `.env`). Run
it again whenever you change the login in the UI.

**Second factor.** IBKR will demand one on every LIVE login and roughly
daily after. Which kind decides whether this can run unattended:

* **IB Key push** (IBKR Mobile app, notification mode) — a push you tap
  to approve. The automation waits for it and retries if you miss it.
  This is the one to have: Client Portal → Settings → Security → Secure
  Login System → IB Key.
* **A code** (SMS, code card, or IB Key in challenge mode) — a number you
  must TYPE into the Gateway's own window, which nothing on the platform
  can reach. It will sit at the code prompt every login. Either switch the
  account to push, or type it by hand through VNC (`IBKR_VNC_PASSWORD`).
* **Paper** — a separate paper username has NO second factor and logs in
  headless. Prove the whole chain on 4004 first.

**Switching to the push, start to finish.** THERE IS NO SETTINGS MENU FOR
THIS, which is the thing worth knowing: an earlier version of this file said
"Menu → Two-Factor Authentication", an operator hunted for it, and it does
not exist. Activation happens on the app's LOGIN SCREEN, or by QR code from
the portal. Either route logs you into the app, which kicks a running
Gateway — fine, you are about to re-login anyway.

*From the app, no portal needed:* open IBKR Mobile → on the login screen tap
**I Have an Account** → **Register Two-Factor** → username and password →
Continue → pick the phone number → **Get Activation SMS** → enter the token
that arrives → create a PIN (Android) or confirm with Face ID / passcode
(iPhone) → Done.

*From the portal:* log in at interactivebrokers.com/sso/Login → **user icon**
→ Settings → Security → **Secure Login System** → the button reads
**Complete**, not "IB Key" → scan the QR code it shows with the phone's
camera → allow notifications → create the PIN.

Notifications must be enabled for IBKR Mobile, and the phone must be able to
receive an SMS: that is how the activation token arrives. KEEP SMS enrolled
as the backup — losing the phone must not mean losing the account. With both devices enrolled, the Gateway's login shows a device
list, and the stack auto-selects `IBKR_TWOFA_DEVICE` (default `IB Key` —
override in `.env` only if IBKR spells your device differently; the value
must match the list exactly). A missed push re-prompts rather than giving
up (`RELOGIN_AFTER_TWOFA_TIMEOUT`), so the ~daily live re-login becomes:
phone buzzes, you tap approve, done — no VNC, nothing typed. Then
recreate the slot (`./deploy/ibkr-apply`, or `--force-recreate` if the
login is unchanged) and watch for the push.

**When the Gateway hangs behind a dialog.** IB Gateway 10.45 shows a
generic notice box titled just "Gateway" for anything the server wants a
human to read: a login refusal, an account action, or a marketing
interstitial. The IBC automation inside the image cannot read that box's
HTML body and — by design — leaves it on screen with no timeout (open IBC
defects #360 and #382, maintainer-confirmed August 2026). The tell in
`dc logs ibgateway`:

```
IBC: detected dialog entitled: Gateway; event=Opened
IBC: GATEWAY
                                   <- blank: the body IBC could not read
IBC: detected dialog entitled: Gateway; event=Focused
                                   <- then nothing, for hours
```

`dc ps` shows the container **(unhealthy)** in this state — the healthcheck
probes the Gateway's internal API port, which only listens after login, so
"Up 3 hours (unhealthy)" means stalled, not running. No IB Key push arrives
because the server never reached the 2FA step. `./deploy/ibkr-doctor` runs
every check below — and the API-session checks the Gateway itself cannot
see — read-only, and names the next step; start there. By hand, in order:

1. `./deploy/dc --profile ibkr restart ibgateway` — the interstitial
   variant is non-deterministic and a restart usually logs in clean.
2. If it recurs, read what the server actually said — the Gateway's own
   log keeps the message IBC could not:
   `docker exec sauron-ibgateway-1 grep -a -i -E "Authorization failed|Connection to server failed|FailReason|AdsManager|asskey" /home/ibgateway/Jts/launcher.log | tail`
   An `Authorization failed: <html>…` line names the reason (account
   action, version, passkey). `AdsManager … 1200x1000` with no failure
   line is the interstitial.
3. To see and dismiss the dialog by eye, set `IBKR_VNC_PASSWORD` in `.env`,
   `./deploy/dc --profile ibkr up -d --force-recreate ibgateway`, and
   tunnel to the container's compose-network IP as described beside that
   variable — nothing is published to the host.

A LIVE login additionally needs IB Key two-factor on the phone at every
start and roughly daily after; IBC types the password but cannot answer
the phone. Paper (4004) logs in headless, which is why it proves the
whole chain first.

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

## Three personalities (/personas/)

A **trader personality** is not a new engine. Every knob it needs already
decides how a bot behaves — the timeframe it reads, the ATR multiples its
stop and target are cut from, how long a thesis may live, how many bets
run at once, how much of the pool one stop-out costs. What was missing is
that those knobs were set ONE AT A TIME with no coherence between them,
graded over one 90-day window that fits none of them, and allocated out of
one 2–60% band. A personality is four things and nothing more:

1. a **coherent preset** of knobs that already exist and are already read;
2. a **grading window** matched to the holding period (21 days of scalps
   is a sample; 21 days of position trades is one trade);
3. a **share band** in the account allocator (`bounds_for`);
4. a **weight** on the 5–10 year horizon prior (`horizon_for`), clamped so
   the factor can never leave 0.85–1.15 whatever the weight.

**The leverage correction — read this one.** The ask was "short exposure in
time and large in volume and leverage". **No personality borrows to fund a
position.** The claim is scoped to personalities because the sweeping
version of it is false, and was caught being false in review:
`bot_program.models.BotConfig` carries both `leverage` and `margin_mode`,
`engine/risk.py` multiplies the position dollars by the first, and
`engine/runner.py` POSTs both at the Binance futures venue through
`ensure_config`. That engine is dormant, not absent, and it is
hand-triggerable from `views.run_tick_now`. Scoped, the claim is stronger
than the sweeping one: `AssetBotConfig` — the only config a personality can
be worn by — carries neither field, so no persona can set what it does not
have.

The honest short-term lever is (a) the **notional fraction** the risk sizer
is allowed to reach — how much position one fixed *cash* risk budget buys
when the stop is tight — and (b) the **number of concurrent positions**. On
stock, ETF, index, commodity, crypto and options both are cash and neither
is a loan. **Forex is the exception, and the leverage there is real:**
`sizing.MAX_NOTIONAL_FRACTION` grants it 4.0 — 400% of the pool in notional
— because 20% on an FX major is an economically meaningless constraint, and
that module names where the leverage sits: *"the leverage is at the
broker"*. **No personality ever lowers it.** "Large in volume" is delivered
as eight concurrent bets at a 35% notional cap on a 0.15% risk budget
everywhere else, and by the venue on FX.

Separately and independently of all the above: IBKR refuses margin, shorts,
currency conversion and futures outright below a 2,000 USD account floor
(Error 201). That is the broker's constraint on the account, not a property
of this code.

| | **scalp** | **swing** | **position** |
|---|---|---|---|
| purpose | many small bets, hours not days | what Sauron is today: the 4h trend | the long view: weeks, few bets |
| timeframe | `1h` | `4h` | `1d` |
| entry_score_min | 0.65 | 0.60 | 0.65 |
| min_signals_for_entry | 2 | 1 | 2 |
| cool_down_minutes | 15 | 60 | 1440 |
| max_concurrent_positions | 8 | 5 | 3 |
| max_daily_loss_pct | 2.0 | 2.0 | 3.0 |
| hold ceiling (`max_hold_hours`) | 8h | 72h | 720h |
| risk_per_trade_pct | 0.15 | 0.25 | 0.40 |
| ATR stop / target | 1.0 / 2.0 | 1.5 / 3.0 | 2.5 / 6.0 |
| ATR measured on (`atr_timeframe`) | `1h` | `4h` | `1d` |
| max_signal_age_hours | 4 | 24 | 72 |
| max_notional_fraction | 0.35 (never forex) | class default | class default |
| loss streak / drawdown breaker | 3 / 8% | 4 / 10% | 5 / 15% |
| grading window | 21 days | 90 days | 365 days |
| horizon weight | ×0.0 | ×0.5 | ×1.5 |
| share band | 5–25% | 20–60% | 15–50% |

A scalp config's horizon factor is therefore exactly 1.00, and the share
plan says so in words: `horizon 1.00 (scalp ignores the 5-year view)`.

**`atr_timeframe` is a separate key from `timeframe`, and it matters.**
`risk_levels.stop_and_target` cuts every ATR multiple from
`extras["atr_timeframe"]`, which defaults to `4h` for every config on the
platform. A multiple is only as long as the frame it is measured on: a
"1.0 ATR" stop measured on 4h bars is two to four times the hourly range a
scalp is written around, and a 2.5 ATR stop measured on 4h bars is about
2% on a liquid equity — which an ordinary week clears twice, so a
thirty-day position thesis would be stopped out by four-hour noise. Each
personality therefore sets `atr_timeframe` to its own frame, and the
missing-bars warning covers it: with no `1d` bars, `atr_for` returns None
and `stop_and_target` falls back to the flat `stop_loss_pct` percentage —
a DIFFERENT stop, not a clamped one.

**Two keys are REMOVED, not merged, when a personality is applied**, and
the plan names both before the write:

* `extras["max_hold_hours"]` — the legacy time-stop inlet.
  `time_stop_setting()` reads it *before* the column, so leaving it would
  let an old value outrank the personality's ceiling silently. It is
  drained exactly as the migration and the settings form drain it.
* a knob the **previous** personality set that the new one does not — today
  only `max_notional_fraction`, which `scalp` writes and the other two do
  not. Without the drop, `scalp -> swing` would leave a scalp's 35%
  notional cap on a swing book for ever. Removed **only** when the stored
  value is still exactly what the previous personality wrote; a number the
  operator typed themselves is never touched by a change of style.

**Applying one to a LIVE config re-sizes REAL risk** on the next entry:
`risk_per_trade_pct`, the ATR stop distance and the notional cap all feed
`sizing.size_position`. The page asks for the trading PIN there, and the
command asks for `--yes`; `apply_persona` refuses a live config without
that force. **A personality changes NO capital and NO account share by
itself, and never enables or disables a bot.** It writes only the knobs in
the table above, plus the `persona` / `persona_at` stamp in `extras`.

```bash
./deploy/dc exec web python manage.py persona list                 # the three side by side, and who wears them
./deploy/dc exec web python manage.py persona show scalp           # one in full, with why each number
./deploy/dc exec web python manage.py persona apply 14 swing       # the plan and every warning — WRITES NOTHING
./deploy/dc exec web python manage.py persona apply 14 swing --yes # writes (--yes stands in for the page's PIN)
./deploy/dc exec web python manage.py persona grade                # each personality over ITS OWN window
./deploy/dc exec web python manage.py persona mix                  # which personality this tape rewards (see below)
```

Read the plan's warnings before the `--yes`. The three that matter: the
timeframe has **no bars** for this config's symbols (nothing writes `1d`
bars for crypto — the EOD task covers stock/etf/index/commodity/forex
only); the config holds **open positions** and the time stop or the ATR
multiples are moving (the time stop measures from `opened_at`, so a
shorter ceiling can flatten a position on the very next tick); and the
config is **live**.

The eleven sector ETFs the Horizon view needs (`XLK XLE XLF XLV XLI XLY
XLP XLU XLB XLRE XLC`) plus `UUP` are in the instrument catalogue, but
their bars are not backfilled by adding them. That is an operator command:

```bash
./deploy/dc exec web python manage.py seed_instruments
./deploy/dc exec web python manage.py backfill_bars --symbols XLV,XLI,XLY,XLP,XLU,XLB,XLRE,XLC,UUP --intervals 1d,4h --bars 300
```

`/personas/` shows the same three presets, the same grade and the same
warnings as the commands, with an Apply form for superusers.

### The mix moves with the market

The ask was: *"make the three personalities interact continuously — under
certain market states some personalities should be used more, no?"* The
intuition is sound and the platform has every piece. **What it does not
have is the answer.** Nobody knows yet which personality suits which
regime: not the operator, not this runbook, and not the code. So the
platform does not hard-code a belief — it runs **two lanes**, and every
answer says which one spoke and with what `n`:

* **MEASURED** — what configs wearing that personality actually earned
  while the platform *recorded* that regime, above the evidence ledger's
  own sample floor (10 graded fills). The regime is joined on the trade's
  **entry**, against the `BrainReport` that existed *then* — never
  today's. This lane wins whenever it exists.
* **PRIOR** — a small, explicitly-labelled, **unproven** tilt, used only
  where nothing is measured. The loudest entry in the table moves a band
  by 9%; the largest one the code permits is 15%. Not one of them is
  backed by a single graded fill on this deployment. **A measured cell
  replaces its prior entirely** — not blended, not decayed, gone.
* **NEUTRAL** — exactly 1.00, when the regime is `unknown` (the absence of
  a reading, not a state of the market) or no prior says anything.

**What the factor does, and the bound on it.** It moves that
personality's **share band**: the band's *centre* shifts, its *width*
never changes, and the shift is held to **5 percentage points of the
account** whatever the factor says — so a ×1.15 on swing (20–60%) lands
at 25–65%, never at 40–80%. Everything under the band is unchanged: the
water-fill, the half-way smoothing, the **per-day cap** and the
hysteresis all still bind, so **a regime flip moves a pool no further in
one day than the allowance the allocator already granted it**: 10 points
in NORMAL and SHOCK, and the 20 points upward that an EXPANSION tape
already allowed before the mix existed. (Saying "still 10 points" would
have been wrong on an expanding tape, and it was wrong there before this
feature too.) An explicit
`extras["share_floor_pct"]`/`["share_ceiling_pct"]` still wins over the
mix, the manual lane still has no ceiling, and **a config wearing no
personality is not touched at all** — its plan is byte-for-byte what it
was before this existed.

**When the shift does not run, the plan says which rule beat it.** The
band shift sits inside one case of `bounds_for`'s precedence — manual
lane, then an explicit band, then the persona band, then the defaults —
so on the hand-taken pool and on a config whose band an operator typed
by hand the mix is read, printed, and **not applied**. The plan's inputs
carry `mix.applied: false` with `mix.outranked_by` naming the winner and
the sentence reads *"not applied, the manual lane wins"*. It used to say
*"the explicit band wins"* on the manual lane and then quote a band move
(5–25 → 2–100%) the exemption had made and the mix had not — a plan
must never claim a number it did not set (2026-09-12).

**The mix moves SHARES ONLY.** It never touches `risk_per_trade_pct` or
`max_notional_fraction`. Two dials moving in the same week make the grade
unattributable: if a regime flip shifted both the share and the risk per
trade, no reading afterwards could say which one earned the R — and being
able to say is the entire point of recording the lane and the `n`.

```bash
./deploy/dc exec web python manage.py persona mix                          # the matrix, the regime, its confidence and age
./deploy/dc exec web python manage.py persona mix --venue paper            # paper is NEVER pooled with live
./deploy/dc exec web python manage.py persona mix --regime trending        # a what-if column, in full sentences
```

`/personas/` carries the same matrix: three rows, six regime columns,
measured cells in bold with their `n`, priors in italic, the current
regime's column marked, and one line saying **how many of the eighteen
cells are still guesses**. On a fresh deployment that line reads 18 of
18. Watching it fall is the feature — the priors retire cell by cell as
the graded fills arrive, and the operator can see exactly which parts of
the mix the platform has actually learned.

---

## The Oculus (/oculus/)

The page above the other thirty. They each answer their own subsystem's
question well; this one answers the operator's — **is the machine
turning, and which of its wheels are actually engaged?** It owns no data,
adds no arithmetic, caches nothing, and writes nothing. Ten panels, one
per cycle: the switches, the scan, the ladder, the signals, the
evolution, the personalities, the allocation, the horizon, the backtests,
the trust.

What it does that no single page could:

1. **The gate sits beside the count.** A number written by a task nobody
   switched on measures the switch, not the market. A component with no
   row at all renders `absent` in amber rather than `off` — the two look
   identical to `is_component_enabled` and have completely different
   fixes. On 2026-09-13 that distinction was the whole bug: three
   components had never had a row and three features had never run.

2. **The qualifier sits inside the same line as the count.** The
   recurring failure in this platform is not a wrong number, it is a
   right number that reads as its opposite. "6 rules in research" reads
   as coverage; a research-stage rule can neither place an order nor vote.
   "40 entries chosen" reads as allocation; in shadow every candidate
   executed at full size anyway. Counts that cannot act are toned down,
   never celebrated.

3. **An em-dash is not a zero.** `—` means *not measurable*; `0` means
   *measured, and nothing happened*. `core/wall_facts.py` collapses
   everything to 0 because it is the public login gateway and must never
   raise; behind auth the duty is the opposite, because an operator acts
   differently on each. Every counter that renders `—` is also listed by
   name at the foot of the page, so a dash can never pass for a quiet
   zero.

Each panel is fenced on its own: a cycle whose table is mid-migration is
reported **dead**, never dropped — a vanished panel reads as "there is no
such cycle", which is a lie of omission the operator cannot see.

The evolution strips are bucketed on creation stamps only, never on
`completed_at` / `resolved_at` / `evaluated_at`: those are NULL on
exactly the rows a stalled cycle would show, so bucketing on them hides
the stall. Each strip is scaled to itself, never to the busiest cycle on
the page — one shared axis would flatten every slow cycle into a flat
line and read as "dead" when the honest reading is "slower than the
scanner, by design".

Nothing to run. Open the page; `tests/test_oculus.py` holds it to the
three rules above.

---

## The cockpit (/ops/)

One page that says "everything, now": every platform switch with its
state, last run, status and error count (toggle from the page, superusers
only); every decision queue with its count, the newest item's age and the
page that decides it (actuator proposals, generator proposals, share plans,
meta-allocation shadows, pending closes, open positions live/paper, the
research fleet); the broker's last reading with its age, the drawdown and
governor, the share-allocator mode, and `preflight_live`'s verdict (the
BLOCKERS lines or NO BLOCKERS FOUND, cached two minutes per user); and the
command catalogue. Every number carries its source and age and reads `—`
where nothing has been measured. The switches and the queues are
platform-wide and follow `/health/`'s rule — staff only; any login reads
its own account, its own plans, the preflight verdict and the catalogue.

The Run lane's rule: the page runs only a command registered as read-only
in `core/ops_commands.py`, with the fixed arguments the registry gives it
and nothing from the browser — `open_trades`, `preflight_live`,
`why_no_trade`, `signals`. Every run and every refusal is an audit row (`ops_run`,
`ops_run_refused`); the output is kept an hour, truncated at 20,000
characters. Anything that writes — `component on`, `proposals approve`,
`actuator apply`, `shares apply`, `follow`, `bot on`, the seeders, the
backfill — shows its usage on the page and runs on the server, where
`--yes` or the PIN keeps its meaning:

```bash
./deploy/dc exec web python manage.py ops            # the catalogue, as text
./deploy/dc exec web python manage.py ops --category read
```

A management command missing from the registry (or from its EXEMPT set)
fails `tests.test_ops_cockpit`, so the page and the shell cannot drift.

---

## Why a setup never fires (/setups/)

On 2026-09-12 the platform carried 28 RuleControl rows, 26 of them at
`research`. Sixteen of those 26 had produced ZERO signals in seven days AND
zero graded signals in their entire life. The ladder wants 30 graded signals
to leave `research`, so at that rate no designed rule is ever promoted, no
designed rule ever trades, and every evidence lane stays unmeasured for ever.
Until this page existed a silent setup was simply silent: nothing said
whether its conditions were too strict, its data was missing, or it missed
its threshold by 0.02.

`/setups/` and `python manage.py setups diagnose` answer that. The diagnostic
runs the SCANNER'S OWN `scan_setup` with `emit=False` — it writes no flag and
no signal — over every active setup × every active instrument the setup's
`asset_classes` admit (an empty `asset_classes` means all). Four verdicts and
an empty case:

| verdict | what it means | what to do |
|---|---|---|
| `fires` | it matched somewhere in the population | nothing — it is working |
| `near` | its best composite is inside the near-miss band (default 0.10) below its threshold | lower `min_match_score`, or widen the weakest condition — the sentence names it |
| `strict` | every condition EVALUATES and none combine past the threshold | it is a rare pattern, honestly measured. Loosen it or accept the rarity |
| `blind` | a condition CANNOT EVALUATE on most of the population — no bars, no indicator row, no news | **loosening the threshold changes nothing, ever.** Backfill the data or drop the condition |

A composite the scanner REFUSED is never counted as a near miss and never
enters the distribution. When less than half a setup's authored weight could
be measured on a pair, `scan_setup` returns `not_enough_measured` with a
score on it — the surviving legs renormalised to themselves — and that
number was never compared to the threshold. Those pairs are counted under
"below quorum" in `setups show` and named in the verdict sentence; lowering
`min_match_score` on such a setup changes nothing.
| `empty` | no active instrument is in its asset classes at all | fix `asset_classes`, or activate instruments |

The distinction between `strict` and `blind` is the whole point. A condition
that evaluates and refuses is a judgement about the market; a condition that
never got to look is a dead leg, and the scanner scores it as a zero either
way — which is exactly why the silence looked identical from outside.

```bash
./deploy/dc exec web python manage.py setups list        # armed, stage, 7d, graded ever
./deploy/dc exec web python manage.py setups diagnose    # every verdict, worst first
./deploy/dc exec web python manage.py setups show advanced_smc_long
./deploy/dc exec web python manage.py setups grading --days 30
```

**Arming what was never armed.** A generated setup is written `is_active=False`
with a research-stage RuleControl row, so nobody clicking means it is neither
scanned nor traded — pure dead weight. `setups arm <name> --yes` (or the Arm
form on `/setups/`, superusers) arms it. Where a PENDING `GeneratedSetupProposal`
exists it goes through `brain.strategy_generator.approve_proposal`, so the
`approval_blocker` re-validation and the audit row are the `/generated/` page's
own and not a second path; with no proposal row it flips `is_active` and writes
its own `setup_armed` audit event. Without `--yes` it prints what it would arm
and the blocker for anything it cannot.

**Arming a research-stage setup is SAFE.** `is_active` decides whether the
SCANNER looks at a setup; `RuleControl.promotion_stage` decides whether any bot
may act on what it finds, and at `research` `stage_policy` returns
`may_trade False` — no order is ever placed. A setup with NO RuleControl row is
NOT research: `stage_policy` treats such a rule as PAPER — it may trade, at full
nominal size, on the paper venue. The command prints that warning before it
arms one, and so does the page.

**The grading leak.** `setups grading --days 30` counts, per rule, how many
signals were created, how many closed, and how many closed with no outcome or
with an outcome and no `realized_r`. Both of those last two are INVISIBLE to
the promotion ladder (`promotion_pipeline._stats_since` excludes both) and to
every evidence lane (`bot_program.evidence.rule_rows` excludes both): the
signal was produced, it cost a scan, and it taught nothing. If a material
share of closed signals lands there, the repair is in `signals/performance.py`
and `run_signal_lifecycle`, not in the scanner.

**The scan cadence stays at daily 09:00 UTC — measured, not assumed.**
A full `diagnose_setups` pass (the same loop `scan_all_setups` runs, one
`scan_setup` per pair) over 6 active setups × 179 active instruments —
**566 admitted pairs, 1,698 evaluator calls, 4.0-7.1 seconds** measured four
times on the local development database on 2026-09-12 (7-12.5 ms a pair; the
spread is OS page cache, cold to warm). That database holds only 5,600 price
bars, so nearly every evaluator refused for want of data before doing any
arithmetic: **the number is a FLOOR on the cost, not an estimate of it.**
The live deployment carries 20 active setups over the same 179 instruments
with a full bar history — about 3.3× the pairs, and a real window measured on
each one instead of an early return. 3.3 × (4.0-7.1) s is 13-24 s of pure
loop before a single real measurement is paid for, and the multiplier above
that is unknown. **13-24 seconds with an unknown multiplier on top is not
"comfortably under 60", so the cadence is NOT raised.** Re-measure on the box
before changing it:

```bash
./deploy/dc exec web python manage.py setups diagnose | head -2   # prints the seconds
```

If that line reads comfortably under 60 s against the real 20-setup
population, `config/celery.py`'s `scan-opportunities` entry may move from
`crontab(hour=9, minute=0)` to `crontab(minute=5, hour='*/4')`: 4× the scans,
4× the flag rate, 4× the evidence accrual, against that many seconds of
worker time per pass. Do not raise a cadence nobody has timed on the
population it will actually run against.

## Reading a signal (/signals/)

Every signal row answers six questions, and the first of them did not exist
anywhere before 2026-09-12:

1. **Can anything act on it?** One badge, derived from
   `rule_actuator.stage_policy` + `is_rule_active` — the SAME two functions the
   entry path calls, never a second implementation. `TRADEABLE` (live venue),
   `PAPER ONLY` (paper stage, or NO RuleControl row at all, which reads
   "unregistered - paper venue at full size" — `stage_policy` fails safe, not
   closed), `WATCHED` (research: may_trade False, and the rule's votes are
   dropped from every bot's consensus, which is why the fleet reads
   "net evidence +0.00"), `PAUSED` / `REDUCED` from the admin lane.
   **A PAUSE IS NOT A VENUE GATE.** `is_rule_active` is read in exactly two
   places — the rule engine's signal write path (`signals/tasks.py`) and the
   fast-rule runner. `scan_all_setups` never reads it, so a paused
   setup-backed rule keeps scanning and publishing; and the bot entry path
   reads `stage_policy` alone, so a bot WILL act on a signal that already
   exists from a paused rule. The badge therefore shows `PAUSED` and still
   reports the stage's own `may_trade`: to stop a rule reaching a venue,
   demote its stage, not its status (2026-09-12).
2. **What is the rule worth?** `bot_program.evidence.rule_rows`, held to that
   module's own `MIN_EVIDENCE_N` floor. Below the floor it reads `unmeasured`,
   never a number.
3. **Why did it fire?** The linked OpportunityFlag's `conditions_evaluated`, or
   `Signal.sub_scores` for an engine rule — and the block names which.
4. **What would it cost?** The levels and R:R on the row. There is no cost
   verdict without a config context, and the page says so rather than
   inventing one.
5. **Did anyone act?** The AssetBotTrade rows joined on rule_name + symbol +
   time. **There is no foreign key from a trade to a signal**, so the block is
   captioned as the inference it is.
6. **Its own grade.** Outcome, realized R, time to outcome — or `ungraded`,
   which is the loud one: a closed signal with no realized R is invisible to
   the ladder and to every evidence lane.

Twelve filters, all combinable as AND, each a removable chip, each a real
queryset narrowing: `q` `rule` `stage` (multi) `asset_class` `direction`
`signal_type` `urgency` `score_min` `age_hours` `state` `acted`, plus the
original `active=1`. The header reads "N of M signals", so a filter matching
nothing is visibly a filter and not an empty platform. An out-of-vocabulary
value is IGNORED, not applied. The list is paginated at 50.

```bash
./deploy/dc exec web python manage.py signals list --stage research --min-score 0.7
./deploy/dc exec web python manage.py signals show 4211     # the same six blocks
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

**IBKR order presets rewrite API orders.** TWS/Gateway applies the
account's order preset to anything the API leaves unset, and can override
what it sets — announced as notice 10349, *"Order TIF was set to DAY based
on order preset"*. Sauron sends the entry as DAY and the stop and target as
GTC, then reads back the time-in-force the Gateway actually kept. A stop the
preset turned into DAY would expire at the session close while the row said
`protected`, so such legs are withdrawn on the spot, the row is booked
unprotected (bot-side management owns the exit) and its `protection_note`
says why. Set the preset's Time in Force to **GTC** before going live, from
a TWS logged in as the same user: Global Configuration → Presets → the
instrument type (Stocks, Forex…) → Time in Force. The headless Gateway
applied one on this deployment with no TWS installed beside it, so the
preset travels with the login; if the Gateway keeps reporting DAY after the
change, the preset is not the only source and IBKR support is the next call.
Until it is fixed, every live entry is booked unprotected and bot-managed.

**The research fleet feeds the learning engine.** The promotion ladder
counts graded Signals and paper fills per rule — thirty signals before a
rule leaves research, twenty paper fills before it can touch live money —
and a fleet of six starter bots on 35 symbols starves it. Seed paper bots
across the whole keyless catalogue, chunked ten symbols a config, within a
budget the bar refresh can afford:

```bash
./deploy/dc exec web python manage.py seed_research_fleet            # ~150 symbols
./deploy/dc exec web python manage.py backfill_bars --from-configs --intervals 1d,4h --bars 300
```

Keep `pipeline_promotion` ON: it is the rung that admits a research rule
into paper, and a paper bot never trades a rule still in research. Its
steps toward real money keep their own gates (thirty days, venue fills,
walk-forward evidence). `--dry-run` prints the plan; `--reset` stands the
fleet down without erasing traded history. The keyless feed now downloads
one sized window per symbol per pass instead of two two-year ones, and
breathes between symbols, so the default budget of 150 is safe.

**The weekly imagination pass runs on the frontier model.** The Strategy
Generator (Sunday 04:00 UTC, at most three proposals) is the one call on
the platform where imagination is the product, and it alone runs on the
`frontier` tier — Claude Fable 5.1, twice the Opus price, thinking always
on. Every other agent stays on its tier; change any of them on `/ai-models/`
(or `AI_MODEL_FRONTIER` in `.env`). The generator reads the evidence
ledger — what each rule has proven in paper and live — and cites it. Its
proposals land as draft setups in RESEARCH stage; switch
`generator_auto_research` ON on `/health/` and it arms them itself: the
scanner grades their signals, the stage gate keeps every bot from trading
them, the promotion ladder decides the rest, and the brain page still lets
you reject one. A safety refusal by the frontier model is not an outage:
the provider re-runs the call once on Opus and says so in the log. An
idea the validator refuses is not lost either: it lands in the history
on `/generated/` as REJECTED by `validator`, with the reason in the
"why" column — the run's `n_validation_rejected` counts those rows. The
`brain` logger keeps its INFO lines in production like every Sauron app,
so `./deploy/dc logs web | grep generator` shows the same reasons.

**The capital desk.** The trading rules size each entry on its own and
nothing ever looked at a whole tick at once: the fleet pass walked config
after config, and the third bot proposed its entry after the first two had
already filled. Five bots each correctly risking 1% is 5% of the account on
one tick, and no gate on this platform noticed. The desk is the agent that
notices.

With `pipeline_capital_desk` ON the fleet pass runs in two halves. Every bot
PROPOSES first — the decision, the levels and its own final size, with the
ticker read through the market-data session so nothing holds the exclusive
IBKR trading client — and only then does anything execute. In between, the
desk ranks the tick.

- **What it ranks on.** Expected R per unit of MARGINAL risk. Expected R is
  what the rule has really paid, on the narrowest population with at least
  ten graded fills: this config live, then this account's live fleet in the
  class, then every account's, then the paper fleet with a haircut, then the
  signal lane with the same haircut. Under that floor there is NO expected R
  — the candidate is ranked on conviction times its planned net
  reward-to-risk and is flagged `unmeasured` everywhere it surfaces. A
  decaying rule keeps its evidence and ranks at half. Marginal risk is what a
  bet adds to the book once its 4h correlation with the chosen set AND the
  open positions is counted: two 40-dollar bets that correlate 0.9 cost
  nearly 80 together, two that correlate 0.0 cost 57. That is why the best
  candidate in R sometimes ranks below one that diversifies.
- **The budget denominator.** 2% of the capital assigned to that user's
  ENABLED configs on that venue — the same pool each entry's own risk
  fraction divides by — through the drawdown governor on live only, minus the
  risk already at stop in the open book. Hand-taken positions are in that
  book: they bypass the desk and they are still money at risk. Paper and live
  never share a budget, a book or a correlation penalty. One rule may take at
  most 40% of the tick's allowance and one asset class 60%, and neither cap
  binds on the first entry of its bucket — what they bound is one idea
  wearing six tickets, and the budget already bounds the first.
- **The two switches.** `pipeline_capital_desk` makes the pass two-phase and
  writes the plans; it is SHADOW, and in shadow every candidate still trades
  at its own size exactly as it does today while the plan beside it records
  what the desk would have done. `capital_desk_mode_live` makes the plan
  obeyed: displaced entries are skipped (recorded as a `desk_displaced` skip
  naming the plan) and chosen sizes multiplied. The multiplier is NEVER above
  1.0, and `execute_entry` re-judges MAX_RISK_FRACTION, the single-position
  cap and the duplicate/theme gates after it lands — a desk that is wrong
  costs an opportunity and can never cost more risk than the bots had already
  cleared.
- **It fails open.** If the ranking pass raises, the failure is written onto
  a plan of its own and the fleet runs UNDESKED — every candidate at its own
  size, in config order, exactly as with the component off. A ranking agent
  that goes down must not stop the bots.
- **The grade.** `bot_program.tasks.grade_capital_desk` runs nightly at 03:45
  UTC. It prices every decision whose horizon has closed — a taken entry by
  its own trade's realized R, a displaced one by walking its own bars over
  its own horizon against the stop and target it was refused with — and then
  scores the plan: `edge_r` is the desk's set (realized R times the size it
  chose) minus the default set (every desked candidate at size 1.0). Positive
  means the ranking beat the fleet it overruled. An unpriceable decision is
  NULL and counted separately; it is never folded in as a zero.

Read all of it on `/desk/`, which explains the last tick in one sentence
before it shows a number, or from the shell:

```bash
./deploy/dc exec web python manage.py component on pipeline_capital_desk   # SHADOW
./deploy/dc exec web python manage.py desk list
./deploy/dc exec web python manage.py desk show
./deploy/dc exec web python manage.py desk explain 14 EURUSD   # read-only
./deploy/dc exec web python manage.py desk grade
```

**The same bar as the share allocator: LIVE only after weeks of positive
edge in shadow.** `capital_desk_mode_live` is the switch that lets an agent
refuse an entry the bots had already approved. Nothing justifies it except
the record on `/desk/` — a sparkline of `edge_r` that has been above zero
over enough graded plans to be more than noise. Until then leave it off; the
shadow plan costs nothing and is the only thing measuring whether the
ranking is worth obeying.

**The admin pages, as commands.** Every decision the pages take has a
shell twin, for the operator at a terminal and for anyone who wants the
proof pasted back. All of them are `./deploy/dc exec web python manage.py`
followed by:

- `component list` / `component on KEY...` / `component off KEY...` — the
  health page's toggle. Says the state before and after, refuses a key it
  does not know (and names the nearest), and registers a component the code
  knows but the database does not before setting it.
- `proposals list` / `proposals approve ID...` / `proposals reject ID...` —
  the brain page's click, through the same `approve_proposal` and the same
  blocker check. An approved proposal is a RESEARCH-stage setup: graded by
  the scanner, traded by no bot.
- `open_trades` (`--symbol SOL`, `--all` for the last 7 days closed too) —
  every position the bots hold, paper or LIVE, with the platform's own
  mark, unrealised P&L and R against the stop; a position with no stop is
  flagged.
- `follow` / `follow ID --share 20 --yes` / `follow ID --stop --yes` — the
  asset-bots page's Follow form: a live pool becomes a share of the
  broker account, through the same `allocate_shares` as the page, the
  sync and the preflight. Prints the plan for every follower; writes
  only with `--yes` (the page asks the PIN for this — say so).
- `bot list` / `bot off ID` / `bot on ID [--yes]` — the admin page's
  toggle with its rule: stopping is frictionless, arming a LIVE config
  takes `--yes` where the page takes the PIN.
- `actuator list` / `actuator apply ID...` / `actuator reject ID...` /
  `actuator rollback ID` — the rule actuator's buttons (live mode
  required to apply, daily caps, snapshot for rollback). `actuator
  reject --stale` is the button the page lacks: the decay investigation
  re-proposes the same enforcement every day it still holds, so one
  finding shows up as six rows; --stale rejects every proposal a newer
  one on the same rule and action supersedes.
- `shares list` / `shares propose --user NAME` / `shares apply ID --yes` /
  `shares reject ID...` / `shares rollback ID --yes` / `shares grade` — the
  share allocator's page (`/shares/`): the same proposal the beat writes,
  the same apply (LIVE mode, fresh reading, three a day, snapshot for
  rollback). Prints the plan with every factor; writes only with `--yes`
  (the page asks the PIN — say so). See the section below.
- `horizon list` / `horizon show [ID]` / `horizon grade` / `horizon run
  --yes` — the Horizon page (`/horizon/`): the 5-10 year sector view,
  its tilts, its graded calls; `run` without `--yes` prints the cost
  (~1.5 USD, frontier model) and does nothing. See the section below.
- `preflight_live`, `why_no_trade`, `seed_components`, and
  `./deploy/ibkr-doctor` (read-only) were already there.

**The share allocator (shadow first).** Until now a live pool's share of
the account was a number typed once on the Follow form. The allocator
computes it instead — every four hours, at :05, after the sync has
stored a reading — and proposes; it re-sizes nothing on its own.

- *What it reads.* The last broker reading (must be under an hour old,
  or it proposes nothing and says so), the 90-day road that reading took
  (`BrokerEquityReading`, one row per sync, written by the sync ONLY —
  a missed sync writes no row, never a zero), and per follower pool four
  factors: graded evidence (this pool's LIVE closes, else the fleet's
  live closes in the same class, else its paper closes, else unmeasured
  = 1.0; NULL R is never counted as 0), regime fit from the brain
  context (risk-off with confidence trims stock/crypto/CFD), opportunity
  density (how much of the class's universe carries a flag or signal),
  and news risk (tighten-only; blind = 1.0 when the analyst has been
  idle two hours). A reader that fails costs a factor of 1.0 and a note
  on the plan, never the plan.
- *What it writes.* A `SharePlan` row in state PROPOSED with every
  number on it: raw share, floors and ceilings (2%–60% unless the pool's
  `extras["share_floor_pct"]` / `["share_ceiling_pct"]` say otherwise),
  the smoothed and day-capped target (10 points per pool per rolling
  24 h, counting what applied plans already moved), a "held" mark when
  the move is under 1 point, and the drawdown governor (full deployment
  to 5% under the high-water mark, 40% at 20% under; the rest is cash by
  construction). It never writes a pool's capital and never talks to the
  broker.
- *The two switches.* After `./deploy/dc exec web python manage.py migrate`
  (0026 creates both tables), `component on pipeline_share_allocator`
  starts the proposals — shadow, safe, and worth a week of reading before
  anything else. `component on share_allocator_mode_live` is the second
  switch: only then does Apply work, and it still takes the trading PIN
  on `/shares/` (or `--yes` on the shell) per plan, three plans per user
  per day. Applying writes each follower's `extras["account_share_pct"]`
  and re-splits the pools through the sync's own arithmetic at once;
  Rollback puts every share back exactly as the apply found it (the key
  removed where the pool was automatic).
- *Read it.* `shares list` shows the mode, the pending plans with
  "current → target" and one sentence of why per pool, the applied ones
  (rollback possible), and the last grade. `shares propose --user NAME`
  runs one proposal now and prints either the plan or the reason there
  is none ("no fresh reading (age 5400s)" means run the sync first).
- *The grade.* Twenty-four hours after a plan is proposed — applied,
  rejected or not — `grade_plans` (inside the same beat, or `shares
  grade`) scores it: Σ over pools of (target − current)/100 × the R that
  pool's LIVE closes earned in the window. Positive means the plan leaned
  toward what paid; "ungradeable" means nothing closed, which is not
  wrong. A run of negative grades in shadow is the reason not to turn
  LIVE on.
- *De-risk fast, re-risk slow.* The 10-point cap and the half-way
  smoothing are symmetric, and a 20% crash whose governor said 0.4 took
  three plans to reach the pools. Every plan now carries a MODE (the
  `mode` column, the badge on `/shares/`, the `mode …` line in `shares
  list`). **SHOCK** — the drawdown is past the 5% knee, or equity is 3%
  or more under its highest reading of the last 24 h, or the brain says
  `risk_off` / `blow_off` at 0.65 confidence or more (`unknown` never
  counts), or a shock plan was proposed in the last 24 h (the hold): a
  share only goes DOWN or holds, uncapped and unsmoothed, nothing is
  redistributed and what a pool releases is cash; floors still hold.
  **EXPANSION** — no shock, the reading IS the 90-day high-water mark
  and at least one pool's evidence is measured with a positive avg_r
  over ten fills or more: the upward allowance is 20 points a day (down
  stays 10). **NORMAL** — the rule exactly as above. The sync itself is
  a trigger: when the reading it just stored is a shock (drop or
  drawdown — no brain context on that path) it proposes at once, once
  per hour per user, and staff get "⚠ Shock plan proposed"; the 4-hourly
  beat is unchanged. Applying still takes the PIN — unless the third
  switch is on: `component on share_allocator_auto_derisk` (LIVE mode
  required too) applies a SHOCK plan that only LOWERS shares by itself,
  under the same daily cap and fresh-reading rule, with the same snapshot
  for rollback, an audit row whose decision reads `auto_derisk`, and a
  "⚠ Shares de-risked automatically" alert. A plan with any upward
  target — a pool entering at its floor counts — waits for a human, and
  a refused apply (daily cap, stale reading) leaves it PROPOSED. The card
  on `/admin-dashboard/` shows all three switches; `/shares/` shows the
  mode and its reasons in the KPI strip.

**Horizon: the 5-10 year view.** Every other agent looks hours to weeks
ahead. Horizon (`brain/horizon.py`) writes the platform's STRUCTURAL
view once a month — how each sector in its universe (the eleven US
sector ETFs plus gold, oil, long Treasuries, the dollar and bitcoin)
develops over 5-10 years, the risks that view must guard against, and
a tilt per asset class — and is held to account like every other
agent: each sector thesis ends in direction calls at 6 and 12 months,
graded by the calibration beat against the first bar at or after the
deadline, and `/horizon/` shows the Brier score and trust built from
them ("—" until ten calls have graded).

- *The switch and the cost.* `component on agent_horizon` arms the
  monthly beat (the 1st at 04:45 UTC). One run is ~1.5 USD on the
  frontier model, under the deep-tier reserve of the daily AI budget;
  a day whose budget is gone skips it cleanly. Off by default.
- *The commands.* `horizon list` (every run: status, model, cost, calls
  registered/dropped, age), `horizon show [ID]` (the sectors, tilts,
  calls and their grades — a REJECTED run shows the raw text the
  operator paid for), `horizon grade` (brier/trust for agent
  `horizon`), and `horizon run` (prints the cost and does nothing) /
  `horizon run --yes` (one synthesis now — the page's Run now button,
  superusers only there).
- *The prior, and its ceiling.* The share allocator reads the latest
  OK view (45 days at most) as its FIFTH factor: 1 + 0.05 × tilt ×
  confidence per asset class, so ±2 at full confidence is ±10% and
  nothing more. The rule: the prior is ±10% at most, by construction —
  a structural view never out-votes graded evidence, and no view, a
  stale view, or a class the view did not tilt reads ×1.00 with the
  reason on the plan. `/shares/` and `shares list` print the factor
  beside the other four.
- *What a bad answer does.* A garbled answer (a sector outside the
  universe, a tilt past ±2, a horizon that is not 6 or 12 months) is a
  REJECTED row with the raw text kept, never a view; a provider error
  is an ERROR row. Neither is read by the allocator.

**A healthy Gateway is not a logged-in Gateway.** The container's
healthcheck sees a process and a port. When the session behind it is gone
(a Client Portal login took it — converting currency counts — or the daily
IB Key push was never approved), the API accepts Sauron's socket and every
request times out: `positions request timed out`, `open orders request
timed out`, `account updates ... timed out`, and the sync returns
`unreachable`. The doctor's verdict now reads step 3 (the server's
`Authorization failed`) and step 5 (no reading for hours) before trusting
`(healthy)`, hides the `remove Client` churn that buries IBC's own lines,
and says the fix in order: approve the push on the phone; if none,
`./deploy/dc --profile ibkr restart ibgateway` (IBC logs in afresh, the
phone gets a push); then the sync. Restarting the workers changes nothing
in that state.


**No prose without a claim the platform can grade.** Every agent that
talks about a symbol now registers a direction call — symbol, up or down,
horizon, the price it was measured from: the strategy advisor's long/short
legs, the anomaly scan's `expected_direction`, and the calls block each
briefing ends with. The nightly calibration grades each call against the
first bar at its horizon (flat is a miss; no bar within 48h is "ungraded",
never "wrong"), and the trust score the strategist and the critic read is
built from those grades. `/calibration/` shows the ledger: who called
what, from which price, and what the market said. An agent whose views
never reach the block has a trust score of nothing, which is the truth.

**Pools are shares of the account.** A pool that follows the account takes
a share of the broker's equity reading — an explicit percentage, or blank
for automatic: followers without a number split what the explicit ones
leave, equally — and the broker sync retunes it every fifteen minutes, down
as well as up. Arm the manual lane with "follow account" and an optional
"% of account" on `/admin-dashboard/`; make a live bot follow from
`/asset-bots/` (Follow, share, PIN). Shares that do not fit in 100% are
refused at the click and, if they ever get in, retune nothing and raise an
alert. Hand-typed pools are still allowed and still measured against the
account by `preflight_live`, which also warns when armed pools together
exceed it.

**IBKR's 2,000 USD floor.** Under 2,000 USD of equity (or the equivalent)
IBKR refuses margin, short sales, currency and futures — Error 201, in
those words. That includes a plain long on a USD ETF from a EUR balance: the
purchase borrows USD, a loan is margin, and the order is refused. Below the
floor the account buys stocks and ETFs with settled cash **in the
instrument's own currency**, and nothing else; convert at IBKR first
(Client Portal → Transfer & Pay → Convert Currency). No forex, no CFDs, no
futures until the account is funded past the floor. `preflight_live` reads
the floor off the equity reading, blocks armed configs in margin classes,
and lists the symbols quoted in another currency as worth reading — the
reading is the base currency and cannot see cash already converted.
Leverage is not a setting that gets around any of this.

**Bars survive a mute venue.** Bars come from the venue a config fills on,
and a venue can go quiet without an error — an IBKR historical request that
never returns, a pacing refusal, a symbol it serves no history for. Every
IBKR request is capped at half a minute, and a symbol the venue gave no bars
for is written from the keyless public feed instead, tagged `*_public` so
`/forensics/` still says where a candle came from. A fresh instrument starts
with too little daily history for any evaluator; give it a year at once:
`./deploy/dc exec web python manage.py backfill_bars --from-configs
--intervals 1d,4h --bars 300`, then the indicator recalculation it prints.

**Watch `/health/` and `/forensics/`** rather than tailing logs: the first
answers "is the machine running", the second answers "why did it do that".

**Resource pressure** shows up first as Celery workers being OOM-killed.
`docker stats` will show it; the fix is a bigger box, or lowering worker
concurrency from `-c 2` in the compose file.
