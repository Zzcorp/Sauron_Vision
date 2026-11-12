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
exists until you create one. Then log out and log back in with it: a session
that set or changed its PIN opens and arms nothing until it logs in again
(closing a position and the kill switch work as they are).

Wrong PINs add up on ONE count per session, at every door that asks for the
PIN (core/trading_pin.py): the lock screen, the switches, a close, close-all,
both kill switches, TAKE TRADE, arming a bot or the manual lane, withdrawals,
the eToro Demo untick, change PIN. At a close, close-all, close-selected, a
kill switch or a stop that only tightens, a wrong PIN never logs you out and
the right one always works. Anywhere else the fifth wrong answer ends the
session, and a session that has used up its five is ended there before any
PIN is checked; only a fresh login (password and PIN) clears it, and
signing in again from the same browser is enough, with or without logging
out first. The login PIN pad allows five wrong answers per sign-in, then
asks for the password again.

## 5. Turn the platform on

**Everything ships OFF, including the master switch.** This is deliberate — a
freshly deployed trading platform should not start acting on its own — but it
means that until you do this, beat fires every scheduled task, the workers
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
- `scraper_sentiment` — StockTwits every 30 min (trending plus the
  starred instruments), keyless. Reddit joins only when
  `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` are in `.env`; without them
  the task reports "Reddit off" and runs on StockTwits alone — not a
  warning. Reddit closed self-service app creation in November 2025
  (reddit.com/prefs/apps no longer creates one; access is a manual
  request), so no keys is the expected state. With keys it covers
  r/wallstreetbets, r/investing, r/stocks, r/CryptoCurrency, r/Bitcoin.
- `pipeline_sentiment_agg` — hourly aggregation into per-instrument scores,
  from the raw StockTwits, Reddit and TradingView reads only. Before
  2026-10-24 each hour summed its own earlier rows, so the stored
  "aggregated" rows carry counts that doubled every hour. Rebuild them once:
  `./deploy/dc exec -T web python manage.py rebuild_sentiment_aggregates` (a dry
  run: what would change), then the same with `--apply`; or `--drop
  --apply` to delete them all and let the next hourly run write fresh ones.
  Raw reads are never touched.
- `agent_news_analyst` — AI turns headlines into structured sentiment.
  Needs `ANTHROPIC_API_KEY` and spends tokens; enable deliberately.

After editing `.env`, run `dc up -d` — **not** `restart`, which keeps the
old environment.

> "all on" beside *System* on `/ops/` turns on the master switch, the
> Telegram eye, the Morgul guards and the alarm bot (`telegram_alarm`,
> which moves no money; see "The alarm bot" below), and leaves every
> live-money switch
> OFF — `actuator_mode_live`, `meta_allocator_mode_live`,
> `share_allocator_mode_live`, `share_allocator_auto_derisk`,
> `capital_desk_mode_live`, `fractional_units_live`, `etoro_leverage_live`,
> `bots_venue_floor_live` and every other one the page names beside the
> button — and the Morgul brake with them.
> Each of those is its own decision: a live-money switch is turned on
> from its own toggle on `/ops/` with your trading PIN (the shell refuses
> it, and never asks for a PIN), the brake by its own toggle or
> `component on <key>`.

Confirm it took:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml logs --tail=50 worker-fast
# the "[GATE] Platform master switch OFF" stream must stop
```

## 6. Create your first bots

The fastest path is the seeded paper fleet — six configs (FX majors and
crosses, metals, energy, softs, megacap stocks), all paper (`--activate`
never arms a starter config since promoted to live: arm that one from
/asset-bots/ with your PIN):

```bash
docker compose --env-file .env -f deploy/docker-compose.yml exec web \
  python manage.py seed_bots --activate
```

**No broker account is needed for paper trading.** Bars and marks arrive
keylessly for every asset class (Binance public for crypto, yfinance for the
rest) within ~10 minutes of enabling the bots and the scrapers from step 5.
That refresh keeps the bars current; it does not give a new instrument the
history the long-window rules need (an SMA200 wants 210 bars). `backfill_bars`
does, for every class through the same keyless feeds — run it once after
seeding, and again for any instrument you add later:

```bash
./deploy/dc exec web python manage.py backfill_bars --from-configs --intervals 1d,4h --bars 300
```

### The proving run

The proving ground (`backtester/proving`, the `proving_ground` component,
off by default) judges every live rule and its short mirror on real 4h
history — next-bar fills, costs, a 30% holdout, a bootstrap bound — and
says no. It refuses to judge a symbol on less than **540 days / 800 bars**
of 4h history, and neither the scheduled refresh (the newest 200 bars) nor
the backfill above (300) ever fetched that much, so every verdict read
INSUFFICIENT. Run it once, in this order; no key is needed. The backfill
places no order, but a saved verdict (the `--save` step below, or the
nightly judge once the switch is on) sizes real money from the next live
entry: FAILED is refused on that class and side, PROVEN keeps full size,
anything else trades at a quarter. Preview with `prove rules` (no --save)
first:

```bash
./deploy/dc exec web python manage.py backfill_bars --proving     # every symbol the judge walks, 4h, 4000 bars deep (two years from Yahoo, more from Binance)
./deploy/dc exec web python manage.py prove data                  # who has enough history, who is still short
./deploy/dc exec web python manage.py component on proving_ground # the nightly judge (03:40 UTC) and the Sunday generator (03:50)
./deploy/dc exec web python manage.py prove rules --save          # judge the live rules now; verdicts on /evidence/
./deploy/dc exec web python manage.py bar_losers                  # the live rules' measured record; --apply bars the losers to paper
```

A rule whose verdict is PROVEN has beaten its costs out of sample; one
that is INSUFFICIENT still has too little history (run `prove data`) or
was judged on broken bars. The proving ground reads only a market: bad
bars and spikes are dropped (a broken entry bar with them, before any
trade is simulated); a price that jumps and holds is read by its cause —
an unadjusted split or a re-based feed is adjusted (`prove data` says
ADJUSTED), any other move is traded as the market it was, and a feed that
never settles on a level is left out of the run (BROKEN). A win past 20R
is excluded and a loss past 20R is capped at -20R, never dropped; past 2%
of a run past 20R the verdict is INSUFFICIENT. A `data:` line under a
verdict says what was not read as stored. The
verdicts are read by the setup memory and the ticket's odds, and, since
size by proof (`backtester/proving/proof.py`), by every live bot entry,
whether `proving_ground` is on or off: the switch runs the nightly judge
that writes them, not the gate that reads them.

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

**Once, after the update of 2026-10-24** (no account figure reaches a
reader who is not staff): a weekly review written before it was made from
the book's value, cash and P&L in money, and it is both the waiting Sunday
letter and what the Monday plan (every user's bell) reads; the plan reads
only a review of the last eight days. If the Saturday 10:00 UTC review ran
before the update, write a fresh one with `agent_weekly_review` on:

```bash
./deploy/dc exec -T web python manage.py shell -c "from ai_agents.tasks import generate_weekly_review as g; g()"
```

It cancels the older waiting edition unless a person approved, edited or
rescheduled it; cancel that one on `/admin-dashboard/newsletters/`. Then
rebuild the sentiment aggregates (`pipeline_sentiment_agg` in section 5).

**Once, straight after the update of 2026-10-31** (Yahoo's 4h on one UTC
grid): the public feed now builds Yahoo's 4h bars at 00, 04, 08... UTC.
For Yahoo series in the London, Berlin or Tokyo zone (Yahoo's forex
pairs, the European and Asian indices) the stored 4h bars sit on another
grid, and the first bar pass after the update writes the new grid BESIDE
them (the timestamp is part of the key). Until the prune below runs, the
newest stretch of those series holds both grids, twice the bars, and the
bots read them: the ATR stops, the swings and the 4h indicators. Wait for
the first bar pass (ten minutes), read the dry run, then delete what it
listed:

```bash
./deploy/dc exec -T web python manage.py prune_offgrid_4h         # the list, nothing deleted
./deploy/dc exec -T web python manage.py prune_offgrid_4h --yes   # delete what the list named
```

It deletes only the public feed's off-grid 4h rows that overlap an
on-grid row of the same instrument; off-grid history with nothing beside
it stays, and a venue's own bars are never touched.

**Once more, after the update of 2026-11-01** (the clean-up also clears an
old grid beside another old grid): the CET-zone indices (DAX40, CAC40,
IBEX35, STOXX50) had two old grids, both off the UTC grid (03, 07, 11...
and 02, 06, 10... UTC), and where both were stored before the new grid's
window the command above listed neither. Run the same two commands again
(whether or not the first clean-up already ran). Over each stretch where
two old grids overlap, it keeps one grid (the grid of the bars just before
and after the stretch, else the later anchor: 03, 07, 11... UTC in the CET
zone), one session at a time: a session where a grid starts or stops
keeps the other grid's bars whole, so the series changes grid between two
sessions and no hour loses its bar. It deletes a bar only when every hour
of it is in a bar that stays, or in a period the kept grid shows empty at
a session's edge; the dry run names the kept grid and why, line by line.
A session neither grid holds whole (both stop inside it) is listed as
left, never deleted, and then the command does not say "No off-grid 4h
duplicates of the public feed.". A venue's bars, and off-grid history
with nothing overlapping it, stay.

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

## The brokers (`/brokers/`)

One page, one row per broker, and for each row: what it can hold, whether it
is keyed, whether its session is alive, and which asset classes it is the
**primary** venue for. Nothing on the platform reads a broker the operator
has not made primary for something — a keyed, connected row with every box
unticked is read by nothing and traded on by nothing. That is the default.

**Precedence, when two rows claim one class:** `saxo`, then `etoro`, then
`ibkr`. Saxo holds the real listing where eToro holds a CFD on it. Two
brokers flagged for one class is a configuration mistake rather than a
strategy, so the page names the conflict and says which venue wins instead
of letting the router resolve it in silence.

**Keys are never typed anywhere but this page.** They are encrypted with the
platform's `FERNET_KEY` and stored in the database; they are not in `.env`,
not in the compose file, and not in any log. A key pasted into a terminal
is a key in that shell's history.

### eToro

Paste the **API key** and the **user key** from eToro's developer portal, and
tick **demo** for their virtual account. Then tick the classes this account
is primary for. eToro is a CFD venue: what it can hold is what its row says.

### Saxo, in two halves

Saxo is OAuth, so half of it happens at Saxo and half here, and the two must
agree character for character.

1. **At Saxo's Developer Portal**, create an application and register its
   redirect URI as exactly:

   ```
   https://<your-host>/brokers/saxo/callback/
   ```

   The path is fixed by `dashboard/urls.py`. A URI that lands anywhere else
   still *matches the portal*, so Saxo accepts the sign-in, the browser
   returns to a page that ignores `?code=`, and nothing happens — the
   failure is silent. The page refuses a URI whose path is not that one, and
   refuses `http://` outside localhost, because the authorization code would
   travel in clear text.

2. **On `/brokers/`**, save the app key, the app secret and that same
   redirect URI, tick **sim** for the simulator, tick the classes this
   account is primary for, then press **Connect Saxo**. You are sent to
   Saxo, you sign in, and the callback stores the session.

### SIM and LIVE are one row and two worlds

The same row serves both, and the `sim` box says which. Re-saving the key,
the secret, the URI or the sim box closes whatever session was open — a
session belongs to one application on one environment. Flipping the box
additionally **clears the stored equity, cash and position readings**,
because a simulated balance read as a live one is the kind of number that
sizes a real order. The history rows keep their own environment and are
never mixed; the drawdown governor reads only the environment in force.

### The session, and the forty-minute fact

The access token lives 1200 s and the refresh token 2400 s, and the refresh
token **rotates** on every use. `refresh_saxo_sessions` runs every 600 s —
four chances per token lifetime — and one missed cycle costs nothing.

The consequence worth knowing before it happens: **a box that is down or
paused for more than forty minutes comes back with a dead Saxo session.**
Nothing is broken and nothing is lost; the row will say `session: LOST`
with the time and the reason, and it needs one sign-in. That is a state,
not an error to wait out. The row distinguishes five of them: `none`,
`renewable`, `renewable (access expired, renewing next cycle)`, `EXPIRED`
and `LOST — <reason>`.

### Verify, in this order

```bash
./deploy/dc exec web python manage.py saxo_smoke --user <you>   # read-only, places NO order
./deploy/dc exec web python manage.py etoro_smoke --user <you>  # read-only, places NO order; names the write URLs it never calls
./deploy/dc exec web python manage.py treasury                  # what every broker holds
```

`saxo_smoke` exercises every read the adapter makes against the real SIM and
reports each in three states: `ok`, `refused` (Saxo answered and said no)
and `unknown` (the adapter, the network or the session is at fault). The
three are never collapsed, because "Saxo refused" and "our adapter is wrong"
call for opposite fixes. It is deliberately not runnable from `/ops/`: it
presents your Saxo session to an external service and prints the account's
balance.

`treasury` is the shell twin of **`/treasury/`** — both render the same
computation, so the page and the terminal cannot tell different stories.
Neither one calls a broker: they read the cached columns the sync task
writes, because a broker round trip does not belong on a render path. A
**dash** means never measured. It is not a zero, and the two are not acted
on the same way.

### One exit that is not like the others

Saxo under the `FifoEndOfDay` netting profile does not flatten on an
opposite market order — both lots stay open until the evening netting. The
engine asks the adapter and closes by `PositionId` on that venue. If the log
ever says a close **will leave BOTH lots open**, the row had no broker
position id: check `/treasury/` after the netting settles, because that is
one position the platform's own row cannot see.

## The Oculus (/oculus/)

The page above the others. They each answer their own subsystem's
question well; this one answers the operator's — **is the machine
turning, and which of its wheels are actually engaged?** It owns no data,
adds no arithmetic of its own, and writes nothing. Eleven cycles and the
book: the viewer's own book on top, then one panel per cycle — the forge,
the switches, the scan, the ladder, the signals, the evolution, the
personalities, the allocation, the horizon, the backtests, the
confidence. The switches and the forge are platform-wide and follow
`/health/`'s rule — staff only, as on `/ops/`: any other login reads the
other cycles and its own book, with no switch state on any panel, and
the forge's source-tree scan and migration plan run only for the reader
who gets their answer. It carries no form and no POST: every action is a
link to the page that holds it, behind its own PIN, and no broker or
model is called to draw it.

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
   name at the foot of the page — the book's included — with its reason
   in words (the kind of failure, never its message) and the command that
   fixes it, so a dash can never pass for a quiet zero.

4. **Every count names its window, and amber needs a threshold.** Each
   count says what it is counted over: `now`, `7 d`, `30 d` or
   `all time`; a code constant says `constant`; a stored reading counted
   `now` prints its age there instead (`probed 3 h ago`). A value turns
   amber (⚠) or coral (⨯) only past its stated threshold, with its
   words — a budget below zero, a late resolver, a call nobody grades —
   and a dash never does. The threshold reads the value as computed, not
   as rounded: a budget of −0.004 prints `-0.00` with its amber, and a
   governor of 0.998 prints 99, never the 100 that means "no drawdown".
   "Not due yet" is not late, and neither is "due, waiting for the next
   pass": detections inside their horizon (the resolver's own `not_due`),
   signals still live and calls whose due date is ahead are counted
   apart, and so is what fell due since the resolver's last scheduled
   pass (the flags' at 23:15 UTC, the calls' grader at 03:30 UTC, read
   from the beat, given five minutes to finish). Only what fell due
   before that pass and is still open is late, in amber.

**The book, in three money worlds.** REAL MONEY, DEMO and PAPER side by
side, never summed — there is no total. The split is
`dashboard.position_summary.world_of`, the rule the Horde and the
headband count REAL with: a row at a broker's demo account (`paper`
False, `broker_env` "paper") is simulated money and never counts as
REAL. Each world prints its open positions, its risk at the stops (the
desk's own `book_risk` arithmetic, per currency, never added across
currencies), the positions with no readable stop and, for REAL, the
closes pending at the venue. A world with open rows none of which has a
readable stop prints a dash for its risk, named at the foot, never 0.00.
Below sits **what the desk sizes with**:
its two venues, live and paper, exactly as `capital_desk.budget_for`
answers them, with its reason (the governor's "100" says which of its two
meanings it is), its currency and what it left aside. The governor and
the reason print the age of the broker equity cell they rest on
(`equity read 3 d ago`, and `stale` past an hour); an unreadable
governor's cause stays in the desk's log, never on the page. The desk's
live venue is `paper=False`, so it still counts the demo rows: a sentence
says how many, from the desk's own count, and their risk from the DEMO
rows themselves, under the desk's currency rule — in its currency, with
any demo row in another currency named as left out of its budget, and
per currency when no live config is enabled (after the kill switch, the
brake or `bot off` the desk adds every row whatever its currency). When
C1–C3 takes demo out of the desk the same sentence reads "counts REAL
rows only" by itself. The paper venue divides by the paper AND the live
pools, and the page says so in numbers. Money keeps its cents.

**What is stored, and how it is dated.** The page counts at load, except
these readings, each printed with its age. Redis keeps its data across
a deploy (the compose file runs it with an appendonly volume), so every
key the page stores carries the build, `<build>` = the image's sha and
build time: a new image, a same-sha rebuild included, reads afresh.

- the forge's guard scan, once per image (`oculus:forge:guards:<build>`;
  an unstamped image keeps it ten minutes): "scan checked at this build";
- the forge's migration plan, ten minutes
  (`oculus:forge:migrations:<build>`), because `migrate` can run on the
  same image;
- the backtests' "signals a run could not simulate", ten minutes
  (`oculus:slow:unsimulated:<build>`), counted again at once when a run
  completes;
- the confidence counts and the desk passes' lifetime counts, ten minutes
  each (`oculus:slow:predictions:<build>`,
  `oculus:slow:desk_passes:<build>`): the two whole-table reads with no
  index for their filter;
- the probe's two counts, which are `manage.py probe_routes`' own tally
  with its own time (kept seven days): a tally older than this build is
  a dash that says "no probe since this build" — the forge exists to
  catch the pages a deploy broke — and no tally at all is a dash that
  says "no probe stored: never run, cleared, or older than 7 days". The
  probe only GETs, as a superuser; after a deploy, fill the two counts
  with `./deploy/dc exec -T web python manage.py probe_routes`;
- the governor's broker equity cell, which the sync writes: its age.

A cache that cannot be read never costs the page: it counts instead.
A warm render (the readings above in place) reads 27 queries for staff
and 26 for any other login; a login whose broker account is keyed adds
the desk governor's two reads (the withdrawals and the equity history).
A cold render (none in place: the first GET of a build, then one GET
every ten minutes, when four readings expire) reads five more for staff
and three more for any other login. Both are tested.

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

Nothing to run. Open the page; `tests/test_oculus.py` and
`tests/test_oculus_truth.py` hold it to the rules above.

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

## The alarm bot (critical problems only)

The operator, 2026-09-28: the second keeper must not be flooded with
trading messages, and must be woken for real emergencies only. The Eye's
group keeps every fill, signal, digest and Morgul warning. The alarm bot
(`bot_program/alarm.py`) is a SECOND bot in a SECOND group — the operator,
the keeper and the alarm bot, **never the Eye's bot** — and it says one
kind of thing: a critical problem. A Morgul critical finding, a safety
check that cannot run, the brake stopping bots, automation paused, a close
the platform abandoned, a safety-critical task failing or stopped, a quote
feed not delivering, a live broker account not answering, the emergency
flatten having run. It never says that all is well, it never prints an
amount, and it obeys two commands: `/status` and `/stopall` (every bot
OFF, never on, unfilled live orders withdrawn; no position is closed).

Set it up once:

1. In Telegram, `@BotFather` → `/newbot`; keep the token. Leave Group
   Privacy **on**: the bot then hears commands only.
2. Create a NEW group with the operator and the keeper only, and add the
   new bot. The Eye's bot must not be in it. Then `@BotFather` →
   `/setjoingroups` → Disable, so nobody can add it to another group.
3. Put the token in `.env` as `TELEGRAM_ALARM_BOT_TOKEN=`, send `/status`
   in the new group (a command: with Group Privacy on, a plain message
   never reaches the bot), and read the group's id (a group id starts
   with `-`):

   ```bash
   ./deploy/dc up -d                     # not restart: up re-reads .env
   ./deploy/dc exec web python manage.py alarm --chats
   ```

   (or open `https://api.telegram.org/bot<token>/getUpdates` in a browser
   and read `"chat":{"id":…}`).
4. Put the id in `.env` as `TELEGRAM_ALARM_CHAT_ID=`, then:

   ```bash
   ./deploy/dc up -d
   ./deploy/dc exec web python manage.py alarm            # the verdict, and what it sees now
   ./deploy/dc exec web python manage.py alarm --test     # one test message to the group
   ./deploy/dc exec web python manage.py component on telegram_alarm
   ```

It refuses to run with the Eye's token, or with the Eye's chats
(`TELEGRAM_CHAT_ID`, any chat saved on `/notifications/settings/`), and the
"Alarm bot" row on `/health/` says why. The master switch does not silence
it — the pause is one of the things it reports; `component off
telegram_alarm` does, and so does "all off" beside System. A standing
problem is said again every three hours, a failing or stopped component
every 24, an event once; nothing is said when a problem ends. If `/status`
gets no answer: the switch is off (`manage.py component list`, then
`component on telegram_alarm`); the configuration is refused — a wrong
chat id, or the Eye's token — (`manage.py alarm` prints the verdict; the
"Alarm bot" row on `/health/` says why); the fast worker is down
(`./deploy/dc ps`, then `./deploy/dc logs --tail 100 worker-fast`); or
another poll holds the batch, and the next one answers. A plain message is
never heard with Group Privacy on, only a command; a second command inside
three seconds is dropped; so is a `/status` older than ten minutes after
an outage — `/stopall` never. If the group is ever upgraded to a supergroup
its id changes: the worker log names the new one, which goes in
`TELEGRAM_ALARM_CHAT_ID`.

## The private terms (the public pages' leak walk)

The Wall (`/wall/`) and the Book (`/book/`) are read by anyone, and this
repository is public. `core/leak_walk.py` walks every byte of both answers
at render time — the visible words, the style and script blocks, the
comments — for the handful of phrases the operator keeps private: a name,
a town, who holds what. Those phrases live in ONE place, the server's
`.env`, and nowhere in git:

    SAURON_PRIVATE_TERMS=a name|a town|another phrase

Pipe-separated, any case, any length (a five-word address is kept whole
and found whole; a term is matched on whole words only). A page that
carries one is NOT sent: the visitor sees a neutral placeholder ("This
page is not published right now"), the log names the page and the count
of terms, staff is told once a day, `/health/` and the daily digest read
the event. Fix the page text, redeploy, and the page publishes again.

Empty or unset, the walk still runs with its planted canary alone — the
platform needs no list to start, and says so once per process at INFO
and on `/health/`. Compose injects `.env` when a container is CREATED, so
after editing the list: `./deploy/dc up -d --force-recreate web`. The
tests walk the real list for free wherever it is in the environment
(`python manage.py test tests.test_the_book tests.test_wall_public_safety`
on the box).

## When the box itself goes silent (the dead man's switch)

2026-09-30: the hosting month ran out, the VPS stopped, and nobody heard.
Every alarm above lives ON the box: the alarm bot, the Eye, Morgul, the
digest. A dead box sends nothing, and its silence reads exactly like "all
is well". Only something OFF the box can notice it. Three layers, cheapest
first:

1. **Pay the box automatically.** At the hosting provider (Billing →
   the VPS → auto-renewal ON, with a card that does not expire before the
   next term). This is what failed on 2026-09-30.
2. **The dead man's switch** (`core/dead_man_switch.py`). The box pings an
   outside watcher after every 5-minute bot tick. When the pings stop,
   whether the box is down, Docker is dead, beat is dead, the default
   worker is stuck or the database is gone, the WATCHER raises the alarm.
   A tick that raises pings `/fail` at once (the exception's type only,
   never an amount). A paused platform still pings: the pause is the alarm
   bot's to report.
   - On <https://healthchecks.io> (free tier), **Add Check**: name
     "Sauron box", Schedule **Simple**, Period **5 minutes**, Grace
     **15 minutes**. Copy its ping URL (`https://hc-ping.com/<uuid>`).
   - **Integrations**: add e-mail, Telegram (the operator's own chat, or
     the alarm group) and/or the phone app, and tick them on the check.
   - Put the URL in `.env` as `DEAD_MAN_SWITCH_URL=` (https only; it is a
     secret: never paste it in a chat or a commit), then:

     ```bash
     ./deploy/dc up -d                                          # up re-reads .env
     ./deploy/dc exec web python manage.py dead_man_switch --ping   # the check turns green
     ```

   - Within 5 minutes the check reads "up" from the ticks themselves.
     To prove the alarm, stop the beat (`./deploy/dc stop beat`), wait for
     the period plus the grace, receive the alert, then `./deploy/dc up -d`.
3. **An outside uptime monitor on the site.** On <https://uptimerobot.com>
   (free tier): a monitor of type **HTTP(s)** on `https://<DOMAIN>/healthz/`,
   every 5 minutes, alerting the same people. `/healthz/` needs no login
   and answers 503 when the database is down, so a dead site, a dead
   Caddy or a dead database all read as down. The two layers see different
   deaths: the site can answer while beat is dead, and beat can tick while
   Caddy is down.

`DEAD_MAN_SWITCH_URL` empty means the switch is off and nothing is sent;
`manage.py dead_man_switch` says which, and names the watcher's host but
never the URL. A ping that cannot land is a WARNING in the worker log
(`grep "dead man's switch"`) and never delays a tick more than 5 seconds.

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

## The AI budget lines and the provider smoke (/ai-models/)

Since PR O0a the AI budget has two lines and one total. The Orcs' line
ships at 0 and stays there until you set it; even set, no Orc calls a
model until you also turn the minds switch on with your PIN (see "The
Orcs' minds (O2a)" below):

- **The total** is `AI_DAILY_BUDGET_USD`. Once the whole ledger's spend
  today reaches it, no call runs on either line. Since O0a this also stops
  the agents that never asked the budget before (the news analyst and the
  anomaly detector run through `BaseAgent.run`): they are refused at the
  total and never earlier. The pre-trade sanity check is exempt, because
  its caller turns any error into "go, full size".
- **The Orcs' line** is `ORC_DAILY_BUDGET_USD`, a cap. At `0` (the
  default) the line is off: no Orc call is allowed and nothing is held
  back for them. It stays `0` until you set it in `.env` (then
  `./deploy/dc up -d`); the minds switch `orcs_minds` is a second,
  independent gate. The cap holds even with
  `AI_DAILY_BUDGET_USD=0` (no total): that lifts the total and the core
  line, never the Orcs' cap, and with the line off it still refuses
  every Orc call.
- **The core line** is everything else (the Mind, the critic, the
  strategist, the reviewers). With the Orcs' line off it is the total.
  With it on, it is the total minus what the Orcs have actually spent
  today minus a $3 floor kept for their live urgent wakes. The deep and
  frontier tiers stop at 70% of a line's live allowance, as before.

Both variables are read when the containers start. To make a new value
bind (for example `AI_DAILY_BUDGET_USD=27`), edit `.env`, then:

```bash
./deploy/dc up -d                       # not restart: up re-reads .env
```

**Reading /ai-models/.** The TODAY cell keeps its first two lines (the
core line's spend and what is left of it) and adds a third:

- line off: `Orcs line off (ORC_DAILY_BUDGET_USD=0) · total stop $T`;
- line on: `AI $x of $y (= $T − Orcs spent − $3.00 floor) · Orcs $z of $C · total $t of $T`.

The card "The Orcs (read-only)" shows the ladder the Orcs read (model and
effort per rung). It is an unvalidated prior. Its sentence reads the
router's switch, `orcs_router`: while it is OFF, as it ships, once the
minds switch and the Orcs line are on, every wake a model reads is
answered on r0. Routing is recorded in shadow (O2b): each rendered wake
also keeps the rung a router would choose from its band and money world,
one effort per model until the smoke's PASS, and the Orc's page shows it
as "would route: r2 (deep tier, medium effort)"; recording it sends no
call and spends nothing. With the switch ON, that rung answers (see "The
Orcs' router (O2b)" below). Each rung's row counts today's calls (the
Orcs line's ledger rows, by the rung that answered), today's
would-counts (the wakes the router would send it) and today's probes;
below the ladder each band boundary shows its probe pairs and whether it
reads validated (see "The Orcs' probes (O2b)" below). It also says that
Fable (r5) stays at 0 through O2: its pair with its r4 blind twin is
bounded above the $3.00 the Orcs may hold in flight, so its gate cannot
open, with the frontier switch and its quota (see "Fable's gate (O2b)"
below). No tier setting on this page ever moves the ladder or the route,
and no override can be saved for an Orc agent name. The card also counts the day's Orc calls
from the ledger. The catalog table lists each model's cache-read price
and the shortest prefix it will cache.

**The provider smoke.** Two facts behind the Orcs' design need the real
API: how many tokens their dossier is on each model's tokenizer, and
whether a mid-conversation "effort-only" message keeps the prompt cache
while it changes the effort of the turn after it. `claude_smoke` measures
both on a synthetic dossier (no market data, no money, nothing private).
Nothing depends on the result until O1. It is dry by default:

```bash
./deploy/dc exec web python manage.py claude_smoke                # the plan and the cost bound; sends nothing
./deploy/dc exec web python manage.py claude_smoke --yes          # Sonnet 5.5, Opus 5.5, Haiku 5.5
./deploy/dc exec web python manage.py claude_smoke --yes --with-fable
./deploy/dc exec web python manage.py claude_smoke --yes --count-only   # token counts only, free
```

The printed cost bound assumes the worst (every prompt token written to
the cache at the 1-hour price on both calls, every answer at its
`max_tokens`): about $1.35 for the three models and about $2.45 more with
Fable. A normal run costs well under the bound. `--yes` needs
`ANTHROPIC_API_KEY` and refuses when the day's budget would not cover the
bound. The calls are booked under the agent `claude_smoke` (source
`Smoke:<time>:<model>:<effort>`) on the core line and show on
/ai-models/.

What each model's block means:

- `count_tokens`: the five layers and the whole request, and the ratio to
  the first model's count (the Opus and Fable tokenizer counts up to about
  1.35x Sonnet's).
- `PASS`: the second call (effort `xhigh`) read the cache written by the
  first (effort `low`), and wrote at least twice the first's output, both
  ended normally and both answers fit the schema. One cache serves every
  effort of a model.
- `FAIL ... read no cache`: each (model, effort) pair would need its own
  cache, so the Orcs' router must change model and effort per epoch,
  never per wake. The Orcs' router assumes a FAIL until a PASS is
  recorded for the family (`orcs smoke-verdict`): until then each model
  runs at one effort all day, Sonnet at r0's (low) and Opus at r2's
  (medium), whatever the band.
- `FAIL ... less than 2x`: the effort-only message did not govern the
  answer; every call would run at the model's pinned effort.
- `FAIL ... stop_reason` or `... schema`: the answer was cut short, refused
  or malformed; rerun once before drawing a conclusion.

Send back the whole printed block, from `THE PROVIDER SMOKE` to the last
line. A FAIL exits with `smoke FAILED: ...` and changes nothing on the
platform.

---

## The Orcs (journals by code; minds in shadow from O2a)

An Orc follows one open position from its birth to its close and keeps
its journal. In O1 every line of that journal is written by code: the
birth (the entry and its stop, so what 1R means), the thesis (the entry's
own record, or a reconstruction for a row that was open before the Orcs),
the army type and why, the care's and the venue's stop moves, a hand
levels edit, an event window, the reviewer's verdicts, the thesis checks,
a pending close and the close itself. **No order is sent and no stop is
moved; a model reads an Orc's wake only in shadow, behind its own switch
and budget line (O2a, below).** The Orcs write their own tables and one
stamp on the trade row (`metadata["orc"]`), nothing else.

**OFF on arrival.** The switch `orcs` (System) arrives OFF. While it is
OFF the platform behaves exactly as before: no Orc is born, no journal
line is written, the census beat (`orc-census`, every 5 min, fast queue)
skips. It is not a live-money switch, so the System group's "all on"
turns it on with the rest.

To switch it on:

```bash
./deploy/dc exec web python manage.py component on orcs
```

Within 5 minutes the census adopts every open position that may have an
Orc (adoption: the entry moment was missed, so the thesis is rebuilt from
the row). To see the plan first, or to adopt now:

```bash
./deploy/dc exec web python manage.py orcs adopt --open          # the plan: each open row, adopted or why not
./deploy/dc exec web python manage.py orcs adopt --open --yes    # adopt now (refused while the switch is OFF)
./deploy/dc exec web python manage.py orcs                       # the live Orcs and their last journal lines
```

Each adopted **real-money** position sends one line to its owner's own
channel (never the alarm group), for example "Orc #N adopted XAUUSD long
(advise). Its thesis is reconstructed; state yours on its page." Quiet
hours apply. Paper and eToro demo positions get journal lines only, and at
most 10 Orcs outside real money (paper and demo together) live at once
(`OrcSetting` `max_paper_orcs`). An eToro demo row sits on its own `demo`
seat, never on the real-money one, so its evidence is never pooled with
real money.

Rows that get no Orc: an entry still working at the venue (it is born at
its fill), an options row, and a row on a config no tick manages (a
config stopped by hand keeps its paper rows managed, and those get one).

**Switching it OFF** stops new births, new journal lines and the census at
the next tick; the Orcs already born keep what they wrote. With the minds
on (O2a), switching `orcs`, `orcs_minds` or the platform master OFF takes
no PIN and stops new model calls at the next claim. With `orcs_minds` OFF,
the next `orc-think` beat (within a minute) answers every waiting wake by
code (`minds_off`). With `orcs` or the platform master OFF, the minds'
worker and watchdog stop with every other Orc task, so a waiting wake
waits: when the switch comes back, one that waited under 30 minutes is
still read, and one that waited longer is never sent on its old dossier
(answered by code, `paused`, at the next claim when the Orcs were off for
over 10 minutes; else closed by the watchdog's next pass as usual). A call
already in flight finishes and is booked, or, with no bill, keeps its
money held until 00:00 UTC.

**The kill switch ends every idea** in its scope, whatever the orcs switch
says: each Orc is marked dead with no re-entry window before the sweep
closes its rows.

### O1b: the arms and the grade (O1: no model)

Each Orc now carries five counterfactual arms in its own table, priced by
one function from the same tick or venue bar: the **care ghost** (the
position care replayed on its own state, the reference), the **playbook**
(the care plus code rules on the menu of levels), the **Orc arm** (the
real row, recorded; after a hand act it carries on as a shadow), and two
mechanical exits from the proving ground (`chandelier3`, `staged`) walked
on the venue's 4h bars. Arms move only on the tick (the hook after the
care) and on bars; they never move a stop, send an order or call a model.
While the row is open the tick alone moves them; once it has closed, the
`orc-track-ghosts` beat alone does, so the two never overwrite each other.
An arm walks only the bars after its birth: an adopted row's history is
never replayed. An arm reads a bar only once it is final: the bar refresh
stores the bar still forming and rewrites it on its next pass, so a bar
that has just ended counts once that pass has stored the next one, or 12
minutes after its end. When the row closes, the arms that are still open
keep walking the venue's 1h bars, from the first bar that opens after
their last tick, up to a cap (a bot row: the later of its close and its
birth plus 1.5 times the class's no-progress hours; the manual lane: its
close plus 30 days). They are marked to market at the close of the bar
that spans the cap; a bar after the cap, every arm still open is closed at
the newest price known, so no idea outlives its cap. On those bars the
care-like arms run the care with the context the tick last gave them (a
manual-lane idea keeps the manual lane's care, which never cuts on a
clock), and the playbook keeps its own rules, every frame cut at the
bar's close: the thesis exit, the structure trail, and the draw trim on
paper. Each arm walks on its own: one that fails is logged and waits, and
the others go on. A row with no stop has no R: its two proving-ground
arms close at once and the idea is graded without numbers. An Orc arm
whose real exit nobody priced (the row's exit price unknown) is closed at
the cap on its last tick and flagged as inferred.

Three beats, all on the `slow` queue by exact name, all behind `orcs`:

- `orc-track-ghosts` every 15 min: the arms that outlive their row walk
  new bars; a pass with no new bar changes nothing.
The thesis's bar predicates read final bars only. The time predicate
needs the care's best excursion: while the care is off it reads
"unchecked", and the journal says so once.

- `orc-grade-closed` hourly at :40: a dead idea whose arms are all closed
  gets one grade (R only: the Orc against the care ghost and the playbook,
  the capture, won / honourable defeat / fault, and whether it counts for
  a seat). It counts when the Orc arm and the care ghost both resolved
  with an R, its arms were not seeded late, and the care ghost stayed
  faithful (its soft stop matched the care's on every tick the Orc arm
  recorded). A stretch with no tick is flagged on the grade, never
  excluded. From O2a it also counts the mind: the wakes a model read, the
  proposals applied to the Orc's shadow arm, the refusals, the share of
  invalid answers and the AI cost booked on the Orcs line. No seat reads
  it. The grade is journaled; nothing is sent.
- `orc-shadow-audit` Sundays 05:40 UTC: the care ghost of each idea that
  died in the last 7 days checked against the care's own exits, one
  journal line per idea, written once.

The same audit by hand, and the graded ideas grouped (never pooled):

```bash
./deploy/dc exec web python manage.py orcs shadow-audit --days 7             # prints only
./deploy/dc exec web python manage.py orcs shadow-audit --days 7 --journal   # and journals each line once
./deploy/dc exec web python manage.py scorecard --by orc                     # class, venue, bar source, level
```

With `orcs` ON the bar refresh also fetches the Orcs' symbols, 4h and 1h
only: a living paper idea's (at most the paper cap of them, oldest first),
a dead paper idea's whose arms still walk their tail, and a real idea's
whose row has closed while an arm still walks its bars. An idea a bar past
its cap asks nothing more. These requests come last in the pass, after
every config, so every config asks exactly what it asks OFF and an eToro
429 there stops only the Orcs' part. They are cut by the pass's deadline
like a config, stamp no mark on any row, and are counted apart (`orcs` in
the pass's result). A symbol an Orc part reached is the venue's for the
rest of the pass: the watchlist does not write the public feed's bars
over it. No 1d candle is asked: an Orc's daily
bars are the venue's 4h bars grouped by UTC day, built in memory, so the
1d table keeps the nightly EOD bars alone. A stock, ETF or Olog-hai idea
born once 60 such fresh days exist reads its thesis on 1d closes; one born
before reads 4h. OFF, the pass requests exactly what it did before.
Morgul's duplicate check (G8) reads the idea of a row's Orc stamp: the
legs of one idea are one position; there is no second leg before O5.

### O1c: the dossier, the day's weather and the war drums (O1: no model)

Each Orc now notices when something happens to its position, and writes
down what it would have seen. **No order is sent and no stop is
moved**; only the Orc tables are written, and in O1 nothing is sent to a
model (O2a's minds, below, read these wakes in shadow).

**Wakes are detected and recorded.** Right after the care, the tick looks
for a reason to think: the birth, a closed bar of the decision timeframe,
the mark near an invalidation level, +1R, +2R, +3R, -0.5R and -0.75R first
reached, half the best given back, the care moving or closing, the venue
refusing a stop, a met predicate, a hand edit of the levels, a close or an
entry in doubt, the metronome (while the market is open, the Orc's army
type's period after its last recorded wake: 4 hours for Line Orcs, every
hour for Mercenaries, once a day for the Olog-hai), a
high-impact print (3 hours and 1 hour before, 15 minutes after), a change
of the daily-loss mode, open risk at 80% of its limit, a change of the
posture, a close pending at the venue. The book is read in the Orc's own
money world: a real Orc counts real-money rows only (the gates also count
a demo row, eToro demo, Saxo SIM, OANDA practice or Alpaca paper, with
real money; the Orc never does), and a demo Orc has no book of its own,
so it never wakes on one. Urgent reasons are recorded at
once; the others at most every 15 minutes. A reason read from a state
(+1R reached, a close in doubt) fires once for the life of the position.
The tick only records the wake and its reasons (a quiet tick costs no
query, a recorded wake a handful); every 2 minutes the slow queue
(`orc-render-wakes`) renders each recorded wake as of its moment: its
complexity score (0 to 100, with its band: routine, material, complex,
extreme), the day's weather for its class (calm, eventful, stormy) and its
dossier. Its status then reads, in words on the Orc's page: answered by
code (`skipped` with its code: `minds_off` while the minds switch is off,
as it ships; a wake O1 rendered reads "no model before O2"), waiting for
its model call (`pending`, only with the minds on, O2a below), or `quiet`
when only a bar or the metronome woke it and nothing it watches moved: the
Orc then writes a one-line reading ("Nothing new: +0.4R, care breakeven at
1.0832, 4h structure unchanged"), which is also its latest note. A wake
whose render fails is marked `failed` in its components and is not
retried; the worker log says why.

**The dossier** is what a model will read from O2: the market's day (a
header at the roll, then one block per closed session: the board of 11
symbols, the prints, the regime, the posture, the Mind's report, the
strategist's brief, up to six headlines; each block reads the prints and
headlines from the previous session's end, so nothing between two
sessions is lost), the instrument (its frames,
structure, levels with their ids, positioning, COT, gaps), the position
(in R only, never money) and the tail (the session in progress, today's
tape, the menu and the candidates, the integrity verdict). Headlines and
calendar titles are fenced as untrusted text, a model's words as views;
instruction-like text is withheld; no news body is read. Every block is
stored once and a wake keeps the list, so any dossier can be printed
again:

```bash
./deploy/dc exec web python manage.py orcs dossier ROOT_ID             # the latest wake's dossier
./deploy/dc exec web python manage.py orcs dossier ROOT_ID --wake 2    # the wake before
./deploy/dc exec web python manage.py orcs actuals --days 14           # how many past prints carry an actual
./deploy/dc exec web python manage.py orcs actuals --days 14 --record  # ... and record it
```

From O2a, `orcs` (the status) also shows the minds: the `orcs_minds`
switch, the Orcs budget line, the model calls today, the wakes waiting for
a model, the money held for calls without a bill, the tickets in flight,
the stall alarm, the breaker and the ledger gaps. `dossier` also prints S,
the model's answer as kept with each V-rule's verdict, the officer's
verdicts and the booking, for a wake a model read. A proposal of an answer
never reaches the position: queued, it steps only the Orc's own shadow arm
at the next tick, priced at that tick, or expires. Three subcommands
prepare the minds without turning them on. `smoke --row` is dry without
`--yes`; with it, and only while the four gates are ON (the platform
master, `orcs`, `orcs_minds`, the Orcs line above 0), it reserves a ticket
for the whole bound, sends ONE call on the Orcs line from the Orc's latest
stored dossier (r0, or h0 with `--rung h0`; from O2b a wake's rung r1 to
r4 with `--rung`, only while the router's switch `orcs_router` is ON too,
answered at one effort per model until the smoke's PASS, both rungs
printed, never with a fallback; r5 only through Fable's gate, which in O2
refuses it with the clause that fails, nothing reserved or sent), prints
the answer and its validation, and writes nothing to the Orc. `smoke-verdict` records what
`manage.py claude_smoke --yes` printed for one model family; it sends
nothing. `tokens --s --yes` counts S at the provider's free token count
(the API key only: no switch, no line) and records it:

```bash
./deploy/dc exec web python manage.py orcs smoke --row ROOT_ID              # dry: the one call it would make
./deploy/dc exec web python manage.py orcs smoke --row ROOT_ID --yes        # one call (refused while a gate is OFF)
./deploy/dc exec web python manage.py orcs smoke --row ROOT_ID --rung r2    # dry: a routed rung (--yes: the router's switch ON too)
./deploy/dc exec web python manage.py orcs smoke-verdict --family sonnet --pass
./deploy/dc exec web python manage.py orcs smoke-verdict --family opus --fail effort cache
./deploy/dc exec web python manage.py orcs tokens --s --yes                 # free, never booked; recorded
```

When the venue's mark is older than 120 s (or not the venue's), the
decision frame's bars are stale, or the row cannot be read, the verdict is
critical and the Orc's menu holds no exit, trim, waiver or add: hold, a
plan revision and a tighten only. A posture that is not measured (with
`crisis_mode` OFF it never is), a blind news analyst or an unread calendar
only print a dash and never stop anything.

**Four beats, on the `slow` queue by exact name, behind `orcs`**, on UTC
times that cover both sides of the clock change (each pass does nothing a
second time):

- `orc-day-roll` at 21:03 and 22:03 UTC (17:00 New York): the day header
  per model family (Haiku, Sonnet, Opus, Fable: each tokenizer gets a
  block sized for it), the day's weather per user and class, the actuals
  measured;
- `orc-session-close` at :14 after each session's close, once the
  session's last 1h bar is final: that session's block per model family (a
  closed session is never rewritten, so a late article does not change
  it);
- `orc-hourly` at :06: the instruments' blocks, the class's hourly terms,
  the level-break and sweep drums (read on final 4h bars only);
- `orc-render-wakes` every 2 minutes: the recorded wakes' scores and
  dossiers; from O2a each wake is first merged with the Orc's waiting one,
  then admitted (`pending`, or answered by code).

From O2a two more beats, both behind `orcs`: `orc-think` every 60 s on the
`orcs` queue, which the `worker-orc` container alone consumes (two slots),
and `orc-minds-watch` every 5 minutes on `slow` (the stall alarm, the
stale wakes, the money held). With the minds switch OFF, as it ships,
`orc-think` only closes what waits and nothing is claimed.

With `orcs` ON the bar refresh also asks the keyless feed for the board's
symbols that exist as instruments (US10Y does not: the 10-year yield is
DGS10 in the macro line), 4h and 1h, after the watchlist's starred part,
cut by the pass's deadline and skipped in a late pass: about ten symbols.
The watchlist's held part is untouched. OFF, the pass asks exactly what it
asked before.

**The war drums** are published by code from facts it already writes (a
leg closed by its stop, break-even or a lock set, the mirror refused, a
turned thesis, a 4h close beyond a level, a sweep, an urgent headline the
price confirmed within 15 minutes, a print far from its forecast) and
routed by the census within one user's book only: to the same symbol, a
measured correlate (|rho| >= 0.7; an unmeasured pair never), a shared
currency leg or commodity complex, or the declared USD factor. Each Orc
reached gets one journal line per wave, "DR3: a stop at 1.08320 was hit on
EURUSD at 14:05 UTC; the price is 0.6 x ATR(1h) beyond it (same symbol,
hop 0)." Prices and ATR only: never another position's R or money, and
never a calendar title (a print is named by its currency and its calendar
row, "the USD print C412"). A level break listing several symbols reaches
the Orcs of each of them. In O1 a drum wakes nobody: the switch
`orcs_drums` (System, OFF on arrival) changes nothing until O2, where it
lets a drum wake the Orcs it reaches; the drums are journaled either way
while `orcs` is ON.

#### eToro's candle headroom, before the 15m and 5m candles

The Orcs' tape (eToro's 15m and 5m candles of the living Orcs' symbols,
then the board's) shares eToro's quota with the trading lane, so it sends
nothing until eToro's headroom is measured AND the switch `orcs_tape`
(System, OFF on arrival) is ON. The System group's "all on" alone sends
nothing. Measure first, on the demo account or in quiet hours:

```bash
./deploy/dc exec web python manage.py etoro_candle_headroom                     # a dry run: the plan, nothing sent
./deploy/dc exec web python manage.py etoro_candle_headroom --yes               # run the ramp (demo, or quiet hours)
./deploy/dc exec web python manage.py etoro_candle_headroom --yes --live        # ... on a live account
```

The ramp asks 2-bar candles with a gap that starts at 2 s and halves every
10 reads down to 0.25 s, and stops at eToro's first 429 or after 60 reads.
It is refused on a live account without `--live`, while eToro is sick,
within two minutes of a trading-lane 429, and while a bar pass or a
Mercenary tape pass is running. While it runs it holds the tape's lock;
if a bar pass starts, the ramp stops at once and records nothing (run it
again in a quiet minute). Its reads are background reads, never noted on
eToro's health, so after its 429 it leaves a two-minute marker every
candle pass yields to instead of meeting the same 429. It records the
clean rate, the rate at the 429, eToro's quota headers and the tape's
budget per bar pass (a quarter of the clean rate over the pass's candle
window). Then:

```bash
./deploy/dc exec web python manage.py component on orcs_tape
```

The tape runs last in each bar pass, cut by its deadline, within that
budget, stopping at the first 429, with no public-feed fallback and no
venue mark stamped on any row. The Mercenaries' own symbols are also
refreshed every 5 minutes (`orc-tape-mercenary`, fast queue), which stands
aside while a bar pass is running and gives way, at its next candle read,
to one that starts. Every pass of it is counted on the `orcs_tape` row (a
pass with no Mercenary holding a position is a success that read nothing;
an unmeasured headroom is a warning in words). To stop it:
`component off orcs_tape`.

### O1d: where the Orcs are seen (O1: no model)

Everything below is read by code from the Orc tables, only while the
switch `orcs` is ON. No new switch, no new beat, no new queue and no tick
hook: switching `orcs` OFF puts every page back to what it was before the
Orcs, byte for byte, and `/orcs/`, `/orcs/<number>/` and `/orcs/seats/`
answer 404 as they did before (the record stays in the tables and reads
again once the switch is ON). The route probe (`manage.py probe_routes`)
counts those two argument-free pages under "off" while the switch is
OFF, never under "missing", so the forge does not report them. Nothing
here sends an order, moves a stop, calls a model or notifies anyone.

**On Telegram** (your own Eye chat, never the alarm group):

```
/orc 12            one Orc: rank, state, R at the last tick and best, the
                   stops its venue and the care hold (once the position is
                   closed: where it closed and the R it booked, never a
                   stop), its thesis and what invalidates it, its latest
                   note, the last fact written by code, the next wake, the
                   care beside the position, its army, and its page. A
                   leg's number works too.
/orcs              every Orc on watch, one line each (20 at most)
/orcs forex        the same, one class
```

R and prices only: never a balance, an amount or a quantity. Your own
thesis shows as you wrote it, or "Withheld: this line may name an amount
of money." when it names one; the Horde and the positions page say the
same. The stops line names the row's own venue (eToro, eToro demo, OANDA
practice, Saxo simulation...). While
`orcs` is OFF, `/orc` is ignored like any unknown command and a quoted
"orc 12" goes to Sauron as a question, as before. `/orc 12 <question>`,
`/orc 12 stand down` and `/orcs off` answer in words and change nothing:
no Orc acts on a position, and none answers questions yet. From O2a `/orc`
also says the Orc's model calls today (a count, never money).

**On the platform:**

- **The Horde.** Each seat with an Orc shows its label and "L0 · Snaga"
  at the card's foot; the dossier's THE ORC box shows its state, thesis,
  what invalidates it, the risk at the venue's stop, the care beside the
  position, the complexity score of its last detected wake and what
  answered it ("No model (code only)" for a code answer, or the rung that
  read it in shadow, in tier words: "r0 · balanced tier, low effort", or
  with the router's switch on a routed rung such as "r2 · deep tier,
  medium effort"; never a model or a cost), the dossier's
  integrity, its journal, the drums it heard
  and a link to its page. Each class band shows the day's weather. The
  answer's `v` is 2 while `orcs` is ON, 1 while OFF.
- **The positions page.** One muted line under the symbol of an open row
  an Orc follows ("Orc #12 · L0 · Snaga, class · invalidates on a 4h close
  below … · no plan yet · "Nothing new: +0.4R…" 14:05 · risk 1.0R of
  2R": the rank and the commission, the first invalidation, the plan
  ("no plan yet", or "a plan in shadow" once a model wrote one, drawn by
  code), the latest note and its time, the risk at the stop the venue
  holds); the dwell card adds its plan, the comparison with the care and
  its last three journal lines. The comparison prices the Orc's arm (the
  position itself, or, once an Orc's proposals stepped it, its shadow
  arm, so named) and the care ghost on the same tick, at the closing side
  of the spread, with what each banked, so two arms that took the same
  steps read the same R. None of the Orc's proposals is applied to the
  position. The history tab is unchanged.
- **The close dialog.** A row an Orc follows shows its note beside the
  early-close warning: its rank, state and plan, the thesis, the latest
  note and the last fact written by code (your own thesis is never shown
  as a fact). Information only: the close itself, its PIN rule and
  close-all are unchanged.
- **`/orcs/`** lists your Orcs on watch, those that ended in the last 30
  days with their grade, and the seats they sit on. Staff also see the AI
  spend lines there: the Orcs line beside the minds switch, and the day's
  Orc calls from the ledger.
- **`/orcs/<number>/`** is one Orc: its thesis (the entry's, or the one
  reconstructed for a row that was open before the Orcs) and its
  predicates, your own thesis, the plan, the journal (facts written by
  code and notes drawn apart, your words marked as yours), the arms, the
  detected wakes with their status in words and the rung a model read
  them on, the proposals in shadow with the officer's would-verdict and
  their status, the refusals, and the grade. A leg's number opens its
  idea.
- **Your thesis.** The form on an Orc's page keeps your thesis beside the
  entry's, in your words (600 characters at most). It is journaled as
  yours, never as a fact, and changes nothing the care does. It is
  refused while `orcs` is OFF and on an idea that has ended.
- **`/orcs/seats/`** (staff only) shows every seat by bar source, never
  pooled: graded ideas, the mean Δ against the care with its 80% bounds,
  and the capture; then each army type by venue, class and bar source,
  with its n, mean Δ and 80% bounds. Only the grades that count for their
  seat enter a statistic. Δ measures the Orc's shadow arm (its proposals
  applied in shadow, when it has any) against the care ghost; no seat
  holds any power.

The adoption line sent for a real-money row now opens that Orc's page.

To check, with `orcs` ON:

```bash
./deploy/dc exec web python manage.py orcs                  # the live Orcs, their numbers
# then open /orcs/ and /orcs/<number>/, and send /orc <number> on Telegram
```

### The Orcs' minds (O2a)

From O2a a model may read each Orc's wakes, in shadow, on the Orcs' own
budget line. It ships OFF behind two independent gates: the switch
`orcs_minds` ("Orc Minds (models in shadow)", System, OFF on arrival,
left OFF by "all on", turned on only with your trading PIN at /ops/) and
the Orcs line (`ORC_DAILY_BUDGET_USD`, 0 = off). A model is asked only
while both are on, with `orcs` and the platform master. **Nothing a model
decides sends an order, moves a stop or changes a size**: its plan is
drawn by code, and each proposal steps only the Orc's own shadow arm and
is graded against the care ghost. Its note is filtered for money before
anything shows it, and no account figure is sent to it.

A wake's life: the tick records it (`recorded`); the render pass
(`orc-render-wakes`) merges it with the Orc's waiting wake, writes its
dossier and admits it: `quiet` (nothing new), answered by code (`skipped`
with its code, for example `minds_off` while the minds switch is off, or a
day cap, the triage, the spacing), or `pending`; `worker-orc` claims it
inside the Orcs line, sends one call (on r0 while the router's switch is
OFF, as it ships; see "The Orcs' router (O2b)"), validates the answer and
settles it: `done` (answered in shadow), `refused` (by the validator),
`failed`, `late` (it came back after the position closed: kept, applied to
nothing), `stale` (not answered in 30 minutes while the worker was
silent: the care holds the idea) or `merged`. The Orc's page shows each
status in words, with the rung that read it and, while that is another
rung, the one a router would choose, recorded in shadow ("would route: r2
(deep tier, medium effort)"): while the router's switch is OFF, r0 answers
every wake a model reads.

To turn them on, in this order:

1. Run the provider smoke (about $1, on the core line) and record what it
   printed, one verdict per model family:

   ```bash
   ./deploy/dc exec web python manage.py claude_smoke --yes
   ./deploy/dc exec web python manage.py orcs smoke-verdict --family sonnet --pass   # or --fail and what failed
   ```

2. Optionally count S, the Orcs' doctrine (the provider's free count,
   never booked):

   ```bash
   ./deploy/dc exec web python manage.py orcs tokens --s --yes
   ```

3. Set the line in `.env`: `ORC_DAILY_BUDGET_USD=6` for the first week,
   and raise `AI_DAILY_BUDGET_USD` by the line plus the $3 floor (24 with
   the core's 15). Both are read when the containers start:

   ```bash
   ./deploy/dc up -d                       # not restart: up re-reads .env
   ```

4. Check that `worker-orc` consumes the `orcs` queue:

   ```bash
   ./deploy/dc exec worker-orc celery -A config inspect active_queues
   ```

5. On /ops/ (Switches, System), turn on "Orc Minds (models in shadow)"
   with your trading PIN. The shell's `component on` refuses this key and
   points to /ops/, and the Django admin will not turn it on either.
6. Check: `./deploy/dc exec web python manage.py orcs status` (the minds
   switch, the line, the model calls today, the wakes waiting, the money
   held).

What they may spend: at most `ORC_DAILY_BUDGET_USD` per UTC day ($6.00
proposed for the first week: about $4.27 to $5.14 a day for 10 positions
on r0 under the triage). Each call is reserved at its bound before it is
sent (about $0.20 at most on r0; up to about $1.37 on a routed Opus rung,
below) and booked at its real cost; inside the
line each Orc spends at most $2.00 a day on real money and $0.50 on paper
and demo, routine wakes 75% of that. While the line is on, the core line
is the total less what the Orcs actually spent, less the $3.00 floor.

To stop them: turning `orcs_minds`, `orcs` or the platform master OFF
takes no PIN and stops new calls at the next claim.
- `orcs_minds` OFF: the next `orc-think` beat answers every waiting wake
  by code (`minds_off`).
- `orcs` or the platform master OFF: the task gate stops the minds'
  worker and watchdog with every other Orc task, so a waiting wake waits,
  with no code. When the switch comes back, a wake that waited under 30
  minutes is still read; one that waited longer is never sent on its old
  dossier (answered by code, `paused`, at the next claim when the Orcs
  were off for over 10 minutes; else closed by the watchdog's next pass
  as usual).
- A call already in flight finishes and is booked or, with no bill, keeps
  its money held until 00:00 UTC; an answer that comes back while a gate
  is OFF is kept as late (`minds_off`, `orcs_off`, `platform_off`) and
  applied to nothing.

Setting the line back to 0 (then `./deploy/dc up -d`) refuses every Orc
call: the next claim answers each waiting wake by code (`line_off`).
Nothing is notified.

### The Orcs' router (O2b)

Every wake the render pass writes also records the rung a pure router
chooses from its band and money world (table v1: routine r0; material r1
on paper and demo, r2 on real money; complex r3; extreme r4, Fable's r5
staying closed through O2). The Orc's page shows it as "would route: r2
(deep tier, medium effort)". The switch `orcs_router` ("Orc Router (routed
rungs in shadow)", System, OFF on arrival, left OFF by "all on", turned on
only with your trading PIN at /ops/) decides whether that choice answers:

- OFF, as it ships: every wake a model reads is answered on r0, and the
  router's choice is only recorded.
- ON, with the minds on: the wake's dossier is written once for the routed
  model's family and the wake is answered on its routed rung, one effort
  per model until the smoke's PASS for that family. Without a recorded
  PASS, Sonnet answers at r0's effort (low) and Opus at r2's (medium): r1
  answers as r0, r3 and r4 as r2, and the router's own choice stays on
  the page. The card says the rung that answered in tier words, for
  example "r2 · deep tier, medium effort", never a model or a cost. A
  real-money wake on r2 to r4 also names Opus 5 as the server's fallback
  for a refused answer, and its reservation counts that fallback too;
  paper and demo wakes, and `orcs smoke`, name none.

To turn it on, in this order:

1. Record the smoke's PASS for each family, as `claude_smoke --yes`
   printed it. Without it the router still answers, at one effort per
   model:

   ```bash
   ./deploy/dc exec web python manage.py orcs smoke-verdict --family sonnet --pass
   ./deploy/dc exec web python manage.py orcs smoke-verdict --family opus --pass
   ```

2. Set the line at $10 in `.env` (`ORC_DAILY_BUDGET_USD=10`) and raise
   `AI_DAILY_BUDGET_USD` to 28 (the core's 15, the line and the $3 floor),
   then `./deploy/dc up -d`.
3. On /ops/ (Switches, System), turn on "Orc Router (routed rungs in
   shadow)" with your trading PIN. The shell refuses this key and points
   to /ops/, and the Django admin will not turn it on either.
4. Optionally smoke one routed rung, dry first:
   `orcs smoke --row ROOT_ID --rung r2`, then the same with `--yes`.

What it may spend: still at most `ORC_DAILY_BUDGET_USD` per UTC day. For
10 positions that is about $5.88 to $11.48 a day of demand at central
output, against $4.47 to $5.36 on r0 alone; under a $10 line a stormy
central day answers about 35 wakes by code. An Opus call is reserved at
its bound before it is sent: about $0.55 to $0.87 on paper and demo, and
on real money, with its fallback, about $1.05 on r2, $1.21 on r3 and
$1.37 on r4. Inside the line, calls on the deep tier (r2 to r4) stop at
70% of the line, counting the money in flight and held, except a
real-money urgent wake; the triage, each Orc's day caps and the $3.00
held for calls in flight still bind.

An Opus call may run past 30 minutes inside its wall time (about 36
minutes on r3, 58 on r4): a wake that waits behind it, its own Orc's next
wake included, is answered by code as a backlog after 30 minutes, and no
Orc goes to the care for that wait. Only a worker with no call in flight,
none claimed and none settled for 30 minutes is silent, which hands the
waiting wake's Orc to the care.

To stop it: turning `orcs_router` OFF takes no PIN. A wake already
waiting is answered on r0 at the next claim, re-priced on r0 (its stored
dossier still fits), and every later wake is answered on r0, its route
only recorded. A call already in flight finishes on its rung and is
booked.

### The Orcs' probes (O2b)

A probe measures the rungs beside the one that answered: beside a paper
or demo wake a model read (answered in shadow, or refused), a
neighbouring rung reads the same stored dossier again, blind to that
answer, and the two answers are kept side by side and graded. The switch
`orcs_probes` ("Orc Probes (neighbouring rungs in shadow)", System, OFF
on arrival, left OFF by "all on", turned on only with your trading PIN at
/ops/) decides whether any is sent. A probe is never sent beside real
money, and nothing it decides is applied: it writes no plan, no proposal,
no note, no journal line and no card line, and it never counts in the
Orc's own day caps. It is kept only in the probe pairs' table and the
ledger, billed on the Orcs line.

Which, beside paper and demo wakes only: h0 on calm and eventful days
(none on a stormy day), and the rung across a band boundary when the
wake's score sits within 5 of 30, 55 or 75 (for example r1 beside an r0
wake at 27), one effort per model until the smoke's PASS, as for a wake.
A boundary pair compares the two rungs on either side of its boundary, so
a boundary probe goes only beside a wake answered on its own route's rung:
while the router's switch is OFF, r0 answers every wake, and only a wake
whose route answers on r0 too (a routine wake near 30, for example) gets
one. A probe sends no fallback: a refused answer is kept as invalid.

When: `worker-orc` sends them after its wakes, last of all: while a
real-money wake waits for its call, none is sent. A probe goes within 15
minutes of the answer it stands beside, else it is dropped; each one is
billed once.

What they may spend: their own allowance, `probes_usd_per_day`, by
default 15% of the line ($1.50 at $10), read at once; an explicit value
is in dollars. A user gets at most 6 boundary probes and 40 h0 probes a
day (`probes_per_day`). Inside the line every probe also stays within
C − R (the real-money non-urgent class), the 70% deep share for an Opus
rung and the $3.00 held for calls in flight. That is about $0.48 a day
for 6 boundary probes on r1, plus cents for h0, and never more than the
allowance. Both settings bind at once, with no restart:

```bash
./deploy/dc exec web python manage.py shell -c "from bot_program.orcs.models import OrcSetting; OrcSetting.objects.update_or_create(key='probes_usd_per_day', defaults={'value': 1.0})"
./deploy/dc exec web python manage.py shell -c "from bot_program.orcs.models import OrcSetting; OrcSetting.objects.update_or_create(key='probes_per_day', defaults={'value': {'boundary': 6, 'h0': 40}})"
```

Where to read them: /orcs/seats/ (staff) adds the ladder table, one row
per kind, boundary and money world: the pairs, the completed blocks of
20, each side's valid answers, how often both named the same action and
level, each side's forward R over the next final decision-frame bar after
the later answer, and each side's cost per pair. /ai-models/ counts each
rung's probes today and shows each boundary's state: validated after two
completed blocks. The state is shown only: no router reads it, and the
ladder does not change.

To turn them on, with the minds switch and the Orcs line on: on /ops/
(Switches, System), turn on "Orc Probes (neighbouring rungs in shadow)"
with your trading PIN. The shell's `component on` refuses this key and
points to /ops/, and the Django admin will not turn it on either. To stop
them: turning `orcs_probes` OFF takes no PIN; the next probe is not sent,
and one already in flight finishes and is booked.

### Fable's gate (O2b)

Fable (r5) stays at 0 through O2. The router sends an extreme wake to r5
only when every clause of Fable's gate holds, read in this order, the
first that fails kept in the route on the wake's journal entry as
"extreme: r4, ..." (no page shows it): real money; the band is extreme; a
frontier quota is left today; the frontier switch is ON; the pair fits
under the wake's class's ceiling and the deep tiers' share; the pair fits
under the $3.00 the Orcs may hold in flight; the router's switch
(`orcs_router`) is ON, since no dossier is written for Fable while it is
OFF; and that dossier, written for Fable at 1.35 times the tokens, is
within its size cap (one that is not is written again for r4, which
answers it). Otherwise the wake is answered as any other: while the
router's switch (`orcs_router`) is OFF, as it ships, r0 answers every
wake a model reads, extreme ones and real money included; with it ON, r4
answers (r2, at Opus's one effort, until the smoke's PASS for Opus).

The pair is r5 with its r4 blind twin. The twin reads the same stored
dossier on r4 (on r2, at Opus's one effort, until the smoke's PASS for
Opus), blind to r5's answer, with no fallback, and is kept only as a
`twin` pair in the probe pairs' table on /orcs/seats/; r5's answer is the
Orc's, and r5 is sent only once its twin was. Both are reserved together
at the wake's claim, priced at the dossier's size cap: r5's bound with its
fallback, about $2.69, and the twin's, about $0.88 on r4 ($0.56 on r2):
about $3.57 in all ($3.25 before Opus's PASS). That is above the $3.00 the
Orcs may hold in flight, so the gate cannot open in O2, whatever the
switch and the quota say: no r5 and no twin call is sent, and Fable adds
$0.

- The switch `orcs_frontier` ("Orc Frontier (Fable and its blind twin in
  shadow)", System, OFF on arrival, left OFF by "all on") takes your
  trading PIN at /ops/ to turn on; the shell's `component on` refuses it
  and points to /ops/, and the Django admin will not turn it on either.
  Turning it OFF takes no PIN: a wake already admitted on r5 is answered on
  r4 at its claim, and a pair whose switch reads OFF at the send sends
  nothing.
- The quota is OrcSetting `frontier_per_day`, 0 by default: the r5 calls a
  user may make a UTC day, across all classes, less those made today (and
  those in flight). The day's weather row shows the setting's value; the
  router never reads that row. It binds at once, with no restart (in O2
  it opens nothing, the pair being above the floor):

  ```bash
  ./deploy/dc exec web python manage.py shell -c "from bot_program.orcs.models import OrcSetting; OrcSetting.objects.update_or_create(key='frontier_per_day', defaults={'value': 0})"
  ```
- `orcs smoke --row ROOT_ID --rung r5` goes through the same gate on the
  Orc's latest stored wake and is refused with the clause that fails;
  nothing is reserved or sent.

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
`frontier` tier — Claude Fable 5.1, 2.5 times the deep tier's Opus 5.5
price, thinking always on. Every other agent stays on its tier; change any of them on `/ai-models/`
(or `AI_MODEL_FRONTIER` in `.env`). The generator reads the evidence
ledger — what each rule has proven in paper and live — and cites it. Its
proposals land as draft setups in RESEARCH stage; switch
`generator_auto_research` ON on `/health/` and it arms them itself: the
scanner grades their signals, the stage gate keeps every bot from trading
them, the promotion ladder decides the rest, and the brain page still lets
you reject one. A safety refusal by the frontier model is not an outage:
the provider re-runs the call once on Opus 5 and says so in the log. An
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
  knows but the database does not before setting it. A live-money switch
  (`LIVE_MONEY_SWITCHES` in `core/platform_control.py`) is never turned ON
  here: that takes your trading PIN, which the shell never asks for, so the
  command refuses the whole list, changes nothing and names `/ops/`, where
  the switch's own toggle takes the PIN. `component off` stays free.
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
  anything else. `share_allocator_mode_live` is the second switch, turned
  on from `/ops/` with your trading PIN (the shell refuses it): only then
  does Apply work, and it still takes the trading PIN
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
  switch is on: `share_allocator_auto_derisk`, turned on from `/ops/`
  with your trading PIN (LIVE mode required too) applies a SHOCK plan that only LOWERS shares by itself,
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
first bar at its horizon (flat is a miss; no bar within 48 of its market's
own open hours — a weekend is not an outage — is "ungraded", never
"wrong"), and the trust score the strategist and the critic read is built
from those grades. `/calibration/` shows the ledger: who called what, from
which price, and what the market said. An agent whose views never reach
the block has a trust score of nothing, which is the truth.

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

**The venue floor for bots (`bots_venue_floor_live`, OFF on arrival).** A
bot risks a small share of its pool per trade (`extras["risk_per_trade_pct"]`,
0.25% unless set). On a small account the size that gives is often under
eToro's smallest size: 1,000 USD of exposure on forex, indices and
commodities, 10 USD on stocks and crypto, and one whole share on a stock
while Fractional Units is off. The bot then opens nothing and records
`venue_min_size` or `sized_to_zero`. With the switch ON, such an order opens
at the venue's smallest size instead.

- *The size it opens at.* eToro's minimum for that order plus 1% (the order
  leaves minutes after it is sized, and a quote a hair lower would put the
  exact minimum under it), rounded up to the bot's own step: 100 units on
  forex and one whole share on a stock while Fractional Units is off, 1 unit
  and 0.0001 share with it on. A pair whose base is the dollar (USDJPY) opens
  at eToro's figure in units, 1,000, with nothing added: no price is in it.
  A bot with a typed multiplier opens at the larger of eToro's minimum
  exposure and that multiplier's minimum margin (at 2x a crypto order is at
  least 20 USD).
- *What bounds it.* The loss at the stop of that size must be at most
  **MAX BOT FLOOR RISK (%)** of the bot's pool, set on `/setup/` beside MAX
  BOT LEVERAGE (2 by default, 0.1 to 7, never above the 7% hard cap of every
  trade). It is a percentage of the pool's own figure, at the stop the order
  is sent with; where eToro then holds a wider stop than the one sent, the
  fill message says so and the loss can pass the ceiling. Its notional must
  also stay inside the class's own cap (4 times the pool on forex, 2 on
  indices and commodities, 0.2 on stocks and crypto, or the bot's
  `extras["max_notional_fraction"]`). The smallest pool that can be raised
  is the larger of two figures: the minimum exposure times the stop's
  percentage divided by the ceiling (1,010 USD with a 1.5% stop at 2%: a pool
  of about 760), and the minimum exposure divided by the class's cap (about
  505 on an index or a commodity, 250 to 280 on forex). Then every other
  limit judges the raised size as it judges any size: the single position,
  the open risk, the notional multiple, duplicates, theme legs, eToro's own
  row, the fees, the cash, the margin and the pledge ceiling, the last look.
- *What is never raised.* A paper bot, and a live bot's entry that its rule's
  stage sends to paper. The hand-taken TAKE TRADE ticket, which has its own
  smallest size. A bot routed to another venue than eToro. An instrument
  whose minimum eToro did not state today, and a minimum the operator
  declared (`extras["venue_min_notional"]`). A size that was zero before any
  rounding (a risk per trade of zero, a setup the stop floor skipped). An
  instrument that is not quoted in US dollars, outside forex. A day past MAX
  DAILY LOSS, read at the proposal and again at the order. A symbol eToro
  refused in the last 12 hours, on that bot or on another bot of the account.
- *Leverage.* A bot with no `extras["leverage"]` lets the chooser of the
  attack mode pick the multiplier for such an entry, inside every leverage
  rule (the switch `etoro_leverage_live`, the class ceilings, eToro's list,
  MAX BOT LEVERAGE, the posture's cap). MAX SINGLE POSITION then counts the
  margin at the multiplier chosen, so the class's notional cap and MAX
  NOTIONAL MULTIPLE are what bound the notional of a raised entry. A bot with
  no multiplier whose own size already clears the minimum still goes at 1x,
  as before. A stock or crypto buy is the asset itself at 1x and a CFD above
  it: eToro charges a fee each night it is held, and no filter here counts
  that fee. The fill message says "as a CFD" when the chooser levered such a
  buy. MAX BOT LEVERAGE 1 keeps every raised entry unlevered. With
  `etoro_leverage_live` off it goes unlevered too, and the full notional must
  then fit the single-position limit and the free cash. A bot with a typed
  number keeps it.
- *Fractional Units decides the step.* Off, a stock bot sends whole units:
  a stock is raised to one whole share, and an index (one unit is far above
  any small pool's ceiling) is not raised at all. On, eToro's own minimum is
  the size: an index can be raised, and a stock's 10 USD minimum is then too
  small to carry eToro's flat fee of 1 USD a side, so the fee filter refuses
  it. The refusal's words name eToro's minimum and the switch.
- *The first pass after turning it on.* Every bot under its minimum is raised
  on the same pass. Each entry is bounded as above, and the pass as a whole by
  the account's own limits: on the default limits it can take an account
  from flat to 4 times its size in notional and 15% at the stops. Lower MAX
  OPEN RISK or the ceiling first for a slower start.
- *Where it is said.* The fill message carries a line "Smallest size: raised
  to ..." that says whose size it is (eToro's minimum plus 1%, or the least
  this bot sends, with eToro's own minimum beside it), the risk in percent of
  the pool beside the bot's usual risk, and the multiplier the chooser
  picked. The trade row keeps the whole record (`metadata["venue_floor"]`)
  and so does the audit log. `why_no_trade` and `preflight_live` print one
  line under each bot: the switch's state and the ceiling; `preflight_live`
  also prints the most the chooser may pick for a raised entry. When the
  switch is ON and an order is still refused for its size, the skip keeps its
  code and its words begin with the reason, for example "the venue's smallest
  size would risk 4.63% of the pool, above your 2% ceiling", or "this bot's
  smallest size would risk ..." when the bot's own step is the cause.
- *Turning it on.* From `/ops/` (Switches, System, "Bots: Venue Floor") with
  your trading PIN. The shell and "all on" never turn it on; turning it off
  is free and takes effect on the next order. Set the ceiling on `/setup/`
  first. Each raised entry risks more than the bot's own setting, up to the
  ceiling, and MAX OPEN RISK still bounds what all open positions may lose
  together.

**Watch `/health/` and `/forensics/`** rather than tailing logs: the first
answers "is the machine running", the second answers "why did it do that".

**Resource pressure** shows up first as Celery workers being OOM-killed.
`docker stats` will show it; the fix is a bigger box, or lowering worker
concurrency from `-c 2` in the compose file.
