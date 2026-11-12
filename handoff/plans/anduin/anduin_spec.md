# Anduin, the Great River: the page of flows (spec, 2026-11-12, second edition after the critique)

For the later build. Written against main `15dd487` (read-only checkout `.claude/worktrees/mainread`), the approved look (S1a tokens plus "the magic kept", `magic/magic_spec.md` §1-4) and the three designs in flight: the Operations Center (`opscenter/opscenter_spec.md`), Barad-dûr (`eyehall/eyehall_spec.md`) and the no-trade maps (`notrade/m1_entry_path.md`, `m4_offmarket_signals.md`). Nothing in the repository was changed. The mock runs on invented data only. This edition applies the review in `critique.md`; `final_log.md` lists each finding, what was done and what was measured.

**Files beside this spec** (all under `scratchpad/anduin/`):
- `anduin_mock.html`: the animated mock, one file. `?demo=0` is the page at rest, `?motion=0` stops the river, `?stop=<ms>` pauses the story at an instant, `?cadence=real` gives prices today's real pace, `?quiet=1` silences every feed (the idle page), `?wx=stressed|crisis|recovery|off` sets the weather, `?n=40` loads the forty-row stress book, `?book=0` an empty one. R replays the story.
- `shots/`: `anduin_1440x900.png`, `anduin_1920x1080.png`, `anduin_390.png`, three `moment_*.png`, `weather_calm_stressed_crisis.png`, `anduin_40_positions_1440x900.png`, `anduin.webm` (12.8 s, the mock's condensed pace), `anduin_real_cadence.webm` (the same story, prices at today's real pace), `board_anduin_1440x900.png`.
- `Anduin.dc.html` and `canvas_entry.json`: board 7 for the preview canvas.
- `anduin_fr.md`: the note for the operator.
- `critique.md` and `final_log.md`: the review and what was done with it.
- `tools/`: `render.js` (shots, moments, the extra stills, both clips, checks), `measure.js` (cost and pauses), `build_board.js`, `board_shot.js`, `switches.js`. `work/cost.json` holds the measurements.

---

## 0. In one page

- **What it is.** One page that shows the book as a river. Positions are blocks; blocks sit in baskets; three kinds of flow cross them: prices, signals and money. The market's weather changes how the river looks. It answers "what is engaged, where, and what is moving right now", at a glance.
- **The river** runs left to right through the top of every basket, in a band of 28 px that holds three still current lines. Upstream is on the left (feeds and signals), downstream on the right (closes). Under the baskets runs the money lane, which joins the reserve to each block.
- **Baskets**: one per family by default (forex, crypto, commodities, stocks and ETFs, indices), in a fixed order. **The solid card is real money's alone.** DEMO, PAPER and rows that state no venue sit apart, in a dashed annex under or beside the card. Each world has its own band, with its own sum and its own bar; no figure and no shape adds two worlds. An empty family is a narrow dashed slot. Other groupings: world, lane (which bot, or his hand), theme.
- **Blocks**: one per open position. **Its height is its size on one scale that real money sets**: full height is the largest real position (exposure at the mark, or risk at the stop). A DEMO or PAPER block above the scale is capped and marked `›`; it never enlarges the scale. The floor is 48 px (symbol, world, side, R, the price's dot and age); a taller block adds lines by tier (risk and origin, the track with stop and target, entry and mark with the P&L words, exposure, capital at work and time held). A bar at every block's foot says its size, so size still reads at the floor.
- **Flows**, each with a datum behind it:
  - a green mote is one price update. It enters the river at its own basket's gate and reaches its block in 1.2 s at most. The printed age comes from the price's stamp, never from the animation;
  - a diamond token is one signal: taken, it enters its basket and a block forms; refused, it evaporates at the basket's gate and a chip names the bot, the world and the reason code. The stored detail is printed in the Upstream card;
  - twelve ink squares are the money of one fill (reserve to block) or one close (block to reserve). Money is never a light. The result's colour, jade or coral, sits on its figure, and only for real money booked at eToro's price.
- **Weather**: the stress level in force (calm, stressed, crisis, recovery) sets the current's speed, the height and length of the river's three lines (2, 4 and 6 px high on the mock) and the tone of every basket's outline (ink, amber, coral). Each family's volatility adds its own height. A shut market freezes its basket. A high-impact print approaches on a six-hour ribbon and, inside the care's window, its front is a hatched amber band in the air above every basket it touches.
- **Rules kept**: REAL, DEMO and PAPER are never added, in a figure or in a shape; every figure carries its age, and an age never restarts without a new stamp; a missing figure is a dash that says why; no figure sits on the void or on a glow, and none fades; nothing moves without a datum or an event; no frame is asked for when nothing moves; no control on the page moves money.
- **Cost, measured on the mock** (§5.3): idle 0.056-0.059 of a core, which is the still page's 0.053, with no frame asked for; 0.11 at rest at today's real price pace; 0.19-0.22 at rest at the mock's condensed pace; 0.32-0.36 during the busiest story. 30 drawn frames a second at most, on a 4-core machine with no graphics card. 0 frames when hidden, locked, reading the table, or under reduced motion.
- **Capacity, measured on the mock** (§2.4): at 1440 x 900 the forty-row stress book draws 21 of its 40 rows (the 7 real ones as full blocks) and folds 19; at 1920 x 1080 it draws all 40.
- **Stages**: A1 the real page, read-only, polled; A2 live events; A3 weather complete and a "last 24 h" replay. Money direction of every stage: none.
- **New things the build needs** are marked **new** in §1 and listed in §1.9. Nothing needs a new feed or a broker call.

---

## 1. The data contract

Every thing drawn has one reader. "World" is always `dashboard/position_summary.py:253 world_of(row)` (`"live"`, `"demo"`, `"paper"`, or `""` for a row that states no venue), never `paper` alone. A dash always carries its reason in a `title` and in the table view.

### 1.1 Positions (the blocks)

| Drawn | Source (file:line) | World | Age | When missing |
|---|---|---|---|---|
| The open book: bot rows and hand rows in OPEN and CLOSE_PENDING, and legacy rows | `dashboard/horde.py:2167 board(user)`: the seats built by `:1158 _bot_seat` (from `bot_program/asset_models.py:244 AssetBotTrade`) and `:1429 _legacy_seat` (from `portfolio/models.py:96 Position`). One call also gives `stragglers` (`:1738`), `unseated` (`:1761`) and the `alarms` | the seat's `world` (`horde.py:1383`) | **`board()` is not cached** (`horde.py:2167-2169`: "Not cached: marks move inside the fingerprint's blind spot"); what is kept 20 s is the head (`_head_raw`, `:817-838`) and the tab (`:2180`). The age the page prints is the payload's own `as_of` (`book read N s ago`, one pill for the blocks, the bands' sums and the baskets' counts); the broker read's age is `head.as_of` | the board unreadable: the stage shows `not measured: the book could not be read`, no basket is drawn |
| Symbol, side, quantity, entry | the seat: `symbol`, `side`, `side_word` (`horde.py:1381`); the trade's `qty`, `entry_price` (`asset_models.py:266-267`); prices through `{% px %}`, quantities through S1a's `qty` | row | `held.t` (`horde.py:1405`) | never missing |
| Family (the default basket) | the seat's `instrument_class` (`horde.py:1386`, the Instrument's `asset_class`, `instruments/models.py:10`, `core/constants.py:5-14`), else its `class`. Stocks and ETFs share one basket; `bond`, `options`, `cfd` fall into "Other", drawn only when it holds a row | n/a | n/a | an instrument with no row: "Other" |
| Lane (bot, or his hand) | the seat's `lane` (`"hand"` or `"bot"`, `horde.py:1387`, decided by `:1110 _is_hand`: `metadata["manual"]`, `rule_name` `manual_take`, or a manual config, `core/context_processors.py:650`) and `config.label` (`horde.py:1388`) | n/a | n/a | a legacy row: lane "Recorded by hand" |
| Where it comes from | a bot row: `rule_name` (`asset_models.py:299`) on one line and `config.label` on the next; a hand row: "Your ticket", with `metadata["signal_id"]` when the ticket came from a signal (`bot_program/manual_trade.py:3245`); the seat's `mission` (`horde.py:2364 _mission`) in the detail | n/a | n/a | a bot row with a blank `rule_name`: `rule not recorded`. **The signal's id for a bot row is not stored today** (the row carries the rule's name and its reasons, `bot_program/asset_engine/base.py:7507-7520`; the only `signal_id` the bot lane writes is the rule's name on an order intent, `base.py:6732`): the block, the detail and the table print the rule and the bot, and no signal number (N8) |
| Size as **exposure at the mark** | quantity x mark x the value per unit, in USD: the notional the seat computes (`horde.py:1301`, at the entry) re-priced at the seat's mark. **New (small)**: the seat carries the notional at the entry only; the page needs one additive field `exposure.v` at the mark | row | the mark's | a forex row with no USD stamp (`horde.py:1281-1284`, `vpu_stamped`): `— no USD stamp`; the block is drawn at the floor size and left out of every sum, which says `+1 apart` |
| Size as **risk at the stop** | the seat's `risk.v` (`horde.py:1271-1280`), which is the gate's own figure, `portfolio/risk_gate.py:829 _row_risk`, at the stop sent | row | n/a (levels are stored) | no stop: `— no stop recorded` ("no R, not a zero"); no USD stamp: `— no USD stamp`; both at the floor size, left out of the sums |
| Capital at work (the block from 248 px, the detail, the card's foot, and what a money stream stands for) | the seat's `at_work` (`horde.py:1301-1307`: margin when levered, cost otherwise, from `_pos_committed`). **Summed per world in the card's foot** (`at work $433.68`), so the reserve's `on Sauron` line and the baskets can be checked against each other (§1.3) | row | n/a | `—` for a row whose money is not in USD; PAPER prints `simulated`; a row with no venue `— not known` |
| R now | the seat's `money.r_v` and `r_t` (`horde.py:1235`) | row | the mark's | no stop: `—`, titled "no stop recorded: no R, not a zero" |
| Open P&L and its words | the seat's `money` with `pnl_words` (`horde.py:1240`): PR #89's tiers (`portfolio/services.py:1197-1343`): `eToro's own`, `estimate: eToro quote`, `estimate: <feed>` | row | the tier's age | an unmarked row: the Horde's `MARK_WAIT` words, no figure |
| Stop, target, and the track | the seat's `levels` (`horde.py:1259-1267`): `stop_t`, `target_t`, `istop_t`, `progress_v`; the track runs from the stop to the target, with a tick at the entry and a mark at the price | row | n/a | no stop or no target: `SL —`, `TP —`, a dashed empty track |
| The Horde's light | `horde.py:934 light(facts)`: `tone` (alarm ⨯ coral, watch ⚠ amber, order ◆, unheld ○) and the first reason's words, verbatim, as the glyph's title and in the detail | row | n/a | calm: no glyph |
| A close given up on (straggler) | `horde.py:1738 _stragglers` | row | n/a | drawn as a dashed block with the Horde's sentence and `Story ›`; no size, no flows |
| At eToro, not on Sauron | `horde.py:1761 _unseated` | the account's world | the holdings read's | drawn in its family's card foot as `+N at eToro, not on Sauron ›` (a count, a link to the Operations Center) and in the reserve as `outside $… · N positions ›` (§1.3); not a block, since eToro's list gives no mark (`horde.py:1828`) |

### 1.2 Baskets and their volume

| Drawn | Source | World | Age | When missing |
|---|---|---|---|---|
| The basket's solid card | the REAL rows of the group, and nothing else: its head, the river's band, the REAL band, its foot. Its size is real money's alone | REAL | the book's | no REAL row: the card is a lid (head, river, foot) and its foot says `REAL — nothing open` |
| The annex | the DEMO, PAPER and no-venue rows of the group, one band per world, in a dashed box: under the card when it fits there, else beside it | each apart | the book's | none: no annex |
| A band's head | the world's chip, **its own sum** of the chosen size (`open_by_world`'s rule, `dashboard/position_summary.py:282`: "from figures the rows already carry") and **its bar** on one page-wide scale (full = the largest REAL sum of a basket; a sum above it is capped and marked `›`). No total, no stacked bar | per world | the book's | rows without a figure for the measure: `+N apart: no USD figure`; none with a figure: `— no figure` |
| The scale | the largest REAL value in the book when the page was laid out (§4.2), printed in a pill: `full height = $21,749.00 · set by real money at 20:46 UTC ↻` | REAL | the layout's time | no REAL row: the largest value shown, and the pill says so; an empty book: `scale · — nothing open` |
| An empty family | a dashed slot 124 px wide: title, `open` or `shut`, the river, `Nothing open`, the 24 h counts | n/a | n/a | n/a |
| Signals in the last 24 h, for the basket | §1.4: three readers that do not add up | n/a | the book's | `— not counted` when the reader failed |
| Session line and volatility line | §1.7 | n/a | printed | §1.7 |

### 1.3 The reserve (the three pools)

| Drawn | Source | World | Age | When missing |
|---|---|---|---|---|
| REAL or DEMO: available, used, used % | `bot_program/etoro_used.py:322 account_used(user)`: `available`, `used`, `total`, `currency`, `world` (`:430-449`). These are eToro's own cells | the account's current world only (`account_used["world"]`) | `age_s`, `age_t` (`:440-441`); greyed past one hour (`BROKER_STALE_S`) | the other world: `— not read`, "the sync reads the eToro account in its current world"; no eToro row: `— no eToro account`; cells unread: `— not read` with `reason` |
| On Sauron, and outside | `on Sauron`: the capital at work of the REAL rows drawn on the page (the cards' own `at work` figures, summed). `outside $… · N positions ›`: `account_used["outside"]` and `positions`, the money eToro counts as used for positions that have no row here. **The two add up to `used`** (on the mock: $1,540.53 + $2,861.57 = $4,402.10), so nothing that is used is missing from the page | same | same | `—` unread |
| PAPER: the pools | the sum of `capital` over the user's paper configs (`bot_program/asset_models.py:133`, `mode="paper"` `:129`), printed "simulated pools · no money moves" | paper | n/a (a setting) | no paper config: `— no paper config` |

A money stream leaves from, and returns to, the pool of its block's world. It stands for the block's capital at work (§1.1); the figures in the pool change only when a new reading of eToro's cells arrives (the engine re-reads the account after a fill, `base.py:7521`), never by counting. The reading's age is in the card's head (`eToro's own cells, read 40 s ago`). The cells are read for one world at a time: the world the account is routed to; the other pool is a dash that says so.

### 1.4 Signals: arrived, taken, refused

| Drawn | Source | Window | When missing |
|---|---|---|---|
| Arrived, per family and in all | `signals/models.py:7 Signal` with `created_at` (`:47`) in the last 24 h, by `instrument.asset_class` | rolling 24 h | `— not counted` |
| On the rail now | `dashboard/signal_rail.py:818 rail_snapshot` (the rail's own list and order) | now | the rail's own empty words |
| Taken | `AssetBotTrade` with `opened_at` (`asset_models.py:305`) in 24 h, by world, family and lane; the rule from `rule_name`; a ticket's signal from `metadata["signal_id"]` | rolling 24 h | `0 taken` is a measured zero |
| Refused: the reason codes | `AssetBotConfig.extras["skips"][symbol]` = `{code, detail, at}` (`bot_program/asset_engine/skips.py:161-183`), read through `skips.py:205 last_by_symbol`; the vocabulary is `skips.py:29-156`; a config keeps its last 200 symbols (`MAX_SYMBOLS_TRACKED`, `skips.py:158`). **A skip belongs to one config**, so the reader keeps the bot and its world with each | **the last recorded reason of each symbol, bot by bot, when it is a refusal (below) and its `at` is within 24 h** | `— nothing recorded` for a config with no skip yet (M1 D1: a config-level refusal writes no skip) |
| Refused: the exposure caps | `bot_program/orchestrator_models.py:13 OrchestratorEvent`, `decision` reject, `created_at` in 24 h (`:30-38`) | rolling 24 h, exact | `0` |
| Left the rail without a trade | `dashboard/models.py:132 RailDeparture` rows, written once with their reason in words (the eleven lifecycle rules, `dashboard/signal_rail.py:17-32`, `:615 _lifecycle`) | rolling 24 h, exact | `0` |

**What a refusal is on this page: a closed list, not "every skip".** A skip is also written when the bot simply waits, and for symbols it already holds, so the page sorts the codes:

| Class | Codes | What the page does |
|---|---|---|
| **Refusal** | `gate_blocked`, `cost_filter`, `bad_timing`, `market_shut`, `leverage_refused`, `proving_failed`, `sized_to_zero`, `venue_min_size`, `wide_spread`, `eligibility_refused`, `stage_blocked`, `brain_paused`, `paper_fallback`, `desk_displaced`, `venue_sick`, `shadow`, `order_rejected`, `order_error`, `error` | a token evaporates at the gate; the symbol counts in `refused` |
| **Refusal, in doubt** | `order_in_doubt` | the same, drawn in coral with ⨯, and its chip stays until read: an order may be live with no row |
| **Waiting** | `hold` (the vote said no), `already_open` (written by `propose_entry` when the config already holds the symbol, `base.py:4909-4920` and `:5309`), `cooldown` | no token; its own count, `waiting N`, titled with the three meanings |
| **About an open row** | `no_price`, `suspect_mark` | a refusal only when that config holds no row on the symbol; left out when it does (M1 §5.4: they are also written for open positions) |
| **Nothing arrived** | `no_signals`, `stale_signals`, `no_instrument` | nothing |

Why the list matters: `skips.clear()` wipes a symbol's skip at the fill (`base.py:7615`, `skips.py:186-195`), and one bot pass later the vote says enter again and the bot writes `already_open`. Under the first edition's rule ("every skip but two") the page would have drawn `BTCUSD refused · already_open` seconds after the block formed, for a real order that was taken.

**The limit, said on the page.** A skip is written on every bot pass and only the last one per symbol is kept; `skip_counts` is cumulative for ever (`skips.py:176-179`). So the page prints `refused: N symbols by their last reason · M by real bots`, not a count of refusals. **New**: a dated record of refusals (M1 D4's "rolling 24-hour count") would make the count and its replay exact; it belongs to the no-trade fixes, not to this page.

**Four readers, and they do not add up.** Arrived (Signal rows), taken (trade rows, split by world: `8 taken: 3 real · 5 paper`), refused (symbols by their last reason, with the count by real bots) and the rail are four separate reads. One signal can be taken by a paper bot and refused by a real one. The Upstream card says so in its head, and the mock's numbers are chosen so that they do not form a sum.

**When a token is drawn.** One token for a signal seen for the first time since the page opened (A1: at a poll; A2: on `new_signal`). One evaporation only when a refusal's `at` is newer than the `created_at` of the symbol's newest signal, and that (config, symbol, code) was not already drawn for that signal: never one per bot pass, never for a code that flips with no new signal. Nothing is replayed at page load: the counts say what happened before.

**The words of a refusal.** The chip in the air names the symbol, the bot, its world and the code: `XAGUSD refused by Commodities #4 [REAL] · cost_filter`. A signal judged by several bots leaves one chip per bot, each with its own world and outcome. The stored `detail` is printed word for word under "last" in the Upstream card, in the event line and in the table, as `why_no_trade` prints it (`why_no_trade.py:193-194`: the code, then the detail): `planned move 0.31% is only 1.4x the 0.22% round-trip cost (need 2.0x)`. The page writes no sentence of its own for a code. A table of plain sentences, if wanted, belongs in `skips.py`, used by the command and the page alike.

### 1.5 Price freshness (the streams)

| Drawn | Source | When missing |
|---|---|---|
| The price that values a block, its source and its age | `bot_program/venue_mark.py:384 resolve(trade, quote)` returns a `Mark` (`:361-370`): `price`, `source` (`venue`, `venue_stale`, `quote`, `awaiting_venue`, `:137-140`), `at`, `age_s`, `via` (fill, tick, candle), `stand_in`. The seat carries `mark` with `word` and `source` (`horde.py:1246-1248`); `mark_age_t` is in the light's facts (`horde.py:1347`), not on the seat. **New (shared with the Operations Center's OC2)**: the additive `mark.age_s`, `mark.at` and `mark.feed` on the seat. **The printed age is always now − `mark.at`**: the canvas never writes it, and it never decreases without a new `at` | `waiting for the venue's price` (the Horde's words) and a dotted feeder: no mote, no age |
| The platform's quote for a symbol | `market_data/models.py:31 LiveQuote`: `last`, `updated_at` (`:39`), `source` (`:40`); eToro's 30 s quotes for open REAL rows are written by `bot_program/etoro_quotes.py` (`BEAT_S = 30`, `:97`) | no row: `— no quote` |
| The four states of a stream | **live**: age under 60 s (two beats of the 30 s quotes); **recent**: under 900 s; **stale**: 900 s or more (`venue_mark.py:104 MAX_AGE_S`, the same line that turns a venue stamp into `venue_stale` and ends PR #89's quote tier); **closed**: the market clock says shut (§1.7) | n/a |
| The feeds' lights (Upstream card) | the newest `updated_at` per `source` among the held and starred instruments' `LiveQuote` rows | a feed with no row: not listed |

A stale stream draws its feeder dashed in amber and prints `stale · 15 min`; the Horde's own sentence ("Priced at the venue's last rate, 15 min old.", `horde.py:989-991`) is the block's ⚠.

### 1.6 Fills and closes as events

All on `/ws/eye/` (`dashboard/routing.py:8`, `dashboard/consumers.py:230 EyeConsumer`, one group per user, `push_eye_event` `:275`).

| Event | Sent from | Carries | What the page does |
|---|---|---|---|
| `fill_open` | `bot_program/asset_engine/base.py:7597` (a bot), `bot_program/manual_trade.py:3823` (his ticket) | `trade_id`, `asset_class`, `symbol`, `side` | re-reads that one seat; a block forms; a money stream leaves the pool of the seat's world |
| `fill_close` | `base.py:4488`, `bot_program/pending_closes.py:1459`, `bot_program/reconcile_asset.py:1023`, `bot_program/nl_trader.py:184`, `bot_program/engine/kill_switch.py:39` | the same, plus `outcome`, `pnl` (a string). An unmeasured result is `""` from `pending_closes.py:1459-1465` and `"0"` from `base.py:4488-4492`: the page never reads the result from the event | the block leaves; its token rides to the mouth; twelve ink squares return to the pool. The riding label's figures are jade or coral for a REAL close booked at eToro's price, ink otherwise |
| `close_pending` | `base.py:4356, 4525`, `pending_closes.py:1518` | the trade | the block's light turns (the Horde's words); no flow |
| `scale_out` | `base.py:3863` | the trade | a short stream returns; the block shrinks at the next read |
| `gate_reject` | `bot_program/orchestrator.py:501` | `asset_class`, `symbol`, `side`, `reason` | a token evaporates at the family's gate with `reason` |
| `new_signal` (staff) | `signals/announce.py:84`, payload `:48-62` | `signal_id`, `symbol`, `direction`, `rule_name`, `score`, entry, stop, target | a token leaves the spring for its family's gate |
| `quote` (on `/ws/dashboard/`) | `dashboard/consumers.py:134 push_quote_update`, `:83-86` | `symbol`, price, change, `source` | one mote for a held symbol |

**No event carries the world or R, and `fill_close`'s `pnl` is not to be trusted for an unmeasured result (above).** The page never colours a figure from an event alone: it re-reads the seat (or the closed row: `realized_r`, `pnl`, `outcome`, `asset_models.py:290, 327-328`) and takes the world from `world_of`. Barad-dûr's stage E2 adds `"world"` and `"via"` to the eleven trade pushes (its spec §4.6); Anduin uses them when they exist and does not need them.

### 1.7 The weather

| Drawn | Source (file:line) | Age | When missing |
|---|---|---|---|
| The level in force and its score | `bot_program/market_stress.py:464 current()` → `{level, score, at, fresh, why}`. Levels, exactly: `calm`, `stressed`, `crisis`, `recovery` (`:48-49`). Thresholds: stressed from a score of 30 (`SCORE_STRESSED`, `:51`), crisis from 55 (`:52`); a crisis ends in recovery under 45 with the index up over 5 days (`:53`); down needs two calm readings over 4 hours (`:54-55`); recovery lasts 10 days at most (`:56`). Stored in `bot_program/aragorn_models.py:69 MarketStressReading` (`at`, `score`, `raw_level`, `level`, `components`, `reasons`, `override`, `:77-83`), written every 15 min by `bot_program/tasks.py:1837-1845 read_market_stress` (`config/celery.py:573`) | `read N min ago` from `at`; `fresh` false past 2 hours (`STALE_HOURS`, `:59`): the level "holds" for 24 h (`:60`), and the page says so with `current()["why"]` | `crisis_mode` off (`bot_program/posture.py:87-97`; the task is behind the same switch): `— not measured: crisis mode is off`; no reading yet: `— no stress reading yet`. In both the river is drawn flat and at the calm speed, and the sky says why |
| The level's words | `market_stress.py:455-461 POSTURE_WORDS`, verbatim and whole (the crisis sentence ends "; open risk-on longs tightened.", on two lines in the sky); an operator override prints its `why` ("operator override until ...") | n/a | n/a |
| What the level does to entries (the detail) | `posture.py:56 POSTURE_TABLE` | n/a | n/a |
| Volatility of the index family | already stored: the reading's `components["raw"]["realized_vol"]` (SPX500's 20-day realized volatility against its 1-year level, `market_stress.py:122-150`) and `vix` | the reading's | left out and said, as the module does |
| **Volatility per family** | **new, a derivation over data that exists**: `indicators/regime.py:13 vol_percentile(close, window=20, lookback=120)` over the daily closes (`market_data/models.py:8 PriceData`, `timeframe="1d"`) of the family's held instruments, else its starred ones; the median, printed `vol p41 · 3 inst · 11 Nov` (the percentile, how many instruments, the newest bar's date). No stored per-family figure exists today (the per-instrument `indicators/models.py:30 atr_14` is the only stored volatility) | **the newest daily bar's date, printed in the line**; computed at most every 15 min, cached | `vol_percentile` needs 120 values of 20-day volatility, about 140 daily closes: with fewer for every instrument of the family, `vol — · not enough bars`, and the family adds no height to the river |
| Session per family | `core/exchange_status.py:743 market_clock(asset_class, exchange, symbol)` per held instrument → `is_open`, `session`, `modelled`, `reopens`, `reopens_words`, `opened`, `closed` (`:769-799`); the next close from `:724 next_close_utc`. The basket prints `open · shuts 21:00 UTC`, `shut · reopens 14:30 UTC`, or `2 of 3 markets open` when its instruments differ | computed now | `modelled` false: `hours not modelled`, never frozen |
| A basket freezes | every instrument it holds is shut, and its class is one where shut means no trading: forex, stock, ETF, commodity (`bot_program/entry_timing.py:123-139`, `SHUT_CLASSES`). **An index is not frozen** on its cash clock: the broker's CFD trades nearly round the clock (M4 §2.1); its line reads `cash shut · CFD trades`. Known limit, printed in the title: only NYSE and NASDAQ holidays are modelled (`exchange_status.py:763-767`) | n/a | n/a |
| The next high-impact prints | `bot_program/position_care.py:312 upcoming_events(horizon_minutes=1440)`: high-impact macro rows of `EVENT_SOURCES` (`:187`) and earnings; rows are `market_data/models.py:63 EconomicEvent` (`title`, `datetime`, `impact`, `currency_affected`, `source`). Every band on the ribbon carries its print's name and time in its title, and the table lists each print | the calendar task's last run, **printed beside the ribbon** (`calendar read 2 h ago`), as the Operations Center does | an unreadable calendar is an empty list (the reader's rule): the ribbon prints `— calendar not read` |
| The positions a print touches | `position_care.py:358 event_for(trade, before_minutes=...)`: forex by either leg's currency; a stock or ETF by its own earnings, else its home currency (`EVENT_HOME_CURRENCY`, USD, `:184`); the rest by the home currency; options never. The rule runs on every row, a hand-kept stock included: on the mock a USD print touches 7 of the 8 rows, as on the Operations Center's board. **The ⚠ count is a different thing**: the care's record, written at its next pass on the rows it manages. Inside the window the page prints both: `touches 7 open · 6 lit by the care` | n/a | none touched: `touches 0 open` |
| "The front is over the book" | the care's own window: 60 minutes before to 15 after (`position_care.py:177-178`). Inside it the Horde's light is already ⚠ with "A high-impact print is near: ...", the sky says `⚠ FRONT OVER THE BOOK`, and a hatched amber band is drawn in the air above every basket that holds a touched row: the ribbon's own datum, nothing more | n/a | n/a |

### 1.8 Closes of the last 24 h (Downstream)

| Drawn | Source | When missing |
|---|---|---|
| Per world: closes, R summed, money | `AssetBotTrade` with `closed_at` (`asset_models.py:306`) in 24 h, split by `world_of` in Python: `realized_r` (`:328`), `pnl` (`:290`), `outcome` (`:327`). The Operations Center's one read (its R2) is reused | a world that closed nothing: `— nothing closed` |
| The words under REAL | `at eToro's price · fees not counted`, or `at the mark` when any close in it was (`base.py:4405-4442`, `pending_closes.py:366-377`) | n/a |
| Colour | jade or coral only on REAL closes booked at eToro's price; the simulator's closes and estimates are ink with their sign (the Operations Center's §5.3) | n/a |
| Legacy closes | they state no world: listed apart as `no venue` | n/a |

### 1.9 What does not exist yet (**new**)

| # | New thing | Size | Needed by |
|---|---|---|---|
| N1 | The page's reader `dashboard/anduin.py` (one payload from the readers above, with its own `as_of`, kept 10 s per user and keyed on the Horde's fingerprint; a marks-only answer for the 10 s price poll), the URL `/anduin/`, the template and `sv-anduin.js` | the build itself | A1 |
| N2 | `exposure.v` at the mark on the Horde's seat (today: the notional at the entry) | one additive field | A1 |
| N3 | `mark.age_s`, `mark.at` and `mark.feed` on the seat (the Operations Center's OC2 plans the same fields; today `mark_age_t` lives in the light's facts) | three additive fields | A1 |
| N4 | Volatility per family: the median `vol_percentile` over daily bars (a derivation, cached 15 min) | one function | A3 (A1 prints the session line only) |
| N5 | The session of a basket: the per-instrument clock, aggregated | one function | A1 |
| N6 | The theme of a row for the Theme grouping: `bot_program/orchestrator.py:188 classify_full` gives `themes` (`usd`, `equity`, `vol_long`); the basket is the dominant theme and its sign | one function | A1 |
| N7 | A dated record of refusals (today: the last skip per symbol and cumulative counts) | belongs to the no-trade fixes | exact counts; A3's replay of refusals |
| N8 | The signal's id on a bot's trade row (today: the rule's name) | one metadata key at the entry: **an engine write, so not in a display PR**; proposed apart. Until then the page prints no signal number on a bot row | "which signal became this block", exactly |
| N9 | `world` and `via` on the trade pushes | Barad-dûr's E2 | nicer A2 (not required) |
| N10 | A history of price freshness (LiveQuote keeps the latest row only) | none planned | the replay does not show streams drying in the past, and says so |

---

## 2. The layout

### 2.1 At 1440 x 900 (main area 1168 x 792, inside the shell)

```
top bar (44)      ANDUIN  the Great River ... · no order leaves this page     clock · sessions · eToro live · REAL ARMED
market band (32)
┌ THE SKY (60) ────────────────────────────────────────────────────────────────────────────────┐
│ WEATHER [CALM] score 18/100 ● read 6 min ago │ NEXT PRINT ... ribbon now→+6 h │ Family World… │
│ Business as usual.                            │ touches 7 open · calendar 2 h  │ exposure risk │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
 UPSTREAM     (the air, 26: the chips that ride with a token; the front's hatched band)   DOWNSTREAM
┌ FOREX ───────┐┌┄ APART ┄┄┄┄┄┄┐ ┌┄CRYPTO┄┐ ┌ COMMODITIES ┐ ┌ STOCKS & ETFS┐ ┌ INDICES ─────┐
│ session · vol│┆ demo · paper ┆ ┆ open   ┆ │ session · vol│ │ session · vol│ │ session · vol│  head (58)
●≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈ the river: three still current lines ≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈▶  band (28)
│ REAL ▬▬▬▬ $  │┆ DEMO ▭ $     ┆ ┆ Nothing┆ │ REAL ▬ $     │ │ REAL ▬ $     │ │ REAL — nothing│
│ [EURUSD:     │┆ [USDJPY]     ┆ ┆ open   ┆ │ [XAUUSD]     │ │ [AAPL]       │ │ 24 h counts  │
│  full height]│┆ PAPER ▭▭ $   ┆ ┆ 24 h … ┆ │ at work $    │ │ at work $    │ └──────────────┘
│              │┆ [GBPUSD]     ┆ └┄┄┄┄┄┄┄┄┘ │ +1 at eToro ›│ │ 24 h counts  │ ┌┄┄┄┄┄┄┄┄┄┄┄┄┄┄┐
│ at work $    │┆ [EURJPY]     ┆            │ 24 h counts  │ └──────────────┘ ┆ DEMO ▭▭▭ $   ┆
│ +1 at eToro ›│└┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘            └──────────────┘ ┌┄┄┄┄┄┄┄┄┄┄┄┄┄┄┐ ┆ [NAS100]     ┆
│ 24 h counts  │                                             ┆ NO VENUE ┄ $ ┆ ┆              ┆
└──────────────┘                                             ┆ [MSFT]       ┆ └┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘
 · · · · · · · · · · · · · the money lane (26) · · · · · · · · · · · · · · · · ·
┌ RESERVE: REAL | DEMO | PAPER ┐ ┌ UPSTREAM · 24 H ┐ ┌ DOWNSTREAM · 24 H ┐          (130)
└──────────────────────────────┘ └─────────────────┘ └───────────────────┘
 legend · the scale's pill · the book's age · Read as a table
status bar (32)
```

- **The sky** (one opaque card): the level chip, the score, the reading's age, the level's words (two lines for the crisis sentence); the six-hour ribbon (now at the left, a hatched band per print: 60 minutes before to 15 after, each band named in its title) with the nearest print in words, how many open positions it touches, how many the care has lit, and the calendar's age; the two switches.
- **The air**: a band of 26 px above the baskets. The opaque chip of a token rides in it; a refusal's chip stays in it about 3 s; inside the care's window the front's hatched amber band lies along its foot, above every basket that holds a touched row. The words UPSTREAM and DOWNSTREAM sit at its ends, on the void, with the void's dark halo (they hold no digit).
- **A basket** is top-aligned, in a fixed order, so the river is one straight line through every band. Three boxes:
  - **the card** (solid outline): head (title in Orbitron, no digits; the session line; the volatility line with its bar date), the river's band, the REAL band (its head, then its blocks), and a foot: capital at work, `+N at eToro, not on Sauron ›`, the 24 h counts. With no real row the card is a lid: head, river, and a foot that says `REAL — nothing open`;
  - **the annex** (dashed outline, the same opaque ground): one band per world, in the order DEMO, PAPER, no venue. It hangs under the card when it fits in the height that is left; otherwise it stands beside the card, with its own head (APART · demo · paper · no venue · never added to real) and its own stretch of river;
  - **the slot** (dashed, 124 px): an empty family.
- **A band's head** is 19 px: the world's chip, its sum at the right, and under them its bar, 3 px high, on one page-wide scale: solid red for REAL, a gold outline for DEMO, a grey outline for PAPER, dashes for no venue.
- **A block** is as wide as its column (163 px at 1440) and as high as its value on the scale (§4.2), from the 48 px floor to the cap (255 px in the family view at 1440 x 900). Its lines appear by height:

| Height (at 1440; x 1.07 from 1680) | Lines |
|---|---|
| 48 to 97 (the floor) | symbol, world chip, the Horde's glyph · side chip, R now, the price's dot and age |
| 98 to 143 | adds risk and quantity · the origin on two lines (the rule, then the bot or "Your ticket") |
| 144 to 203 | adds the price line in words (source, age) · the track · `SL` and `TP`; R at 15 px |
| 204 to 247 | adds entry → mark · the P&L and its words; R at 20 px |
| 248 and more | adds exposure · capital at work · time held |
| 22 (a row; outside the real card only, when its column is full, §2.4) | symbol · side chip · R now |

  Every block wears a bar 3 px high along its foot: its value over the scale. REAL: the 3 px solid red edge. DEMO: a gold outline. PAPER: a grey outline. No venue: dashed. A capped block wears `›` after its world chip and a broken bar.
- **Where flows run.** A price's feeder leaves the river above the gutter at its block's **right**, drops, and runs along the block's top edge toward the left; on a REAL block the top-edge light stops 12 px short of the red edge, so the Eye's green never touches REAL's red. Money climbs the gutter at the **left** of its box, runs under the blocks, and enters its block along the bottom edge. Gutters are 9 to 10 px wide; a mote's light is 9 px across.
- **The block width** is the same everywhere: `(stage width − gaps − paddings) / columns`, between 152 and 206 (170 and 236 from 1680), found as if every empty family already held one column, so a first fill never changes it.
- **The money lane** runs under the baskets from the REAL pool to the right edge; each pool has a riser to it.
- **The banks**: RESERVE (three pools, never added; REAL prints available, used, on Sauron, outside); UPSTREAM · 24 H (arrived and taken by world; the rail and its age, and `waiting`; refused symbols and how many by real bots; the last refusal with its bot, world, code and time; its stored detail; the feeds' lights); DOWNSTREAM · 24 H (closes per world in R).
- **The legend row**: three keys (a price update, a signal or a close, an order's money), the scale's pill (a button: it refits the scale), the book's age, `Read as a table`. Every figure in it sits in an opaque pill.
- **Hover or focus on a block** opens its detail (entry, mark, P&L words, exposure, capital at work, risk, levels, origin, the Horde's words) and one line: "Its page is Positions ›, where CLOSE lives. Nothing here sends an order."

### 2.2 At 1920 x 1080

The same structure. The block width caps at 236 and the scale's cap is 380 px: a taller block would only add blank. The S1a tier raises the type by one step (cells 12-14 px). The sky's ribbon is 560 px wide. Checked on the mock: no clipped line, no overlap (`work/report_check.json`).

### 2.3 Under 1440 px wide (1280-1439)

Not drawn in the mock. The floor-size block of this edition is the compact form the first edition recommended for this tier, and the planner already takes columns away when the row is too wide, so the same rules should hold; the build must measure it at 1280 in A1 before saying so.

### 2.4 Growth rules, and how many positions fit

- The order inside a basket is REAL (in the card), then DEMO, PAPER, no venue (in the annex), then the newest first. It never depends on a price, a light or an R, so a tick never moves a block.
- **A column that is full, outside the real card.** Blocks give up height before any of them is hidden, the smallest first: a block taller than the floor drops to the floor; a floor-size block becomes a one-line row (symbol, side, R); the bar at its foot keeps saying its size. Only when every block of the box is a row does the smallest fold, whatever its band, under one line: `+N more · in the table`. A band with nothing left to show loses its head.
- **Real money** is never cut down to the floor or to a row. Its card takes a second column before anything of it folds, and its columns are the last to be taken away.
- **A row that is too wide.** Columns are taken where they cost least: an annex of several columns loses one; then the annex with the most room under its card goes under it; a card's extra column goes last. An annex with no room at all is reduced to a count in its card's foot: `+11 apart · in the table`.
- **Measured on the mock** (`shots/anduin_40_positions_1440x900.png`, `tools/render.js extra`): the forty-row stress book (7 real, 8 demo, 22 paper, 3 with no venue) draws **21 of 40** at 1440 x 900: the 7 real rows as full blocks, 3 other blocks and 11 rows; 19 fold. At 1920 x 1080 it draws **all 40**. A sixteen-row book draws all 16 at 1440 x 900.
- A family with nothing open keeps its place as a narrow dashed slot: the river still crosses it, and a signal can still arrive at its gate. When its first position arrives the slot opens into a card; the baskets at its right slide over in 0.4 s; the block width does not change.
- **A re-lay** (a fill, a close, a fold that changes) keeps the scale and the block width; what moved eases to its place in 0.4 s, and the river is redrawn with it.

### 2.5 The phone (390)

No canvas, no particles, no river: the same content as a list (`shots/anduin_390.png`).
1. The sky: level, score, age, words; the next print and the ribbon; the two switches (44 px high).
2. The reserve, REAL first.
3. The baskets, stacked: the card, then its annex; each band with its head, its sum and its bar; each block a full-width card with every line shown and a size bar with its figure.
4. **Last events**: the five newest lines (a refusal with its bot, world, code and detail; a fill; a close; a market that shut; the weather turning). They are the lines the river would have shown.
5. Upstream · 24 h, then Downstream · 24 h.
States are words and marks only: `stale · 15 min`, `closed · last 21:00 UTC`, `shut · reopens 14:30 UTC`, ⚠. Measured: 0 frames requested.

---

## 3. Every animation, and its trigger

**The rule: nothing moves without a real datum or event behind it, and nothing is asked of the screen when nothing moves.** There are no embers on this page: it does not opt in to the magic layer's ember field (`magic_spec.md` §4.2), so every moving dot means something. The void keeps its light from above, its vignette and its grain.

| What moves | Trigger (the datum) | How | Colour | Never |
|---|---|---|---|---|
| A price mote | one observed price update of a held instrument: A1, the mark's `at` advanced since the last poll (several stamps found at one poll leave in the order of their stamps, spread over 1 s at most); A2, one `quote` push or one venue stamp | **the age is printed from the stamp at once**; then the mote enters the river at its basket's gate, rides to the gutter at its block's right, drops, runs along the block's top edge and is taken in; the edge takes a 0.5 s light. It goes at the current's speed and never takes more than 1.2 s in calm weather: `speed = max(96 px/s, path / 1.2 s) x the weather's factor` | the Eye's green (light on what lives) | an age set, or reset, by the animation; a mote for a block whose price did not change hands; a mote under a shut market |
| A signal token | a signal seen for the first time (§1.4) | a diamond rides the river at 330 px/s from the spring to its family's gate; its opaque chip rides above it: `XAGUSD [SHORT] trend_break_4h` | ink outline, a small Eye glow | a token at page load; a token per bot pass; ▲ or ▼ for a side (they mean a result) |
| ... taken | `fill_open` for that symbol (A2), or a new seat at a poll (A1) | the basket re-lays (a slot opens into a card); the token enters and reaches the new block's corner; the block's frame opens in 0.6 s and its lines then stand at full strength; the chip reads `BTCUSD taken by Crypto #5 [REAL] · fill 91,230.5` | the block wears its world | a block before its row exists |
| ... refused | a refusal by §1.4's list, a `gate_reject`, or a rail departure | the token rises 34 px at the gate, grows and is gone in 0.9 s; the chip stays about 3 s: `XAGUSD refused by Commodities #4 [REAL] · cost_filter`; the Upstream card's "last" line and its stored detail change at the same instant; one chip per bot that judged the signal | ink; `order_in_doubt` coral with ⨯, and it stays | an evaporation for `hold`, `already_open`, `cooldown`, or for a code with no new signal behind it |
| ... born while its market is shut | a new signal whose family is frozen (M4) | the token stops at the frozen gate and waits in the ice, its chip reading `born while shut`; it moves on, or is judged, when the market opens | ink | an evaporation: nothing refused it |
| A money stream, out | a fill | twelve ink squares, 3 px, leave the pool of the block's world, 62 ms apart, at 430 px/s; a faint guide shows their path while they travel; the block's bottom edge takes a light when the last arrives | ink, always | a glow, a colour, or a stream for a paper fill from a broker pool: it leaves the PAPER pool |
| A money stream, back | a close (`fill_close`) | the block's lines leave at once; its place is held as a dashed outline, "closed", until its money has left the basket (1.5 s); then the basket re-lays; twelve ink squares return to the pool; the bet's token rides the river to the mouth with its chip: `EURUSD closed [REAL] · +$63.80 ▲ · +1.23R · at eToro's price` | **the squares are ink whatever the result; the result's colour is on the chip's figures**: jade or coral for a REAL close booked at eToro's price, ink for every other close and for an unmeasured one | jade or coral on a mote, on an estimate, or on a DEMO or PAPER close |
| A figure | a new reading | it is replaced at once, at full strength; its age restarts from the new stamp | n/a | a figure that counts up or down, fades in or out, or flashes Eye green on a change |
| The front on the ribbon | the time left to the print, at each poll | the hatched band slides toward "now" (0.7 s when its place changed); inside the window the band in the air appears above the touched baskets, at once | amber | a front for a print that is not high-impact by the care's rule |
| The stage re-laid | a fill, a close, a larger real position than the scale | what moved eases to its place in 0.4 s | n/a | a block that moves on a tick; a scale that shrinks by itself |

### 3.1 What each weather state changes

The river's band holds three still lines, 9 px apart; the outer two are half as high as the middle one. Heights below are the middle line's, on the mock's book (measured: 2.2, 4.2 and 5.7 px).

| State | The current (price motes) | The river's three lines | The baskets' outline | The sky |
|---|---|---|---|---|
| `calm` | x1 (96 px/s or more, §3) | 1 px high, plus up to 1.5 px for the family's volatility (p0 to p100); 34 px long | ink (the card's own hairline) | the level chip in ink |
| `stressed` | x1.5 | 3 px plus the family's; 26 px long | an amber hairline | the chip in amber with ⚠; the level's words |
| `crisis` | x2.1 | 4.5 px plus the family's, 6 at most; 20 px long | a coral hairline (an outline, never the REAL red fill) | the chip in coral with ⨯; the level's words, two lines |
| `recovery` | x1.2 | 1.8 px plus the family's; 30 px long | ink | the chip in ink, `recovery · day N of 10` (`market_stress.py:494 recovery_days`) |
| not measured | x1 | flat | ink | `— not measured: crisis mode is off` |
| a family's volatility | n/a | its basket's stretch of river is that much higher | n/a | `vol p41 · 3 inst · 11 Nov` in the head |
| a market shuts | no mote for its instruments | its stretch of river is three flat dotted lines under a pale hatch | **frost**: a pale outline, and the same hatch over its head and its body | the session count in the top bar; the head reads `shut · reopens 14:30 UTC`; feeders dotted; a block's price reads `closed`; text keeps its contrast |
| a print approaches | n/a | n/a | n/a | its band nears "now" on the ribbon |
| the front is over the book | n/a | n/a | a hatched amber band in the air above every basket that holds a touched row | `⚠ FRONT OVER THE BOOK`; the touched blocks wear the Horde's ⚠ and its sentence |

The surface is a **still** shape: it changes only when the level or a volatility changes, easing in about 0.5 s, so the weather costs nothing at rest. A wave never travels by itself; the motes follow the shape as they pass. The level's change is not a "moment": no flash, no sound. `shots/weather_calm_stressed_crisis.png` shows the three levels in one still.

### 3.2 What stays from the shell

The Eye mark breathes (Magic), one live dot beats (the eToro pill), the REAL ARMED dot beats: S1a's and the magic layer's rules, unchanged. All three stop under reduced motion, under the Ambience choice, and under the PIN lock (on the mock: 0 running animations while locked).

---

## 4. The two switches

### 4.1 Grouping

| Choice | Baskets | Head | Notes |
|---|---|---|---|
| **Family** (default) | forex, crypto, commodities, stocks and ETFs, indices; fixed order; an empty family keeps a slot | title, session, volatility | the only grouping with a frost per basket and a height of river per basket; real money in the card, the rest in the annex |
| World | REAL, DEMO, PAPER, no venue; only those that hold a row | the world chip and plain words (a money word never wears Orbitron) | each basket is one world: REAL's is solid, the three others wear the dashed outline; "N open · N markets open · N shut"; no annex |
| Lane | one basket per bot config that holds a row, "Your tickets", "By hand" | the config's label | real money in the card, the rest in the annex |
| Theme | `USD long`, `USD short`, `Equity long`, ..., `No theme` (N6) | the theme | the same |

A change of grouping re-lays the stage at once and refits the scale; motes in flight are dropped and the next updates draw new ones. The choice is remembered per user (a display preference, the Operations Center's mechanism).

### 4.2 Sizing, and the one scale

| Choice | A block's height | A band's sum and bar |
|---|---|---|
| **By exposure** (default, his word "volumes") | `cap x exposure / the scale`, never under the 48 px floor, never over the cap | exposure at the mark, per world |
| By risk | the same with risk at the stop | risk at the stops, per world |

- **Real money sets the scale.** The scale is the largest REAL value in the book (the largest value shown only when no REAL row exists, and the pill says so). Above the floor, two blocks' heights are in the ratio of their values: on the mock EURUSD ($21,749.00) is 255 px and GBPUSD ($12,904.40) 151 px.
- **A DEMO or PAPER row never sets it.** A block above the scale is drawn at the cap, with `›` after its chip and a broken bar; a band's sum above the bars' scale is capped the same way. On the mock, by risk, NAS100 (DEMO, $110.50 against a scale of $52.00) is capped.
- **The scale is a ruler, and it is printed**: `full height = $21,749.00 · set by real money at 20:46 UTC ↻`. It is set when the page is laid out (at load, at a switch, at a resize, at a click on its pill). **It never shrinks by itself**: when the largest real position closes, the other blocks keep their size. A real position larger than the scale enlarges it at once, with one re-lay.
- **The cap** is the height one real block can take alone in its card, and one other block under an empty card with room for a fold line: 255 px in the family view at 1440 x 900, 286 px in the other groupings (their foot is shorter), 380 px at most.
- **The floor is a legibility floor.** Under it, height no longer says size; the bar at the block's foot does, and its title gives the figure and the scale.
- A row with no figure for the chosen measure (no stop under "risk", no USD stamp under either) is drawn at the floor, left out of its band's sum and counted `apart`.
- A third measure exists and is not offered as a size: capital at work (margin or cost). It is what leaves the reserve; it is printed in the card's foot, in the tall blocks and in the detail.

---

## 5. Truth rules, and what the page does not do

### 5.1 Truth

1. **Worlds are never added, in a figure or in a shape.** No total cell exists. A count may be totalled beside its split (`8 · 3 real · 2 demo · 2 paper · 1 no venue`); money never. The solid card is REAL's; the scale is REAL's; each world's band has its own sum and its own bar. Tests assert that no element sums two worlds and that no box other than the annex holds a block of a second world.
2. **DEMO is never REAL**: the world is `world_of` on the row, and on the routed account for a pool.
3. **Every stored reading prints its age.** One payload, one age: the pill `book read N s ago` covers the blocks, the bands' sums and the baskets' counts. A reading with its own, older age prints it: the reserve's cells, each price, the weather's reading, the rail, the calendar, the volatility's newest bar. A reading with no age is drawn as a dash.
4. **An age comes from its stamp.** It is `now − at`, it is never written by an animation, and it never decreases without a new `at`.
5. **A dash says why**, in its title and in the table. Zero is a measured zero.
6. **Estimates are ink.** Jade and coral sit only on a side chip, on the track's gain fill (a loss is a coral hatch with an outline, never a red fill), and on the figures of money eToro states or booked at its price. The Eye's green is light: motes, live dots, the selected switch, the active nav row. It never marks a gain, never sits behind a figure, and never runs beside REAL's red edge.
7. **Money is never a light.** A money stream is ink squares, whatever its result.
8. **The solid red is REAL only**: the chip, the block's edge, the REAL band's bar, the armed pill. A crisis is a coral outline.
9. **No figure on the void or on a glow, and no figure fades.** Flows travel only where no text is: the river's band, the gutters between and beside blocks, the block's own edges, the lane, the void. Every chip that rides with a flow is opaque, and it appears and leaves at full strength. A forming block opens its frame first; its lines then stand at once.
10. **One figure, one reader** (§1). The blocks' figures are the Horde's seats, so Anduin, the Operations Center, the Horde and /positions/ print the same digits.
11. **The reserve reconciles**: `used` = `on Sauron` + `outside`, and `on Sauron` is the sum of the cards' `at work` figures.
12. **Mote counts are not figures.** Twelve squares is "one fill", whatever its size; the amount is printed in words.
13. **The mock condenses, and says so with a second clip.** In the mock a live price draws a mote every 3 s or so. On the real page before A2 it is at most one per instrument per poll; eToro's quotes arrive every 30 s for open REAL rows (`etoro_quotes.py:97`) and a tick stamp is rewritten every 240 s (`venue_mark.py:107`). `?cadence=real` and `shots/anduin_real_cadence.webm` show that pace. The still river carries the meaning alone: the three lines, each block's price dot and age, each feeder's state.

### 5.2 Does not do

- No button that moves money: no CLOSE, no TAKE TRADE, no kill switch, no switch. A block's link goes to /positions/; a token's chip links to the rail.
- No broker call and no model call to draw it: it reads what Sauron already stored.
- No invented figure, and none in a particle.
- No replay at page load, no sound, no notification. **A return after a long hidden spell is a fresh load**: no flow is replayed, the counts and the last events tell what happened.
- It does not replace the Operations Center (his desk) or the Horde (the lights' home).
- It does not judge: no advice, no "should". The weather is the posture's own words; a refusal is the bot's own code and detail.
- It writes nothing but the user's two display preferences.

### 5.3 Performance budget, measured on the mock

Conditions: headless Chrome, 4 Xeon cores at 2.1 GHz, **no graphics card** (software raster and compositing), 1440 x 900, DPR 1, two windows per row; the box was shared (load 0.6-1.8). CPU is Chrome's whole process tree. Script `tools/measure.js`; two runs on the final mock, both given where they differ (the last is `work/cost.json`; both are in `final_log.md`).

| Page | CPU, cores | Main thread, ms/s | Frames asked, /s | Drawn frames, /s | Work per drawn frame | Actors at most |
|---|---|---|---|---|---|---|
| A flat page (the floor) | 0.001-0.003 | 0 | n/a | n/a | n/a | n/a |
| Anduin with the river stopped (`?motion=0`): cards, the Eye's breath, the two beats | 0.053 | 1 | 0 | 0 | n/a | n/a |
| **Idle: every feed quiet** (`?quiet=1`) | **0.056-0.059** | 4.5 | **0** | **0** | n/a | 0 |
| **At rest, today's real pace** (`?cadence=real`: a 30 s quote, a 10 s poll) | **0.105-0.112** | 20-20.5 | 13 | 6.7-6.8 | 0.17-0.20 ms | 2 |
| At rest, the mock's condensed pace (a price about every 3 s per live instrument) | 0.193-0.222 | 48-56.5 | 43.1-43.7 | 22.1-22.4 | 0.11 ms | 4 |
| **The scripted story, looping** (two signals, a fill, two money streams, a close, the weather turning) | **0.324-0.357** | 90.5-103.5 (script 9-10.5) | 51 | 25.1 | 0.39-0.42 ms | 16 |
| At rest, 1920 x 1080 | 0.273-0.296 | 67-76 | 43.4-43.6 | 22.3 | 0.11-0.12 ms | 4 |
| CPU slowed 4x, at rest | n/a | 187-192.5 | 43.2-43.4 | 22.1-22.2 | 0.33 ms | 4 |
| CPU slowed 4x, the story | n/a | 348.5-362 | 49.3-50 | 24.8-25.1 | 1.41-1.55 ms | 16 |

Reading:
- **Idle costs what the still page costs** (0.056-0.059 against 0.053) and asks for no frame: when no actor is alive and the bed is clean the loop stops, and one timer wakes it at the next event, price or second (the ages' tick). The first edition's loop re-armed itself for ever and cost 0.107 idle.
- A frame is drawn once per slot of a thirtieth of a second, so 30 a second is a ceiling whatever the display's rate; the averages above are lower because the page sleeps between flows.
- What the river costs is compositing a full-stage canvas in software while something moves; the script is 4-9 ms a second. A graphics card removes most of it; the order carries over, not the ratios.
- On a CPU four times slower a drawn frame of the story takes 1.4 to 1.6 ms on average.
- **The preview board** (`Anduin.dc.html`): 0.13 of a core and no layout while its three motes and one token move (CSS `offset-path` in steps of a thirtieth of a second); 0.001-0.004 and still under reduced motion. Its first edition ran SMIL at the display's rate: 60 layouts a second, 0.32, and it kept moving under reduced motion.

**Budgets for the build** (asserted where a test can, measured in every PR with the scratch harness):
- at most 30 drawn frames a second; **idle = the still page within 0.01 of a core, and 0 frames asked**; at most 60 actors alive (a burst of events queues: at most 3 tokens and 2 streams at once, the rest wait);
- work per drawn frame p95 ≤ 1 ms at CPU 1x, ≤ 3 ms at 4x;
- **the reader has its own cache**: `horde.board()` is not cached (`horde.py:2167-2169`), so the first edition's "behind the Horde's 20 s cache" was wrong. Anduin's reader keeps its payload 10 s per user, keyed on the Horde's fingerprint; the 10 s poll asks for the marks only; the 30 s poll for the rest. Query budget to confirm by measure after `cache.clear()`, before it is fixed: ≤ 60 cold and ≤ 20 warm for the full payload (the Horde's board is 47 cold, 16 warm, the Operations Center's §7.2), a handful for the marks; no query in a loop over positions;
- one request per poll; polls stop when the page is hidden;
- if the branch's measure on a machine with a graphics card passes 0.15 of a core at rest, split the canvas: a river strip that redraws, and an event canvas that exists only while a token or a stream is in flight.

### 5.4 The pauses (measured, frames drawn in 2 s)

| State | Detected by | Drawn |
|---|---|---|
| Running (the mock's pace, at rest) | n/a | 49-50 (it sleeps between flows) |
| Tab hidden | `document.hidden`, `visibilitychange` | **0**; the loop and its timer both stop; it draws again after showing |
| PIN lock | `sv:pin-locked` / `sv:pin-unlocked` (idle-lock.js) | **0**, and 0 running animations: the shell's three loops stop too |
| The table view open | the page's own state | **0** |
| Reduced motion | `prefers-reduced-motion: reduce` | **0**: no frame requested, 0 running animations; the still bed (the river's lines, the feeders, the lane) is drawn once |
| The phone | the layout | **0**: the canvas is not shown |
| Ambience Off / Calm (the magic layer's choice, §4.6) | `body[data-sv-ambience]` | to build in A1: Off and Calm draw the still bed and no mote, as reduced motion does |
| A dialog holds the page | `body.sv-scroll-locked` | to build in A1: 0 |

### 5.5 Accessibility

- **The table is the page.** "Read as a table" (a button, `aria-expanded`; Esc closes) replaces the stage with tables: the weather; the prints of the next six hours (each band of the ribbon by name, its window, what it touches, what the care has lit); the positions (basket, symbol, world, side, exposure, capital at work, risk, R, stop, target, the price's state, source and age, where it comes from, the Horde's words); the families (market, volatility with its bar date, signals, taken, refused, at eToro not on Sauron); Upstream's counts; the last events. Both canvases are `aria-hidden`.
- **The flows are also lines of text.** Each event is one line in an `aria-live="polite"` region, the same five "last events" the phone shows. Under reduced motion the newest line stands in the air as a still chip (`LAST EVENT 20:31 UTC AAPL …`), the legend's three keys are not shown, and the table lists the five.
- **Under reduced motion** the same content stands still: states are words and marks (`stale · 15 min`, `closed`, `shut · reopens ...`, ⚠, the level chip, the baskets' tone). An event changes the words and the counts, with no motion.
- Colour never works alone: a side is a word in a chip (LONG, SHORT), on a block and on a signal's chip alike; ▲ and ▼ mean a result and nothing else; a world is a word; a stale price is an amber dot, its age and the Horde's ⚠, and the word from 144 px up; a level is a word, with ⚠ or ⨯; a gain carries its sign and ▲.
- Every block is focusable in reading order (REAL first) and opens its detail on focus. Nothing under 11 px; every text measured at 4.5:1 or more on its own ground (the mock's check: none below).
- Touch targets on the phone: 44 px for the switches.

---

## 6. The mock, and what was checked on it

- **The story (12.8 s)**, on a clock that jumps between events: rest in calm weather (20:46 UTC); a signal on XAGUSD arrives and Commodities #4, a real bot, refuses it (`cost_filter`, with the stored detail); a signal on BTCUSD is taken by Crypto #5: the Crypto slot opens into a card, the money leaves the REAL reserve, a REAL block forms; XAUUSD's price turns 15 minutes old and its stream dries (20:58); the stocks' market shuts, their basket freezes, and the print's front reaches the book (21:00: both are true at that minute); a quarter of an hour later a new stress reading turns the weather to `stressed` (21:15: the calendar does not drive the level); EURUSD closes, booked at eToro's price $1.20 under the estimate, and its money flows back; the reserve's cells and the status bar's PORTFOLIO change with the next reading.
- **Two clips**: `anduin.webm` at the mock's condensed price pace; `anduin_real_cadence.webm`, the same story with prices at today's real pace (one EURUSD quote, one AAPL quote and one EURJPY poll in 13 s). Send both: the second is what A1 will look like.
- **Checks run on every render** (`tools/render.js`): no page error; no request but the fonts (served from local copies); no text under 11 px; no text under 4.5:1; no clipped line; no block, head, pool or card body taller than its box; no basket past its region; no two blocks or chips overlapping. All empty at 1440 x 900 (rest, the three moments, the end of the story, the forty-row book, the three weather levels), 1920 x 1080 and 390; and for the four groupings, both sizings, a sixteen-row book and an empty book (`tools/switches.js`, `final_work/stress.js`).
- **Looked at**: every image in `shots/`, and frames of both clips. Fixed after looking in this edition: a class name of the new blocks that met the sky's "overline" class and set a capped block in capitals; a sentence of the Upstream card that passed its card; the ribbon's "+6 h" under the touch count; the front's band under the words UPSTREAM and DOWNSTREAM; a foot that printed "not known" for an empty real band; an annex that folded every row while room was left under it.
- **The board** (`Anduin.dc.html`): the page at rest, built from the mock's own markup; the two canvases are replaced by one still SVG with the same geometry; three price motes and one refused signal move by CSS `offset-path` in steps of a thirtieth of a second, the refusal replaying every 12 s; one rule under reduced motion hides them. No SMIL, and no script but the closing `text/x-dc` block. `canvas_entry.json` places it on a new row under board 5 (x 0, y 3360) as "7 · Anduin, la page des flux".

---

## 7. Decisions for him (the note asks; defaults in bold)

1. The name: **Anduin**, or his own.
2. The default grouping: **by family**.
3. The default sizing: **by exposure** (his word "volumes"), risk one click away.
4. Its place: **a page of its own**, `/anduin/`, opened from the sidebar (Amon Hen, after the Operations Center), and from Barad-dûr (a tile on its ring and the key A) once Barad-dûr exists: its E1 is not built and is not a prerequisite of A1.
5. How present the weather is: **as in the mock** (speed, the river's lines, the outlines' tone, frost, the ribbon and the front's band), or quieter (the sky's words only), or stronger.
6. The scale: **real money sets the scale and owns the solid basket; DEMO and PAPER sit apart in each basket and are capped at the scale.** The alternative is one scale for the three worlds, where a large DEMO or PAPER row shrinks his REAL blocks and swells the basket.

## 8. The stages

Each stage is its own PR, tests first. **Money direction of every stage: none.** No stage touches an order path, a gate, a size, a switch or a broker call; the only writes are two display preferences.

### A1. The real page, read-only, polled (after S1a and the magic layer merge; shares N2, N3 with the Operations Center's OC2)

- **Goal.** `/anduin/` with real data: the sky (level, score, age, words, the ribbon, the touch and lit counts), the baskets with their cards, annexes and blocks, both switches and the scale's pill, the reserve, Upstream and Downstream, the detail, the table, the last events, the phone list. Flows by polling, every 10 s for marks and 30 s for the rest: price motes from observed stamp advances; a token and a block for a seat that appeared; an evaporation for a new refusal; a stream for a seat that appeared or a row that closed between two polls.
- **Files.** `dashboard/anduin.py` (the reader, N1), `dashboard/views_anduin.py`, `templates/dashboard/anduin.html`, `static/js/sv-anduin.js`, `static/css/sv-anduin.css`; the nav row; additive fields on the seat (N2, N3); the session aggregate (N5); the theme (N6). Barad-dûr's tile comes with Barad-dûr.
- **Tests first.**
  - The reader, on the Operations Center's fixture: each block's world equals `world_of`; no key of the payload sums two worlds (a walker over the payload); each band's sum equals the sum of its blocks' own figures; a row without a USD stamp and a row without a stop are `apart`, never zero; the reserve's `on Sauron` equals the sum of the REAL rows' `at_work`, and `on Sauron` + `outside` = `used`.
  - **The scale and the shapes**: the scale is the largest REAL value; adding a DEMO row of $500,000 changes no REAL block's height and no REAL bar; above the floor, two blocks' heights are in the ratio of their values within 2 %; the bars of the REAL bands rank as their REAL sums; the card holds no block of another world; closing the largest real position changes no other block's height.
  - The digits: a block's R, risk and mark equal the Horde's seat for the same row (mock `wraps` on `horde.board`).
  - Every stored reading in the payload has an age, or is a dash with a reason; the named dashes of §1 each have a test (no eToro row, the other world, no stress reading, `crisis_mode` off, calendar unread, no quote, no stop, no USD stamp).
  - **Ages**: a printed age is `now − at`; over a run of polls and animations an age never decreases without a new `at`.
  - **Skips**: a fill followed by `already_open` draws nothing; `hold` a hundred times draws nothing; `cooldown` draws nothing; a held symbol's `no_price` draws nothing and an unheld symbol's draws one refusal; the same (config, symbol, code) for the same signal draws once; a code that flips with no new signal draws nothing; `no_signals` and `stale_signals` are nothing; a refusal carries its config's label and world.
  - The clock: an index is never frozen; a basket freezes only when every instrument it holds is shut; an unmodelled class is never frozen; a signal born while its family is frozen waits and does not evaporate.
  - The touch count runs on every row (a hand-kept stock is touched by a USD print); the lit count is the care's record.
  - Staff and viewer: a viewer sees his own rows only; `new_signal` is staff-only today and the token follows that rule.
  - The template: no element with a money control's hook (`data-sv-close-trade`, the ticket's, the switches'); a test lists the page's links and forms.
  - A Node test of `sv-anduin.js`: the layout (the cap, the floor, the tiers, the annex under or beside, the row tier, the fold's order, real money last, the slot), the path builder (every path stays inside gutters, a feeder never runs beside a REAL edge: a property test against the block rectangles), a mote's travel is 1.2 s at most, the pauses, **the idle loop: no frame is requested when no actor is alive**.
  - Budgets: the query counts after `cache.clear()`, for the full payload and for the marks-only answer; the scratch harness measure (§5.3) in the PR, idle included.
- **Acceptance.** The mock's rest frame reproduced on the fixture at 1440 x 900, 1920 x 1080 and 390; his book in his browser, read with him.
- **Size.** M-L.

### A2. Live events (after A1; nicer after Barad-dûr's E2)

- **Goal.** The flows at their own instant: `fill_open`, `fill_close`, `close_pending`, `scale_out`, `gate_reject`, `new_signal` on `/ws/eye/`, `quote` on `/ws/dashboard/`. Each event triggers one re-read of what it names, then its flow. The poll stays as the safety net and for what has no event.
- **Tests first.** A Node test of the event table (each kind to its flow; an unknown kind draws nothing); the world of a flow and the colour of a result come from the re-read row, never from the event (an event with a forged `world` or `pnl` changes nothing); a burst of 50 events keeps at most 3 tokens and 2 streams in flight and drops none from the counts; the socket closing prints "live updates paused" and the motes stop; reconnecting re-reads once; a return after a hidden spell replays nothing.
- **Acceptance.** The mock's story reproduced on the fixture by firing the same events through the channel layer, recorded.
- **Size.** S-M.

### A3. The weather complete, and "the last 24 h" replayed (after A2)

- **Goal.** Volatility per family (N4) and its height of river; `recovery` and `crisis` drawn; the ribbon's later prints; and a replay: a button "Replay 24 h" plays, in at most 20 s with a clock and a caption, what the stored rows can prove: fills and closes (`opened_at`, `closed_at`), signals (`created_at`), rail departures, the caps' refusals, the stress readings, the sessions' opens and shuts (computed), the prints' times. It says what it cannot show: the refusals between two skips (N7) and the past freshness of prices (N10).
- **Tests first.** The volatility: the median of `vol_percentile` over the family's instruments, `—` when no instrument has the 140 daily closes it needs, cached 15 min, never computed in the request when the cache is warm, its bar date in the payload; the replay's event list is built from dated rows only and is the same list the table view prints; no replay without his click; the replay pauses like the river; under reduced motion it is a list.
- **Acceptance.** A day of his book replayed beside its trade journal: every fill and close of the journal appears once, at its time.
- **Size.** M.

## 9. Unsure, to settle in A1

- **The real river is quiet** before the eToro-grade feed's later stages: an eToro tick stamp is rewritten every 240 s, quotes every 30 s for open REAL rows only. `shots/anduin_real_cadence.webm` shows it. If the real page reads as dead, the remedy is A2's `quote` push, not an invented drift.
- **`waiting` may be large**: `hold` is written on every pass for every quiet symbol with a signal. It is a count now, out of the evaporations; whether he wants it on the page at all is his call.
- **Exposure on levered forex and indices** dwarfs stocks (a 1-lot index is $20,872 against $908 of shares in the mock), and now the picture says so: one tall block, the rest at the floor. "By risk" spreads the heights. That is why the default is a question for him.
- **Forty rows at 1440 x 900 fold 19** (§2.4). The row tier and the fold are drawn; a book much larger than that needs the table, or the larger screen.
- **A block cut down in a full annex** no longer says its size by its height, only by its bar. If that reads as a lie on his book, the alternative is to fold it.
- **Several chips for one signal** (one per bot that judged it) are specified, not drawn in the mock: its story has one bot per signal.
- **The Theme grouping** rests on `classify_full`'s three themes; whether they are the baskets he means by "theme" is his call.
- **The 1280 px tier** is not measured (§2.3).
- **The board's host**: it was rendered here with scripts disabled, in the Signature board's exact frame; it was not opened in the canvas itself, and it now relies on CSS `offset-path`.
