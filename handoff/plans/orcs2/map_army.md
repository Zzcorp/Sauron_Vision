# MAP 3: honor to surfaces, what O2b, O2c and O2d must add

Source: the read-only checkout of main `9d74a19` (2026-11-01) at
`/home/user/Sauron_Vision/.claude/worktrees/orcsread`. Every `file:line` below
is in that tree. A bare file name is under `bot_program/orcs/`.

Companion maps, same folder:
- `map_wakes.md`: O2a (the dispatch, the prompt, the validator, OrcIntent, the
  plan). Not repeated here; cited where O2b-O2d stand on it.
- `map_ai.md`: the provider, the prices, the per-call and per-day cost of O2a's
  wakes, and the caps it proposes.
- `map_pitfalls.md`: the recovered O2a review findings, as requirements.

Where a recovered O2a finding has a twin in O2b-O2d, it is flagged
**[P: the finding, short]**.

Legend:
- **HAS**: the code already does it.
- **ADD**: the commit must add it.
- **DECIDE**: the code leaves a choice open. A recommendation follows.
- **KEEP**: an O1 guarantee the commit must not break.
- **inferred**: a reading of the lost master spec from code comments, not a fact
  in the code.

Items are numbered X (every commit), B (O2b), C (O2c) and D (O2d), so the spec
can cite them.

---

## 0. The answer on one page

### O2b, routing in shadow (a router, its probes, its grades; no new power)

1. **A pure router** (new `router.py`). It maps the band the render already
   computes (wake.py:731-741) to a rung NAME of the ladder (catalog.py:505-519),
   by money world, with the floors F1-F4 (complexity.py:256-274), the Fable gate
   and the frontier quota (weather.py:33; models.py:342).
   - Only rung names live in the package. The gateway resolves the model id from
     `ORC_LADDER_V1`.
   - Pins: tests/test_model_catalog.py:455-498 forbids a model id literal outside
     the catalog; tests/orcs/test_orc_switch_off.py:427-456 forbids `ai_agents`
     anywhere in the package.
2. **Routing ships in shadow** (DECIDE, recommended). A switch `orcs_router`,
   OFF on arrival.
   - OFF: O2a's fixed rung answers, and the router's choice is only recorded on
     the wake.
   - ON: the routed rung answers.
3. **The dossier is rendered for the routed family.** dossier.py:360 and :368
   take the model; wake.py:728 passes none today.
4. **The day's caps bind.** Today they are display only (weather.py:6-9, :29-42;
   models.py:341-343).
5. **Probes, in shadow.**
   - h0 beside paper wakes: "a paper probe only; never decides"
     (catalog.py:506-507).
   - The adjacent rung on wakes near a band boundary (constants.py:244-247).
   - r4 as Fable's blind twin (catalog.py:516-519).
   - A probe never becomes a plan, an intent, a note or a line of the Orc.
6. **OrcTierGrade** (reserved: tests/orcs/test_orc_models.py:18-20) grades each
   probe pair. "Two completed probe blocks per boundary" is the validation gate
   (catalog.py:500-504).
7. **The card**: the rung in words, `escalated` and `late` (wake.py:765-771).
   Today notes.py:431-442 overwrites `rung_t`.
8. **The ladder seen** on /ai-models/ (ai_models.html:151-175;
   views_ai_models.py:89-104, :232-235) and on /orcs/seats/.

### O2c, honor, temperaments, Captains, the Emperor and the drums, all in shadow

1. **Honor.** Code-of-honor audits run over the shadow record and write `breach`
   entries in mode shadow. The binding inputs of the council of war's class keep
   their O1 values (grading.py:149-152; tribunal.py:22-23), so no idea is FAULT
   in O2.
2. **Temperaments.**
   - A pure table of lead voices and their lane texts, copied from
     ai_agents/agents/council.py:260-486 and trade_debate.py:150-189 and pinned
     equal by a test.
   - Assigned at birth and fixed for life.
   - PS9 filled (dossier_position.py:299-302). OrcTemperamentGrade.
3. **Captains.**
   - One per (user, class), with its own wakes on the Orcs' line: agent
     `captain` or `captain_<class>`, source_ref `Captain:<class>:Wake:<n>`
     (spend.py:93-97; tests/test_ai_spend_lines.py:183-197).
   - CaptainOrder in shadow, PS11 (dossier_position.py:304), the class band's
     slot (notes.py:749-771; horde.py:422-440, :1665).
   - `captain_may_cut` stays False (models.py:67).
4. **The Emperor.** One daily order per user, written into the MK-E block
   (dossier_market.py:258-268) under a NEW key, plus theme orders in PS11 and a
   journal kind `emperor` with a new author.
5. **The drums.**
   - W12 from `drum_bus.route` (drum_bus.py:666-667), through `wake._queue`
     (wake.py:843-857), urgent per `_urgent_for` (drum_bus.py:582-597), gated by
     `orcs_drums` (drum_bus.py:84-93; platform_control.py:326-331).
   - OrcWave; the settle (constants.py:255, read by nothing today) and a
     breaker; the wave stamp on shadow intents.

### O2d, seats, ranks, the council of war, Q&A, the post-mortem and the surfaces

1. **Seats** computed in shadow (grading.py:28-30):
   - blocks of SEAT_WINDOW = 20 (constants.py:140, read by nothing today);
   - the record in OrcSeat.stats; OrcGrade.seat_block (models.py:272);
   - never OrcSeat.level.
2. **Ranks**: the earned level in shadow with its qualifiers (ranks.py:5-7), the
   White Hand mark (inferred: the Uruk bar, army.py:125-137), the slot's lineage
   keys (notes.py:471-485).
3. **The post-mortem**: agent `orc_postmortem` (views_ai_models.py:100), kind
   `postmortem` (constants.py:26), after the grade.
4. **The council of war's words**: agent `orc_tribunal`
   (views_ai_models.py:101); OrcBattle, OrcLesson, OrcWeapon; scars and heritage;
   PS10 (dossier_position.py:303).
5. **Q&A**: "/orc N <question>" (surfaces.py:16-18, :35-36, :292-294), agent
   `orc_question` (views_ai_models.py:99), rung r1 on real money
   (catalog.py:510-511). Answered by a queued task, never inside the three
   pinned modules (tests/orcs/test_orc_source_pins_o1d.py:18-24).
6. **The surfaces**: every O1 sentence that says "no model", "no plan", "no step"
   or "not built" turns truthful, and every key O1 reserved is filled. §5.6 lists
   31 surfaces with their file:line.

### Every commit (§2)

- One model gateway.
- The Orcs' line asked before every call.
- A switch per new caller, OFF on arrival.
- Every model-written text through the money filter and the fence before a
  prompt or a surface.
- The O2 seam pins updated on purpose.
- Fake models only.

---

## 1. What O2a leaves behind

`map_wakes.md` specifies these; O2b-O2d assume they exist:

- **The pipeline:** the dispatch, the `orcs` queue and its worker
  (config/celery.py:96, :100-101), the claim, and the watchdogs for a stalled
  queue and a silent worker.
- **ONE module that calls the provider, "the gateway".** It is the only file of
  the Orc code that may import ai_agents. Today the whole package is pinned
  against it (tests/orcs/test_orc_switch_off.py:427-456).
- **The minds switch**, OFF on arrival.
- **The budget:** `can_spend(line="orcs")` before each call, and a reservation
  for the calls in flight (map_ai §0 items 2-3).
- **The per-Orc day caps** (Orc.llm_wakes_today, spend_today_usd:
  models.py:103-109).
- **The validator and the strengthened money filter** (plain.py:36-42 today)
  [P: the money filter misses common forms].
- **OrcIntent** in mode shadow or refused (constants.py:388-389), and the O arm
  carrying the Orc's shadow intents (ghost.py:948-1063). OrcActionGrade, if O2a
  ships it.
- **The plan:** the columns (models.py:83-85), PS3 and PS5.

When an O2b-O2d item needs one of these and O2a did not ship it, the item says
so.

---

## 2. Rules for every O2b-O2d model caller

**X1. One gateway.** Every new caller goes through O2a's gateway: the probe, the
twin, the Captain, the Emperor, the post-mortem, the council of war, the answer
and the Skeptic's co-sign.
- The gateway asks the line, reserves, builds the request, calls
  `ClaudeProvider.complete()` (map_ai §0 item 1), books, and releases.
- The source pins (tests/orcs/test_orc_switch_off.py:427-456;
  tests/orcs/test_orc_source_pins_o1d.py:18-24) widen to that one file, never to
  the package.

**X2. Agent names and source_refs.**
- HAS: the Orcs' line counts the agents `orc`, `captain`, `orc_*` and
  `captain_*`, and the source_refs starting with `Orc:` or `Captain:`
  (spend.py:93-97, :130-140).
- HAS: tests/test_ai_spend_lines.py:183-197 already books `orc_confirm`,
  `orc_question`, `orc_postmortem`, `captain`, `captain_fx`, `Orc:7:Add:x` and
  `Captain:fx:Wake:2`.
- HAS: /ai-models/ lists eight names, "spec §7.1 and §7.5.8, the union of both
  lists" (views_ai_models.py:89-104): orc, orc_confirm, orc_question,
  orc_postmortem, orc_tribunal ("The council of war"), orc_emperor ("The
  Emperor"), orc_skeptic ("The Skeptic's co-sign"), captain ("one per asset
  class").
- ADD: each caller uses one of these names.
- DECIDE the probe's name. Recommended: agent `orc`, source_ref
  `Orc:<id>:Wake:<wake>:probe:<rung>`.

**X3. The line, a reservation and day caps for every caller.**
[P: routine wakes ignore the day's totals] [P: triage inverted]
[P: `orcs record --yes` never asks can_spend]
- Each caller has its own day cap and its place in the triage order (§9 proposes
  both).
- A call the line refuses is journaled with a code (kind `budget`,
  constants.py:26) and retried by its own beat, never in a tight loop.

**X4. A switch per new caller, OFF on arrival.**
- HAS: the Orc switches live in core/platform_control.py:320-339 (orcs,
  orcs_drums, orcs_tape), System group.
- HAS: `orcs` is not exempt from "all on" (platform_control.py:320-322;
  switches.py:1-3).
- DECIDE: the new switches spend AI money. Recommended: add each to
  BULK_ENABLE_EXEMPT (platform_control.py:126-128), so one tap never starts the
  Captains, the Emperor and the probes together.
- None is a live-money switch (LIVE_MONEY_SWITCHES, platform_control.py:97-110).
  Nothing in O2 moves money, so none takes the PIN. The PIN arrives with the
  first binding power (O3/O4a).

**X5. Every text a model writes.** This covers a probe's note, a Captain's
order, the Emperor's order, a post-mortem, the council's words, a lesson and an
answer. Before it is stored on a surface or re-enters a prompt:
- it passes O2a's strengthened money filter [P: the money filter];
- it is quarantined and sanitized (fence.py:62-94);
- it enters a prompt only as a view (`fence.view`, fence.py:104-108), with a cap
  in FENCE_CAPS. Today FENCE_CAPS has headline, calendar_title, mind, reviewer,
  lesson 200 and note 140 (constants.py:225-226). ADD caps for temperament,
  captain, emperor, postmortem, battle and answer.

On the surfaces, only the operator's thesis is treated as a voice today
(horde.py:448-450: `ORC_VOICE_AUTHORS = ("operator",)`,
`ORC_VOICE_KINDS = ("thesis",)`; notes._plain_voice, notes.py:555-578). ADD the
authors orc, captain and emperor and their kinds there. Their lines are withheld
whole when they may name an amount.

**X6. No model id and no order path.** KEEP the three pins for every new module:
- no model id literal outside the catalog
  (tests/test_model_catalog.py:455-498);
- the ladder pinned exactly (tests/test_model_catalog.py:434-452);
- no order path and no stop mover in the package
  (tests/orcs/test_orc_switch_off.py:429-431;
  tests/orcs/test_orc_source_pins_o1b.py:15-22).

**X7. The slot carries no money and no model key.** KEEP: "no cost, token,
model, R-money or spend key at any depth" (notes.py:24-26). Pinned by
tests/orcs/test_orc_notes.py:37-39 (MONEY_KEYS includes model_used and
cost_usd) and tests/test_the_horde.py:391-432. Rung words are fine; model ids
and dollars are not.

**X8. No Orc verb, and every Orc sentence reserved.**
- Pins: tests/test_the_horde.py:918-1006; tests/orcs/test_orc_notes.py:40-42
  (VERB, BY).
- An intent or an order is said as proposed, in shadow ("proposed in shadow:
  tighten to S4h-3"), never "the Orc tightened".
- Each new sentence that names an Orc or a Captain goes into
  `notes.RESERVED_SENTENCES` or `RESERVED_PATTERNS` (notes.py:781-796), or into
  `horde.RESERVED_ORC_SENTENCES` (horde.py:291-299).

**X9. The O2 seam pins.**
- tests/orcs/test_orc_source_pins_o1c.py:69-83 asserts a "# O2:" marker in
  wake, integrity, dossier_market, dossier_position, drum_bus and fence, and no
  `status="pending"` in wake.py.
- The commit that fills a seam replaces its marker and updates that pin in the
  same commit:
  - O2c fills dossier_market's and drum_bus's;
  - O2c and O2d fill dossier_position's.

**X10. Allowed values live in constants.**
- HAS: JOURNAL_KINDS (constants.py:22-28, :379) already holds captain,
  question, answer, postmortem, breach, temperament, rank, heritage, scar and
  emperor.
- HAS: AUTHORS (constants.py:30-31) holds code, orc, care, captain, operator,
  morgul and reconcile. No Emperor.
- ADD an author for the Emperor's entries (DECIDE: "emperor").
- journal.append checks neither tuple (journal.py:53-56), so a test must.

**X11. The reserved tables ship in the commit that writes them.**
- models.py:7-9 says so.
- tests/orcs/test_orc_models.py:14-20 and :57-64 assert that the package defines
  exactly the O1 tables, so each commit moves its tables from O2_TABLES into the
  defined set.
- The newest migration in 9d74a19 is 0046
  (bot_program/migrations/0046_etoro_pnl_frozen_balance.py). origin/main 49b6b57
  already holds 0047 and 0048 (the shorts). Each O2 migration follows whatever is
  newest at build time.

**X12. Tests.**
- Fake providers only.
- The zero-call proof must not be swallowed by an `except Exception` in the code
  under test: record the calls in a list and assert it is empty, and block the
  network at the socket for the class [P: the zero-call proof is weaker than it
  looks].
- No vacuous assertion [P].
- Every caller runs end to end on a real-money, a demo, a paper and a manual row
  [P: no end-to-end test runs a real-money or manual row].

**X13. Words.**
- English only.
- R, ATR, and prices through format_price (notes.py:253-256).
- No account figure.
- AI spend in dollars only on staff pages (orcs_list.html:84-90).

---

## 3. O2b: routing in shadow

### 3.1 HAS

**The band of each wake.**
- The score: complexity.py:223-227.
- The stakes: complexity.py:230-233, called with real and hand only
  (wake.py:731).
- The floors F1-F4: complexity.py:256-274. The render calls them with
  `binding_on_table=False` (wake.py:735-737).
- Hysteresis and the urgent hold: complexity.py:287-308; constants.py:244-248;
  wake.py:738-741. The hold is set at wake.py:678-680.
- Stored on OrcWake.score, band, day_class and components (models.py:174-178).

**The wake kinds.**
- O1 writes birth, routine and material (wake.py:628-634).
- `confirm` is named by F1 (complexity.py:266-267), by `orc_confirm`
  (views_ai_models.py:98) and by D30 (spend.py:36-37, :216-218), and is never
  written.

**The ladder, display only** (catalog.py:500-519):

| Rung | Model and effort | Note in the catalog |
|---|---|---|
| h0 | Haiku low | a paper probe only; never decides |
| r0 | Sonnet low | routine |
| r1 | Sonnet high | paper material; real money only for questions |
| r2 | Opus medium | real-money material |
| r3 | Opus high | complex |
| r4 | Opus xhigh | extreme when the Fable gate fails; Fable's blind twin |
| r5 | Fable max | extreme, gate passes; real money only, under a quota |

- "The router (O2) reads its own versioned copy and never the tier resolver ...
  until each band boundary has two completed probe blocks it is an unvalidated
  prior" (catalog.py:500-504).
- Pinned by tests/test_model_catalog.py:434-452.

**The table's version.** ROUTING_VERSION "table-v1", display only
(constants.py:358-359), stored on OrcDayBaseline.routing_version (models.py:343;
weather.py:194).

**The day's caps, display only** (weather.py:29-42):
- model wakes a day: real money 12, 14 or 16 by the day's weather; paper 12;
- the frontier quota per (user, class): 1, 2 or 4;
- probes off on a stormy day;
- "the dollar caps arrive with the router, O2" (weather.py:6-9);
- stored on OrcDayBaseline.caps and frontier_quota (models.py:341-342).

**The families.**
- MK is built for every family: tasks.py:163-170 at the day roll, and likewise
  at the session close and the hourly read.
- The token factors: constants.py:286-294.
- The render takes the model (dossier.py:360, :368). wake.py:728 passes none, so
  every O1 dossier is rendered for Sonnet.

**The seat's models.** OrcSeat.model_routine and model_decisive
(models.py:31-32), never written.

**The card.**
- intellect.rung_t is RUNG_O1 "no model (O1: code only)", with escalated False
  and late False (wake.py:81, :765-771).
- notes._intellect ignores all three and prints RUNG_NONE "No model (code only)"
  (notes.py:184, :431-442).
- The Horde paints "Complexity: {score} · {rung}" (the_horde.html:223;
  sv-horde.js:1689-1691), and so does the Orc page (orc_detail.html:20).

**The epoch rule.** If the smoke's effort check fails, "the Orcs' router must
change model and effort per epoch, never per wake" (claude_smoke.py:26-29;
RUNBOOK.md:1343-1348). The smoke prints its verdict and stores nothing
(claude_smoke.py:599-607).

**The army type's ladder.** "Its cadence, dossier focus, model ladder and mandate
parameters act from O2 (shadow)" (army.py:11-12). No ladder parameter exists on
ArmyType (army.py:35-61).

**No consequence lowers a tier.** "Nothing here reads a lineage's standing, a
fault mark, a probationary period or the operator's privileges (§7.5.1): no
consequence lowers the tier of a live decision" (complexity.py:23-25).

### 3.2 ADD

**B1. The router, pure** (new `router.py`).
- In: the band after the floors, the money world (constants.py:45-46: live,
  demo, paper), the kind, the day class, the frontier quota left, the Fable gate
  (B9) and the effort mode (B10).
- Out: {rung, why[], escalated, probes[], twin, routing_version}. Rung names
  only.
- Table v1, read from the catalog's notes (inferred where the notes are terse):

  | Band | Rung |
  |---|---|
  | routine | r0 |
  | material | r1 on paper and demo; r2 on real money (catalog.py:510-513) |
  | complex | r3 |
  | extreme | r5 when the gate passes, else r4 (catalog.py:514-519) |
  | a question (O2d) | r1 on real money (catalog.py:510-511); DECIDE paper (recommended r0) |

- h0 is never routed (catalog.py:506-507).
- DECIDE demo. Recommended: demo routes as paper. A demo seat is never the
  real-money seat (constants.py:39-43), and its stakes term is already 0
  (complexity.py:230-233 with real=False).
- Confirm wakes get F1's floor (complexity.py:266-267) only if O2a runs them
  (map_wakes §3.2).

**B2. Routing ships in shadow** (DECIDE; recommended). A new switch
`orcs_router`, OFF on arrival.
- OFF: O2a's own rule answers every wake. The router's choice is written beside
  it, on OrcWake.components["route"] = {rung, why, version}, at no cost.
- ON: the routed rung answers.
- The probes have their own switch (B5).
- This is the literal "routing in shadow": the new power (choosing a dearer
  mind) is measured before it is used.

**B3. The model id at the gateway.**
- The gateway reads (model id, effort) from ORC_LADDER_V1 (catalog.py:505-519)
  by rung name.
- Nothing in the package holds an id (tests/test_model_catalog.py:455-498).
- A later table is ORC_LADDER_V2 beside V1, with a new ROUTING_VERSION. Each wake
  stores the version it was routed on.

**B4. The render for the routed family.**
- Render, or render again, for `family_of(model)` (dossier.py:65-76) whenever it
  differs from the reference "sonnet" (constants.py:296; wake.py:728).
- MK and IN-slow already exist for every family (tasks.py:163-170).
- A Fable render is sized ×1.35 (constants.py:294). When it comes back
  `over_budget` (dossier.py:441), the router falls to r4 with a code (DECIDE;
  recommended).

**B5. Probes, in shadow.** A switch `orcs_probes`, OFF on arrival (DECIDE the
name). Two kinds:
- h0 beside a paper wake, on calm and eventful days only (weather.py:42:
  `"probes": day_class != "stormy"`).
- The adjacent rung beside a paper wake whose score sits within
  BAND_HYSTERESIS (5, constants.py:247) of a band boundary: 30, 55 or 75
  (constants.py:244-246).
- DECIDE: paper only in O2 (recommended: cheap, plentiful, and no real-money
  dossier is sent twice).

A probe:
- is called on the same stored blocks as the routed answer
  (OrcWake.block_hashes, models.py:178), blind to that answer;
- goes through the same validator;
- is journaled on the wake only. Never in the Orc's plan, intents, latest_note,
  card lines or PS5, and on no surface except the staff ladder table;
- is billed on the Orcs' line and triaged last (§9).

**B6. Fable's blind twin.**
- Each r5 call is paired with an r4 call on the same blocks, blind to it
  (catalog.py:516-519).
- The r5 answer is the Orc's; the twin's answer is a probe.
- With r5 at 0 a day (map_ai §6 proposes 0 through O2b), the twin runs only once
  the operator opens the quota.

**B7. OrcTierGrade** (reserved). One row per probe pair. Proposed fields:
- the wake and the Orc;
- the kind (h0, boundary or twin) and the boundary (30, 55, 75 or none);
- the routed rung and the probe rung;
- each answer's action, level id and validator verdict, and their agreement on
  action and level;
- the cost of each call;
- the forward grade of each action when they differ. DECIDE: reuse O2a's forward
  pricing (pricing.py), so both are graded on the same stop logic [P: the shadow
  stop is the raw level, not the menu's stop beyond the crowd];
- the block index.

A block is SEAT_WINDOW (20, constants.py:140) pairs per (boundary, kind, world)
(DECIDE). A boundary is "validated" after two completed blocks
(catalog.py:500-504). The result is shown, and code never applies it in O2.

**B8. The day's caps bind.**
- `caps_for` (weather.py:37-42) drops `display_only` and gains the dollar caps.
  The router reads wakes_per_day and the frontier quota at dispatch.
- DECIDE, with map_ai §6:
  - paper: 6 model wakes a day, not 12;
  - frontier (r5): 0 a day in O2, then at most 1 a day across all classes,
    never per class.
- FRONTIER_PER_DAY is per class today (weather.py:33). The day row's
  frontier_quota (models.py:342) must then count per user.

**B9. The Fable gate** (inferred; DECIDE). All of these must hold:
- real money (VENUE_LIVE);
- the band is extreme;
- frontier quota left today;
- the line's live allowance covers r5's loose bound (map_ai: $2.04 at the cap);
- a frontier switch is ON (DECIDE `orcs_frontier`: OFF on arrival, exempt from
  "all on");
- the render is not over budget.

When the gate fails, the wake goes to r4 and the failing clause is journaled.

**B10. Effort per wake or per epoch.**
- ADD an OrcSetting key (DECIDE: "effort_switch"), default "per_epoch", kept
  until the operator records the smoke's PASS. The smoke prints it
  (claude_smoke.py:599-607) and nothing stores it.
- Per epoch: within one epoch, every call to a model uses one effort, and the
  router picks only among the rungs with that effort.
- DECIDE the epoch. Recommended: the trading session (sessions.py).

**B11. escalated and late.**
- `escalated`: the floor raised the band, or the router asked once more one rung
  up after an invalid answer. At most once per wake, inside the line. DECIDE
  whether O2b asks again at all (map_ai's lever: "re-run at higher effort only
  when the validator fails").
- `late`: the answer landed after its wake went stale (O2a's staleness rule).
- Both go on the card (wake.py:770) and are read by notes._intellect
  (notes.py:431-442).

**B12. The rung on the card.**
- `card.intellect.rung_t` is the rung in words. DECIDE the wording.
  Recommended: "r2 · deep, medium effort". Never an id, never a cost
  (notes.py:24-26).
- notes._intellect (notes.py:441) prints it. RUNG_NONE stays for a reading by
  code.

**B13. The army type's ladder** (army.py:11-12). DECIDE. Recommended: no
per-type rung in O2.
- A type that also changed the model would change two things at once: the job
  and the mind.
- The type's own record stays clean only while the mind is the same
  (army.py:8-9).
- The type's cadence (army.py:43, :91, :98, ignored by W11 at wake.py:307-309)
  is O2a's (map_wakes item 20).

**B14. The seat's models** (models.py:31-32). DECIDE. Recommended: unwritten in
O2, since no rung is validated yet. If written, rung names only.

**B15. O2b's surfaces.**
- /ai-models/, "The Orcs (read-only)" (ai_models.html:151-175).
  - Its sentence "read by the router from O2 ... stays off until O2 ... No Orc
    runs today." (:153-156) is replaced by the live truth.
  - ADD per rung: today's calls (the staff page may also show their spend), the
    probes, and each boundary's validation state.
  - The view passes ORC_LADDER_V1 (views_ai_models.py:232-235). Also update its
    comment (views_ai_models.py:89-95) and RUNBOOK.md:1308-1312.
- /orcs/seats/ (staff): a ladder table from OrcTierGrade (views_orcs.py:300-354;
  orcs_seats.html).
- The Orc page's wakes table (orc_detail.html:104-125) gains Rung and Status. Its
  heading "Wakes detected (recorded only: no model is called)" (:105) changes
  with O2a.

### 3.3 KEEP

- No consequence lowers a tier (complexity.py:23-25). The router reads no seat
  level, scar, probation or privilege.
- The floors only raise (complexity.py:262-265, :306-307). The urgent hold never
  lowers a band (complexity.py:303-305).
- F3 and F4 apply only to a binding action on the table (complexity.py:270-273).
  In O2, `binding_on_table` stays False (wake.py:735).
  - Observation: as coded, F4 adds nothing F3 does not (both raise to
    "material"). Check it against the lost spec.
- Rung names in the package, ids in the catalog.

### 3.4 Pitfalls to design out

- [P: routine wakes ignore the day's totals] Probes and twins count toward the
  line and toward a probe allowance, and never toward the Orc's own wake count
  (DECIDE; recommended).
- [P: triage inverted] Probes go last, after paper routine wakes. They never
  touch the floor kept for live urgent wakes (spend.py:82-84,
  ORC_LIVE_FLOOR_USD).
- [P: `orcs record --yes` accepts any rung, called Fable with a $2 bound and the
  switch OFF] Any shell command that routes or probes:
  - refuses r5 unless the gate passes;
  - asks can_spend on the Orcs' line;
  - refuses while a switch it needs is OFF;
  - is dry without --yes.
  The command's actions today are status, adopt, shadow-audit, actuals and
  dossier (management/commands/orcs.py:51-55).
- [P: the frozen urgent flag is taken before a newer wake absorbs an older
  urgent one] The band and the route are recomputed when a wake absorbs
  another.
- A probe's answer must never reach Orc.latest_note, the card's lines, PS5's
  notes or the next prompt.

### 3.5 Tests (red first, fake provider)

- The table: band × world × day × quota → the rung. h0 is never routed.
- Switch OFF: the router's choice is recorded and O2a's rung is called (the fake
  records the model id it was given). Switch ON: the routed rung is called.
- The family render: a Fable route renders with the 1.35 factor and falls to r4
  when over budget.
- Probes:
  - a paper wake on a calm day at a score of 27 calls h0 and the adjacent rung;
  - the same wake on a stormy day calls neither;
  - a real-money wake calls no probe;
  - the probe's answer appears in no slot key and in no PS block of the next
    wake.
- The twin: r5 never runs without r4; with the quota at 0, neither runs.
- The ladder pins (tests/test_model_catalog.py:434-498) still pass.
- The card: rung_t in words, with no id and no cost
  (tests/orcs/test_orc_notes.py:37-39).

### 3.6 Cost

The arithmetic is in calc/army_costs.py, using map_ai's central outputs:

| Caller | Per call | A day (10 open positions) |
|---|---:|---:|
| h0 probe | $0.0018 | 5 paper Orcs × 6 wakes = $0.05 |
| Boundary probe at r1, paper | $0.080 | 6 probes = $0.48 |
| r4 twin | $0.319 | none while r5 is at 0 a day |

---

## 4. O2c: honor, temperaments, Captains, the Emperor and the drums, in shadow

### 4.1 Honor

**HAS**

- **The council of war's class is set by code** (tribunal.py:1-24, :66-89).
  The inputs O2 owns:
  - `breaches`: "written by the audits or G13 (O2), never refusals"
    (tribunal.py:47-48);
  - `signpost_unacted` (:49-50);
  - `exit_available`: "a discretionary exit sat in allowed_actions (L2+), or a
    clause could have been armed" (:51-53);
  - `refusals`: "counted elsewhere, never a fault" (:54-55);
  - `gave_back` (:56).
- **The grade passes the O1 values**: breaches=0, signpost_unacted=False,
  exit_available=False (grading.py:149-152). Hence "In O1 ... every idea is won
  or honourable" (tribunal.py:22-23).
- **The code of honor is cited by article** (§1.5):
  - article VI: the integrity verdict and F5 (integrity.py:1-2);
  - article IX: the fence (fence.py:1-2);
  - the smoke's synthetic doctrine shows the shape of the others
    (claude_smoke.py:117-140), e.g. "when a critical fact is stale, holding and
    saying so is the honourable answer".
- **G13** is named (tribunal.py:6-7), but Morgul's guards stop at G12
  (morgul.py:19-47).
- **Journal kinds** `breach` and `scar` (constants.py:27).
- **TRIPWIRE_IDEA_R = -1.2** (constants.py:143), read by nothing. It is the same
  -1.2R as Morgul's G12 (morgul.py:45-47).
- **L0's shadow vocabulary already lets an Orc propose** an exit, a trim and a
  lock waiver (integrity.py:32-35).

**ADD**

**C1. A pure audit** (new `honor.py`) over one idea's shadow record: its journal,
intents, refusals, predicates and plan versions.
- Each finding is a `breach` entry, author code, with body {article, mode:
  "shadow", evidence ids}.
- DECIDE the articles checked in O2 (they were in the lost §1.5). The code
  already measures these candidates:
  - a non-hold intent with no T0 fact in its V10 set (constants.py:227-241;
    fence.v10_satisfied, fence.py:169);
  - a plan changed without a newer fact (V10's "plan": newer);
  - a missed expectation never acknowledged (the doctrine line,
    claude_smoke.py:132-134);
  - a signpost left unacted past one decision bar (tribunal.py:7-9).

**C2. The grade records the shadow tally beside the binding one.**
- OrcGrade.tags (models.py:275, always [] today) gains
  "shadow_breach:<article>" (DECIDE the form).
- The grade's journal body carries the shadow verdict: the class the idea would
  get if its shadow breaches bound.
- KEEP: IdeaFacts.breaches stays 0 and exit_available stays False
  (tribunal.py:8-10, :22-23). No idea is FAULT in O2.

**C3. signpost_unacted in shadow.**
- Computed from the predicate facts (predicates.py:350-354), the thesis check's
  exit and the Orc's own "dead", checked against the shadow intents within one
  decision bar (dossier.decision_tf, dossier.py:187-197).
- In O2 it feeds the shadow verdict only.

**C4. G13.** DECIDE. Recommended: not in O2. A guard over binding breaches has
nothing to read until O3. The number stays reserved.

**C5. The tripwire.** DECIDE. Recommended: an O arm that closes past
TRIPWIRE_IDEA_R journals a shadow breach ("the stop did not hold"), and O2d's
seats read it as a block-fault input.

**C6. The refusals.** n_refused (models.py:281) is written by the grade (in
O2a, or here if O2a did not) and never counts as a fault (tribunal.py:54-55).

### 4.2 Temperaments

**HAS**

- **PS9**: "— (the temperament arrives with O2)", described as "the
  temperament's lead voices and lane texts (§4.6)"
  (dossier_position.py:299-302).
- **Reserved**: journal kind `temperament` (constants.py:27); the table
  OrcTemperamentGrade (tests/orcs/test_orc_models.py:18-20); the slot's seam,
  "temperament ... O2's" (notes.py:32-33).
- **The ten voices**: ALL_VOICES (council.py:85-87) and their names
  (:149-156). Each voice's lane is a sentence in its prompt:

  | Voice | Lane sentence |
  |---|---|
  | Opportunist | council.py:260-262 |
  | Striker | council.py:289-290 |
  | Fixer | council.py:310-311 |
  | Gambler | council.py:335-337 |
  | Skeptic | council.py:368-370 |
  | Awakened | council.py:398-400 |
  | Theorist | council.py:423-424 |
  | Emperor | council.py:485-486 |
  | Executioner | trade_debate.py:150 |
  | Champion | trade_debate.py:189 |

- **The council's readers "for the council band, the Orcs"**
  (council.py:2576-2710): session_payload, voice_line, card_payload,
  session_for_trade (:2693), voice_weights (:2701) and record_matrix (:2708).
- **The live weights' readers are pinned to three modules**: any file outside
  tests that names `voice_weight` fails tests/test_council_shadow.py:275-294.
- **The model of a real type**: "A type is real only where the job differs", and
  the type is fixed for life so its record is clean (army.py:3-10).

**ADD**

**C7. A pure table, versioned** (new `temperament.py`).
- Each temperament is one to three lead voices with their lane texts. There is
  also a control temperament with no lead voice.
- The lane texts are COPIED as constants, since the package imports nothing of
  ai_agents (tests/orcs/test_orc_switch_off.py:427-456). A test that imports
  council.py pins them equal to the prompts, as URUK_* are pinned
  (constants.py:96-99).
- DECIDE the set. Recommended: one temperament per voice that can manage a
  single position (Striker, Fixer, Skeptic, Executioner, Champion, Awakened),
  plus the control.
  - The Gambler's "all in" and the Opportunist's "elsewhere" fit no single
    position's management.
  - The Theorist posts to the hypothesis market.

**C8. The assignment, at birth** (birth.py:324-345, beside the army type).
Journaled `temperament`; fixed for life.
- DECIDE the rule. Recommended: a seeded draw among the temperaments and the
  control, balanced per seat. OrcTemperamentGrade then measures the temperament,
  not the situation it was chosen for.
- Alternatives:
  - the voices the council's Emperor followed at entry (council.py:2596-2611;
    only live bot entries have a sitting);
  - by army type.

**C9. PS9 filled.**
- The lead voices' names and lane texts, as a view (fence.view) with a FENCE_CAPS
  cap.
- PS9 sits inside PS, which is never trimmed (TRIM_ORDER, constants.py:304).
  PS must therefore stay inside PS_TAIL_RESERVE (dossier_instrument.py:39-41,
  :214-217). Measure it, and move the reserve if needed.

**C10. OrcTemperamentGrade.**
- Per (temperament, version, venue, class, bar source): the block statistics of
  Δ against the care (tribunal.block_stats, tribunal.py:92-105), over the
  counted grades whose idea had at least one model wake.
- And the difference against the control: the temperaments' analog of "Against
  Line" (views_orcs.py:350; orcs_seats.html:59-65).

**C11. Reading the council.**
- If a temperament or the Emperor reads the council's record, it does so through
  the gateway, or through a reader outside the package that does not name
  `voice_weight`. Otherwise tests/test_council_shadow.py:275-294 must be widened
  on purpose. DECIDE.

### 4.3 Captains

**HAS**

- **The class band's seams.**
  - notes.for_classes runs one query: "No `label` key: no Captain is seated
    before O2. O2: the Captain, its orders, the open waves, the fallen and the
    Emperor's line." (notes.py:749-771).
  - horde._captain_slots (horde.py:422-440) fills group["captain"]
    (horde.py:1665).
  - The JS paints the Captain's label or "No Captain seated yet.", then the day
    (sv-horde.js:1136-1142). It paints "Captains are not built yet. ..." ALWAYS
    (sv-horde.js:1162).
  - The words: the_horde.html:147-148; horde.py:280-283.
- **PS11**: "— (no Captain seated yet)", described as "the Captain's orders and
  the Emperor's theme orders (§4.2, §4.6)" (dossier_position.py:299-304).
- **Reserved**: Orc.captain_may_cut (models.py:67), never read or written. The
  journal kind and author `captain` (constants.py:25, :30). The Orc page draws a
  captain's entry as a note (views_orcs.py:52-54).
- **The line**: agents `captain` and `captain_*`, source_refs `Captain:`
  (spend.py:93-97). "Captain:fx:Wake:2" (tests/test_ai_spend_lines.py:190)
  shows that a Captain has wakes of its own. /ai-models/ lists "captain", "The
  Captain (one per asset class)" (views_ai_models.py:104).
- **What holds a class today**: the book limits, the theme legs and the
  correlation taper (horde.py:281-283). The Horde's "same bet":
  horde.py:1540-1595.
- **The smoke's synthetic order**: "The order binds nothing by itself; the
  Captain binds only on its own basis." (claude_smoke.py:201-202).
- **The tests that pin O1**: tests/test_the_horde.py:918-925 (the reserved
  words), :948-956 (no Captain seated), :958-961 (empty seams);
  tests/orcs/test_orc_notes.py:475-496 (for_classes: one query, no label).

**ADD**

**C12. The Captain table.** One per (user, asset class), since the class band is
per viewer and class (horde.py:1630-1684). DECIDE when it is seated.
Recommended: while its class has a living Orc. It is never deleted; its record
is kept.

**C13. The Captain's wake and call.**
- DECIDE the cadence. Recommended:
  - at its class's first session open of the trading day;
  - on a level_break wave of its class (drum_bus.py:16-19: one wave per (user,
    class, 4h bar));
  - after the Emperor's order;
  - at most N a day (§9).
- Agent `captain` (or `captain_<class>`); source_ref
  `Captain:<class>:Wake:<n>`.
- DECIDE the rung. Recommended: r0, since a Captain reads cards, not dossiers.
- Inputs:
  - its living Orcs' cards: plan, intents, R, the care beside each, army,
    temperament;
  - the class's weather (OrcDayBaseline);
  - the same bets;
  - the book as shares of its limits (sources.book);
  - the Emperor's line.
- KEEP: one user's book only, never another user's (the drums' rule,
  drum_bus.py:34-35).

**C14. CaptainOrder, in shadow.** Proposed fields:
- the Captain;
- the kind. DECIDE the vocabulary. Recommended: hold_fire (no add), tighten, cut
  (names an Orc), theme (a cap on a same bet's legs);
- the scope: the class, or a list of Orc ids;
- the text, filtered and capped;
- issued_at and expires_at;
- mode "shadow";
- the wave or wake that caused it;
- its grade.

Each order is journaled `captain` (author captain) on each Orc it names, as a
view and never as a fact. PS5 lists facts only (dossier_position.py:176-184).

**C15. PS11 filled**: the unexpired orders that name the Orc, and the Emperor's
theme orders, as views.

**C16. The facts hash.** An order changes PS11 but not the facts the quiet-wake
check compares (wake.py:123-138; _snapshot at wake.py:592). DECIDE:
- either an order is a wake reason of its own (cost: one wake per Orc per
  order);
- or the hash gains PS11's version, so the next metronome wake is not quiet
  (recommended).

[P: the quiet-wake facts hash omits the plan version]

**C17. KEEP: captain_may_cut stays False.** A cut is a power (O3 or later). An
order of kind cut is graded, never applied, and never moves the O arm. The O arm
follows the Orc's own intents only.

**C18. Grading an order** (DECIDE). Recommended: each cut and tighten order is
priced forward on the named Orcs' arms with the pricing function (pricing.py),
against what they did, the way an intent is.

**C19. The class band slot.**
- It carries: the label (the Captain's name), the orders in force, the open
  waves (OrcWave), the fallen (the class's dead ideas with their class) and the
  Emperor's line.
- for_classes stays a constant number of queries
  (tests/orcs/test_orc_notes.py:491).
- The JS stops printing CAPTAINS_NOT_BUILT once a Captain is seated
  (sv-horde.js:1162).
- The new sentences are reserved (X8).

### 4.4 The Emperor

**HAS**

- **MK-E, the Emperor's line.**
  - "its own block after the sessions, so MK0 never changes when it lands. O1:
    '— (no order yet today)'" (dossier_market.py:22-23, :54).
  - "# O2: MK-E carries the Emperor's daily order (§4.6), written once it lands"
    (:34), and at :260-261: "(OrcJournal kind 'emperor'); MK0's bytes never
    change for it".
- **mk_e builds the dash block on its first read of the day**, under the key
  `<day>|mk_e` (dossier_market.py:258-268).
  - The key holds no model family and no user (`_key`, :57-61).
  - Its tokens are estimated on the reference family only (dossier.py:110-132).
- **day_hashes appends MK-E after the closed sessions**
  (dossier_market.py:290-308, at :307). MK-E is the last block of the shared MK
  prefix, where the smoke put the 1 h cache breakpoint (claude_smoke.py:14-19;
  map_wakes §2.2 b).
- **dossier.find returns the OLDEST block of a kind and key**
  (dossier.py:135-138: `order_by("built_at", "id").first()`).
- **The journal**: kind `emperor` exists (constants.py:27), but AUTHORS has no
  Emperor (constants.py:30-31). The Orc page would draw an unknown author as a
  fact (AUTHOR_STYLE at views_orcs.py:52-54, read as
  `AUTHOR_STYLE.get(e.author, "fact")` at :225; orc_detail.html:72).
- **The agent**: orc_emperor, "The Emperor" (views_ai_models.py:102).
- **The council has an Emperor of its own**: council_emperor, on the core line
  (council.py:436-438), named "The Emperor" on the council band
  (council_band.py:206).
- **The smoke's synthetic order** is a view, "may be wrong; facts win", with a
  preference and a theme slot ("no theme slot today"): "The order binds nothing
  by itself" (claude_smoke.py:195-202).
- **Two neighbouring dashes nobody claims**: MK0's MK10 "— (not built)" and MK11
  "— (the council has not sat)" (dossier_market.py:151). The council's origin
  "market" is "reserved for council-2, the morning council"
  (council_models.py:33-37). Neither is marked O2 in the code.

**ADD**

**C20. The daily order** (new `emperor.py`).
- One per user per trading day, on the Orcs' line (agent orc_emperor), at a
  fixed time after the roll. DECIDE the time. Recommended: after orc_day_roll
  (tasks.py:145-197; beat at config/celery.py:500-503), once each class's
  weather exists.
- DECIDE the inputs. Candidates:
  - each class's weather;
  - the Captains' orders and their grades;
  - the living Orcs' counts and R, and the fallen;
  - the book as shares of its limits;
  - the people's mood (ai_agents/council_mood.py).
- Never another user's book. Never money.

**C21. MK-E under a NEW key.** There is a trap here. The order is a new block
(its text differs), but `find` keeps returning the dash built earlier under
`<day>|mk_e` (dossier.py:135-138; dossier_market.py:262-265).
- Key the order apart. DECIDE the key; recommended: `<day>|mk_e|<user>|order`.
  day_hashes takes the order when it exists, else the dash.
- If the order reads the user's book, the block is per user. "One copy serves
  every user" (dossier_market.py:29-32) is promised for MK0 and the session
  blocks, not for MK-E. There is one operator today. DECIDE.
- Its text is a view (fence.view, source "emperor", with a FENCE_CAPS cap), after
  the money filter.
- Its tokens are estimated per family. The dash is estimated on the reference
  family only.
- Cost: the order changes the shared prefix once a day, one cache write per
  model (map_ai.md:468 counts it among about seven MK changes a day).

**C22. The theme orders (§4.2, §4.6).** DECIDE the shape. Recommended:
- structured slots per class (press, hold or none, at most one theme) in the
  order's body;
- shown in PS11 and to the Captains;
- graded later;
- never read by sizing, a gate or an order path. The council's law
  (council.py:38-50) holds for the Emperor's order too.

**C23. The journal.**
- One `emperor` entry on each living Orc of the user.
- ADD "emperor" to AUTHORS.
- Draw it as a note in AUTHOR_STYLE.
- DECIDE whether it shows on the card's lines.

**C24. One Emperor or two.** DECIDE, and say the answer on every surface.
Recommended: one Emperor persona with two duties, each graded on its own
record. Where both show, name them apart: "the Emperor's order to the Orcs" and
the council's chair.

### 4.5 The drums, in shadow

**HAS**

- **The plan**: "drum wakes (a delivery adds W12 to the receiver's pending wake,
  urgent per _urgent_for, gated by `orcs_drums`), waves (OrcWave), the breaker
  and the wave stamp on intents and stops; a stop placed from a drum wake
  carries the wave and its hit inherits hop + 1" (drum_bus.py:41-44).
- **The seam in route.** Right after the DR fact is journaled:
  "# O2: a delivery adds W12 ..." (drum_bus.py:666-667).
  - route runs in the census (drum_bus.py:622-687).
  - One delivery per (wave, Orc), within one user's book, never to the origin,
    never at hop 2 or more (drum_bus.py:34-39; drums.py:66-67).
- **_urgent_for**: urgent for a stop_hit on the Orc's own symbol, or when its own
  stop sits within 1 × ATR(1h) of the mark. "called by nothing in O1"
  (drum_bus.py:582-597).
- **drums_on**: "Read by nothing in O1" (drum_bus.py:84-93). The switch's words:
  "from O2, on, a drum also wakes the Orcs it reaches"
  (platform_control.py:326-331).
- **The way in.** wake._queue adds a reason to the Orc's pending wake under its
  lock (wake.py:843-857, :402). The next tick merges seen["wake_pending"]
  (wake.py:359) and records it: at once if urgent, otherwise after
  MIN_WAKE_SPACING_MIN, 15 minutes (constants.py:257; wake.py:386-393).
- **The wake side already reads W12**: the disagreement flag "a drum heard on
  this wake" (wake.py:544-546).
- **The hop seam**: "a stop placed from a drum wake carries its wave; its hit
  inherits the wave and hop + 1 ... In O1 every stop is hop 0"
  (drum_bus.py:219-221).
- **Unread**: DRUM_SETTLE_MIN = 15 (constants.py:255). "fill" is a drum kind with
  no publisher (constants.py:341-342; the docstring at drum_bus.py:7-31 lists
  none).
- **OrcDrum** carries wave_id, hop, reach, routed_at and user
  (models.py:351-380).

**ADD**

**C25. W12.**
- In route, for each delivery, when `orcs_drums` AND the minds switch AND the
  Orcs' line are all on: add a W12 reason through wake._queue, urgent per
  _urgent_for.
- Keyed per (wave, Orc): one W12 per wave.
- [P: the frozen urgent flag] Urgency is read again when a wake absorbs
  another.

**C26. The settle** (DECIDE). A W12 records no earlier than DRUM_SETTLE_MIN after
its wave's first drum. Recommended: the drums that join the wave within
DRUM_JOIN_MIN (constants.py:254) wake the Orc once.

**C27. OrcWave** (reserved). One row per wave. Proposed fields:
- wave_id, user, kind, symbols, origin;
- first_at and last_at, the highest hop;
- drums, reach;
- W12 queued, and W12 that reached a model;
- the line's cost;
- the breaker's state and why;
- the shadow outcome: the reached Orcs' intents from that wave, graded.

**C28. The breaker** (DECIDE the numbers). Recommended:
- at most 6 W12 model wakes per wave;
- at most 12 per user per hour;
- none once the Orcs' line is 60% spent.

When it trips, the deliveries are journaled only, as in O1, and the wave says
why.

[P: a burst-deferred wake held more than 30 minutes is always skipped as stale]
The breaker's deferral must not starve an urgent W12 on the Orc's own stakes.

**C29. The wave stamp.**
- An intent from a drum wake carries the wave_id. OrcIntent is O2a's table; add
  the column here if O2a did not.
- The O arm's shadow stop from that intent carries the wave and its hop.
- KEEP: no real stop carries a wave in O2, since no Orc places one.
- KEEP: a shadow stop being hit never publishes a drum. Drums come from real
  facts only: drum_bus.on_close reads the real exit (drum_bus.py:194-224).

**C30. Words.**
- The switch's description and RUNBOOK.md:1585-1594 change from "In O1 this
  switch changes nothing" to what the switch does.
- The card's drums (notes.py:56-61, :115-119) are unchanged.

### 4.6 O2c's other hooks

- **The Skeptic's co-sign** (orc_skeptic, views_ai_models.py:103). No code says
  where it applies. DECIDE. Recommended: O2c applies it to two things only, both
  in shadow:
  - a Captain's cut order;
  - a risk-adding shadow intent (add, re-entry, widen, reverse:
    integrity.py:36-39).
  One r0 call each, capped per day. Its verdict is journaled beside the order or
  intent, and is never a gate in O2.
- **PS9-PS11 as of the wake.** These sections are written per wake
  (dossier_position.py:290-305), as of the render's moment
  (dossier.py:360-376). They must show the temperament, the lessons and the
  orders as of the wake's as_of, never one wake late
  [P: the dossier shows the result of the expectation from two decisions ago].

### 4.7 Tests and cost

**Tests, red first, with fake providers:**
- the audit's findings on hand-built journals;
- no idea is FAULT;
- the lane texts are equal to the prompts;
- temperaments are drawn balanced and stay fixed for life;
- PS9 and PS11 fit PS_TAIL_RESERVE;
- the MK-E order is found and the dash is not (the trap);
- the Emperor's text passes the money filter;
- with `orcs_drums` OFF, a delivery queues no W12;
- with it ON, own-stakes drums are urgent and others are not;
- the breaker trips at its numbers, and an urgent own-stakes W12 still runs;
- no Captain cut ever changes captain_may_cut, the O arm or a row.

**Cost** (calc/army_costs.py; the prompt sizes are assumptions, stated there):

| Caller | Per call | A day |
|---|---:|---:|
| A Captain's wake at r0 (r2) | $0.034 ($0.108) | 2 classes × 3 = $0.20 ($0.65) |
| The Emperor's order at r3 | $0.208 | $0.21 |
| A Skeptic co-sign at r0 | $0.030 | 2 = $0.06 |

---

## 5. O2d: seats, ranks, the council of war, Q&A, the post-mortem and the surfaces

### 5.1 Seats: the lineage's record, in shadow

**HAS**

- **OrcSeat** (models.py:21-41): level (27, "0..4"), status (28; SEAT_STATUSES
  active, suspended, revoked: constants.py:44), pinned (29), reason (30),
  model_routine and model_decisive (31-32), stats (33), changed_by (34).
  - Every seat is born at L0 (models.py:22-23).
  - The seat key is (venue, class, rule key), the rule key being "*" or
    "manual_take" (birth.py:184-189; constants.py:47-48).
- **"The grade never touches OrcSeat: seats are computed in O2, in shadow"**
  (grading.py:28-30).
  - counts_for_seat: grading.py:18-24, :164-167; models.py:269.
  - seat_block: never written (models.py:272).
  - level_at_birth: frozen at birth (birth.py:330-332; grading.py:110-117;
    models.py:267).
- **The numbers the code already holds:**
  - SEAT_WINDOW = 20 (constants.py:140), read by nothing;
  - PROMOTE_Z = 1.2816 (constants.py:138-139). Its comment says "aragorn.py:83";
    the constant actually sits at aragorn.py:92. The comment is stale;
  - RANK_GATE_N = 20 (constants.py:390-391);
  - BLOCK_FAULT_MIN_N = 5, "the spec is silent; a builder's choice"
    (constants.py:144-146);
  - block_stats and block_faults (tribunal.py:92-129);
  - HONOUR_TOLERANCE_R (constants.py:142) and TRIPWIRE_IDEA_R (:143).
- **The readers:**
  - notes._lineage reads seat.stats["n"] (notes.py:471-485);
  - /orcs/ lists the seats with their n (views_orcs.py:134-140;
    orcs_list.html:59-80);
  - /orcs/seats/ computes block_stats per (seat, bar source) on the fly
    (views_orcs.py:300-354).
- **The precedent: Aragorn's `proven`.** n ≥ 20, expectancy ≥ +0.15R, the 80%
  lower bound above 0, profit factor ≥ 1.3, the last 10 (aragorn.py:53, :90-94,
  :205-219); probation (aragorn.py:16-31, :84-86).
- **The Uruk-hai's bar on a lineage record:** n ≥ 20, win rate ≥ 0.55, average
  ≥ 0.20R, level ≥ 2, no fault in the block (army.py:125-137;
  constants.py:96-104). In O1, `assign` gets no lineage record and no privilege
  (army.py:236-243; birth.py:230).
- **Never pooled:** "Venues and bar sources are never pooled"
  (grading.py:17-24; models.py:246-247; views_orcs.py:303-308).

**ADD**

**D1. A seats beat** (new `seats.py` and a task, run after grade_closed at :40;
config/celery.py:482-485). Per seat and per bar source, it recomputes the shadow
record:
- the counted grades in graded_at order, cut into blocks of SEAT_WINDOW;
- per block: block_stats and block_faults;
- written to OrcSeat.stats. Proposed keys: n, blocks [{i, n, mean, se, lb80,
  ub80, fault}], earned_level, provisional, coin_toss, white_hand, probation,
  scars, breaches, disbanded, by_source, at;
- OrcGrade.seat_block stamped.

**D2. What counts** (DECIDE; this must be designed out).
- A grade counts for a seat only if its idea had at least one model-answered wake
  in shadow: OrcGrade.n_llm > 0 (models.py:279), written by the grade from O2a
  on.
- Otherwise O1's grades fill the "n of 20" with no evidence of a mind. In O1, Δ
  measures the care ghost against the care, with the Orc taking no step
  (views_orcs.py:39-41).
- O1's rows keep counts_for_seat as written. The seat reads n_llm.

**D3. The earned level, in shadow** (DECIDE the rule). Recommended, in
Aragorn's shape:
- a full block with LB80 > 0 earns one level;
- UB80 < 0, or a block fault, loses one;
- at most one step per block;
- "coin toss" when LB80 ≤ 0 ≤ UB80;
- "provisional" while n < 20.

Written to stats["earned_level"] only.

**D4. KEEP: OrcSeat.level, status and pinned are never written in O2.** They are
authority:
- effective_level stays 0 (notes.py:287-290);
- level_at_birth stays the seat's level, which is 0.

ADD a source pin: no O2 module writes `level`, `status` or `pinned` on OrcSeat.

**D5. The White Hand mark** (inferred: the Uruk bar met on the shadow record at
an earned L2 or above).
- Stored in stats["white_hand"]. Shown; grants nothing.
- The privilege needs the operator's PIN (army.py:236-243). KEEP Uruk-hai
  unreachable in O2.

**D6. Scars and breaches on the lineage.**
- They come from O2c's shadow breaches and O2d's council of war (D19).
- for_rows' third query (notes.py:688-689: "O2: a third, the lineages' scars and
  breaches") reads them for every row at once. The query count stays constant
  (tests/orcs/test_orc_notes.py:109, :135, :141).

**D7. A `rank` entry** (constants.py:27) on the seat's living Orcs when the
earned level changes. It is a code fact. KEEP: the model never sees it. PS1
shows no rank (dossier_position.py:11-12, :72).

**D8. The tripwire** (constants.py:143) **and "disbanded"** (notes.py:485).
DECIDE. Recommended:
- a counted idea whose O arm closed past -1.2R is a block-fault input;
- "disbanded" stays False in O2, since revoking a seat is a power.

### 5.2 Ranks

**HAS**

- **ranks.py:10-45**: RANKS, HOLDS, name, badge, level_t. Its docstring: "O2 adds
  the record a rank is earned on (n of 20, the provisional and coin-toss
  qualifiers) and the White Hand mark" (ranks.py:5-7).
- **The slot's lineage** (notes.py:471-485):
  - rank: the effective level;
  - rank_t: "Snaga · n 0";
  - badge;
  - earned_level: also the effective level;
  - white_hand: False;
  - provisional_t: "n 0 of 20";
  - venue_t;
  - probation_t: "";
  - scars: [];
  - breaches_t: "";
  - disbanded: False.
- **Where the rank is printed:**

  | Surface | Text | Where |
  |---|---|---|
  | /orc | "Rank: L0 · Snaga (watches and writes: shadow only) · n 0" | surfaces.py:241-242 |
  | /orcs | "L0 Snaga" on each line | surfaces.py:342-348 |
  | The Orc page | the Rank row | orc_detail.html:14 |
  | The Horde card | the label and level_t | sv-horde.js:1094-1098 |
  | The Horde's Orc box | "Lineage: {rank} ({n})" | the_horde.html:225; sv-horde.js:1693 |
  | /orcs/ | "Every seat is L0 · Snaga ... Seats hold no power in this release." | orcs_list.html:78 |
  | /orcs/seats/ | the Rank column, from seat.level | views_orcs.py:331 |

**ADD**

**D9. The words, in ranks.py (pure).**
- The qualifiers: "provisional" ("n 14 of 20"), "coin toss", the White Hand.
- The earned level said beside the effective rank: "L0 · Snaga; earned in
  shadow: L1 · Tracker, n 23, coin toss".
- HOLDS read as "would hold".

**D10. The lineage keys filled** from stats. `rank` stays the effective level;
`earned_level` is the shadow one. Every surface in the table above shows both,
the effective one first.

**D11. KEEP: the rank's key is `lineage`, never `seat`** (notes.py:28; horde
C18).

### 5.3 The post-mortem

**HAS**

- Kind `postmortem` (constants.py:26); agent `orc_postmortem`
  (views_ai_models.py:100; tests/test_ai_spend_lines.py:186).
- Death comes three ways: lifecycle._close_leg (lifecycle.py:101-149), the kill
  switch (lifecycle.py:152-179), the sweep (lifecycle.py:182-206).
- The grade waits for every arm (grading.py:132-139) and runs hourly
  (tasks.py:84-109; config/celery.py:482-485).
- OrcGrade's counters are never written: expectation_hit_rate, flipflop_rate,
  n_wakes, n_llm, n_actions, n_refused (models.py:276-281).

**ADD**

**D12. One post-mortem per graded idea that had at least one model wake.**
- It runs after the idea's grade, never at death, because the arms are still
  walking at death. A beat after grade_closed runs it.
- The Orc reads its journal digest, its plan versions, its intents and their
  grades, the arms (O, care, playbook, policies), and the class and labels set by
  code.
- It writes kind `postmortem`, author orc, filtered and capped.
- Idempotent: one per idea, with a unique key.
- Deferrable: lowest triage. It may wait for the next day's line.

**D13. The grade's counters** (models.py:276-281) are written by the grade, from
O2a's journal, if O2a does not write them. The post-mortem and D15 read them.

**D14. Who gets one.**
- A killed idea (lifecycle.kill_all) and a hand-touched one (grading.py:28) get a
  post-mortem like any other.
- DECIDE whether an idea with no model wake gets one. Recommended: no; there is
  nothing to judge.

### 5.4 The council of war

**HAS**

- **tribunal.py** sets the class by code: FAULT, WON, HONOURABLE. The labels:
  victory_in_defeat, costly_early, costly_late. The block faults
  (tribunal.py:1-24, :66-129).
- **Written in O1**: OrcGrade.fell, sub_label and first_divergence
  (models.py:283-286; grading.py:149-152, :200-202), and the grade's journal line
  (grading.py:101-107, :204-211).
- **"the council's words (the model call) arrive with O2"** (tribunal.py:1-3).
  The agent: orc_tribunal, "The council of war" (views_ai_models.py:101).
- **Reserved**: OrcBattle, OrcLesson, OrcWeapon (tests/orcs/test_orc_models.py:
  18-20).
- **PS10**: "— (no lesson yet: the lineage's record starts in O2)", described as
  "the lessons and weapons of the lineage (§6.10-6.11)"
  (dossier_position.py:299-303).
- **A lesson is T1 prose** (fence.py:7-9), capped at 200 characters
  (constants.py:225-226).
- **Journal kinds** heritage and scar (constants.py:27).
- **"the fallen"** on the class band (notes.py:752).
- **A name collision**: "battles" is taken by the council of ten. Its band shows
  "BATTLES · 30 DAYS" (council_band.py:202, :1136-1145), and CouncilClaim has a
  "battle" kind (council_models.py:184-186).

**ADD**

**D15. The council of war's sitting**, after the post-mortem.
- DECIDE: one per idea or one per block. Recommended: one per graded idea that
  has a post-mortem, one call: r2 on real money, r0 on paper and demo.
- KEEP: the class and the labels stay code's (tribunal.py:1-3).
- The model writes the words, at most N lesson candidates and N weapon
  candidates, each citing fact ids.

**D16. OrcBattle.** Proposed fields:
- the Orc (one-to-one) and its grade;
- fell, sub_label, and the causes set by code;
- the shadow verdict (O2c C2);
- the words, filtered;
- the post-mortem's entry id;
- the cost; at.

On surfaces, name it "the council of war" or "the fallen", never "battles".

**D17. OrcLesson.** Proposed fields:
- the seat (the lineage) and the battle it came from;
- the text (at most 200 characters, filtered);
- the kind: do or avoid;
- the evidence ids;
- created_at and retired_at.

DECIDE a cap per lineage. Recommended: 5 in force, the oldest retired. A lesson
is never a rule that code obeys.

**D18. OrcWeapon** (inferred: a tactic that worked for the lineage). Proposed
fields:
- the seat and the battle or battles it came from;
- the tactic, as a pattern code can recognise: a playbook id or a plan clause
  kind;
- its measured Δ (n, mean, bounds);
- the text.

DECIDE whether a weapon needs a measured block. Recommended: a pattern is listed
as a weapon only when its Δ over at least BLOCK_FAULT_MIN_N ideas reads
LB80 > 0. Until then it is a lesson.

**D19. Scars.**
- A block fault (tribunal.block_faults), or from O3 a FAULT, marks the lineage:
  stats["scars"], and a `scar` entry on the dead Orc.
- In O2 only a block fault can scar (D3, D8).

**D20. Heritage, at birth.**
- The newborn Orc of a seat gets a `heritage` entry: its lineage's lessons in
  force, weapons and scars.
- PS10 shows them as views (dossier_position.py:303), sized inside
  PS_TAIL_RESERVE.

**D21. The fallen.** The class band (notes.for_classes) and the dead list on
/orcs/ (views_orcs.py:132-133; orcs_list.html:35-57) show each fallen idea's
class, its labels and a link to its council of war.

**D22. IdeaFacts in O2.**
- refusals: from n_refused.
- signpost_unacted: from O2c's shadow audit.
- gave_back: an OrcGrade tag. tribunal.py:111-119 reads it from the rows. DECIDE
  the definition. Recommended: W4's give-back, the O arm's R at or below half
  its best after a best of +1R (constants.py:308-311).
- KEEP: breaches and exit_available stay as in O1.

### 5.5 Q&A

**HAS**

- **/orc N <question>** today answers QUESTION_LATER: "Orcs do not answer
  questions yet: none calls a model. Ask Sauron instead: /q <question>."
  (surfaces.py:35-36, :292-294). The docstring: "(O2 answers it)"
  (surfaces.py:16-18).
- **Reserved**: kinds `question` and `answer` (constants.py:26); agent
  `orc_question` (views_ai_models.py:99).
- **The rung**: r1, "real money only for questions" (catalog.py:510-511).
- **The Eye's own question flow** (telegram_eye.py:1279-1318) is the pattern to
  follow.
  - The question is persisted and the reply says "received".
  - The queueing rides the reply's meta "then", run after the commit
    (telegram_eye.py:1569-1572).
  - The answer is sent with `_send` (telegram_eye.py:598).
  - QUESTIONS_PER_DAY = 30 (telegram_eye.py:124), counted by questions_today
    (:1266-1276).
- **The pins.**
  - notes, surfaces and ranks may not name begin_ask, answer_question,
    ClaudeProvider, complete, _send_telegram or send_alarm, nor anything of
    ai_agents (tests/orcs/test_orc_source_pins_o1d.py:18-24, :41-50).
  - views_orcs writes through exactly one journal.append
    (tests/orcs/test_orc_source_pins_o1d.py:66-84).

**ADD**

**D23. A module outside the three pinned ones** (new `questions.py`).
- ask(orc, text, user, chat) writes a `question` entry: author operator, the
  operator's own words under plain voice, no fact id.
- It queues the answer task on the `orcs` queue, with a first_enqueued_at for
  the stall clock [P: re-stamping enqueued_at defeats the stall census].

**D24. The reply.** surfaces.orc_reply's question branch (surfaces.py:292-294):
- answers "received; the answer follows here" when the switches and the cap
  allow it, and otherwise says why;
- returns the queueing as meta "then", which the Eye registers after its commit,
  as ask_question does;
- surfaces itself stays free of the model, of begin_ask and of _send.

**D25. The answer task.**
- It checks again: the switches, the Orc, the per-day cap, can_spend.
- DECIDE whether an ended idea can still be asked about. Recommended: yes, read
  only.
- It calls agent orc_question, source_ref `Orc:<id>:Question:<n>`. DECIDE the
  rung: r1 on real money, r0 on paper.
- It validates the answer: the money filter, English, a length cap.
- It writes an `answer` entry, author orc, filtered.
- It sends the reply to the chat that asked (telegram_eye._send), never to the
  alarm group (surfaces.py:4-6).

**D26. An answer is inert** (recommended). It never writes a plan, an intent,
latest_note or a stop, and it is not a wake.

**D27. The cap** (DECIDE). Recommended: 10 a day per user, counted on `question`
entries since 00:00 UTC. It sits beside the Eye's own 30
(telegram_eye.py:124, :1266-1276).

**D28. The prompt.**
- The Orc's latest wake's blocks (OrcWake.block_hashes, models.py:178; replayed
  by dossier.text_of, dossier.py:141-147).
- Plus the question, as an operator view (fence.view, source operator).
- The quarantine may withhold the question whole. The reply then says so and
  asks the operator to rephrase.

**D29. The form on the Orc's page** (DECIDE).
- A POST on /orcs/<id>/ (dashboard/urls.py:255-261), accepted only while the
  switch is ON.
- tests/orcs/test_orc_source_pins_o1d.py:66-84 (one journal.append in views_orcs)
  changes on purpose.

### 5.6 The surfaces: every hook

The owner is the commit whose arrival makes the O1 text false. O2d builds what
is left.

| # | Surface | Hook (file:line) | O1 today | O2 must | Owner |
|---|---|---|---|---|---|
| 1 | Horde slot: plan | notes.py:507-510, :535 | "No plan yet: Orcs write plans once they reason." | The plan, rendered by code, prices through format_price (:509) | O2a writes, O2d renders |
| 2 | Horde slot: intents | notes.py:545 | [] | The 3 newest, each with its mode: "proposed in shadow: tighten to …" | O2a, O2d |
| 3 | Horde slot: the comparison | notes.py:176-177, the pattern at :786-787 | "…the Orc has taken no step." | The O arm with its shadow intents against the care ghost, in a new reserved sentence | O2a, O2d |
| 4 | Horde slot: rung | notes.py:184, :431-442 | RUNG_NONE | The rung in words (B12) | O2b |
| 5 | Horde slot: lineage | notes.py:471-485 | fixed O1 values | D10 | O2d |
| 6 | State words | notes.py:140-150 | born: "Watching: a journal written by code, no model." | Words for born, active and care_owned that are true with the minds switch on or off | O2a |
| 7 | Next wake words | notes.py:179-182 | "detected and recorded only, no model" | Whether a model will answer | O2a |
| 8 | Commission words | notes.py:151-157 | advise, class; reduce and trail "under your PIN" | KEEP (those powers are O4a's) | |
| 9 | Positions line and close note | notes.py:613-614, :657 | PLAN_SHORT "no plan yet" always | The plan's short form | O2d |
| 10 | Voices on the slot | notes.py:555-578; horde.py:448-450 | only the operator's thesis | Add the orc, captain and emperor authors (X5) | O2a (the Orc's), O2c |
| 11 | for_rows | notes.py:688-689 | 2 queries | A 3rd: the lineages' scars and breaches | O2d |
| 12 | for_classes | notes.py:749-771 | the day's weather only, no label | Label, orders, waves, the fallen, the Emperor's line | O2c, O2d |
| 13 | Reserved words | notes.py:781-796; horde.py:272-299 | O1's sentences | Each new sentence | each commit |
| 14 | Horde: Captain words | horde.py:280-283; the_horde.html:147-148; sv-horde.js:1137, :1162 | "No Captain seated yet."; "Captains are not built yet…" painted always | Conditional on a seated Captain | O2c |
| 15 | Horde: mission plan row | horde.py:2891-2896, :3050-3056 | the row's levels; "the agent's plan line rides its own slot … until one writes a plan" | DECIDE. Recommended: the Orc's shadow plan on its own line, never replacing the venue's levels | O2d |
| 16 | Horde: the Orc box | horde.py:2831-2836, :3047-3048; sv-horde.js:1667-1707; the_horde.html:209-229 | paints state, rank, thesis, plan, risk, compare, note, army, score, integrity, lineage, journal, drums | Also paint the intents, the earned rank and its qualifiers, the temperament, the Captain's order in force | O2c, O2d |
| 17 | Horde: the card's plan | sv-horde.js:1038 | plan_line | The plan's short form | O2d |
| 18 | Horde pins | tests/test_the_horde.py:918-1006, :948-961 | no Orc or Captain seated; every Orc word reserved; no Orc verb | Updated on purpose, the verb pin kept | O2c, O2d |
| 19 | Positions page | dashboard/views.py:2918-2931; positions_list.html:314, :332 | line_dict: line, plan, compare, j1-j3 | Items 1-3 and 9 flow through | O2d |
| 20 | Close dialog | dashboard/views_close.py:91-104; base.html:3187; notes.py:649-670 | rank, state, "no plan yet", thesis, note, last fact, "Information only" | The plan and the latest intent. KEEP INFO_ONLY (notes.py:191) | O2d |
| 21 | Orc page | views_orcs.py:203-248; orc_detail.html | the Rank row (14), Complexity and rung (20), Plan and Intents (59-64; NO_INTENTS at views_orcs.py:38), the journal's styles (72; AUTHOR_STYLE at views_orcs.py:52-54, read at :225), the wakes table and heading (104-125, heading at 105), the grade, "Graded (shadow, no Orc action)" (130) | Each true. New cards: the temperament, the Captain's orders in force, the post-mortem, the council of war, the lineage (lessons in force, scars). DECIDE the question form (D29). An "emperor" author drawn as a note | O2a (wakes, plan), O2c, O2d |
| 22 | /orcs/ | views_orcs.py:104-156; orcs_list.html:3, :78, :87 | "ORCS · JOURNALS BY CODE"; "Every seat is L0 · Snaga…"; staff: "off (no Orc calls a model in this release)" | The title and the spend line (O2a); the seats with their earned levels (O2d) | O2a, O2d |
| 23 | /orcs/seats/ | views_orcs.py:39-41, :300-354; orcs_seats.html:9, :59, :65 | SEATS_NOTE "In this release no Orc takes a step, so Δ measures the care ghost against the care…"; vs_line "—" (views_orcs.py:350) | The note becomes false once the O arm carries shadow intents (O2a). Add the earned levels and blocks (O2d), the temperaments against the control (O2c), the ladder (O2b). Against Line once the types act (army.py:11-12) | O2a-O2d |
| 24 | Telegram /orc | surfaces.py:228-271 | Rank (241-242), plan (254), MODEL_CALLS "Model calls today: 0" (45, :268), the grade "(shadow: no Orc acted)" (218-225) | The real count of model calls (Orc.llm_wakes_today, models.py:103: O2a). The intents, temperament, Captain's order and earned rank (O2c, O2d) | O2a, O2c, O2d |
| 25 | Telegram questions | surfaces.py:16-18, :35-36, :292-294; HELP_LINES at :46-48 | QUESTION_LATER | D23-D29. The help line for the question form (telegram_eye.py:957-967 reads help_lines) | O2d |
| 26 | Telegram stand-down and off | surfaces.py:37-40, :286-291, :321-323 | words only | KEEP (their write is O4a's) | |
| 27 | Council band | council_band.py:205, :326, :2386, :2410; sv-council-band.js:746-747 | "The Orcs are not in the field yet." | The truth: how many Orcs think, in shadow, and that none acts | O2a (minimal), O2d |
| 28 | /ai-models/ | views_ai_models.py:89-104, :232-235; ai_models.html:151-175 | "No Orc runs today." | The line on (O2a); the ladder's use and validation (O2b) | O2a, O2b |
| 29 | Switch descriptions | platform_control.py:320-339 | "Orcs (journals, no model)" (323-324); orcs_drums: "In O1 this switch changes nothing" (330-331) | True descriptions, and the new switches' rows | O2a, O2c, each commit |
| 30 | The Book, the RUNBOOK | core/book_content.py:129, :579-592, :1599-1605, :1740-1745; tests/test_the_book.py:2230; RUNBOOK.md:1275, :1308-1312, :1360, :1520, :1591-1594, :1637, :1671, :1713 | "No model is called"; "no Orc reasons or acts in this release"; "no Orc takes a step" | Each commit's own section and the corrected lines (MAP 4 lists the promises) | each commit |
| 31 | Scorecard and shell | bot_program/scorecard.py:306-345 (--by orc; ai_cost_r is 0 until O2a books AI cost); management/commands/orcs.py:51-55 | O1's choices | DECIDE --by rung and --by temperament. New dry-by-default subcommands per commit [P] | O2b-O2d |

### 5.7 Tests and cost

**Tests, red first, with fake providers:**
- O1-era grades do not fill a seat's n.
- No O2 module writes OrcSeat.level (a source pin).
- The earned level moves by the rule and never touches effective_level.
- Each post-mortem is written once, after its grade.
- The council of war cannot change fell or sub_label.
- A lesson is capped at 200 characters and filtered.
- Heritage appears in PS10 at the next birth on the seat.
- A question:
  - with the switch OFF, there is no call and the reply says why;
  - past the cap, there is no call;
  - an answer naming an amount is withheld;
  - the answer goes to the chat that asked;
  - surfaces.py still names no model.
- Every new sentence is reserved; no Orc verb appears anywhere.

**Cost** (calc/army_costs.py):

| Caller | Per call | A day |
|---|---:|---:|
| The council of war at r2 | $0.116 | 2 ideas = $0.23 |
| A post-mortem at r0 (r1) | $0.038 ($0.078) | 2 ideas = $0.08 |
| An answer at r1, warm cache (cold) | $0.080 ($0.094) | 3 questions = $0.24 |

---

## 6. The ten reserved tables

Source: tests/orcs/test_orc_models.py:14-20, :57-64; models.py:7-9.

| Table | Commit | What it holds | Main hooks |
|---|---|---|---|
| OrcIntent | O2a | the shadow intents (map_wakes §3.7); O2c adds wave_id (C29) | constants.py:388-389; notes.py:545 |
| OrcActionGrade | O2a, else O2d | each intent priced forward; reused by B7 and C18 | ghost.py and pricing.py |
| OrcTierGrade | O2b | the probe pairs and their blocks (B7) | catalog.py:500-504 |
| Captain | O2c | one per (user, class): seated_at, label, state, last_wake_at, wakes_today; its record | notes.py:749-753; horde.py:422-440 |
| CaptainOrder | O2c | C14 | dossier_position.py:299-304 |
| OrcWave | O2c | C27 | drum_bus.py:41-44 |
| OrcTemperamentGrade | O2c | C10 | dossier_position.py:299-302 |
| OrcBattle | O2d | D16 | tribunal.py:1-3 |
| OrcLesson | O2d | D17 | dossier_position.py:299-303; FENCE_CAPS "lesson" |
| OrcWeapon | O2d | D18 | dossier_position.py:299-303 |

Rules for all ten:
- No `choices=` on a kind or status column (models.py:11-13).
- No money column on any table a surface reads.
- Each table ships in its own commit's migration (X11).

---

## 7. Every O2 hook in the code, with its owner

**The O2 markers** (a grep of `O2` in bot_program/orcs/ at 9d74a19):

| File:line | What the code says | Owner |
|---|---|---|
| wake.py:43, :47, :54-55 | the dispatch, the router, the reserve, the budget; W12 | O2a; the router O2b; W12 O2c |
| observe.py:78; tasks.py:4 | the dispatch; the `orcs` queue and worker | O2a |
| playbook.py:3, :26-27; integrity.py:19-21, :33, :39 | the menu a wake sees; the mandate's officer | O2a (map_wakes) |
| fence.py:23-24; constants.py:231-232 | the validator enforces V10 | O2a |
| constants.py:9 | the active and care_owned states | O2a |
| constants.py:351, :354, :356-357 | the words "no model before O2" | O2a |
| dossier.py:5, :410; dossier_position.py:16, :38 | S; PS5's notes; PS3 | O2a |
| dossier_position.py:26, :355-356 | the continuation odds | O2a (DECIDE in map_wakes) |
| weather.py:9; complexity.py:10 | "the dollar caps arrive with the router"; "the router is O2's" | O2b |
| army.py:12 | the type's cadence, dossier focus, model ladder and mandate act from O2 | cadence and mandate O2a; ladder O2b (B13) |
| dossier_position.py:24, :299-304 | PS9, PS10, PS11 | PS9 and PS11: O2c; PS10: O2d |
| dossier_market.py:34, :260-261 | MK-E, the Emperor's daily order | O2c |
| drum_bus.py:41-44, :85, :219-220, :584, :666-667 | W12, waves, the breaker, the hop | O2c |
| predicates.py:36-37, :351 | `wake.request(orc, "W8", urgent=True)` (the function does not exist) | O2a (map_wakes §2.1 j) |
| tribunal.py:3, :47 | the council's words; the breaches | words O2d; breaches O2c (binding O3) |
| grading.py:29 | seats are computed in O2, in shadow | O2d |
| ranks.py:6-7 | the record a rank is earned on; the White Hand | O2d |
| army.py:239 | Uruk-hai unreachable "until the ranks (O2) and the operator's PIN exist" | O2d supplies the record; the PIN later |
| notes.py:33 | the plan line, intents, temperament, honor, the lineage's record | O2a-O2d |
| notes.py:509 | the plan rendered by code | O2a, O2d |
| notes.py:688-689 | for_rows' third query | O2d |
| notes.py:751-753 | for_classes: the Captain, orders, waves, the fallen, the Emperor's line | O2c, O2d |
| surfaces.py:17-18 | "/orc N <question>" (O2 answers it) | O2d |
| models.py:7-9, :293 | the O2 tables; "the budget keys from O2" | each commit; O2a |

**Hooks with no O2 marker:**

| File:line | What it is | Owner |
|---|---|---|
| models.py:31-32 | OrcSeat.model_routine and model_decisive | O2b, DECIDE |
| models.py:67 | Orc.captain_may_cut: KEEP False | O3 or later |
| models.py:272, :275-281 | OrcGrade.seat_block, tags and the counters | O2d (counters O2a) |
| models.py:341-343 | OrcDayBaseline.caps, frontier_quota and routing_version become binding | O2b |
| constants.py:30-31 | AUTHORS gains "emperor" | O2c |
| constants.py:140, :143, :255 | SEAT_WINDOW, TRIPWIRE_IDEA_R, DRUM_SETTLE_MIN: unread | O2d, O2c, O2c |
| complexity.py:230-233 | stakes `wounded` and `level` never passed | DECIDE. `level` must stay the effective level, so STAKES_L3 stays off in O2 |
| wake.py:123-138 | the facts hash, versus PS9-PS11 | O2c, C16 |
| wake.py:731, :735-741, :765-771 | the stakes, the floors, the band, the card | O2b |
| horde.py:448-450 | the voice authors | X5 |
| views_orcs.py:52-54 | AUTHOR_STYLE | O2c, O2d |
| views_ai_models.py:89-104 | the eight agent names | every commit |
| dossier.py:135-138 | `find` returns the oldest block | O2c, C21 (the trap) |
| dossier_instrument.py:39-41 | PS_TAIL_RESERVE, versus PS9-PS11 | O2c, O2d |

---

## 8. Test pins O2b-O2d must change on purpose

| Pin | What it holds today | Changed by |
|---|---|---|
| tests/orcs/test_orc_models.py:14-20, :57-64 | the package defines exactly the O1 tables | each commit moves its tables |
| tests/orcs/test_orc_switch_off.py:427-456 | no `ai_agents` and no order path in the package | widened to the gateway file only (O2a); order paths still forbidden |
| tests/orcs/test_orc_source_pins_o1c.py:69-83 | the "# O2:" markers; no pending wake | O2a (wake), O2c (dossier_market, drum_bus), O2c/O2d (dossier_position) |
| tests/orcs/test_orc_source_pins_o1d.py:18-24, :41-84 | notes, surfaces and ranks call no model and write nothing; views_orcs makes one append | O2d (the question form) |
| tests/orcs/test_orc_notes.py:32-42, :109-141, :157-167, :431, :475-496 | O1_KEYS; MONEY_KEYS; VERB; the query counts; the lineage keys; intents []; rung_t; for_classes with no label | O2b (rung), O2c (class slot), O2d (lineage, intents) |
| tests/orcs/test_orc_pages.py:160 | NO_INTENTS | O2a or O2d |
| tests/test_the_horde.py:918-1006 | the Orc rule | O2c, O2d |
| tests/test_model_catalog.py:434-498 | the ladder; no id outside the catalog | KEEP, never changed |
| tests/test_council_shadow.py:275-294 | only three modules read the weights | C11, DECIDE |
| tests/test_ai_spend_lines.py:183-197 | Orc and Captain membership on the line | KEEP, extended |
| tests/test_the_book.py:2230 | the orcs_drums description says "from O2" | O2c |

---

## 9. Calls a day, caps and triage (proposal)

The arithmetic is in calc/army_costs.py: catalog prices, map_ai's central output
per rung, and the prompt sizes stated in that script. Assumed day: 10 open
positions (5 real money, 5 paper), 2 classes, 2 ideas dying, 3 questions, 2
risk-adding shadow intents, Captains waking 3 times a class.

| Caller | Rung | Per call | Calls a day | $ a day | Proposed cap | Triage |
|---|---|---:|---:|---:|---|---|
| Captain | r0 | 0.034 | 6 | 0.20 | 4 a class a day | with real routine |
| Emperor | r3 | 0.208 | 1 | 0.21 | 1 a user a day | with real routine |
| Council of war | r2 | 0.116 | 2 | 0.23 | deferrable | last, may wait a day |
| Post-mortem | r0 | 0.038 | 2 | 0.08 | deferrable | last, may wait a day |
| Answer | r1 | 0.080 | 3 | 0.24 | 10 a user a day | with real urgent (the operator waits) |
| Skeptic co-sign | r0 | 0.030 | 2 | 0.06 | 6 a day | with its intent's wake |
| Boundary probe (paper) | r1 | 0.080 | 6 | 0.48 | 6 a day | last of all |
| h0 probe (paper) | h0 | 0.0018 | 30 | 0.05 | paper wakes, calm and eventful days | last of all |
| **Total** | | | | **1.55** | | |

- Probes and post-mortems never touch the floor for live urgent wakes
  (spend.py:82-84).
- The total is on top of map_ai's $6.34 calm-day central for O2a's wakes at 10
  positions (map_ai §5.4). That makes about $7.9 a day, inside the $10 line
  map_ai proposes. On a stormy day the line binds, and the triage keeps real
  money first.
- A busy day costs $3.23 for these callers alone: Captains at r2, 4 ideas dying
  with r1 post-mortems, the 10-question cap reached with a cold cache, 6
  co-signs.

---

## 10. Questions only the operator can answer (O2b-O2d), with a recommendation

1. **Routing**: does O2b's router first run in shadow behind `orcs_router`,
   OFF, while O2a's fixed rung answers? *Recommended: yes.*
2. **Fable (r5)**: stays at 0 a day through O2. Afterwards, 1 a day across all
   classes, real money only, with its r4 twin. *Recommended: yes.*
3. **Probes**: on paper only, 6 boundary probes a day plus h0. *Recommended:
   yes.*
4. **Temperaments**: drawn at random (balanced) beside a control, rather than
   chosen by the council at entry. *Recommended: random, so the grade measures
   the temperament.*
5. **Captains**: one per class, waking at the class's first session open, on a
   class-wide level break and after the Emperor's order. Orders in shadow,
   graded, never applied. *Recommended: yes.*
6. **The Emperor**: one daily order per user after the day roll. Is he the
   council's Emperor with a second duty, or a separate figure? *Recommended:
   one Emperor, named apart where both duties show.*
7. **Seats**: count only ideas that had at least one model wake; earn levels in
   shadow by a full block of 20; never grant power in O2. *Recommended: yes.*
8. **Questions**: 10 a day, answered on r1 for real money, on Telegram (and on
   the Orc's page?). *Recommended: 10 a day; the page form too.*
9. **The new switches**: kept out of the System group's "all on", since they
   spend AI money. *Recommended: yes.*
10. **The Skeptic's co-sign**: only on a Captain's cut order and on risk-adding
    shadow intents, or deferred to O3. *Recommended: O2c, capped at 6 a day.*
