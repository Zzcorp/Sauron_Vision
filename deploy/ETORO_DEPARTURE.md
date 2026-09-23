# eToro departure — the operator's ordered plan

Measured on the VPS on 2026-09-23 between 06:09 and 06:21 UTC, on commit 8eddee1
(branch ibkr-sessions-and-working-entries). Written at 976e06d: three commits
landed between the measurement and this file (20fa370, 3ac446f, 976e06d) and
moved lines in bot_program/engine/etoro_client.py, bot_program/asset_engine/base.py,
bot_program/reconcile_asset.py, bot_program/engine/venue_close.py and
bot_program/manual_trade.py — treat every file:line below as read at 8eddee1 and
re-read before editing. Every command runs on the VPS from ~/Sauron_Vision as
`./deploy/dc exec worker-fast python manage.py ...` (deploy/dc is the compose
wrapper). The Django username is Sauron. Companion: deploy/IBKR_RETIREMENT.md —
its Stage 1 waits on §1-§2 below; its Stage 2b is §6-§7 below.

The operator's goal, in their words: eToro trades every class, unattended, for
weeks; IBKR is retired.

## 0. Where things stand (measured)

- **What the operator believed** on the morning of 2026-09-23: the three IBKR
  positions closed by hand in the IBKR app, the cash withdrawn, the Gateway not
  worth another IB Key push. **What the platform measured** once the Gateway was
  logged in (06:09 UTC, `sync_broker_account` → `{'attempted': 1, 'stored': 1,
  'unreachable': 0}`): equity **2,026.53 EUR**, read 70 s earlier; **NEM SELL 1**
  and **HYG BUY 3 still HELD** at IBKR; GLDM absent; and
  `IBKRTrader.resting_order_ids()` answered `set()` — **no protective leg rests
  at IBKR any more** (77/78 and 64/65 are gone; NEM's mark of 127.50 sits above
  its former stop of 126.45). This is the whole reason nothing in this platform
  writes CLOSED on a statement: the statement was wrong on two rows out of three
  and on the cash.
- **#95 GLDM — CLOSED** at 06:20 UTC by `reconcile_user` against the live
  IBKRTrader's own book (reason `reconciled-orphan`, `exit_price_inferred` True;
  IBKR refused the quote — error 10089, no market-data subscription — so the exit
  price is unavailable and the P&L is recorded **UNMEASURED, not zero**; legs
  90/91 answered "not among the open orders — already filled or cancelled"). The
  path, in this order and outside 13:00-21:59 UTC: the eToro keys forgotten on
  /brokers/ (Forget eToro keys) so that `keyed_venue_count` == 1 and the carrier
  guard's no-carrier refusal (bot_program/reconcile_asset.py:70-73) no longer
  fires; then ONE shell that asserted `keyed_venue_count(u) == 1`, asserted the
  routed client's class name was `IBKRTrader`, printed the book (NEM and HYG
  present, GLDM absent — a raise here means the Gateway did not answer and
  nothing is written), printed the resting orders, and only then called
  `reconcile_user(u)` → `{'checked': 3, 'closed_as_orphan': 1,
  'broker_unavailable': 0, 'errors': 0}`; then both eToro keys re-entered on
  /brokers/, Demo unticked, **no class ticked** (`keyed 2 | etoro keys present:
  True`). Why one process: the IBKR trading session is pooled per process, so
  the class and the book printed before the walk are the client the walk uses.
- **#94 NEM and #93 HYG — OPEN on both sides, unprotected at IBKR.** They close
  through the platform at the NYSE open (§1). The operator close refused at
  06:2x UTC with "No usable price mark for HYG — closing now would book the exit
  at a price nobody quoted" (bot_program/manual_close.py:251, the same guard at
  :415): market shut and delayed data only, no mark exists. That refusal is the
  platform working.
- **Config 10 ("manual", the TAKE TRADE lane) owns all three rows.** It is
  disabled and stays disabled: the bot walks only enabled configs
  (bot_program/asset_engine/base.py:381), so nothing ticks these rows; enabled,
  the 336 h clock exit (bot_program/asset_models.py:46) would fire from
  2026-09-28 into a client with no position id. Config 14 does NOT own GLDM's
  row — the commodity config carries no trap.
- **Live configs, all disabled:** [1] starter_fx_majors forex 150 EUR fixed
  (EURUSD GBPUSD USDJPY USDCHF AUDUSD USDCAD NZDUSD); [14] commodity_etf stock
  follower 20 % 402.40 EUR (GLDM SLV USO BNO UNG CPER WEAT CORN SOYB CANE DBC);
  [10] manual stock follower, no share, 1609.62 EUR, no symbols; [6]
  starter_megacaps stock 150 EUR fixed (AAPL MSFT NVDA AMZN GOOGL META TSLA).
  base_currency EUR on all four; eToro reads USD; nothing converts; the
  preflight names the mismatch a BLOCKER for every live config, enabled or not.
- **eToro row:** keyed, live, no class ticked, 1.40 USD. Reads measured against
  the real key on 2026-09-22 (aggregate-portfolio 200, portfolio 200, real/pnl
  200, GET market-close-orders 405). The WRITE path — the v2 order POST, the
  orders:lookup poll, the market-close POST, the PATCH stop mover — has never met
  eToro.
- **Alerts:** telegram proven end to end (`_send_telegram` from worker-fast
  returned True; preflight section 7 reads token and prefs row).
- **Backup + export:** pg_dump `sauron-20260923T053524Z.dump` (39,641,466 B) and
  `~/ibkr_equity_road_2026-09-23.json` (17,053 B), both copied to the operator's
  own machine by `scp` over the IP (the hostname form was refused by the VPS's
  SSH). `BACKUP_REMOTE` is still unset: dumps are local until an rclone remote
  exists (deploy/backup.sh:5, deploy/RUNBOOK.md:414-420).
- **Since the measurement, in the tree:** 20fa370 — the eToro adapter refuses a
  stop or target that is present and not a price BEFORE the POST (`_level`) and
  `ticker()` raises on a rates shape it has never seen rather than reading it
  as a quiet market; 3ac446f — `AssetBot.venue_stamps` is the one rule for
  `metadata["broker"]` / `broker_env` / `broker_position_id`, an eToro PENDING
  answer is reported `working` (booked as an order, never as an OPEN position at
  the pre-order ticker), `unattributable()` refuses a miss across worlds
  (live row, demo book), and `close_or_refuse()` refuses to SEND a close at a
  venue that did not carry the row; 976e06d — `etoro_smoke`, the read-only
  probe §3 runs.

## 1. Close NEM and HYG through the platform, at the NYSE open

13:30 UTC (15:30 Paris). Test first, read-only — the shell twin of the
preview page asks the broker whether it still holds the position, then asks for a
mark; nothing is sent:

```
./deploy/dc exec worker-fast python manage.py shell -c "
from django.contrib.auth.models import User
from bot_program.models import AssetBotTrade
from bot_program.manual_close import preview_close
u = User.objects.get(username='Sauron')
for i in (94, 93):
    print(i, preview_close(u, AssetBotTrade.objects.get(id=i)))
"
```

When the answer carries a price and no `error`, close by the pages, with the
PIN: `/positions/94/close/preview/` then `/positions/94/close/`, the same for
`/positions/93/…`. **Never on #95** — it is CLOSED, and a CLOSE on a flat symbol
is an opening order. Expect the rows to read CLOSE_PENDING, then CLOSED with the
broker's own fill once the drain reads it (hourly, all day).

Then read the venue back — the proof is the book, not the row:

```
./deploy/dc exec worker-fast python manage.py shell -c "
from django.contrib.auth.models import User
from bot_program.models import AssetBotTrade
from bot_program.engine.broker_router import client_for_symbol
u = User.objects.get(username='Sauron'); t = AssetBotTrade.objects.get(id=94)
c = client_for_symbol(u, t.symbol, t.config); print(type(c).__name__)
print('positions', c.get_positions()); print('resting', c.resting_order_ids())
"
```

Expect `IBKRTrader`, `positions []`, `resting set()`. A surviving order id in
`resting` is cancelled with `c.cancel_order('<id>')` in the same shell — the
platform's own cancel, never the portal's guesswork.

If the preview answers "broker unavailable" the Gateway has dropped on 2FA:
`./deploy/ibkr-doctor`, then the same restart-and-approve as the morning. If the
operator closes in the IBKR app instead, the rows are settled the way #95 was
(§0: forget the eToro keys, one process that prints the class and the book
before `reconcile_user`, re-key), outside 13:00-21:59 UTC.

An alternative for a future row whose carrier is provable: write
`metadata["broker"] = "ibkr"` on it, so the guard's FIRST refusal protects it
— an IBKRTrader closes only on its own measured [], and any PaperTrader the
router falls back to is refused as "carried by ibkr and the router now answers
paper" (bot_program/reconcile_asset.py:67-69; tests/test_venue_drift.py pins
both sides) — with eToro's keys untouched and at any hour. The design
refutation of 2026-09-23 preferred that stamp to un-keying eToro; this plan
un-keyed because the in-process assertions above made it a measurement, and
because the stamp is a provenance write by hand, which this platform has so far
refused (10863a8). Either way: the class name and the book are printed BEFORE
anything is written, in the process that then writes. There is no selective
revert in this repo (deploy/RUNBOOK.md §10 restores the whole database).

## 2. Withdraw, then retire IBKR at runtime — only after §1 shows IBKR flat

Designed and refuted on 2026-09-23 (three lenses and a critic on the runtime
sequence, read against 8eddee1). No code changes; nothing here moves money.
The withdrawal is the operator's act at IBKR, before 2a.

**Gate — all of it, or STOP.** #93, #94 and #95 CLOSED; no live row OPEN or
CLOSE_PENDING; no live options/cfd row; §1's read of the venue answered
`positions []` and `resting set()`; the cash withdrawn. While an UNSTAMPED
live row is OPEN, dropping `keyed_venue_count` to 1 (2b) hands the reconcile
beat a PaperTrader whose `get_positions()` is the paper table, and the row is
orphan-closed against a simulator — the one thing this order exists to
prevent. Read the gate in one shell:

```
./deploy/dc exec worker-fast python manage.py shell -c "
from bot_program.models import AssetBotTrade
from bot_program.equity_models import BrokerEquityReading
for t in AssetBotTrade.objects.filter(id__in=(93, 94, 95)).order_by('id'):
    m = t.metadata or {}
    print(t.id, t.symbol, t.side, t.status, 'exit', t.exit_price, 'pnl', t.pnl, 'closed', t.closed_at, 'src', m.get('exit_fill_source'), 'inferred', m.get('exit_price_inferred'), 'unpriced', m.get('exit_price_unavailable'))
print('live rows OPEN/CLOSE_PENDING', list(AssetBotTrade.objects.filter(status__in=('OPEN', 'CLOSE_PENDING'), paper=False).values_list('id', 'metadata__broker')))
print('live options/cfd rows', list(AssetBotTrade.objects.filter(status__in=('OPEN', 'CLOSE_PENDING'), paper=False, asset_class__in=('options', 'cfd')).values_list('id', flat=True)))
print('ibkr readings', BrokerEquityReading.objects.filter(broker='ibkr').count())
"
```

Expect three CLOSED rows (#95 with `unpriced True` and pnl None — unmeasured,
not zero; #93/#94 with the broker's fill and `src broker`), `live rows []`,
`options/cfd []`. Write down `ibkr readings` N — 2b must reproduce it.

- **2a. Untick the five IBKR routing flags** — the retirement's Stage 1,
  whose gate is "every live row CLOSED". Reversible (set them back):

  ```
  ./deploy/dc exec worker-fast python manage.py shell -c "
  from bot_program.models import IBKRAccount
  a = IBKRAccount.objects.get(user__username='Sauron')
  print('before', a.is_primary_for_stocks, a.is_primary_for_forex, a.is_primary_for_commodity, a.is_primary_for_options, a.is_primary_for_cfd)
  a.is_primary_for_stocks = a.is_primary_for_forex = a.is_primary_for_commodity = a.is_primary_for_options = a.is_primary_for_cfd = False
  a.save(update_fields=['is_primary_for_stocks', 'is_primary_for_forex', 'is_primary_for_commodity', 'is_primary_for_options', 'is_primary_for_cfd'])
  a.refresh_from_db(); print('after', a.is_primary_for_stocks, a.is_primary_for_forex, a.is_primary_for_commodity, a.is_primary_for_options, a.is_primary_for_cfd)
  "
  ```

  Expect `before True True True True False` then `after False False False
  False False`; treasury section 3 then reads stock/forex/commodity/crypto
  "by default" and the IBKR claims column is a dash. The row is still keyed,
  still the book, still swept — nothing is blinded yet. Once unticked, the
  router answers alpaca/paper for a stock row and the carrier guard refuses
  every future miss on an unstamped row for ever — which is why this comes
  AFTER the rows are CLOSED.
- **2b. Un-key the row — the two writes HQ Disconnect makes, and nothing
  else.** The shell twin is preferred over the × IBKR button because it
  writes exactly two columns and prints the reading cells it leaves intact
  (the page's flash does not), and because it works when the button is not
  rendered. This is the step that makes `broker_backed()` return None — IBKR
  is the book on its account id ALONE, eToro needs keyed AND a class — and
  empties the IBKR sync's queryset, drops the row from the sweep and zeroes
  the data feed's walk. **Never delete the IBKRAccount row**: the FK from
  BrokerEquityReading is CASCADE and the 400-day road goes with it; un-keying
  is a column write on the same row and cascades nothing. Never null the
  cells either — the aged reading is the honest record.

  ```
  ./deploy/dc exec worker-fast python manage.py shell -c "
  from bot_program.models import IBKRAccount
  from bot_program.equity_models import BrokerEquityReading
  a = IBKRAccount.objects.get(user__username='Sauron')
  n_before = BrokerEquityReading.objects.filter(broker='ibkr', account_pk=a.pk).count()
  a.account_id_enc = ''
  a.connected = False
  a.save(update_fields=['account_id_enc', 'connected'])
  a.refresh_from_db()
  print('pk', a.pk, 'keyed', bool(a.account_id_enc), 'connected', a.connected)
  print('cells kept: equity', a.last_equity, a.last_equity_currency, a.last_equity_at, '| held', None if a.broker_positions is None else len(a.broker_positions), a.broker_positions_at, '| login stored', a.has_login)
  print('ibkr readings', n_before, '->', BrokerEquityReading.objects.filter(broker='ibkr', account_pk=a.pk).count())
  "
  ```

  ```
  ./deploy/dc exec worker-fast python manage.py shell -c "from django.contrib.auth.models import User; from bot_program.capital_truth import broker_backed; print(broker_backed(User.objects.get(username='Sauron')))"
  ```

  Expect `keyed False connected False`, the cells line with the last reading
  and its timestamp, `ibkr readings N -> N`, and `None`. Re-keying later is
  re-saving the HQ IBKR form with the account id (it is in the dump).
- **2c. Stop AND remove the Gateway container, and take `ibkr` out of
  `COMPOSE_PROFILES`** so the one-command deploy (`./deploy/dc up -d --build`)
  cannot recreate it — a recreated Gateway restart-loops on the IB Key push
  nobody will approve and pings the phone for weeks. Done AFTER 2b so no beat
  still opens a socket toward it. Never a bare `dc stop` or `dc rm` — without
  a service name compose stops the whole stack.

  ```
  cd ~/Sauron_Vision && docker ps -a --format '{{.Names}} {{.Status}}' | grep -i gateway
  ```

  ```
  cd ~/Sauron_Vision && ./deploy/dc --profile ibkr stop ibgateway && ./deploy/dc --profile ibkr rm -f ibgateway
  ```

  ```
  cd ~/Sauron_Vision && cp -p .env .env.bak.$(date +%F) && chmod 600 .env.bak.$(date +%F) && grep -nE '^COMPOSE_PROFILES=|sauron: IBKR' .env && nano .env
  ```

  In nano: remove `ibkr` from `COMPOSE_PROFILES`; delete the managed block
  from `# >>> sauron: IBKR gateway logins` through `# <<< sauron: IBKR gateway
  logins` and any hand-typed `IBKR_USERNAME=` / `IBKR_PASSWORD=` lines. Proof:
  `docker ps -a --format '{{.Names}}' | grep -ci gateway` prints 0;
  `./deploy/dc config --services | grep -i gateway` prints nothing;
  `grep -c 'sauron: IBKR' .env` prints 0. From now on: never
  `./deploy/ibkr-apply`, never `./deploy/dc --profile ibkr … up`. The
  Gateway login stored on the row (`has_login`) stays: preflight blocks on a
  missing login until the coded Stage 6 removes that block; if the password
  must leave the database, change it at IBKR.
- **2d. Verify the walks:**

  ```
  ./deploy/dc exec worker-fast python manage.py shell -c "
  from django.contrib.auth.models import User
  from bot_program.tasks import sync_broker_account, sync_etoro_accounts
  from bot_program.reconcile_asset import reconcile_unknown_positions, keyed_venue_count
  u = User.objects.get(username='Sauron')
  print('ibkr sync', sync_broker_account())
  print('etoro sync', sync_etoro_accounts())
  print('keyed venues', keyed_venue_count(u))
  print('sweep', reconcile_unknown_positions(u))
  "
  ```

  Expect `ibkr sync {'attempted': 0, 'stored': 0, 'unreachable': 0}`,
  `etoro sync {'attempted': 1, 'stored': 1, 'unreachable': 0}`, `keyed
  venues 1`, and a sweep with `broker_unavailable 0, errors 0` that names
  eToro only. The 6-hourly "IBKR unreachable" alert stops here.
- **2e. Verify the pages print the retired state honestly:**

  ```
  ./deploy/dc exec worker-fast python manage.py treasury --user Sauron
  ```

  ```
  ./deploy/dc exec worker-fast python manage.py preflight_live --user Sauron
  ```

  Treasury: section 1 reads "no row is the book"; the IBKR line stays with
  its aged reading and the session note "no account id", NOT `*book`; exactly
  one BLOCKER — "No broker row is the book … the preflight will refuse to arm
  money" — which is the honest retired state until an eToro class is ticked
  (§6). Preflight: section 2 `ibkr … primary=nothing`, `book NOTHING`; NO
  stale-reading blocker (it needs a book), NO IBKR floor line; each disabled
  config "NO BROKER is primary … PaperTrader" as worth-reading. Three prints
  stay dishonest in this state and are named rather than hidden: preflight
  section 3 says "NEVER MEASURED" where the truth is "no book"; a follower's
  `tracking_freeze_reason` says "no reading has landed yet — enable
  broker_account_sync" where the sync is ON and the missing thing is a book
  (it bites the moment config 14 is re-enabled before §6); and treasury's
  worth-reading note says the IBKR row "holds N position(s)" in the present
  tense over whatever snapshot the last sync left. Wording patches for the
  three are designed (count-1 anchors) and ship with the next coded batch,
  not alone.
- **2f. Record what was done**, beside the equity export — the flags' prior
  values, the un-key time, the container removal, the profile edit, N:

  ```
  ./deploy/dc exec worker-fast python manage.py shell -c "
  from bot_program.models import IBKRAccount, AssetBotTrade
  from bot_program.equity_models import BrokerEquityReading
  from core.models import PlatformComponent
  a = IBKRAccount.objects.get(user__username='Sauron')
  print('ibkr row', a.pk, 'keyed', bool(a.account_id_enc), 'flags', a.is_primary_for_stocks, a.is_primary_for_forex, a.is_primary_for_commodity, a.is_primary_for_options, a.is_primary_for_cfd, 'connected', a.connected, 'login', a.has_login)
  print('cells', a.last_equity, a.last_equity_currency, a.last_equity_at, None if a.broker_positions is None else len(a.broker_positions), a.broker_positions_at)
  print('readings ibkr', BrokerEquityReading.objects.filter(broker='ibkr').count(), 'etoro', BrokerEquityReading.objects.filter(broker='etoro').count())
  print('closed ibkr-era rows', list(AssetBotTrade.objects.filter(id__in=(93, 94, 95)).values_list('id', 'status', 'exit_price', 'pnl')))
  print('components', list(PlatformComponent.objects.filter(key__in=('broker_account_sync', 'pipeline_asset_bots', 'platform_master')).values_list('key', 'is_enabled', 'last_status')))
  " | tee -a ~/ibkr_retirement_$(date +%F).log
  ```

What still reads IBKR afterwards, and is ended only by the coded stages of
deploy/IBKR_RETIREMENT.md (3 → 4 → 5 → 6, none of them while the operator is
away): the IBKR sync walk returns attempted 0 and task_gate grades it
"ran and produced nothing" on the SHARED `broker_account_sync` row every 15
minutes, alternating with eToro's success — true and useless; the ibkr quote
feed stays red for ever (the feed row exists, nothing writes it); the router
and the preflight still NAME IBKR for options/cfd while the router hands back
paper — never arm a live options or cfd config before Stage 4. Never untick
`broker_account_sync` (it guards the eToro sync too) or `pipeline_asset_bots`
(it guards the tick, the reconcile and the sweep) to quiet any of this.

## 3. The eToro read-only probe

```
./deploy/dc exec worker-fast python manage.py etoro_smoke --user Sauron
```

Four states per read — ok / refused / no-such / unknown — and no order ever.
It prints the row, the world's ping with the account currency, the nested
equity, every symbol of every live config with eToro's OWN spelling beside the
id (a lone /search result spelled differently is `unknown`, never `ok`), the
rate as "no rate" whenever lastPrice is not > 0, the bars on the config's
timeframe, the book, how many live platform rows are OPEN without an etoro
stamp, the four write URLs it never calls, and the floor line. Add
`--other-world` to re-measure the other world with the same pair — measured
2026-09-23: the pair saved with Demo ticked answered 200 on the live
aggregate-portfolio too, so ONE pair opens both worlds and only the Demo tick
on /brokers/ picks which. Add `--symbol X` for a spelling that belongs to no
config. Read every `unknown` before blaming the keys.

## 4. Demo write proof — the first order ever, on the virtual portfolio, with NO row and NO tick

Through the adapter itself — never through TAKE TRADE (config 10 is disabled
and stays so; enabled, it would book a paper=False row on the venue that is
about to trade unattended) and never with a class ticked (a tick makes the
demo row the book and the venue in one click).

- D1. On /brokers/ save the key pair from eToro's developer portal (the portal
  calls it "virtual"; measured 2026-09-23 with `etoro_smoke --user Sauron
  --other-world`, the SAME pair answered 200 on the demo AND the live
  aggregate-portfolio — there is no demo-only pair, the Demo tick alone picks
  the world), Demo ticked (it ships ticked), all four class boxes UNTICKED.
  With no box ticked eToro is neither book nor venue; the 900 s sync stores a
  virtual balance under env "paper" and re-sizes nothing. THE WORLD CHECK:
  every demo write snippet in this section asserts, in this order and before
  any order, `t.demo`, `t.ping()` True, and `net_liquidation` above 100,000
  (the virtual balance measured 332,449.10 USD; the real one 1.40 USD). A
  demo-shaped snippet on a row someone unticked would otherwise place a REAL
  order with the same pair — the assert on the balance is the one that cannot
  be fooled by the flag.
- D2. One round trip, printed values only:

  ```
  ./deploy/dc exec worker-fast python manage.py shell -c "
  from bot_program.models import EtoroAccount
  from bot_program.engine.etoro_client import EtoroTrader
  a = EtoroAccount.objects.get(user__username='Sauron'); k, u = a.get_credentials()
  t = EtoroTrader(k, u, env='demo' if a.demo else 'live')
  assert t.demo, 'REFUSING: the row is not demo'
  assert t.ping(), 'REFUSING: the demo world did not answer'
  nl = t.net_liquidation(); print('env', t.env, 'net_liquidation', nl)
  assert nl and nl[0] > 100000, f'REFUSING: {nl} is not the virtual balance (332,449.10 USD measured 2026-09-23; the real one 1.40 USD)'
  print('GLDM instrumentId', t.instrument_id('GLDM'))
  tk = t.ticker('GLDM'); print('ticker', tk)
  last = float(tk.get('lastPrice') or 0); assert last > 0, 'REFUSING: no price'
  r = t.market_order('GLDM', 'BUY', 1, stop_loss=round(last * 0.97, 2), take_profit=round(last * 1.03, 2))
  print('ORDER', {k2: v for k2, v in r.items() if k2 != 'raw'}, 'statusName', r['raw'].get('statusName'))
  print('LOOKUP', r['raw'].get('lookup'))
  print('POSITIONS', t.get_positions())
  pid = r.get('positionId') or ''
  print('CLOSE', t.close_position(pid, 'GLDM') if pid else 'no positionId reported - close on the eToro portal by hand')
  import time; time.sleep(3); print('POSITIONS after', t.get_positions())
  "
  ```

  Read it in three states: ORDER with status FILLED and a positionId is a
  measurement; REJECTED/CANCELLED/EXPIRED is eToro refusing; PENDING with
  `working: True` is an order eToro is HOLDING — the adapter cannot poll or
  cancel it, so it is watched and resolved on the portal; a ValueError starting
  "eToro NOT SENT" is the adapter refusing a level that is not a price (nothing
  left the box); a raise at the POST is eToro refusing the body (the response
  text is logged) or could-not-ask. `close_position` answers PENDING with no
  executedQty — the proof of the close is `POSITIONS after []`, never the
  answer. Write down: the orderId shape; the lookup status id; the
  positionExecutions shape; whether protectedOnFill landed; what the close
  returned. If the position filled, one PATCH before the close:
  `t.modify_protective(pid, <new stop>)`.
- D2b. THE LEVERAGED ROUND TRIP — on the DEMO row, after D2 printed
  `POSITIONS after []`, BEFORE D4, and before the component
  `etoro_leverage_live` is ever ON. It ships OFF: while it is OFF every
  levered entry is refused (`leverage_refused`) and preflight §4 blocks
  arming; nothing is sent at 1 instead. Two sittings, because a levered
  order sent off hours lands WaitingForMarket — the shape a WORKING levered
  row needs, measured for free on funding night — and the filled round trip
  needs a market day. Through the adapter, printed values only, one unit at
  leverage 2 with both legs; every snippet runs D1's WORLD CHECK first.
  - D2b-i — OFF HOURS. Print `MARGIN before` (`t.margin_cells()`); the RAW
    ELIGIBILITY read (`t._sess().post(f'{BASE}/api/v2/trading/info/eligibility',
    json={'instrumentIds': [t.instrument_id('GLDM')]}, headers=t._headers(),
    timeout=t.timeout)` and, on 404, the `.../trading/info/demo/eligibility`
    and `.../trading/demo/info/eligibility` spellings — the demo segment's
    placement on that tail is unmeasured); ONE order `t.market_order('GLDM',
    'BUY', 1, stop_loss=round(last*0.97, 2), take_profit=round(last*1.03, 2),
    leverage=2)` → expect PENDING with `working: True` (statusName
    WaitingForMarket); print ORDER, LOOKUP, `pollFailed` if present, `MARGIN
    after order` (do accountFrozenCash / accountTotalUsedMargin move for a
    HELD order?); the COSTS read (`POST /api/v2/trading/info/costs` with the
    same body at leverage 1 and at leverage 2 — record costType/amount per
    row: markup, marketSpread, overnightFee, overWeekendFee); then the
    DELETE (`t._sess().delete(f'{BASE}/api/v3/trading/execution/orders/{r["orderId"]}',
    headers=t._headers(), timeout=t.timeout)` and its demo spelling) → record
    the status code and text; LOOKUP again by referenceId to prove status
    7/8; `MARGIN after delete`. A 404/405 on the DELETE is a measurement:
    the WORKING-row hole then stands and the flip's precondition is unmet.
    If the order cannot be withdrawn it fills at the open at 2x — close it
    by position id in D2b-ii, first thing.
  - D2b-ii — IN HOURS. `MARGIN before`; the same order → FILLED; print
    LOOKUP and compare `positionExecutions[0].stopLossRate` with the SENT
    stop (the THIRD state: accepted, filled, stop REWRITTEN — record both
    numbers and whether 0.0001 appears); the raw `t._open_positions()` row:
    `leverage`, `amount`, `settlementTypeID`, `isNoStopLoss`, and whether
    `amount` is units × openRate / 2 or the full notional; `MARGIN after
    open`; `t.modify_protective(pid, round(last*0.98, 2))` (TIGHTER only — a
    widening PATCH moves cash into margin per the public reference,
    unmeasured); `t.close_position(pid, 'GLDM')`; `POSITIONS after []`;
    `MARGIN after close`; then ONE deliberate refusal: a second levered order
    whose stop lies outside the printed band — refused at the POST (4xx,
    text logged) or accepted and landed status 4 with an errorCode (record
    whether `status` is an int or an object). A refusal of the FIRST order
    (status 4/10 or a raise at the POST) IS the measurement — record it, do
    not retry with another number, do not flip.
  - PIN every shape in tests/test_etoro_client.py with the real class and a
    patched session (D3's rule): the lookup's leverage placement and status
    shape, the /portfolio row's leverage/amount/settlementTypeID, the totals
    arithmetic before/after, the DELETE answer, the costs rows, the stop
    echo.
  - THE FLIP, by hand, never by a deploy, and only when ALL of: D2b-i and
    D2b-ii are pinned; the costs rows for GLDM at 1x and 2x are written into
    this plan; the DELETE answer is written down; every levered config's
    `max_hold_hours` has been set by the operator with the printed overnight
    fee in mind (or the fee accepted here in writing); the operator's own
    book is saved on /setup/. Command:
    `./deploy/dc exec worker-fast python manage.py shell -c "from core.platform_control import PlatformComponent; print(PlatformComponent.objects.filter(key='etoro_leverage_live').update(is_enabled=True))"`
    → prints 1; then `preflight_live` must show the config's leverage line
    without a BLOCKER.
- D2c. FRACTIONS — on the DEMO row, after D2 has closed flat and before any
  class is ticked or the `fractional_units_live` switch is flipped. Every
  answer written down by NAME; the shell idiom of D2 (values printed, never a
  key; D1's WORLD CHECK first).
  - D2c-0 THE ELIGIBILITY READ FIRST, for the 18 stock symbols of configs 6
    and 14, by hand through the adapter's own session
    (`t._sess().post(<url>, json={'symbols': [...], 'currency': 'USD'},
    headers=t._headers(), timeout=t.timeout)`); the URL is POST
    /api/v2/trading/info/eligibility from the public reference (unmeasured),
    and whether the demo world takes a `demo/` segment there is unmeasured
    too — try the adapter's `_v2("info/eligibility")` rule and the bare path,
    and write down which answers and the status of the other. Record per
    symbol: unitsQuantityType, allowedOrderQuantityType, minPositionExposure,
    maxUnitsPerOrder, and the stop-percentage band. If it answers, the belief
    in capabilities.py and `takes_fractional_units` are corrected in the same
    commit to read the payload and answer None for an unread instrument.
  - D2c-1 THE FRACTION, four significant decimals above the believed
    minimum: check `last` first and pick a size s with s × last > 10 USD
    (0.2345 GLDM if it fits):
    `r = t.market_order('GLDM', 'BUY', 0.2345, stop_loss=round(last*0.97, 2), take_profit=round(last*1.03, 2))`.
    Write down: accepted or refused; the lookup `status` WIRE SHAPE (int or
    object — this decides `_status_of` and the D3 fixture);
    openingData.units and remainingUnits byte for byte (0.2345 exactly, or
    rounded to how many decimals — this measures FRACTIONAL_DECIMALS = 4
    against the venue's step); requestedUnits versus the fill (an over-fill
    is a measurement, not a surprise); the /portfolio row's units and
    amount; the margin cells before and after; the close with units=0.2345
    and `POSITIONS after []`.
  - D2c-2 THE FLOOR, deliberately BELOW it: `t.market_order('GLDM', 'BUY',
    0.0123, …)` (0.0123 × last under 10 USD). A refusal measures the
    minimum — record its shape: an HTTP 4xx at the POST (the raise now says
    "eToro refused (<code>): <words>", ORDER_ERROR on the bot lane) or an
    accepted order landing status 4 with errorCode/errorMessage
    (ORDER_REJECTED with the words) — and its number becomes the value the
    operator types into extras['venue_min_notional']; an acceptance refutes
    the 10 USD belief and the position is closed by id.
  - D2c-3 THE SHORT, overnight: `t.market_order('GLDM', 'SELL', 0.2345, …)`
    held over one night; read /portfolio totalFees and the costs endpoint
    for the same body; close by id. The number goes to the cost item; this
    item only names it.
  - D2c-4 THE QUOTA: on the demo key, more than 20 orders:lookup GETs
    inside 60 s by hand; record the 429's status and body and whether the
    demo world enforces it. Until written down, §7 runs the first eToro
    stock config with max_concurrent_positions = 1.
  - D2c-5 D3 lands each shape by name in tests/test_etoro_client.py with the
    real class over _FakeSession: the fractional fill, the refusal in its
    measured shape, the over-fill, the status wire shape; then and only
    then the operator flips fractional_units_live on /health/, ticks
    the class, and enables ONE config.
- D3. Any divergence from the adapter's assumptions is recorded in
  tests/test_etoro_client.py by name, with the real class and a patched
  session — never a subclass.
- D4. Re-save the SAME pair on /brokers/ with Demo UNTICKED — the switch to
  live is the checkbox, not a key change (measured 2026-09-23) — all four
  boxes still UNTICKED, and the trading PIN typed in the form's PIN field. The
  save is refused, nothing written, while any live config is enabled, while
  any class box is ticked on that same save, or without the PIN; the flash
  names which. The environment flip drops the demo reading cells on purpose.
  From this save every order the platform routes to eToro is real money.

## 5. Funding, and the pool arithmetic

- eToro cannot be asked its size floor in UNITS before an order
  (bot_program/engine/capabilities.py:74-84). Since 2026-09-23 the adapter
  declares `fractional_units` — a BELIEF that `units` may be non-whole — and
  the stock bot SENDS a fraction only while the fractional_units_live
  switch is ON (OFF until D2c's pins land). The venue's minimum position is
  NOT known to the platform: after D2c, type it per config into
  extras['venue_min_notional'] (USD, unconverted) and the engine refuses
  under it as venue_min_size with both numbers; without it the venue's
  refusal is the only floor and the symbol is quiet for 24 h after the first.
  The fuel arithmetic is pool × risk_per_trade_pct / stop_fraction against
  that minimum — preflight section 5 prints it — not the notional ceiling.
  Whole units stay the rule on every other venue, and on eToro while the
  switch is OFF: fund enough that one unit of the largest-priced symbol fits
  inside the smallest pool's notional ceiling until then.
- A DISABLED pool is not a follower (`followers_of` filters enabled=True), so
  nothing is re-sized today. The moment configs 14 and 10 are BOTH enabled while
  both follow, `allocate_shares` gives 10 the remainder after 14's 20 %. Before
  §7 enables anything, decide about 10:
  `./deploy/dc exec worker-fast python manage.py follow 10 --stop --yes`, or an
  explicit share. Away for weeks, keep 10 disabled: there is no hand to take a
  trade.
- `tracking_freeze_reason` refuses every follower's entries until a reading
  younger than 3600 s exists on the book.

## 6. Ticking classes — the book moves on the click

`broker_backed` returns eToro the moment it is keyed AND flagged for any of
stock/forex/commodity/crypto. From that click: the IBKR equity road stops being
readable by the production readers (why the export came first); the router
sends that class to eToro before IBKR; on the next 900 s beat every ENABLED
follower is re-sized from the eToro reading in USD (capital only — the rows
keep saying EUR until §8).

Tick ONE class at a time on /brokers/, re-entering both keys each time, with
Demo left UNTICKED (the live row — re-ticking it is the §10 must-not). Never on
the save that unticks Demo: the form refuses a demo -> live flip with a class
ticked, so D4 and the first tick are two saves, in that order. Stocks
first (configs 6 and 14; 10 stays disabled), forex second (config 1). Options
and CFD have no eToro box and fall to paper by design; no live options config
exists. Crypto routes nothing until a crypto config exists.

## 7. Follow before enable — per config, in this order

- a. `./deploy/dc exec worker-fast python manage.py follow --user Sauron` — who
  follows, at what share.
- b. One sync after the tick:
  `./deploy/dc exec worker-fast python manage.py shell -c "from bot_program.tasks import sync_etoro_accounts; print(sync_etoro_accounts())"`
  → attempted 1, stored 1.
- c. `./deploy/dc exec worker-fast python manage.py follow 14` (plan), then
  `./deploy/dc exec worker-fast python manage.py follow 14 --yes` (write). The
  CLI has no venue refusal (the page's Follow button does), so run it only
  after §6 made eToro the book for that class.
- d. Relabel base_currency (§8) BEFORE enabling.
- e. `./deploy/dc exec worker-fast python manage.py preflight_live --user Sauron`
  → NO BLOCKERS FOUND. The first eToro stock config runs with
  max_concurrent_positions = 1 until D2c's quota note exists.
- f. `./deploy/dc exec worker-fast python manage.py bot on 14 --yes` — one
  config per sitting; watch one full 5-minute tick and the Telegram before the
  next.

## 8. base_currency relabel to USD — no page edits it in isolation

The only page that writes `base_currency` re-creates the config with it
(hq_create_asset_bot's update_or_create rewrites every field); `follow` and the
sync write `capital` only. Relabel before enabling, once per config, after its
follow (the number is already USD):

```
./deploy/dc exec worker-fast python manage.py shell -c "from bot_program.models import AssetBotConfig; print(AssetBotConfig.objects.filter(user__username='Sauron', mode='live', id__in=(1, 6, 10, 14)).update(base_currency='USD'))"
```

Expect 4. The FIXED pools (1 and 6, "150") do not move — 150 becomes 150 USD;
size them deliberately, ≤ the deposit. Proof:
`./deploy/dc exec worker-fast python manage.py preflight_live --user Sauron`
no longer prints CURRENCY MISMATCH.

## 9. The departure picture

eToro keyed live; stocks (then forex) ticked; configs 6 and 14 (then 1) enabled
and following at explicit shares that sum to ≤ 100 %; config 10 disabled and
not following; the five IBKR flags unticked, the IBKR account id cleared, the
Gateway container stopped; #93, #94, #95 CLOSED — #95 with `exit_price_inferred`
True and an unmeasured P&L, #93/#94 with the broker's fills; no resting order at
IBKR; preflight NO BLOCKERS; telegram proven; `BACKUP_REMOTE` set. The
retirement then continues at deploy/IBKR_RETIREMENT.md Stage 3.

```
./deploy/dc exec worker-fast python manage.py treasury --user Sauron
./deploy/dc exec worker-fast python manage.py preflight_live --user Sauron
./deploy/dc exec worker-fast python manage.py open_trades --all
./deploy/dc exec worker-fast python manage.py follow --user Sauron
```

## 10. Must-nots

- Never write status='CLOSED', exit_price, pnl or last_equity by hand. A
  statement is not a measurement — 2026-09-23 proved it twice.
- Never accept a CLOSED that was not preceded, in the same process, by the
  routed client's class name (`IBKRTrader`, or `EtoroTrader` for an eToro row)
  and a printed book.
- Never untick the IBKR flags or press HQ Disconnect on IBKR while any live row
  is OPEN or CLOSE_PENDING.
- Never tick a class on /brokers/ before the demo write proof: the tick makes
  eToro the book and the venue in one click.
- Never flip fractional_units_live before D2c's pins are in
  tests/test_etoro_client.py, and never with more than one config enabled
  until the 20-per-60-s quota's 429 shape is written down (D2c-4).
- Never run the demo write proof through TAKE TRADE, and never enable config 10
  for it. The TAKE TRADE lane refuses a config carrying extras['leverage']
  above 1 (nothing sent, not at 1). Forex stays 1x on eToro until
  capital_at_work reads the row's multiplier.
- Never flip `etoro_leverage_live` ON before D2b (both sittings) is recorded
  in tests/test_etoro_client.py, and never put extras['leverage'] above 1 on
  a config while it is OFF: the preflight blocks arming and every tick
  refuses the entry (`leverage_refused`) — nothing is sent at 1 instead.
  Leverage changes the cash eToro locks and the financing it charges, never
  the units or the loss at the stop; a bigger position is
  risk_per_trade_pct, max_notional_fraction and funding (§5).
- Never press CLOSE, close-all or EMERGENCY FLATTEN on a row whose symbol the
  broker no longer holds: the ordinary close is an opposite MARKET order.
- Never disarm a live config by setting mode='paper' (`client_for_symbol`
  short-circuits to paper and reconcile filters neither enabled nor mode);
  `bot off <id>` or the page toggle.
- Never put a key in argv, chat or history; the /brokers/ form is the only
  path, and every shell snippet above prints values, never a key.
- Never enable two configs in one sitting.
- Never read ticker "0" or a net_liquidation None as a measurement.
- Never toggle `pipeline_asset_bots` or `broker_account_sync` to steer one
  beat; each gates more than one walk.
- Never re-save the eToro form with Demo ticked by accident: it ships ticked,
  the row flips to demo, the live cells are dropped, and every save rewrites
  all four class boxes — an unticked box is OFF.
- Never treat the key pair as demo-only: measured 2026-09-23, the SAME pair
  opens both worlds and the Demo tick alone picks which. Unticking it sends
  real orders; the form refuses that flip while a live config is enabled,
  with a class ticked on the same save, or without the trading PIN — and a
  shell bypasses the form, which is why every demo snippet runs D1's WORLD
  CHECK (`t.demo`, `t.ping()`, net_liquidation above 100,000).
