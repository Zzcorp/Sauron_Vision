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

The withdrawal is the operator's act at IBKR. Then, in this order:

- **2a. Untick the five IBKR routing flags** — the retirement's Stage 1, whose
  gate is "every live row CLOSED":

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

  Expect `after False False False False False`. Once unticked, the router
  answers alpaca/paper for a stock row and the carrier guard refuses every
  future miss on an unstamped row for ever — which is why this comes AFTER the
  rows are CLOSED.
- **2b. Clear the IBKR account id, keep the row.** HQ Disconnect on the IBKR row
  of /admin-dashboard/ (posts broker=ibkr to admin-dashboard/brokers/disconnect/)
  clears `account_id_enc` and nothing else: the sync stops walking the row
  (bot_program/tasks.py excludes an empty account id), the 6-hourly "unreachable"
  alert stops, `broker_backed` no longer returns it, `keyed_venue_count` drops
  to 1. The row and the 400-day BrokerEquityReading road stay (the FK is
  CASCADE — **never delete the IBKRAccount row**). The form renders only while
  `row.ibkr.connected` is True; if it is not there, say so before touching the
  column by hand.
- **2c. Stop the Gateway container:** `./deploy/dc --profile ibkr stop ibgateway`.
- **2d. Proofs:** `./deploy/dc exec worker-fast python manage.py shell -c "from bot_program.tasks import sync_broker_account as s; print(s())"`
  → `{'attempted': 0, 'stored': 0, 'unreachable': 0}`;
  `./deploy/dc exec worker-fast python manage.py preflight_live --user Sauron` →
  section 2 with no book until an eToro class is ticked, and no stale-reading
  blocker; `./deploy/dc exec worker-fast python manage.py treasury --user Sauron`
  → no IBKR row under "positions the platform believes are open".

Never untick `broker_account_sync` to silence IBKR: one switch guards the
eToro sync too.

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
`--other-world` to measure whether the real pair opens the demo portfolio —
nothing in the tree knows. Add `--symbol X` for a spelling that belongs to no
config. Read every `unknown` before blaming the keys.

## 4. Demo write proof — the first order ever, on the virtual portfolio, with NO row and NO tick

Through the adapter itself — never through TAKE TRADE (config 10 is disabled
and stays so; enabled, it would book a paper=False row on the venue that is
about to trade unattended) and never with a class ticked (a tick makes the
demo row the book and the venue in one click).

- D1. On /brokers/ save the DEMO key pair from eToro's developer portal, Demo
  ticked (it ships ticked), all four class boxes UNTICKED. With no box ticked
  eToro is neither book nor venue; the 900 s sync stores a virtual balance
  under env "paper" and re-sizes nothing.
- D2. One round trip, printed values only:

  ```
  ./deploy/dc exec worker-fast python manage.py shell -c "
  from bot_program.models import EtoroAccount
  from bot_program.engine.etoro_client import EtoroTrader
  a = EtoroAccount.objects.get(user__username='Sauron'); k, u = a.get_credentials()
  t = EtoroTrader(k, u, env='demo' if a.demo else 'live')
  assert t.demo, 'REFUSING: the row is not demo'
  print('env', t.env, 'net_liquidation', t.net_liquidation())
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
- D3. Any divergence from the adapter's assumptions is recorded in
  tests/test_etoro_client.py by name, with the real class and a patched
  session — never a subclass.
- D4. Re-save the LIVE keys on /brokers/, Demo UNTICKED, all four boxes still
  UNTICKED. The environment flip drops the demo reading cells on purpose.

## 5. Funding, and the pool arithmetic

- eToro cannot be asked its size floor before an order
  (bot_program/engine/capabilities.py:74-84); an under-minimum order is refused
  AT the order. Fund enough that one unit of the largest-priced symbol fits
  inside the smallest pool's per-trade size.
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

Tick ONE class at a time on /brokers/, re-entering both keys each time. Stocks
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
  → NO BLOCKERS FOUND.
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
- Never run the demo write proof through TAKE TRADE, and never enable config 10
  for it.
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
