# MAP 1 — Wakes and the mind: what O2a must add

Source: the read-only checkout of main 9d74a19 (2026-11-01) at
`/home/user/Sauron_Vision/.claude/worktrees/orcsread`. Every `file:line` below
is in that tree. A bare file name is under `bot_program/orcs/`.

Companion maps: `map_ai.md` (the provider, the prices, the per-call and per-day
cost), `map_army.md` (the O2b-O2d hooks), `map_pitfalls.md` (the recovered O2a
review findings turned into requirements). Where a recovered pitfall binds a
hook named here it is flagged **[P]**; the requirement itself is in
`map_pitfalls.md`.

Legend: **HAS** = the code already does it. **ADD** = O2a must add it.
**DECIDE** = the code leaves a choice the spec must make. **KEEP** = an O1
guarantee O2a must not break.

---

## 0. The answer on one page

For an Orc to wake, think, and leave a plan and intents in shadow, O2a must add
eight things. Everything before the dispatch already exists.

1. **A dispatch stage after the render.** Today a wake ends `skipped` ("no model
   before O2") or `quiet` (F6) when `orc_render_wakes` renders it
   (wake.py:745-749). O2a turns a rendered, non-quiet wake into `pending`, admits
   or refuses it (per-Orc caps, the Orcs line, a reserve, urgency, money world),
   queues it to a worker, and claims it (`running`). The seam is marked at
   wake.py:54-55. ADD: new statuses and codes, the `orcs` queue and its worker
   (config/celery.py:96, :100-101), a switch OFF on arrival, the watchdogs
   (stalled queue, silent worker → the care), and the Orc's states `active` and
   `care_owned` (constants.py:8-16).
2. **S, the doctrine.** It is reserved in the size cap (`S_TOKENS_RESERVE = 3930`,
   constants.py:299-300) but no text exists. ADD: an English system block,
   versioned and stored as a dossier block, that fits the reserve. It is cached
   for 1 h.
3. **The request built from the stored blocks.** `dossier.render` already returns
   the shared prefix (MK0, the closed sessions, MK-E, IN-slow) and the private
   pair (PS, tail) (dossier.py:433-443). ADD: send them as the provider's
   `system_blocks`, `shared_user_blocks` and `private_user_blocks`, with the
   cache breakpoints the smoke measured (claude_smoke.py:14-19); render for the
   routed model's family (today the render is for "sonnet" only, wake.py:728,
   dossier.py:360); fill PS1, PS3 and PS5 (dossier_position.py:16, 38, 176-184;
   dossier.py:409-410).
4. **The call, on the Orcs line.** Use agent `orc` and source_ref `Orc:...`
   (spend.py:95-97). Ask `can_spend(line="orcs", estimated_usd=..., tier=...,
   deep_share_exempt=...)` before the call. `BaseAgent.run` asks only the total
   (base_agent.py:83-86), so the Orc's caller must ask its own line. ADD a
   reservation: `can_spend` reads only spend already booked (spend.py:149-154),
   so two concurrent calls can overshoot. Call the provider with
   `line="orcs", client_refusal_rerun=False` (claude_provider.py:405-408), a
   `max_tokens` cap and an `output_schema`.
5. **The validator.** The code already provides V10 (fence.py:169-204), the F5
   menu shrink (integrity.py:102-133), the L0 vocabulary (integrity.py:34-39),
   I11 room (constants.py:115-119, playbook.py:68-98), the menu's ids
   (menu.py:293-300) and the money filter (plain.py:36-42). ADD: run every check
   on the answer and journal each failure as a `refusal`. ADD the fact
   producers V10 needs: no code writes a `bar`, `gap` or `level_reached` fact
   today (fence.py:35-37; only drum_bus.py:675 sets `fk`).
6. **The plan.** `Orc.plan`, `plan_version` and `plan_changes_24h`
   (models.py:83-85) are reserved and never written. ADD: write them,
   journal kind `plan`, render the plan by code (notes.py:507-510) and show it
   in PS3.
7. **Intents in shadow.** ADD the `OrcIntent` table in O2's own migration
   (models.py:7-9; tests/orcs/test_orc_models.py:17-20), with mode `shadow` or
   `refused` (constants.py:388-389). No intent ever reaches an order. The O arm
   (`orc_shadow`, constants.py:157) gets a shadow mode, built from the existing
   hand-act transition (ghost.py:947-962) and the playbook arm's
   `extra_stop` path (ghost.py:760-819, 911-916), so each intent is graded
   against the care ghost.
8. **Truthful words and deliberate pin changes.** About twenty O1 sentences say
   "no model" (§2.8 lists them). Several tests pin the O1 boundary: no `pending`
   wake, no O2 table, no `orcs` glob, no `ai_agents` import in the O1c modules
   (§2.7). O2a must change those pins on purpose, and prove every claim with a
   fake model. No fake provider exists in tests/orcs today.

---

## 1. The O1 pipeline as it stands

### 1.1 The tick (fast worker, every bot pass)
- `AssetBot.manage_positions` runs the care, then
  `observe.after_care(bot, trade, price, _cared)` and **ignores its return**
  (asset_engine/base.py:1396-1409). This is why an Orc cannot steer the tick.
  KEEP.
- `after_care` costs no query for a row with no stamp. It reads the `orcs`
  switch once per pass, then runs `TICK_STEPS = (_snapshot_seen, _observe_tick,
  _check_predicates, _step_ghosts, _drums_tick, _detect_wakes)`, each step
  fenced (observe.py:84-113).
- `wake.detect` never raises. It finds W1-W4, W6, W8-W11 and merges what the
  census left in `seen["wake_pending"]` (W5, W7, W10 pending) (wake.py:351-399).
  - An urgent reason records at once. The others wait `MIN_WAKE_SPACING_MIN =
    15` after `seen["last_recorded"]` (wake.py:386-393; constants.py:257). A
    deferred reason is pended under the Orc's lock (wake.py:402-421).
- `wake.record` writes the OrcWake in a savepoint (wake.py:396-399, 637-691):
  - `status="skipped"`, `skipped_reason="no model before O2"`;
  - `priority` 1.0 when urgent, else 0.0;
  - `kind`: birth, routine or material (wake.py:628-634);
  - `dedupe_key = "orc<pk>:<YYYYmmddHHMMSS>:<first reason key>"`;
  - `components = {render: "queued", as_of, price, care, predicates,
    prev_recorded}`.
  It then merges the memory under the lock (`wake_keys`, `wake_once`,
  `wake_pending`, `last_recorded`, `w11_at`, `band_hold_until`, `w2_bar`,
  `w3_at`) and sets `next_wake_due` (the metronome).

### 1.2 The census (fast worker, every 5 min)
- census.run, in order (census.py:146-178):
  - deaths, births, restamps, late seeds;
  - review and pending-close facts;
  - then `wake.census_book` (W7), `wake.census_clock` (W5),
    `wake.census_pending` (W10), `drum_bus.census_market` and `drum_bus.route`.
- The census reasons reach a wake only through `seen["wake_pending"]`
  (wake.py:843-855), which the next tick merges.
- The result names no `skipped`, `parsed` or `attempted` key, because the task
  gate reads those as health verdicts (census.py:25-27;
  core/task_gate.py:9-84).

### 1.3 The render pass (slow worker, every 2 min)
- `tasks.orc_render_wakes` → `wake.render_queued(limit=40)`: oldest first, each
  wake in its own savepoint; a failure marks `components.render = "failed"` and
  is never retried (tasks.py:290-312; wake.py:793-831; config/celery.py:512-516).
- `wake.render_wake(wake)` (wake.py:694-790), as of `components.as_of`:
  1. Build the context: the care the tick saw, `dossier.context_for` (mark,
     frames, menu, candidates, integrity, allowed actions), the day's weather
     (wake.py:704-727; dossier.py:220-345).
  2. `dossier.render(orc, trade, ctx, as_of=now)`, with the default model "sonnet"
     (wake.py:728; dossier.py:360; constants.py:296).
  3. Score: the complexity vector, stakes, score, floors (F1-F4) and band with
     hysteresis and hold (wake.py:729-740).
  4. F5 items, the facts hash and F6 quiet (wake.py:741-744).
  5. Write the status (skipped or quiet), `components` (vector, stakes, floor,
     f5, f6, tokens, trimmed, render done, as_of, price), `block_hashes`, and
     `finished_at = now`. Note that `finished_at` is the as-of moment, not a
     finish time (wake.py:745-760).
  6. Remember `band`; for a non-quiet wake also remember
     `answered_hash = fh`, the O1 "proxy" (wake.py:761-763; wake.py:46-47).
  7. Write the card's `intellect` and `integrity` (wake.py:765-773) and a
     journal `wake` entry kept off the card (wake.py:777-784). A quiet wake also
     gets a `reading` entry and `latest_note` (wake.py:785-789).

### 1.4 What a rendered wake holds that O2a can use as is
- **The dossier's hash list** (OrcWake.block_hashes), in this order: MK0, each
  closed session, MK-E, IN-slow, PS, tail (dossier.py:370-373, 433;
  dossier_market.py:290-308).
- **Its token estimate** (`components.tokens`), what was trimmed, the integrity
  verdict (in the tail), the band, the day class and the F5 items.
- **The reasons**: code words only, no third-party text (wake.py:873-879).

### 1.5 What does not exist anywhere
- S text, the answer schema, the validator, `OrcIntent` or any O2 table, a model
  call from the Orcs, the `orcs` queue and its worker, an Orc state other than
  `born` and `dead`.
- The fact kinds `bar`, `gap` and `level_reached`.
- `continuation_odds` (backtester/proving/memory.py has no such function).
- `wake.request` (named only in a comment, predicates.py:37, :351).
- A fake model provider for the Orcs' tests.

---

## 2. What O2a must add

### 2.1 Wake → dispatch

**(a) The switch.** ADD a System switch, OFF on arrival, that gates every Orc
model call. Its name is a DECIDE (e.g. `orcs_minds`).
- The `orcs` switch must stay a "journals, no model" switch. Its name and
  description say so (core/platform_control.py:323-324), and `orcs` is armed by
  "all on" (switches.py:1-3).
- DECIDE whether the new switch joins `BULK_ENABLE_EXEMPT`
  (core/platform_control.py:126-127). Recommendation: yes. It spends dollars,
  though it moves no money, so it is not a LIVE_MONEY switch.
- The budget line is a second, independent gate: `ORC_DAILY_BUDGET_USD = 0`
  refuses every Orc call (spend.py:79-81, :229-230). Its default must stay 0
  (tests/test_ai_spend_lines.py).
- "Shadow before power": power still needs a PIN-gated switch from O3 on. O2a
  adds no PIN switch, because nothing binds.

**(b) Statuses and codes.** Allowed values live in constants.py as tuples, never
as `choices` (constants.py:1-3; models.py:11-13;
tests/orcs/test_orc_models.py:74-79).
- O1 writes `skipped` and `quiet` (constants.py:351-357). The model default is
  `pending` (models.py:166).
- ADD at least: pending, running, done, failed, stale, merged, and a refused or
  unbudgeted status, each with its `skipped_reason` code (budget, day cap,
  switch off, dead, row closed, spacing, over budget, ...).
- The recovered O2a used `day_cap`, `merged`, unbudgeted, dead, stale, and
  "answered by code" [P].
- `STATUS_WORDS` (constants.py:356-357) must gain words for each new status.

**(c) Where a wake becomes pending.** The render pass is the natural place,
because the prompt needs the dossier.
- After `render_wake` saves, a non-quiet wake whose switch, line and admission
  pass becomes `pending`; otherwise it ends with a code.
- KEEP: the tick never writes `pending` and never pays for dispatch
  (observe.py:8-16 query budget).
- DECIDE the dedupe. The unique constraint `orcwake_one_pending_per_key` is on
  `dedupe_key` where `status="pending"` (models.py:180-185). Today's key carries
  a timestamp to the second (wake.py:657-658), so the constraint never merges
  two wakes of one Orc. For "one wake in flight per Orc", key the pending state
  per Orc, or lock the Orc row and merge a newer wake into the older one
  (status `merged`) [P "a newer wake absorbs an older urgent one" — the frozen
  `priority` at wake.py:659 must be recomputed on absorb].

**(d) Admission and triage.** ADD. Every input already exists.
- **Per-Orc wake cap:** `weather.WAKES_PER_DAY` = real calm 12 / eventful 14 /
  stormy 16, paper 12 (weather.py:31-32). Today it is display only
  (`caps_for(...)["display_only"]`, weather.py:37-42; weather.py:6-9: "the
  dollar caps arrive with the router, O2").
  - Trap: OrcDayBaseline is per (user, class), not per world. Its stored `caps`
    are whatever the first reader's `real` produced (`orc_day_roll` calls
    `weather.current` without `real`, so real=True, tasks.py:177;
    weather.py:160). O2a must compute the cap per Orc with `caps_for(day_class,
    real)`.
- **Per-Orc day counters:** `Orc.llm_wakes_today`, `routine_wakes_today`,
  `spend_today_usd` and `routine_spend_today_usd` (models.py:103-109) are never
  written. ADD them. A routine wake must also respect the day totals that urgent
  wakes used [P].
  - DECIDE the clock. The spend line's day starts at UTC midnight
    (spend.py:143-146; config/settings.py:445 `TIME_ZONE = "UTC"`); the weather's
    day rolls at 17:00 New York (constants.py:371). Pick one and say it.
- **The line:** `spend.can_spend(line="orcs", ...)` and
  `spend.remaining_today("orcs")` (spend.py:191-276). The cap binds even with no
  total (spend.py:223-225).
- **The core floor:** `ORC_LIVE_FLOOR_USD = 3.00` is held back from the CORE line
  for the Orcs' live urgent and confirm wakes (spend.py:28-31, :82-84). It is
  not a reserve inside the Orcs line. "The reserve" in the dispatch seam
  (wake.py:54) is O2a's own slice of the Orcs line for real-money wakes: DECIDE.
  The recovered order was real urgent > real routine > paper urgent > paper
  routine, with paper urgent stopping at 60% of the line [P].
- **D30:** inside the Orcs line, a live urgent or confirm wake may pass
  `deep_share_exempt=True` past the 70% deep-tier share (spend.py:34-36,
  :216-218, :267-272). The share binds only for `tier in ("deep", "frontier")`,
  so O2a must pass the rung's tier honestly: Haiku → fast, Sonnet → balanced,
  Opus → deep, Fable → frontier.
- **Urgency and money world:**
  - urgency: `OrcWake.priority` (wake.py:659) and `reason.urgent` (wake.py:141-145);
  - money world: `birth.world(row)` gives live, demo or paper (birth.py:126-135);
    the seat's venue is the world frozen at birth (constants.py:39-46).
- **Spacing:** `MIN_WAKE_SPACING_MIN` is checked only at detection
  (wake.py:386-393). ADD a re-check at the claim for a non-urgent wake [P].

**(e) The queue and the worker.** ADD the `orcs` queue and a worker that
consumes it.
- Today there is no `orcs.*` glob (config/celery.py:96, :100-101). The O1b and
  O1c tasks are routed to `slow` by exact name (config/celery.py:102-115).
- docker-compose has only `worker-fast` (fast,default -c 3) and `worker-slow`
  (slow,ai -c 2) (deploy/docker-compose.yml:163-175). A glob to a queue no
  worker consumes strands the tasks (tasks.py:4-6).
- Every new task is `@guarded_task("orcs")` (core/task_gate.py:88-140) and
  returns `idle` when it has nothing to do (tasks.py:13-15).

**(f) The claim.** ADD. Lock the OrcWake row: pending → running and set
`started_at` (models.py:171, never written today). Then re-check:
- the switch;
- the Orc is not dead (wake.py:342 is the tick's check);
- the row is still OPEN or CLOSE_PENDING (wake.py:82);
- the line with the reservation;
- spacing.

Re-check the row after the call too [P "an Orc whose row closes during the model
call still gets a queued shadow intent, last_good_wake_at and a plan"].

**(g) Watchdogs.** ADD census steps in the O1c tuple style (census.py:167-178).
- A queue stall: a pending wake older than N minutes. Use a first-send clock,
  never a re-stamped one [P].
- A silent worker: a wake that waited for a worker and never ran sends the Orc
  to the care. Count only wakes that really waited (pending, running, failed,
  stale), never wakes answered by code, merged or unbudgeted [P].
- The stale rule: a wake older than X minutes is closed as stale [P: the
  recovered value was 30 min].

**(h) The Orc's states.** `STATE_ACTIVE` and `STATE_CARE_OWNED` exist as
constants and are never written ("arrive with the wakes (O2)",
constants.py:8-16).
- The words already exist: "Active.", "Stood aside: the care holds this
  position." (notes.py:140-146).
- Journal kinds `takeover` and `return` exist (constants.py:25).
- `care_owned_reason` (read by notes.slot, notes.py:533) and `care_owned_at`
  (models.py:110-111) are never written.
- ADD the transitions: born → active on the first good wake; active →
  care_owned on silence or repeated refusals [P]; care_owned → active only
  through a wake that read the takeover fact [P].
- In shadow, "care_owned" changes nothing the care does: the care always holds
  the row in O2.

**(i) The next wake asked by the model.** `Orc.next_wake_due` is written today
only as the metronome (wake.py:667-690). It has an index (`orc_next_wake`,
models.py:126).
- ADD: a validated `next_wake` from the answer [P "the validated next_wake is
  dropped"], detected as a reason. W11 already reads `seen["w11_at"]`
  (wake.py:307-309).
- DECIDE whether this is a new reason code or a W11 key.

**(j) Seams to keep open for O2c.**
- **W12, the drum wake:** a delivery in `drum_bus.route` adds W12 to the
  receiver's pending wake, urgent per `_urgent_for`, gated by `orcs_drums`
  (drum_bus.py:41-44, :582-597, :666-667; core/platform_control.py:328-331).
  - The wake side already reads W12: the disagreement flag "a drum heard on this
    wake" (wake.py:544-546).
  - O2a's admission must accept W12 reasons, which arrive through
    `seen["wake_pending"]` like the census reasons (wake.py:843-855).
- **`wake.request(orc, "W8", urgent=True)`** (predicates.py:36-38, :351) does not
  exist. W8 is already detected on the same tick from the predicate's state
  transition (wake.py:257-262). DECIDE: delete the stale seam comment, or add
  `request()` as the one API for drums, the operator's questions (O2d) and the
  model's next_wake.

### 2.2 Assemble the prompt from the dossier

**(a) S, the doctrine.** "S the doctrine (O2; reserved in the size cap:
S_TOKENS_RESERVE)" (dossier.py:5). `S_TOKENS_RESERVE = 3930` was "measured by
the 2026-10-16 smoke" (constants.py:299-300). The trim and IN-slow budgets
subtract it (dossier.py:163, :398; dossier_instrument.py:216-217).
- ADD the text: English, versioned, stored as a block (`dossier.block("s",
  "s|v<n>|<family>", ...)`), so a replay prints it.
- Its tokens must fit 3930 on the package's estimator (4 chars a token × the
  family factor, dossier.py:102-107) and on the real tokenizer through the
  smoke's count. Otherwise the reserve constant moves with it.
- The smoke's synthetic layer sizes, mid-day: S 3050, MK 3650, IN 2830, PS 2650,
  tail 3700 tokens (claude_smoke.py:60).
- Content the code already defines and S must state:
  - the fence's bands T0/T1/T2/N and "may be wrong; facts win" (fence.py:4-13,
    :31-32);
  - R and ATR units only, never money (dossier.py:20);
  - the L0 vocabulary and why-not (integrity.py:32-39);
  - the V10 relevance table (constants.py:227-241);
  - the menu's level ids (menu.py:15-18) and the playbook's candidate ids, which
    are unordered (playbook.py:5-7, :9-23);
  - the R0-R6 reversibility ranks (wake.py:97-100; constants.py:274-275);
  - the answer schema.

**(b) The shared user turn.** It is MK0, the closed sessions and MK-E, then
IN-slow, the leading `render()["shared"]` hashes (dossier.py:373, :439).
- `OrcWake.block_hashes` keeps the list but not the `shared` count
  (wake.py:750-756). ADD: store it, or rely on "the last two are PS and tail"
  (dossier.py:433).
- MK and IN-slow are byte-identical for every Orc on a model (and a symbol)
  (dossier.py:18-19). The smoke's measured layout (claude_smoke.py:14-19):
  - S in `system`, cached 1 h;
  - the shared turn: the MK blocks with the last one cached 1 h, then IN-slow
    cached 5 min;
  - the effort-only system message;
  - the private turn: PS and the tail, uncached.
- At most 4 cache breakpoints (claude_provider.py:49); this layout uses 3.
- MK-E sits after the sessions (dossier_market.py:307). When the Emperor's line
  lands (O2c), only the bytes from MK-E onward change.

**(c) The private user turn.** PS (`ps_hash`) and the tail (`tail_hash`), per
wake, uncached.
- The tail carries `mk_missing`, `mk_now` (the user's clusters and book as
  shares), `in_today`, `ps12`, `ps13` and the reasons (dossier.py:416-427).
- `turn_effort` sets the private turn's effort, if the model supports it
  (catalog `per_message_effort`; claude_provider.py:393-399).
- If the smoke's C3 effort check fails, each (model, effort) pair becomes its own
  cache namespace and the router changes model and effort per epoch, never per
  wake (claude_smoke.py:27-29).

**(d) Render per family.** `render(..., model=DOSSIER_REFERENCE_MODEL)`
(dossier.py:360); `render_wake` passes no model (wake.py:728).
- The beats build MK for every family (tasks.py:163-170, :217-224) and IN-slow
  hourly for every family (tasks.py:258-266). `day_hashes` only FINDS MK, never
  builds it (dossier_market.py:290-308).
- ADD: render, or render again, for the family of the model that will be
  called. `family_of(model_id)` maps an id to its family (dossier.py:65-76).
- PS and tail hashes do not depend on the family unless the trim differs.

**(e) The O2 dashes.**
- **PS1** ADD: the allowed actions come from the officer.
  `integrity.allowed_actions_l0` stands in today (dossier.py:333-334;
  integrity.py:19-21). "level" is hard-coded "L0 shadow"
  (dossier_position.py:72), which stays true in O2.
- **PS3** ADD: the current plan rendered by code, its version and the last
  expectation's result. Today it is `PS3_WORDS` (dossier_position.py:38, :293)
  [P "the dossier shows the result of the expectation from two decisions ago"].
- **PS5** ADD: `notes` holds the Orc's own earlier notes as T1 views (cap
  `FENCE_CAPS["mind"] = 300`, constants.py:225-226; fence.py:7-9), the last
  decisions with their outcomes, and the officer's refusals [P "PS5 has no
  last 6 decisions with outcomes, and the officer's refusals never reach the
  model"]. Today notes = [] and the dash reads "— (no note: the Orc writes none
  before O2)" (dossier_position.py:176-184; dossier.py:409-410). `ps5_notes` is
  third in the trim (constants.py:304).
- **PS4** carries `"loss": "+0.00R"` hard-coded (dossier_position.py:169) [P
  would-mode "prior losses are 0"].
- **PS9-PS11** stay dashes for O2c (dossier_position.py:299-304).
- **PS12 continuation odds:** "— (continuation odds arrive with O2)"
  (dossier_position.py:355-356). No reader exists: DECIDE between building it
  in O2a and keeping the dash.
- **MK-E** stays "— (no order yet today)" until O2c (dossier_market.py:258-268).

**(f) Size caps.**
- `DOSSIER_MAX_TOKENS = 22000`, S included (constants.py:216-217).
- The per-wake budget is 22000 − 3930 − the shared blocks' tokens
  (dossier.py:396-399).
- The trim runs in order `in12_5m`, `in12_15m_old`, `ps5_notes`, `in9`,
  `in1_1h_old` (the last one at IN-slow build) (constants.py:301-304;
  dossier.py:159-174; dossier_instrument.py:216-225).
- `MK_SESSION_MAX_TOKENS = 900`, headlines 6 → 4 → 3 (constants.py:220-224);
  `PS_TAIL_RESERVE = 6600` (dossier_instrument.py:39-41).
- `render()` returns `over_budget` (dossier.py:441). ADD: refuse the call, with
  a code, when it is true.
- Token counts are ESTIMATES (dossier.py:22-25). ADD: store the provider's real
  input, cache-read and cache-write tokens beside the estimate.

**(g) The facts index and the missing facts.** V10 needs `{id: {kind, symbol,
at, event?, drum_kind?}}` (fence.py:169-174). ADD a builder over the Orc's
OrcJournal facts.
- `kind = fence.fact_kind(entry)` (fence.py:117-152).
- `symbol`: the Orc's own symbol for its own facts; `body["symbol"]` for a drum,
  so a correlate's drum fails V10's `symbol: True`, by design.
- ADD the producers. Today no code writes:
  - `fk: "bar"`: V10's reduce and add sets name "bar" (constants.py:233-235);
  - `fk: "gap"`: V10's `lock_waive` set (constants.py:238);
  - `fk: "level_reached"` [P V6].
  Only the drum facts carry an `fk` (drum_bus.py:675).
- The care's event-window fact keeps the calendar title in its body
  (facts.py:294-299). V10's `event` match must key on code (the calendar row's
  id or time), never on that title.

**(h) Replay.** `text_of(hashes)` (dossier.py:141-147); `manage.py orcs dossier
ROOT --wake N` (management/commands/orcs.py:100-124). ADD: S's hash in the
replay, and the answer with its validation printed beside it.

### 2.3 Call a model inside its budget line

**(a) Who pays.** `spend.orc_line_q` puts on the Orcs line every ledger row
whose agent is `orc` or `captain`, starts with `orc_` or `captain_`, or carries a
`source_ref` starting with `Orc:` or `Captain:` (spend.py:93-97, :130-140).
- The names shown on /ai-models/: `orc`, `orc_confirm`, `orc_question`,
  `orc_postmortem`, `orc_tribunal`, `orc_emperor`, `orc_skeptic`, `captain`
  (dashboard/views_ai_models.py:89-105).
- ADD: agent `orc`, source_ref `Orc:<orc pk>:Wake:<wake pk>`.

**(b) Ask the line.**
- `BaseAgent.run` refuses only at the day's TOTAL (`total_only=True`,
  base_agent.py:74-91, :103-109), and it sends only `system_prompt` and
  `user_message` (base_agent.py:134-148): no blocks, schema, line, fallbacks or
  max_tokens.
- So the Orc must call `can_spend(tier, estimated_usd, line="orcs",
  deep_share_exempt)` itself (spend.py:208-276), and call the provider directly
  (`record=True` books the row, claude_provider.py:362-381), or extend `run()`.
- `estimated_usd` defaults to 0.05 (spend.py:208). ADD a real estimate:
  `catalog.cost_usd(model, input_tokens=<render tokens>,
  output_tokens=<max_tokens>)` as the worst case (ai_agents/catalog.py:431-437;
  numbers in map_ai.md).

**(c) The reservation.** `can_spend` sums only booked spend (spend.py:149-154).
- ADD: hold `OrcWake.est_usd` (models.py:168-169, never written today) on every
  running wake and subtract it from the line's remaining under a lock. Release
  it on the booked cost.
- A failed or refused call is still billed by the provider (base_agent.py:177-202;
  claude_provider.py:417-423) [P: a timed-out call booked at $0 was judged
  false].

**(d) The provider call.** `ClaudeProvider.complete` (claude_provider.py:333-351,
:383-415) already takes:
- `system_blocks`, `shared_user_blocks`, `private_user_blocks`, `turn_effort`;
- `output_schema`, `max_tokens` ("the Orcs' per-wake cap"), `fallbacks`;
- `line`, `client_refusal_rerun=False` ("Every Orc call passes False and relies
  on `fallbacks` alone"), `timeout_s`, `task_budget`, `speed`.

`build_request` raises before anything is sent on a request the API would
refuse (claude_provider.py:167-181).

- **Effort.** The smoke's layout pins the top-level `effort` at the model's
  default and carries the rung's effort in `turn_effort` (claude_smoke.py:14-19).
  The defaults: Sonnet 5.5 high, Opus 5.5 medium, Haiku 5.5 medium
  (tests/test_model_catalog.py:414-416). So r0 "Sonnet low" is low only through
  the effort-only message, and only if the model supports it (catalog
  `per_message_effort`).
- **Refusals.** With `client_refusal_rerun=False` the only re-run is the server's
  `fallbacks`. The forms differ per model: Opus 5.5 and Fable 5.1 "both",
  Sonnet 5.5 "default", Haiku 5.5 none (tests/test_model_catalog.py:409-412). On
  Haiku a refusal is a billed failure, and every attempt of a server re-run is
  billed (claude_provider.py:402-404).

**(e) Which model in O2a.** Routing is O2b. The ladder is in
ai_agents/catalog.py:500-519 (h0 Haiku low, a paper probe; r0 Sonnet low,
routine; r1 Sonnet high; r2 Opus medium; r3 Opus high; r4 Opus xhigh; r5 Fable
max, real money only, under a quota).
- A model id may appear only in ai_agents/catalog.py: a test scans the platform
  for literals (tests/test_model_catalog.py:456-525; constants.py:277-285).
- DECIDE O2a's fixed rule: one rung for every wake, or band → rung without
  probes and quota. Read the rung from the catalog by name.
- The floors already in code: F2 (a real-money birth is at least complex) and
  F1 (a confirm wake) (complexity.py:256-274).

**(f) Booking.**
- `OrcJournal.model`, `tokens_in`, `tokens_out`, `cache_read`, `cache_write`
  and `cost_usd` (models.py:206-211) are never written. ADD them on the decision
  entry.
- `OrcWake.model` (models.py:167); the Orc's day counters (§2.1 d).
- `OrcGrade.ai_cost_usd` is written 0 (grading.py:181).
  `grading.numbers(ai_cost=)` already turns a cost into `orc_r` and
  `net_edge_money` (grading.py:57-84), but `grade()` passes none
  (grading.py:144-147). ADD: the sum of the idea's Orc costs.

**(g) Where the call may live.**
- The O1c pins forbid any `ai_agents` or `anthropic` identifier, and
  `count_tokens`, in sessions, fence, complexity, integrity, weather, sources,
  dossier, dossier_market, dossier_instrument, dossier_position, wake, drums,
  drum_bus, observe, census, tasks, journal and notes
  (tests/orcs/test_orc_source_pins_o1c.py:18-21, :32-39).
- constants.py:281-282: "the orcs package imports nothing of ai_agents".
- ADD a new module (e.g. `mind.py`), the only one that imports
  `ai_agents.spend` and the provider, with its own pins: none of the FORBIDDEN
  identifiers (tests/orcs/test_orc_source_pins_o1b.py:15-20) and no
  AssetBotTrade write (:21-23).

### 2.4 Validate the answer

**(a) The schema keys the code already implies.**
- The fence withholds third-party text that looks like an action JSON with the
  keys `action`, `candidate`, `level_id`, `facts_cited` and `risk_share`
  (fence.py:57-58). These are the lost spec's answer keys.
- V10's inputs: the action kind, the cited ids, the event, and the plan
  version's time (fence.py:169-170).
- A note of 140 characters (`latest_note`, models.py:97; `FENCE_CAPS["note"]`).
- An expectation that can be graded (`OrcGrade.expectation_hit_rate`,
  models.py:276).
- Flip-flops (`flipflop_rate`, models.py:277).
- "the Orc's own dead" signpost (tribunal.py:7-8).
- `next_wake` (§2.1 i); a plan whose prices code renders (notes.py:507-510).
- `risk_share` stays out of O2a: adds need the officer (integrity.py:33-39;
  playbook.py:25-27).

**(b) The checks, each with its hook.** ADD them all; every failure is a refusal.
1. **The action is allowed:** in PS1's allowed list, `L0_ALLOWED = hold,
   revise_plan, tighten, exit, trim, lock_waive` (integrity.py:34-35), plus
   plan and note.
2. **F5:** under critical items, only hold, revise_plan, and tighten on a fresh
   mark (integrity.py:102-116).
3. **The candidate is real:** a named candidate must be in `ctx["candidates"]`
   after the F5 shrink (dossier.py:340; integrity.py:119-133). P-HOLD is a
   waiver though its action reads "hold" (integrity.py:29-31).
4. **The level is real:** a `level_id` must resolve with
   `menu.level_by_id(rows, id)` on the dossier's menu (menu.py:293-300;
   dossier.py:267-268).
5. **I11 room:** a stop needs ≥ 0.5 × ATR(tf) of room on p and on m, and at most
   3 × ATR(4h) from m (constants.py:115-119). This is the arithmetic of
   `playbook.t_struct` (playbook.py:88-93). Use the level's own `stop`, the one
   beyond the crowd (menu.py:111-126) [P "the shadow stop is the raw level"].
6. **Tighten only:** the new stop must be tighter than the effective stop
   (`ctx["effective"]`, dossier.py:270-277; the rule at playbook.py:94-96).
7. **V10:** `fence.v10_satisfied(kind, cited, facts_index, symbol, event=,
   since=plan_at)` (fence.py:169-204). A hold or note needs nothing; a plan
   needs a T0 fact newer than its version. V10's own failure text is "advisory
   to the phone" (fence.py:202-204) [P "V10 writes no refusal and is not counted
   in the invalid-output rate"].
8. **The plan-change rate:** `Orc.plan_changes_24h` (models.py:85). Count only
   changes inside 24 h [P].
9. **No money in the words:** `plain.voice(text, row_marks(row))`, which keeps
   the text whole or withholds it whole (plain.py:19-42), plus
   `fence.quarantine` and `fence.sanitize` for instruction-like echoes
   (fence.py:62-94) [P "the validator's money filter misses common forms"].
10. **English only, caps:** note 140, mind 300 (constants.py:225-226).
11. **A bounded next_wake** (§2.1 i).

**(c) Refusals.** Journal kind `refusal` (constants.py:25), mode `refused`
(constants.py:388-389).
- Count each refusal: `OrcGrade.n_refused` (models.py:281) and the
  invalid-output rate.
- Validator refusals are "counted elsewhere, never a fault"
  (tribunal.py:54-55).
- DECIDE how many refusals send the Orc to the care [P].

**(d) The officer, in would-mode.** "mandate.allowed_actions replaces
allowed_actions_l0 (the seat, the commission, the switches and the hazards of
§3.1)" (integrity.py:19-21). "the mandate's officer (orcs/mandate.py, O2)"
(playbook.py:25-27). The army types' "mandate parameters act from O2 (shadow)"
(army.py:11-12, :35-54).
- ADD `mandate.py`, which computes what each intent WOULD be allowed, cut or
  refused if it were binding. Its inputs:
  - §2 numbers (constants.py:69-74), `GROSS_MAX_R` (constants.py:381-383);
  - the gap waiver (gaps.py:74-91);
  - the type's `risk_share_max`, `waiver_floor_r`, `gap_min_samples`,
    `add_pre_shut_h`, `exotic_adds` (army.py:35-54).
- Record the verdict on the intent. Every seat stays L0, so nothing binds
  (notes.py:287-290).
- [P would-mode: I3c costs, I4 cuts instead of refusing, I12 counters with no
  writer.]

### 2.5 Store the plan and the intents in shadow

**(a) The plan.** ADD:
- write `Orc.plan` (JSON: clauses on level ids and R, triggers, the
  expectation), `plan_version` (+1 per change) and `plan_changes_24h`
  (models.py:83-85);
- a journal entry of kind `plan`, author `orc` (constants.py:22-31), carrying
  `wake`, `model`, tokens, cost and `block_hashes`;
- `notes.plan_line` renders it with `format_price` (notes.py:507-510; today
  `PLAN_NONE`, notes.py:171), and PS3 shows it.
- KEEP: no care code reads `Orc.plan`. `position_care.plan(orc=)` arrives with
  O3 (ghost.py:63-64).

**(b) Intents.** ADD `OrcIntent` in O2's migration. bot_program/migrations ends
at 0046 on main; PR82 brings 0047 and 0048.
- Suggested fields: orc, wake, kind, candidate, level_id, the stop level the
  officer read, facts_cited, mode (shadow or refused), why, the officer's verdict,
  status (queued, simulated, expired [P C17 staleness]), created_at,
  expires_at, and the grade's link.
- `notes.slot` already has `"intents": []` (notes.py:545). The page says
  `NO_INTENTS` (dashboard/views_orcs.py:38).
- `OrcActionGrade` is the per-intent grade table (models.py:7-9) DECIDE: O2a or
  later.

**(c) Journal entries.** Kinds `decision` (one per answer), `plan`, `intent` and
`refusal`; `budget` and `error` for the call; `takeover` and `return` for the
care (constants.py:22-28). Each entry is written through `journal.append` with
`remember` and `fields` under the Orc's one lock (journal.py:17-70). The card
refreshes in the same transaction (notes.py:103-134).

**(d) The Orc's columns O2a writes.**
- `latest_note` and `latest_note_at`: the model's note, fenced and filtered.
- `last_wake_at` and `last_good_wake_at`.
- `last_facts_hash`: on a validated answer only. F6 must then read it
  (wake.py:46-47, :761-763). Otherwise a wake refused for budget makes the next
  metronome "quiet" on facts no model saw.
- `next_wake_due` (§2.1 i), the day counters (§2.1 d), `state`,
  `care_owned_reason` and `care_owned_at` (§2.1 h).
- `watches`: the plan's watched levels, so W3 can watch them
  (models.py:94; wake.py:200-229 reads only the thesis's `close_beyond` levels)
  [P "W3 ignores the plan's trim and add-trigger levels"].
- The facts hash must cover the plan version (wake.py:123-138) [P].

**(e) Grading the shadow.**
- The O arm `orc_shadow` records the REAL row tick by tick (ghost.py:12-18,
  :988-1071). In O2 the real row is the care's, so today's Δ against the care
  measures the care ghost, not the Orc ("SEATS_NOTE",
  dashboard/views_orcs.py:39-41; COMPARE, notes.py:176-177).
- Three existing mechanisms grade a shadow decision with no new pricing:
  - the hand-act transition `_to_shadow` (ghost.py:947-962), from the previous
    tick's record "as the care would";
  - `_care_step(extra_stop=..., extra_why=...)`, how the playbook arm applies its
    own stop (ghost.py:760-819, :911-916; `orc_stop` in its state, ghost.py:321);
  - `first_divergence` (ghost.py:1058-1065).
- Every price goes through pricing.py (pricing.py:1-24).
- DECIDE the moment an intent takes effect. The dossier is rendered as of the
  wake's detection (`components.as_of`, wake.py:705), then the wake waits for
  the render pass (up to 2 min), the queue and the model. The mark the
  integrity verdict judged fresh (120 s, I10) is stale by the answer. A shadow
  intent must take effect at the first tick after the answer is validated, and
  be priced there by pricing.py, never at the dossier's moment. That keeps the
  O arm on the same marks as the care ghost (ghost.py:1-4) and grants no
  look-back.
- KEEP: `metadata["orc_exit"]` on the ROW marks a BINDING Orc exit
  (ghost.py:1328-1330). O2a must never write it, nor any `DROP_META` key
  (`orc_stop`, `effective_stop`, `trail_owner`, ...) on a row (ghost.py:99-102).
- `OrcGrade.n_wakes`, `n_llm`, `n_actions` and `n_refused`, plus the rates
  (models.py:276-281), are never written: ADD.

**(f) Shadow by construction.** These guarantees hold today. O2a keeps them and
adds a test that proves each one.
- (1) The tick ignores `after_care` (asset_engine/base.py:1398-1409).
- (2) No order-path module imports `bot_program.orcs` beyond `observe`,
  `birth.ensure_on_commit` and `thesis.complete_provenance`
  (asset_engine/base.py:1403, :2325, :6763; asset_engine/runner.py:404).
- (3) The new modules carry the FORBIDDEN-identifier pins and no AssetBotTrade
  write.
- (4) `Orc.stop_level`, `stop_why`, `stop_at`, `trail_owner`, `lock_waiver` and
  `be_swap_floor` (models.py:86-93) are binding powers (O3 and later): O2a must
  not write them.

### 2.6 The command `manage.py orcs`
- Today: `status`, `adopt [--open --user --yes]`, `shadow-audit`, `actuals`,
  `dossier ROOT [--wake N]` (management/commands/orcs.py:1-35, :48-68). The ops
  page lists the same lines (core/ops_commands.py:140-152).
- ADD:
  - `status` shows the minds switch, `spend.lines_summary()` (spend.py:297-325)
    and the model calls today;
  - `dossier` shows S, the answer and the validation;
  - `smoke --row ROOT_ID`, "§10.2's `orcs smoke --row` (O2)"
    (ai_agents/management/commands/claude_smoke.py:33).
- Any subcommand that sends a call is dry by default. `--yes` must be refused
  while the switch is OFF, must ask `can_spend(line="orcs")` for the whole bound,
  and must cap the rung [P: the lost `orcs record --yes` took any rung, ran with
  the switch OFF and never asked the line].

### 2.7 Tests O2a changes on purpose, and the ones it adds
- tests/orcs/test_orc_source_pins_o1c.py:69-74 pins no `status="pending"` in
  wake.py. Rewrite it as "pending only from the dispatcher, never in the tick".
- tests/orcs/test_orc_source_pins_o1c.py:18-21, :32-39: keep them for the O1c
  modules. Add pins for the mind and mandate modules.
- tests/orcs/test_orc_models.py:57-65 pins exactly the O1 tables and no O2 table;
  :23-46 pins migration 0044. Extend both for O2's migration.
- tests/orcs/test_orc_census.py:33 ("no orcs glob before O2") and
  tests/orcs/test_orc_tasks_o1b.py:2: change them when the `orcs` queue ships.
- tests/orcs/test_orc_wake_detect.py:81 and test_orc_wake_memory.py:380
  (`("skipped", "no model before O2")`): still true with the minds switch OFF;
  add the ON case.
- The hard-rule-1 tests (test_orc_switch_off*.py, test_orc_tick_off.py,
  test_orc_seen_off.py): extend them to the minds switch.
- tests/test_model_catalog.py:456-525 (no model id literal) and
  tests/test_ai_spend_lines.py (the line off at 0) must stay green as they are.
- ADD a fake model provider for tests/orcs: `complete(**kw)` returns
  `(json_text, usage)` and records the kwargs it saw. tests/orcs/helpers.py has
  none; other suites write their own (tests/test_monday_plan_visible.py:95-104).
- ADD a no-network guard. Neither exists today [P "the zero-call proof is weaker
  than it looks"].

### 2.8 Words that become false when the minds switch is ON
Every one stays true with the switch OFF, so they must read the switch.
- constants.py:354, :356-357: "no model before O2", "recorded only: no model
  before O2".
- wake.py:81 `RUNG_O1` "no model (O1: code only)"; wake.py:774-776 "Recorded
  only: no model is asked yet."
- notes.py:141 "Watching: a journal written by code, no model."
- notes.py:171 `PLAN_NONE`; notes.py:176-182 COMPARE and NEXT_WAKE "detected and
  recorded only, no model"; notes.py:184 `RUNG_NONE`.
- notes.py:441: `_intellect` hard-codes `RUNG_NONE` and ignores the card's
  `rung_t`.
- surfaces.py:35-36 `QUESTION_LATER` (Q&A is O2d); surfaces.py:45
  `MODEL_CALLS = "Model calls today: 0"`.
- dashboard/views_orcs.py:38-41 `NO_INTENTS`, `SEATS_NOTE`.
- templates/dashboard/ai_models.html:153-156 "No Orc runs today."
- core/platform_control.py:323-324 "Orcs (journals, no model)".
- deploy/RUNBOOK.md:1275, :1285, :1310, :1520, :1527.

---

## 3. Reserved fields and tables

"Never written" means no writer outside models.py and the migrations, checked by
a grep of bot_program/, dashboard/ and core/.

### 3.1 Orc (models.py:44-134)
| field | line | today | O2a |
|---|---|---|---|
| state: active, care_owned, reentry_window | 63; constants 8-16 | only born and dead are written | active and care_owned (reentry_window is O5) |
| commission: reduce, trail | 64; constants 33-37 | advise or class at birth | no (PIN commissions: O4a) |
| stood_down | 65 | read by notes.py:532 | no (O4a) |
| hand_hold_until | 66 | never read or written | no |
| captain_may_cut | 67 | never read or written | no (Captains: O2c; binding: O3+) |
| last_step_tick | 68 | never read or written | no (binding steps) |
| adds_used, reentries_used | 75-76 | read by PS4 and lifecycle.py:72 | no (O3, O5) |
| attempt, reverse_of | 77-80 | never written | no (O5, L4) |
| plan, plan_version, plan_changes_24h | 83-85 | never written | YES |
| stop_level, stop_why, stop_at | 86-89 | never written | NO (binding stop, O3) |
| trail_owner, lock_waiver, be_swap_floor | 90-93 | never written | NO (L2, L3 powers) |
| watches | 94 | never written | YES (plan levels for W3) |
| latest_note, latest_note_at | 97-98 | quiet readings only | YES (the model's note) |
| last_wake_at, last_good_wake_at | 99-100 | never written (wake.py:47) | YES |
| next_wake_due | 101 | the metronome | YES (+ the validated next_wake) |
| last_facts_hash | 102 | never written (O1 uses the `seen["answered_hash"]` proxy) | YES |
| llm_wakes_today, routine_wakes_today | 103-104 | never written | YES |
| spend_today_usd, routine_spend_today_usd | 105-109 | never written | YES |
| care_owned_reason, care_owned_at | 110-111 | never written (reason read by notes.py:533) | YES |
| index orc_next_wake | 126 | metronome only | dispatcher scan |

### 3.2 OrcWake (models.py:156-187)
- `status`: default "pending" (166); O1 writes skipped and quiet. O2a adds the
  rest (§2.1 b).
- `model` (167): never written. O2a writes the model that answered.
- `est_usd` (168-169): never written. O2a writes the estimate and reservation.
- `skipped_reason` (170): one O1 value. O2a writes codes.
- `started_at` (171): never written. O2a writes the claim time.
- `finished_at` (172): render writes the as-of moment (wake.py:757). O2a writes
  the answer's time and keeps the render time in components.
- `priority` (164): 1.0 or 0.0, frozen at record. O2a uses it as the triage key
  and recomputes it on absorb [P].
- `kind` (165): birth, routine or material. `confirm` is named by F1
  (complexity.py:266-267), `orc_confirm` (views_ai_models.py:98) and D30, but
  never written. DECIDE whether O2a runs confirm wakes in shadow.
- `dedupe_key` (163) and the constraint `orcwake_one_pending_per_key`
  (180-185): designed for dispatch (§2.1 c).

### 3.3 OrcJournal (models.py:190-221)
- `model`, `tokens_in`, `tokens_out`, `cache_read`, `cache_write`, `cost_usd`
  (206-211): never written. O2a writes them on model entries.
- `author` `orc` and `captain` (AUTHORS, constants.py:30-31): never written
  today.
- The kinds decision, plan, intent, refusal, action, takeover, return, captain,
  question, answer, postmortem, budget, error, breach, temperament, rank,
  heritage, scar and emperor (constants.py:22-28): never written today.
  O2a uses decision, plan, intent, refusal, takeover, return, budget and error.

### 3.4 OrcGrade (models.py:245-287)
- `ai_cost_usd` (252): always 0 (grading.py:181). `orc_r` and `net_edge_money`
  are computed with no AI cost (grading.py:12-14, :57-84).
- `expectation_hit_rate`, `flipflop_rate`, `n_wakes`, `n_llm`, `n_actions` and
  `n_refused` (276-281): never written. `tags` (275) is always []. `seat_block`
  (272) is always None (seats: O2d).

### 3.5 Other tables
- **OrcSeat** (models.py:21-41): `level` is always 0, `status` "active".
  `pinned`, `reason`, `model_routine`, `model_decisive` and `stats` are never
  written (`stats` is read by notes.py:473 and dashboard/views_orcs.py:139-140).
  The seat's models are an O2b concern.
- **OrcSetting** (models.py:290-310): "the budget keys from O2" (292-293).
  Keys in use: max_paper_orcs, drum_factor_map, token_factors,
  calendar_actuals. ADD the O2a budget keys (per-Orc dollar cap, the reserve
  share, ...).
- **OrcDayBaseline** (models.py:331-348): `caps` is display only,
  `frontier_quota` and `routing_version` are written (weather.py:186-219). The
  router (O2b) and the per-Orc caps (O2a) read them. Trap in §2.1 d.
- **OrcDrum** (models.py:351-380): `reach` and `routed_at` are written. W12 and
  waves (OrcWave) are O2c (drum_bus.py:41-44).
- **OrcDossierBlock** (models.py:313-328): O2a stores S here.

### 3.6 The card and the slot (Orc.card; notes.py)
- `card.intellect` = {score_v, score_t, band, day_class, rung_t, status_t,
  escalated: False, late: False, at} (wake.py:765-771).
  - `rung_t`, `escalated` and `late` wait for the router (O2b).
  - `notes._intellect` overwrites `rung_t` with `RUNG_NONE` (notes.py:431-442),
    so O2a must change it.
- `slot.intents = []` (notes.py:545).
- `slot.lineage`: white_hand False, probation_t "", scars [], breaches_t "",
  disbanded False (notes.py:471-485). These belong to O2c and O2d.
- `slot.authority.care_owned_reason` (notes.py:533).

### 3.7 The O2 tables (none exists)
- From tests/orcs/test_orc_models.py:17-20: OrcIntent, OrcActionGrade, Captain,
  CaptainOrder, OrcWave, OrcBattle, OrcLesson, OrcWeapon, OrcTierGrade,
  OrcTemperamentGrade.
- From models.py:7-9: "OrcIntent, OrcActionGrade, Captain, CaptainOrder and the
  2026-10-09 additions marked O2".
- For O2a: OrcIntent, and possibly OrcActionGrade. OrcTierGrade belongs to O2b;
  Captain, CaptainOrder, OrcWave and OrcTemperamentGrade to O2c; OrcBattle,
  OrcLesson and OrcWeapon to O2c or O2d (see map_army.md).

### 3.8 Orc.seen keys O1 uses (no collision)
- Wake memory: w1, w2_bar, w3_at, w11_at, wake_keys, wake_once, wake_pending,
  last_recorded, band, band_hold_until, answered_hash, book_state.
- Other memory: predicates, drum_waves, drum_seq, fact_seq, birth_seq,
  level_at_birth, menu_source, care_stop, venue_stop, venue_refused, hand_at,
  event_at, scaled_out, care_close, thesis, review_id, venue_missing_at,
  venue_crossed_at, venue_said_open_at, venue_unlisted, pending, closed_legs,
  provenance_completed, audited.
- Sources: wake.py:667-690; facts.py:186-220; journal.py:14; drum_bus.py:665;
  predicates.py:303-372; birth.py:332, :343-344; thesis.py:284-296;
  grading.py:239-242.

---

## 4. Every "O2" comment, file:line

### 4.1 bot_program/orcs/ and the command
- wake.py:43-44 — the status reads skipped ("no model before O2") or quiet
  under F6.
- wake.py:46-47 — detection, spacing and the answered-hash proxy live in
  `Orc.seen`, "never in O2's columns (last_wake_at, last_facts_hash)".
- wake.py:54-55 — `# O2: a recorded wake is dispatched (status pending, the
  router, the reserve, the budget) instead of skipped; drum deliveries add W12.`
- observe.py:76-78 — "no model; the dispatch is O2's".
- tasks.py:4-6 — the slow queue "until O2's worker and its `orcs` queue exist".
- complexity.py:10 — "routes NOTHING (the router is O2's)".
- weather.py:6-9 — the caps are display only; "the dollar caps arrive with the
  router, O2".
- constants.py:8-9 — "active, care_owned and reentry_window arrive with the
  wakes (O2) and the re-entry (O5)".
- constants.py:227-232 — V10: "The I3 facts of an add arrive with the mandate
  (O2). Enforced by the validator from O2".
- constants.py:351 — "OrcWake.status values O1 writes (no `pending`: dispatch is
  O2's)".
- constants.py:354, :356 — `WAKE_SKIPPED_REASON` and `STATUS_WORDS["skipped"]`.
- models.py:7-9 — the tables only O2 writes ship in O2's own migration.
- models.py:290-293 — OrcSetting: "the budget keys from O2".
- dossier.py:5 — "S the doctrine (O2; reserved in the size cap:
  S_TOKENS_RESERVE)".
- dossier.py:409-410 — PS5 notes: "— (no note: the Orc writes none before O2)".
- dossier_position.py:16 — PS3: "no plan yet: the Orc writes one from O2".
- dossier_position.py:24 — "PS9-PS11 dashes until O2".
- dossier_position.py:26 — PS12: "continuation odds: O2".
- dossier_position.py:38 — `PS3_WORDS`.
- dossier_position.py:299-304 — `# O2: PS9 the temperament's lead voices and lane
  texts (§4.6), PS10 the lessons and weapons of the lineage (§6.10-6.11), PS11
  the Captain's orders and the Emperor's theme orders (§4.2, §4.6).`
- dossier_position.py:355-356 — `# O2: continuation_odds
  (backtester/proving/memory.py, §5.2)`.
- dossier_market.py:34 — `# O2: MK-E carries the Emperor's daily order (§4.6)`.
- dossier_market.py:260-261 — "the Emperor's daily order replaces the dash once it
  lands (OrcJournal kind "emperor"); MK0's bytes never change for it".
- fence.py:23-24 — `# O2: the validator enforces v10_satisfied on every binding
  non-hold action; O1 ships the table and the check.`
- integrity.py:19-21 — `# O2: mandate.allowed_actions replaces
  allowed_actions_l0 (the seat, the commission, the switches and the hazards of
  §3.1)`.
- integrity.py:33 — "Risk-adding kinds wait for the mandate's officer (O2)".
- integrity.py:37-39 — "add, re-entry, BE-swap, widen and reverse: the mandate's
  officer arrives with O2".
- playbook.py:3 — "the candidate menu a wake will see (O2)".
- playbook.py:25-27 — A-CONFIRM, R-RECLAIM, V-REVERSE and W-WIDEN "need the
  mandate's officer (orcs/mandate.py, O2)".
- predicates.py:36-38, :351 — `# O2: wake.request(orc, "W8", urgent=True)`.
- drum_bus.py:41-44 — drum wakes (W12, urgent per `_urgent_for`, gated by
  `orcs_drums`), waves (OrcWave), the breaker, the wave stamp on intents and
  stops; a stop placed from a drum wake carries the wave, and its hit inherits
  hop + 1.
- drum_bus.py:85-86 — `drums_on()` "Read by nothing in O1: drum wakes are O2's".
- drum_bus.py:219-220 — `# O2: a stop placed from a drum wake carries its wave;
  its hit inherits the wave and hop + 1`.
- drum_bus.py:582-585 — `_urgent_for` "O2's (a drum wake); called by nothing in
  O1".
- drum_bus.py:666-667 — `# O2: a delivery adds W12 to the receiver's pending
  wake (urgent per _urgent_for), gated by orcs_drums`.
- grading.py:28-30 — "seats are computed in O2, in shadow".
- tribunal.py:3 — "the council's words (the model call) arrive with O2".
- tribunal.py:47 — "binding breaches written by the audits or G13 (O2), never
  refusals".
- ranks.py:6-7 — "O2 adds the record a rank is earned on (n of 20, the
  provisional and coin-toss qualifiers) and the White Hand mark".
- army.py:11-12 — "mandate parameters act from O2 (shadow) and O3 (paper)".
- army.py:236-239 — "Uruk-hai is unreachable until the ranks (O2) and the
  operator's PIN exist".
- notes.py:32-33 — "the plan line, the intents, temperament, honor and the
  lineage's record are O2's".
- notes.py:507-510 — `plan_line`: "O2: the model's plan, rendered by code (prices
  through format_price)".
- notes.py:688-689 — `for_rows`: "O2: a third, the lineages' scars and breaches".
- notes.py:750-753 — `for_classes`: "no Captain is seated before O2. O2: the
  Captain, its orders, the open waves, the fallen and the Emperor's line".
- surfaces.py:15-18 — "/orc N <question>" (O2 answers it).
- management/commands/orcs.py — no O2 mention. Its docstring says "O1: journals
  of code facts, no model" (line 1).
- Boundary marks beyond O2: ghost.py:63-64 (O3: `plan(orc=)` and the effective
  stop); notes.py:287-290 (O3/O4a `effective_level`); notes.py:689 (O5); lifecycle.py:14-15,
  :77 (O5 re-entry); surfaces.py:18 (O4a stand down); constants.py:164-166 (O3
  trail ownership and waivers).

### 4.2 Outside the package
- config/celery.py:96 — "No orcs.* glob: the `orcs` queue and its worker arrive
  with O2".
- config/celery.py:100-101 — "by exact name until O2 ships the `orcs` queue and
  worker-orc".
- core/platform_control.py:328-331 — `orcs_drums` "INERT: drum wakes (W12) are
  O2's"; its name "Orc War Drums (wakes from O2)" and its description.
- ai_agents/spend.py:17, :24, :66, :80 — the Orcs line "from O2", "off until O2
  turns it on", "O2 turns it on".
- ai_agents/catalog.py:502-504 — "The router (O2) reads its own versioned copy and
  never the tier resolver".
- ai_agents/management/commands/claude_smoke.py:1, :33 — "what O1 and O2 need";
  "this is not §10.2's `orcs smoke --row` (O2)".
- dashboard/views_ai_models.py:91, :95 — "pinned ladder (... versioned from
  O2)", "No Orc calls a model before O2".
- dashboard/views_ai_models.py:230 — "the Orcs' line (off until O2)".
- templates/dashboard/ai_models.html:154-156 — "read by the router from O2 ...
  stays off until O2 ... No Orc runs today".
- deploy/RUNBOOK.md:1275, :1285, :1310, :1520, :1527, :1592.

### 4.3 Tests that pin an O2 boundary
- tests/orcs/test_orc_source_pins_o1c.py:5, :69-82;
  tests/orcs/test_orc_models.py:17-20;
  tests/orcs/test_orc_census.py:33;
  tests/orcs/test_orc_tasks_o1b.py:2;
  tests/orcs/test_orc_wake_detect.py:7, :81;
  tests/orcs/test_orc_wake_memory.py:380;
  tests/orcs/test_orc_drums.py:5, :349-350;
  tests/orcs/test_orc_dossier.py:340, :372, :547;
  tests/orcs/test_orc_army.py:6;
  tests/test_ai_spend_lines.py:1;
  tests/test_model_catalog.py:421;
  tests/test_claude_smoke.py:3;
  tests/test_the_book.py:2230.

---

## 5. Every rule the code names, and what it says

### 5.1 W, the wake reasons (wake.py:1-34, constants.py:306-328)
- **W1** — the first detect after the birth. Urgent (wake.py:9, :372-373).
- **W2** — a FINAL venue bar of the decision timeframe: a Mercenary's 1h, else
  the thesis's structure timeframe, 4h by default; only after W1
  (wake.py:10, :163-175; dossier.py:187-197).
- **W3** — the closing-side mark within `W3_NEAR_ATR1H = 0.1` × ATR(1h) of a
  thesis `close_beyond` level. Urgent. Again for that level only
  `W3_ONCE_H = 4` hours after its last W3, never on a clock bucket
  (wake.py:11-12, :200-229; constants.py:325-328).
  - The mark is the closing side: a fresh venue stamp, else the tick's bid or
    ask, else the price (wake.py:178-197).
- **W4** — +1R, +2R, +3R first reached on the best excursion; −0.5R and −0.75R
  on the worst of (now, MAE, 0), urgent; the give-back to
  `W4_GIVEBACK_SHARE = 0.5` of the best after +1R. Once for life
  (wake.py:13-14, :232-243; constants.py:308-311; ONCE_CODES wake.py:85).
- **W5** — census.
  - T−180, T−60 and T+15 around a high-impact print on the row's currencies.
    T+15 fires at most `W5_LATE_MIN = 60` minutes late.
  - A stock's or ETF's own earnings at T−24h; the ticker must be the row's own,
    matched as a word.
  - One reason per event: the nearest offset; the farther ones are spent.
  - Urgent. Code words only, no calendar title (wake.py:858-943;
    constants.py:312-316).
- **W6** — the care moved its stop; the venue refused the stop; the care closed
  the position, urgent and once, key `W6:closed` (wake.py:15-16, :246-256).
- **W7** — census. The daily-loss mode changed; open risk crossed
  `W7_OPEN_RISK_SHARE = 0.8` of its limit; the measured posture's level changed.
  - A term is compared only when it is readable now and was readable before; the
    first reading is silent.
  - The book is read in the Orc's own money world; a demo Orc has none.
  - Not urgent (wake.py:946-1001; constants.py:323-324).
- **W8** — a predicate met, urgent; the thesis check turns to exit, not urgent
  (wake.py:17, :257-267).
- **W9** — a hand edit of the levels (wake.py:18, :268-270).
- **W10** — a close in doubt, an entry in doubt on the symbol, inert stop rules.
  Urgent, once (wake.py:19, :273-293). Census: a close pending at the venue on
  any leg, urgent, once (wake.py:1004-1016).
- **W11** — the metronome: every `W11_METRONOME_H = 4` hours while the market is
  open; a stock or ETF at the open + 60 min and the close − 90 min; 2 h before a
  weekend. Only after W1. Nothing while the market is shut
  (wake.py:20-21, :296-330; constants.py:317-322).
  - The Mercenaries' `metronome_h = 1.0` and the Olog-hai's 24.0 are written
    (army.py:43, :90-98) but not applied: W11 uses the constant 4 h.
- **W12** — a drum delivery (O2c seam; wake.py:55, :544-546; drum_bus.py:41-44,
  :666-667).
- **Wake mechanics:**
  - Each reason counts once per key. The one-shots W4, W10 and `W6:closed` live
    in `seen["wake_once"]`, never trimmed. The time-keyed ones live in the last
    `WAKE_KEYS_KEPT = 200` of `seen["wake_keys"]` (wake.py:22-30, :85-86;
    constants.py:306-307).
  - Urgent reasons record at once; the others wait `MIN_WAKE_SPACING_MIN = 15`.
  - After an urgent wake the band may rise but never fall for
    `BAND_HOLD_AFTER_URGENT_MIN = 60` (complexity.py:287-308; wake.py:678-680).
  - Kinds: birth (W1), routine (only W2 and W11), material (anything else)
    (wake.py:628-634).

### 5.2 F, the floors and filters (complexity.py, integrity.py)
- **F1** — a `confirm` wake is at least complex on real money, material on paper
  (complexity.py:266-267).
- **F2** — a real-money birth is at least complex (complexity.py:268-269).
- **F3** — a binding action on the table with real money is at least material
  (complexity.py:270-271). `binding_on_table` is always False today
  (wake.py:735-736).
- **F4** — as coded: binding, real money and a stormy day give "material", the
  same as F3, so it adds nothing (complexity.py:272-273). Trap: the lost spec's
  F4 may say more.
- **F5** — set only by the integrity verdict's three CRITICAL items:
  - the mark: on a real row the venue's own mark, at most `MARK_MAX_AGE_S = 120`
    s old (I10); on paper its venue's quote;
  - the decision frame's venue bars, no older than two bar lengths of open market;
  - the row's own state, readable.
  Under F5 the menu loses every R3-R6 kind, and X-THESIS, K-DRAW, P-TRIM and
  P-HOLD drop. What stays: hold, revise_plan, and tighten on a fresh mark only.
  Every other stale input only prints a dash (integrity.py:1-17, :51-133;
  complexity.py:236-239).
- **F6** — quiet: every reason a W2 or W11, and the facts hash unchanged since
  the last answered wake. The hash covers R in quarter-R buckets, the menu's
  level ids, the PO3 phase, the calendar's hour, the thesis verdict and the
  predicates. A quiet wake gets a code reading and `latest_note`
  (complexity.py:242-249; wake.py:123-138, :785-789).

### 5.3 V, the validator
- **V10** — "the T0 fact kinds that may justify each action kind"
  (constants.py:227-241; fence.py:169-204). Enforced by the validator from O2.
  - exit, trim, tighten: bar, structure, predicate or care facts on this symbol.
  - lock_waive: gap or calendar facts of the named event.
  - add, reenter: structure or bar facts on this symbol, plus the I3 facts (O2's
    mandate).
  - plan or revise_plan: any T0 fact newer than the current plan.
  - hold or note: nothing.
  - "army" and "arm" facts never satisfy it (fence.py:33-37).
  - Failure text: "... cites no T0 fact of its set (...): advisory to the
    phone".
- V1-V9, V11 and later are not in the code. V6 is named only in the recovered
  notes (§5.10).

### 5.4 I, the mandate items (§2.2)
- **I2** — the idea's gross risk cap, `GROSS_MAX_R = 2.0`, printed in the risk
  line; no mandate binds in O1 (constants.py:381-383; notes.py:173, :339-351).
- **I3** — the facts an add needs, which arrive with the mandate in O2
  (constants.py:230-231).
- **I3 h** — the gap model. An add or a lock waiver leaning on an UNMEASURED gap
  (< `GAP_MIN_SAMPLES = 8` samples, 12 for the Corsairs) is refused. The waiver
  needs the worst case at the stop less the gap's p90 to stay ≥ −0.5R (−0.3R
  for the Corsairs) (gaps.py:1-20, :74-91; constants.py:69-74, :109-111).
- **I7** — a re-entry needs an L3 seat (`REENTRY_MIN_LEVEL = 3`); it arrives with
  O5 (lifecycle.py:30-31, :66-77).
- **I10** — the venue mark's freshness, 120 s (integrity.py:5-7;
  constants.py:258).
- **I11** — a stop needs ≥ `MIN_STOP_ROOM_ATR = 0.5` × ATR(tf) of room on both p
  and m, and sits ≤ `MAX_LEVEL_DIST_ATR4H = 3.0` × ATR(4h) from m; an Orc names
  levels by menu id (constants.py:115-119; menu.py:1; integrity.py:12-13).
- The §2 numbers a type may only tighten: `MAX_ADDS = 2`, `RISK_SHARES = (0.5,
  1.0)`, `ADD_PRE_SHUT_H = 6`, `EVENT_WAIVER_FLOOR_R = -0.5`,
  `GAP_MIN_SAMPLES = 8` (constants.py:69-74). Line adds at half size
  (constants.py:107-108).

### 5.5 D, the decisions
- **D2** — the basis fallback. With no fresh venue frame, platform levels are
  shifted by (mark − the last 1h platform close) and labelled "basis-shifted".
  Their structure levels are dropped unless the last `BASIS_SAMPLES = 10` hourly
  samples sit within `BASIS_UNSTABLE_ATR1H = 0.25` × ATR(1h); fewer samples
  fail closed (constants.py:176-180; menu.py:19-24, :129-142; playbook.py:1).
- **D9** — a bar before the birth never meets a predicate (forward only)
  (tests/orcs/test_orc_predicates.py:243; predicates.py:17-18, :305-312).
- **D18** — the Orcs' line example: cap $13, total $27
  (tests/test_ai_spend_lines.py:181). The recovered notes also call the per-Orc
  cap "D18" [P].
- **D21** — MK is sized per model family at build time: headlines 6 → 4 → 3, and
  the per-wake trim touches uncached parts only, in TRIM_ORDER
  (constants.py:221-222, :277-304; models.py:323-325).
- **D30** — inside the Orcs line, a live urgent or confirm wake is exempt from
  the 70% deep-tier share; the exemption is the caller's (spend.py:34-36,
  :216-218, :267-272; tests/test_ai_spend_lines.py:258).

### 5.6 C
- **C18** (the Horde spec) — the rank's key is `lineage`, never `seat`
  (notes.py:28).
- The smoke's C1-C3 (ai_agents/management/commands/claude_smoke.py:7-24):
  - C1: the dossier's token counts on each tokenizer;
  - C2: call A in the spec's layout (S cached 1 h; the shared turn, the last MK
    block 1 h, IN-slow 5 min; the effort-only message at low; the private turn
    uncached; structured output; no fallback);
  - C3: call B, the same request with only the effort message at xhigh.
  PASS needs B to read the cache, B's output to be at least twice A's, both to
  stop at end_turn, and both answers to validate.
- C14 and C17 are named only in the recovered notes (§5.10).

### 5.7 G
- **G8** — Morgul's duplicates guard, the one reader of `metadata["orc"]` outside
  the Orcs (notes.py:16; bot_program/morgul.py:38-39).
- **G13** (O2) — "binding breaches written by the audits or G13 (O2), never
  refusals" (tribunal.py:7, :47). Morgul's guards end at G12
  (bot_program/morgul.py:20-41).

### 5.8 The dossier's sections (dossier.py:1-25 and the dossier_* modules)
- **S** — the doctrine; O2; reserved at 3,930 tokens.
- **MK, the market day** (dossier_market.py:5-32):
  - **MK0**, at the roll, immutable for the day:
    - MK1 the day header (sessions, the classes shut, crypto 24/7, the board);
    - MK5 the macro line (FRED: VIXCLS, BAMLH0A0HYM2, DGS2, DGS10, T10Y2Y;
      VIX/VIX3M);
    - MK6 today's and tomorrow's high-impact prints;
    - MK9 the long view (the Horizon);
    - MK10 and MK11 as dashes ("the council has not sat").
  - **A closed session's block** (once its last 1h bar is final, immutable):
    - MK2 the 11-symbol board in the ICT window;
    - MK3 the regime clock;
    - MK4 the posture at its close;
    - MK7 the Mind;
    - over its span: the prints that landed, MK8 the brief, MK12 headlines
      (6 → 4 → 3, ≤ 900 tokens).
  - **MK-E**, the Emperor's line, its own block (O2c).
  - **MK-now**, in the tail: the session, the prints since the last close, the
    Mind and the brief, new headlines, the board's live move, the user's
    correlation clusters (|rho| ≥ 0.7), the book as shares, never money.
- **IN, the instrument** (dossier_instrument.py:1-24):
  - **IN-slow**, per (symbol, final 1h bar, family):
    - IN1 the frames (1h × 120, 4h × 60, 1d × 60) as integer rows in
      0.1 × ATR(1h) around an anchor;
    - IN2 the structure per frame;
    - IN3 the menu's levels and the floor pivots;
    - IN5 the positioning; IN6 the COT; IN10 the gap model.
  - **IN-today**, in the tail:
    - IN4 PO3 today;
    - IN7 the mark's source and age, the spread in ATR(1h);
    - IN8 the correlated instruments' moves with rho;
    - IN9 the symbol's headlines (24 h, 8 at most, fenced);
    - IN11 the next print and its gap;
    - IN12 the tape (15m since the Asia open, 5m for 2 h; a stale frame is
      `last_known`).
- **PS, the position** (dossier_position.py:11-27):
  - **PS1** you: L0 shadow, the commission, the allowed actions and why not, the
    army type, never a rank.
  - **PS2** the thesis and its money-free provenance, the debate's killer and edge
    as views, the operator's own thesis as a view.
  - **PS3** the plan (O2).
  - **PS4** the mandate: worst case, gross, loss, adds left, re-entry left, the
    book's headroom in R.
  - **PS5** the last 12 facts with their ids, plus notes (O2).
  - **PS6** the care: soft stop and why, effective stop, peak and worst, MFE, MAE,
    R now, the scale-out, the venue's stop and any refusal, the last 10 stop
    moves, Aragorn's last 5 actions.
  - **PS7** the reviewer's verdicts over 24 h (reasoning as a view, capped at 280)
    and the thesis check.
  - **PS8** the drums heard since the wake BEFORE this one.
  - **PS9-PS11** O2c.
  - **PS12** (tail) the menu (30 rows), the candidates (sorted by id, never ranked,
    after the F5 shrink), recovery odds under water only, continuation odds (O2).
  - **PS13** (tail) the integrity verdict (critical, contradictions, stale,
    missing; flag critical, contradiction, stale or ok). A PO3 read on the 4h
    fallback is a contradiction, never critical (dossier.py:383-389).
- **The tail** also carries the missing MK blocks, the reasons and what was
  trimmed (dossier.py:416-427).

### 5.9 Other named sets
- **The fence's bands** (fence.py:4-13, :155-166):
  - T0: code facts (F-n) and DR-n whose trigger is a price, stop, fill, lock or
    predicate; they may justify an action within V10.
  - T1: platform model prose inside `<view source=...>`, "may be wrong; facts
    win".
  - T2/N: third-party text inside `<untrusted kind= id=>`, never a justification;
    the `news_shock` drum is N.
  - Instruction-like text is withheld whole (fence.py:44-59, :80-89).
  - Code ids: F-n facts, DR-n drums, C-n calendar rows (wake.py:908-924;
    drums.py:192-196), N-n articles (drums.py:188-190), V-n views read as T1.
- **The reversibility ranks** (wake.py:97-100; constants.py:274-275): hold R0;
  revise_plan R1; tighten R2; lock_waive R3 (and P-HOLD); trim and exit R4; add,
  reenter and be_swap R5; widen_with_cut and reverse R6. Scores 0, 25, 40, 55,
  75, 90, 100, halved for a shadow-only candidate (complexity.py:194-201).
- **The seat levels and ranks** (ranks.py:10-18):
  - L0 Snaga: watches and writes, shadow only.
  - L1 Tracker: reduces (plan-clause exits, 4h tightens).
  - L2 Warg-rider: trail ownership, lock waivers.
  - L3 Standard-bearer: adds, the one re-entry.
  - L4 Chieftain: widens with a cut; reverses.
  - Provisional below `RANK_GATE_N = 20` graded ideas (constants.py:390-391).
- **Bands and day classes** (constants.py:244-247; complexity.py:277-331):
  - bands: routine < 30, material < 55, complex < 75, extreme from 75,
    hysteresis 5;
  - days: calm < 30, eventful < 55, stormy from 55, or a stressed, crisis or
    recovery posture (only while measured), or 3 high-impact prints today.
  - The complexity weights and breakpoints are at constants.py:260-272.
  - Stakes: real money +10, a hand idea +5, a wound +10 and L3+ +5, but
    wounded and level are never passed (wake.py:731) (constants.py:249-252).
- **The ladder's rungs** h0 and r0-r5 (ai_agents/catalog.py:505-519).
- **The day caps** (display only today) (weather.py:29-42):
  - model wakes a day: real 12, 14 or 16 by day class; paper 12;
  - frontier quota: 1, 2 or 4;
  - probes: on any day that is not stormy.
- **The playbook's candidate ids** (playbook.py:9-27, :143-182):
  - H-HOLD, T-CARE, T-STRUCT (from MFE ≥ 0.5R; 1h swings below +2R MFE, 4h
    from there);
  - K-DRAW (paper or two legs; the mark within 0.5 × ATR(4h) of the draw);
  - X-THESIS (a fresh "exit" within 24 h, or a met predicate);
  - P-LOCK, P-TRIM, P-HOLD (a print within 3 h; P-HOLD only if the waiver check
    clears).
  - Never listed: A-CONFIRM, R-RECLAIM, V-REVERSE, W-WIDEN.
- **The menu's ids** (menu.py:15-18, :303-345): S{tf}-L/Hk swings, P{tf}-L/Hk
  pools, SW{tf}-L/Hk sweeps, RC{tf}-L/H the recent extreme, RN-k round numbers,
  and the idea's rows BE, CARE and EFF.
- **The arms** (constants.py:155-162): care (G), playbook (P), orc_shadow (O),
  chandelier3, staged.
- **The modes** (constants.py:385-389): binding, shadow, refused. Every key that
  describes an act carries one.
- **Hard rules** (§11): rule 1, `orcs` OFF is byte-identical
  (tests/orcs/test_orc_switch_off*.py); rule 2, no order path, stop mover, model,
  token counter or row writer (tests/orcs/test_orc_source_pins_o1b.py,
  _o1c.py, _o1d.py).
- **Code-of-honor articles:** VI is PS13's integrity (integrity.py:1-2); IX is
  the fence (fence.py:1-2).

### 5.10 Rules named only in the recovered O2a notes, not in the code
All flagged [P]; the requirements are in map_pitfalls.md.
- "Rule 2": the plan-change rule, counted over 24 h.
- **V6**: an exit or trim that only names an unreached pool, and the missing
  `level_reached` fact.
- **V10**: must refuse, and be counted.
- **I3c**: costs in the add arithmetic.
- **I4**: cut instead of refuse.
- **I12**: steps_today, bars_since_add and bars_since_trim, which have no
  writer.
- **C14**: plan clauses against allowed_actions, F5, C14 and the type's
  risk_share (that finding was judged false).
- **C17**: staleness of queued shadow exits.
- **D18**: the per-Orc cap.
- The lost module names: `scheduler.py` (dispatch_due, run, census_stalled,
  census_silence, first_enqueued_at) and `orcs record --yes`.

---

## 6. Traps in the code O2a will hit
1. `dedupe_key` carries a timestamp to the second (wake.py:657-658), so the
   one-pending-per-key constraint (models.py:180-185) never merges an Orc's two
   wakes.
2. `render_wake` writes `finished_at` as the as-of moment (wake.py:757).
3. The render's `answered_hash` is written for every non-quiet wake, as a proxy
   (wake.py:761-763). With models it must follow a validated answer instead,
   and `Orc.last_facts_hash` is the column.
4. The render is for "sonnet" only (wake.py:728; dossier.py:360).
5. `notes._intellect` hard-codes `RUNG_NONE` (notes.py:441).
6. `BaseAgent.run` asks only the TOTAL and passes no blocks, schema, line or bound
   (base_agent.py:83-86, :134-148).
7. `can_spend` reads booked spend only (spend.py:149-154), so there is no
   reservation.
8. Its `estimated_usd` defaults to 0.05 (spend.py:208).
9. Its deep share binds only for tier "deep" or "frontier" (spend.py:268-269).
10. `ORC_LIVE_FLOOR_USD` protects the Orcs from the CORE line; it is not a reserve
    inside the Orcs line (spend.py:28-31, :82-84).
11. The spend day is UTC midnight (spend.py:143-146) while the weather's day rolls
    at 17:00 New York (constants.py:371).
12. The weather's caps sit on a (user, class) row whose `caps` came from the first
    reader's `real` (weather.py:160-219; tasks.py:177).
13. No code writes `bar`, `gap` or `level_reached` facts, so V10 cannot pass a
    reduce citing a bar, nor any lock waiver citing a gap (fence.py:35-37;
    constants.py:233-238).
14. The event-window fact's body holds the calendar title (facts.py:297).
15. The O1c pins forbid `ai_agents` in 18 modules
    (tests/orcs/test_orc_source_pins_o1c.py:18-21, :32-39), so the call needs its
    own module.
16. The models test forbids any O2 table (tests/orcs/test_orc_models.py:57-65).
17. `test_no_pending_wake_is_ever_written` (test_orc_source_pins_o1c.py:69-74).
18. No worker consumes an `orcs` queue (deploy/docker-compose.yml:163-175).
19. The task gate reads `skipped`, `parsed` and `attempted` as health verdicts
    (census.py:25-27).
20. W11 ignores the army type's metronome (army.py:43, :91, :98; wake.py:308).
21. F4 as coded equals F3 (complexity.py:270-273).
22. Stakes never get `wounded` or `level` (wake.py:731).
23. PS4's "loss" is a hard-coded +0.00R (dossier_position.py:169).
24. PS1's level is hard-coded "L0 shadow" (dossier_position.py:72).
25. `continuation_odds` and `wake.request` do not exist.
26. A model id literal anywhere outside ai_agents/catalog.py fails
    tests/test_model_catalog.py:495-525.
27. The thinking models' default bound is 32,000 tokens (ANSWER_TOKENS 8192 +
    THINKING_TOKENS; claude_provider.py:53-73), so an Orc call needs its own
    `max_tokens` to bound the worst case.
28. `claude_provider.complete(line=...)` only steers the client-side refusal
    re-run's budget question (claude_provider.py:405); billing follows the agent
    name and source_ref.
29. The tick's Orc hook runs on the fast worker inside every bot pass
    (asset_engine/base.py:1398-1409), so dispatch must never move into it.
30. A wake's dossier and its integrity verdict are as of its detection
    (wake.py:705, :716-728). By the time the model answers they are minutes
    old, so an intent must be timed and priced at the answer, not at the
    dossier (§2.5 e).
31. `dossier.context_for` reads `orc._orc_results` for the predicates; the
    render clears it first (wake.py:715), so the render reads the stored states
    in `Orc.seen`. A dispatcher that re-renders later reads the states as they
    are then, not as of the wake.
