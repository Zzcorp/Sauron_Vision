> Handoff copy: the symbol the operator asked about is written `<SYMBOL>` here (public repository).

# Fixes spec: off-market signals, the watchdog, Ask Sauron's facts, feedback on trades

**Basis:** main `15dd487`. Every `file:line` is relative to the repository root at that commit. Most references come from the five maps, each checked by its own script against the read-only checkout; those this spec adds, and those it leans on most, were re-read there on 2026-11-11.

**Why:** the operator's message of 2026-11-11 (the "evidence chain is broken" alarm, signals while markets are shut, feedback on trades, and Ask Sauron's wrong answer to "why is Sauron not trading").

**Revision of 2026-11-11, after two verifications.** The findings of `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/verify_truth.md` (S1 to S10) and those of `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/verify_rules.md` that touch this spec were each checked against the read-only checkout and are applied below. What was applied, changed or rejected, with the reason, is in `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/final_log.md`. The spec as it stood before is `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/_apply_work/fixes_spec.before_apply.md`.

**Sources.** The five maps hold the evidence, the scratch runs and the prototypes. Read the map named in each fix before building it.

| Map | File |
|---|---|
| M1 entry path | `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/m1_entry_path.md` |
| M2 stages and ladder | `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/m2_stages_ladder.md` |
| M3 alarm | `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/m3_alarm_idle.md` |
| M4 off-market signals | `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/m4_offmarket_signals.md` |
| M5 feedback and Ask Sauron | `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/m5_feedback_asksauron.md` |

**Prototypes (scratch only, not the fix):**

- F1: `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/_m4_work/proto/m4_proto.py` (`market_state`, `levels_reason`, `birth_decision`, `release_decision`).
- F2: `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/_m3_work/proto_watch.py` (`classify`, `decide`, `LIVE_ACTION_WORDS`).
- F3: `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/_m5_work/scripts/proto_no_trade.py` (`collect`, `print_report`, `extra`, `rule_facts`, `symbol_facts`, `named`, `ask_block`, `mask`).

---

## 0. The four fixes at a glance

| Fix | What | New switch (OFF on arrival) | Migration | Money direction | Model spend | Needs his word |
|---|---|---|---|---|---|---|
| F1a | Signal announcements wait for the market to open | `signal_market_hold` | `signals/0020_signalhold` (additive) | none | none | no |
| F1b | The rail shows shut-market signals in a "MARKET SHUT" section | the same switch | none | none | none | no |
| F2 | The watchdog says "live by decision" once and alarms only on faults | none (existing `pipeline_campaign_watch`) | none | none | none | no |
| F3 | One read-only reader for `why_no_trade` and a fact block for Ask Sauron | `ask_sauron_bot_facts` | none | none | about $0.002 to $0.012 of input a staff question | no to build; the switch is his word |
| F4 | A "Feedback" card on the position page | `trade_feedback` | none | none | none | no |
| later | Debrief lesson by a model; automatic Council sitting after a LIVE hand trade | `trade_debrief_ai`, `council_ticket_auto` | one table for the lesson | none | yes | **yes** (section 5.6) |

**Build order:** F1a, F1b, F2, F3, F4. Each is its own branch and pull request, and each ships alone. None depends on another, except F1b, which needs F1a merged.

---

## 1. Rules that bind every fix

1. **Tests first.** Write the listed cases, see them fail, then build. Each fix carries its own "nothing moved" test (money direction).
2. **A new switch arrives OFF.** Its row goes in `DEFAULT_COMPONENTS` (`core/platform_control.py:158` onward). With its switch OFF, a switched fix leaves every page, message and response byte-identical to main (F3d's one deliberate prompt sentence apart). Three parts have no switch and change bytes on arrival, on purpose: F2 (the watchdog's messages and the `paper_readiness` output), F3a (two buttons gain an attribute) and F3c (the `why_no_trade` output). Read a switch with `is_component_enabled`, which answers False for a key that has no row yet (`core/platform_control.py:72-77`): an unseeded switch is then today's behaviour.
3. **Descriptions stay under 300 characters.** Postgres enforces the column; SQLite does not. An overlong description once failed `seed_components` on deploy. `tests/test_seed_data_fits_postgres.py` checks every row.
4. **None of the new switches is a PIN switch.** None moves account money, so none goes in `LIVE_MONEY_SWITCHES` (`core/platform_control.py:97-110`). The operator turns each on by its own row at `/ops/` or with `component on <key>`.
5. **"all on".** `BULK_ENABLE_EXEMPT` is pinned by equality in `tests/test_ops_cockpit.py:557-592`, and that test wants every exempt key outside the Lore readers to be a System row. The three switches of F1, F3 and F4 spend nothing to speak of and move no money, so they are **not** added to the exempt set and that test is left alone. The two later switches that start model spend (section 5.6) must be exempt; that edit changes the pinned test on purpose.
6. **`TESTS_GREEN`.** `core/wall_facts.py:52` holds the suite's test count (16121 at `15dd487`) and `tests/test_wall_facts.py:165-183` counts the suite against it. Every fix adds tests: update the number last, after every other edit, and verify it with its own full run. After a rebase on a main that merged another fix, recount.
7. **No private value in a test, a fixture, a message or a commit.** No real symbol list, size, result or account figure of the operator. Synthetic rows only.
8. **Telegram house style.** No raw key outside the folded `<code>` record; `tests/test_telegram_house_style.py` and the `jargon` check of `tests/test_telegram_polish.py` enforce it.
9. **A new management command** must be listed in `core/ops_commands.py` or exempted (`tests/test_ops_cockpit.py:83`). None of the four fixes needs one.
10. **Other worktrees are not to be touched.** Open branches touch some of the same files (section 6).
11. **The deploy runs `migrate --noinput`, `seed_instruments` and `seed_components` by itself** (`deploy/docker-compose.yml:131-134`). A new switch row and an additive migration need no hand step. Turning a switch on is the operator's step, given to him in a French sheet (section 7).
12. **A switch that gates no task has no run to show.** Its "Last run" on `/ops/` stays empty, as `council_ticket`'s does. Check how the system map draws such a row before merging (`dashboard/views_topology.py:185-195`, `:339`): the three new switches must not read as broken.

---

## 2. F1. Signals while the market is shut

Map: M4, sections 5 to 8. Two pull requests: F1a first, F1b after.

### 2.1 Behaviour before

- No writer of `Signal` rows, no announcement and no rail rule asks the market clock (`core/exchange_status.market_clock`, `core/exchange_status.py:743`). The bots, the paper venue, Morgul and the ticket do.
- A signal born while its market is shut is a normal row. It gets the "New signal" banner on every staff page, a bell row for every user, a Telegram message with "Prepare ticket" (not for a born-at-research rule still at research, `signals/announce.py:100-111`), and a rail card with "▶ TAKE TRADE" for 24 hours from `created_at`, or from the scanner's last match of the same signal (`dashboard/signal_rail.py:498-500`, `:638-641`).
- It is born at fixed moments: the 09:00 UTC opportunity scan every day (`config/celery.py:460-463`), the 23:45 UTC full-universe scan (`:373-376`), a closed-bar rule reading a session's last bar after the bell (M4 run E2: Friday's 20:00 bar was written on Saturday at 00:05 UTC), and a re-fire on the same unchanged bar 24 hours after a close (M4 run E3).
- The bots already refuse a shut market (`bot_program/entry_timing.py:139`, `bot_program/asset_engine/base.py:5111-5122`). These signals cause no order.

### 2.2 Behaviour after F1a (the announcements wait)

With `signal_market_hold` ON:

1. **At birth.** The signal is written exactly as today. If its market cannot trade now, nothing is announced and one `SignalHold` row is written (state `held`, reason `market_shut`, the words, `reopens_at`). If the hold cannot be written, the signal is announced as today.
2. **Every 5 minutes**, inside `run_signal_lifecycle` after the grading loop and in its own `try`, a release pass reads the held rows. First match wins:
   1. the signal is no longer active: drop, `closed`;
   2. it is 24 hours old or more: drop, `aged_shut`;
   3. its market is still shut or settling: wait;
   4. a price of the new session exists (a quote written after the open plus 15 minutes and at most 15 minutes old, the bound of `signals/performance.py:61`; else the close of a 1h or 4h bar opened since the session opened): judge it with `levels_reason`; drop (`stop_crossed`, `target_reached`, `chased`) or release;
   5. no such price 30 minutes after the settling window: release, saying "no price since the open: its levels were not re-checked".
3. **A release** announces once through the same three steps as a birth (banner, bell, channels), with one more sentence: "fired Sunday 09:00 UTC, while its market was shut". Releases go out best score first; the existing guard of 20 Telegram messages an hour (`alerts/dispatch.py:11-12`) holds the rest and says how many.
4. **A born-at-research rule still at research:** banner and bell wait like the others; Telegram stays off, as today.
5. **The switch turned OFF while rows are held:** the release pass still settles them. The switch gates the hold at birth only, so no signal is swallowed.

**"Cannot trade now" is one function**, `market_state(instrument, now=None)`:

| Class | Held when | Source |
|---|---|---|
| crypto, an unmodelled class | never | |
| forex, stock, ETF, commodity | `market_clock` reads shut, or opened less than 15 minutes ago | the class set is `entry_timing.SHUT_CLASSES` (`bot_program/entry_timing.py:139`), the settle is `entry_timing.OPEN_SETTLE_MINUTES` (`:113`). A test pins both equalities |
| index | the cash session and the CME futures week are both shut, or the cash session opened less than 15 minutes ago | `market_clock("index", ...)` and `market_clock("commodity", "CME")`. An approximation for non-US indices, said as one in the words |
| a clock that cannot be read | never, with a WARNING | the house rule of `bot_program/entry_timing.py:74` |

The hold reads only "shut" and "opened less than 15 minutes ago". It does not reuse the bots' whole timing verdict (rollover, the hour around a print, Friday's last hour): in those the market is open.

### 2.3 Files, F1a

| File | Change |
|---|---|
| `signals/market_hold.py` (new) | `GATE = True` (read at call time); `enabled()` (the switch); `market_state(instrument, now=None)`; `levels_reason(direction, entry, stop, target, mark)` (stop crossed, target reached, chased under `manual_trade.REWARD_RISK_WARN`, `bot_program/manual_trade.py:1201`); `hold_at_birth(signal, now=None)`; `release_due(now=None)`. It must not import the rail, nor name it (the first trap below) |
| `signals/models_hold.py` (new), one import line in `signals/models.py` (beside `:231-233`), `signals/migrations/0020_signalhold.py` | `SignalHold`: one row per held signal (one-to-one), `state` (held, released, dropped), `reason`, `words`, `reopens_at`, `held_at`, `decided_at`, `mark`. A signal announced at birth has no row. `0019_rulecontrol_scope` is the last migration on main and on every open branch checked on 2026-11-11; check again before numbering |
| `signals/announce.py` | `announce_new_signal` (`:65-119`) asks `hold_at_birth` first and returns `{"signal_id", "held": words}` when held. New `announce_released(signal, note)`: the same three steps with the note. All four creators already pass through `announce_new_signal` (`signals/tasks.py:154-155`, `:370-377`; `signals/opportunity_scanner.py:1868-1870`; `signals/fast_rules.py:245-247`) |
| `alerts/notify.py` (`notify_new_signal`, `:8-23`), `alerts/dispatch.py` (`signal_telegram`, `:93-152`; `dispatch_signal_alert`, `:287`) | an optional `note`: the bell body ends "· fired Sunday 09:00 UTC, while its market was shut"; the Telegram message gets one line "Fired Sunday 09:00 UTC, while the market was shut. First price since the open: ..." |
| `signals/tasks_lifecycle.py` | `run_signal_lifecycle` (`:41-72`) calls `release_due()` after its loop, fenced; its counts join the result |
| `core/platform_control.py` | the row `signal_market_hold`, category `pipeline`, name "Signal Market Hold". Description: what it holds, that OFF means "announce at birth, as before", that it moves no money |
| `tests/__init__.py` | `_market_hold.GATE = False` with the reason, beside `_paper_trader.MARKET_HOURS_GATE` and `_entry_timing.GATE` (`:20`, `:26`): without it a test that turns the switch on would depend on the hour it runs |
| `tests/test_signal_market_hold.py` (new) | the cases of 2.4 |

**Four traps the build must respect** (existing tests pin each one):

- **The rail guard is a text search.** `tests/test_rail_lifecycle.py:1119-1146` reads every Python file outside `tests/` and the rail's own display modules and fails on the words `signal_rail`, `rail_prefs` or `RailDeparture`, in a comment or a docstring too. `signals/market_hold.py`, `signals/models_hold.py`, the migration and every edited engine file must not contain them. (Test 22's comparison with `_price_verdict` lives in a test file, which the guard does not read.)
- **`signals/tasks_lifecycle.py` must not contain the word `guarded_task`,** in a comment either (`tests/test_paper_readiness.py:143-149`): the release pass is called from the lifecycle task, never gated by a decorator there.
- **The birth path keeps its two one-argument calls.** `announce_new_signal` goes on calling `notify_new_signal(signal)` and `dispatch_signal_alert(signal)` with one argument: `tests/test_signal_announce.py:67-84` replaces both by one-argument functions, and an added `note=` keyword would raise inside the fenced step and turn "ok" into "failed". Only `announce_released` passes the note.
- **The hold row is written inside its own savepoint,** so a database refusal cannot poison a creator's transaction; the fallback of 2.2 (announce as today) then really runs.

**One deliberate difference from M4.** M4 proposed the switch ON on arrival, read so that a missing row means ON. This spec keeps the house rule: OFF on arrival, read with `is_component_enabled`. A missing row is then the old behaviour, which is the safe side, and the operator turns it on with one line after the deploy.

### 2.4 Tests first, F1a (`tests/test_signal_market_hold.py`)

Clock fixed with the `_at(when)` pattern of `tests/test_paper_market_hours.py:59-65`; instants in November (winter hours) and one set in July.

*The clock (no database):*

1. Crypto on a Saturday is never held.
2. Forex: Saturday 2026-11-07 00:05 held, opens Sunday 22:00 UTC, tradeable 22:15; Sunday 21:30 held; 22:05 settling; 22:20 open. In July the same at 21:00.
3. A US share: Monday 09:00 held until 14:30; Thanksgiving 2026-11-26 15:00 held until Friday 14:30; Friday 2026-11-27 18:30 held until Monday 14:30.
4. Gold on COMEX at 22:30 UTC on a Tuesday: held until 23:00.
5. SPX500 at 03:00 UTC on a Tuesday: not held. On Saturday: held, opens Sunday 23:00 UTC.
6. An unmodelled class, and a clock that raises: not held.
7. `HOLD_CLASSES == entry_timing.SHUT_CLASSES` and the settle equals `entry_timing.OPEN_SETTLE_MINUTES`.
8. `GATE` off: nothing is held.

*At birth:*

9. A forex signal created on Saturday: no banner push, no `Notification` row, `dispatch_signal_alert` not called; one `SignalHold` row, state held, reason `market_shut`, `reopens_at` Sunday 22:00 UTC.
10. A forex signal created on Monday 10:00: the three steps in the engine's order, no `SignalHold` row (the assertions of `tests/test_signal_announce.py:59-84`).
11. Every creator goes through the hold: the rule engine, a live scanner pass, the TradingView task, a fast rule (not the admin button). Each still writes its `Signal` row.
12. The scanner's reuse branch on Sunday writes no second hold and announces nothing.
13. The switch OFF, the switch with no row, and a hold that cannot be written: announced as today, and the bytes of the banner payload, the bell row and the Telegram text equal main's.

*At the open:*

14. Still shut: waits. Settling: waits. A quote stamped before the open: waits.
15. A fresh quote inside the plan: announced once, with "fired Sunday 09:00 UTC, while its market was shut"; a second pass announces nothing.
16. A gap through the stop, past the target, and "chased": dropped with that reason, no announcement.
17. Born Saturday 00:05, read Sunday 22:20: dropped `aged_shut`.
18. Closed by the engine before the open: dropped `closed`.
19. No quote and no bar 30 minutes after the settle: released with "its levels were not re-checked". A bar opened since the open counts as a price.
20. Three held signals released at one open go out in score order.
21. A rule still at research: banner and bell at release, no Telegram.
22. `levels_reason` gives the rail's own reason for every mark of a grid (`_price_verdict`, `dashboard/signal_rail.py:531-570`), so the two cannot drift.
23. The switch turned OFF with a held row: the next pass still releases or drops it.

*Money direction (modelled on `tests/test_rail_lifecycle.py:1044-1202`):*

24. Every column of every `Signal`, `RuleControl`, `PromotionEvent`, `AssetBotTrade`, `Instrument` and `OpportunityFlag` row is identical before and after a hold, a release and a drop.
25. `ForexBot.decide` and `StockBot.decide` return the same decision with the switch on and off, for a held signal, a released one and a dropped one.
26. `evaluate_signal_outcome` gives the same outcome, `realized_r` and `expired_at` for a held signal as without the hold (the three cases of M4 run E5).
27. A guard: no file under `bot_program/`, `portfolio/`, `backtester/`, nor `signals/promotion_pipeline.py`, `signals/performance.py`, `signals/tasks.py`, names `SignalHold` or `market_hold`.
28. The lifecycle task still grades when the release raises.

### 2.5 Behaviour after F1b (the rail)

With the same switch ON, the rail's lifecycle stays as it is. A candidate it would show as a card is shown under a new section "MARKET SHUT" when `market_state` says its market cannot trade now. It becomes a card again by itself once the market has opened and settled. With the switch OFF the rail is byte-identical to main.

| File | Change |
|---|---|
| `dashboard/signal_rail.py` | `RailFacts` (`:158`) gains `market`, `market_words`, `opens_at`, `misses_open`; `_build` splits the cards into `cards` and `waiting`; `n` counts the cards only; a new `waiting_n`; `older_n` subtracts it; the title reads "N on the rail · W waiting for their market · ..."; the headband rows stay the cards. The price rules (`:640-644`) judge nothing while the market is shut or settling: today a quote re-stamped before the open can record a sticky "STOP" departure |
| `templates/_partials/signal_rail_items.html` | a section like LEFT THE RAIL (`:34`): head "MARKET SHUT" and its count; per row the symbol, the side, the rule, "opens Sunday 22:00 UTC", and "its 24 hours end Sunday 00:05 UTC, before the market opens" when that is so; the "▶ TICKET" button stays, with the title "The market is shut: a paper ticket is refused until it opens; a live ticket warns and is yours to send" |
| `templates/base.html` | the filter row "MARKET SHUT hidden / shown" (as LEFT THE RAIL's, `:1543`), and a cell "MARKET SHUT" in the headband dropdown (`:1188-1192`) |
| `static/css/sv-rail.css`, `static/js/sv-rail-filters.js`, `dashboard/rail_prefs.py` | the key `shut`, default hidden, cleaned by the whitelist like `gone` (`dashboard/rail_prefs.py:53-55`) |
| `dashboard/signal_surface.py` | `/signals/` rows and `signals show` say "born while its market was shut" and the opening hour |
| `tests/test_rail_market_shut.py` (new) | the cases below |

**Tests first, F1b:**

1. A forex signal on Saturday is not among the cards; it is in the MARKET SHUT list; the rail's count and the headband's exclude it; the title counts it as waiting.
2. Its row says "opens Sunday 22:00 UTC" and keeps `window.svTakeTrade(<id>)`; no "▶ TAKE TRADE" card exists for it.
3. Born Saturday 00:05: the row says its 24 hours end before the market opens.
4. Born Sunday 09:00, read Sunday 22:20 with a fresh quote inside the plan: a card again.
5. The same with a quote through the stop: LEFT THE RAIL, "STOP", as today.
6. A quote through the stop written while the market is shut records no departure.
7. Crypto and open markets: cards, as before.
8. The counts add up: on the rail + waiting + left and still active + left earlier + not evaluated = active in the engine.
9. No query is added per row (`tests/test_rail_every_signal.py:222`).
10. The rail still writes no engine row with a shut case added (`tests/test_rail_lifecycle.py:1063-1106`); `test_no_engine_module_reads_the_rail` still passes (`:1121-1147`).
11. With the switch OFF, and with `GATE` off, every existing rail test passes unchanged.

### 2.6 Switches, money direction, deploy notes

- **Switch:** `signal_market_hold`, new, OFF on arrival, category `pipeline`, no PIN, not exempt from "all on".
- **Money direction: none.** No `Signal` field is written or deleted. `decide()` reads `Signal(is_active=True, created_at >= now - 24h)` exactly as today (`bot_program/asset_engine/base.py:9825-9829`). Tests 24 to 28 and F1b test 10 pin it.
- **Model spend: none.**
- **Deploy, F1a:** one additive migration, applied by the deploy. The operator then turns the switch on (section 7). Signals already active at that moment are untouched: they have no hold row.
- **Deploy, F1b:** templates, CSS and script; static files are baked into the image at build.
- **To tell the operator** (M4 section 7): shares outside exchange hours are treated as shut, which is the bots' own rule, so a signal born after the bell is announced at the next open; indices are held only when the cash session and the futures week are both shut; holidays other than NYSE and NASDAQ are unknown to the clock; crypto is unchanged. **What he will see at each open:** the held signals go out together fifteen minutes after it, best score first, and the 20-an-hour Telegram guard holds the rest; the rail's MARKET SHUT section is hidden until he shows it with its filter. The note of 2026-11-11 already tells him the burst and the hidden section; the Telegram guard and the three limits above were cut from it for length and go in F1's own sheet.
- **Not in F1, his decision** (M4 section 9): starting a signal's 24 hours at the open (**more entries considered** on the first session after a shut), grading from the opening price, a per-bar key, the grading pass asking the clock. Option (a) of M4, not writing the row while shut, was run and rejected for the same reason: it is not money-neutral.

---

## 3. F2. The watchdog tells the truth for a live operator

Map: M3, sections 1 and 6.

### 3.1 Behaviour before

- `watch_evidence_chain` (`bot_program/tasks.py:1645-1712`, daily 06:40 UTC, switch `pipeline_campaign_watch`) alarms whenever `readiness()` (`bot_program/campaign_readiness.py:108-302`) holds one blocker.
- Two of its checks are about the campaign being paper: the five keys of `MUST_BE_OFF` being OFF (`:54-60`, `:164-173`) and one enabled config being in paper mode (`:184-187`). A live operator can never meet them.
- The message shows the first blocker only, under the title "▲ The evidence chain is broken" and the summary "The paper campaign is not complete, so the days passing now give the promotion ladder nothing to grade." (`notify_evidence_chain_cold`, `bot_program/notifications.py:2673-2734`; `:2695` is its first statement). For a live operator with every link ON, the title and the summary are false.
- One sentence serves all five keys: "a proposer is allowed to ACT on live capital" (`bot_program/campaign_readiness.py:169-172`).
- "A link that is off is a decision; a link with no row was never set up" is appended every time (`bot_program/notifications.py:2720-2721`).
- The cooldown is a 24-hour cache key on a 24-hour schedule (`bot_program/tasks.py:1642`, `:1682-1684`, `:1706-1707`), so a standing blocker re-alerts every 24 to 48 hours, for ever (M3 run D). The comment (`:1638-1641`) and the switch's description (`core/platform_control.py:555-557`) promise once.

### 3.2 Behaviour after

**Campaign kind**, worked out by `readiness()` from the enabled configs:

| Kind | When | The two paper-campaign checks |
|---|---|---|
| `live` | at least one enabled live-mode config that **scans** (symbols not empty, not the manual lane) | not blockers; listed under "LIVE BY DECISION", announced once |
| `paper` | no scanning live config is enabled, at least one paper config is | blockers, under their own title and with true words |
| `none` | neither | as today |

**A live hand lane is not a bot.** A TAKE TRADE lane is an enabled config with no symbols (`bot_program/manual_trade.py:107`, `:340-342`), in live mode once he arms it, and today's `live` list counts it (`bot_program/campaign_readiness.py:177-179`). A live hand lane alone does not change the kind, and the notice names it apart: "N bots are armed for real money; M hand lanes are in live mode". So a paper campaign run beside a live hand lane keeps the kind `paper`, and its "no longer paper-only" alarm.

**What the watchdog sends:**

| State | Message | Repeats |
|---|---|---|
| A chain fault (master switch, an unticked beat entry, a cold link, closed signals with no result, bars missing or stale, no symbol), any kind | the alarm. Title unchanged for a cold link: "▲ The evidence chain is broken at ...". Without a named link the title stays "▲ The evidence chain is broken" and the summary becomes "Evidence is not being produced, so the days passing now give the promotion ladder less to grade." | once when it appears; again at once when the set of faults changes; a reminder after 7 days while unchanged; cleared when the chain is whole. The set is compared by the findings' **keys**, never by their sentences (3.3): a stale bar that grows a day older is the same fault |
| Kind `paper`, a live-action switch ON | a new title: "▲ The paper campaign is no longer paper-only". Summary: "A switch that lets real money move is on while every enabled bot trades on paper." | same rule |
| Kind `live`, any live-action switch ON or no paper bot | one notice, never an alarm: "Live by decision: the paper-campaign checks stand down" | once per set of armed keys |
| Kind `live`, a rule born at research has reached the paper stage, and no paper bot is on | the alarm, scoped: "▲ No paper bot for the rules at the paper stage", naming the rules | same rule as a chain fault |
| Kind `live`, nothing else | silence | |

**Other changes to the message:**

- The count of the findings not shown: "And 2 more findings: run the full check".
- "A link that is off is a decision; a link with no row was never set up" only when a link is named.
- Each live-action switch in its own words, the key folded as code only:

| Key | Words |
|---|---|
| `actuator_mode_live` | the rule actuator's live mode (a superuser may apply a pause or a size cut to a rule; nothing applies by itself) |
| `meta_allocator_mode_live` | the meta-allocator's live mode (a superuser may apply rule weights, 0.1x to 3x, to future entries) |
| `share_allocator_mode_live` | the share allocator's live mode (a share plan may be applied with the PIN, which re-sizes the pools) |
| `capital_desk_mode_live` | the capital desk's live mode (the bots obey the desk's plan: displaced entries are skipped and sizes cut) |
| `share_allocator_auto_derisk` | the share allocator's automatic de-risk (a shock plan that only lowers shares applies itself) |

The notice for a live operator, then nothing (M3 section 6.2, run "proto", with the hand lanes named apart as decided above; the counts are a scratch database's):

```
ℹ️ Live by decision: the paper-campaign checks stand down
2 bots are armed for real money; 1 hand lane is in live mode. So this is not a paper campaign: that is your decision, not a fault.

Armed: the rule actuator's live mode (a superuser may apply a pause or a size cut to a rule; nothing applies by itself)
No paper bot is on: nothing trades on the simulator except entries a live bot's rule sends there
Still watched every day: the master switch, the indicators, the signals, the bots, the promotion ladder, the bar feeds and the graded outcomes
```

**Edge cases the build must settle:**

- A live-mode config on a broker row that answers the demo world moves no real money: the notice says "in live mode on the demo world", never "armed for real money" (`bot_program/capital_truth.py:426` reads a row's world).
- Paper configs and a scanning live config both enabled: the kind is `live`. Paper bots and a live hand lane only: the kind is `paper`. A live hand lane and nothing else: the kind is `none`, as today.
- **What a "paper bot" is.** Today's check counts any enabled config in paper mode, a paper manual lane with no symbols included (`bot_program/campaign_readiness.py:176-187`; the lane is `MANUAL_CONFIG_NAME`, `bot_program/manual_trade.py:107`). For the scoped alarm a paper bot is an enabled paper-mode config that scans: symbols not empty, not the manual lane. Leave the count of the `paper` kind as it is, so the existing tests do not move.
- The quiet result keeps `status: "cooldown"`: `tests/test_evidence_chain_watch.py:200-210` pins the word.
- The old key `campaign_watch:alerted` lives in Redis across deploys: delete it on the first run.
- The cache emptied: at most one alarm is repeated. The notice is protected by the bell-row memory.
- Nobody to tell, quiet hours, a muted bot feed: unchanged (`bot_program/tasks.py:1686-1695`; `bot_program/notifications.py:403-409`).

### 3.3 Files

| File | Change |
|---|---|
| `bot_program/campaign_readiness.py` | `readiness()` also returns `campaign` ("live", "paper", "none"), `chain_faults`, `campaign_gaps`, `armed` (the live-action keys that are ON) and `paper_stage_stuck`. `blockers` keeps today's content when the kind is not `live`; when it is `live` it holds the chain faults and the stuck-rule finding only. `notes`, `cold_links`, `sections` and `window_days` are unchanged. Add `LIVE_ACTION_WORDS` and use it in place of the single sentence at `:169-172`; **the blocker keeps its frame**, `f"{key} is ON — {words}, which is not a paper campaign"` (`tests/test_paper_readiness.py:237-238` asserts "share_allocator_mode_live is ON" and "is not a paper campaign"), and `readiness()` keeps the section title "MONEY MUST NOT MOVE" (`tests/test_paper_readiness.py:222` slices the output on "3. MONEY"). **Each finding carries a key,** built where the finding is appended, and the task's fingerprint reads keys only: `("master",)`, `("beat", task)`, `("link", key, state)`, `("no_result",)`, `("no_bars", sorted symbols)`, `(kind, venue, sorted symbols)` for the three bar findings, `("no_symbol",)`, `("stuck", sorted rules)`, and for the `paper` kind `("armed", key)` and `("no_paper",)`. No age, count or day goes into a key. The scanning rule of 3.2 decides the kind (`live` counts configs that scan; the hand lanes are counted apart). Rewrite the comment at `:49-53`. `MUST_BE_OFF` keeps its name |
| `signals/rule_birth.py` | one reader: the born names (and forks) whose row is at the paper stage. It makes **one** read of `_born_rows()` (`:136-150`) and returns the names whose stage is neither research nor a live stage; a failed read returns nothing and is logged. Not the difference `voteless(live=True) - voteless(live=False)` the prototype used: `voteless` fails closed by returning every born name (`:152-168`), so one failed call of the two would name rules that sit at a live stage |
| `bot_program/tasks.py` | `watch_evidence_chain`: alarm on `blockers` as redefined. Replace the 24-hour key with a memory of the fault set: a fingerprint of the findings' **keys** (the row above), never of their sentences, and the time it was said, in the cache with no expiry. Three findings carry a moving number in their text (the count of closed signals with no result, `bot_program/campaign_readiness.py:217-222`; the age of the stale bar, `:271-275`; the days missing, `:284-287`): the prototype hashed the sentences (line 126 of `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/_m3_work/proto_watch.py`), and on the real `readiness()` one unchanged stale symbol gave three fingerprints in three daily runs (`/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/_verify_work/out/fp_demo.out`), an alarm every day. If the set of stale symbols turns out to flap from day to day on his fleet, drop the symbols from the three bar keys and keep `(kind, venue)`; decide it on test 6b. Same fingerprint and under `CHAIN_REMIND_AFTER` (7 days): quiet. A different fingerprint: speak at once. No finding: clear. Send the notice when no bell row carries its fingerprint yet (the bell table is the memory, as `notify_staff` does, `bot_program/notifications.py:2528-2534`). Rewrite the comment at `:1638-1641`. The result dict gains `campaign` and `noticed` |
| `bot_program/notifications.py` | `notify_evidence_chain_cold` (`:2673-2734`): the three title and summary forms, the "and N more" line, the conditional closing line. New `notify_live_by_decision(user, *, armed, live_configs, hand_lanes, paper_configs, fingerprint)`: kind `system_health`, a neutral mark from `_PLATFORM_MARKS` (`:564`) on the bell title (never ▲), a new `NOTIFY_MARKS` entry (`:64`) for Telegram, `row_data` carrying the fingerprint, the same "Open ops page" button. Its mark must not join the "warn" set of `dashboard/activity_feed.py:581-596` |
| `bot_program/management/commands/paper_readiness.py` | three groups in place of one "BLOCKERS" list when the kind is `live`: "CHAIN FAULTS — evidence is not being produced", "LIVE BY DECISION — not a paper campaign, and no fault", "WORTH READING". For the `live` kind only, the command prints section 3 under the heading "LIVE-ACTION SWITCHES — a paper campaign wants all five off" (`readiness()` still names the section "MONEY MUST NOT MOVE"), and the verdict line names the kind. With the kind `paper` or `none` the output is as today, the heading "3. MONEY MUST NOT MOVE" included: `tests/test_paper_readiness.py:222` slices on "3. MONEY" |
| `core/platform_control.py:555-557` | the description, 296 characters: "Daily read-only check that the evidence chain (bars -> indicators -> signals -> fills -> outcomes -> ladder) is complete. Speaks once when a link is off, missing or starved, again only when that changes, weekly while it lasts. Live trading by decision is said once, never alarmed. Writes nothing." |
| `core/ops_commands.py:503-515` | the purpose line of `paper_readiness`: it also names a live operation as one |

### 3.4 Tests first

**New, in `tests/test_evidence_chain_watch.py`:**

1. A live bot enabled and `actuator_mode_live` ON: no alarm; one "live by decision" notice.
2. The same task run again: no second notice.
3. The armed set changes (a second key goes ON): one new notice.
4. A live bot enabled, `actuator_mode_live` ON and `pipeline_promotion` OFF: the alarm, titled "at the promotion pipeline", whose first problem is the pipeline and never the actuator.
5. Only paper bots enabled and `actuator_mode_live` ON: the alarm, titled "The paper campaign is no longer paper-only". 5b. The same with one live hand lane beside the paper bots: the same alarm (the lane does not make the campaign live), and no "live by decision" notice.
6. A standing fault under a fake cache clock, seven daily runs: one alarm. The eighth run: one reminder. Today's suite cannot see this: its test runs the task twice in the same second (`:200-210`). 6b. Written with findings whose text moves, or it proves nothing (a cold link's text never moves): a stale-bar fault whose age grows at each run, and a no-result fault whose count grows; seven daily runs, one alarm. A second symbol joining the first: an alarm that day.
7. A second fault appearing on day 3: an alarm on day 3, not after a cooldown.
8. A born rule at the paper stage, a live bot, no scanning paper bot: the scoped alarm naming the rule. With an enabled scanning paper bot of a class the rule fires on (the rule's own `eligible`, `signals/rules/bearish_rules.py:123-124`): silence. With a scanning paper bot of another class only (a paper stock bot beside a forex-only rule, which can still earn no paper fill): the alarm. With only a paper manual lane enabled: the alarm. 8b. The reader of the stuck rules with `_born_rows()` raising: it returns nothing, logs, and names no rule.
9. A born rule still at research, no paper bot: silence.
10. The cache emptied between two runs: the notice is not sent twice.

**New, in `tests/test_paper_readiness.py`:**

11. A live bot and a live-action switch ON: the line appears under "LIVE BY DECISION" and not under a blockers heading; the verdict names a live operation.
12. Every key of `MUST_BE_OFF` has an entry in `LIVE_ACTION_WORDS`, and no entry contains an underscore.
12b. Every blocker `readiness()` can return carries a key, and no key holds a number that moves from one run to the next (an age, a count, a day).

**New, in `tests/test_telegram_polish.py` and `tests/test_telegram_house_style.py`:**

13. The exact text of the notice and of the "no longer paper-only" alarm, with the existing `jargon` check.
14. The new notifier in the house-style list (`tests/test_telegram_house_style.py:663-671`): its mark and at least one line.

**Existing tests that must pass unchanged:** `tests/test_evidence_chain_watch.py` (its fixtures set the five keys OFF and enable one paper config, `:54-67`, so the kind is `paper`); `tests/test_paper_readiness.py:234-262`; `tests/test_telegram_polish.py:221-282` (the cold-link message is unchanged).

### 3.5 Switches, money direction, deploy notes

- **Switch:** none new. `pipeline_campaign_watch` exists, OFF on arrival, no PIN.
- **Migration:** none. **Model:** none.
- **Money direction: none.** The task reads and notifies. None of the five keys is read by the ladder (M3 section 1.7).
- **Model spend: none.**
- **Deploy:** on 2026-11-11 the operator was advised to turn `pipeline_campaign_watch` OFF until this ships. The note told him the cost (until then nothing tells him a link went cold; the stopgap is `paper_readiness` by hand) and that we would tell him when to turn it back on: the sheet for this fix does (section 7). The first run after that, at 06:40 UTC, sends one notice if a live-action key is ON or no paper bot is on, then stays quiet. He was also advised to turn `actuator_mode_live` OFF (R1); if he did, that notice lists no armed key and says only that no paper bot is on.
- **Until this ships the alarm shows the first blocker only,** and the order of `readiness()` puts the master switch, the beat boxes and the four links before the five keys, and the no-result and bar findings after them (`bot_program/campaign_readiness.py:122-187`, `:215-299`). So with a key ON a stale bar feed is hidden behind it today, whether the watchdog is on or off; the "and N more findings" line ends that.

---

## 4. F3. One reader for "why no trade", and Ask Sauron's fact block

Maps: M5 section 4, M1 sections 5 and 7.

### 4.1 Behaviour before

- Ask Sauron's snapshot (`brain/research_agent.py:47-209`) holds no rule stage, no bot config, no skip count, no heartbeat, no switch, no reading of the posture level in force, no eToro cash state. (It does carry the strategist's advice word, `latest_briefing.posture`, and prose that may name the measured posture: `brain/research_agent.py:143-149`, `brain/strategist.py:228-236`. Neither is the level the bots obey.) Its prompt calls seven audit kinds "the source of truth" for "why did X happen?" (`:278-282`).
- A bot's refusals are never audit rows. `gate_reject` has one writer, the opt-in orchestrator, off by default (`bot_program/orchestrator.py:383`, `:489-496`). Every other refusal goes to `AssetBotConfig.extras` (`skips`, `skip_counts`, `last_tick_note`).
- The signal popup shows "stage ... · ..." and "graded ..." (`templates/_partials/signal_rail_items.html:195-196`), and its "▸ ASK SAURON" button passes the subject only (`:240-244`). So does the button on `/signals/` (`templates/dashboard/signals_list.html:228-230`). The panel already accepts facts beside a subject (`templates/base.html:7269-7276`, `:7968`).
- `why_no_trade` (`bot_program/management/commands/why_no_trade.py`, 237 lines) cannot see a config-level refusal: daily loss, exposure, open risk, slots, a stale account reading, a breaker write only `extras.last_tick_note` (`bot_program/asset_engine/base.py:1109-1125`, `:4645-4858`; `bot_program/asset_engine/safety.py:198-200`). The command prints none of it: a config with older skips shows its old counts and its old "last" lines, which then read as the present, and only a config that never recorded a skip prints "nothing recorded — the tick may never have reached this config at all" (`:186-188`; M1 runs A and C2; M1 section 5.3, item 1). The daily loss reaches section 4, as `gate_blocked`, in the elite band only (`bot_program/asset_engine/base.py:5398-5413`), and in that band the heartbeat note reads `ok`. Its skip counts are cumulative and undated (`:189-194`), and nothing resets them (`bot_program/asset_engine/skips.py:161-183`). It judges the bot pass from a component row five tasks write (`:91-101`). It omits `broker_account_sync` and nine other switches. It lists a starved symbol once per bot (`:198-209`) and runs two count queries a symbol a bot (`:200-204`).

### 4.2 Behaviour after, in four commits

**F3a. The buttons pass what is on screen (templates only).** Add `data-ask-facts` to the two signal buttons: on the popup, "stage {{ s.rail.stage_label }} · {{ s.rail.vote_words }} · graded {{ s.rail.record_words }}"; on `/signals/`, the same from the row's badge. No agent change, no switch. One caution: the badge is not the entry path's reading for a born rule that has no row (`dashboard/signal_surface.py:129-135` says "PAPER ONLY" with `may_trade` True, so the popup would say a default bot counts its vote, `dashboard/signal_rail.py:708`). A born rule's card normally has its row, written with its first stored signal (`signals/tasks.py:134-139`); F3d reads `stage_policy` and never the badge for that reason.

**F3b. One reader (pure refactor).** New `bot_program/no_trade.py`:

- `collect(per)`: every read `why_no_trade` makes today, in its order, returned as data;
- `print_report(facts, write)`: the command's text from that data.

The command becomes `print_report(collect(per), self.stdout.write)`. Its output does not change by a byte. The bar counts become one grouped query that returns the same numbers.

**F3c. The command says what it could not see.** `extra(facts)` in the same module, read-only:

- per enabled config: the heartbeat (`last_tick_at`, `last_tick_status`, `last_tick_note`), and its last skips with their time, newest first;
- the other switches that stop or reshape entries: `broker_account_sync`, `pipeline_indicators`, `pipeline_promotion`, `crisis_mode`, `aragorn`, `pipeline_capital_desk`, `capital_desk_mode_live`, `trade_debate`, `morgul_brake`, `etoro_leverage_live`;
- the posture in force (`market_stress.current()`: level, score, fresh or stale) beside the state of `crisis_mode`. A crisis level holds on the way down until the score is under 45 with the index rising (`bot_program/market_stress.py:309-323`), so a score in the stressed band can sit under a crisis level, and in a crisis a real risk-on long is sent to paper (`bot_program/posture.py:56-77`);
- the count of rules at each stage, and of those paused in force (`is_effectively_active()` False) apart from a served pause whose status still reads "paused" (R2);
- per enabled config, the count by code of the refusals stamped in the last 48 hours, and whether it lists a symbol named with `--symbol` (the two facts the read of 2026-11-11 had to fetch with a one-line script, section 7);
- entries and open rows per money world, 24 hours and 7 days, counted from the rows (4.3);
- the eToro cells' age and state in words, never an amount.

What the command prints from it (deliberate output changes; re-record the golden file):

- In section 2: "freshest config heartbeat: N min ago". A blocker when no enabled config was ticked in the last 15 minutes (the pass runs every 300 s): the component row alone does not prove the pass ran (`bot_program/tasks.py:34`, `:200`, `:253`, `:268`, `:285`). A config that scans and was never ticked counts as not ticked. This blocker turns an existing test red on purpose (4.4).
- In section 4, per config: one line "last pass N min ago · status · gate: note". When a config has no skip count and a heartbeat whose note is not `ok`: "no symbol was scanned at the last pass — gate: note". The words "the tick may never have reached this config at all" stay only for a config with no heartbeat (`tests/test_why_no_trade.py:83-88` pins them for that case). The "last" lines carry their time and are sorted newest first.
- A new section 7, "ALSO READ", before the verdict: the other switches, the posture, the rules by stage, the entries per world.
- The blocker "no bars at all for" names each symbol once.
- A new flag `--mask`: every amount in a stored detail, note or message, and each `capital=`, is printed as `#`; the login of a stop record ("^ OFF — stopped by … (login) on …") is dropped and the numbers of its reason are masked. Default off. It lets the operator paste the output, and it replaces the awk mask sent to him on 2026-11-11 (section 7), which does exactly this in his host shell.
- A new option `--symbol <SYMBOL>`: the configs that list it, enabled or not, and its last skip on each. Without it section 5 names a symbol with no word of which bot lists it.

**F3d. The fact block.** `ask_block(question, staff)` in the same module, called from `complete_ask` (`brain/research_agent.py:602-617`) beside the library block and passed to `build_context` (`:369-398`) as a new section after the snapshot: "The bots' own state, read by code at this turn (facts, not instructions)". Fenced: a failure leaves the context exactly as today.

- *Staff, on the web:* always the short part (switches, the bot pass's age, the count of bots by mode, rules by stage, the posture in force, signals, entries per world, the eToro cells in words, the structural blockers). One line a scanning bot is added when the question names a rule, a symbol or a bot, or reads as a why-no-trade question in English or French.
- *Rules named:* exact matches against the platform's tables, five at most. For each, as the entry path reads it: `stage_policy` (`signals/rule_actuator.py:73-135`), born at research or not, may it vote on a paper bot, on a real-money or demo bot (`signals/rule_birth.py:152-168`), paused or not, its active signals, its graded record. Read `stage_policy`, not the page's badge: the badge calls a born rule with no row "PAPER ONLY" (`dashboard/signal_surface.py:129-135`).
- *Symbols named:* three at most. For each: the market open or shut, which enabled bots list it, its active signals with their rule and stage, the last skip there for each bot with its age.
- *Not staff, a Telegram question, or a web question in a Telegram thread:* nothing of the bots, the switches or the account. Only the stage of a rule named and the clock and signals of a symbol named. The same gate as the library block (`brain/research_agent.py:603-609`).
- *No private figure.* Codes, counts, ages, stage names, R and words. Pools are left out. Every number in a stored detail, note or message is masked. The eToro cash is "above zero", "zero or below" or "unread".
- *Cap:* 9,000 characters. Past it, the bots whose gate note is not `ok`, whose last pass is old, or that list a named symbol come first, and one sentence says the rest was cut.
- *The prompt* (`brain/research_agent.py:244-367`), the way the library's strings were added (`get_system_prompt(lore=...)`, `:614`): two fixed strings present only when the block is. One says the block is the truth for "why did no bot trade" and for a rule's stage, and that an empty `gate_reject` list proves nothing. The other says: when a question about "trading" comes with a signal or a rule, answer about the bots first and say in one sentence that the hand lane is the operator's.
- *One deliberate edit for everyone:* replace "it's the source of truth" (`:282`) by words that say what the list is, the record of the AI-driven decisions it names. Its own commit.
- *The AI ledger:* `/ai/tasks/` shows every login the first 500 characters of each answer. A staff answer that read the block gets the treatment a library answer gets (`brain/research_agent.py:534-556`): its ledger copy is a pointer to the thread.
- *The panel's menu* (`templates/base.html:7187-7190`): unchanged. Its two bot questions become answerable.

Measured on the prototype (M5 section 4.5): the block for the operator's exact question is 5,914 characters, about 2,000 tokens, about $0.008 of input on the deep tier; 130 to 151 queries, every one a SELECT; the command's output from the shared reader was byte-identical to the real command's (256 and 280 lines).

### 4.3 Files

| File | Change |
|---|---|
| `templates/_partials/signal_rail_items.html:240-244`, `templates/dashboard/signals_list.html:228-230` | F3a: `data-ask-facts` |
| `bot_program/no_trade.py` (new) | F3b: `collect`, `print_report`. F3c: `extra`, `mask`. F3d: `rule_facts`, `symbol_facts`, `named`, `ask_block` |
| `bot_program/management/commands/why_no_trade.py` | F3b: the thin wrapper. F3c: the new lines, section 7, `--mask` |
| `brain/research_agent.py` | F3d: `build_context` takes `bot_block`; `get_system_prompt(bots=...)`; `complete_ask` builds the block when the switch is on; the ledger pointer; the one sentence at `:282` |
| `core/platform_control.py` | F3d: the row `ask_sauron_bot_facts`, category `agent`, name "Ask Sauron: bot facts". Description: what the block holds, that it carries no amount, that it adds about one cent of input a question |
| `tests/test_why_no_trade.py` | F3b: the golden output. F3c: the new cases |
| `tests/test_no_trade_facts.py`, `tests/test_ask_sauron_bot_facts.py` (new) | F3d |
| a template test (new, or beside the rail popup's tests) | F3a |

**Two guards the refactor must respect:**

- `tests/test_why_no_trade.py:236-257` patches `core.platform_control.is_component_enabled` as a module attribute. `collect()` must import it inside the function, as the command does today (`bot_program/management/commands/why_no_trade.py:34`), or the patch misses and the test fails.
- `bot_program/` is a decision tree for `tests/test_venue_pnl.py:451`, `:469-471`: `bot_program/no_trade.py` must not name `venue_pnl`, `venue_pnls`, `venue_pnls_for_rows`, `shown_open_rows`, `shown_unrealized`, `ShownRow`, `etoro_carried` or `shown_book`. "Entries and open rows per money world" are counted from the rows.

### 4.4 Tests first

**F3a:**

1. The rendered popup button of a research-stage signal carries the stage label and the vote words.
2. A signal with no rule carries no `data-ask-facts`.

**F3b:**

3. Golden output: record `why_no_trade` on a seeded fleet before the refactor, for `--symbols 4` and `--symbols 200`; it must not change by a byte. The 20 tests of `tests/test_why_no_trade.py` stay green.
4. `collect` issues only SELECT statements and changes no row.

**F3c:**

One existing test changes on purpose, and the spec said nowhere that it does: `tests/test_why_no_trade.py:212-228` (`_healthy_platform`) builds one enabled config with no heartbeat beside a fresh component row, and `test_a_healthy_platform_has_no_structural_blocker` (`:230-234`) asserts "No structural blocker". That is exactly the state of test 8 below. Give the fixture's config a fresh heartbeat (`write_heartbeat`), or that test fails. The other 19 stay as they are.

5. A config whose only refusal is config-level (its slots at zero, as in M1 run A): the command prints the gate's note, and not "never have reached". 5b. A config with an old skip count and a heartbeat whose note is not `ok` (the case of his bots): the "last pass · status · gate" line carries the note, and the old "last" lines carry their old time.
6. A config with no heartbeat keeps today's words.
7. The "last" lines carry a time and come newest first.
8. No enabled config ticked in 15 minutes: a blocker, even with a fresh component row. A scanning config never ticked counts as not ticked.
9. `--mask`: seed pools, cash and amounts inside details with recognisable digits, and a stop record with a login and a reason that carries a number; none is printed. Without the flag the pools print as today.
10. A symbol with no bars listed by four bots is named once.
11. Section 7 names `broker_account_sync`, the posture level and `crisis_mode`, and counts a pause in force apart from a served one.
11b. `--symbol X`: the configs that list X, enabled or not, each with its last skip there and its time; a symbol no config lists says so in words.
11c. The 48-hour count by code: two skips inside the window and two older give two; a skip with no time stamp is left out, never counted as fresh.

**F3d (M5 section 4.6):**

12. `ask_block` issues only SELECT statements and changes no row.
13. Staff block: the switches, the pass's age and, for a why-no-trade question, one line a scanning bot.
14. No money: seed pools, cash, equity and amounts inside details with recognisable digits; none is in the block.
15. A born rule named with no stage record: "stage research (no stage record yet)", may vote no and no. A born rule at paper: a paper bot yes, a real-money bot no. An ordinary rule with no row: paper, said as "no promotion record". At `live_small`: real yes at 0.25x. Paused: said.
16. A symbol named that no enabled bot lists: "listed by enabled bots: NONE".
17. Not staff, the Telegram channel, a Telegram thread opened on the web: no bot, no switch, no account word; only the reduced lines.
18. The switch OFF or unseeded: the context and the prompt are byte-identical to main's (after the one deliberate sentence); with the switch ON the context differs by exactly the inserted section and the prompt by the two strings.
19. `collect` raises: the question is still answered, on today's context.
20. The ledger copy of a staff answer that read the block is the pointer sentence.
21. Sixty bots: the block is under the cap and ends with the cut sentence; the bots with a closed gate come first.
22. The matcher returns only exact names from the tables, at most five rules and three symbols, and puts none of the question's own text into the block.
23. A bound on the block's queries.
24. A crisis level held under a score in the stressed band: the block says the level in force, not the band.

### 4.5 Switches, money direction, deploy notes

- **Switch:** `ask_sauron_bot_facts`, new, OFF on arrival, category `agent`, no PIN. F3a, F3b and F3c have no switch: the first passes facts already on screen, the other two are a command.
- **Migration:** none.
- **Money direction: none.** Reads only; tests 4 and 12 pin SELECT-only.
- **Model spend:** F3a adds a few tokens a question. F3d adds the block's input: about $0.002 for a market question, about $0.008 for a why-no-trade question, $0.012 at the cap, on the deep tier. The question's existing budget gate asks $0.30 of room (`brain/research_agent.py:591`). It arrives OFF; the operator's "turn on" is his word.
- **Deploy:** nothing by hand but the switch (section 7). After F3c the operator's read becomes `why_no_trade --symbols 200 --mask` (with `--symbol <SYMBOL>` when he asks about one symbol), in place of read 1 and of the posture and bot lines of read 2 (section 7). The stage of each rule by name stays its own read: read 2's rule lines, or `rule_scope show <rule>` for one rule (M1 section 9, command 5).
- **Not in F3** (M1 section 10): a skip code of its own for "rule not armed" (D5) and for the cash check (D8), a skip for a desk candidate refused at execution (D9), `bot_health` (D10), `desk explain` (D11). They change what the engine records and are separate work.

---

## 5. F4. Feedback on trades: the "Feedback" card

Map: M5 sections 1 to 3. This is the proposal M5 ranks first. It calls no model.

### 5.1 Behaviour before

- Feedback on one trade sits in five places: the position page (`/forensics/<number>/`: the Council's card, `templates/dashboard/forensics_detail.html:209-254`, and the "Should I close?" button, `:212-217`), the Horde seat (light, reviewer, thesis, care, Orc, debate), `/orcs/<number>/`, `/council/`, and Telegram.
- The Council sits on a hand trade only on his click; nothing is automatic. Its verdict and an Orc's plans and proposals reach no phone and no bell (`ai_agents/tasks.py:1623-1641`). No debrief is written at a close.
- What does reach him today on a real-money position, so no sheet may say "nothing from the Orcs reaches your phone": one line when an Orc adopts it (`notify_adopted`, `bot_program/orcs/birth.py:380-396`, kind `orc_adopted`, an operator-side kind, `bot_program/notifications.py:340-345`: the bell row always, then Telegram when that is his channel, `:411-461`); the position reviewer's actionable call and the "thesis is dead" notice while `agent_position_review` is on (`bot_program/notifications.py:2266-2284`, `:2332`); and the answers to `/orc N` and `/orcs` on Telegram when he asks (`bot_program/orcs/surfaces.py:1-23`). The note of 2026-11-11 says so.

### 5.2 Behaviour after

With `trade_feedback` ON, the position page shows a "Feedback" card under the summary:

- *Before:* the signal the ticket came from and its rule's stage; the Council's sitting (the Emperor's words, the count of voices, a link to the card below) or one fixed sentence saying why there is none; the debate line for a bot's row.
- *While open:* the Horde's light with its reasons; the reviewer's last verdict and age; the thesis check; the care's stops; the Orc's plan line, latest note, proposals in shadow and next wake.
- *After the close:* the grade in R that exists today. The debrief of 5.6 fills this block later.
- Under each line, the link to the page that holds the whole record.
- For a paper or demo row, the card says the Council never argues it.

The card writes no words of its own about the voices. It shows the existing readers' strings.

### 5.3 Files

| File | Change |
|---|---|
| `dashboard/trade_feedback.py` (new) | `feedback_for(trade, user) -> dict`. It calls `council.card_payload` (`ai_agents/agents/council.py:2652`), `horde.seat_detail` for an open row (`dashboard/horde.py:2724`), `position_review.latest_verdicts` (`brain/position_review.py:1371`), and the Orc's notes for a closed idea. Each section is fenced: one that cannot be read says "not read" |
| `dashboard/views_forensics.py` | one context key, built only while the switch is on, fenced like `_council_or_none` (`:325-336`) |
| `templates/dashboard/_feedback_card.html` (new) | included in `templates/dashboard/forensics_detail.html` after line 209 |
| `core/platform_control.py` | the row `trade_feedback`, category `agent`, name "Trade Feedback Card" |
| `tests/test_trade_feedback_card.py` (new) | the cases below |

### 5.4 Tests first

1. Switch OFF: the page's bytes equal main's for a seeded trade.
2. A hand trade with no sitting: the fixed sentence, no error.
3. A linked sitting: the Emperor's words and each voice's line are `card_payload`'s own strings.
4. An open trade: the light's word and reasons equal `horde.light`'s (`dashboard/horde.py:934`) for the same row.
5. No money: seed a size, a risk amount and a result with recognisable digits; none appears anywhere in the card's data.
6. Another user's trade: today's 404; the builder is never called.
7. A reader that raises: the page renders, that section says "not read".
8. A bound on the queries the card adds.
9. A paper or demo row: the card says the Council never argues it.

### 5.5 Switches, money direction, deploy notes

- **Switch:** `trade_feedback`, new, OFF on arrival, category `agent`, no PIN.
- **Migration:** none.
- **Money direction: none.** The card reads. No order path, size, stop, gate or limit reads it.
- **Model spend: none.** It does not need his word.
- **Deploy:** the switch only (section 7).

### 5.6 What follows F4, and what needs his word

| # | Addition (M5 name) | Switch | Model spend | Needs his word |
|---|---|---|---|---|
| F4b | The debrief at the close, from stored data (M5 F2): new `bot_program/debrief.py`, read at page time, nothing stored; the "After" block of the card | `trade_feedback` (same) | none | no |
| F4c | Phone and bell lines for the Council's verdict and an Orc's proposal on a real position, and three debrief lines in the close message (M5 F3) | `trade_feedback_tell`, OFF on arrival | none | no (it sends messages: his switch decides) |
| F4d | One cheap call for a lesson at a real-money close (M5 F2b); one new table | `trade_debrief_ai`, OFF on arrival, exempt from "all on" | about $0.001 a close on the fast tier, $0.014 on the balanced one; cap 12 a day | **yes** |
| F4e | An automatic Council sitting after each LIVE hand trade (M5 F4) | `council_ticket_auto`, OFF on arrival, exempt from "all on" | one sitting a trade: the platform's pre-check estimates $0.54 to $0.85 at the default model; it shares his 12 ticket sittings a day and the day's AI budget (`ai_agents/agents/council.py:44-46`, `:102`) | **yes: asked in the French note of 2026-11-11, choice 1. With no answer the note's default is no** |

Tests-first outlines for each are in M5 section 3. Do not start F4d or F4e before his answer. A sitting on an open position is not proposed: it needs a new truth for the grader.

---

## 6. Order, independence and shared files

| Step | Branch (suggested) | Depends on | Files other open work also touches (checked 2026-11-11 against `15dd487`) |
|---|---|---|---|
| F1a | `claude/markethold` | nothing | none found |
| F1b | `claude/railshut` | F1a merged (it reads `market_hold`) | `templates/base.html`: `claude/uis1a` changes 78 lines of it, `claude/opscenter0` 2 lines. Rebase F1b on them, not the reverse |
| F2 | `claude/watchtruth` | nothing | `bot_program/notifications.py` (`usedfix`, +68 lines at `:2020`) and `core/ops_commands.py` (`claude/feedf1`, +18 lines at `:403`). Other hunks than F2's, so the merges are clean, but F2's line references move once either lands |
| F3 | `claude/notradefacts` | nothing | `templates/_partials/signal_rail_items.html` is also edited by F1b (another block); the second to land rebases |
| F4 | `claude/tradefeedback` | nothing | none found |

- `core/platform_control.py` gets one new row from F1a, F3 and F4 and one edited description from F2: four small conflicts at most, each a row.
- `core/wall_facts.py:52`: every fix edits the same number. Recount after each rebase.
- The UI branches are still moving (the magic layer on `claude/uis1a`). Check again before F1b: `git diff --stat 15dd487...claude/uis1a -- templates/base.html templates/_partials/signal_rail_items.html static/css/sv-rail.css static/js/sv-rail-filters.js dashboard/signal_rail.py dashboard/rail_prefs.py`.
- Each fix gets the usual three review lenses, the full suite, CI, and a French sheet verified before it is sent.

---

## 7. Operator steps, for the French sheets

All in his form. None of these switches takes the PIN. Never "all on".

| After | Step | Writes? |
|---|---|---|
| F1a | `cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py component on signal_market_hold` | one switch |
| F2 | `cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py component on pipeline_campaign_watch` (only if he turned it off on 2026-11-11) | one switch |
| F3c | `cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py why_no_trade --symbols 200 --mask` | no |
| F3d | `cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py component on ask_sauron_bot_facts` | one switch |
| F4 | `cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py component on trade_feedback` | one switch |

**The two reads given to him on 2026-11-11.** They are the note's final text, extracted from it and run as written on a scratch copy of `15dd487` (synthetic rows, no key, proxies on a dead port) by `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/_apply_work/scripts/run_note_cmds.py`; the database file's hash is the same before and after each. Outputs: `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/_apply_work/out/note_cmd1.out` and `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/notrade/_apply_work/out/note_cmd2.out`.

```
cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py why_no_trade --symbols 200 | awk '/^ +last /{i=index($0,":"); r=substr($0,i); gsub(/[0-9][0-9.,]*/,"#",r); $0=substr($0,1,i-1) r} /\^ OFF/{sub(/ \([^()]*\) on /," on "); i=index($0," UTC"); if(i){r=substr($0,i+4); gsub(/[0-9][0-9.,]*/,"#",r); $0=substr($0,1,i+3) r}} {sub(/capital=[0-9.,]+/,"capital=#")} 1'
cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py shell -c 'import re; from collections import Counter as K; from datetime import timedelta as D; from django.utils import timezone as Z; from signals.models import RuleControl as R; from signals.rule_birth import BORN_AT_RESEARCH as B; from bot_program.models import AssetBotConfig as C; from bot_program import market_stress as M, posture as P; c = M.current(); print("posture:", c["level"], "| score:", c["score"], "| crisis_mode:", "ON" if P.crisis_mode_on() else "OFF"); m = lambda s: re.sub(r"\d[\d,.]*", "#", str(s or "")); t = (Z.now() - D(hours=48)).isoformat(); [print("bot", b.id, b.asset_class, b.mode, "| <SYMBOL>:", "<SYMBOL>" in (b.symbols or []), "| last pass", str((b.extras or {}).get("last_tick_at"))[:16], (b.extras or {}).get("last_tick_status"), "| gate:", m((b.extras or {}).get("last_tick_note")), "| refusals 48h:", dict(K(d.get("code") for d in ((b.extras or {}).get("skips") or {}).values() if isinstance(d, dict) and str(d.get("at") or "") > t))) for b in C.objects.filter(enabled=True).order_by("id")]; rs = list(R.objects.order_by("promotion_stage", "rule_name")); [print(r.promotion_stage.ljust(11), (r.status if r.is_effectively_active() else "PAUSED").ljust(8), r.rule_name) for r in rs]; print("born rules with no row yet (research):", sorted(B - {r.rule_name for r in rs}))'
```

**Read 1** is `why_no_trade --symbols 200` through a mask that runs in his host shell. Each `capital=` becomes `#`. On a "last" line, and on section 2's "last message" line, every number after the first colon becomes `#`. On a "^ OFF" line the login in brackets is dropped and every number after the date becomes `#`. Ids, counts, the dates of stops and the bar counts are left. Tested with mawk 1.3.4 only (no other awk on the build machine); it uses POSIX constructs only.

**Read 2** is what `why_no_trade` cannot show, in one line. It prints:

- the posture: the level in force, the score, `crisis_mode`;
- one line per enabled config: id, class, mode; whether it lists <SYMBOL>; the time (UTC) and status of its last pass; the gate's note with every number masked; the count by code of the refusals stamped in the last 48 hours (each symbol's last skip carries its time, `bot_program/asset_engine/skips.py:176-177`; a skip with no time is left out);
- one line per `RuleControl` row: stage, state, name;
- the born names that have no row yet. They read research with no row (`signals/rule_actuator.py:108-117`) and would otherwise be missing from the list; the row is written with a rule's first stored signal (`signals/tasks.py:134-139`).

How to read its lines when his paste comes back:

| On the line | Means |
|---|---|
| `gate: ok` | the config-level gate was open at the last pass and the symbols were scanned; in read 1 the "last" line of each symbol it refused at that pass is current ("refusals 48h" says how many are) |
| `gate: ok (UNCHECKED: …)` | open, with a check that could not run or a pool declared above the account (`bot_program/asset_engine/base.py:4852-4857`) |
| `gate:` followed by any other words | the reason no symbol was scanned at all: "book risk limits: …" (daily loss past its absolute stop, exposure, open risk), "max # concurrent positions reached", "this pool follows the broker account …" (a reading over an hour old, `bot_program/capital_truth.py:575`, `:601-605`), "circuit breaker: …". Its "last" lines in read 1 date from before |
| `gate: ok` beside `gate_blocked` in "refusals 48h" | the elite band of the daily loss: past the limit, above the absolute stop, only an elite entry opens (R7) |
| a status `RUNNING` with an old time | the pass did not finish for that config; `None None` is a config never ticked |
| a last pass over 15 minutes old | the pass no longer reaches that config (it runs every 300 s) |
| `PAUSED` | a pause in force (`is_effectively_active()` False): no new signal, no new entry, whatever the stage |
| `paused` in lower case | a served pause whose status was never reset: the rule runs again, and the nightly sweep skips it (R2) |
| `reduced` | the half size applied by hand |
| `leverage_refused` in "refusals 48h" | the multiplier, or the cash check: not enough free cash, or cells that are missing, over an hour old, deferred by the request budget, in the other world or in another currency (`bot_program/asset_engine/base.py:8700-8790`). The nearest lead to "capital was free and nothing opened" |

Not printed by either read: the dated list of skips per symbol (M1 section 9, command 2, prints the eight newest per config), the pools, any amount.

**The note's three other commands,** run the same way: `paper_readiness` (read-only; he pastes it whole, it prints no amount); `component off pipeline_campaign_watch` and `component off actuator_mode_live` (each writes one switch row, with no PIN: "ON → OFF" on the scratch copy). Turning `actuator_mode_live` back on from the shell is refused ("turning it on takes your trading PIN, and the shell never asks for one. Turn it on from /ops/ (Switches, System) with your PIN."); the watchdog comes back with `component on pipeline_campaign_watch`.

**What the note told him to leave alone** until his outputs are read: no bot re-armed (the PR #86 sheet's rule stands: no second re-arming without us, and the bots left off on purpose stay off), no rule promoted, no limit or pool raised, nothing "repaired" from a BLOCKERS list.

**The note's defaults with no answer:** choice 1 (an automatic Council sitting after each LIVE hand trade) is no; choice 2 (letting a bearish rule trade) is A, its first step only, which is the 1h backfill sheet below.

**The 1h backfill still owed to him** (flags verified in `market_data/management/commands/backfill_bars.py:167-191`: `--symbols`, `--from-configs`, `--proving`, `--intervals`, `--bars`, `--dry-run`; a typed `--intervals` or `--bars` wins over `--proving`'s own 4h and 4000, `:232-241`). It was not given in the note of 2026-11-11; it goes in the sheet of the "honest path", which he gets if he chooses A and also if he does not answer (the note's default). It writes bars only.

```
cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py backfill_bars --proving --intervals 1h --bars 9000 --dry-run
cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py backfill_bars --proving --intervals 1h --bars 9000
cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py prove data --timeframe 1h --class forex
```

Cautions for that sheet (M2 section 2.2): the dry run downloads everything a real run does and skips only the writes; a light trial is `--symbols EURUSD,<SYMBOL> --intervals 1h --bars 9000 --dry-run`; run it after about 17:00 UTC or at a weekend, because rules fire on their newest stored bar whatever its age and a backfill that ends on a po3 fire bar would repeat that signal; do not follow it with `prove rules --save`.

---

## 8. Recorded, not in these four fixes

Each needs its own decision. Money direction is stated where there is one.

| # | Finding | Source | Money direction of a fix |
|---|---|---|---|
| R1 | Applying or rolling back an actuator action, or a meta-allocation, on a rule with no stage row creates the row at `live_full`. A paper-only rule becomes a real-money rule after a pause. Reachable only with the matching live-mode switch ON. The French note advises `actuator_mode_live` OFF for this reason | M3 A1, M2 D5; `signals/rule_actuator.py:409-413`, `:489-493`; `signals/meta_allocator.py:419-424` | fewer real-money entries. **Recommended as the next small fix** |
| R2 | A served pause keeps the status "paused", and the nightly sweep skips that status: the rule is never promoted or demoted again | M3 A2; `signals/promotion_pipeline.py:1255-1258` | the floor reaches the rule again: fewer real-money entries from a measured loser |
| R3 | A born rule at the paper stage casts no vote on a live config. On a fleet with no scanning paper bot it can never earn the paper fills Aragorn asks for; its ladder ends at paper unless promoted by hand | M2 D1; `signals/rule_birth.py:74-79`, `:152-168` | a paper-mode config for the pack's markets: more paper entries considered, no real money. To design with the operator (French note, choice 2: with no answer, A, its first step only). The step from paper to real money is Aragorn's (20 proven paper closes of one class, then a quarter size: `bot_program/aragorn.py:84`, `:90-94`, `:206-220`, `:399-446`), so path A ends at the paper stage while the `aragorn` switch, a PIN switch (`core/platform_control.py:107`), is off; the note says so |
| R4 | In a crisis posture the platform's words say "shorts and safe havens keep trading" while every rule of the bearish pack is born at research, and a forex SELL that buys the lower-ranked currency is classed risk-on long | `bot_program/market_stress.py:455-461`; `bot_program/posture.py:100-118`; M1 section 4.5 | words only. F3 puts the level in force in the fact block |
| R5 | The nightly sweep can take only `golden_cross` and `death_cross` to a live stage; the docstring, the component text and the HQ card read as if every rule could climb | M2 D2 | none (words) |
| R6 | A hand promotion to a live stage takes no PIN and no evidence, one click a rung | M2 D6; `dashboard/views_admin_hq.py:1598-1614` | a PIN on it: fewer real-money entries by accident |
| R7 | Closing his own real positions at a loss counts in the bots' daily loss limit for 24 hours, with no word to him; in the elite band the gate's note reads `ok` | M1 D13, D15; `portfolio/risk_gate.py:663-684` | none (words) |
| R8 | The refusal of a close in the wrong world advises "flip the SIM/Demo box back". For a real position that is the move he must never make | M3 V1; `bot_program/engine/venue_close.py:137-141` | none (words). Small and worth doing soon |
| R9 | Demo rows count as real in the book limits and in a live bot's slots | M3 V2 | already agreed as "real-only limits", not built |
| R10 | The Council is graded only while `pipeline_calibration` is on, and nothing says so on `/council/` or on the card | M5 G1 | none |
| R11 | `council_bots` starts model spend by itself and the Agents group's "all on" turns it on | M5 G11; `core/switch_pin.py:328-335` | none; add both Council switches to the exempt set |
| R12 | The close of a hand-taken trade is filed as a bot event: muting the bots' alerts also mutes the close of his own trades | M5 G13; `bot_program/notifications.py:36-47`, `:1783-1784` | none |
| R13 | Rules read their newest stored bar whatever its age; `Signal` has no per-bar key, so a rule fires again on an unchanged bar 24 hours after a close | M2 D10; M4 section 11, items 3 and 4 | fewer signals; fewer votes on the next session for shares |
| R14 | The share quote poller's clock is 13:30 to 20:00 UTC all year, so from November to March it stops an hour before the New York close | M4 section 11, item 7; `core/market_calendar.py:21-29` | none |
| R15 | The proving ground charges every forex pair the majors' 2 bps; a forex verdict is optimistic for an exotic such as <SYMBOL> | M2 D11 | none until a verdict binds |

---

## 9. What only the operator's data can settle

The French note of 2026-11-11 asks him for the two reads of section 7 and for the whole output of `paper_readiness`. Until they come back, nothing here is asserted about his server. What each one settles:

| Not known | Settled by |
|---|---|
| the stage of `po3_london_sweep_short` and of every other rule, whether any rule is at a live stage, which rules are paused in force | read 2, the rule lines and its last line (born names with no row) |
| the posture level in force and whether `crisis_mode` is on (Ask Sauron's answer quoted the crisis level's sentence beside a score of 40.5) | read 2, first line |
| which enabled bots exist, in which mode, and whether one lists <SYMBOL> | read 2, the bot lines; read 1, section 3 for the bots that are off and who stopped them |
| whether a config-level gate is closed (daily loss past its absolute stop, exposure, slots, a stale account reading, a breaker), and whether the pass reaches each bot | read 2, `last pass` and `gate:`. Read 1 cannot show it: it prints old counts and old "last" lines for such a bot (4.1) |
| the refusals since his capital was free | read 2, "refusals 48h" by code, beside read 1's "last" lines for their words. The dated list per symbol is not in either read (M1 section 9, command 2) |
| the state of the five live-action keys, and any blocker beyond the two that are normal for a live operator | `paper_readiness`, section 3 and its BLOCKERS list |
| whether `pipeline_campaign_watch` and `actuator_mode_live` were turned off as advised | his word, or `component list` |
| whether his real closes of the night the capital was freed were losses that count against the daily limit (R7) | read 2 shows the gate's words with the amounts masked; the amounts stay with him |
