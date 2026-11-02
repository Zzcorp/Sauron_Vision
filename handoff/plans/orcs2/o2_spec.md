# The Orcs, O2 "shadow minds": the spec

Rebuilt on 2026-11-01. The first O2 spec, its O2a build and the master Orcs
spec were lost in an environment reset. This spec is built from what
survives: the O0 and O1 code, and the recovered review of the lost O2a.

Revised the same day after a review by three lenses (shadow, cost,
completeness). Every blocking and important finding is applied, and every
minor one that is right. §5, the review log, gives one line for each
finding not applied as written, and for the one rule added beyond the
review (the PIN on the O2 switches, N2).

## How to read this spec

**Sources.**
- The code is the read-only checkout of main `9d74a19` at
  `/home/user/Sauron_Vision/.claude/worktrees/orcsread`. Every `file:line` is
  in that tree. A bare file name such as `wake.py` is under
  `bot_program/orcs/`.
- The four maps in this folder (full paths at the end):
  - `map_wakes.md`: the hooks O2a plugs into;
  - `map_ai.md`: the provider, the prices and the costs;
  - `map_army.md`: the hooks of O2b, O2c and O2d;
  - `map_pitfalls.md`: the recovered O2a review, turned into P1-P40, and the
    platform's promises (K, U and D ids).
- The arithmetic of §2: `calc/o2_spec_costs.py` in this folder.

**The lost section numbers.** The code cites the lost master spec by section
(§2.2, §3.6, §4.6, §5.2, §7.1, §7.5.4, §10.6 and others). This spec never
relies on one. Every rule it keeps is restated here under its own id.

**Rules named only in the recovered notes.** Each one is restated or
dropped:
- "rule 2" becomes V2 (A.32);
- V6 becomes V6 (A.32);
- I3c, I4 and I12 become the officer's I3c, I4 and I12 (A.37);
- C17 becomes the intent's time to live (A.42);
- D18 as a per-Orc cap becomes A.12;
- C14 is dropped (P24 explains why).

**Ids.**
- **N1-N8**: the invariants (§0).
- **§1.0.9**: the table of every model caller.
- **A.n, B.n, C.n, D.n**: the rules of O2a, O2b, O2c and O2d. They have a
  dot.
  - map_army's items have no dot. They are cited as "map_army B4".
  - The code's own names keep their family word: "decision D30", "floor F5",
    "rule V10", "wake reason W11".
- **V1-V14**: the validator's rules (A.32).
- **I2-I12**: the officer's rules (A.37).
- **P1-P40**: map_pitfalls's requirements. **K-, U-, D-** ids: its promises.
- **H1-H3**: the shadow honor audits (C.1).

**Words.** Platform text is English. No account figure appears anywhere
(N6's distinctive figures are fake test values, there to catch a leak).
"$" always means AI spend in USD. Model ids live only in
`ai_agents/catalog.py`.

---

## §0 Invariants

Every commit keeps all eight. Each one comes with the test that proves it.
A commit that cannot keep one does not ship.

### N1. Shadow by construction: nothing an Orc decides reaches an order

O2 adds no new mechanism for this. It keeps what O1 built and fences what it
adds.

1. **The tick discards the Orcs' answer.** `AssetBot.manage_positions` runs
   the care, then calls `observe.after_care(...)` and ignores what it returns
   (bot_program/asset_engine/base.py:1396-1409).
   - O2 adds to the tick only `intents.take` (A.42): Orc-table writes in
     their own savepoint, under the 200 ms lock timeout of N8. Never a
     trade-row write, never a model call, and never an import of `mind`,
     `mind_gateway` or `scheduler`.
   - The tick hands its REAL in-memory `trade` and `bot` to every Orc step
     (observe.py:104-106; ghost.py:1249-1253), and the care then reads the
     same objects: `_manage_broker_stop`, `_update_trailing_stop`, the SL/TP
     check and `_close_trade` (base.py:1420-1450). No O2 code mutates them
     (A.45b).
   - Dispatch runs on the slow and orcs workers, never in the tick
     (map_wakes trap 29).
2. **The order path's hooks into the Orcs are a frozen table.** Each hook
   has exactly one allowed callee:

   | Hook | Where it runs | Its one callee |
   |---|---|---|
   | base.py:1403 | the tick, after the care | `observe.after_care` |
   | base.py:2325 and base.py:6763 | a new bot row | `birth.ensure_on_commit` |
   | manual_trade.py:2845 | a manual ticket | `birth.ensure_on_commit` |
   | bot_program/asset_engine/runner.py:404 | the entry's provenance | `thesis.complete_provenance` |
   | kill_switch.py:121 | the kill switch, before the flatten | `lifecycle.kill_all` |
   | the receiver `lifecycle._leg_saved` (lifecycle.py:34; registered by bot_program/apps.py:16) | every AssetBotTrade save, so inside every close path | on commit: `_closed_quietly`, then `on_leg_closed`, then `drum_bus.on_close_quietly` |
   | Morgul's guard G8 (bot_program/morgul.py:38-39) | the guard | reads `metadata["orc"]`; imports nothing |

   (The receiver is not an import, so an import scan cannot see it; the
   table names it.) The rules:
   - O2 adds no hook and no importer on the order path.
   - O2 changes none of `birth._create`, `lifecycle._leg_saved`,
     `_closed_quietly`, `on_leg_closed`, `_close_leg`, `kill_all` and
     `drum_bus.on_close`, except the lock timeout of N8.
   - The temperament draw (C.4) and the heritage entry (D.11) run in their
     own transaction AFTER `_create` commits. They lock the Orc row only,
     never under the trade row's lock (birth.py:292).
   - The queued intents of a closed row expire in `track_ghosts`
     (`ghost.step_bars`, A.44), never in `on_leg_closed`.
   - drum_bus.py:219-221 is not filled in O2: it is re-marked "# O3:"
     (C.17).
3. **No Orc module reaches an order path or a stop mover**, by name and by
   structure (test items a and g):
   - the FORBIDDEN names of tests/orcs/test_orc_switch_off.py:427-431 and
     tests/orcs/test_orc_source_pins_o1b.py:15-19 appear in no module of
     the package, with one allow-listed use: `birth.notify_adopted`'s
     adoption notice (K-R12);
   - O2 code makes no call on the tick's `bot`, a broker client or the
     tick's cache, and references no callable of the order-path modules.
   - The gateway gets no exception.
4. **One module only may name `ai_agents` or `anthropic`:**
   `bot_program/orcs/mind_gateway.py` (A.22). It calls the provider and
   imports nothing of the order path. No other route reaches the provider:
   not a string, not `importlib`, not `apps.get_model`, not a helper outside
   the package (test item b; the runtime proof of N7).
5. **No Orc module writes what has power.** By receiver, never by spelling:
   - No AssetBotTrade write, except the existing `metadata["orc"]` stamp
     (O1a's `census._restamp`, by design).
   - On an Orc, none of the binding columns:
     - `stop_level`, `stop_why`, `stop_at`, `trail_owner`, `lock_waiver`,
       `be_swap_floor` (models.py:86-93);
     - `captain_may_cut` (:67);
     - `commission`, `stood_down`, `hand_hold_until`, `last_step_tick`
       (:64-68).
   - On an OrcSeat, none of `level`, `status` or `pinned` (models.py:27-29).
   - Into a trade's metadata, no `DROP_META` key (ghost.py:99-102) and no
     `"orc_exit"`, which marks a binding Orc exit (ghost.py:1328-1330).

   The same words on other receivers are allowed: an OrcWake's `status`,
   the agent name `"orc"`, the O arm's own `"orc_stop"` (ghost.py:321,
   :864-869, :913).
6. **What a model writes is read only by the surfaces that show it.** This
   covers `Orc.plan`, `OrcIntent`, the notes, the orders and the answers.
   - The readers are `notes.slot`, dashboard/views_orcs.py,
     dashboard/horde.py and the Telegram surfaces.
   - No care, sizing, gate or broker module reads any of it, by import or
     through a reverse accessor: `trade.orc`, `trade.orc_leg`,
     `config.orcs`, `user.orcs`, `orc__` lookups (models.py:47-55,
     :140-144; test item g).
7. **A proposal moves only the O arm.** The O arm (`ARM_ORC`) is a JSON
   state on an OrcTrack row (ghost.py:1-10).

**The tests that prove it** (`tests/orcs/test_orc_o2a_shadow_pins.py`). O2a
creates it, and every later commit adds its modules to it.
- **What it scans:** every `.py` file in `bot_program/orcs/`, plus
  `bot_program/management/commands/orcs.py`.
- **"O2 code"** is a module O2 adds (§1.1.3, §1.2.3, §1.3.3, §1.4.3), plus
  each function O2 adds to an O1 module. The test names those functions
  in a list that every commit extends. The O1 functions O2 must leave
  alone are pinned by item (h).

- (a) **No order path, by name and by structure.**
  - The union of the two FORBIDDEN sets appears in no module of the
    package. The one allow-listed use: `birth.notify_adopted`'s
    `dispatch_notification` (birth.py:384-392).
  - In O2 code, no call whose callee chain is rooted at `bot`, `env.bot`,
    a broker client, or a value read from `_tick_broker_cache`. The read
    allowlist: `_tick_broker_cache.get`, `_last_ticks.get`, and the
    attribute reads `cfg`, `user` and `asset_class`.
  - In O2 code, no import of, and no attribute reference to, any callable
    defined in `bot_program.asset_engine`, `bot_program.position_care`,
    `bot_program.manual_close`, any `bot_program.engine` module,
    `bot_program.venue_exit` or `bot_program.adjust_levels`. The test
    builds that set by introspection (every function and method those
    modules define), less a pinned read allowlist (`position_care.plan`).
    A mutator added later is forbidden on arrival.
- (b) **The model is reached from one module only.**
  - The names `ai_agents`, `anthropic` and `count_tokens` appear only in
    mind_gateway.py. The gateway's token count is called `measure_tokens`
    (A.22, A.61).
  - Outside mind_gateway.py: no string constant other than a docstring
    contains "ai_agents" or "anthropic"; no `importlib.import_module`,
    `__import__` or `apps.get_model` call names ai_agents; and none of the
    identifiers `ClaudeProvider`, `BaseAgent`, `can_spend`,
    `count_tokens` or `total_only` appears.
- (c) **No trade-row write.** In no module does a call chain that names
  `AssetBotTrade` end in a write (the WRITES set,
  test_orc_source_pins_o1b.py:21-23), except inside the one function
  `census._restamp` (census.py:74-99, O1a's leg stamp).
- (d) **Nothing with power is written, judged by receiver.** In O2 code:
  - no attribute store, `update()`, `create()` or `bulk_update()` keyword,
    `update_fields=` entry or `journal.append(fields=...)` key names a
    binding Orc column (item 5) on an Orc receiver: a name bound to an Orc
    (`orc`, `locked`, or any name assigned from `Orc.objects` in the same
    function), or a chain rooted at `Orc.objects` or `orc`;
  - none names `level`, `status` or `pinned` on an OrcSeat receiver (a
    chain rooted at `OrcSeat.objects`, `seat` or `orc.seat`);
  - no `DROP_META` key and no `"orc_exit"` is written into a trade's
    metadata: a subscript store on `.metadata` or `meta`, a
    `metadata.update(...)` or `meta.update(...)`, or a `metadata=` value
    in an AssetBotTrade write.
  - String constants are not banned. OrcIntent's would-be stop is named
    `would_stop`, never `stop_level`.
- (e) **The importers outside the package are a frozen list.**
  - The list is computed from the import nodes (never the comments) at the
    commit the branch starts from. It grows only by the files this spec
    names.
  - The order-path files are, under bot_program/: asset_engine/*.py,
    engine/*.py, manual_trade.py, manual_close.py, paper_exits.py,
    position_care.py, morgul.py, aragorn*.py, smart_money.py and
    share_allocator.py. They import exactly the callees of item 2's table,
    at exactly its sites, and nothing else of the package.
  - G8 stays pinned by `test_nothing_outside_the_orcs_reads_the_stamp`
    (tests/orcs/test_orc_switch_off.py:458).
- (f) No module outside bot_program/orcs, except the allowed surfaces and
  the tests, imports `OrcIntent`, `scheduler`, `mandate`, `validator`,
  `mind` or `mind_gateway` from the package.
- (g) **No reverse-accessor read.** An AST scan of every non-test module
  outside bot_program/orcs, except the allowed surfaces
  (dashboard/views_orcs.py, horde.py, views.py, views_close.py;
  bot_program/telegram_eye.py, scorecard.py; the orcs and scorecard
  commands). It fails on:
  - any attribute chain through `.orc.`, `.orc_leg` or `.orcs`;
  - any string constant starting "orc__" or containing "bot_program_orc";
  - any `apps.get_model("bot_program", "Orc...")`.

  The order-path files of (e) get the strict form: no Orc reference at all,
  except the hooks of item 2. Green on the base: today only the allowed
  surfaces read these (bot_program/scorecard.py:301-329,
  dashboard/views_orcs.py:170, :316-340).
- (h) **The frozen O1 functions** of item 2: a hash of `inspect.getsource`
  of each is pinned as O2a leaves them (after N8's lock timeout). A change
  to one is a deliberate pin change in the same commit, with its reason.

**The behaviour proofs beside them.**
- **T12b, the tick differential** (`tests/orcs/test_orc_o2a_tick_diff.py`).
  It extends `test_orc_tick_off._run` (tests/orcs/test_orc_tick_off.py:
  56-82, :121-150).
  - Two identical configs and rows. On one: `orcs` and `orcs_minds` ON,
    the line set, and one queued intent of each kind in
    `seen["intents_queued"]`: a tighten whose would-stop is strictly
    tighter than the real stop, with the tick's price between the two; a
    trim; an exit; a lock_waive of the live event. The other row is
    unhooked.
  - It runs once per world: an unprotected bot row (so the trailing stop
    and the SL/TP check run after `after_care`), a protected eToro-style
    row (so `_manage_broker_stop` runs), a manual row and a paper row.
  - It asserts equal results between the two rows: `closed`; the row
    snapshot (every column, `take_profit` included, and the metadata less
    `"orc"`); the AragornAction rows; the broker's `mock_calls`.
  - It also asserts that a `copy.deepcopy` of `trade.__dict__` (less
    `_state`), `trade.metadata` and `trade._care_tick`, taken before
    `after_care`, equals the same taken after it.
- **T12, end to end** (P38): every world through detection, render,
  admission, claim, fake model, validation, intents, the O arm and the
  grade, with the bookings and counters asserted (§1.1.7). T12 is not the
  shadow proof: a quiet fixture there could hide a leak. T12b is the proof.
- **The behavioural guard** of every O2 test (N7): no binding column, no
  trade-row column and no metadata key but "orc" changes.
- **The lock proof** (N8): the tick, a real close and the kill switch never
  wait on an Orc lock.

### N2. Every new switch is OFF on arrival, and only the operator's PIN turns it on

The new switches, by commit:

| Commit | New switches |
|---|---|
| O2a | `orcs_minds` |
| O2b | `orcs_router`, `orcs_probes`, `orcs_frontier` |
| O2c | `orcs_temperaments`, `orcs_captains`, `orcs_emperor`, `orcs_skeptic`, `orcs_drum_wakes` |
| O2d | `orcs_postmortem`, `orcs_council_of_war`, `orcs_questions` |

Every one of them:
- is a System switch, OFF on arrival;
- is in `BULK_ENABLE_EXEMPT` (core/platform_control.py:126-128), so "all on"
  never turns it on (§4 Q1);
- takes the operator's trading PIN to turn ON, through the one rule of
  core/switch_pin.py (§4 Q0). Turning one OFF never asks. The shell's
  `component on` and the Django admin refuse it and point to /ops/, as they
  do for a live-money key (switch_pin.py:30-34);
- is listed in a new tuple, `ORC_MIND_SWITCHES`, beside
  `LIVE_MONEY_SWITCHES` (:97-110) and never in it. Nothing in O2 moves
  account money, but each of these switches lets a model spend AI money,
  or changes what a model reads;
- reads OFF when it cannot be read (switches.py:1-28).

The existing `orcs_drums` keeps its O1 meaning: drums are journaled. It
stays outside both tuples. The drum WAKES, which spend, sit behind the new
`orcs_drum_wakes` (C.14), because `orcs_drums` may already be ON in
production: it was inert since O1, it is not exempt, and `seed_components`
never resets a row's `is_enabled` (core/platform_control.py:326-332,
:519-560; core/switch_pin.py:271-281).

A model caller needs its own switch AND `orcs_minds` AND `orcs` AND the
platform master (A.2).

**The PIN rule, built in O2a** (§1.1.3):
- core/platform_control.py: `ORC_MIND_SWITCHES`, named by hand like
  `LIVE_MONEY_SWITCHES`; `PIN_SWITCHES = LIVE_MONEY_SWITCHES +
  ORC_MIND_SWITCHES`; `BULK_ENABLE_EXEMPT` gains `ORC_MIND_SWITCHES`.
- core/switch_pin.py: `needs_pin` reads `PIN_SWITCHES`. Every ON, refused ON
  and OFF of such a key lands on the audit chain, as for a live-money key.
  `set_category` excludes `PIN_SWITCHES` by name a second time.
- Every door that reads `LIVE_MONEY_SWITCHES` to decide whether to ask the
  PIN reads `PIN_SWITCHES` instead: dashboard/views_ops.py:113,
  dashboard/views.py:4066, dashboard/views_desk.py:552, core/admin.py:41
  and :98. The Wall's count of live-money switches (core/wall_facts.py:
  433-441) does not change.

**Proof** (one test per commit). For each new key:
- it is OFF in a fresh database;
- it is in `BULK_ENABLE_EXEMPT` and `ORC_MIND_SWITCHES`, and not in
  `LIVE_MONEY_SWITCHES`;
- `set_switch(key, True)` writes nothing with no PIN, with a wrong PIN and
  from the shell; with the right PIN it turns the key ON; OFF takes no PIN
  (the pattern of tests/test_switch_pin.py);
- its description is under 300 characters;
- it is in the named list of tests/test_the_book.py:1650-1670 (K-B8);
- with it OFF, the fake provider's call list stays empty, as one pair with
  its positive control (N7).

### N3. The budget line binds every call

- **The line ships off.** `ORC_DAILY_BUDGET_USD` ships at 0 and stays 0 by
  default (spend.py:79-81). At 0 no Orc call is made, whatever the switches
  say (spend.py:229-230).
- **Every Orc call goes through `mind_gateway`.** That includes wakes,
  probes, the twin, Captains, the Emperor, the Skeptic, post-mortems, the
  council of war, answers, and every shell command that sends a call
  (§1.0.9). The gateway:
  1. reads the four gates again (A.2);
  2. asks the line:

     ```
     spend.can_spend(line="orcs",
                     tier=<the model's tier_hint>,
                     estimated_usd=<this call's bound
                                    + the reservations and holds
                                      of the OTHER calls and tickets>,
                     deep_share_exempt=<a real-money urgent wake only>)
     ```

     (spend.py:208-276). A call's own reservation is never counted twice.
     The gateway never passes `total_only`, which would skip the line-off
     refusal (spend.py:229-230, :244-245);
  3. only then calls the provider, with:
     - `record=True`, `line="orcs"`, `client_refusal_rerun=False`,
       `max_attempts=1` (A.21);
     - an Orc agent name (spend.py:93-97);
     - a `source_ref` that starts with `Orc:` or `Captain:`
       (spend.py:130-140).
- **The one exception: counting tokens.** `count_tokens` is not a model
  call: it is free and never ledgered (claude_provider.py:724-742). It is
  sent only by `orcs tokens --yes`, through `mind_gateway.measure_tokens`,
  which never calls `complete()`. It needs only `--yes` and the API key, so
  S can be counted before anything is turned on (A.61). The fake client
  records count requests in a list of their own.
- **Calls in flight hold a reservation under one lock** (A.18). Two workers
  can therefore never both spend the same remainder (`can_spend` sees only
  booked rows, spend.py:149-154).
- **Money is never released before its cost is known** (A.24, A.25, A.55,
  A.57). A call that ends without a bill keeps its bound held until
  00:00 UTC. A late settle books the real cost and drops the hold.
- **The core's floor covers the Orcs' unbooked money** (A.18). The core
  line subtracts only the Orcs' booked spend and `ORC_LIVE_FLOOR_USD`
  (spend.py:157-170). So the bounds in flight plus the holds may never pass
  that $3.00.
- **Day caps and triage bind inside the line** (A.12-A.14, A.57): per Orc,
  per caller, and the triage ceilings.

**Proof:**
- with the line at 0 and every switch ON, the call list stays empty; the
  same fixture with the line set records exactly one request (N7's pair);
- with the line on and `orcs_minds` OFF, the call list stays empty (with
  its pair);
- the reservation, in one thread: inside the fake client's first call, a
  claim of a second wake whose bound no longer fits ends `triage` or `line`
  with no second request (T5);
- on PostgreSQL, two concurrent claims where only one fits make exactly one
  call, and neither thread raises (T5; N7's PostgreSQL rule);
- every recorded request passed through `mind_gateway.call`, after a
  `can_spend(line="orcs", total_only=False)` that answered allowed (N7);
- `orcs tokens --s --yes` with the line at 0 records one count request and
  no messages request;
- the provider's ledger row lands on the Orcs line: `spent_today("orcs")`
  rises by the booked cost;
- tests/test_ai_spend_lines.py stays green, unchanged.

### N4. The ladder cannot exceed its rung bound

- **Every call names a rung** of `ORC_LADDER_V1` (catalog.py:505-520). The
  gateway reads the model id and the effort from the catalog by that name.
  No model id appears in the package (tests/test_model_catalog.py:455-525).
- **Each caller has a list of allowed rungs** (`CALLER_RUNGS`, A.22;
  §1.0.9).
  - In O2a, wakes may use r0, and the smoke may use r0 and h0.
  - A rung outside the caller's list raises before anything is sent.
  - r5 is reachable only through O2b's Fable gate (B.9), whose quota ships
    at 0. In O2 the gate cannot open at all (B.9's last clause).
- **The answering rung governs** (B.2, B.5). The rung that answers sets the
  limits, the bound, the tier, the `source_ref` and the grade's tag. The
  routed rung is kept only as `components["route"]["would_rung"]`.
- **Every rung has an explicit `max_tokens` and `timeout_s`**
  (`RUNG_LIMITS`, A.21). The provider's default of 32,000 tokens
  (claude_provider.py:53-73) is never used.
- **One send per call** (A.21). The gateway passes `max_attempts=1`, so the
  provider never re-sends the whole request after a mid-stream error
  (claude_provider.py:14-20, :471-493). The SDK's own retries stay: they
  happen before any token streams.
- **The reservation is a true upper bound** (A.21). It is the sum of:
  - every prompt token at the model's 1h cache-write price (its dearest
    input price), on 1.35 × the estimate of the exact text sent;
  - `max_tokens` of output;
  - the fallback's own bound, where a fallback is sent (B.14).

  With one send per call, a booked cost can pass the bound only when the
  real prompt is more than 1.35 × its estimate. The bound test is written
  to catch that case.
- **A slow stream never frees money** (A.55). `WALL_S` closes a wake's
  status only; its bound stays held until a settle, or until 00:00 UTC.
- **No escalation.** O2 never asks a wake again on a higher rung after an
  invalid answer (B.6). A floor raises the band, never the rung beyond the
  table.

**Proof:**
- a fake usage at `max_tokens`, with every prompt token written at 1h,
  books at most the bound;
- a fake stream that raises an `overloaded_error` event mid-stream receives
  exactly one request; the wake ends `failed` with its bound still held
  (T6);
- each caller's disallowed rungs raise, with an empty call list (and its
  pair);
- the ladder pins (tests/test_model_catalog.py:434-452) stay green,
  unchanged.

### N5. A model's words are never a fact, never money, never an instruction

- **Model text is never a fact.** It enters the journal as a note, a plan,
  a proposal, an order or an answer. Its author is `orc`, `captain` or
  `emperor`, and it never gets an F-id (journal.py:1-5; K-B3).
- **It is filtered once, at write time.** Before it is stored, shown or fed
  back, it passes:
  - the platform's money filter, widened in O2a (A.34; plain.py:19-42;
    dashboard/plain_words.py:121-186);
  - the fence: `fence.quarantine`, `fence.sanitize` and a `FENCE_CAPS` cap
    (fence.py:62-108).
- **It re-enters a prompt only as a T1 view**: `fence.view`, labelled "may
  be wrong; facts win" (fence.py:4-13, :104-108).
- **The slot carries no cost, token, model, R-money or spend key**
  (notes.py:22-28; tests/orcs/test_orc_notes.py:37-39). AI spend in dollars
  appears on staff pages only.

**Proof:** table-driven money-form tests (A.34), whose answers reach none of
the card, the page, Telegram or the next PS5; and the walk over the slot's
keys.

### N6. The house words

- English only.
- No account figure in code or text.
- R, ATR, and prices drawn through `format_price` (notes.py:253-256).
- No Orc verb such as "the Orc tightened" (tests/orcs/test_orc_notes.py:40-43;
  tests/test_the_horde.py:918-1006). A proposal is "proposed in shadow".
- Every new sentence that names an Orc or a Captain is registered
  (notes.py:781-796; horde.py:291-299).
- **No account figure is sent to a model** (K-B10). The test fixture's
  account and config carry distinctive fake figures: a balance of
  123456.78, an `r_money` of 987.65 and a quantity of 4321. Every text block
  of every request the fake client records contains none of them, in any
  format: raw, grouped or rounded, matched by value through
  `plain_words.money_marks` (dashboard/plain_words.py:234). The generic
  money filter is not the check here: the dossier's bars carry prices, which
  it would flag (T6; the call tests of O2b-O2d; the pattern of
  tests/test_the_book.py:2253).

### N7. Every claim is proven by a test with a fake model, red first, with no network

- **The fake is the real provider with a fake client.** `ClaudeProvider()`
  gets a fake `client` (the pattern of
  tests/test_claude_provider_keywords.py:43-84).
  - So the ledger, the costs and the refusal paths run for real.
  - The fake records every messages request, with its
    `traceback.extract_stack()`, in a list the test owns, and every
    `count_tokens` request in a second list. The test asserts on those
    lists after the code has run, because the Orc code swallows exceptions
    (observe.py:104-109, wake.py:819-830) [P36].
- **Every O2 test class inherits `MindTestMixin`** (tests/orcs/helpers_o2.py),
  through `MindTestCase(TestCase)` or
  `MindTransactionTestCase(TransactionTestCase)`. The mixin:
  - blocks `socket.connect`, `requests.Session.request`, `requests.get`,
    `requests.post` and the anthropic client's constructor;
  - installs `pre_save` receivers on Orc, OrcSeat and AssetBotTrade, and
    wraps `QuerySet.update` and `bulk_update` for those models. Its
    tearDown asserts that no binding Orc column (N1.5), no OrcSeat `level`,
    `status` or `pinned`, no AssetBotTrade column and no AssetBotTrade
    metadata key other than "orc" changed;
  - asserts in its tearDown that every recorded request's stack passes
    through `mind_gateway.call`, and that a spy on `spend.can_spend` saw,
    in the same call and before the send, `can_spend(line="orcs",
    total_only=False)` answer allowed.
- **Every O2 test module** is named `tests/orcs/test_orc_o2{a,b,c,d}_*.py`.
  A meta-test (T16) proves that every TestCase there inherits one of the
  two base classes [P36].
- **Every zero-call assertion is a pair inside one test method** [P37].
  - First, the fixture with every gate ON records exactly one request on
    the fake client: `orcs`, `orcs_minds`, the platform master and the
    caller's own switch ON, the line set through `minds_on()`, no cap
    reached.
  - Then ONLY the gate under test is flipped, and the list is empty, with
    that gate's code asserted.
  - T16 fails any test that claims "no call" or "empty call list" without a
    positive assertion of exactly one recorded request.
- **Red first.** Each test is run red on the base first. For a zero-call
  test, "red first" means this: with the gate's check deleted (a recorded
  mutation), the test fails.
- **The PostgreSQL-only tests.** CI runs SQLite
  (.github/workflows/tests.yml: `DB_ENGINE: sqlite`), where
  `select_for_update` and `lock_timeout` do nothing.
  - The lock and concurrency tests (N8, T5) are `skipUnless` the engine is
    PostgreSQL.
  - The builder runs them before each commit that touches a lock, on a
    throwaway local cluster (PostgreSQL 16 is installed at
    /usr/lib/postgresql/16/bin; `DB_ENGINE=postgresql`). The commit message
    names that run.

### N8. No Orc lock can delay the care, a close or the kill switch

Three real-money paths take an Orc's row lock with no timeout today:
- the tick's Orc steps (journal.py:35-36, :87-88, :183-184), inside the
  loop over every OPEN row of a config (base.py:1084-1087, :1396-1409;
  observe.py:104-109);
- the close receiver's `on_leg_closed`, inside every closing process, the
  kill switch's sweep included (lifecycle.py:34-63, :107-109;
  kill_switch.py:525, :872);
- `kill_all`, before the flatten (kill_switch.py:117-124;
  lifecycle.py:163-166).

`DATABASES` sets no lock or statement timeout (config/settings.py:201-225),
and a stalled pass makes the next beat skip (bot_program/tasks.py:53-56).
So O2 holds an Orc lock only briefly, and the real-money paths never wait
long for one.

1. **An O2 transaction that locks an Orc row or the line lock does only
   database reads and writes inside it.** No render, no validation, no
   officer, no pricing, no provider call.
   - The render pass is three transactions (A.7).
   - Validation and the officer (A.30-A.38) run before the settle takes
     its lock (A.24).
   - The claim locks each candidate's Orc row with
     `select_for_update(skip_locked=True)` and commits per examined wake
     (A.18).
2. **Every O2 lock holder** sets `SET LOCAL lock_timeout = '2s'` and
   `SET LOCAL statement_timeout = '5s'`.
3. **The Orc locks on the real-money paths** use `SET LOCAL lock_timeout =
   '200ms'`. These are: the tick's `after_care` steps, `intents.take`
   included; `lifecycle._closed_quietly` and `on_leg_closed`; `kill_all`;
   and, for the same reason, `thesis.complete_provenance` on the entry path
   (bot_program/asset_engine/runner.py:404; thesis.py:280).
   - One helper, `journal.orc_lock(orc_pk)`, sets the timeout and takes the
     lock; every Orc-row lock of the package goes through it (journal.py's
     three, lifecycle.py:109 and :166, thesis.py:280). `journal.lock_budget
     (ms)` is a context manager (a ContextVar, default 2,000 ms) that
     `observe.after_care`, `_closed_quietly`, `kill_all` and
     `complete_provenance` enter with 200. The census's `lifecycle.sweep`
     keeps the default. On SQLite the timeout is a no-op.
   - A timeout is fenced and logged, as every Orc failure already is
     (observe.py:104-109; lifecycle.py:59-63; lifecycle.py:152-184). The
     census's `lifecycle.sweep` and the next tick catch up.
   - The kill switch itself is unchanged. Its flatten never waits on an
     Orc.
4. **The O2 watchdogs (A.54-A.57) run in their own task,**
   `orc_minds_watch` on `slow` (A.17), never inside `orc_census` on `fast`.
   worker-fast serves fast and default with three slots
   (deploy/docker-compose.yml:165), beside the bot tick
   (config/celery.py:454-462) and the alarm bot's /stopall poll (:74-78).

**Proof** (`tests/orcs/test_orc_o2a_locks.py`, PostgreSQL only, N7).
`MindTransactionTestCase`, two threads. Thread A holds one Orc's row lock
for 10 s. Thread B then runs each of these in under 1 s, with the same
fake-broker calls and rows as the same run with no Orc:
- (a) `manage_positions` on a config that holds that Orc's row and a second
  real row whose price crosses its stop;
- (b) `execute_kill_switch`;
- (c) the close of the Orc's row;
- (d) the runner's provenance step for that Orc's row (bot_program/asset_engine/runner.py:404).

A source test beside it pins that no O2 function that holds `orc_lock` or
the line lock calls `dossier.render`, the validator, the officer,
`pricing` or the gateway.

---

## §1 The commits

### §1.0 What every commit does

1. It is built tests-first with the fake model (N7).
2. It makes every model call through the gateway (N3, N4), as a row of the
   callers' table (§1.0.9).
   - Its callers use agent names from `ORC_AGENT_KEYS`
     (dashboard/views_ai_models.py:96-105).
   - A new name joins both `ORC_AGENT_KEYS` and spend's membership
     (spend.py:95-97), and never `KNOWN_AGENT_KEYS`.
3. It adds a switch for each new model caller: OFF, exempt from "all on",
   and turned on only with the PIN (N2).
4. It ships its tables in its own migration.
   - The migration follows the newest at build time: 0046 at 9d74a19;
     origin/main 49b6b57 already holds 0047 and 0048 (models.py:7-9).
   - It moves its tables from `O2_TABLES` into the defined set of
     tests/orcs/test_orc_models.py:14-20 and :57-65.
5. It keeps allowed values as tuples in constants.py (constants.py:1-3).
   - `journal.append` checks neither tuple (journal.py:53-56).
   - So a test checks that every journal kind and author the commit writes
     is in `JOURNAL_KINDS` and `AUTHORS`.
6. It replaces each "# O2:" seam marker it fills, re-marks each one O2
   does not fill, and updates tests/orcs/test_orc_source_pins_o1c.py:69-83
   in the same commit to the markers that remain:

   | Marker | O2a | O2b | O2c | O2d |
   |---|---|---|---|---|
   | wake.py:54 | narrowed to "# O2b, O2c: the router; drum deliveries add W12" | narrowed to "# O2c: drum deliveries add W12" | removed | |
   | integrity.py:19 | replaced (the officer, A.36) | | | |
   | fence.py:23 | replaced (the validator's V10, A.32) | | | |
   | predicates.py:37, :351 | deleted (§1.1.3) | | | |
   | dossier_position.py:355 | re-marked "# Later:" (continuation odds, §3) | | | |
   | drum_bus.py:41, :666 | | | filled (C.14) | |
   | drum_bus.py:219 | | | re-marked "# O3:" (C.17) | |
   | dossier_market.py:34, :260 | | | filled (C.12) | |
   | dossier_position.py:299 | | | narrowed to PS10, "# O2d:" | removed (D.11) |

   Comments that name O2 without a marker are rewritten by the commit that
   makes them true or false: playbook.py:25-27 and weather.py:6-9 in O2a
   (A.36, A.12), complexity.py:10 in O2b.
7. It updates every sentence that its arrival makes false. The new words
   read the switch and the line, so they stay true while both are OFF
   (map_wakes §2.8; map_army §5.6; map_pitfalls B.7).
8. It is committed the house way, and pushed at once [P40].
   - Commit through `commit.sh`, which recounts `TESTS_GREEN`
     (core/wall_facts.py:52).
   - Restore any stray churn in core/wall_facts.py.
   - Use the two trailers, and no model id in the body.
   - Push the commit as soon as it exists.

#### §1.0.9 Every model caller

One row per caller. A caller missing from this table raises in the gateway
and in `reserve_ticket` (A.57). Every doctrine is English, byte-stable,
carries A.29's authority sentence, and is counted by `orcs tokens` like S.
"The bound" is A.21's formula on `dossier.estimate_tokens` of the exact
text sent, × the family factor, with the caller's own rung limits. Tickets
and every non-real-money wake send no fallback (B.14).

| Caller | Commit, switch | Doctrine (version, cap) and schema | What it sends | Rung after B.5 (no PASS / PASS) | Its bound | Day cap | Triage ceiling (A.13) | Agent, `source_ref` |
|---|---|---|---|---|---|---|---|---|
| wake | O2a, `orcs_minds` | S (s1, 12,000 chars), `SCHEMA_V1` | S, the shared blocks, PS, the tail (A.23) | r0 in O2a; routed from O2b | on `components.tokens`; r0 $0.197 | per Orc (A.12) | its class | `orc`, `Orc:<pk>:Wake:<w>:<rung>` |
| smoke | O2a, the four gates and `--yes` | the wake's | a wake's stored blocks | r0 or h0; from O2b the wake's rungs | the wake's | one per command | C − R | `orc`, `Orc:<pk>:Smoke:<w>:<rung>` |
| probe | O2b, `orcs_probes` | the wake's | the wake's stored blocks | h0, r0, r1, r3, r4, mapped | the primary's alone: h0 $0.01, r1 $0.28, r3 $0.71, r4 $0.87 | boundary 6 a user, h0 40 | its own allowance, 15% of C, and C − R (B.11) | `orc`, `Orc:<pk>:Wake:<w>:probe:<rung>` |
| twin | O2b, `orcs_frontier` | the wake's | r5's stored blocks | r4 | $0.87, reserved with r5 as one pair (B.9) | with r5 (quota 0) | the r5 wake's (C) | `orc`, `Orc:<pk>:Wake:<w>:twin:r4` |
| captain | O2c, `orcs_captains` | `CAPTAIN_DOCTRINE` (c1, 6,000), `CAPTAIN_SCHEMA_V1` | its Orcs' cards, the weather, the book as shares, the Emperor's line (C.7) | r0 | at most 10,000 tokens: $0.13 | 4 a class a day | C − R | `captain`, `Captain:<class>:Wake:<n>:r0` |
| emperor | O2c, `orcs_emperor` | `EMPEROR_DOCTRINE` (e1, 6,000), `EMPEROR_SCHEMA_V1` | the weather, the orders and their grades, counts in R, the fallen, the book as shares, the mood's fractions (C.11) | r2 / r3 | at most 16,000 tokens: $0.49 / $0.65 | 1 a user a day | C − R | `orc_emperor`, `Orc:Emperor:<user>:<day>:<rung>` |
| skeptic | O2c, `orcs_skeptic` | `SKEPTIC_DOCTRINE` (k1, 3,000), `SKEPTIC_SCHEMA_V1` | the item, its cited facts, the menu, the mandate | r0 | at most 6,000 tokens: $0.11 | 6 a user a day | its item's class: a Captain's cut C − R; an add, the Orc's own non-urgent class | `orc_skeptic`, `Orc:<pk>:Skeptic:<intent>:r0` or `Captain:<class>:Skeptic:<order>:r0` |
| postmortem | O2d, `orcs_postmortem` | `POSTMORTEM_DOCTRINE` (p1, 4,000), `POSTMORTEM_SCHEMA_V1` | the journal digest (trimmed oldest first), the plan versions, the intents and their grades, the arms (D.8) | r0 | at most 12,000 tokens: $0.14 | 1 an idea | 0.30 × C | `orc_postmortem`, `Orc:<pk>:Postmortem:<grade>:r0` |
| tribunal | O2d, `orcs_council_of_war` | `TRIBUNAL_DOCTRINE` (w1, 4,000), `TRIBUNAL_SCHEMA_V1` | the post-mortem, the grade, the arms, the digest (D.9) | r2 on real money, r0 on paper | at most 12,000 tokens: $0.45 / $0.14 | 1 an idea | 0.30 × C | `orc_tribunal`, `Orc:<pk>:Tribunal:<grade>:<rung>` |
| question | O2d, `orcs_questions` | `ANSWER_DOCTRINE` (q1, 2,000), `ANSWER_SCHEMA_V1` | the latest wake's stored blocks, then the doctrine and the question as a view (D.15) | r0 / r1 on real money; r0 on paper | at most `DOSSIER_MAX_TOKENS` + 400: $0.20 / $0.28 | 10 a user a day | C − R on real money, never R; 0.60 × C on paper | `orc_question`, `Orc:<pk>:Question:<entry>:<rung>` |

No ticket is charged to an Orc's own dollar cap (A.12): each caller has the
day cap above. The bounds are calc/review_bounds.py's.

---

### §1.1 O2a: wakes and the mind in shadow

#### 1.1.1 Scope

O2a turns a recorded wake into a model call in shadow. A recorded,
rendered, non-quiet wake goes through these steps:

1. admission;
2. the `orcs` queue;
3. a worker's claim, inside the Orcs' budget line;
4. a call to the provider, on the stored dossier plus S, the doctrine;
5. a hand-written validator and the mandate's officer, both in would-mode;
6. the result: a plan, proposals ("intents") in shadow, a note, and a state.

The proposals move the O arm only. They are graded against the care ghost.

**What O2a does not do:**
- It does not route: every wake is answered on one fixed rung, r0 (A.21).
- It sends no probe.
- It has no Captain, Emperor, drum wake, seat or question.
- It adds no power: nothing an Orc decides reaches an order, a stop or a
  size (N1).

**What it ships with:**
- the minds switch (`orcs_minds`), OFF, which only the operator's PIN turns
  on (N2);
- the Orcs line at 0;
- one fixed rung.

#### 1.1.2 Models and migration

The migration is `bot_program/migrations/00NN_orcs_o2a.py`. NN is the next
number at build time.

1. **`OrcIntent`** (new; moved out of `O2_TABLES`). One row per proposal
   that is not a hold:

   | Field | Type | Meaning |
   |---|---|---|
   | `orc` | FK Orc, CASCADE | |
   | `wake` | FK OrcWake, null, SET_NULL | |
   | `decision` | FK OrcJournal, null, SET_NULL | the decision entry |
   | `kind` | CharField 16 | tighten, trim, exit, lock_waive or add |
   | `candidate` | CharField 16, blank | |
   | `level_id` | CharField 24, blank | for display only |
   | `level` | JSON dict | the stored level reference {level_id, kind, tf, price, stop}, copied by code from the wake's `vctx.menu` (A.39); every later use reads it, never the id |
   | `would_stop` | Decimal 18,8, null | the would-be stop (A.32 V7): the level's own `stop` beyond the crowd, or the BE row's price |
   | `event_id` | CharField 16, blank | a lock_waive's event code (A.30, V14) |
   | `share` | Float, null | the trim's share, or the add's risk share |
   | `facts_cited` | JSON list | |
   | `mode` | CharField 10 | `shadow` or `refused` (constants.py:388-389) |
   | `rule` | CharField 16, blank | the refusing rule, or the expiry code (`ttl`, `moved`, `row_closed`, `arm_closed`) |
   | `officer` | JSON dict | the would-verdict (A.37) |
   | `status` | CharField 12 | `queued`, `simulated`, `expired`, `recorded` or `refused` |
   | `why` | CharField 200, blank | fixed English words |
   | `created_at` | auto_now_add | |
   | `expires_at` | null | |
   | `applied_at` | null | |
   | `applied_price` | Decimal 18,8, null | |
   | `applied_r` | Float, null | |
   | `wave_id` | CharField 40, blank | O2c's wave stamp, blank until then |
   | `rung` | CharField 4 | |
   | `s_version` | CharField 8 | |
   | `schema_version` | CharField 8 | |

   - Indexes: (orc, −created_at) and (status).
   - No `choices` (models.py:11-13).
   - No money column: R and prices only.
2. **`OrcWake.queued_at`** (AddField: DateTimeField, null). The first send.
   It is set once at admission and never changed again [P9].
3. **`AddIndex`** on OrcWake (status, −priority, queued_at), for the claim.
4. **OrcSetting keys** (models.py:290-310, "the budget keys from O2"). They
   bind at once, with no restart (K-R4):
   - `per_orc_daily_usd`, and `per_orc_high` (A.12's HIGH column);
   - `wakes_per_day`;
   - `routine_share`;
   - `triage`;
   - `minds_lock`: the lock row, created with `get_or_create` and one retry
     on `IntegrityError` (A.18). The migration does not create it;
   - `minds_inflight`: the tickets and the holds (A.25, A.55, A.57);
   - `minds_breaker`;
   - `smoke_verdict`: one verdict per family (A.61);
   - `s_tokens`;
   - `minds_watch_last_at` (A.55).

   Defaults are in A.12-A.14 and A.56.
5. **No new Orc column.** O2a writes the reserved columns:
   - `plan`, `plan_version`, `plan_changes_24h`, `watches` (models.py:83-85,
     :94);
   - `latest_note`, `latest_note_at`, `last_wake_at`, `last_good_wake_at`,
     `next_wake_due`, `last_facts_hash` (:97-102);
   - the four day counters (:103-109);
   - `care_owned_reason`, `care_owned_at` (:110-111);
   - `state` = `active` or `care_owned` (constants.py:8-16).

   It writes none of the binding columns (N1.5).
6. **The model tests change on purpose:**
   - tests/orcs/test_orc_models.py:57-65 now expects O1_TABLES plus
     `OrcIntent`;
   - its migration test gains the O2a migration, with these operation types
     allowed: CreateModel, AddField, AddIndex, AddConstraint.

#### 1.1.3 The code it adds or changes

**New modules** (bot_program/orcs/):

| Module | What it holds |
|---|---|
| `mind_gateway.py` | the ONLY module that names `ai_agents` or `anthropic`: the rungs, the bound, the line, the call with `max_attempts=1`, `measure_tokens` (A.20-A.23) |
| `scheduler.py` | admission, the merge, the claim, the reservation, the tickets and the holds, the settle, the day counters, the triage, the watchdogs, the breaker (A.7-A.27, A.54-A.57) |
| `mind.py` | one claimed wake: the request built from the stored blocks, the call through the gateway, the parse, the validation and the officer (no lock held), then the writes of the outcome inside the settle (A.23-A.26, A.39-A.41) |
| `validator.py` | `SCHEMA_V1` and V1-V13, pure (A.30-A.35) |
| `mandate.py` | the officer: `allowed_actions` and the would-verdicts I2-I12, pure but for one read of the O arm (A.36-A.38) |
| `doctrine.py` | S, versioned, pure (A.28-A.29) |
| `intents.py` | queued shadow intents applied to the O arm at the tick (A.42) |
| `evidence.py` | the code facts V6 and V10 need: `level_reached`, `bar`, `gap`, `expectation` (A.46) |

**Changed in the package:**

| File | What changes |
|---|---|
| wake.py | `record` writes `recorded` (A.3); `render_queued` merges and admits in three transactions (A.7); `render_wake` writes the validation context and the evidence first (A.8), and reads the Orc's journal up to `journal_as_of` on a re-render (A.24); F6's reference (A.9); the facts hash v2 (A.10); W3 reads `watches`, without urgency (A.48); the asked wake and the metronome in W11 (A.49-A.50); the words; the seam marker |
| journal.py | `orc_lock` and `lock_budget` (N8); `append` and `remember` take their lock through `orc_lock` |
| observe.py | the tick's Orc steps inside `lock_budget(200)` (N8) |
| lifecycle.py | `_closed_quietly` and `kill_all` inside `lock_budget(200)`, and the two Orc locks through `orc_lock` (N8); nothing else |
| thesis.py | `complete_provenance` inside `lock_budget(200)`, its lock through `orc_lock` (N8); nothing else |
| constants.py | statuses, codes and words; the switch name; `RUNG_LIMITS`; the O2a numbers; `FENCE_CAPS["orc"]`; `PLAN_WATCH_MIN_ATR1H` |
| dossier.py | S as a stored block; `context_for` builds the idea rows with the row's cost fraction (A.8); PS5's notes; `allowed` from the officer at :333-334 |
| dossier_position.py | PS1, PS3, PS4's loss and counters, PS5, PS12's `watch` column and the words (A.47) |
| ghost.py | the would mode of `_step_orc`, in new functions named by N1's test list; `_care_step` gains `extra_kind` (default "playbook"); the call to `intents.take` (A.42-A.44) |
| grading.py | the counters, the AI cost and the tags (A.58) |
| notes.py | the words; `plan_line`; `intents` read from the card; `rung_t` (A.62) |
| surfaces.py | Telegram words (A.62) |
| tasks.py | `orc_think`; `orc_minds_watch`; the render task admits (A.17) |
| weather.py | `caps_for` makes the wake cap binding, paper 6 (A.12); the header comment at :6-9 |
| playbook.py | the comment at :25-27 (A.36) |
| integrity.py | the comment: the officer replaces `allowed_actions_l0` |
| fence.py | `FACT_KINDS` gains `expectation`; the comment |
| models.py | `OrcIntent`; `OrcWake.queued_at` |
| switches.py | `minds_on()`, which reads the four gates (A.2) |
| predicates.py | delete the stale `wake.request` seam comment at :36-38 and :351. W8 is already detected on the same tick (wake.py:257-262), and O2 adds no `request()` |

census.py does not change in O2a: the watchdog is its own task (N8).

**Changed outside the package:**

| File | What changes |
|---|---|
| bot_program/management/commands/orcs.py | the new subcommands (A.59-A.61) |
| ai_agents/providers/claude_provider.py | `complete()` gains a keyword-only `max_attempts: int = None`. None keeps `_MAX_ATTEMPTS`, so every other caller's request is unchanged and tests/test_claude_provider_bytes.py stays green. A provider test of its own proves 1 and None (T18) |
| config/celery.py | the `orcs` route; `orc_minds_watch` on `slow`; the beats; the comment at :96 and :100-101 |
| deploy/docker-compose.yml | `worker-orc` |
| core/platform_control.py | `orcs_minds`; `ORC_MIND_SWITCHES`, `PIN_SWITCHES`; `BULK_ENABLE_EXEMPT` (N2) |
| core/switch_pin.py | `needs_pin`, the audit and `set_category` read `PIN_SWITCHES` (N2) |
| dashboard/views_ops.py:113, dashboard/views.py:4066, dashboard/views_desk.py:552, core/admin.py:41 and :98 | the PIN doors read `PIN_SWITCHES` (N2) |
| core/ops_commands.py:140-152 | the new subcommands |
| ai_agents/spend.py | comments only, :23-24 and :79-81: "the operator turns it on" (U-C4); the default stays 0 |
| dashboard/plain_words.py | the widened money filter (A.34) |
| dashboard/views_orcs.py and templates/dashboard/orc_detail.html, orcs_list.html | the wakes table, the plan, the intents, the words |
| dashboard/views_ai_models.py and templates/dashboard/ai_models.html | the Orcs card's sentence |
| dashboard/council_band.py | one sentence (A.62) |
| core/book_content.py, templates/landing/the_wall.html, deploy/RUNBOOK.md | the words (A.62) |
| tests/test_llm_ledger_truth.py | `BYPASS_SITES` gains the gateway |
| tests/test_switch_pin.py | the O2 keys' PIN cases (N2) |

`ai_agents/catalog.py` does not change in O2a: the gateway reads
`ORC_LADDER_V1` as it is.

#### 1.1.4 The life of a wake in O2a (build order)

Build the steps in this order, each red first.

1. **The tick** (unchanged in cost). `wake.detect` and `wake.record` write
   the OrcWake with status `recorded`.
2. **The render pass** (`orc_render_wakes`, slow queue, every 2 minutes;
   tasks.py:290-312). For each recorded wake, oldest first, in three short
   transactions (N8):
   1. absorb any older pending wake of the same Orc;
   2. render it as of its moment;
   3. admit it: the result is `quiet`, `skipped` with a code, or `pending`.

   A pass that admits any wake then sends one `orc_think` ticket.
3. **The worker** (`orc_think` on `orcs`, run by `worker-orc`; every 60 s
   and on a ticket).
   1. Claim the best pending wake whose Orc has no call in flight, in one
      short transaction per candidate under the line lock. Check everything
      again and reserve its bound.
   2. Call the provider with no lock held, once (`max_attempts=1`).
   3. Validate the answer and judge it as the officer would, still with no
      lock held.
   4. Settle in one short transaction: book; release, or keep a hold; read
      the row again; write the plan, the queued intents, the note, the state
      and the facts hash; send any waiting wake of the same Orc back to the
      render.
4. **The next tick.** Each queued intent is applied to the O arm (would
   mode), priced by `pricing.py`, or expired.
5. **The watchdog** (`orc_minds_watch` on `slow`, every 5 minutes). It
   raises the stall alarm, closes stale and backlogged wakes, marks
   wall-timed calls, expires the holds at 00:00 UTC, and sends Orcs to the
   care when the worker is silent.
6. **The grade** (hourly, after the idea dies). It counts and prices the
   mind.

#### 1.1.5 The rules

##### I. Gates and statuses

**A.1 The minds switch.**
- Add `orcs_minds` to the components list in core/platform_control.py,
  beside `orcs` (:320-325).
  - It is a System switch, OFF on arrival.
  - Its name is "Orc Minds (models in shadow)".
  - Its description: "Off (default). With orcs on and the Orcs' budget line
    set (ORC_DAILY_BUDGET_USD above 0), a model reads each Orc's wake in
    shadow and writes plans and proposals that are graded. Nothing it
    decides sends an order or moves a stop. Turning it on takes the PIN."
  - Add it to `BULK_ENABLE_EXEMPT` (:126-128; §4 Q1) and to
    `ORC_MIND_SWITCHES`: turning it on takes the trading PIN at /ops/ (N2;
    §4 Q0).
- The `orcs` switch keeps its name and its words. "Journals, no model"
  stays true of `orcs` alone (K-C1).
- The switch is read by `switches.minds_on()`, beside `orcs_on` in
  switches.py:14-28. An unreadable switch reads OFF.
- The tick never reads it.

**A.2 Four gates, read at every step.** A model call needs all four:
- the platform master (`platform_master`, "Global kill switch — disables
  ALL automated tasks", core/platform_control.py:133) ON;
- `orcs` ON;
- `orcs_minds` ON;
- `orc_line_cap() > 0` (spend.py:124-127), read through the gateway.

Each gate is read at admission (A.11), at each claim (A.18), in the gateway
immediately before the send (A.22), and by every `--yes` command (A.60). An
unreadable switch reads OFF. `guarded_task` reads the platform master only
when a task starts (core/task_gate.py:88-129), so without this an
`orc_think` run that began before a global stop would go on claiming for up
to `THINK_RUN_S`. `ORC_DAILY_BUDGET_USD` keeps its default of 0
(spend.py:79-81).

**A.3 Statuses** (they extend constants.py:351-357).
- The full set: `recorded`, `quiet`, `skipped`, `pending`, `running`,
  `done`, `refused`, `failed`, `late`, `stale`, `merged`.
- Each fits `max_length=12` (models.py:166) [P18].
- **Who writes what:**
  - The tick's `record` (wake.py:655-666) writes `recorded` with an empty
    `skipped_reason`. O1 wrote `skipped` with "no model before O2" there.
  - The render writes `quiet`, or `skipped` with a code.
  - Only scheduler.py writes `pending`. scheduler.py also writes `recorded`
    back on a pending wake it returns to the render (A.24).
- The pin at tests/orcs/test_orc_source_pins_o1c.py:69-74 becomes "pending
  is written by scheduler.py only, never in wake.py or the tick".

**A.4 Codes for `skipped`** (`skipped_reason`, 200 characters,
models.py:170):
- `platform_off`, `minds_off`, `orcs_off`, `line_off`, `total`, `line`,
  `deep_share`, `triage`, `inflight`;
- `day_cap`, `routine_cap`, `dollar_cap`, `spacing`;
- `dead`, `row_closed`, `over_budget`, `breaker`, `render_failed`, `paused`,
  `backlog`, `authority`.

The old value "no model before O2" (`WAKE_SKIPPED_REASON`,
constants.py:354) stays readable as the historical code `pre_o2`.

A `failed`, `late` or `stale` wake carries its cause in `skipped_reason` as
well: `wall_time` (A.55), `row_closed`, `dead`, the gate codes (A.26),
`worker_silent` (A.52, A.55).

Every code has fixed English words in `WAKE_CODE_WORDS`. `STATUS_WORDS`
(constants.py:356-357) gains one sentence per status:

| Status | Words |
|---|---|
| `recorded` | "recorded: its dossier is being written" |
| `quiet` | "nothing new: a code reading" (O1's) |
| `skipped` | "answered by code: {code words}" |
| `pending` | "waiting for its model call" |
| `running` | "a model is reading it" |
| `done` | "answered in shadow" |
| `refused` | "the answer was refused by the validator" |
| `failed` | "the model call failed" |
| `late` | "answered after the position closed: kept, applied to nothing" |
| `stale` | "not answered in time: the care holds" |
| `merged` | "merged into a newer wake" |

**A.5 A code answer is journaled** while the minds switch is ON.
- The entry has kind `budget` (constants.py:26), author `code`, and
  `card=False`. Its headline: "Answered by code: {code words}."
- The dollars go in the body only, never in the headline (X13).
- While the switch is OFF, no `budget` entry is written. The wake's own
  `wake` entry carries the status words, as in O1.
- **With `orcs` ON and `orcs_minds` OFF, the journal differs from O1's in
  exactly these ways:**
  - the tick writes `recorded` (A.3); W11 counts from any recorded wake, at
    the army type's cadence (A.50), because the tick cannot read the switch
    (A.1);
  - every rendered wake that is not quiet reads `skipped` with code
    `minds_off`;
  - the facts hash v2 (A.10) applies whatever the switch says, so F6's
    quiet share is measured before the minds go on;
  - no `budget` entry and no evidence fact is written, and no plan exists,
    so no plan watch fires (A.48).

  T2 pins exactly that list.

**A.6 Allowed values stay tuples** in constants.py, never `choices`
(constants.py:1-3; tests/orcs/test_orc_models.py:74-79).

##### II. From the render to `pending`

**A.7 The render pass admits, in three short transactions** (N8).
`render_queued` (wake.py:793-831) does three things for each wake. None of
them holds an Orc lock across the dossier render:
1. **`scheduler.absorb(wake)`** [P15], in its own transaction under the
   Orc's lock, which commits before the render. If the Orc has a `pending`
   wake, this newer wake absorbs it:
   - the newer wake takes the union of both wakes' reasons, by key, each
     reason keeping its own `urgent`;
   - it inherits the older wake's `queued_at` as
     `components["queued_at_inherited"]`;
   - the older wake becomes `merged`, with `components["merged_into"]` and
     `finished_at`.

   The merge runs BEFORE the render, so the survivor's dossier lists every
   reason, and its kind, its F6 test and its urgency are those of the union.
2. **`render_wake(wake)`** (A.8-A.10), in O1's own per-wake transaction,
   which takes the Orc lock only at its final `journal.append`
   (wake.py:777-789, :811-817).
3. **`scheduler.admit(wake, rendered)`** (A.11), in its own transaction. It
   takes the Orc lock for the status write only.

wake.py imports `scheduler` inside `render_queued`, never at module level.
`mind_gateway` imports `ai_agents` inside its functions. So the tick's
import path (observe → wake) never loads the gateway or the provider.

A render that fails keeps O1's `components.render = "failed"`. It also gets
`skipped` with code `render_failed` (wake.py:819-830) and never counts as
silence [P11].

**A.8 What the render adds** while the minds switch is ON.
- **`components["shared"]`**: the count of shared hashes,
  `render()["shared"]` (dossier.py:439; map_wakes §2.2 b).
- **`components["s"]`**: S's hash and version (A.28).
- **`components["vctx"]`**: the validation context, as of the dossier. It
  holds:
  - `allowed` and `why_not` (A.36);
  - the F5 items;
  - `candidates` [{id, action, level_ids}], after the F5 shrink;
  - `menu` [{id, kind, tf, side, price, stop, watchable}], the `for_idea`
    rows, at most 30:
    - `context_for` builds the idea's own rows with the row's cost fraction
      (`ghost._cf`: the metadata's `cost_fraction_charged`, else
      `risk_levels.round_trip_cost_fraction`; ghost.py:234-244). So BE is
      the entry plus its round trip, as its kind `breakeven_plus_cost`
      says (menu.py:333). Today dossier.py:267-268 passes none, and BE is
      the raw entry;
    - `watchable` is True when the level sits at least
      `PLAN_WATCH_MIN_ATR1H` = 0.5 × ATR(1h) from the closing-side mark
      (A.48);
  - `events` {C-n: {at, ccy}}: the prints within `PRINT_WITHIN_H` and the
    shuts within the type's `add_pre_shut_h`, each under its code id. PS1
    lists them (A.47);
  - `effective`; `atr` {1h, 4h}; `p`; `m`; `mark_fresh`;
  - `thesis_intact`: no invalidation met, no thesis-check exit within 24 h,
    no predicate met;
  - `plan_version`, `plan_at`;
  - the highest fact id;
  - `world`, `urgent`, `army_type`, `decision_tf`;
  - the gap per event code.

  The validator reads only this context, the journal and the Orc row's own
  counters (V2) [map_wakes trap 31].
- **P-HOLD stays unlisted in O2.** `context_for` passes no waiver
  (dossier.py:297-301), so the playbook never lists it
  (playbook.py:178-181). A lock_waive names candidate "none" (V4, V14).
- **The evidence facts** (A.46). They are written BEFORE `dossier.render`,
  so PS5 lists them.

The render stays for the reference family "sonnet" (wake.py:728). That is
r0's family, so O2a needs no family change.

**A.9 F6's reference** [P27; map_wakes trap 3].
- With the minds switch ON, `complexity.f6` compares the hash against
  `Orc.last_facts_hash` (models.py:102). Only a validated answer writes that
  column (A.40).
- With the switch OFF, it compares against O1's proxy
  `seen["answered_hash"]`, as O1 does (wake.py:744, :761-763).
- So a wake answered by code (for budget or a cap) never makes the next
  metronome wake quiet.

**A.10 The facts hash, version 2** (wake.py:123-138).
- It adds the plan's version and the watched levels, by their stored
  references (kind, tf, price; A.39), never by id alone [P27].
- It puts the distance to the next print in bands: over 24 h, 3 to 24 h,
  under 3 h. O1 counts whole hours, which makes F6 almost never quiet
  (map_ai §4.2).
- `FACTS_HASH_VERSION = 2` is part of the hashed input.

**A.11 Admission** (`scheduler.admit`). The first check that fails decides,
and every failure is a code with no call [P1]:
1. A quiet wake (F6, already decided by the render) stays `quiet`.
2. The platform master OFF → `platform_off`. `orcs_minds` OFF →
   `minds_off`. The line off → `line_off`. `orcs` OFF → `orcs_off`. Only
   the claim and the gateway can see the first and the last, because the
   render task does not run while either is OFF.
3. The Orc dead → `dead`. The row not OPEN or CLOSE_PENDING (wake.py:82) →
   `row_closed`.
4. The render `over_budget` (dossier.py:441) → `over_budget`.
5. The breaker open (A.56) → `breaker`.
6. A day cap reached (A.12) → `day_cap`, `routine_cap` or `dollar_cap`.
7. The triage ceiling reached, counting the money in flight, the holds and
   this wake's bound (A.13) → `triage`. The Orcs' unbooked money past the
   core's floor (A.18) → `inflight`.
8. Spacing (A.15) → `spacing`.
9. Otherwise → `pending`:
   - `dedupe_key = "orc<pk>:pending"`. The existing constraint
     `orcwake_one_pending_per_key` (models.py:180-185) then holds one
     pending wake per Orc at the database (map_wakes trap 1).
   - `components["record_key"]` keeps the tick's own key.
   - `queued_at` = the inherited first send, or now [P9].
   - `priority` = the triage rank (A.14).
   - `components["rung"] = "r0"` and `components["bound"]` = A.21's bound.

**A.12 Per-Orc day caps** [P5; recovered fix 1].
- **The count cap.** `caps_for(day_class, real)` (weather.py:37-42) gives
  model wakes a day.
  - Real money: 12, 14 or 16 by calm, eventful or stormy.
  - Paper and demo: 6. O1 displays 12; O2a changes `WAKES_PER_DAY["paper"]`
    (weather.py:31-32), see §4 Q4.
  - The cap is computed per Orc, with that Orc's own `real`, and never read
    from `OrcDayBaseline.caps`. That row holds whatever the first reader's
    `real` produced (weather.py:160-219; tasks.py:177; map_wakes trap 12).
- **The dollar cap.** OrcSetting `per_orc_daily_usd`: real money $2.00,
  paper and demo $0.50. A wake is admitted, and claimed, only while

  ```
  spend_today_usd + seen["unbilled_usd"]
    + Σ HIGH(rung) over the Orc's calls in flight + HIGH(this rung)
    ≤ per_orc_daily_usd
  ```

  - HIGH is §2.2's high column: h0 $0.0025, r0 $0.0594, r1 $0.1294, r2
    $0.1789, r3 $0.2989, r4 $0.5389, r5 $1.8644. After the first week each
    rung's measured p90 cost replaces it (OrcSetting `per_orc_high`, §2.7).
  - `seen["unbilled_usd"]` is Σ HIGH of the Orc's calls held without a bill
    today (A.25, A.55). It resets with the counters.
  - The line and the triage keep the full bound (A.13). So an Orc's cap can
    be passed only by one call's excess over its HIGH estimate, and never
    the line. In the simulated routed day this gives at most $1.98 for a
    real Orc and $0.50 for a paper one, and a paper Orc can still take r3
    early in its day (calc/cost_lens_routed_fix.py).
  - Counting the full bound here instead would bar every paper r3 and r4
    wake ($0.71 and $0.87 even without the fallback, against $0.50) and
    every r5 ($2.69 against $2.00), and would stall real Orcs near $1.3-1.7
    on stormy days. Counting nothing would let the day's last call pass the
    cap by its whole cost.
  - No ticket is charged to an Orc's dollar cap: each ticket caller has its
    own day cap (§1.0.9).
- **The routine sub-caps.** A wake is routine when every one of its reasons
  is W2, W11 or a plan watch (A.48). Routine wakes may use at most
  `routine_share` = 75% of each cap (`routine_wakes_today`,
  `routine_spend_today_usd`). They are checked AS WELL AS the whole-day caps,
  never instead of them.
- **The counters.** `llm_wakes_today` and `routine_wakes_today` are written
  at the claim. `spend_today_usd` and `routine_spend_today_usd` are written
  at the settle. All four under the Orc's lock (models.py:103-109).
- **Which wakes stop where:**
  - a non-urgent wake stops at either whole-day cap, even when urgent wakes
    used them, with code `day_cap` or `dollar_cap`;
  - a routine wake also stops at its sub-cap, with code `routine_cap`;
  - a real-money urgent wake may pass the count cap, but never the dollar
    cap, its triage ceiling or the line;
  - a paper urgent wake stops at both caps;
  - a plan watch is never urgent (A.48), so it stops at every cap.
- **One call in flight per Orc** (A.18) keeps the in-flight term to one
  call.
- **The day** is the UTC day, the same as the line's (spend.py:143-146).
  The counters reset lazily: `seen["counters_day"]` holds the UTC date, and
  when it differs, all four reset under the lock before use (§4 Q7). The day
  class that picks 12, 14 or 16 is the trading day's (constants.py:371).

**A.13 The triage ceilings** [P6; recovered fix 2].
- Every check uses the same sum: the Orcs line's booked spend today, plus
  the reservations of the OTHER calls and tickets in flight, plus the holds
  (A.25, A.55), plus this call's bound. That sum must stay within this
  call's class ceiling.
- **The ceilings in O2.** With cap C and R = min($1.00, 0.2 × C):

  | Class | Ceiling |
  |---|---|
  | real-money urgent | C (the whole line) |
  | real-money non-urgent | C − R |
  | paper urgent | 0.60 × C |
  | paper non-urgent | 0.45 × C |
  | post-mortems and the council of war (tickets, A.57) | 0.30 × C |

  - R ≤ 0.2 × C, so C − R ≥ 0.8 × C. The ceilings therefore never invert,
    at any cap. At $6: 6.00, 5.00, 3.60, 2.70 and 1.80.
  - Probes reserve against an allowance of their own (B.11). The other
    tickets take the class §1.0.9 gives them.
  - Under the bound and the money in flight, every class ceiling is in
    effect lower than its figure: by about $0.39 on r0 (one call in
    flight), by $1.4-1.6 on the Opus rungs (§2.2).
- **Why R is small in O2.** In shadow a real-money urgent wake on r0 costs
  about $0.044 (bound $0.197), so the day's late urgent demand is well under
  $1. The O1-era reserve, min($3.00, 0.4 × C), held back 40% of a small line
  for it: at C = $5 it cut paper wakes from 08:14 UTC and real routine wakes
  from 16:10 UTC, and a central calm day spent only $3.29 of the $5.00
  (calc/cost_lens_sim.py). A reserve that decays over the UTC day was tried
  and rejected: on a stormy day with a 19:00 UTC print it starves the late
  real urgent wakes (calc/cost_lens_variants.py). R returns to
  min($3.00, 0.4 × C) when O3 binds (§3).
- **R is the Orcs' own reserve, inside their line.** `ORC_LIVE_FLOOR_USD`
  ($3.00, spend.py:84) is O0's, and O2 leaves it as it is. It is held back
  from the CORE line while the Orcs line is on (spend.py:28-31, :82-84,
  :157-170; map_wakes trap 10), whatever R is inside the line. It also
  covers the Orcs' unbooked money (A.18's `inflight` rule). OrcSetting
  `triage` holds the shares and R's cap (§4 Q5).

**A.14 Triage rank and money world** [P6, P7].
- **The rank:** 3 for real urgent, 2 for real non-urgent, 1 for paper
  urgent, 0 for paper non-urgent. `priority` = the rank. The claim takes
  wakes in the order −priority, `queued_at`, id.
- **"Real"** means both:
  - `Orc.seat.venue == "live"` (constants.py:39-46);
  - and `dashboard.position_summary.world_of(row) == "live"`
    (dashboard/position_summary.py:253-270).

  A demo row, a paper row and a row that states no world (`""`) are all
  budgeted as paper. `birth.world` maps `""` to live (birth.py:126-135), so
  it is never used for the budget (§4 Q6).
- **"Urgent"** means any reason is urgent (wake.py:141-145), read on the
  survivor after a merge [P15]. A reason with `source: "plan"` never makes
  a wake urgent (A.48).

**A.15 Spacing** [P12; recovered fix 5].
- A non-urgent wake needs `MIN_WAKE_SPACING_MIN` (15 minutes,
  constants.py:257) since `Orc.last_wake_at`, the last CLAIMED model wake.
  `last_wake_at` is written at the claim.
- The check runs at admission and again at the claim.
- Urgent wakes are exempt.

**A.16 No wake is deferred; a cold model's first call runs alone.**
- A wake is answered by code, merged, or `pending`. Nothing waits outside
  `pending`, and the stall and stale clocks (A.54-A.55) apply to `pending`
  only. That designs P14 out by construction.
- **The cold-burst rule** (map_ai §2.2 item 9). When no call on a model has
  STARTED in the last 55 minutes, the claim takes one wake alone for that
  model and holds the second worker until that call returns. A cache entry
  is readable only once the first response begins streaming, and the
  provider has no first-token hook. Urgent wakes are never held. A held
  wake stays `pending`: it is never closed for this, and A.55's busy rule
  keeps it from counting as silence.
- **Why.** The 4h fleet wakes in bursts at the W2 closes (00:12, 04:12, ...
  UTC) and around the prints, often more than an hour apart, so many
  bursts start cold. At concurrency 2 both first calls of a cold burst write
  S and MK: 12,335 × ($4.00 − $0.10) per MTok = $0.048 each. The simulated
  10-Orc day has about 15 cold writes without the rule ($0.72 a day) and
  about 9.5 with it ($0.47) (calc/cost_lens_checks.py, check 2).

##### III. The queue, the claim, the call, the settle

**A.17 The `orcs` queue and its worker** [P4].
- **The task:** `tasks.orc_think`, `@shared_task @guarded_task("orcs")`
  (core/task_gate.py:88-140).
  - It is routed by exact name to `orcs` (config/celery.py:96-115). The O1
    tasks stay where they are.
  - Its beat, "orc-think", runs every 60 s with expires 55 s
    (`expire_seconds` beside it).
  - The render pass sends one ticket after a pass that admitted any wake.
  - With the minds switch OFF, it closes every pending wake with code
    `minds_off` and returns `{"idle": ...}` (tasks.py:13-15).
  - Its result never names a `skipped`, `parsed` or `attempted` key
    (census.py:25-27; map_wakes trap 19). For example:
    `{"status": "success", "thought": n, "by_code": m}`.
- **The worker:** deploy/docker-compose.yml gains `worker-orc`:
  `celery -A config worker -l info -Q orcs -c 2 --without-gossip
  --without-mingle`, with worker-fast's healthcheck (:163-175).
- **The watchdog:** `tasks.orc_minds_watch`, `@guarded_task("orcs")`, every
  5 minutes, routed by exact name to `slow` (N8). It runs A.54-A.57's steps
  and returns their counts (stalled, stale, backlog, wall-timed, holds,
  breaker, ledger gaps), never a `skipped`, `parsed` or `attempted` key.
- **A config test** parses docker-compose.yml and proves that every queue in
  `task_routes` has a consumer.

**A.18 The claim** (`scheduler.claim`): one short transaction per examined
candidate (N8).
- **Locks, always in this order:** the line lock (`select_for_update` on
  OrcSetting `minds_lock`), then the candidate's Orc row with
  `select_for_update(skip_locked=True)`, then the wake. A candidate whose
  Orc row is locked (the tick, a close) stays `pending` for the next claim.
  Both locks are taken under N8's 2 s timeout.
- **The lock row** is created with `get_or_create`, with one retry on
  `IntegrityError`.
- **Pick** the best pending wake (A.14) whose Orc has no running wake: one
  call in flight per Orc. A pending wake of an Orc with a running wake
  stays `pending`. Its stall and stale clocks run, and it is never closed
  for this: the running wake's settle sends it back to the render (A.24).
- **The cold-burst rule** (A.16): while the first call on a cold model is
  running, a non-urgent candidate on that model waits.
- **Check again everything of A.11 steps 2-8**, with the money in flight
  and the holds, plus the line (A.20).
  - A failed check ends that wake `skipped` with its code and commits. The
    claim then tries the next candidate.
- **The core's floor covers the Orcs' unbooked money.** A claim is refused
  with code `inflight` when the bounds of the calls and tickets in flight,
  plus the holds, plus this bound, would pass `ORC_LIVE_FLOOR_USD` ($3.00).
  The core line subtracts only the Orcs' booked spend and that floor
  (spend.py:157-170), so this keeps the whole within the total. Without it,
  two real-money worker calls on r4 and r3 ($2.57 with their fallbacks) and
  a smoke on r4 ($0.87) would hold $3.44 in O2b.
- **On a pass:**
  - status `running`, `started_at` = now (models.py:171);
  - `est_usd` = the bound (models.py:168-169);
  - `model` = the rung's model id, read from the gateway;
  - `Orc.last_wake_at` = now;
  - `llm_wakes_today` += 1, and `routine_wakes_today` += 1 for a routine
    wake.
- **Commit.** The call follows with no lock held.

**A.19 One run** claims and thinks one wake at a time. It stops when nothing
can be claimed, or when 100 s have passed since it started
(`THINK_RUN_S`). Each claim reads the four gates again, the platform master
included (A.2).

**A.20 Ask the line, with the money in flight** [P2].
- `mind_gateway.ask_line` classifies first, then asks:
  - a cap at or under 0 gives `line_off`;
  - the whole AI budget spent gives `total` (spend.py:241-243);
  - otherwise it calls `can_spend(tier=MODELS[model]["tier_hint"],
    estimated_usd=<this bound + the in-flight money>, line="orcs",
    deep_share_exempt=<real urgent>)`. A refusal gives `line`, or
    `deep_share` when the reason names the deep-tier reserve
    (spend.py:264-272).
- **The in-flight money** is the sum of `est_usd` over the OTHER running
  wakes, plus the other open tickets and the holds in OrcSetting
  `minds_inflight`. A claimed wake's or a reserved ticket's own reservation
  is excluded, so no call is refused because of itself.
  - Pass the tier honestly (map_ai §1.5: the debate's "fast" for an Opus
    call is the counter-example).
  - Never rely on the default estimate (spend.py:208; map_wakes trap 8),
    and never pass `total_only` (N3).
- r0's tier is "balanced", so the deep share never applies in O2a.

**A.21 The bound, one send, the rung limits and the wall time** (N4).
- **The bound:**

  ```
  bound(rung, est) = catalog.cost_usd(model,
                         input_tokens=0,
                         cache_write_1h=ceil(est x 1.35),
                         output_tokens=max_tokens)
                     + the same for the fallback model at its own max_tokens,
                       where a fallback is sent (B.14)
  ```

  - `est` is the estimate of the exact text sent: a wake's render
    `components.tokens`; a ticket's `dossier.estimate_tokens` × the family
    factor (A.57).
  - `cost_usd` is at catalog.py:431.
  - The 1.35 is the smoke's tokenizer headroom (claude_smoke.py:375-384).
  - r0 at O1's end-of-day estimate is $0.197 (calc; §2.2).
- **One send per call.** The gateway sends every Orc call with
  `max_attempts=1` (A.22). Without it the provider re-sends the whole
  request once after any error whose text names `overloaded`,
  `internal_server_error` or `api_error`, mid-stream ones included, and
  reads only the final attempt's usage (claude_provider.py:14-20,
  :471-493). A cut attempt may still be billed (map_ai §2.1 item 6), so one
  reserved call could bill about twice its bound while the ledger showed
  one. A mid-stream error now ends the call: the wake is `failed` and its
  bound stays held (A.25). The SDK's own retries stay: they happen before
  any token streams (2 retries on 408, 409, 429, 5xx, connection errors and
  timeouts).
- **`RUNG_LIMITS`** lives in constants.py, with no model id:

  | Rung | `max_tokens` | `timeout_s` |
  |---|---:|---:|
  | h0 | 8,000 | 120 |
  | r0 | 8,000 | 120 |
  | r1 | 16,000 | 180 |
  | r2 | 16,000 | 180 |
  | r3 | 24,000 | 300 |
  | r4 | 32,000 | 600 |
  | r5 | 32,000 | 600 |

- **Fallbacks.** From O2b, only real-money wakes on r2-r5 send one, in the
  list form (B.14). O2a's r0 has none: a refusal is a billed failure
  (map_ai §6).
- **Wall time:** `WALL_S(rung) = 3 × timeout_s + ceil(max_tokens / 20) +
  60`. That is three pre-stream tries (`timeout_s` is an httpx stall
  timeout, never a cap on a live stream: map_ai §1.1) plus a live stream at
  20 tokens a second. h0 and r0: 820 s; r1 and r2: 1,400 s; r3: 2,160 s; r4
  and r5: 3,460 s. It sets a wake's status only and never releases money
  (A.55).

**A.22 The gateway** (`mind_gateway.py`). It is the only module that names
`ai_agents` or `anthropic`. It provides:
- **`rung(name)`**: the model id, the effort and the tier, read from
  `catalog.ORC_LADDER_V1` (catalog.py:505-520) by name.
- **`CALLER_RUNGS`**: `{"wake": ("r0",), "smoke": ("r0", "h0")}`. Later
  commits extend it (§1.0.9). Any other rung raises `ValueError` before
  anything is sent.
- **`ask_line`, `bound`, `line_cap`, `line_spent`, `line_summary`** (the
  last is `spend.lines_summary`, spend.py:297-325).
- **`measure_tokens`**, for `orcs tokens` (A.61). It calls the provider's
  `count_tokens` and never `complete()` (N3's one exception).
- **`call(...)`**: `ClaudeProvider().complete(..., max_attempts=1)`.
  - The variable must be named `provider`, for the completeness scan
    (tests/test_llm_ledger_truth.py:282-297).
  - The site is registered in `BYPASS_SITES` (:48-63), with `agent_name=`
    within 500 characters of the call.
  - It reads the four gates (A.2) again just before the send.
  - It refuses to send, with code `authority`, while any OrcSeat reads
    `level > 0` (A.29).

Nothing else in the package imports `ai_agents`. The pin of
tests/orcs/test_orc_switch_off.py:427-456 is widened to allow this one file
only. It still forbids the order path there.

**A.23 The call's keywords** (claude_provider.py:333-351, :383-415):

| Keyword | Value |
|---|---|
| `system_blocks` | `[{S, "1h"}]` |
| `shared_user_blocks` | MK0, the closed sessions, MK-E, IN-slow: the texts of `block_hashes[:shared]` (`dossier.text_of`, dossier.py:141-147) |
| `private_user_blocks` | `[{PS, None}, {tail, None}]` |
| `turn_effort` and `effort` | see the effort rule below |
| `output_schema` | `validator.SCHEMA_V1`: one object for every Orc and every model |
| `max_tokens`, `timeout_s` | from `RUNG_LIMITS` |
| `max_attempts` | 1 (A.21) |
| `fallbacks` | None on r0; from O2b, B.14 |
| `agent_name` | `"orc"` |
| `source_ref` | `f"Orc:{orc.pk}:Wake:{wake.pk}:{rung}"` |
| `line` | `"orcs"` |
| `client_refusal_rerun` | False |
| `record` | True |

- **The cache breakpoints.** In the shared turn, put a 1h breakpoint on the
  last CLOSED session block (on MK0 when no session has closed yet) and
  another on MK-E. IN-slow gets none in O2a. With S, that makes 3 of the 4
  allowed (claude_provider.py:49; map_ai §2.2).
- **The effort rule.**
  - The effort-only message is used only when both hold:
    - `catalog.supports_per_message_effort(model)`;
    - OrcSetting `smoke_verdict` records a PASS for the model's family
      (A.61): `claude_smoke --yes` printed PASS for it, its four checks
      together. The check that proves the message governs the private turn
      is the effort check (B's output at least twice A's,
      claude_smoke.py:23-28); a cache read alone would pass the bug where
      the message governs nothing.
  - Then `turn_effort` = the rung's effort, and the top-level `effort` is
    pinned at `catalog.default_effort(model)` (catalog.py:475).
  - Otherwise there is no `turn_effort`, and the top-level effort is the
    rung's own. Without this, a message that governs nothing would run
    every r0 wake at Sonnet's default high effort (catalog.py:183) while
    the card said "low effort", at about $0.079 a call against $0.044.
  - Either way O2a calls one model at one effort, so the cache key is
    stable.

**A.24 The settle** (`scheduler.settle`). Validation and the officer
(A.30-A.38) run first, with no lock held (N8). Then one short transaction
under the Orc's lock, on every outcome:
1. Book the usage on the `decision` or `error` entry's columns: `model`,
   `tokens_in`, `tokens_out`, `cache_read`, `cache_write`, `cost_usd`
   (models.py:206-211).
2. Add the cost to `spend_today_usd`, and to `routine_spend_today_usd` for a
   routine wake.
3. **Release, or hold.**
   - Release (`est_usd` = 0) only after confirming the provider's ledger
     row: one lookup of an AgentTask whose `structured_output__source_ref`
     equals this call's `source_ref`, created since `started_at`.
   - If none exists, the provider failed to write it: it fences that write
     and only logs that the daily budget now undercounts
     (claude_provider.py:616-641), while the line reads AgentTask alone
     (spend.py:143-154). The reservation then becomes a hold of the booked
     cost (kind `ledger_gap`, until 00:00 UTC), and the watchdog raises
     `minds_ledger_gap`.
   - A call without a bill keeps its bound held (A.25).
4. `finished_at` = now, the answer's time. The render's as-of moment stays
   in `components.as_of` (map_wakes trap 2).
5. Read the row again (A.26). Then the status (A.25) and the writes of
   A.39-A.41.
6. **Send back a waiting wake.** A pending wake of the same Orc (A.18) goes
   back to the render: status `recorded`, `components.render = "queued"`,
   `components.journal_as_of` = now, `queued_at` kept. The next render pass
   renders it again, still as of its own moment for the market, the price
   and the care, but reads the Orc's own journal (PS3, PS5) up to
   `journal_as_of`. So its dossier holds the decision that just landed, and
   F6 may now make it quiet (A.9). Its `components.as_of` never moves: a
   moved as-of would judge the detection's price stale (`MARK_MAX_AGE_S`,
   120 s) and push the answer under F5.

**A.25 The outcomes:**

| What came back | Status | Notes |
|---|---|---|
| a success with `stop_reason` `end_turn` | `done` or `refused` | after validation (A.31) |
| a `max_tokens` stop with some text (claude_provider.py:669-670) | `refused` | V1, "cut off at its bound" |
| a `RuntimeError` carrying `.usage`: a refusal, `max_tokens` with no text, an empty answer (claude_provider.py:643-650, :655-719) | `refused` | V1; its cost is booked [P8] |
| a `ValueError` from `build_request` (nothing was sent) | `failed` | an `error` entry carries the message; the bound is released at once |
| a timeout, a network error, or a provider error without `.usage` (the final "overloaded" RuntimeError, claude_provider.py:482-487) | `failed` | nothing is written to the ledger, and the bound stays held in `minds_inflight` as kind `unbilled` until 00:00 UTC: Anthropic may bill the tokens generated before a cut (map_ai §2.1 item 6). The wake is still counted (A.12) [P8] |

**The holds** (kinds `orphan`, A.55; `unbilled`; `ledger_gap`, A.24):
- they count in every in-flight sum of the line (A.13, A.18, A.20);
- the `orphan` and `unbilled` holds also count, as HIGH, in the Orc's
  `seen["unbilled_usd"]` (A.12). A `ledger_gap`'s cost is already in the
  Orc's `spend_today_usd`, so it is not counted there twice;
- a late settle with usage books the real cost and drops its hold;
- every other hold expires at 00:00 UTC, never earlier;
- `orcs status` and /orcs/ for staff show "held for calls without a bill:
  $x".

The ledger stays the truth of what was measured: nothing is invented in
AgentTask. Only the line keeps the money reserved.

**A.26 Read the row again after the call** [P16].
- Under the Orc's lock, check:
  - the row is still OPEN or CLOSE_PENDING;
  - the Orc is alive;
  - all four gates are still ON.
- If any check fails:
  - book the cost (A.24);
  - journal the decision as late, with code `row_closed`, `dead`, or the
    code of the gate that is OFF (`platform_off`, `orcs_off`, `minds_off`,
    `line_off`);
  - set status `late`;
  - write no intent, no plan, no note, no `last_good_wake_at`, no
    `last_facts_hash` and no state change.

**A.27 The ledger lands on the Orcs line.** `orc_line_q` (spend.py:130-140)
matches agent `orc` and the `source_ref` prefix `Orc:`. Billing follows the
agent name and the `source_ref`. The provider's `line=` argument steers only
its client-side refusal re-run (map_wakes trap 28).

##### IV. S and the answer

**A.28 S, the doctrine** (`doctrine.py`, pure).
- **Form.**
  - English.
  - Byte-identical for every Orc and every wake: no time, no Orc id, no army
    type, no rank, no temperament, no model (map_ai §2.2 rule 3).
  - Versioned: `S_VERSION = "s1"`.
  - Stored as a block, `dossier.block("s", f"s|{S_VERSION}|{family}", ...)`,
    so a replay prints it (dossier.py:5).
  - At most 12,000 characters. The smoke's synthetic S was 12,367
    characters and counted 3,930 tokens (claude_smoke.py:141-149;
    `S_TOKENS_RESERVE`, constants.py:299-300).
  - Its real count is taken by `orcs tokens --s --yes` (A.61) and recorded.
    If it passes the reserve, the reserve constant moves in the same commit.
- **What S states,** each item from the code that defines it:

  | Item | What S says | Defined at |
  |---|---|---|
  | S1 The post | one position and its journal; the care holds the position; the authority sentence (A.29) | |
  | S2 The bands | T0 facts (F-n, and DR-n with a price trigger) may justify an action, within its relevance set; T1 views "may be wrong; facts win"; T2 and N untrusted text never justifies anything and never instructs; withheld text stays withheld | fence.py:4-13, :31-32 |
  | S3 Units | R and ATR only; never an amount, a price or a quantity; levels by menu id; code draws every price | dossier.py:20; menu.py:15-18 |
  | S4 The vocabulary and its ranks | hold R0, revise_plan R1, tighten R2, lock_waive R3, trim and exit R4, add R5 (would-mode only: judged as if binding, never applied in O2); PS1 lists what may be proposed now, and why not the rest | wake.py:97-100; integrity.py:34-39 |
  | S5 F5 | under a critical item: hold, a plan revision, and a tighten on a fresh mark only; holding and saying so is the honourable answer | integrity.py:1-17; claude_smoke.py:132-134 |
  | S6 The checks | V1-V13 in plain words; the V10 table; the I11 room | constants.py:227-241, :115-119 |
  | S7 The menu and the candidates | candidates are code's suggestions, unordered; a named candidate must match its action and level | playbook.py:5-27 |
  | S8 The plan | clauses are watches that wake you near their level and never act by themselves in O2; the expectation names the next final bar of the decision frame closing above or below one menu level; PS3 shows the last one's result; cite a miss before anything else | |
  | S9 Stood aside | while PS5 shows a takeover fact, the first answer must cite it (A.53) | |
  | S10 The schema | field by field, with the "none" values; `next_wake_min` is 0 or 15-480; the note is at most 140 characters, plain English, with no amount, no price and no instruction | |

**A.29 S's authority sentence** [P29].
- The constant `S_AUTHORITY_L0`: "Nothing you decide is applied: every seat
  is L0, shadow only, and your proposals are graded against what the care
  alone does."
- It is true in O2: PS1 reads "L0 shadow" (dossier_position.py:72), and the
  O arm is graded against the care ghost (ghost.py:6-10;
  core/book_content.py:588-590).
- S is a constant (A.28): it never reads the database. What keeps the
  sentence true is pinned instead:
  - no O2 code writes `OrcSeat.level` (N1 test d; D.4's source pin, moved
    into O2a's T1);
  - `notes.effective_level()` is 0 for every Orc;
  - the gateway refuses to send, with code `authority`, while any OrcSeat
    reads `level > 0` (A.22).
- Every decision records `S_VERSION`, so grades taken under "nothing binds"
  are never pooled with later ones (A.58).

**A.30 The answer schema** (`SCHEMA_V1` in validator.py,
`SCHEMA_VERSION = "d1"`).
- **It follows the raw API's rules** (map_ai §0 item 5, §2.3):
  - `additionalProperties: false` on every object;
  - every key required, with no optional key and no union type;
  - no `minimum`, `maximum`, `minLength`, `maxLength` or `multipleOf`;
  - no field named `reasoning`, `thinking` or `trace` (that draws a billed
    `reasoning_extraction` refusal);
  - no per-Orc enum. Changing the format invalidates the cache, so code
    checks the ids after the answer.
- **The fields:**

  ```
  action          string, enum [hold, revise_plan, tighten, exit, trim, lock_waive, add]
  candidate       string                     # a playbook id, or "none"
  level_id        string                     # a menu id, or "none"
  risk_share      string, enum [none, half, full]   # add only; RISK_SHARES (constants.py:69-74)
  facts_cited     array of string
  event_id        string                     # a C-n code listed in PS1 (vctx.events), or "none"
  plan_clauses    array of {kind: enum [tighten, trim, exit, add],
                            level_id: string,
                            trigger: enum [touch, close_beyond]}
  expectation     {kind: enum [none, closes_above, closes_below], level_id: string}
  next_wake_min   integer                    # 0 = no request
  note            string
  ```

  The keys follow those the fence already treats as an action's
  (fence.py:57-58).
- **The model names ids; code stores prices.** A menu id names a price only
  within one build of the menu: ids are re-ranked by distance at every
  build (menu.py:15-18, :145-146, :186-191). So every level the answer names
  is stored as a reference {level_id, kind, tf, price, stop}, copied by
  code from that wake's `vctx.menu`: in the plan's clauses, the watches,
  the expectation, the intents and, from O2c, the Captain's orders. Every
  later use reads the stored price and never resolves the id again
  (A.39).
- **A trim always banks `TRIM_SHARE = 0.5`** of the open size.
- **The shape check is hand-written,** like `claude_smoke.validate_decision`
  (claude_smoke.py:310-332). `jsonschema` is not pinned.

##### V. The validator

**A.31 Order and classes.** The rules run in the order of the table below.
There are three classes of outcome:

| Class | Rules | Effect |
|---|---|---|
| Whole answer refused | V1-V8, V10, V12, V13, V14 | the wake is `refused`; no plan, no intent in shadow (a proposed act is stored with mode `refused`), no note on the card; it counts toward A.52's refusal rule |
| Part refused | V9 (the `next_wake` is dropped); V11 (the note is withheld) | the rest of the answer stands; it is counted and journaled, but not toward the care rule |
| The officer's would-refusal (A.37) | I-rules | the intent's mode is `refused`; it counts toward A.52 |

**A.32 The V-rules.** V2, V6 and V10 keep the meanings the code and the
recovered notes give them. The other numbers are this spec's.

| Rule | What it checks | Hook |
|---|---|---|
| **V1 Complete** | `stop_reason == "end_turn"`; the text is a JSON object; exactly the schema's keys, types and enums | claude_provider.py:669-670; map_ai §2.3 item 3 |
| **V2 Plan rate** ("rule 2") [P19] | `plan_changes_24h` holds each change's time; entries older than 24 h are dropped on every read and write. Every change in the window counts. A non-urgent wake may change the plan only while the window holds fewer than `PLAN_CHANGES_24H_MAX` = 2 changes; an urgent wake may change it past the limit. A wake whose only urgent reasons come from the plan (A.48) is not urgent here. The first plan (version 0) is exempt. V2 reads the Orc row's `plan_changes_24h` at validation, never the dossier's copy | models.py:85 |
| **V3 Allowed** | the action is in `vctx.allowed`, the officer's list with F5 applied | A.36; dossier.py:333-334 |
| **V4 Candidate** | `candidate` is "none" or one of `vctx.candidates`, after the F5 shrink; a named candidate's action and level must match. P-HOLD is never listed in O2 (A.8), so a lock_waive names "none" | integrity.py:29-31, :119-133 |
| **V5 Level** | `level_id` may be "none" only for hold, revise_plan, a market exit and a lock_waive; otherwise it must resolve on `vctx.menu` | menu.py:293-300 |
| **V6 Reached** [P21] | an exit or a trim while `vctx.thesis_intact` must name a level whose `level_reached` fact (A.46) exists by the wake's as-of moment, and must cite that fact. The fact's (kind, tf, price) must equal the named level's in `vctx.menu`, to the instrument's precision: an old fact on an id that now names another pool fails. Naming an unreached pool or target fails | fence.py:33-37; menu.py:15-18 |
| **V7 Stop room (I11) and tighten only** [P33] | a tighten's would-stop is the named level's own `stop`, beyond the crowd. For BE it is the BE row's price, the entry plus its round trip (A.8). A tighten naming CARE or EFF is refused: those are the care's own stops, with no stop of their own (menu.py:314, :333-344). The would-stop needs at least `MIN_STOP_ROOM_ATR` × ATR(tf) from both p and m, at most `MAX_LEVEL_DIST_ATR4H` × ATR(4h) from m, and must be strictly tighter than `vctx.effective` | menu.py:111-126; constants.py:115-119; playbook.py:88-96, :176 |
| **V8 F5** | with F5 items present: only hold, revise_plan, and tighten when `vctx.mark_fresh`. It overlaps V3 on purpose, so the refusal names F5 | integrity.py:102-116 |
| **V9 next_wake** [P23] | 0, or 15 ≤ n ≤ 480 minutes (`MIN_WAKE_SPACING_MIN` to 2 × `W11_METRONOME_H`); otherwise the request is dropped with a refusal entry | constants.py:257, :319 |
| **V10 Relevance** [P20] | `fence.v10_satisfied(kind, cited, facts_index, symbol, event=event_id, since=plan_at for a plan)`. A lock_waive therefore needs a gap or calendar fact of its own event (fence.py:197-199 checks the event only when one is passed). The refusal carries V10's reason in the validator's own words, never "advisory to the phone" | fence.py:169-204; constants.py:227-241 |
| **V11 Words** [P22] | the note through `plain.voice(note, row_marks(row))` with the widened filter (A.34), then `fence.quarantine` and `fence.sanitize`, cut at `FENCE_CAPS["note"]` = 140. A note with more than 20% of its letters outside Latin-1, measured before `fence.sanitize` (which folds the text to ASCII, fence.py:15-17), is refused. A withheld note is replaced by the withheld words | plain.py:19-42; fence.py:62-94 |
| **V12 Plan structure** [P24] | for revise_plan: 1 to `PLAN_CLAUSES_MAX` = 4 clauses; each kind in the clause enum; each level on the menu and `watchable`, at least `PLAN_WATCH_MIN_ATR1H` = 0.5 × ATR(1h) from the closing-side mark at plan time (PS12 marks each row, A.47); an add clause only while the officer lists add. For any other action, `plan_clauses` = [] | A.48 |
| **V13 Expectation** | `kind` none, or `closes_above` or `closes_below` with a level on the menu | |
| **V14 Event** | a lock_waive needs an `event_id` in `vctx.events`; every other action needs `event_id` "none" | A.8; constants.py:238 |

**Where P24's checks run.** A plan clause is a watch, never an act. Its
structure is checked at plan time (V12). When its level comes near, it wakes
the Orc (W3, A.48), and the model's answer at that wake goes through V1-V13
and the officer like any other answer. No clause acts by itself in O2 (§3).
That is why the lost "C14" is dropped (map_pitfalls P24).

**A.33 Refusals are journaled, counted and shown** [P20, P26].
- Each refusal is a journal entry: kind `refusal`, author `code`, body
  {rule, part, words, wake, decision}. Headline: "Refused by the validator
  ({rule}): {fixed words}." An officer refusal reads "Would be refused by
  the officer ({rule}): ...".
- The intent, if there is one, is stored with mode `refused` and its rule.
- Refusals are counted in `OrcGrade.n_refused` and the invalid-output rate
  (A.58).
- Every refusal since the previous model-answered wake (`done`, `refused`
  or `late`) appears in the next model wake's PS5 (A.47). A wake answered
  by code in between never swallows one [P26].
- Budget, cap, spacing, triage and switch answers are never refusals [P17].

**A.34 The money filter is widened at the platform, once** [P22, N5].
- **Widen `dashboard/plain_words.py`**, never a private regex, so every
  surface judges a line alike:
  - `MONEY_WORD` gains "P/L" (:73-79);
  - the money verbs gain up, down and made (:86-89), next to a figure;
  - "unrealized", "floating" and "the account is at";
  - every ISO currency code next to a figure, not only `_CODES` (:40);
  - "grand", "k" and "K" after a figure;
  - spelled-out amounts ("fifty thousand", "half a million").
- **One table-driven test** holds every form in map_pitfalls P22: the forms
  that pass today must now be withheld, and the forms withheld today must
  stay withheld. The known false positive on the safe side (a grouped price
  with two decimals) stays withheld.
- **The same table has a "must pass" column.** The Orc's own R language
  must keep passing, or its notes are withheld: up, down and made beside an
  R, ATR, pip or percent figure, for example "up 1.2R", "down 0.5R since
  entry", "made 0.8R on the trim", "0.4 ATR below the level", "down 12
  pips", "up 0.6%". The existing plain_words tests stay unchanged.
- **The filter runs at write time,** before any of these can hold the text:
  `latest_note`, the journal, the card, the pages, Telegram, the next PS5.

**A.35 The facts index for V10** (map_wakes §2.2 g).
- It is built at validation from the Orc's journal entries that have a fact
  id, up to the wake's as-of moment: `{id: {kind, symbol, at, event,
  drum_kind}}`.
- `kind` = `fence.fact_kind(entry)` (fence.py:117-152).
- `symbol` = the Orc's own symbol, or a drum's `body["symbol"]`, so a
  correlate's drum fails V10's symbol test by design.
- `event` is the calendar row's code id, never its title (facts.py:294-299;
  map_wakes trap 14).

##### VI. The officer (`mandate.py`), in would-mode

**A.36 `allowed_actions(orc, ctx)`** replaces `integrity.allowed_actions_l0`
in `dossier.context_for` (dossier.py:333-334; integrity.py:19-21).
- **Allowed:** the L0 vocabulary (integrity.py:34-35), plus `add` in
  would-mode when all of these hold:
  - the army type allows adds (army.py:35-54);
  - adds remain (the type's `max_adds`, less those used and those accepted
    in would-mode, A.38);
  - F5 is not set.

  F5 shrinks the list exactly as `allowed_actions_l0` does
  (integrity.py:102-116).
- **The army type's flags act** (army.py:11-12: the mandate parameters act
  from O2). `lock_waive` is removed when the type's `lock_waiver` is False
  (army.py:47; Mercenaries carry False, :86-92), with why-not "lock_waive:
  not for {type name}".
- **Why not:**
  - "L0: shadow only: every proposal is journaled and graded, none is
    applied";
  - "add: judged by the officer as if binding, never applied in O2";
  - "re-entry, BE-swap, widen and reverse: not in O2";
  - the type's lines and the F5 lines.
- **The risk-adding candidates stay unlisted in O2.** A-CONFIRM is not
  listed: an add names candidate "none". R-RECLAIM waits for O5, V-REVERSE
  and W-WIDEN for L4 (§3). playbook.py:25-27's comment is rewritten to say
  so.
- **The dossier's focus** (army.py:11-12) is the decision frame
  (`dossier.decision_tf`, built in O1). O2 adds nothing more to it.

**A.37 The would-verdicts.** Each intent is judged as if it were binding at
the authority its kind needs. The seat stays L0, so nothing binds
(notes.py:287-290). The verdict is `allow`, `cut` or `refuse`, with its rule
and its words, and is stored on `OrcIntent.officer`.
- The officer judges against the would-world, the O arm's state (A.43): its
  open size, its effective stop and its banked R. That costs one OrcTrack
  read.

| Rule | What it checks | Hook |
|---|---|---|
| **I2 Gross** | after an add: open risk at the would-stop, with the exit spread counted at the stop (P31.3), plus the add's risk, plus prior realized losses (the O arm's banked negative R, P31.4), must stay ≤ `GROSS_MAX_R` = 2.0 | constants.py:381-383 |
| **I3 An add's facts** | V10's add set (structure or bar on this symbol), and the root's effective stop at or beyond the menu's BE row | constants.py:233-235; menu.py:26-27 |
| **I3c Costs** | "break-even" is the BE row (the entry plus its round trip, now built with the row's cost fraction, A.8) plus the exit's half spread (`pricing.half_spread` at the tick), never the raw entry (P31.1) | menu.py:333; pricing.py:53 |
| **I3h The gap** | an add or a lock waiver that leans on an unmeasured gap is refused; a waiver needs the worst case at the stop less the gap's p90 to stay at or above the type's floor, using the type's `waiver_floor_r` and `gap_min_samples` | gaps.waiver_check, gaps.py:74-91 |
| **I4 Size** (P31.2) | an add's share is CUT to fit min(the type's `risk_share_max`, the room under I2); it is refused below `ADD_MIN_SHARE` = 0.25 | army.py:35-54; constants.py:107-108 |
| **I5 Adds left** | adds used plus adds accepted in would-mode must stay under the type's `max_adds` (`MAX_ADDS` = 2); an exotic leg is refused when the type's `exotic_adds` is False | constants.py:69-74 |
| **I6 Before a shut** | no add within the type's `add_pre_shut_h` of a shut (`ADD_PRE_SHUT_H` = 6) | constants.py:69-74 |
| **I12 The step budget** [P30] | at most `STEPS_PER_DAY_MAX` = 4 tightens accepted per trading day; at least `ADD_SPACING_BARS` = 2 and `TRIM_SPACING_BARS` = 1 final decision-frame bars since the last accepted add or trim | constants.py:371 |

**A.38 The officer's state and I12's counters** [P30].
- `seen["officer"]` = {day, steps_today, last_add_bar, last_trim_bar,
  would_adds}.
- It is written when an intent is ACCEPTED in would-mode (allowed or cut),
  never from the care's real acts.
- `steps_today` resets at the trading-day roll.
- The bar counters read the decision frame's final bars.

##### VII. The plan, the intents, the O arm

**A.39 The plan** (models.py:83-85). It is written on a `done` revise_plan:
- `Orc.plan` = {v, at, wake, decision, clauses, expectation, s, schema}.
  Each clause and the expectation carry the stored level reference
  {level_id, kind, tf, price, stop} (A.30);
- `plan_version` += 1;
- `plan_changes_24h` gains {at, urgent}, pruned to 24 h;
- `watches` = [{level_id, kind, tf, price, stop, side, clause}], the stored
  references, with prices from `vctx.menu` (code), never from the model
  (A.48);
- a journal entry: kind `plan`, author `orc`. Its headline is drawn by
  code: "Plan v{n} in shadow: {plan_line}."
- `notes.plan_line` (notes.py:507-510) draws the plan, with prices through
  `format_price`.

No care code reads `Orc.plan`: `position_care.plan(orc=)` is O3's
(ghost.py:63-64; N1.6).

**A.40 A `done` answer also writes:**
- `latest_note` and `latest_note_at`: the filtered note (models.py:97-98);
- `last_good_wake_at` (:100);
- `last_facts_hash` = the wake's facts hash (:102);
- `next_wake_due` (A.49);
- the decision entry: kind `decision`, author `orc`, carrying
  - the booking columns;
  - a body with {wake, rung, answer (after the filter), the verdict of each
    V-rule, the officer, `s_version`, `schema_version`, latency};
  - a headline drawn by code, for example "Decision in shadow: tighten to
    S4h-L1 (2,612.00)."

**A.41 Intents** (one `OrcIntent` per non-hold proposal):

| Proposal | Status | What happens |
|---|---|---|
| tighten, trim, exit, lock_waive, allowed or cut | `queued` | `expires_at` = validation + `INTENT_TTL_S` (600 s); its id goes into `seen["intents_queued"]` inside the settle (A.24) |
| add, allowed or cut | `recorded` | judged, never applied to the arm; its forward grade arrives with O2d's OrcActionGrade (D.13) |
| any proposal while the Orc is `care_owned` | `recorded` | the care holds the would-world too (A.53) |
| a proposal V-refused or I-refused | `refused` | stored with mode `refused` and its rule |

- A hold and a lone plan revision write no OrcIntent; the decision entry is
  their record.
- Each intent also writes a journal entry: kind `intent`, author `orc`.
  Its headline: "Proposed in shadow: {kind words} {level id} ({price})."
  The same append rewrites `card["intents"]`, the 3 newest {kind_t, mode,
  status_t}, and so does every later status change (simulated, expired),
  so the slot reads them with no query (A.62).

**A.42 The tick applies a queued intent** (`intents.take`, called from
`ghost._step_orc`) [P32, P33; map_wakes trap 30].
- **When:** at the first tick after validation.
- **How:** in its own savepoint, under the 200 ms lock timeout (N8),
  writing the Orc tables only. It works on copies of what the tick hands it
  (A.45b).
- **It expires** with a code, journaled, when any of these holds:
  - `expires_at` has passed (code `ttl`);
  - for a tighten: the would-stop no longer has the I11 room on the tick's
    own price and closing-side mark (`pricing.closing_mark`), or it is no
    longer tighter than the arm's effective stop (code `moved`);
  - the O arm has already closed while the row is still open (code
    `arm_closed`);
  - the row closed first (code `row_closed`; A.44 names who writes it).
- **It waits** for the next tick when the tick has no fresh price. It is
  never priced at a later price, such as a reopen gap.
- **Not critical for its kind** (P32's second clause). Of the integrity
  verdict's three critical items (integrity.py:1-17), a tick can judge two:
  - the mark: the tick's own fresh price;
  - the row: its state is readable.

  An exit, trim or lock waiver applies only on such a tick. A tighten also
  needs the I11 room above. The bars item stays as the dossier judged it.
- **Price:** every price comes from pricing.py at that tick
  (pricing.py:1-24).
- **On a fill:** status `simulated`, with `applied_at`, `applied_price` and
  `applied_r`. The id leaves `seen["intents_queued"]` through a callable
  `remember` under the lock (journal.py:17-70).
- **The writer:** the tick alone writes the arms while the row is open (one
  writer per phase, ghost.py:38-42).
- **The query budget:** the tick reads the queue from `orc.seen`, already in
  hand, so a tick with nothing queued costs no query (observe.py:8-16).

**A.43 The O arm's would mode** (ghost.py:988-1071).
- **Entering it.** The first applied tighten, trim, exit or lock_waive sets
  `state["mode"] = "would"`.
  - From mode `real`, the arm holds no care-like state yet: in mode real it
    only records the row (ghost.py:988-1071). So entering would mode first
    seeds that state from the previous tick's record, exactly as
    `_to_shadow` does (ghost.py:947-962): `CARE_KEYS` from `last_care`,
    `venue_stop` from `last_stop`, `target` from `last_target`, and
    `qty_open` from the last record. It never sets `hand`.
  - From O1's `shadow`, which follows a hand act, the state is already
    care-like.
  - It also sets `first_divergence`, if unset: {kind: reduce for tighten,
    trim and exit, hold for lock_waive; at; intent} (constants.py
    `DIVERGE_*`).
- **Each kind:**

  | Kind | Effect on the arm |
  |---|---|
  | tighten | `orc_stop` = the tighter of the existing and the intent's `would_stop` (V7: the level's own `stop`, or the BE row's price); `orc_why` = "the Orc's proposal {level_id}" |
  | trim | `_bank(state, shadow_of(state), tick, now, fraction=share, why="the Orc's trim (shadow)")` |
  | exit | `_exit("orc", pricing.market_exit_px(tick, side, cf), now, "the Orc's exit (shadow)")`, which closes the arm |
  | lock_waive | `state["waived"]` = the intent's `event_id`; the arm's care step then reads a copy of the tick's context without that event: `dict(env.ctx)`, never `env.ctx` itself (A.45b) |

- **Each tick in would mode:**
  1. Keep the real-row bookkeeping:
     - the root mark (`_root_mark` already runs before the mode test);
     - the faith block against the care ghost, because in O2 the real row
       is still the care's;
     - the hand-edit fact, which sets `hand_touched` and never moves the
       would arm.

     These stay as they are so that `counts_for_seat` stays honest
     (grading.py:18-24).
  2. Return `_care_step(state, env, extra_stop=_f(state["orc_stop"]),
     extra_why=state["orc_why"], extra_kind="orc")`, as the playbook arm
     does (ghost.py:760-819, :911-916). `_care_step` gains `extra_kind`
     (default "playbook", so the playbook arm is unchanged): an exit at the
     would-stop is labelled `orc`, with `why` = `orc_why`, never
     "playbook" (ghost.py:812-814).

**A.44 After the row closes.**
- `step_bars` (in `track_ghosts`, on `slow`) walks a would arm like any arm
  that is not `real`. Its checks test `mode == "real"` (ghost.py:1754,
  :1826, :1910). `_tail_bar` and `_arm_stop` already read
  `state["orc_stop"]` (ghost.py:1391-1397, :1491-1499).
- At its first walk after the close, `step_bars` expires the Orc's queued
  intents with code `row_closed`. The tick no longer runs for a closed row,
  and `on_leg_closed` never does this (N1.2).
- The would arm never takes the real exit.

**A.45 Never the real row.**
- An intent never touches the row, its stops or its metadata.
- `DROP_META` (ghost.py:99-102) is never inherited.
- `metadata["orc_exit"]` and the binding Orc columns are never written
  (N1.5).

**A.45b Never the tick's objects.**
- The tick hands the real in-memory `trade` and `bot` to every Orc step
  (N1.1), and after `after_care` the same `trade.stop_loss`, `take_profit`,
  `metadata` and `_care_tick` drive the real stop and the real close
  (base.py:1420-1450). An O2 step that set one of them in memory would move
  or close the real position in that tick, with no Orc-table write.
- So no O2 code (N1's test scope) assigns to, stores a subscript into,
  deletes from, or calls a mutating method of (`update`, `setdefault`,
  `pop`, `popitem`, `clear`, `append`, `extend`, `insert`, `remove`, `save`,
  `delete`, `refresh_from_db`) a value rooted at `env.row`, `env.meta`,
  `env.ctx`, `env.bot`, `trade`, `row`, `root_trade` or `bot`. Reads stay
  allowed (`.get`, `.items`, `.keys`, `.values`, `copy`). The would mode
  works on copies.
- An AST test pins it: no Assign, AugAssign or Delete target, no `setattr`,
  and no Subscript store rooted at those names, in O2 code. T12b's deepcopy
  check proves it at run time.

##### VIII. Evidence, the dossier, the wake reasons

**A.46 The evidence facts** (`evidence.py`) [P21; map_wakes trap 13].
- They are written at the render while the minds switch is ON, through
  `journal.append(fact=True)`.
- Each is a T0 fact with an F-id and a `body["fk"]`, which
  `fence.fact_kind` reads first (fence.py:117-130).
- Event keys are code ids, never titles.

| Fact | When it is written | Body | Headline |
|---|---|---|---|
| `level_reached` | once per (kind, tf, snapped price) per idea, when a final 1h venue bar since max(birth, the last check) traded through a pool, swing, sweep, recent extreme or round number of `vctx.menu` (ids P, S, SW, RC, RN; never the idea's own BE, CARE or EFF rows). A later, different level under the same id is a new fact | {level_id, kind, tf, price, bar_end, symbol}; `seen["reached"]` remembers the (kind, tf, price) keys, never the ids | "Price reached {id} ({price}) on the 1h bar to {hh:mm} UTC." |
| `bar` | one per final decision bar, on a wake that carries W2 | {tf, end, open, high, low, close, symbol} | "The {tf} bar to {hh:mm} UTC closed at {close}, {x.x} ATR from its open." |
| `gap` | one per event code, on a wake whose `vctx` shows a print within `PRINT_WITHIN_H` or a shut within the type's `add_pre_shut_h` | {event (C-n, or the shut's key), kind, n, p90_r, measured} | "The gap model for {event}: {n} samples, p90 {x.xx}R ({measured or unmeasured})." |
| `expectation` | when an earlier decision's decision-frame bar has become final; graded on the expectation's stored price, never on a later menu | {decision, kind, level (the stored reference), result hit or missed, bar_end, close} | "The expectation set at {hh:mm} UTC ({words}) was met." or "...was missed." |

- `FACT_KINDS` (fence.py:33-37) gains `expectation`. V10's plan rule
  ("any newer fact") accepts it: a missed expectation is a reason to revise
  a plan.
- With the minds switch OFF, no evidence fact is written, so the journal
  stays O1's.

**A.47 The dossier's position sections** (dossier_position.py):
- **PS1:** `allowed` and `why_not` from the officer (A.36), and the events
  of `vctx.events` by code id, for example "C-3: a USD print in 2 h 10 min"
  (a lock_waive names one, V14). "L0 shadow" stays (:72).
- **PS3** [P25]: {plan: `plan_line`, version, last_expectation: {set_at,
  words, result: hit, missed or pending}}, taken from the LAST decision.
  `PS3_WORDS` (:38) becomes "no plan yet" for an Orc with no plan (A.62).
- **PS4** [P31.4, P17]:
  - the "loss" (:169): the idea's realized loss in R, the O arm's banked
    negative R or the real row's closed legs;
  - `adds_left` = the type's `max_adds` − `adds_used` − the officer's
    `would_adds` (A.38), never `MAX_ADDS` − `adds_used` (:170);
  - `plan_changes_left` (V2); `steps_left_today`, `bars_since_add` and
    `bars_since_trim` (I12).

  So a refusal under V2, I5 or I12 always names a counter the model was
  shown, and it counts toward the care like any other (A.52).
- **PS5** [P13, P26]:
  - the 12 facts, as today (:176-184);
  - the takeover fact, pinned while the Orc is `care_owned`, even after it
    scrolls out of the 12;
  - `notes`:
    - the last `PS5_DECISIONS` = 6 decisions, each {at, action, cited,
      expectation, outcome: the intent's status, or "hold", or the
      refusal's rule};
    - every refusal since the previous model-answered wake (`done`,
      `refused` or `late`), with its rule id and fixed words.
  - Each note is a T1 view, `fence.view("orc", ..., cap=FENCE_CAPS["orc"]
    = 300)`, and has already passed V11 at write time.
  - The notes are trimmed third, as `ps5_notes` (`TRIM_ORDER`,
    constants.py:304; dossier.py:409-410).
  - With no note yet, PS5's notes read "— (no note yet)".
- **PS9-PS11** stay dashes until O2c and O2d, in words that are true: PS9
  "— (no temperament drawn)", PS10 "— (no lesson yet)".
- **PS12:**
  - each menu row gains `watch`: "yes", or "no: too near the mark" (V12,
    A.48);
  - the BE row now carries the cost (A.8), so PS12's BE bytes change on
    every wake that has a cost fraction (T11);
  - the continuation odds read "— (not measured)": they stay unbuilt
    (dossier_position.py:355-356; §3).

**A.48 W3 watches the plan's levels, never with urgency** [P28].
- W3 (wake.py:200-229) reads `Orc.watches` (models.py:94) beside the
  thesis's `close_beyond` levels, with the same `W3_NEAR_ATR1H` and once
  per level per `W3_ONCE_H` (constants.py:325-328). The Orc row is in hand
  at the tick, so this costs no query.
- **A watch is the model's own choice, so it never buys urgency.** A W3
  raised by a watch records with `urgent: false`, `source: "plan"`, and the
  key `W3:plan:<level_id>:<YYYYmmddHHMM>`. Its memory in `seen["w3_at"]` is
  keyed by the stored reference (`plan:<kind>:<tf>:<price>`), never by the
  id alone (A.30).
  - It is routine (A.12's sub-caps), ranks as non-urgent (A.14), and waits
    for the spacing (A.15).
  - The urgency of A.7 and A.14 ignores reasons with `source: "plan"`, and
    so does V2's urgent exemption (A.32).
  - Only the thesis's `close_beyond` levels keep W3's urgency
    (wake.py:198-229).
- **A watch is never placed at the mark.** V12 refuses a clause whose level
  sits nearer than `PLAN_WATCH_MIN_ATR1H` = 0.5 × ATR(1h) to the
  closing-side mark at plan time. PS12 shows which rows qualify, so the
  refusal is one the model can avoid.
- **Why.** An urgent watch skips the spacing (A.15), passes the real-money
  count cap (A.12), may spend the reserve (A.13), is exempt from the deep
  share and from V2's rate. At each such wake the model could re-plan onto
  new menu levels near the mark. With up to 4 clauses and one W3 per level
  every 4 h, that is up to 24 urgent calls a day from one plan, bounded
  only by the dollar cap: for a real Orc about 45 r0 wakes, almost four
  times its 12-wake cap.

**A.49 The asked wake** [P23].
- A `next_wake_min` that passes V9 sets `seen["w11_ask"]` = the answer time
  plus n minutes.
- W11's detection (wake.py:296-330) then fires reason W11 with key
  `W11:ask:<YYYYmmddHHMM>` and the words "the Orc asked to look again".
  - It fires at the first open-market tick at or after that time.
  - `record` consumes it.
- `next_wake_due` = min(the metronome, the ask) (models.py:101;
  wake.py:667-690).
- An asked wake is routine, so F6 can still make it quiet.

**A.50 The metronome counts from the last recorded wake and follows the
army type** [map_wakes trap 20; §4 Q10].
- `record` sets `w11_at` = now on EVERY recorded wake. Today it does so only
  on a W11 or a birth (wake.py:667-669).
- The period is the army type's `metronome_h` (army.py:43, :90-98): Line 4,
  Mercenaries 1, Olog-hai 24. It is read from the pure `army.ARMY_TYPES`.
  W11 today uses the constant at wake.py:307-309.
- The stock and ETF clock triggers (open + 60, close − 90, a weekend − 2 h)
  are unchanged.
- The effect: a 4h Orc in a 24-hour market records about 12 wakes a day
  instead of 18 (§2.3).

##### IX. States and watchdogs

**A.51 born → active** on the first `done` wake that is not `late`. The
words already exist (notes.py:140-146), and A.62 makes them true.

**A.52 What sends an Orc to the care** [P10, P11, P17; recovered fix 4].
Only causes the model or the worker owns:
- one sent wake closed `stale` with code `worker_silent` (A.55): reason
  `worker_silent`. A wake closed for a backlog never counts;
- `CARE_AFTER_FAILED` = 2 consecutive `failed` wakes: reason
  `calls_failing`;
- `CARE_AFTER_REFUSED` = 2 consecutive refused answers: reason
  `answers_refused`.

How the two counters move:
- An answer counts as **refused** when its wake ended `refused` (a V-rule,
  A.31), or when it ended `done` but the officer would refuse its intent
  (A.37).
- `seen["refused_in_row"]` rises on a refused answer. `seen["failed_in_row"]`
  rises on a `failed` wake.
- Any other `done` wake resets both counters.
- Code answers, `quiet`, `merged` and `late` never move either counter.
- A part refusal (V9, V11) moves neither.
- A V2, I5 or I12 refusal counts like any other: PS4 shows every counter
  those rules read (A.47), so the model can always avoid them [P17].

**A.53 The takeover and the return** [P13; recovered fix 6].
- **Entering `care_owned`** writes a journal entry: kind `takeover`, author
  `code`, `fact=True`, body {fk: "care", reason, wake}. Its headline: "The
  care holds this position: {reason words}."
  - It sets `state = care_owned`, `care_owned_reason` (its words) and
    `care_owned_at` (models.py:110-111).
- **While `care_owned`:**
  - wakes go on as before;
  - accepted intents are `recorded` and never applied: the care holds the
    would-world too;
  - in shadow, nothing changes in what the care does.
- **The return** happens only through a `done` wake that both:
  - carried the takeover fact in PS5;
  - and cites its F-id.

  It writes a journal entry: kind `return`, author `code`, headline "The
  Orc reads its position again: it cited the takeover."
- A good wake that does not cite the fact leaves the Orc `care_owned`.

**A.54 The stall alarm** (watchdog step `minds_stalled`, in
`orc_minds_watch`, N8; in census.py's O1c tuple style, :167-178) [P9].
- It counts the pending wakes whose `queued_at` is older than `STALL_MIN` =
  20 minutes.
- When the count is above 0, it:
  - adds `"minds_stalled": n` to the watchdog's result, with status
    `warning`;
  - writes a log line;
  - shows the alarm in `orcs status` and on /orcs/ for staff.
- Nothing is ever sent again, so nothing can re-stamp `queued_at`. A claim
  ends the stall clock, and from then on the call's wall time judges the
  wake.

**A.55 Stale, backlog and wall time** (watchdog step `minds_stale`) [P8,
P10, P11, P14].
- **A pending wake** older than `STALE_MIN` = 30 minutes is closed. What it
  closes as depends on the worker:
  - **Silent:** no wake was claimed (`started_at`) and none settled
    (`finished_at`) in the last `STALE_MIN`. The wake closes `stale` with
    code `worker_silent`, and its Orc goes to the care (A.52).
  - **Busy:** otherwise. The wake closes `skipped` with code `backlog`: a
    code answer, journaled as one, never a refusal and never silence. The
    watchdog reports `"minds_backlog": n` with status `warning`. Bursts are
    built in: every 4h Orc's W2 lands on the same bar close, and every USD
    row's W5 at the same offsets (map_ai §4.1), behind two slots and, from
    O2b, calls of up to `WALL_S` = 3,460 s.
  - Two more exceptions, both answered by code with no care: a gate is OFF
    now (code `minds_off`, or `platform_off`); the watchdog did not run for
    more than 10 minutes before this pass, so the Orcs were paused
    (OrcSetting `minds_watch_last_at`; code `paused`).
- **A running wake** past `WALL_S(rung)` since `started_at` is closed
  `failed` (code `wall_time`), for the care's counters. Its bound moves to
  OrcSetting `minds_inflight` as a hold {wake, usd: the bound, kind:
  "orphan", until: the next 00:00 UTC}. The call may still be streaming, or
  be orphaned by a worker restart: there is no Celery time limit and no
  `acks_late` (config/celery.py), and the RUNBOOK restarts the containers to
  bind a new line (`./deploy/dc up -d`).
- **A late settle** on a wake that is no longer `running` books its real
  cost on an `error` entry and in the day's dollars, drops the hold, and
  writes nothing else.
- **Holds expire at 00:00 UTC**, never earlier (A.25).

**A.56 The breaker** [P8].
- It opens when `BREAKER_FAILS` = 5 wakes of any Orc end `failed` within
  `BREAKER_WINDOW_MIN` = 10 minutes.
- Open, it pauses the claims for `BREAKER_PAUSE_MIN` = 15 minutes
  (OrcSetting `minds_breaker` {until, why}). Claims in the pause end
  `skipped` with code `breaker`, which never counts as silence.
- It is shown by `orcs status`, on /orcs/ for staff, and in the watchdog's
  result.

**A.57 Tickets: every call that is not a wake.**
- **Who:** every ticket caller of §1.0.9 (from O2a, `orcs smoke --row`;
  later the probes, the twin, Captains, the Emperor, the Skeptic,
  post-mortems, the council of war and questions). It reserves through
  `scheduler.reserve_ticket(caller, request)` under the line lock, in
  OrcSetting `minds_inflight` {id: {usd, at, wall_s, caller, kind:
  "ticket"}}. A caller missing from §1.0.9 raises.
- **Its request comes first.** The caller builds its request, then
  estimates it with `dossier.estimate_tokens` × the family factor
  (dossier.py:102; constants.py:294). Above `TICKET_MAX_TOKENS` = {captain
  10,000; emperor 16,000; skeptic 6,000; postmortem 12,000; tribunal
  12,000; question `DOSSIER_MAX_TOKENS` + 400} it is refused by code
  (`over_budget`). The post-mortem's and the council's journal digest is
  trimmed oldest first to fit, never the grade or the arms. Without a cap,
  a digest that grows with the idea's life would make the reservation no
  bound at all.
- **Its bound** is A.21's formula on that estimate, with the caller's own
  rung limits. Tickets send no fallback (B.14).
- **Its ceiling and day cap** are §1.0.9's, enforced in `reserve_ticket`
  under the line lock, beside A.18's `inflight` rule. A ticket refused at
  its ceiling makes no call. The questions never reach the reserve R.
- **One billed attempt per item.** A call with usage closes its item,
  whether it succeeded or failed (a refusal is billed). A failure without
  usage is retried at most once, on the next beat. Only a budget refusal (no
  call made) may wait, at most until the next UTC day; then the item closes
  with code `expired`. So an item refused every time, for example by a
  classifier tripping on a journal headline, is billed once, never once a
  beat.
- **The settle** releases the ticket as A.24 does, the ledger check
  included. A ticket past its wall time becomes an orphan hold until
  00:00 UTC: nothing is dropped earlier.

##### X. The grade

**A.58 The grade counts the mind** (grading.py:120-215).
- **The counters** (models.py:276-281):
  - `n_wakes`: every OrcWake of the idea;
  - `n_llm`: the wakes with a model call: done, refused and late;
  - `n_actions`: the simulated intents;
  - `n_refused`: the refusal entries;
  - the invalid-output rate = V-refused wakes ÷ `n_llm`, written as the tag
    `invalid:<x.xx>` (OrcGrade has no column for it, models.py:276-281);
  - `expectation_hit_rate` = hits ÷ graded expectations;
  - `flipflop_rate` = the plan changes that restore the clauses of one of
    the two versions before ÷ all plan changes.
- **The AI cost.** `ai_cost_usd` = Σ `cost_usd` of the idea's decision and
  error entries.
  - It is passed to `grading.numbers(ai_cost=...)` (grading.py:57-84;
    `grade()` passes none today, :144-147).
  - It is converted to `Orc.ccy` first when that is not USD or empty. With
    no rate, `orc_r` and `net_edge_money` stay None, with the tag
    `ai_cost_unconverted`.
- **The tags** (models.py:275): `s:<S_VERSION>`, `schema:<v>`, `rung:<r>`,
  so grades under different minds are never pooled (P29).
- **The grade line** (grading.py:100-107) reads "Graded in shadow: ...". It
  names "the Orc's shadow arm" once the arm went to would mode.
- **No consequence lowers a tier** (complexity.py:23-25).

##### XI. Commands (bot_program/management/commands/orcs.py)

This file sits under the package pins (tests/orcs/test_orc_switch_off.py:
427-456). It names no `ai_agents`; it calls the scheduler and the gateway.

**A.59 `status` and `dossier`.**
- `status` adds:
  - the minds switch;
  - the line (`line_summary`);
  - the model calls today (Σ `llm_wakes_today`);
  - the counts of pending and running wakes, and of the backlog closes;
  - "held for calls without a bill: $x" (A.25);
  - the stall alarm, the breaker and any ledger gap.
- `dossier ROOT [--wake N]` adds (map_wakes §2.2 h):
  - S, by its stored hash;
  - the answer, with each V-rule's verdict;
  - the officer's verdicts;
  - the booking.

**A.60 `smoke --row ROOT [--rung r0|h0] [--yes]`.** This is the only
command of O2a that sends a call [P34, P35;
ai_agents/management/commands/claude_smoke.py:33].
- It is dry by default. It prints the rung, the family, the tokens, the
  bound, the line's answer and the switches.
- `--yes` is refused while any of the four gates (A.2) is off.
- Only the rungs in `CALLER_RUNGS["smoke"]` are accepted. Fable cannot be
  reached in O2a.
- It reserves a ticket (A.57) and asks the line for the whole bound (A.20)
  before the call, which it sends once (`max_attempts=1`).
- It makes one call on the Orcs line: agent `orc`, `source_ref`
  `Orc:<pk>:Smoke:<wake pk>:<rung>`.
- It prints the answer and its validation.
- It writes nothing to the Orc: no journal entry, no plan, no intent, no
  counter.

**A.61 `smoke-verdict` and `tokens`.**
- `smoke-verdict --family F --pass`, or `--fail` with one or more of
  `call_a`, `call_b`, `cache`, `effort`, records what the operator read from
  `claude_smoke --yes` in OrcSetting `smoke_verdict` {family: {verdict,
  reasons, at}}.
  - The reasons are the smoke's own printed ones (claude_smoke.py:487-516,
    :593-603): call A failed or answered off the schema; call B the same;
    "read no cache"; "less than 2x".
  - The smoke prints one verdict per model and stores nothing
    (claude_smoke.py:599-607), so there is no separate "C2" or "C3" verdict
    to record.
  - One PASS gates both uses: the effort-only message (A.23) and two
    efforts on one model (B.5). A `--fail effort` means the message governs
    nothing, so neither is used.
  - It sends no call.
- `tokens --s [--yes]` counts S through `mind_gateway.measure_tokens`
  (N3's one exception).
  - `count_tokens` is free and never ledgered (claude_provider.py:724-742).
  - Without `--yes` the command is dry. With it, it needs only the API key:
    no switch and no line.
  - The count goes to OrcSetting `s_tokens`.
- All the new subcommands are listed on the ops page
  (core/ops_commands.py:140-152) and in the RUNBOOK.

##### XII. Words

**A.62 The words O2a changes.** Each new text is true with the switch and
the line both ON and both OFF. Each new sentence is registered (N6).

| Where | Today | O2a |
|---|---|---|
| notes.py:141, `STATE_WORDS["born"]` | "Watching: a journal written by code, no model." | "Watching: a journal written by code; no model has read it yet." |
| notes.py, `STATE_WORDS["active"]` | "Active." | "Active: its wakes are read in shadow when the minds are on; nothing it decides is applied." (true after `orcs_minds` goes OFF too) |
| notes.py:176-177, `COMPARE` | "...; the Orc has taken no step." | the arm in mode `real`: "The position {o} and the care ghost {g} so far; none of the Orc's proposals has been applied."<br>the arm in would mode: "In shadow, the Orc's proposals {o} and the care ghost {g} so far; none was applied to the position." (both added to `RESERVED_PATTERNS`) |
| notes.py:179-182, `NEXT_WAKE_*` | "...detected and recorded only, no model." | "Next wake {when} UTC." (the slot takes `minds` from its caller, read once per page, never once per slot) |
| notes.py:184 and :441, `RUNG_NONE` and `_intellect` | `rung_t` is hard-coded | `_intellect` reads `card.intellect.rung_t`: "r0 · balanced tier, low effort" when a model answered; `RUNG_NONE` for a code answer [map_wakes trap 5] |
| wake.py:81 `RUNG_O1`, and card.intellect | the render writes `RUNG_O1` and the render's status | the render writes `RUNG_NONE` and its status words; mind.py rewrites `card.intellect.rung_t` and `status_t` at the settle |
| wake.py:772-776, the wake headline | "...Recorded only: no model is asked yet." | "Wake detected: {words}. Complexity {n} ({band}); the day is {class}. {status words}." |
| notes.py:545, `slot.intents` | `[]` | the 3 newest from `orc.card["intents"]`, each {kind_t: "proposed in shadow: tighten to S4h-L1 (2,612.00)", mode, status_t}, written by `journal.append(card_extra=...)` when an intent is written and at each status change (A.41). `slot()` stays query-free (notes.py:513-516) and `for_rows` stays at two queries (:685) |
| dossier_position.py:38 `PS3_WORDS`; PS5, PS9, PS10, PS12 dashes | "no plan yet: the Orc writes one from O2"; "arrives with O2"; "starts in O2"; "continuation odds arrive with O2" | "no plan yet"; PS5 "— (no note yet)"; PS9 "— (no temperament drawn)"; PS10 "— (no lesson yet)"; PS12 "— (not measured)" (A.47) |
| notes.py:507-510, `plan_line` | `PLAN_NONE` | the plan drawn by code; `PLAN_NONE` when there is none |
| surfaces.py:45, `MODEL_CALLS` | "Model calls today: 0" | "Model calls today: {n}" (`llm_wakes_today`, on the UTC day) |
| surfaces.py:35-36, `QUESTION_LATER` | "...: none calls a model." | "Orcs do not answer questions yet. Ask Sauron instead: /q <question>." |
| surfaces.py:39-40, `ORCS_OFF_NONE` | "...each keeps a journal only..." | "Nothing to switch off: no Orc acts on a position; the care holds every position." |
| surfaces.py:46-48, `HELP_LINES` | "(no model)" | "/orc NUMBER — one Orc: its thesis, journal, plan in shadow and the care beside it" |
| views_orcs.py:38, `NO_INTENTS` | "No intents: an Orc proposes nothing until it reasons." | "No intents: this Orc has proposed none." |
| views_orcs.py:39-41, `SEATS_NOTE` | "...no Orc takes a step..." | "Δ measures the Orc's shadow arm (its proposals applied in shadow, when it has any) against the care ghost; no seat holds any power." |
| orc_detail.html:105 | "Wakes detected (recorded only: no model is called)" | "Wakes detected", with Status (`STATUS_WORDS`) and Rung columns |
| orc_detail.html:130 | "Graded (shadow, no Orc action)" | "Graded in shadow" |
| orcs_list.html:3, :87 | "ORCS · JOURNALS BY CODE"; "off (no Orc calls a model in this release)" | "ORCS · IN SHADOW"; for staff, "Orcs line: off (ORC_DAILY_BUDGET_USD=0)" or "Orcs line: ${x} of ${y} today · minds switch on/off" |
| ai_models.html:152-157 | "...stays off until O2 ... No Orc runs today." | "...read by the Orcs from O2; tier settings never move it. Their calls bill the Orcs' own budget line (ORC_DAILY_BUDGET_USD, off at 0). O2a answers every wake on r0." plus the day's Orc calls from the ledger (U-A1) |
| views_ai_models.py:91, :94-95, :230 | comments | updated (U-A5) |
| council_band.py ("The Orcs are not in the field yet.") | always | kept while no Orc lives; otherwise "{n} Orcs watch in shadow; none acts on a position." |
| core/book_content.py:591, :1740-1744 | "No model is called"; "It calls no model and sends no order." | "With a second switch on and its budget line set, a model reads its dossier at each wake, in shadow: it writes a plan and proposals that are graded, and sends no order." (U-B2). Keep K-B1. Guard tests/test_the_book.py:2164-2180 |
| the_wall.html:3175-3176 | the Horde card | adds one sentence: "With a second switch on and their budget line set, a model reads each Orc's dossier in shadow; nothing it decides is applied." (U-W3; tests/test_the_wall.py:1204-1226) |
| deploy/RUNBOOK.md | :1274-1275, :1285, :1308-1312, :1360, :1368-1369, :1407-1408, :1455-1463, :1520-1523, :1555, :1669-1671, :1678-1679, :1684-1691, :1697-1699, :1713-1714 | U-R1, U-R6, U-R9, U-R14, U-R17 (the AI cost), U-R20, U-R25, U-R30 (first half), U-R31, U-R32, U-R34, U-R37 |
| ai_agents/spend.py:23-24, :79-81 | "O2 turns it on" | "the operator turns it on" (U-C4) |
| /ops/ (the switch row) | no PIN field for an Orc switch | the PIN field on every O2 switch, as on a live-money switch (N2) |

**The new RUNBOOK section, "The Orcs' minds (O2a)", says how to turn them
on:**
1. Run `manage.py claude_smoke --yes` (about $1) and record its verdict
   with `orcs smoke-verdict`.
2. Optionally count S: `manage.py orcs tokens --s --yes` (free).
3. Set `ORC_DAILY_BUDGET_USD` (§2.5: $6.00 for the first week), and raise
   `AI_DAILY_BUDGET_USD` by the cap plus the $3.00 floor (24 with the core's
   15). Then `./deploy/dc up -d` (K-R4).
4. Check that `worker-orc` consumes `orcs`:
   `celery -A config inspect active_queues`.
5. On /ops/, turn on "Orc Minds (models in shadow)" with the trading PIN.
   The shell's `component on orcs_minds` refuses and points to /ops/.
6. `manage.py orcs status`.

It also says that switching `orcs_minds`, `orcs` or the platform master OFF
stops new calls at the next claim and needs no PIN; that pending wakes close
with a code; and that a call already in flight finishes and is booked, or,
with no bill, keeps its money held until 00:00 UTC (U-R14).

#### 1.1.6 The pitfalls O2a designs out

| P | Designed out by |
|---|---|
| P1 one call per real reason | A.11 (every code path), A.7 (merge), A.26 |
| P2 inside the line | A.2, A.20, A.22, A.27 |
| P3 nothing decided can act | N1, N8, A.45, A.45b |
| P4 queues consumed | A.17 (worker-orc and the consumer test) |
| P5 day caps on the whole day | A.12 |
| P6 triage that never inverts | A.13, A.14 |
| P7 "real" is live only | A.14 |
| P8 failures booked and bounded | A.21 (one send), A.24, A.25 (the holds), A.55, A.56, A.57 |
| P9 the stall from the first send | A.11 (`queued_at` set once), A.16, A.54 |
| P10 stale closes; the care takes the idea | A.52, A.55 |
| P11 silence counts only wakes that waited | A.52, A.55 (silent or busy), A.7 (render failures) |
| P12 spacing again at the claim | A.15, A.18 |
| P13 the return only by citing the takeover | A.53, A.47 |
| P14 deferred wakes | A.16 (nothing is deferred), A.55 (`backlog`, never silence) |
| P15 urgency recomputed on merge | A.7, A.14 |
| P16 the row read again after the call | A.26 |
| P17 the care's causes | A.52, A.47 (PS4 shows every counter a refusal reads) |
| P18 statuses fit | A.3 |
| P19 V2 over 24 h | A.32 V2 |
| P20 V10 refuses and is counted | A.32 V10, A.33 |
| P21 V6 and `level_reached` | A.32 V6, A.46 |
| P22 the money filter | A.34, A.32 V11 |
| P23 `next_wake` kept | A.32 V9, A.49 |
| P24 where clause checks run | A.32 V12 and the paragraph after the V-rules table |
| P25 PS3's last expectation | A.47 |
| P26 PS5's decisions and refusals | A.47, A.33 (since the last model-answered wake) |
| P27 the facts hash and its reference | A.9, A.10 |
| P28 W3 on the plan's levels | A.48 (never urgent, never at the mark) |
| P29 S's authority | A.29 |
| P30 I12 counts | A.37, A.38 |
| P31 would-mode per the mandate | A.37 (I2, I3c, I4, the exit cost, prior losses) |
| P32 C17's time to live | A.42 |
| P33 the stop beyond the crowd | A.32 V7, A.43 |
| P34 sending commands gated | A.60 |
| P35 no Fable from the wake path | A.22 (`CALLER_RUNGS`) |
| P36 a zero-call proof that can fail | N7 (the pairs, the stack proof), the tests T1-T19 (T16 is the meta-test) |
| P37 no vacuous assertion | N7 (pairs; red first by mutation) |
| P38 end to end in every world | T12, and T12b for the shadow proof |
| P39 every requirement has its test | 1.1.7 |
| P40 push every commit | §1.0 item 8 |

#### 1.1.7 Tests (red first, fake model, `MindTestMixin`)

A new helper module, `tests/orcs/helpers_o2.py`, provides:
- `FakeClient`: scripted messages, both stream paths, mid-stream error
  events, and two lists the test owns: the messages requests (each with
  its stack) and the `count_tokens` requests (N7);
- `fake_answer(...)`;
- `MindTestMixin`, with `MindTestCase(TestCase)` and
  `MindTransactionTestCase(TransactionTestCase)`: the no-network guard, the
  behavioural guard and the stack proof (N7);
- `minds_on()`: turns on the four gates and sets the line through
  `AI_CONFIG["orc_daily_budget_usd"]` (tests/test_claude_provider_keywords.py:
  91-98);
- the fixture's distinctive fake figures for the K-B10 walk (N6).

Every zero-call case below is a pair inside one test method: first the
positive control records exactly one request, then only the gate under test
flips (N7).

| Test | Module (tests/orcs/ unless named) | What it proves |
|---|---|---|
| T1 | test_orc_o2a_shadow_pins.py | N1 (a)-(h): the names, the structural rule, the gateway-only rule with strings and dynamic imports, the trade-row writes outside `census._restamp`, the receiver-scoped bans, the frozen hook table, the reverse accessors, the hashes of the frozen O1 functions; A.45b's AST rule; "pending only in scheduler.py" |
| T2 | test_orc_o2a_switch.py | N2 for `orcs_minds`: OFF in a fresh database, exempt, in `ORC_MIND_SWITCHES` and not in `LIVE_MONEY_SWITCHES`, ON only with the right PIN, OFF with none, refused from the shell; `minds_off` with an empty call list; the line at 0 with every switch ON gives `line_off` and an empty call list [P2]; the platform master OFF between two claims of one `orc_think` run leaves the second with an empty call list (A.2); `orcs` OFF stays byte-identical (the hard-rule-1 tests extended); the switch OFF closes pending wakes with `minds_off`; with `orcs` ON and `orcs_minds` OFF the journal differs from O1's by exactly A.5's list |
| T3 | test_orc_o2a_admission.py | every code of A.11 [P1, P36]; 12 urgent wakes then a routine one gives `day_cap` [P5]; the dollar cap with HIGH: a paper Orc at $0.45 is refused an r1 claim with `dollar_cap`, and at $0.20 an r3 claim passes (A.12); the routine sub-cap; the triage at R = min($1.00, 0.2 × C): paper urgent wakes cannot push spend past 60%, while a real urgent wake still runs at 95% [P6]; in one pass a real routine wake is claimed before a paper urgent one; the ceilings never invert at caps $1-$50 (a table); `inflight` when the bounds in flight and the holds would pass $3.00; a demo row and a row with no world budget as paper [P7] |
| T4 | test_orc_o2a_merge.py | a newer routine wake absorbs an older urgent one, and the survivor is urgent, skips spacing and keeps the older `queued_at` [P15]; a plan-watch reason never makes the survivor urgent; the database holds one pending wake per Orc |
| T5 | test_orc_o2a_reserve.py | the reservation in one thread: inside the fake client's first call (no lock held), `scheduler.claim()` for a second wake whose bound no longer fits ends `triage` or `line`, with no second request; on PostgreSQL only, two concurrent claims where only one fits make one call and neither thread raises; a settle releases only after the ledger check, and a patched `AgentTask.objects.create` that raises leaves `spent_today("orcs")` unchanged while the next claim's in-flight sum holds the cost (`ledger_gap`); a fake timeout leaves `spent_today("orcs")` unchanged while the next claim holds the bound until the fake clock passes 00:00 UTC; a wall-timed fake call that settles later is booked once and never counted free in between; a fake call that streams past `WALL_S` keeps its reservation, and a concurrent claim that fits only without it is refused; booked ≤ bound for the worst fake usage (N4); `can_spend` gets the bound plus the OTHER calls' money, never its own twice and never 0.05; two urgent wakes of one Orc and two workers make one call at a time, and the second is claimed only after the first settles, with the first decision in its PS5 (A.18, A.24); the lock row's `get_or_create` survives a race |
| T6 | test_orc_o2a_call.py | the request: S and the shared turn byte-identical for two Orcs on one model; the schema is the same object; the breakpoints; `turn_effort` with a recorded PASS, the top-level effort without one, and no `turn_effort` after `--fail effort`; the keywords of A.23, `max_attempts=1` included; a stream that raises an `overloaded_error` event mid-stream receives exactly one request and ends `failed` with its bound held; the ledger row lands on the Orcs line; `BYPASS_SITES`; no model id outside the catalog; the K-B10 walk: no text block of any request carries a fixture figure in any format (N6) |
| T7 | test_orc_o2a_validator.py | V1-V14 table-driven, one red and one green case per rule; V2 with two changes 25 h ago passes, two inside 24 h refuse the third non-urgent change, an urgent wake passes it, and a wake urgent only by a plan watch does not [P19]; V5 takes "none" for a lock_waive; V6 refuses an exit naming an unreached P1h-H1 and passes it after the fact [P21], and a menu rebuilt so that P1h-H1 names a new pool refuses with the old fact; V7 puts a BE tighten at the BE row's price and refuses CARE and EFF; V10 refuses an exit citing only a drum on another symbol, journaled and counted [P20], and a lock_waive with a calendar fact of another event; V11 refuses a note over 20% outside Latin-1; V12 refuses a clause 0.05 ATR(1h) from the mark; V14; every V-refusal is journaled with its rule |
| T8 | test_orc_o2a_money.py | every form of map_pitfalls P22 in a fake note reaches none of the card, the page, Telegram or the next PS5; the forms already withheld stay withheld; the "must pass" forms (R, ATR, pips, percent) pass |
| T9 | test_orc_o2a_officer.py | I2, I3, I3c, I3h, I4 (cut, then refused below 0.25), I5, I6 and I12 with numbers in R; BE differs from the entry when the cost fraction is above 0, and an add whose root stop sits between the raw entry and BE is refused; the exit cost at the stop; prior losses; a Mercenaries Orc gets no lock_waive, with its why-not; PS4 shows `adds_left` from the type, `plan_changes_left`, `steps_left_today` and the bars since the last add and trim; I12's counters advance from accepted intents only [P30, P31] |
| T10 | test_orc_o2a_queue.py | the stall fires at 20 minutes whatever happened since admission [P9]; a silent worker's stale wake at 30 minutes gives the care [P10]; 40 pending wakes and a fake worker settling one every 2 minutes: the wakes past 30 minutes close `backlog`, and no Orc changes state [P11, P14]; `paused`, `platform_off` and `minds_off` give no care; silence counts only failed and silent-stale wakes, and a day of code-answered wakes leaves the Orc `active` [P11]; two routine wakes 5 minutes apart give the second `spacing` at the claim [P12]; a valid answer without the takeover leaves `care_owned`, and one citing it returns the Orc [P13]; a pending wake 25 minutes old is still served [P14]; the cold-burst rule: the second worker waits for the first call on a cold model, never for an urgent wake (A.16); a row closed inside the fake call writes only the booking and the late entry [P16]; the breaker after 5 timeouts [P8]; the consumer test, and `orc_minds_watch` routed to `slow` [P4, N8] |
| T11 | test_orc_o2a_dossier.py | S ≤ 12,000 characters and ≤ the reserve on the estimator; S is stored and printed by the replay; S is a constant, and the gateway refuses with `authority` while a seat reads `level > 0` [P29]; three decisions give PS3 the third one's expectation [P25]; a refusal at wake N, then a code-answered wake N+1: the refusal shows in N+2's PS5 [P26]; the same facts with plan v1 then v2 are not quiet [P27]; a plan watch near the mark is recorded non-urgent, waits for the 15-minute spacing and counts toward the day caps; on a real-money Orc with 4 clauses near the mark the wakes are non-urgent, rank 2, and stop at the count cap and the spacing [P28]; PS12 shows `watch` and the BE row with its cost; PS1 lists the events; the asked wake fires at +40 minutes [P23]; W11 counts from any recorded wake, with the army's cadence |
| T12 | test_orc_o2a_e2e.py | P38: detection, render, admission, claim, fake model, validation, plan and intents, the O arm's step and the grade, for a real-money bot row, a manual row, an eToro demo row and a paper row, each with a menu with F5 and one without; the booking on the Orcs line, the day counters, and the grade's `n_llm`, `n_actions`, `n_refused`, invalid-output tag and AI cost |
| T12b | test_orc_o2a_tick_diff.py | N1's shadow proof: the tick differential, per world, with one queued intent of each kind (N1) |
| T13 | test_orc_o2a_arm.py | an intent is applied at the first tick after validation and priced by `pricing`; the Orc and T-STRUCT naming S1h-L1 hold the same stop [P33]; an Orc that follows P-LOCK puts `orc_stop` at BE; an exit validated at Friday's close expires at the Monday reopen [P32]; `moved` at the tick; entering would mode from `real` seeds the care-like state as `_to_shadow` does, with no `hand`; a would-stop exit is labelled `orc`; would mode keeps the faith block; `first_divergence`; the walk after the close applies `orc_stop`, and `step_bars` expires the queued intents with `row_closed`; an intent after the arm closed expires `arm_closed`; a lock waiver drops the event lock on a copy of the context; an add never moves the arm; `care_owned` intents are `recorded` |
| T14 | test_orc_o2a_commands.py | `smoke --row` is dry by default; `--yes` is refused with any of the four gates OFF; r1-r5 are refused; the whole bound is asked; the call is sent once and bills the Orcs line; nothing is written to the Orc [P34, P35]; `smoke-verdict` stores {verdict, reasons, at} per family; `tokens --s --yes` with the line at 0 records one count request and no messages request |
| T15 | test_orc_o2a_words.py | every new sentence is registered; no Orc verb; the slot walk finds no money or model key; each U-sentence of A.62 is pinned with the switch both ON and OFF; `slot.intents` comes from the card with no query |
| T16 | test_orc_o2a_meta.py | every TestCase in tests/orcs/test_orc_o2{a,b,c,d}_*.py inherits `MindTestCase` or `MindTransactionTestCase`; every test that claims "no call" or "empty call list" also asserts exactly one recorded request; every zero-call branch of T3 and T10 ran [P36, P37] |
| T17 | test_orc_o2a_locks.py | N8's proof, on PostgreSQL only: the tick, the kill switch, the close of an Orc's row and the runner's provenance step each finish in under 1 s while another thread holds that Orc's lock for 10 s, with the same broker calls and rows as with no Orc; the source test that no lock holder renders, validates, prices or calls the gateway |
| T18 | tests/test_claude_provider_attempts.py | the provider's `max_attempts`: 1 sends once after a mid-stream `overloaded_error`; None keeps two attempts; tests/test_claude_provider_bytes.py stays green |
| T19 | tests/test_switch_pin.py (extended) | every key of `ORC_MIND_SWITCHES` takes the PIN to turn on, at every door, and none to turn off; "all on" never reaches one; each lands on the audit chain |

**Pins changed on purpose, in the same commit:**
- tests/orcs/test_orc_source_pins_o1c.py:69-83 (the markers that remain,
  §1.0 item 6);
- tests/orcs/test_orc_models.py (OrcIntent and the migration);
- tests/orcs/test_orc_census.py:33 and test_orc_tasks_o1b.py:2 (the
  `orcs` queue);
- tests/orcs/test_orc_wake_detect.py:81 and test_orc_wake_memory.py:380
  (`recorded`, plus the ON case);
- tests/orcs/test_orc_switch_off.py:427-456 (the gateway only);
- tests/orcs/test_orc_notes.py:163 (`intents` read from the card);
- tests/test_llm_ledger_truth.py (`BYPASS_SITES`);
- the Book, Wall, notes and pages pins named in A.62;
- tests/orcs/test_orc_pages.py:160 (`NO_INTENTS`).

**Pins that stay green as they are:**
- tests/test_ai_spend_lines.py;
- tests/test_model_catalog.py:434-525;
- tests/test_claude_provider_bytes.py;
- tests/orcs/test_orc_notes.py:37-43, :109, :135, :141 (the query counts)
  and :498-521 [P39];
- tests/orcs/test_orc_beats_o1c.py:89-101 (`orcs_drums` stays outside the
  exempt set, C.14).

#### 1.1.8 What the operator sees

**On arrival** (`orcs_minds` OFF, the line at 0):
- Nothing behaves differently. Wakes read "answered by code: the minds
  switch is off" where O1 said "no model before O2".
- /ops/ shows a new switch row, OFF, with the PIN field of a live-money
  switch. "All on" leaves it OFF.
- `orcs status` shows the minds switch OFF and the line off.

**After he turns them on** (the RUNBOOK steps):
- **The Orc page:**
  - each wake with its status and rung: "answered in shadow", "answered by
    code: {why}", stale, merged;
  - the plan, drawn by code;
  - the intents, each "proposed in shadow" with the officer's verdict and
    its status (simulated, expired);
  - the refusals.
- **The card:** the model's filtered note, the state "Active: ..." or
  "Stood aside: ...", and the shadow comparison against the care ghost.
- **Telegram `/orc`:** "Model calls today: n".
- **/ai-models/:** the Orcs line spending in the TODAY cell.
- **/orcs/ for staff:** the line, the stall alarm, the backlog, the breaker,
  and the money held for calls without a bill.
- No notification is sent (K-R12). Nothing about the position changes.

#### 1.1.9 Money direction

- **Account money:** none moves. No order, stop, size or close comes from
  an Orc (N1).
- **AI money:** from $0 (the line off on arrival) up to
  `ORC_DAILY_BUDGET_USD` per UTC day, once the operator sets it ($6.00
  proposed for the first week, §2.5).
  - For example, all on r0, 10 positions: about $4.47 to $5.36 a day of
    demand at central output, the cold cache writes included (§2.4). Under
    the triage, a $6.00 line spends about $4.27 to $5.14 (§2.5).
- **The core line:** while the Orcs line is on, the core line's allowance
  is the total, less what the Orcs actually spent, less the $3.00 floor
  (spend.py:157-170). Raise `AI_DAILY_BUDGET_USD` by the cap plus $3.00 to
  keep the core whole (§2.5).

---

### §1.2 O2b: routing in shadow

#### 1.2.1 Scope

- **A pure router** chooses a rung for every wake, from the band the render
  already computes.
  - It ships in shadow, behind `orcs_router` (OFF). While the switch is OFF,
    O2a's r0 answers every wake and the router's choice is only recorded.
  - With the switch ON, the routed rung answers, and the dossier is rendered
    for that model's family.
- **Probes**, behind `orcs_probes` (OFF), measure the neighbouring rungs on
  paper wakes. They are graded in OrcTierGrade.
- **Fable** (r5) has a gate and a quota of 0, behind `orcs_frontier` (OFF).
  Its r4 blind twin runs only beside r5. In O2 the gate cannot open (B.9).
- The smoke's verdict decides whether one model may run at two efforts.
- Each of the three switches takes the PIN to turn on (N2).

O2b depends on O2a only.

#### 1.2.2 Models and migration

- **`OrcTierGrade`** (new), one row per probe pair:

  | Field | Meaning |
  |---|---|
  | `wake`, `orc` | |
  | `kind` | h0, boundary or twin |
  | `boundary` | 30, 55, 75 or null |
  | `world` | |
  | `routed_rung`, `probe_rung` | the ANSWERING rungs (B.2); `would_rung` beside them |
  | `routed` | {action, level_id, valid} |
  | `probe` | {action, level_id, valid} |
  | `agree_action`, `agree_level` | |
  | `routed_cost_usd`, `probe_cost_usd` | AI spend, shown on staff pages only |
  | `fwd_routed_r`, `fwd_probe_r`, `fwd_at` | the forward grade (B.12) |
  | `block`, `created_at` | |

- **OrcWake** needs nothing new: `components["route"]`.
- **OrcSetting:** `frontier_per_day` (default 0), `probes_per_day`
  (boundary 6, h0 40), `probes_usd_per_day` (15% of the cap, B.11).
- **OrcDayBaseline:** weather writes `frontier_quota` from OrcSetting
  `frontier_per_day` (0 by default) from O2b on, and the router never reads
  it (B.8). `routing_version` is written per wake.

#### 1.2.3 Code it adds or changes

- **New:** `router.py` (pure); `probes.py`.
- **Changed:**
  - wake.py: the band, then the route, then one render for the routed
    family (B.4);
  - scheduler.py: the answering rung, the deep share mirrored, probes as
    tickets on their own allowance, the r5 pair;
  - mind_gateway.py: `CALLER_RUNGS` and fallbacks;
  - weather.py: the probes become binding; `frontier_quota` written from
    the setting;
  - complexity.py: the comment at :10 ("the router is O2's");
  - notes.py: `rung_t`, `escalated`, `late`;
  - views_orcs.py and the templates;
  - views_ai_models.py and ai_models.html;
  - core/platform_control.py: three switches;
  - management/commands/orcs.py: `smoke --row` accepts the routed rungs
    under the gates;
  - ai_agents/catalog.py: `ORC_FALLBACK_V1` beside the ladder, the only new
    model id literal, in the only file allowed to hold one.

#### 1.2.4 Rules

**B.1 The router** (`router.py`, pure).
- `route(band, world, kind, day_class, frontier_left, gate, effort_mode)`
  returns {rung, why[], escalated, probes[], twin, routing_version}.
- **Table v1** (catalog.py:505-519 notes; map_army B1):

  | Band | Rung |
  |---|---|
  | routine | r0 |
  | material | r1 on paper and demo; r2 on real money |
  | complex | r3 |
  | extreme | r5 when the gate passes (B.9); otherwise r4 |

- h0 is never routed (catalog.py:506-507).
- Demo routes as paper (constants.py:39-43).
- The band already carries the floors F1-F4 (complexity.py:256-274).
- **KEEP:**
  - no consequence lowers a tier: the router reads no seat level, scar,
    probation or privilege (complexity.py:23-25);
  - F3 and F4 apply only to a binding action on the table, and in O2
    `binding_on_table` stays False (wake.py:735). As coded, F4 equals F3
    (map_wakes trap 21). Kept, and noted for O3.

**B.2 Routing in shadow.**
- `orcs_router` is OFF on arrival.
- Every render writes `components["route"]` = {rung, would_rung, why,
  version}, at no cost.
- **OFF:** `components["rung"]` stays O2a's r0.
- **ON:** `components["rung"]` = the ANSWERING rung: the routed rung after
  B.5's mapping. `RUNG_LIMITS`, the bound (A.21), the tier, `CALLER_RUNGS`,
  the `source_ref`'s rung and the grade's tag are all the answering rung's.
  The routed rung is kept only as `components["route"]["would_rung"]`, so
  the reservation and §2.7's per-rung p90 are never booked under the wrong
  rung.
- On a merge the route is computed again from the survivor [P15].

**B.3 Ids only at the gateway.**
- The gateway reads (model id, effort) from `ORC_LADDER_V1` by rung name.
- `ROUTING_VERSION` "table-v1" (constants.py:358-359) is written on every
  wake.
- A later table becomes `ORC_LADDER_V2` with a new version.

**B.4 The render for the routed family, once.**
- With `orcs_router` ON, `render_wake` first computes the score, the floors
  and the band: they read the context and the reasons, never the render
  (wake.py:729-741). It then routes (B.1) and renders ONCE, for
  `family_of(model)` of the answering rung (dossier.py:65-76, :360).
  `components.tokens` is that render's, so the bound is the routed family's.
  The beats already build MK and IN-slow for every family (tasks.py:163-170,
  :258-266).
- A Fable route renders with the 1.35 factor (constants.py:294). Only a
  Fable render that comes back `over_budget` renders again, for r4's
  family; the failing clause is journaled. `block_hashes` holds the final
  render (models.py:178).

**B.5 One effort per model until the smoke's PASS.**
- Without a recorded PASS for a family (A.61), that model runs at one
  effort: Sonnet at r0's (low), Opus at r2's (medium).
  - The router's own choice is kept as `would_rung`.
  - The answering rung maps r1 to r0, and r3 and r4 to r2.
  - Tickets map the same way (§1.0.9): the Emperor answers on r2 and a
    real-money question on r0 until the PASS.
- With the PASS, the full table applies, with the effort-only message.
- This honours the smoke's FAIL rule: "change model and effort per epoch,
  never per wake" (claude_smoke.py:27-29; RUNBOOK.md:1343-1348). Here the
  epoch is the whole day until the PASS is recorded (§4 Q20).

**B.6 `escalated` and `late`; no second ask.**
- `escalated` means only that a floor raised the band.
- O2b never asks a wake again after an invalid answer (N4). An invalid
  answer is a refusal (A.31).
- `late` means the answer landed after the wake's row closed (A.26).
- Both go on the card (wake.py:765-771), and `notes._intellect` reads them
  (notes.py:431-442).

**B.7 The rung on the card.**
- `rung_t` is the rung in tier words, for example "r2 · deep tier, medium
  effort".
- Never a model id, never a cost (notes.py:24-26).

**B.8 The day's caps bind.**
- `caps_for` (weather.py:37-42) makes the probes binding.
- **The frontier quota** is OrcSetting `frontier_per_day` (default 0, §4
  Q12), counted per user across all classes, less today's r5 calls counted
  on the ledger by the `source_ref`'s rung.
  - The router never reads `OrcDayBaseline.frontier_quota`. Weather wrote 1,
    2 or 4 there per (user, class) from `FRONTIER_PER_DAY`
    (weather.py:31-42, :193, :212), so a router reading it would get Fable
    calls as soon as `orcs_router` and `orcs_frontier` were ON, with the
    setting at 0.
  - From O2b weather writes the setting's value there (0 by default). The
    rows of earlier days are history and are read by nothing that routes.

**B.9 The Fable gate.** Every clause must hold:
- real money;
- the band is extreme;
- frontier quota is left today (B.8);
- the pair fits: r5's bound, computed on the Fable-family estimate, which
  `over_budget` caps at 22,000 tokens (at most $2.69 with its fallback),
  plus its twin's ($0.87), $3.56 in all, reserved together as one ticket
  under the r5 wake's class ceiling;
- A.18's `inflight` rule passes for the pair;
- `orcs_frontier` is ON;
- the Fable render is not `over_budget`.

If a clause fails, the wake goes to r4 and the failing clause is journaled.
**In O2 the gate cannot open:** the pair's $3.56 is more than the $3.00 that
A.18 allows in flight, so the `inflight` clause always fails. Fable stays at
0 through O2 whatever the quota (§4 Q12).

**B.10 The blind twin.**
- Each r5 call is paired with an r4 call on the same stored blocks, blind
  to the r5 answer (catalog.py:516-519).
- The r5 answer is the Orc's. The twin is a probe: no fallback, a bound of
  $0.87, reserved with r5 as one pair (B.9).
- With the quota at 0, neither runs.

**B.11 Probes, in shadow** (`orcs_probes`).
- **h0** runs beside a paper or demo wake on calm and eventful days
  (weather.py:41-42).
- **The boundary probe:** the adjacent rung, beside a paper or demo wake
  whose score is within `BAND_HYSTERESIS` (5) of 30, 55 or 75
  (constants.py:244-247). At most 6 a day per user.
- **A probe:**
  - is called on the wake's own stored blocks (models.py:178), blind to the
    routed answer;
  - goes through the same validator;
  - is stored only in OrcTierGrade and the ledger;
  - is never a plan, an intent, a note, a card line, a PS5 note or a
    journal entry;
  - is billed on the Orcs line: agent `orc`, `source_ref`
    `Orc:<pk>:Wake:<w>:probe:<rung>`;
  - reserves a ticket (A.57);
  - **reserves against its own allowance:** the probes' booked spend today,
    plus the probes in flight, plus this bound, stays within OrcSetting
    `probes_usd_per_day` = 15% of C ($1.50 at $10); AND the line's booked
    spend, plus everything in flight and held, plus this bound, stays
    within C − R. A share of the WHOLE line's spend would let an r3 probe
    ($0.71) or an r4 probe ($0.87) run only in the first hours of the UTC
    day, and bias B.12's blocks by session;
  - sends no fallback (B.14): a refused probe is stored as invalid, and its
    bound is the primary's alone (r3 $0.71, r4 $0.87);
  - never counts toward the Orc's own wake caps.
- Real-money wakes get no probe (§4 Q13).

**B.12 OrcTierGrade and its forward grade.**
- Both answers are priced by pricing.py over the next final decision-frame
  bar:
  - exit: the R at the first tick after the answer;
  - trim: half at that tick, half at the bar's close;
  - tighten: the bar's close, or the stop if the bar traded through it;
  - hold and revise_plan: the bar's close.
- Blocks hold `SEAT_WINDOW` (20) pairs per (boundary, kind, world).
- A boundary is "validated" after two completed blocks (catalog.py:500-504).
  The result is shown. Code never applies it in O2.

**B.13 The deep share is mirrored.** For r2 to r5, the reservation check
also holds the line's booked spend, plus the OTHER calls in flight and the
holds, plus this call's bound, within 70% of the cap (`DEEP_TIER_SHARE`,
spend.py:87, :264-272). A real-money urgent wake is exempt (decision D30).

**B.14 Fallbacks.**
- In O2, only real-money wakes on r2-r5 send the list form
  `[{"model": ORC_FALLBACK_V1, "max_tokens": 8000}]`, with the id read from
  the catalog (map_ai §6).
- Paper and demo wakes, probes, the twin and every ticket (§1.0.9) send
  none. Their bounds drop by $0.49 (29,215 × $10 + 8,000 × $25 per MTok),
  and a refusal is a billed failure, as on r0. In shadow a refusal is
  already a billed, counted failure, so the fallback buys little there and
  would lower every ceiling for Opus calls.
- Sonnet and Haiku send none (claude_provider.py:238-253).
- The bound includes the fallback where one is sent (A.21).
- When a fallback served, `usage["model"]` is written on the wake and the
  decision entry.

**B.15 `CALLER_RUNGS` grows.**
- wake: r0-r4, plus r5 only through B.9;
- probe: h0, r0, r1, r3, r4;
- twin: r4;
- smoke: the wake's rungs, under the same gates, with r5 only through B.9;
- from O2c and O2d: captain, emperor, skeptic, postmortem, tribunal and
  question, as §1.0.9 lists them.

**B.16 The surfaces.**
- **/ai-models/:** per rung, today's calls and probes, and each boundary's
  validation state. The card's sentence says routing runs in shadow
  (ai_models.html:151-175; U-R6).
- **/orcs/seats/ (staff):** a ladder table from OrcTierGrade
  (views_orcs.py:300-354).
- **The Orc page:** the Rung column, with "would route: r2" while the router
  is OFF.

#### 1.2.5 Pitfalls designed out

| P | Designed out by |
|---|---|
| P1 | probes are capped measurements on tickets (B.11) |
| P5's twin | probes never consume the Orc's caps (B.11) |
| P6's twin | probes on their own allowance, inside C − R (B.11) |
| P15 | the route is recomputed on a merge (B.2) |
| P22 | a probe's text reaches no surface (B.11) |
| P34, P35 | the command's rungs and the Fable gate (B.9, B.15) |
| P36-P39 | the tests below |

#### 1.2.6 Tests (red first, fake model)

- **The table:** band × world × day × quota gives the rung; h0 is never
  routed.
- **The switch** (each switch's zero-call case as a pair, N7):
  - OFF: the router's choice is recorded, and the fake records r0's model;
  - ON: the fake records the routed model;
  - each of the three switches takes the PIN to turn on (N2).
- **One render:** with the router ON, one render per wake, for the routed
  family, except the Fable fall-back; `components.tokens` is that render's.
- **The family:** a Fable route renders × 1.35 and falls to r4 when over
  budget.
- **The answering rung:** RUNG_LIMITS, the bound, the tier, the
  `source_ref` and the grade's tag are the answering rung's; `would_rung`
  keeps the routed one.
- **Effort without a PASS:** r1 is sent as r0, r3 as r2 (the fake sees the
  effort); with a PASS, the effort-only message carries the rung's effort.
- **Probes:**
  - a paper wake on a calm day at score 27 calls h0 and r1;
  - the same wake on a stormy day calls neither;
  - a real-money wake calls none;
  - the probe's answer appears in no slot key and in no PS block of the
    next wake;
  - the cap of 6 holds;
  - an r3 probe late in the UTC day still fits its own allowance, and one
    past `probes_usd_per_day` is refused with an empty call list.
- **The twin:** r5 never runs without r4; with the quota at 0, neither runs;
  with the floor raised in the test, the pair reserves as one ticket of
  $3.56; at the real $3.00 floor the pair is refused (`inflight`).
- **The frontier quota:** with a day row at `frontier_quota` = 4, and
  `orcs_router` and `orcs_frontier` ON, a real-money extreme wake routes to
  r4, and the fake records no Fable model.
- **The deep share:** an r2 claim is refused at 70%, but not for a real
  urgent wake.
- **Fallbacks:** the fallback id comes from the catalog, and the bound
  includes it; a paper r3 wake, a probe and the twin send none.
- **The card:** `rung_t` in tier words, with no id and no cost.
- **K-B10:** the walk of N6 on every routed request.
- **Unchanged:** the ladder pins and the catalog pins.

#### 1.2.7 What the operator sees

- **`orcs_router` OFF:** each wake shows "would route: r2 (deep tier,
  medium effort)". /ai-models/ shows the would-counts per rung.
- **ON:** wakes are answered on their rungs; the card shows the rung in
  words.
- **`orcs_probes` ON:** a staff ladder table fills up, block by block.
- Fable stays at 0.

#### 1.2.8 Money direction

- **Account money:** none moves.
- **AI money:**
  - with the router ON, 10 positions cost about $5.88 to $11.48 a day
    central, against r0's $4.47 to $5.36 (§2.4). Under a $10.00 line, a
    stormy central day answers about 35 wakes by code (§2.5);
  - probes add about $0.48 a day (6 boundary probes on r1), and at most
    their own allowance, 15% of the line;
  - Fable adds $0: its gate cannot open in O2 (B.9).

---

### §1.3 O2c: honor, temperaments, Captains, the Emperor and the drums, in shadow

#### 1.3.1 Scope

Five parts, each behind its own switch where it calls a model. All of them
run in shadow:
1. **Honor:** code audits over the shadow record. No model.
2. **Temperaments:** drawn at birth, fixed for life, shown in PS9 and
   graded.
3. **Captains:** one per (user, class), with orders in shadow, shown in PS11
   and graded, never applied.
4. **The Emperor:** one daily order per user in MK-E, under a new key.
5. **The drums:** W12 drum wakes from `drum_bus.route`, behind a new switch
   of their own (`orcs_drum_wakes`), with waves, a settle and a breaker; the
   wave stamp on shadow intents.

The Skeptic co-signs a Captain's cut and an add, in shadow. Each of the five
new switches takes the PIN to turn on (N2).

O2c depends on O2a only.

#### 1.3.2 Models and migration

| Model | Fields |
|---|---|
| `Captain` (new) | user, asset_class (unique together), seated_at, label, state, last_wake_at, wakes_today, counters_day, pending {reasons, queued_at} |
| `CaptainOrder` (new) | captain, kind (`hold_fire`, `tighten`, `cut`, `theme`), scope {class, or orc ids}, level_id, words (filtered, capped), mode `shadow`, issued_at, expires_at, cause {wave_id or wake}, skeptic {verdict, words}, grade {r_issue, r_end, value_r, at}, s_version |
| `OrcWave` (new) | wave_id (unique), user, kind, symbols, origin, first_at, last_at, max_hop, drums, reach, w12_queued, w12_answered, cost_usd, breaker {state, why} |
| `OrcTemperamentGrade` (new) | temperament, version, venue, asset_class, bar_source, n, mean, se, lb80, ub80, vs_control_mean, block, at |
| `Orc.temperament` (AddField) | CharField 16, blank |

- `JOURNAL_KINDS` gains `skeptic`.
- `AUTHORS` gains `emperor` (constants.py:30-31).
- `FENCE_CAPS` gains temperament 600, captain 280, emperor 600 and skeptic
  280.

#### 1.3.3 Code it adds or changes

- **New:** `honor.py`, `temperament.py`, `captains.py`, `emperor.py`,
  `skeptic.py`.
- **Changed:**
  - drum_bus.py: the W12 seam at :41 and :666-667; waves; the breaker;
    :219-221 re-marked "# O3:" (C.17); `drum_bus.on_close` itself is
    unchanged (N1.2);
  - wake.py: the settle at detection; the carried W12 reasons (C.16); the
    facts hash gains PS11's version;
  - dossier_market.py: MK-E's new key at :258-268 and :290-308;
  - dossier_position.py: PS9 and PS11;
  - birth.py: the temperament draw, in its own transaction after `_create`
    commits (C.4; `_create` itself is unchanged, N1.2);
  - grading.py: shadow breaches and tags;
  - notes.py and horde.py: the class band slot, the voices,
    `CAPTAINS_NOT_BUILT` (C.10);
  - sv-horde.js:1136-1162: the Captain words;
  - views_orcs.py: `AUTHOR_STYLE` emperor → note;
  - tasks.py and config/celery.py: the Captain, Emperor and Skeptic tasks
    on `orcs`;
  - core/platform_control.py: five switches, all in `ORC_MIND_SWITCHES`,
    and `orcs_drums`'s description (C.19);
  - tests/test_the_book.py: the bench tripwire reads the switch's name
    (C.19);
  - the RUNBOOK's drum lines (:1585-1594).
- **Seam markers:** §1.0 item 6's table.

#### 1.3.4 Rules

**C.1 Honor audits** (`honor.py`, pure; run at the grade).
- The lost code of honor's article numbers are not restated, except VI (the
  integrity verdict) and IX (the fence), which the code cites
  (integrity.py:1-2; fence.py:1-2). Each audit carries its own code:
  - **H1, an unacknowledged miss:** a decision after a "missed" expectation
    fact that does not cite it;
  - **H2, an unacted signpost:** a met predicate, a thesis-check exit, or
    the Orc's own "dead", with no exit, trim or tighten proposed within one
    decision bar (predicates.py:350-354; dossier.py:187-197;
    tribunal.py:7-9);
  - **H3, the tripwire:** the O arm closed past `TRIPWIRE_IDEA_R` = −1.2R,
    "the stop did not hold" (constants.py:143; it equals Morgul's G12).
- Each finding is a journal entry: kind `breach`, author `code`, body
  {code, mode: "shadow", evidence ids} (constants.py:27).

**C.2 The shadow verdict.**
- `OrcGrade.tags` gains `shadow_breach:H1` and the like (models.py:275).
- The grade's body carries `tribunal.classify` run with the shadow breaches,
  as the class the idea would get if they bound.
- **KEEP:** the binding grade still passes `breaches=0`,
  `signpost_unacted=False` and `exit_available=False` (grading.py:149-152).
  No idea is FAULT in O2 (tribunal.py:22-23).
- Refusals never count as faults (tribunal.py:54-55).
- G13 stays unbuilt: it has nothing to read until O3 (§3).

**C.3 Temperaments** (`temperament.py`, pure, versioned "t1").
- **The set:** six temperaments, one per voice that can manage a single
  position (Striker, Fixer, Skeptic, Awakened, Executioner, Champion), plus
  a control with no lead voice (§4 Q14).
- **The lane texts are COPIED as constants**, because the package imports
  nothing of ai_agents. A test outside the package imports
  ai_agents/agents/council.py and trade_debate.py and pins them equal
  (ai_agents/agents/council.py:260-486;
  trade_debate.py:150-189). URUK_* are pinned the same way
  (constants.py:96-99).
- **Nothing reads `voice_weight`,** so tests/test_council_shadow.py:275-294
  stays as it is.

**C.4 The draw, just after birth.**
- With `orcs_temperaments` ON, every newborn draws one temperament. The
  draw runs in its own transaction after `_create` commits (an on-commit
  step of the birth path), and locks the Orc row only. It never runs under
  the trade row's lock, which `_create` holds for its whole transaction
  (birth.py:292; N1.2).
  - The draw takes the temperament with the fewest Orcs on its seat, the
    control included.
  - Ties are broken by a seed of the root trade id.
- It writes `Orc.temperament` and a journal entry: kind `temperament`,
  author `code`, "Temperament: {name} (lead voices: ...)."
- The temperament is fixed for life. The switch governs only new draws.
- Orcs born with the switch OFF have none, and are never graded as a
  temperament.

**C.5 PS9.**
- PS9 shows the lead voices' names and lane texts, as
  `fence.view("temperament", ...)`.
- The control's PS9: "— (control: no lead voice)".
- PS sits inside `PS_TAIL_RESERVE` (dossier_instrument.py:39-41) and is
  never trimmed. PS9 is measured and fitted there, and the reserve moves if
  needed.

**C.6 OrcTemperamentGrade.**
- It is written per (temperament, version, venue, class, bar source).
- It holds `block_stats` of Δ against the care (tribunal.py:92-105), over
  the counted grades with `n_llm > 0`, and the difference against the
  control.

**C.7 Captains** (`captains.py`, `orcs_captains`).
- **Seating:** one Captain per (user, class) while the class has a living
  Orc. It is never deleted.
- **Its wakes:**
  - the class's first session open of the trading day;
  - a `level_break` wave of its class (drum_bus.py:16-19);
  - after the Emperor's order;
  - at most 4 a class a day, spaced 15 minutes apart.
- **The pending item:** one per Captain, with `queued_at` set once. It goes
  stale at 30 minutes and is then dropped with a code.
- **The call** (§1.0.9):
  - agent `captain`, `source_ref` `Captain:<class>:Wake:<n>:<rung>`;
  - `CALLER_RUNGS["captain"]` = ("r0",);
  - a ticket (A.57), at most 10,000 tokens, one billed attempt per wake;
  - triaged with real non-urgent wakes (C − R).
- **Its prompt:** its own doctrine (`CAPTAIN_DOCTRINE`, version c1, at most
  6,000 characters, carrying A.29's authority sentence), plus:
  - its living Orcs' cards: the plan lines, intents, R, the care beside
    each, the army type and the temperament;
  - the class's weather;
  - the same bets;
  - the book as shares of its limits (`sources.book`);
  - the Emperor's line.

  Never another user's book (drum_bus.py:34-35).
- **The answer:** `CAPTAIN_SCHEMA_V1` {orders: [{kind, scope, level_id,
  words}], note}, validated by V1, V11, and a check that the named Orcs
  belong to its class and user.

**C.8 Orders in shadow.**
- Each order is a `CaptainOrder`, journaled `captain`, author `captain`, on
  each Orc it names, as a view and never a fact (dossier_position.py:176-184
  lists facts only).
- PS11 shows the unexpired orders that name the Orc, and the Emperor's theme
  orders (dossier_position.py:304).
- The facts hash gains PS11's order version, so the next metronome wake is
  not quiet (map_army C16).
- **KEEP:** `captain_may_cut` stays False (models.py:67). A cut is graded,
  never applied, and never moves the O arm. The O arm follows the Orc's own
  intents only.

**C.9 Grading an order** (at the named idea's grade).
- A cut: `value_r` = the R at issue less the named O arm's exit R.
- A tighten: whether price hit the level before the idea's exit, with the R
  at the level against the arm's exit R.
- Every price comes from pricing.py.

**C.10 The class band.**
- It shows the label, the orders in force, the open waves, the fallen and
  the Emperor's line (notes.py:749-771; horde.py:422-440, :1665).
- `for_classes` stays at a constant number of queries
  (tests/orcs/test_orc_notes.py:491).
- `CAPTAINS_NOT_BUILT` (dashboard/horde.py:281-283;
  templates/_partials/the_horde.html:148; sv-horde.js:1162) stops being
  true when O2c ships, even with `orcs_captains` OFF. While that switch is
  OFF it reads "No Captain seated: the Captains' switch is off." Once a
  Captain is seated, the band shows it.

**C.11 The Emperor's order** (`emperor.py`, `orcs_emperor`).
- **When:** one per user per trading day, after `orc_day_roll`
  (tasks.py:145-197; config/celery.py:500-503), once each class's weather
  exists.
- **The call** (§1.0.9):
  - agent `orc_emperor`, `source_ref`
    `Orc:Emperor:<user pk>:<trading day>:<rung>`;
  - `CALLER_RUNGS["emperor"]` = ("r3",), answered on r2 until the PASS
    (B.5);
  - no fallback (B.14), so O2c needs no fallback code of its own;
  - a ticket (A.57), at most 16,000 tokens, triaged with real non-urgent
    wakes (C − R); one billed attempt per day: an order refused every time
    is billed once, never once a beat.
- **Its prompt:** its own doctrine (`EMPEROR_DOCTRINE`, version e1, at most
  6,000 characters, carrying A.29's authority sentence), plus its inputs:
  - each class's weather;
  - the Captains' orders and their grades;
  - the living Orcs' counts and R;
  - the fallen;
  - the book as shares;
  - the people's mood, read through the gateway (ai_agents/council_mood.py):
    its fractions only, never the book size or drawdown it computes them
    from (K-B10; the walk of N6).

  Never another user's book. Never money.
- **The answer:** `EMPEROR_SCHEMA_V1` {order: words, themes: [{class,
  stance: press, hold or none, theme}]}, through V1 and V11.
- **The council's law holds:** nothing in sizing, a gate or an order path
  reads the order (ai_agents/agents/council.py:38-50).

**C.12 MK-E under a NEW key** (the `find` trap).
- `dossier.find` returns the OLDEST block of a kind and key
  (dossier.py:135-138). The dash built earlier under `<day>|mk_e` would win
  forever.
- So the order is stored under `<day>|mk_e|<user>|order`. `day_hashes`
  takes the order when one exists for the user, and the dash otherwise
  (dossier_market.py:258-268, :290-308).
- MK-E becomes per user, as the last shared block. MK0 and the session
  blocks stay shared across users (dossier_market.py:29-32).
- The order changes the shared prefix once a day: one cache write per model.

**C.13 The Emperor's journal and names.**
- One `emperor` entry, author `emperor`, on each living Orc of the user,
  written with `card=False`: it is shown on the Orc's page and in MK-E,
  never on the card's lines (map_army C23). `AUTHOR_STYLE` draws it as a
  note (views_orcs.py:52-54, :225).
- One persona with two duties, named apart wherever both show: "the
  Emperor's order to the Orcs" and "the council's chair"
  (ai_agents/agents/council.py:436-438;
  council_band.py:206) (§4 Q15).

**C.14 W12, the drum wake** (drum_bus.py:666-667; map_army C25).
- **Its own switch.** `orcs_drum_wakes`, "Orc Drum Wakes (models in
  shadow)", is new: System, OFF on arrival, in `BULK_ENABLE_EXEMPT` and
  `ORC_MIND_SWITCHES`, never in `LIVE_MONEY_SWITCHES` (N2). `orcs_drums`
  keeps journaling the drums (drum_bus.py:84-93). It may already be ON in
  production, since it was inert since O1, so the power that spends needs a
  switch that is OFF on arrival.
- In `route`, for each delivery, while `orcs`, `orcs_drums`,
  `orcs_drum_wakes`, `orcs_minds`, the platform master and the line are all
  on (drum_bus calls `scheduler.minds_ready(drums=True)`; drum_bus names no
  ai_agents), add a reason through `wake._queue` (wake.py:843-857): {code
  W12, key `W12:<wave_id>`, urgent: `_urgent_for(orc, drum)` with its stop
  clause narrowed for W12 to 0.25 × ATR(1h) (drum_bus.py:582-597), t: code
  words}.
- One W12 per (wave, Orc).
- Urgency is read again on a merge [P15].
- `drums_on()` gets its first reader (drum_bus.py:84-93).

**C.15 The settle.**
- `wake.detect` records a W12 no earlier than `DRUM_SETTLE_MIN` (15) after
  its wave's first drum (constants.py:255; today read by nothing).
- The drums that join within `DRUM_JOIN_MIN` wake the Orc once.

**C.16 OrcWave and the breaker.**
- One OrcWave row per wave.
- **The breaker:**
  - at most 6 W12 model wakes a wave, and at most 12 a user an hour, urgent
    ones included;
  - at most `DRUM_URGENT_PER_ORC_DAY` = 2 urgent W12 model wakes per Orc per
    UTC day. Beyond that, the W12 reason waits in the Orc's memory
    (`seen["w12_carry"]`) and joins its next recorded wake, with no wake of
    its own, and the delivery is journaled;
  - drum wakes as a whole stop at `DRUM_SHARE` = 25% of the line (the W12
    spend booked today, plus the W12 calls in flight, plus this bound),
    urgent ones included;
  - none once the Orcs line is 60% spent, except an urgent W12 on the Orc's
    own stakes: it is exempt from this rule only, and still runs inside its
    triage ceiling [P14's twin].
- When it trips, the deliveries are journaled only, as in O1, and the wave
  records why.
- **Why.** `_urgent_for` makes a delivery urgent whenever the receiver's stop
  is within 1 × ATR(1h) of the mark, whatever the drum's kind. In a
  correlated shock ATR widens, so most stops qualify and nearly every W12
  would be urgent: two workers at about 45 s per r0 call could answer about
  160 drum wakes an hour, and one storm hour would spend the whole line,
  reserve included.

**C.17 The wave stamp.**
- An intent from a wake that carries W12 gets `OrcIntent.wave_id`.
- The O arm's would-stop carries the wave and its hop in the arm's own state
  (`intents.take`). drum_bus.py:219-221, inside the real close path, stays
  unfilled in O2 and is re-marked "# O3:" (N1.2).
- **KEEP:** no real stop carries a wave.
- **KEEP:** a would-stop hit never publishes a drum. Drums come from real
  facts only (drum_bus.on_close, drum_bus.py:194-224).

**C.18 The Skeptic's co-sign** (`skeptic.py`, `orcs_skeptic`).
- It signs on a Captain's `cut` and on an add the officer would allow or
  cut, nothing else (§4 Q16).
- **The call** (§1.0.9): r0, at most 6 a day per user; agent
  `orc_skeptic`; `source_ref` `Orc:<pk>:Skeptic:<intent>:r0` or
  `Captain:<class>:Skeptic:<order>:r0`; its own doctrine
  (`SKEPTIC_DOCTRINE`, k1); a ticket of at most 6,000 tokens, triaged with
  its item's class (a Captain's cut with real non-urgent wakes; an add with
  the Orc's own non-urgent class).
- Its verdict is journaled `skeptic` beside the item. It is never a gate.

**C.19 The words.**
- `orcs_drums` keeps its NAME, "Orc War Drums (wakes from O2)", in O2c, and
  only its description changes (D-C2; core/platform_control.py:330-332):
  "Off (default). With orcs on, the war drums (a stop hit, a lock, a level
  break...) are always journaled on the Orcs they reach within one user's
  book. On, with Orc Drum Wakes on, a drum also wakes the Orcs it reaches,
  in shadow."
- **The Book's bench tripwire.** test_the_bench_is_not_on_main
  (tests/test_the_book.py:2223-2231) asserts that the description contains
  "from O2" while "The Orcs' shadow minds" is on the bench, and the bench
  line moves only at D.19. So O2c changes that assertion on purpose, in the
  same commit, to read the name: `assertIn("from O2", drums["name"], ...)`.
  Otherwise the suite is red from O2c until O2d. tests/test_the_book.py
  joins O2c's pin list (§1.3.6).
- D.19 renames the switch "Orc War Drums", moves the bench line and rewrites
  the same test.
- RUNBOOK.md:1585-1594 changes the same way.
- New Captain and Emperor sentences are registered (N6).

#### 1.3.5 Pitfalls designed out

| Twin of P | Designed out by |
|---|---|
| P2, P5, P6 | Captains, the Emperor and the Skeptic on tickets, with their own caps and triage places (C.7, C.11, C.18; §1.0.9) |
| P9, P10 | the Captain's pending item keeps `queued_at` once and goes stale at 30 (C.7) |
| P14 | an urgent own-stakes W12 is exempt from the 60% rule only, within 2 a day per Orc and the 25% drum share (C.16) |
| P15 | W12 urgency read again on a merge (C.14) |
| P22 | every order, theme and verdict through V11 (C.7, C.11, C.18) |
| P25 | PS9 and PS11 as of the wake (map_army §4.6) |
| P27 | PS11's version in the facts hash (C.8) |

#### 1.3.6 Tests (red first, fake model)

- **Honor:** H1-H3 on hand-built journals; no idea is FAULT.
- **Temperaments:**
  - the lane texts equal the prompts;
  - the draws are balanced, and fixed for life;
  - the draw runs after `_create` commits: the trade row is not locked
    while it runs, and `_create`'s pinned hash is unchanged (N1 h);
  - OFF means no draw;
  - PS9 and PS11 fit `PS_TAIL_RESERVE`.
- **Captains:**
  - the cadence and the cap of 4;
  - an order names only its own class's Orcs;
  - no cut changes `captain_may_cut`, the O arm or a row.
- **The Emperor:**
  - the order is found and the dash is not (the trap);
  - its text passes the money filter;
  - MK0's bytes do not change;
  - a fake that refuses every order is called once a day.
- **Drums:**
  - with `orcs_drums` already ON from before O2c, `orcs_minds` ON and the
    line set, a delivery journals the drum and records an empty call list;
    the same fixture with `orcs_drum_wakes` ON queues exactly one W12 (the
    positive control);
  - an own-stakes drum is urgent only within 0.25 × ATR(1h), and the others
    are not;
  - the settle;
  - the breaker trips at its numbers; 20 waves reaching one real Orc whose
    stop sits 0.5 ATR from the mark make at most 2 urgent W12 model wakes,
    and drum wakes stop at 25% of a fake line; an urgent own-stakes W12
    still runs past the 60% rule;
  - a carried W12 reason joins the Orc's next recorded wake;
  - a would-stop hit publishes no drum; `drum_bus.on_close` is unchanged.
- **The Skeptic:** it runs only on its two items; it is never a gate.
- **Every ticket caller:** refused at its ceiling with an empty call list,
  and a positive control just under it (§1.0.9); the K-B10 walk (N6) on the
  Captain's and the Emperor's requests.
- **Every new switch:** OFF means an empty call list, as a pair (N7); ON
  takes the PIN (N2).
- **The Book:** the bench tripwire reads the switch's name, and the full
  suite is green at O2c (C.19).

#### 1.3.7 What the operator sees

- **The Orc page:** the temperament, the Captain's orders in force as
  views, the Emperor's line, shadow breaches with their codes, the
  Skeptic's verdicts.
- **The class band:** a seated Captain's label, orders, waves and the
  fallen.
- **Drums:** W12 wakes appear among the wakes.
- Nothing about any position changes.

#### 1.3.8 Money direction

- **Account money:** none moves.
- **AI money:** about $0.47 a day central: Captains $0.20, the Emperor
  $0.21, the Skeptic $0.06 (calc/army_costs.py). It is about $0.66 on a busy
  day, on the spec's own rungs: 8 Captain wakes on r0 at their cap × $0.034,
  the Emperor $0.208, 6 co-signs × $0.030.
- **W12 wakes** are ordinary wakes under A.12-A.14, capped by the breaker:
  at most 25% of the line (C.16).

---

### §1.4 O2d: seats, ranks, the council of war, Q&A, the post-mortem and the surfaces

#### 1.4.1 Scope

- **Seats and ranks in shadow:** each lineage's record, its earned level and
  the White Hand mark. Code only, and never any power.
- **The post-mortem**, then **the council of war's words**, after each
  idea's grade, with lessons, weapons, scars and heritage (PS10).
- **OrcActionGrade:** each simulated intent and each judged add, graded
  forward.
- **Q&A:** "/orc N question", answered by a queued task, and on the Orc's
  page.
- **The surfaces:** every remaining O1 sentence made true, and the Book's
  bench line moved at the PR's landing.

Each of the three new switches takes the PIN to turn on (N2). O2d depends
on O2a, and reads O2c's breaches when they exist.

#### 1.4.2 Models and migration

| Model | Fields |
|---|---|
| `OrcBattle` (new) | orc (one-to-one), grade, fell, sub_label, causes (set by code), shadow_verdict, words (filtered), postmortem entry id, cost_usd (staff only), at |
| `OrcLesson` (new) | seat (the lineage), battle, text (≤ 200, filtered), kind do or avoid, evidence ids, created_at, retired_at |
| `OrcWeapon` (new) | seat, battles, pattern {playbook id or plan clause kind}, n, mean, lb80, ub80, text, created_at |
| `OrcActionGrade` (new) | intent (one-to-one), orc, kind, applied_at, r_at, fwd_r, horizon, at |

- `OrcSeat.stats` is a JSON field that already exists.
- `OrcGrade.seat_block` already exists (models.py:272).
- Journal kinds and authors needed: `postmortem`, `question`, `answer`,
  `rank`, `heritage`, `scar`. They already exist (constants.py:22-28).

#### 1.4.3 Code it adds or changes

- **New:** `seats.py`, `postmortem.py`, `tribunal_words.py` (the council
  of war's call; tribunal.py stays code only), `questions.py`.
- **Changed:**
  - ranks.py (pure words);
  - grading.py: stamps `seat_block`;
  - notes.py: the lineage keys at :471-485, `for_rows`' third query at
    :688-689, and the words;
  - surfaces.py: the question branch at :292-294, kept free of the model;
  - views_orcs.py and the templates: the question form, the lineage cards;
  - horde.py and sv-horde.js: the Orc box at :1667-1707;
  - views.py and positions_list.html, views_close.py: plan and intent
    lines;
  - telegram_eye.py: registers the reply's "then";
  - tasks.py and config/celery.py: the seats beat, the post-mortem, the
    tribunal and answer tasks;
  - core/platform_control.py: three switches;
  - core/book_content.py: the bench line at the landing.

#### 1.4.4 Rules

**D.1 The seats beat** (`seats.py`, after `grade_closed` at :40;
config/celery.py:482-485).
- Per seat and per bar source, never pooled (grading.py:17-24), it:
  - cuts the counted grades into blocks of `SEAT_WINDOW` (20), in
    `graded_at` order;
  - takes `block_stats` and `block_faults` (tribunal.py:92-129);
  - writes `OrcSeat.stats` = {n, blocks [{i, n, mean, se, lb80, ub80,
    fault}], earned_level, provisional, coin_toss, white_hand, probation,
    scars, breaches, disbanded, by_source, at};
  - stamps `OrcGrade.seat_block`.

**D.2 What counts.**
- A grade counts for a seat only if `counts_for_seat` AND its idea had at
  least one model wake (`OrcGrade.n_llm > 0`, A.58).
- O1-era grades never fill "n of 20". In O1, Δ measured the care ghost
  against the care (views_orcs.py:39-41).
- O1's rows keep `counts_for_seat` as written.

**D.3 The earned level, in shadow** (Aragorn's shape, bot_program/aragorn.py:53,
:90-94, :205-219).
- A full block with LB80 > 0 earns one level.
- UB80 < 0, or a block fault, loses one.
- At most one step per block.
- "Coin toss" when LB80 ≤ 0 ≤ UB80.
- "Provisional" while n < 20.
- Written to `stats["earned_level"]` only.

**D.4 KEEP: no power.**
- `OrcSeat.level`, `status` and `pinned` are never written in O2 (N1.5; a
  source pin).
- `effective_level` stays 0 (notes.py:287-290).
- `level_at_birth` stays the seat's level.
- STAKES_L3 stays off (complexity.py:230-233).

**D.5 The White Hand.**
- The mark: the Uruk-hai bar met on the shadow record at an earned L2 or
  above (army.py:125-137; constants.py:96-104).
- It is shown, and grants nothing. Uruk-hai stays unreachable without the
  operator's PIN (army.py:236-243).

**D.6 Scars and ranks.**
- A block fault scars the lineage: `stats["scars"]` and a `scar` entry.
  In O2, only a block fault can scar.
- A `rank` entry (a code fact) is written on the seat's living Orcs when
  the earned level changes. PS1 never shows a rank
  (dossier_position.py:11-12, :72).
- The rank's key is `lineage`, never `seat` (notes.py:28; Horde C18).

**D.7 The words of rank** (ranks.py, pure).
- "L0 · Snaga; earned in shadow: L1 · Tracker, n 23, coin toss".
- HOLDS reads as "would hold".
- Every rank surface shows the effective rank first, then the earned one
  (map_army §5.2 table).

**D.8 The post-mortem** (`postmortem.py`, `orcs_postmortem`).
- One per graded idea with `n_llm > 0`, after its grade, never at death
  (grading.py:132-139).
- A killed or hand-touched idea gets one too.
- **The call** (§1.0.9):
  - agent `orc_postmortem`, `source_ref` `Orc:<pk>:Postmortem:<grade>:r0`;
  - `CALLER_RUNGS["postmortem"]` = ("r0",);
  - a ticket of at most 12,000 tokens, triaged last (0.30 × C, A.13);
  - one billed attempt per idea: a fake that refuses every post-mortem is
    called exactly once. Only a budget refusal may wait, at most until the
    next UTC day; then the item closes `expired` (A.57).
- **Its prompt:** its own doctrine (`POSTMORTEM_DOCTRINE`, p1), then the
  journal digest (trimmed oldest first to fit, never the grade or the
  arms), the plan versions, the intents and their grades, and the arms with
  their class and labels as set by code.
- **Its output:** kind `postmortem`, author `orc`, filtered and capped.
- It is idempotent: one per idea, with a unique key.

**D.9 The council of war's words** (`orcs_council_of_war`).
- One call per graded idea that has a post-mortem (§1.0.9).
  - Agent `orc_tribunal`; its own doctrine (`TRIBUNAL_DOCTRINE`, w1).
  - `CALLER_RUNGS["tribunal"]` = r2 on real money, r0 on paper and demo.
  - A ticket of at most 12,000 tokens, triaged last (0.30 × C), with one
    billed attempt per idea (A.57).
- **KEEP:** the class and the labels stay code's (tribunal.py:1-3). The
  words can never change `fell` or `sub_label`.
- The answer carries the words, at most 2 lesson candidates and at most 2
  weapon candidates, each citing fact ids.
- An `OrcBattle` row is written.
- On surfaces it is "the council of war" or "the fallen", never "battles":
  that name belongs to the council of ten (council_band.py:202,
  :1136-1145).

**D.10 Lessons and weapons.**
- **A lesson:** at most 200 characters, filtered, of kind do or avoid.
  - At most 5 in force per lineage; the oldest is retired.
  - A lesson is never a rule that code obeys.
- **A weapon:** a pattern code can recognise, either a playbook id or a
  plan clause kind.
  - It is listed only when its Δ over at least `BLOCK_FAULT_MIN_N` (5)
    ideas reads LB80 > 0. Until then it stays a lesson.

**D.11 Heritage.**
- A seat's newborn Orc gets a `heritage` entry: its lineage's lessons in
  force, its weapons and its scars. It is written in its own transaction
  after `_create` commits, locking the Orc row only (N1.2), like C.4's draw.
- PS10 shows them as views, sized inside `PS_TAIL_RESERVE`
  (dossier_position.py:303).

**D.12 IdeaFacts in O2.**
- `refusals` come from `n_refused`.
- `signpost_unacted` comes from H2.
- `gave_back` is W4's give-back on the O arm (constants.py:308-311).
- **KEEP:** `breaches` and `exit_available` stay as they are in O1 (C.2).

**D.13 OrcActionGrade.**
- **The horizon:** the next final decision-frame bar after `applied_at`,
  priced per kind as B.12 prices each kind. `r_end`, the R at the idea's
  end, is stored as well.
- **A simulated intent:** the O arm's R over that horizon, against the R
  the care ghost's path reached over the same horizon, both through
  pricing.py.
- **A judged add:** the would-leg's R from its would-entry (the price at the
  first tick after validation) to the O arm's exit, at its would-share.
- It feeds the post-mortem and the council of war.

**D.14 Questions** (`questions.py`, outside the three pinned modules,
tests/orcs/test_orc_source_pins_o1d.py:18-24; `orcs_questions`).
- **`ask(orc, text, user, chat)`** writes a `question` entry: author
  `operator`, the operator's own words under plain voice, no fact id.
- It queues the answer on `orcs`, with `queued_at` set once [P9's twin].
- **`surfaces.orc_reply`'s question branch** (surfaces.py:292-294):
  - answers "Received: the answer follows here." when the switches and the
    cap allow it, and otherwise says why;
  - returns the queueing as the meta "then", which the Eye runs after its
    commit (telegram_eye.py:1569-1572);
  - surfaces itself stays free of the model, of `begin_ask` and of `_send`.

**D.15 The answer task.**
- **It checks again:** the switches, the Orc, the cap and `can_spend`.
- **The call** (§1.0.9):
  - agent `orc_question`, `source_ref`
    `Orc:<pk>:Question:<entry>:<rung>`;
  - `CALLER_RUNGS["question"]` = r1 on real money, r0 on paper and demo
    (catalog.py:510-511). Until the PASS of A.61 is recorded for Sonnet, a
    real-money question answers on r0, as B.5 maps r1 to r0 (about $0.07);
    with it, on r1 through the effort-only message (about $0.10 to $0.15);
  - a ticket of at most `DOSSIER_MAX_TOKENS` + 400 tokens, one billed
    attempt per question (A.57).
- **Its prompt:** the Orc's latest wake's stored blocks (models.py:178),
  then its own doctrine (`ANSWER_DOCTRINE`, q1) and the question as
  `fence.view("operator", ...)`. If the quarantine withholds the question,
  the reply says so. Its own answer schema means it reads none of the
  wakes' cache entries (a schema change breaks the cache), so it sends no
  breakpoint of its own and pays every input token once.
- **Validation:** V1-style shape, V11 words, at most 600 characters.
- **It writes** an `answer` entry, author `orc`, and sends it with
  `telegram_eye._send` to the chat that asked, never to the alarm group
  (surfaces.py:4-6).
- **It goes stale** after 30 minutes. The reply then says the answer could
  not be made in time.
- **An answer is inert.** It never writes a plan, an intent,
  `latest_note` or a stop, and it is not a wake.
- **An ended idea** may be asked about, read only.

**D.16 The cap.**
- 10 questions a day per user, counted on `question` entries since 00:00
  UTC.
- It sits beside the Eye's own 30 (telegram_eye.py:124, :1266-1276).
- Questions on real money are triaged with real non-urgent wakes (C − R),
  never on the reserve R kept for real-money urgent wakes; on paper, with
  paper urgent wakes (0.60 × C) (§4 Q18).

**D.17 The form on the Orc's page.**
- A POST on `/orcs/<id>/` (dashboard/urls.py:255-261), accepted only while
  `orcs_questions` is ON.
- The pin "views_orcs makes one `journal.append`"
  (tests/orcs/test_orc_source_pins_o1d.py:66-84) changes on purpose.

**D.18 The surfaces.**
- O2d builds every surface hook of map_army §5.6 whose owner is O2d, among
  them:
  - the plan and intents on the positions line and in the close dialog,
    keeping `INFO_ONLY` (notes.py:191);
  - the Horde's mission plan row (map_army §5.6 item 15): the Orc's shadow
    plan on its own line, never replacing the venue's levels;
  - the Horde Orc box: the intents, the earned rank and its qualifiers, the
    temperament, the Captain's order in force;
  - `for_rows`' third query (scars and breaches) at a constant query count
    (tests/orcs/test_orc_notes.py:109, :135, :141);
  - /orcs/ and /orcs/seats/ with the earned levels and blocks;
  - Telegram's intents, temperament, order and earned rank;
  - `QUESTION_LATER` replaced by the Q&A flow, with the help line
    (telegram_eye.py:957-967);
  - `--by rung` and `--by temperament` in the scorecard
    (bot_program/scorecard.py:306-345).
- Kept as they are: the stand-down and `/orcs off` replies, whose write is
  O4a's.

**D.19 The landing** (the PR's last commit, D-B6, K-B9).
- The bench line `IN_PROGRESS` "The Orcs' shadow minds"
  (core/book_content.py:1600-1606) moves to `MILESTONES` with its hash.
- The new milestone says what stands, and never "no longer", "was handed"
  or "used to carry" (tests/test_the_book.py:2240-2250).
- The bench kicker says the bench is empty.
- `orcs_drums` is renamed "Orc War Drums", and the bench test that O2c
  pointed at the name (C.19) is rewritten for the empty bench.
- The guards: tests/test_the_book.py:2223-2238, :1620-1628, :2320-2327
  (§4 Q19).

#### 1.4.5 Pitfalls designed out

| Twin of P | Designed out by |
|---|---|
| P2, P5, P6 | post-mortems and the council of war last on tickets; questions with their own cap (D.8, D.9, D.16) |
| P9, P10 | the question's `queued_at` and its stale reply (D.14, D.15) |
| P16 | the answer is inert (D.15) |
| P22 | every word through V11 (D.9, D.10, D.15) |
| P34 | no command sends without the gates |
| P36-P39 | the tests below |

#### 1.4.6 Tests (red first, fake model)

- **Seats:**
  - O1-era grades do not fill n;
  - no O2 module writes `OrcSeat.level` (a source pin);
  - the earned level moves by D.3 and never touches `effective_level`;
  - the White Hand grants nothing.
- **The post-mortem:** written once, after its grade, idempotent; a fake
  that refuses every post-mortem is called exactly once per idea; a budget
  refusal waits at most until the next UTC day, then closes `expired`; a
  long digest is trimmed oldest first, never the grade or the arms.
- **The council of war:** it cannot change `fell` or `sub_label`; a lesson
  is capped at 200 characters and filtered; heritage appears in PS10 at
  the next birth on the seat, written after `_create` commits.
- **OrcActionGrade:** priced by pricing.py over D.13's horizon.
- **A question:**
  - with the switch OFF, no call, and the reply says why (a pair, N7);
  - past the cap, no call;
  - a real-money question answers on r0 until the PASS, and never draws on
    the reserve R;
  - an answer that names an amount is withheld;
  - the answer goes to the chat that asked;
  - surfaces.py still names no model;
  - a stale question gets its reply.
- **K-B10:** the walk of N6 on the post-mortem's, the council's and the
  answer's requests.
- **Words:** every new sentence is registered; no Orc verb anywhere; the
  landing's Book pins.

#### 1.4.7 What the operator sees

- Earned ranks in shadow beside every rank, with "provisional" or "coin
  toss".
- The council of war's words, lessons and scars on the Orc page and among
  the fallen.
- "/orc N question" answered in his chat.
- Every page saying what O2 does, with no "no model" sentence left that is
  false.

#### 1.4.8 Money direction

- **Account money:** none moves.
- **AI money:** about $0.55 a day central: the council of war $0.23,
  post-mortems $0.08, questions $0.24 (calc/army_costs.py). About $1.65 to
  $2.15 on a busy day, on the spec's own rungs: 4 councils of war × $0.116,
  4 r0 post-mortems × $0.038, and the 10-question cap at $0.10 to $0.15 each
  (r1 after the PASS; the latest wake's 26,740 tokens read with no cache).

---

## §2 The cost model

Every number comes from `calc/o2_spec_costs.py` (prices read from
ai_agents/catalog.py at 9d74a19), or is quoted from `map_ai.md` and
`calc/map_ai_costs.py`, or from `calc/army_costs.py`. Every catalog price
matches the live pricing page of 2026-11-01 (map_ai §1.2).

### 2.1 The prompt and the price card

**The day model's prompt** (map_ai §3.1) is about 26,440 tokens, as the API
will count it:
- 12,335 cached: S 3,930 + MK 8,405;
- 14,105 uncached: IN-slow 5,716 + PS and the tail 8,389.

That is O1's own estimate of 21,640 tokens, with the measured 1.27
correction on everything but S. S is a count, not an estimate.

**Output tokens per rung** (thinking included) are ASSUMED: map_ai §3.2's
lean, central and high columns. §2.7 says how to measure them.

**Prices in $ per MTok** (catalog.py):

| Model | Input | Cache read | 1h write | Output |
|---|---:|---:|---:|---:|
| Haiku 5.5 | 0.10 | 0.01 | 0.20 | 0.50 |
| Sonnet 5.5 | 2.00 | 0.10 | 4.00 | 10.00 |
| Opus 5.5 | 4.00 | 0.20 | 8.00 | 20.00 |
| Fable 5.1 | 10.00 | 0.25 | 20.00 | 50.00 |

### 2.2 Per call, and the bound

```
call = (cached x cache_read + uncached x input + output_tokens x output) / 1,000,000

r0, central:  12,335 x 0.10 = 1,234 u$
              14,105 x 2.00 = 28,210 u$
               1,500 x 10.0 = 15,000 u$          ->  $0.0444
```

| Rung | Lean | **Central** | High | Bound (A.21) |
|---|---:|---:|---:|---:|
| h0 Haiku low | 0.0018 | **0.0020** | 0.0025 | 0.0098 |
| r0 Sonnet low | 0.0374 | **0.0444** | 0.0594 | 0.1969 |
| r1 Sonnet high | 0.0544 | **0.0794** | 0.1294 | 0.2769 |
| r2 Opus medium | 0.0889 | **0.1189** | 0.1789 | 1.0459 (with the Opus 5 fallback) |
| r3 Opus high | 0.1189 | **0.1789** | 0.2989 | 1.2059 |
| r4 Opus xhigh | 0.1789 | **0.2989** | 0.5389 | 1.3659 |
| r5 Fable max (no cache) | 0.7644 | **1.2644** | 1.8644 | 2.6764 |

The r0 bound, worked: 21,640 × 1.35 = 29,215 tokens × $4.00 per MTok, plus
8,000 × $10.00 per MTok = **$0.1969**.

- **Without the fallback** (paper and demo wakes, probes, the twin and every
  ticket, B.14): r2 $0.5537, r3 $0.7137, r4 $0.8737. The Opus 5 fallback
  adds $0.4921 (29,215 × $10 + 8,000 × $25 per MTok).
- **r5's bound** is computed on the Fable-family estimate, which
  `over_budget` caps at 22,000 tokens: at most $2.69 with its fallback.
  With its twin ($0.87) the pair is $3.56 (B.9). calc/review_bounds.py
  prints these.
- **The high column is HIGH**, the estimate the per-Orc dollar cap counts
  (A.12), until each rung's measured p90 replaces it.

What the table says:
- On r0, 96% of the input cost is the 14,105 uncached tokens. The cache
  saves about $0.024 a call on Sonnet and cannot save more.
- From r1 up, output is half the cost or more. There, effort is the lever,
  not the cache (map_ai §3.4).
- The bound is two to nine times the central cost, and the release returns
  the difference at the settle. Under A.13 the bound and the money in flight
  count against every class ceiling, so each ceiling is in effect lower by
  about $0.39 on r0 (one call in flight) and by $1.4-1.6 on the Opus rungs.
  §2.5's figures come from a simulation that counts this.

### 2.3 Wakes per Orc-day

- **O1's detectors** record about 18 wakes a weekday for a 4h Orc in a
  24-hour market: W2 6, W11 6, W5 4.5, the others 1.5 (map_ai §4.1).
- **After A.50** (the metronome counts from any wake), W11 rarely fires
  beside W2. That leaves about **12**.
- **After A.10** (the print distance in bands), some routine wakes become
  quiet. The share is unmeasured.
- **Other army types** (map_ai §4.1's rates, less the W11 wakes that A.50
  removes):
  - Mercenaries (1h) record about 30 (W2 alone is 24). Under the caps,
    their routine wakes go to code once the cap is used: shadow evidence on
    Mercenaries is thinner by design.
  - An Olog-hai records about 7.
  - A US stock about 10. Its open + 60 and close − 90 triggers stay.
- **The caps** (A.12): real money 12, 14 or 16 by calm, eventful or stormy
  day; paper and demo 6. So a real-money 4h Orc sits near its cap, and a
  paper Orc is capped at half its wakes.

### 2.4 Per day

These are DEMAND figures: what the wakes would cost if every one were
answered. What a given line actually answers depends on the triage (A.13);
§2.5's figures include the triage, the bound and the cold writes.

**A. O2a: every wake on r0, at the caps.** Plus the Sonnet cache upkeep:
the cold writes a day × $0.048 (A.16). At 10 positions that is about $0.47
a day with A.16's cold-burst rule, and $0.72 without it
(calc/cost_lens_checks.py, check 2). The bursts follow the clock (the W2
closes and the prints) more than the fleet's size, so the 5- and
20-position rows carry the same $0.47 until §2.7 item 4 measures them. The
O1-era figure of $0.064 assumed the 1h entries stay warm; they do not.
Each cell reads lean / **central** / high, in $ (calc/review_table_a.py):

| Open positions (real + paper) | Calm | Eventful | Stormy |
|---|---|---|---|
| 5 (3 + 2) | 2.27 / **2.60** / 3.32 (48 calls) | 2.49 / **2.87** / 3.68 (54) | 2.72 / **3.14** / 4.04 (60) |
| 10 (5 + 5) | 3.84 / **4.47** / 5.82 (90) | 4.21 / **4.91** / 6.41 (100) | 4.59 / **5.36** / 7.01 (110) |
| 20 (10 + 10) | 7.21 / **8.47** / 11.17 (180) | 7.96 / **9.36** / 12.36 (200) | 8.71 / **10.25** / 13.55 (220) |

Without the cold-burst rule, add $0.25 to every cell (10 positions,
central: $4.72, $5.16, $5.61).

Worked, 10 positions on a calm day, central:

```
(5 x 12 + 5 x 6) x $0.0444 + $0.47 = 90 x 0.0444 + 0.47 = $4.47
```

Per Orc-day on r0, central, before the upkeep:
- real money: calm $0.53, eventful $0.62, stormy $0.71;
- paper: $0.27.

The $2.00 and $0.50 dollar caps never bind on r0: 16 × HIGH(r0) is $0.95
and 6 × HIGH(r0) is $0.36 (A.12). The count caps do.

**B. O2b: the router ON** (map_ai §5.3 C: real money 12/14/16, paper 6,
r5 off, the band mix of map_ai §4.4), plus O2b's 6 boundary probes on r1
($0.48). Central:

| Open positions | Calm | Eventful | Stormy |
|---:|---:|---:|---:|
| 5 | 3.37 + 0.48 = **3.85** | 4.86 + 0.48 = **5.34** | 6.60 + 0.48 = **7.08** |
| 10 | 5.88 + 0.48 = **6.36** | 8.47 + 0.48 = **8.95** | 11.48 + 0.48 = **11.96** |
| 20 | 11.38 + 0.48 = **11.86** | 16.59 + 0.48 = **17.07** | 22.63 + 0.48 = **23.11** |

Table B does not yet carry the cold writes of table A (about $0.5 a day on
Sonnet, more once the Opus rungs answer); the routed simulation behind
§2.5's O2b row counts the bound and the triage, not the cold writes.

On a stormy day at high output, a real-money Orc-day of 16 wakes costs
$2.87, so the $2.00 dollar cap binds, checked with HIGH (A.12). That is its
purpose.

**C. With O2c and O2d's callers ON**, 10 positions (calc/army_costs.py,
whose prompt sizes are assumptions):
- central: Captains $0.20, the Emperor $0.21, the Skeptic $0.06 (O2c,
  $0.47); the council of war $0.23, post-mortems $0.08, questions $0.24
  (O2d, $0.55). With B's probes that is $1.50, army_costs.py's own total,
  so the probes are counted once;
- a busy day, on the spec's own rungs: O2c $0.66 (8 Captain wakes on r0 at
  their cap × $0.034, the Emperor $0.208, 6 co-signs × $0.030); O2d $1.65
  to $2.15 (4 councils of war × $0.116, 4 r0 post-mortems × $0.038, 10
  questions × $0.10 to $0.15: on r1 after the PASS, with no cache read,
  D.15); the probes $0.48. About $3.0 in all.

The row is map_ai's routed day (table B, without its probes) plus that
total:

| 10 positions | Calm | Eventful | Stormy |
|---|---:|---:|---:|
| central | 5.88 + 1.50 = **7.38** | 8.47 + 1.50 = **9.97** | 11.48 + 1.50 = **12.98** |
| with busy callers | about 8.9 | about 11.5 | about 14.5 |

**The wakes' ceiling from the per-Orc caps** (probes and tickets excluded):
real × $2.00 + paper × $0.50. That is $7.00, $12.50 and $25.00 for 5, 10
and 20 positions, before the line. An Orc's cap can be passed only by one
call's excess over its HIGH estimate (A.12).

### 2.5 The proposal

**`ORC_DAILY_BUDGET_USD`, by phase** (§4 Q3). The figures are for 10
positions (5 real, 5 paper) and include the triage (A.13, with R =
min($1.00, 0.2 × C)), the bound and the cold writes (calc/cost_lens_sim.py
and calc/review_o2a_line.py for O2a; calc/cost_lens_checks.py, check 3, for
O2b):

| Phase | Cap | Why | `AI_DAILY_BUDGET_USD` |
|---|---:|---|---:|
| On arrival | **0** | the line is off; no call; nothing held back (spend.py:79-81) | 15 (unchanged) |
| O2a, the first week | **$6.00** | at central output it answers every real-money urgent wake, 100%, 97% and 82% of the real routine wakes (calm, eventful, stormy) and at least 92% of the paper wakes, and spends $4.28, $4.76 and $5.14. At high output it binds: real urgent 91-100%, real routine 65-88%, paper cut first. $5.50 falls short (77% and 75% of real routine on eventful and stormy days); $6.50 answers 91% of real routine on a stormy day | 24 |
| O2b with the router ON | **$10.00** | with A.12's HIGH rule and the ladder fixes of B.9-B.14: every wake answered on a calm central day; on a stormy central day about 35 wakes are answered by code and 94% of the real urgent ones by a model. $12.00 would bring that to 7 and 100% | 28 |
| O2c and O2d callers ON | **$12.00** | the callers add about $1.50 central and $3.0 busy (§2.4 C); calm and eventful days fit; stormy days answer more wakes by code, paper first | 30 |
| After each first week | p90 day + 20% | from the measured week (§2.7) | cap + 18 |

- **Why the total rises:** core = total − Orcs actually spent − $3.00
  (spend.py:157-170). With the total at cap + $3 + 15, the core keeps its
  15 even when the Orcs spend their whole cap.
- **Starvation by the core:** raising the total makes it unlikely, not
  impossible. BaseAgent callers ask the total only, and the daily briefing
  and the Monday plan ask nothing (map_ai §1.3).

**Per-Orc caps** (A.12; OrcSetting, bind at once):

| World | Model wakes a day | Dollars a day (checked with HIGH) | Routine share |
|---|---|---:|---:|
| real money | 12, 14 or 16 (calm, eventful, stormy) | $2.00 | 75% |
| paper and demo | 6 | $0.50 | 75% |

- The counters reset at 00:00 UTC with the line.
- Urgent real-money wakes may pass the count cap, but never the dollars.
- The dollar check counts the Orc's spend, its unbilled holds, and HIGH of
  its call in flight and of this call (A.12). The line keeps the bound.

**The live floor and the reserve** (A.13):
- `ORC_LIVE_FLOOR_USD` stays **$3.00** (spend.py:84). It is O0's, and O2
  does not change it. It is held back from the core line while the Orcs
  line is on, whatever R is inside the line, and it also covers the Orcs'
  money in flight and held (A.18).
- Inside the Orcs line, R = min($1.00, 20% of the cap) is kept for
  real-money urgent wakes in O2. It returns to min($3.00, 40% of the cap)
  when O3 binds (§3).

| Cap | Reserve R | Real non-urgent stops at | Paper urgent at | Paper non-urgent at | Post-mortems and council at | Probes' own allowance (O2b) |
|---:|---:|---:|---:|---:|---:|---:|
| $6 | $1.00 | $5.00 | $3.60 | $2.70 | $1.80 | $0.90 |
| $10 | $1.00 | $9.00 | $6.00 | $4.50 | $3.00 | $1.50 |
| $12 | $1.00 | $11.00 | $7.20 | $5.40 | $3.60 | $1.80 |

- Real-money urgent wakes may use the whole cap, and are exempt from the
  70% deep share (decision D30).
- Fable: a quota of 0 through O2, and the pair cannot run under the $3.00
  floor (B.9; §4 Q12).

### 2.6 When the line is exhausted

1. **A wake whose class ceiling is reached** is answered by code with code
   `triage`. One that the line refuses gets `line`, `deep_share`, or
   `total` when the whole AI budget is spent (spend.py:241-243). One whose
   unbooked money would pass the core's floor gets `inflight` (A.18).
   - A `budget` entry says so in fixed words (A.5). Dollars appear in the
     body and on staff pages only.
   - Nothing retries it: every Orc call is sent with `max_attempts=1`, and
     the next detection makes a new wake.
2. **The cut follows triage order:** the post-mortems and the council of
   war first (30%), then paper non-urgent (45%), then paper urgent (60%),
   then real-money non-urgent (cap − R). Real-money urgent wakes keep the
   reserve.
3. **When even the reserve is spent**, real-money urgent wakes are answered
   by code too. The care holds the position, as it always does in O2.
   Nothing about the position changes.
4. **No Orc changes state for budget reasons.** Code answers are never
   refusals and never silence (A.52).
5. **F6's reference is not updated** (A.9). So the first wake after the
   reset is a full wake, never a false "quiet".
6. **At 00:00 UTC** the line resets, and the per-Orc counters reset lazily
   (A.12). In-flight calls finish and are booked; their reservations count
   until they settle. The holds of calls without a bill expire then
   (A.25).
7. **The total.** When core callers spend the whole total, the Orcs line is
   refused too (spend.py:241-243; code `total`). The words name the total,
   not the Orcs line.
8. **Where it shows:** `orcs status`, /ai-models/'s TODAY cell (spend.py:
   297-325) and /orcs/ for staff show the state of the line and the money
   held. The watchdog's result carries the count of wakes answered by code
   for budget.

### 2.7 What to measure, and when to re-size

Measure these before trusting §2.3 and §2.4 (map_ai §7 gives the read-only
queries):
1. The band mix and the recorded wakes per Orc-day. O1 already writes them
   on every OrcWake.
2. The real token counts: S with `orcs tokens --s`, and the stored blocks.
   Watch the 1.27 factor and the session blocks stored over their cap.
3. The output tokens per rung, p50 and p90, from the first week's AgentTask
   rows, by the `source_ref`'s rung (the answering rung, B.2). Each rung's
   p90 cost replaces HIGH in A.12 (OrcSetting `per_orc_high`).
4. The cache writes per model, per day and per burst, and the start-to-start
   gaps between calls that share a prefix, to choose the TTL: a 5-minute
   entry costs 1.25× instead of 2× when the bursts are more than an hour
   apart. Also the refusal and invalid-answer rate per rung, and the
   cache-read share per model (alert when a model goes a day with zero
   reads).
5. The share of routine wakes F6 makes quiet after A.10.
6. The holds a day (calls without a bill) and the backlog closes, to size
   the floor and the workers.

Then re-size the line from the p90 day + 20%, never from §2.4.

---

## §3 What stays for O3 (paper) and later

**O3 (paper, binding on paper rows only, behind a PIN-gated switch):**
- `position_care.plan(orc=)` and the effective stop (ghost.py:63-64).
- The binding Orc columns, written for paper rows: `stop_level`,
  `stop_why`, `stop_at`, `trail_owner`, `lock_waiver`, `be_swap_floor`.
- Code-armed plan clauses that act by themselves. In O2 a clause is a watch
  (A.32).
- The confirm wake (`kind="confirm"`, floor F1, `orc_confirm`, decision
  D30's confirm exemption). In O2 nothing binds, so nothing needs
  confirming.
- Binding breaches and guard G13 (tribunal.py:7, :47). IdeaFacts' breaches
  and `exit_available` read the shadow record.
- `captain_may_cut` on paper.
- An add that is applied: legs added to the arm and to the row.
- I3's facts as a binding gate. I2-I12 move from would-mode to binding.
- F3 and F4 with a binding action on the table. As coded, F4 equals F3
  (complexity.py:270-273): check it then.
- Seats that grant authority on paper: `OrcSeat.level` written, and the
  earned level becoming effective under the operator's PIN.
- The reserve R back to min($3.00, 0.4 × C) once a decision binds (A.13).
- A real stop that carries a drum's wave (drum_bus.py:219-221, re-marked
  "# O3:", C.17).
- A-CONFIRM listed, with the officer binding (A.36).

**O4a:**
- The commissions reduce and trail under the PIN (notes.py:151-157).
- Stand down, and `/orcs off`, with their writes (surfaces.py:37-40,
  :286-291, :321-323).

**O5:**
- The re-entry window (`STATE_REENTRY`), the re-entry intent, I7
  (lifecycle.py:30-31, :66-77), and R-RECLAIM.

**Later:**
- L4: widen with a cut (W-WIDEN), and reverse (V-REVERSE).
- The Uruk-hai privilege by PIN.
- Fable's quota above 0. Its pair ($3.56) needs the in-flight floor raised
  above it first (B.9).
- P-HOLD listed, with the waiver check computed at the render (A.8).
- A per-type ladder (map_army B13).
- The seat's models (models.py:31-32).
- Continuation odds in PS12 (dossier_position.py:355-356, re-marked
  "# Later:"). No reader exists (backtester/proving/memory.py).
- The Batch API for post-mortems and re-grading (−50%; it refuses
  `fallbacks`).
- IN-slow's 5m breakpoint for twin wakes on one symbol (map_ai §2.2
  item 8).
- Real money binding (after O3's paper evidence, under its own
  PIN-gated switch).

---

## §4 Open questions only the operator can answer

Each has a recommended default. The builder ships the default unless the
operator says otherwise.

0. **The PIN on the minds' switches.** Should turning on any O2 switch take
   the trading PIN at /ops/, as a live-money switch does, with the shell
   refusing?
   - *Default: yes* (N2). No model spends his AI money until he types his
     PIN. Turning a switch OFF never asks.
1. **"All on" and the new switches.** Should the System group's "all on"
   leave `orcs_minds` and every later O2 switch OFF?
   - *Default: yes, all exempt.* One tap never starts AI spend.
2. **O2a's rung.** Should every wake, real money and paper, be answered on
   r0 (Sonnet 5.5 at low effort) until O2b's router is ON?
   - *Default: yes.* One mind, one cache, the cheapest clean evidence.
3. **The Orcs line by phase** (§2.5).
   - *Default:* 0 on arrival; $6.00 for O2a's first week; $10.00 once the
     router is ON ($12.00 if he wants stormy days answered too); $12.00
     with O2c and O2d's callers; then the measured p90 day + 20%.
   - *Default:* raise `AI_DAILY_BUDGET_USD` with it: 24, 28, 30.
4. **Per-Orc caps.**
   - *Default:* real money 12, 14 or 16 model wakes and $2.00 a day; paper
     and demo 6 wakes (O1 displays 12) and $0.50. The dollars are checked
     with each rung's high cost estimate, so an Orc passes its cap by at
     most one call's excess over that estimate.
   - *Default:* routine wakes, the plan's own watches included, may use at
     most 75% of either.
5. **Triage.**
   - *Default for O2:* keep R = min($1.00, 20% of the cap) for real-money
     urgent wakes. Real non-urgent wakes stop at the rest; paper urgent at
     60%; paper non-urgent at 45%; post-mortems and the council of war at
     30%; probes on their own 15%.
   - R returns to min($3.00, 40% of the cap) when O3 binds. The core's
     $3.00 floor is unchanged.
6. **Demo, and rows that state no world.**
   - *Default:* both are budgeted as paper and never draw on the real-money
     reserve.
7. **The day clock.**
   - *Default:* the per-Orc counters reset at 00:00 UTC with the line. The
     day class that picks 12, 14 or 16 is the trading day's (17:00 New
     York).
8. **The care, in shadow.** What stands an Orc aside?
   - *Default:* one wake not answered in 30 minutes while the worker is
     silent, two failed calls in a row, or two refused answers in a row. A
     wake that only waited behind a busy worker closes as a backlog and
     stands nothing aside. It comes back only by citing the takeover.
   - The care itself never changes.
9. **Adds in would-mode.** Should an Orc be able to propose an add in O2a,
   judged by the officer as if binding, never applied?
   - *Default: yes.*
10. **The metronome.** Should W11 count from the last recorded wake, at the
    army type's cadence (Line 4 h, Mercenaries 1 h, Olog-hai 24 h)?
    - *Default: yes.* About a third fewer routine wakes.
11. **The router.** Should it ship in shadow, behind `orcs_router` OFF,
    while r0 answers?
    - *Default: yes.*
12. **Fable (r5).**
    - *Default:* 0 a day through O2; its pair cannot run under the $3.00
      in-flight floor anyway (B.9). Afterwards, at most 1 a day for the
      whole fleet, real money only, with its r4 twin, behind
      `orcs_frontier`, once the floor is raised above the pair.
13. **Probes.**
    - *Default:* paper and demo only; h0 on calm and eventful days; at most
      6 boundary probes a day; their own allowance of 15% of the line.
14. **Temperaments.**
    - *Default:* a seeded, balanced draw among six temperaments and a
      control, fixed for life, so the grade measures the temperament, not
      the situation.
15. **Captains and the Emperor.**
    - *Default:* one Captain per class, on r0, at most 4 wakes a day, its
      orders graded and never applied.
    - *Default:* one Emperor's order per user a day, on r3 (r2 until the
      smoke's PASS), with no fallback. One persona, named apart from the
      council's chair.
16. **The Skeptic.**
    - *Default:* only on a Captain's cut and on an add the officer would
      allow, at most 6 a day, never a gate.
17. **Seats.**
    - *Default:* only ideas with at least one model wake count. Levels are
      earned in shadow by full blocks of 20. No power in O2.
18. **Questions.**
    - *Default:* 10 a day per user; r1 on real money once the smoke's PASS
      is recorded, r0 before it and on paper; never on the reserve; on
      Telegram and on the Orc's page.
19. **The Book's bench line.**
    - *Default:* it moves to `MILESTONES` at the PR's merge, with all four
      commits, not at O2a.
20. **The smoke first.** Should the operator run `claude_smoke --yes`
    (about $1) and record its one verdict per family before turning
    `orcs_minds` ON?
    - *Default: yes.* Without a recorded PASS, O2a sends the rung's effort
      at the top level, and O2b runs each model at one effort. A FAIL on the
      effort check alone means the effort-only message governs nothing, so
      neither use is made.
21. **Drum wakes.** Should the drums wake the Orcs behind a switch of their
    own, with at most 2 urgent drum wakes per Orc a day and drum wakes held
    to 25% of the line?
    - *Default: yes* (C.14, C.16). The existing drums switch keeps
      journaling only.

---

## Appendix A: O1 traps and the rule that handles each (map_wakes §6)

| Trap | Rule | Trap | Rule |
|---|---|---|---|
| 1 a timestamped dedupe_key | A.11 (the "orc<pk>:pending" key) | 17 the no-pending pin | A.3 |
| 2 `finished_at` = as of | A.24 | 18 no `orcs` worker | A.17 |
| 3 the answered_hash proxy | A.9 | 19 the gate's health keys | A.17 |
| 4 the render for Sonnet only | r0 is Sonnet; B.4 | 20 W11 ignores the type | A.50 |
| 5 `RUNG_NONE` hard-coded | A.62 | 21 F4 = F3 | B.1 KEEP; §3 |
| 6 `BaseAgent.run` asks the total only | A.22 | 22 stakes without wound or level | D.4 |
| 7 no reservation | A.18, A.20 | 23 PS4's loss 0 | A.47 |
| 8 the default estimate | A.20 | 24 PS1 "L0 shadow" | stays true (A.29) |
| 9 deep share by tier | A.20, B.13 | 25 `continuation_odds`, `wake.request` | §3; `request` dropped (1.1.3) |
| 10 the floor is the core's | A.13 | 26 model id literals | A.22, B.3 |
| 11 UTC against the trading day | A.12 | 27 the 32,000 default | A.21 |
| 12 caps on the (user, class) row | A.12 | 28 `line=` steers the re-run only | A.27 |
| 13 no bar, gap or level_reached facts | A.46 | 29 the tick's hook | N1.1 |
| 14 the event title in the body | A.35, A.46 | 30 the dossier as of detection | A.42 |
| 15 the O1c pins | A.22 | 31 `context_for` reads stored states | A.8 (`vctx`) |
| 16 the models test | 1.1.2 | | |

## Appendix B: the promises, by commit (map_pitfalls B.7)

| Commit | Keeps | Updates or delivers |
|---|---|---|
| O2a | K-B1, B3-B5, B7, B8, B10; K-W1, W2, W5; K-R2-R5, R7, R10-R13, R15, R16, R18, R19, R21-R24, R27-R29, R33, R35, R36; K-P1, P3, P7, P12, P16-P18, P23; K-A2, A3; K-C1, C5 | U-B2, U-W3, U-R1, R6, R9, R14, R17 (AI cost), R20, R25, R30 (first half), R31, R32, R34, R37; U-P2, P4-P6, P8-P11, P13-P15, P20-P22; U-A1, A5; U-C3, C4 (A.62) |
| O2b | K-W2, K-R8, K/D-A4 | U-R6 (routing in shadow), U-R31 (the rung), U-P15 (B.6, B.7, B.16) |
| O2c | K-R26 | D-C2 and D-R26: drum wakes (C.14-C.19) |
| O2d | K-R28 (Q&A through the dispatcher), K-P3 | U-R30 and U-P19 (Q&A), U-R17 and U-R37, U-P9 (seats) (D.1-D.18) |
| The landing (in O2d) | K-B9, K-W4 | D-B6 (D.19) |

## Files

- This spec:
  `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/orcs2/o2_spec.md`
- The spec as it stood before the review:
  `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/orcs2/o2_spec_before_review.md`
- The plan for the operator, in French:
  `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/orcs2/plan_fr.md`
- The arithmetic of §2:
  `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/orcs2/calc/o2_spec_costs.py`,
  and the review's: `calc/review_bounds.py`, `calc/review_table_a.py`,
  `calc/review_o2a_line.py`, `calc/cost_lens_sim.py`,
  `calc/cost_lens_checks.py`, `calc/cost_lens_routed_fix.py` in the same
  folder (run each with `/home/user/Sauron_Vision/venv/bin/python -I <path>`)
- The maps:
  - `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/orcs2/map_wakes.md`
  - `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/orcs2/map_ai.md`
  - `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/orcs2/map_army.md`
  - `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/orcs2/map_pitfalls.md`
- The recovered notes:
  `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/orcs_o2_recovered.txt`

---

## §5 Review log

The review of 2026-11-01 had three lenses: shadow (17 findings), cost (14)
and completeness (29). Every blocking and important finding is applied, and
every minor one that is right. Below, one line each: what was not applied as
written, and why; and the one rule added beyond the review.

| # | Finding | Decision, and why |
|---|---|---|
| 1 | none (added) | The PIN on every O2 switch (N2, §4 Q0): the operator's plan promises he turns the minds on himself with his PIN, and AI spend is his money; it reuses switch_pin.py's one rule and leaves `LIVE_MONEY_SWITCHES` alone. |
| 2 | shadow, locks, fix 4 (the watchdogs "on the orcs queue") | On `slow` instead: worker-orc's two slots can both be held by calls of up to `WALL_S` (3,460 s on r4), which would starve the watchdog. |
| 3 | shadow, the reservation bound, options (i) and (ii) | (ii) taken, as the cost lens's single provider keyword `max_attempts=1`. |
| 4 | shadow, the reservation bound, the heartbeat release | Not built: a cut or orphaned call may still bill (map_ai §2.1 item 6), so a hold lasts until a settle or 00:00 UTC, the cost lens's rule. |
| 5 | shadow, test (a), "replace the name lists" | The FORBIDDEN names stay as a floor beside the structural rule, which binds O2 code only: O1's ghost imports `engine.trailing` and `lock_adjuster` by design (ghost.py:680-690). |
| 6 | shadow, A.45b's scope | O2 code only: O1 code such as render_wake's in-memory copy of the care (wake.py:706-711) is outside it, and T12b proves the tick at run time. |
| 7 | shadow and completeness, test (d), "a name bound to an Orc" | Approximated by `orc`, `locked` and names assigned from `Orc.objects`, in O2 code only; birth._create's O1 `commission=` keyword is pinned by the hash test (h). |
| 8 | shadow (one call in flight) and completeness (the dollar cap) | The cost lens's HIGH rule instead: "+ this bound" bars paper r3, r4 and r5, and "no bound" lets the day's last call pass the cap by its whole cost; the completeness lens's T3 case gives way to the cost lens's. |
| 9 | completeness, one call in flight, re-render "as of the settle" | The waiting wake keeps its own as-of and reads only the Orc's journal up to the settle: a moved as-of would judge the detection's price stale and push the answer under F5. |
| 10 | completeness, lock_waive's two options | P-HOLD stays unlisted in O2, and a lock_waive names candidate "none". |
| 11 | shadow, the frontier quota, the zeroing migration | No data migration: the router never reads the column, its rows are per day, and weather writes the setting's value from O2b. |
| 12 | completeness, `orcs_drums` into `BULK_ENABLE_EXEMPT` | Not applied: the spend moved behind the new exempt, PIN-gated `orcs_drum_wakes`; `orcs_drums` only journals, so test_orc_beats_o1c.py:89-101 stays. |
| 13 | cost, tickets, the post-mortem's and council's class | 0.30 × C, as the shadow and completeness lenses say, rather than the paper non-urgent ceiling: "last" must sit below paper non-urgent's 0.45 × C. |
| 14 | cost, the ladder, fix 3, "real-money wakes on r2-r4" | Read as r2-r5: r5's $2.69 bound counts its fallback. |
| 15 | cost, the in-flight floor against the r5 pair | The `inflight` rule refuses the $3.56 pair, so B.9 states that r5 cannot run in O2 rather than exempting it; Fable is at 0 through O2 anyway. |
| 16 | cost, questions, "$0.13 until the PASS" and the "warm" prices | Before the PASS a real-money question answers on r0 (about $0.07), and $0.10-0.15 is r1 after it; a question's own schema reads none of the wakes' cache, so no warm price applies. |
| 17 | cost, triage, the O2b line | $10.00 kept, as the lens allows once the HIGH rule and the ladder fixes are in; $12.00 is named as the stormy-day choice (§4 Q3). |
| 18 | cost, the cache upkeep, table A | The lens recomputed only the 10-position row; the 5- and 20-position rows carry the same $0.47 until §2.7 measures them. |
| 19 | cost, the busy day's O2d row | $1.65-2.15 rather than $1.72-2.02, with the questions priced uncached as in line 16. |
| 20 | shadow, K-B10, "passes plain_words.scrub unchanged" | A match by value with `plain_words.money_marks` instead: the generic filter flags the dossier's bar prices, and `scrub` cuts at `LINE_MAX`. |
| 21 | shadow, the gateway-only string ban | Docstrings are exempt: tribunal.py:2 and sources.py:585 name ai_agents in prose and would make the test red on the base. |
| 22 | completeness, the callers' table | The doctrine caps (2,000 to 6,000 characters) and `TICKET_MAX_TOKENS` are this revision's numbers, to be measured with `orcs tokens` like S. |
| 23 | shadow, locks, fix 3 (the real-money lock list) | Widened, not narrowed: `thesis.complete_provenance` on the entry path (bot_program/asset_engine/runner.py:404) also takes its Orc lock under the 200 ms budget. |
