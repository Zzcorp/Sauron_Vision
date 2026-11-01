# MAP 4 — The recovered pitfalls and the promises

Source: the read-only checkout of main 9d74a19 (2026-11-01) at
`/home/user/Sauron_Vision/.claude/worktrees/orcsread`. Every `file:line` below
is repo-relative in that tree. The recovered text is
`/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/orcs_o2_recovered.txt`,
cited as REC:line.

Companion maps in this folder: `map_wakes.md` (the O2a hooks; its **[P]** flags
point here), `map_ai.md` (the call recipe, the prices, the costs) and
`map_army.md` (O2b to O2d).

How to cite this map:
- **P1-P40** are the requirements O2a must meet (Part A).
- **F1-F39** are the recovered review findings, numbered in their recovered
  order (table A.10).
- **Fix 1-6** are the fixes that survive.
- **K-**, **U-** and **D-** ids are the promises (Part B). K means keep it
  true, U means update the words, D means deliver what the words promise.
- **DECIDE** marks a value or a choice the lost spec held. The new spec must
  state it; a recommended default follows.

---

## Part A. The recovered pitfalls as requirements

### A.0 What survives, and how much

- **The run.** REC:1-11 is the notification of task wt3zrcu0k (run
  wf_ac58c694-b3f, branch `orcs2` on main 6e30161). It planned O2 as four
  commits:
  - O2a: wakes and the mind in shadow;
  - O2b: routing in shadow;
  - O2c: honor, temperaments, Captains, the Emperor and the drums in shadow;
  - O2d: seats, ranks, the council of war, Q&A, the post-mortem and the
    surfaces.
  Each commit was to be built tests-first with fake models and reviewed by
  three lenses (safety, spec, tests), with two skeptics per finding.
- **Only O2a finished.**
  - It was committed as `e264dc3`, "The Orcs wake and think in shadow: one call
    per real reason, inside their own budget line, and nothing they decide can
    act" (`TESTS_GREEN=13836`).
  - It was never pushed and was lost in the reset.
  - O2b's verification and fix, and all of O2c and O2d, failed on the weekly
    limit (REC:12-47). No O2b-O2d finding survives.
- **The O2a review.**
  - 39 findings: 35 marked `real: true`, 4 marked `real: false`.
  - The fixer reported "26 distinct confirmed findings (the list of 34 had
    duplicates)". Grouped by subject, the 35 real findings make exactly 26
    groups, once the two `orcs record --yes` findings (F6, F27) count as one.
- **The fix list is truncated.**
  - The notification cuts at 10,550 characters, inside fix 6 (REC:7-8). Fixes
    1-6 survive; fixes 7-26 do not.
  - The full output (`tasks/wt3zrcu0k.output`) and the run's journal no longer
    exist. The session transcript holds the same truncated text (checked
    2026-11-01).
  - Every requirement below that has no surviving fix is derived from the
    finding's own words and the O1 code, and says so.
- **The lost build's names.**
  - Module: `bot_program/orcs/scheduler.py`, with `dispatch_due`, `run()`,
    `census_stalled` and `census_silence`.
  - OrcWake fields: `enqueued_at` and, after the fix, `first_enqueued_at`.
  - Skip code: `day_cap`.
  - Command: `orcs record --yes`, which reads a scenario file.
  - Test helpers: `NoCallProvider` and `NoNetworkMixin`.
- **The lost build's numbers.**
  - 15-minute spacing.
  - A 20-minute queue stall.
  - A 30-minute stale rule.
  - Paper urgent wakes stop at 60% of the Orcs line.
  - "A 13th model wake", so 12 a day.
  - "The last 6 decisions".
  - "Two such refusals send the Orc to the care".
- **The pre-reset session summary** (transcript, line 2) adds three rules:
  - "O2 is 'shadow minds': no model call while `ORC_DAILY_BUDGET_USD=0`";
  - "Queues and workers must be consumed";
  - "Fake providers in tests".
- **Rule names the lost spec defined and the code does not.**
  - The names: V6, "rule 2", I3c, I4, I12, C14, C17, and D18 used as a per-Orc
    cap. In the code, D18 is only the line example "Cap $13, total $27"
    (tests/test_ai_spend_lines.py:181).
  - The new spec must restate every rule it keeps, or drop its name.

### A.1 Cross-cutting: the lost commit's three promises, and the queue rule

**P1. One call per real reason.** *(the lost commit's title)*
- No model call is made for a wake that code can answer:
  - a quiet wake (F6, wake.py:741-744);
  - a wake merged into a newer one;
  - a wake refused by a cap, the triage, the spacing, a switch or the line;
  - a dead Orc;
  - a closed row;
  - a dossier that is `over_budget` (dossier.py:441).
- Each such wake ends with a status and a code, and a code reading (journal
  kind `budget` or `reading`) in fixed English words.
- Proof: the fake provider's call list stays empty on every one of these paths,
  and each path's code is asserted (see P36).

**P2. Inside their own budget line.** *(the lost commit's title; the
session summary)*
- Every Orc call is billed to the Orcs line. Use agent `orc` or an
  `orc_`-prefixed name, and source_ref `Orc:...` (spend.py:93-97, :130-140).
- Before any call, the line is asked for the call's whole bound plus the money
  already reserved by calls in flight: `can_spend(line="orcs", tier=<rung tier>,
  estimated_usd=<bound + in flight>)` (spend.py:208-276; recipe in map_ai.md
  §2.1).
- `ORC_DAILY_BUDGET_USD` defaults to 0. At 0, no call is made, whatever the
  switches say (spend.py:79-81, :229-230). tests/test_ai_spend_lines.py pins
  the refusal text and must stay green as it is.
- With the line on and the minds switch OFF, no call is made either.
- Proof: one test with the line at 0 and every switch ON, and one with the line
  on and the minds switch OFF. Both leave the fake provider's call list empty.

**P3. Nothing they decide can act.** *(the lost commit's title)*
- No order, stop move, size change or close comes from an Orc. No AssetBotTrade
  write except the existing `metadata["orc"]` stamp.
- O2a must never write any of these:
  - the binding fields `Orc.stop_level`, `stop_why`, `stop_at`, `trail_owner`,
    `lock_waiver` and `be_swap_floor` (models.py:86-93);
  - a row's `metadata["orc_exit"]`, which marks a BINDING Orc exit
    (ghost.py:1328-1330);
  - any `DROP_META` key (ghost.py:99-102).
- No order-path module may read `Orc.plan`, an intent or a note.
- The tick keeps ignoring `after_care` (asset_engine/base.py:1396-1409).
- Proof: source pins on every new module (no FORBIDDEN identifier, no
  AssetBotTrade write; tests/orcs/test_orc_source_pins_o1b.py:15-23), plus
  P38's end-to-end runs.

**P4. Queues and workers must be consumed.** *(the session summary)*
- No task may be routed to a queue that no worker consumes.
  - Today `worker-fast` serves `fast,default` and `worker-slow` serves
    `slow,ai` (deploy/docker-compose.yml:163-175).
  - There is no `orcs` glob "until O2's worker and its `orcs` queue exist"
    (config/celery.py:96, :100-101; bot_program/orcs/tasks.py:4-6).
- The `orcs` queue ships with its worker in the same commit.
- A config test parses deploy/docker-compose.yml and proves that every queue in
  `task_routes` has a consumer.
- The RUNBOOK says how to check that the worker runs (U-R8).

### A.2 Budget and triage

**P5. Day caps bind every wake on the whole day's totals.** *(F1 important/
safety; F29 important/tests; Fix 1)*
- A routine wake is answered by code, with code `day_cap`, once the Orc's whole
  day is used, even when urgent wakes used it. "Whole day" means either cap:
  - model wakes of every kind;
  - dollars.
- The routine sub-caps (`routine_wakes_today`, `routine_spend_today_usd`) are
  checked as well as the whole-day caps, never instead of them.
- The wake cap is `weather.caps_for(day_class, real)` (weather.py:29-42): real
  money 12, 14 or 16 by calm, eventful or stormy; paper 12.
  - Compute it per Orc with that Orc's own `real`.
  - Trap: `OrcDayBaseline.caps` holds whatever the first reader's `real`
    produced. `orc_day_roll` calls `weather.current` without `real`
    (tasks.py:177; weather.py:160).
- The dollar cap is a per-Orc `per_orc_daily_usd`, an OrcSetting key ("the
  budget keys from O2", models.py:290-293). DECIDE its value with map_ai.md.
- The counters `llm_wakes_today`, `routine_wakes_today`, `spend_today_usd` and
  `routine_spend_today_usd` (models.py:103-109) are never written today.
  - Write the counts at the claim and the dollars at the settle, under the
    Orc's lock.
  - Reset all four on ONE stated day clock. DECIDE; recommend the ledger's UTC
    day (spend.py:143-146), because the dollars guard the line. The weather's
    day rolls at 17:00 New York instead (constants.py:371).
- DECIDE what an urgent wake does at the whole-day cap. Recommend:
  - a real-money urgent or confirm wake may pass the count cap, but never the
    line nor the Orc's dollar cap;
  - a paper urgent wake stops at both caps.
- Proof:
  - urgent wakes use all 12 → the 13th wake, a routine one, gets `day_cap` and
    0 calls;
  - the same test with dollars.

**P6. Triage by money world, then urgency, with ceilings that never invert.**
*(F13 important/spec; Fix 2)*
- The dispatch order is real urgent, then real routine, then paper urgent, then
  paper routine.
- A paper urgent wake stops once the Orcs line is 60% spent (the recovered
  value), "so the rest stays for real money".
- No class may spend past the ceiling of a class above it.
- Only real-money urgent and confirm wakes may use the top of the line (the
  reserve).
- The recovered build stopped real routine wakes at 60% too (F13's text).
  DECIDE:
  - real routine's ceiling: recommend keeping 60%;
  - paper routine's ceiling: at most 60%; recommend 40%.
- Reservations of calls in flight count against the ceiling (map_ai.md §2.1
  step 2).
- The reserve is the Orcs' own slice of their line. It is not
  `ORC_LIVE_FLOOR_USD`, which is held back from the CORE line (spend.py:28-31,
  :82-84).
- Proof:
  - paper urgent wakes cannot push spend past 60%;
  - a real urgent wake still runs at 95%;
  - in one pass, a real routine wake is claimed before a paper urgent one.

**P7. "Real" means the live money world.** *(derived from F13's "paper" and
"live")*
- Triage reads the world frozen at birth: the seat's venue, from
  `birth.world(row)` (birth.py:126-135; constants.py:39-46).
- An eToro demo row and a paper row are "paper" for the budget. "A demo row is
  never real money" (constants.py:39-43); the Orc never counts one with real
  money (deploy/RUNBOOK.md:1508-1512).
- Trap: `world()` maps any world it does not recognise to live
  (birth.py:133-135). DECIDE whether a NO VENUE row may draw on the real
  reserve. Recommend: no; budget it as paper.

**P8. A failed call is booked honestly, and a storm of failures is bounded.**
*(F25 minor/spec, judged FALSE)*
- **Why it was judged false** (the skeptics' reasons were not preserved; this
  is inferred from the code):
  - the ledger books measured spend only ("computed from real spend rather than
    an estimate", ai_agents/spend.py:9-12);
  - a call cut before any response has no usage to book;
  - a call that raises after a response carries `.usage`, and that cost is
    booked ("Usage FIRST, before any verdict", claude_provider.py:494-503;
    base_agent.py:177-202);
  - a `build_request` ValueError sends nothing;
  - so $0 for a no-response timeout, with the reservation released, is the
    ledger's honest reading, not a bug.
- **Required anyway**, because the cost lens will ask:
  - a failure books whatever usage it carries;
  - a no-usage failure is journaled `error` and counts toward the Orc's day
    wake count, so P5's count cap bounds a timeout storm even when the dollars
    read $0;
  - the reservation is released at the settle, never before;
  - every rung has an explicit `timeout_s` and `max_tokens`. A thinking model's
    default bound is 32,000 tokens (claude_provider.py:53-73; map_wakes.md trap
    27).
- [derived] A breaker pauses dispatch on the line after N no-usage failures in
  a row within M minutes, and `orcs status` shows it. DECIDE N and M.
- Proof: a fake provider that raises a timeout →
  - $0 booked;
  - one wake counted;
  - `error` journaled;
  - the reservation released;
  - after N such timeouts, dispatch pauses with a code.

### A.3 The queue and the care

**P9. The stall clock runs from the first send.** *(F2 minor/safety; F19
minor/spec; F34 minor/tests; Fix 3)*
- `first_enqueued_at` is set once, at the first send, and a re-send never
  changes it. A re-send after a lost broker message may update a separate
  `last_sent_at`.
- The stall check (the lost `census_stalled`) alarms when a pending wake's
  `first_enqueued_at` is more than 20 minutes old (the recovered threshold),
  however many re-sends happened.
- A worker's claim (pending → running; `started_at`, models.py:171) resets the
  stall clock. From then on, the call's own timeout judges the wake.
- Proof: re-send every 5 minutes (and every 2 minutes, the render pass's
  cadence, config/celery.py:512-516); the stall still fires at 20 minutes.

**P10. A sent wake that waits too long is closed as stale, and the care takes
the idea.** *(Fix 3)*
- A pending wake whose first send is more than 30 minutes old (the recovered
  value) is closed `stale` instead of re-sent.
- If it had been sent, it waited for a worker, so the care takes the idea:
  state `care_owned`, reason "the worker did not answer", and a takeover fact
  as in P13.
- The thresholds keep their order: the stall alarm (20) comes before the stale
  close (30).
- A wake never sent is P14's case, not this one.

**P11. The silence check counts only wakes that waited for a worker.** *(F3
minor/safety; F14 important/spec; F30 minor/tests; Fix 4)*
- Counted: pending, running, failed (a worker error) and closed stale.
- Never counted:
  - wakes answered by code (quiet, `day_cap`, triage, spacing, switch off, line
    off, over_budget);
  - merged, unbudgeted or dead wakes;
  - a closed row;
  - a render failure (`components.render = "failed"`, wake.py:793-831), which
    never reached a worker.
- Only the counted wakes may send the Orc to the care as "the worker may be
  down".
- Proof:
  - a full day of routine wakes answered by code leaves the Orc `active`;
  - N waited and unanswered wakes send it to the care.

**P12. The spacing is checked again at the claim.** *(F5 minor/safety;
Fix 5)*
- In `run()`, under the Orc's lock, a non-urgent wake needs
  `MIN_WAKE_SPACING_MIN = 15` minutes (constants.py:257) since the Orc's last
  model call. Otherwise code answers it, with code `spacing`.
- Today the spacing is checked only at detection, against
  `seen["last_recorded"]` (wake.py:386-393).
- DECIDE the reference time. Recommend the last claimed model wake, not the
  last recorded detection.
- An urgent wake is exempt.
- Proof: two routine wakes admitted 5 minutes apart → the second is answered by
  code at the claim.

**P13. Only a wake that read the takeover brings an Orc back from the care.**
*(F16 minor/spec; Fix 6, whose text ends at "through a wake r")*
- Entering `care_owned` writes a takeover journal entry that is a code FACT:
  - author `code`, an F-id, and `body["fk"] = "care"`;
  - `fence.fact_kind` reads `fk` first (fence.py:117-130), so the entry is a T0
    care fact;
  - fixed English words name the reason code.
- It sets `state = care_owned` (constants.py:12), `care_owned_reason` and
  `care_owned_at` (models.py:110-111). The words "Stood aside: the care holds
  this position." already exist (notes.py:143).
- The Orc returns to `active` only through a validated answer whose wake
  carried that fact in PS5 and whose decision cites its id.
  - V10's plan rule accepts any T0 fact newer than the plan
    (constants.py:240), and a care fact is one.
  - Write a `return` journal entry (constants.py:25).
- A good wake that did not carry the fact leaves the Orc `care_owned`.
- [derived] While the Orc is `care_owned`, PS5 pins the takeover fact even when
  it has scrolled out of the last 12 facts (`PS5_FACTS = 12`, dossier_position.py:39; `_ps5`, :176-184).
- In shadow, `care_owned` changes nothing the care does: the care always holds
  the row in O2.
- Proof:
  - after a takeover, a valid answer that omits the fact leaves the Orc
    `care_owned`;
  - a valid answer that cites it returns the Orc to `active`.

**P14. A deferred wake is not killed by the clock that guards sent wakes.**
*(F23 minor/spec; no surviving fix)*
- A wake held back by a burst control, or by triage waiting for budget, has no
  first send. The stall alarm and the 30-minute stale rule do not apply to it.
- When it is finally sent:
  - if its dossier is older than a freshness bound, it is rendered again as of
    the send. DECIDE the bound; recommend the render cadence, and I10's 120 s
    for the tail's mark;
  - or it is merged into the Orc's next wake (status `merged`).
- It is never closed as stale just for waiting its turn, and never counted as
  silence (P11).
- DECIDE the burst rule itself; its text was lost (map_wakes.md §2.1). A
  real-money urgent wake is never deferred by a burst.
- Proof: a burst defers 20 wakes for 40 minutes → each is sent or merged; none
  is skipped as stale; none counts as silence.

**P15. The urgent flag is recomputed when a newer wake absorbs an older one.**
*(F26 minor/spec; no surviving fix)*
- On absorb, the surviving wake takes:
  - the higher priority and urgency of the two;
  - the union of both wakes' reasons.
- Triage, the spacing exemption and the ceilings read the survivor after the
  merge, never a flag frozen before it. Today `priority` is frozen at the
  record (wake.py:659).
- Trap: `dedupe_key` carries a timestamp to the second (wake.py:657-658), so
  the one-pending-per-key constraint (models.py:180-185) never merges two wakes
  of one Orc on its own. The merge must be explicit, under the Orc's lock.
- Proof: a newer routine wake absorbs an older urgent one → the survivor is
  urgent and skips the spacing.

**P16. The row and the Orc are read again after the call.** *(F35
minor/tests; no surviving fix)*
- After the model answers, under the Orc's lock, check again:
  - the row is still OPEN or CLOSE_PENDING (wake.py:82);
  - the Orc is not dead;
  - the switches are still ON.
- If the row closed or the Orc died during the call:
  - book the cost (P2);
  - journal the decision as late, with code `row_closed` or `dead`;
  - write no intent, no plan, no `last_good_wake_at` and no state change.
- Proof: close the row inside the fake provider's call → only the booking and
  the late entry are written.

**P17. What sends an Orc to the care is stated and counted on causes the model
owns.** *(derived from F7's consequence: "two such refusals send the Orc to the
care")*
- The causes are:
  - N consecutive refusals of the model's own output by the validator or the
    officer (the recovered N is 2; DECIDE);
  - silence (P11);
  - a sent wake closed stale (P10).
- Budget, cap, spacing, triage and switch answers are never refusals.
- A refusal caused by a counter bug cannot be told apart at run time, so P19's
  window must be right.
- A good wake resets the refusal count.

**P18. The new statuses fit the column.** *(derived trap)*
- `OrcWake.status` is `CharField(max_length=12)`, default "pending"
  (models.py:166). Every new status fits 12 characters (for example pending,
  running, done, failed, stale, merged, refused, code).
- Codes live in `skipped_reason` (200 characters, models.py:170).
- Allowed values are tuples in constants.py, never model `choices`
  (constants.py:1-3). `STATUS_WORDS` (constants.py:356-357) gains a sentence
  for each.

### A.4 The validator

**P19. Rule 2 counts plan changes inside the last 24 hours only.** *(F7
important/spec; F31 minor/tests)*
- `plan_changes_24h` is a JSON list (models.py:85). Store each change's time.
  Drop entries older than 24 hours on every read and write, and count what
  remains.
- A change older than 24 hours never refuses a plan.
- DECIDE the limit. The recovered rule: after two changes, every later
  non-urgent plan change is refused. Urgent wakes are exempt.
- Proof:
  - two changes 25 hours ago → a routine plan change passes;
  - two changes inside 24 hours → the third non-urgent change is refused, with
    a refusal entry.

**P20. V10 refuses, is journaled, and is counted.** *(F10 important/spec)*
- A V10 failure (`fence.v10_satisfied`, fence.py:169-204):
  - writes a `refusal` journal entry: author `code`, rule "V10", fixed words;
  - records the intent with mode `refused` (constants.py:388);
  - counts in `OrcGrade.n_refused` and in the invalid-output rate
    (models.py:276-281).
- V10's failure text ends "advisory to the phone" (fence.py:202-204). The
  validator's refusal needs its own words.
- The same path holds for every validator and officer check (P19-P24;
  map_wakes.md §2.4 b). No check fails silently.
- Proof: an exit that cites only a drum fact on another symbol → refused,
  journaled and counted.

**P21. V6: an exit or trim with the thesis intact needs the level reached.**
*(F11 important/spec; F33 minor/tests)*
- Define V6 again (its text was lost). An exit or trim made while the thesis is
  intact (no invalidation met, no thesis-check exit) must cite a
  `level_reached` fact for the level it names.
- Naming a pool or a target the price has not reached does not satisfy V6.
- ADD the producer. No code writes `fk: "level_reached"` today: the kind exists
  only in `FACT_KINDS` (fence.py:33-37), and only drum facts set `fk`
  (drum_bus.py:675).
  - Write it by code when the closing-side mark (wake.py:178-197), or a final
    bar of the decision frame, trades through a menu level.
  - Once per level, as a T0 fact with an F-id and the level id.
  - DECIDE which level kinds count: pools, swings, round numbers.
- Proof:
  - an intact exit naming an unreached P1h-H1 is refused under V6;
  - after the `level_reached` fact, the same exit passes.

**P22. No amount of money survives into an Orc's stored or shown words.** *(F4
minor/safety; F32 minor/tests)*
- The validator's money filter is the platform's one filter:
  `plain.voice(text, row_marks(row))` → `dashboard/plain_words.scrub`
  (bot_program/orcs/plain.py:19-42; dashboard/plain_words.py:121-186).
  - It keeps a line whole or withholds it whole, never cut.
  - Apply it ONCE, at write time. That is before any of these can hold the
    text: `latest_note`, the journal, the card, the pages, Telegram, or the
    next dossier's PS5.
- The lost filter missed "common forms". Measured against today's platform
  patterns (probe:
  `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/orcs2/calc/money_forms.py`):
  - **These pass unwithheld today:**
    - "P/L -350": `MONEY_WORD` knows P&L and PnL only (plain_words.py:73-79);
    - "up 1,200 today", "down 300 since entry", "made 450 on the trim": up,
      down and made are not money verbs (:86-89);
    - "unrealized -350", "floating -350";
    - "the account is at 12,500";
    - currency codes outside `_CODES` (:40): "NZD 500", "500 NZD", "500 SEK",
      "AED 2,000", "HKD 800", "ZAR 900", "MXN 1500";
    - "2 grand", "1.2k on the table", "a 1.5k swing";
    - "fifty thousand", "half a million".
  - **These are already withheld:** "$350", "350 USD", "EUR 1,200", "PnL -350",
    "lost 450", "worth 1,250", "gain of 640", "500 dollars", "350€".
  - **A false positive on the safe side:** a level written with grouping and
    two decimals, such as "trim at P1h-H1 (2,650.50)", is withheld
    (`MONEY_FIGURE`, :93).
- Widen the platform filter itself, never a private regex, so every surface
  judges a line alike. Pin it with a table-driven test of these forms.
- S tells the Orc to name levels by menu id (menu.py:15-18) and amounts in R
  only. The plan's prices are rendered by code (notes.py:507-510, through
  `format_price`).
- Proof: each form, in a fake answer's note, reaches none of the card, the
  page, Telegram or the next PS5.

**P23. A validated next_wake is kept and honored.** *(F22 minor/spec)*
- Validate it:
  - no sooner than `MIN_WAKE_SPACING_MIN`;
  - no later than a bound. DECIDE; recommend `W11_METRONOME_H` × 2 or 24 hours;
  - a time when the market is shut moves to the reopen.
- Write it to `Orc.next_wake_due` (models.py:101). Today that column holds the
  metronome only (wake.py:667-690).
- Detect it as a reason. DECIDE a new code or a W11 key (map_wakes.md §2.1 i).
- An invalid next_wake is a refusal entry, never a silent drop.
- Proof: the answer asks for +40 minutes → a wake is detected at +40 minutes.

**P24. Plan clauses against allowed_actions, F5, C14 and the type's
risk_share.** *(F12 important/spec, judged FALSE)*
- **Why it was judged false** (inferred; the reasons were not preserved):
  - a plan clause is not an action. It becomes an intent only when it fires,
    and in O2 nothing binds (every seat is L0; notes.py:287-290);
  - when a clause fires, the validator and the officer check it against the
    allowed actions with F5 (integrity.py:102-133), the army type's
    `risk_share_max` (army.py:35-54) and the rest;
  - integrity.py:12-14 already says "the armed clauses run as code and the care
    stands in";
  - C14 is defined nowhere that survives.
- **Required so the finding cannot come back.** The spec says where each check
  runs:
  - at plan time, a structural check: each clause's kind is in the Orc's
    vocabulary (`L0_ALLOWED`, integrity.py:34-35, plus the would-mode kinds),
    and every level id resolves on the menu (`menu.level_by_id`,
    menu.py:293-300);
  - when the clause fires, the full validator and the officer in would-mode
    (P30-P33).
- A test proves that a fired clause breaching F5, or the type's risk_share, is
  refused or cut at that moment.
- Restate C14 in the new spec, or drop the name.

### A.5 The dossier and the prompt (and the wake inputs they depend on)

**P25. PS3 shows the newest decision's expectation and its result.** *(F8
important/spec)*
- The lost build showed the result of the expectation from two decisions ago,
  an off-by-one.
- PS3 (dossier_position.py:38, :293; today `PS3_WORDS`) holds:
  - the current plan, rendered by code;
  - its version;
  - the LAST decision's expectation and its result: hit, missed or pending.
- Proof: three decisions with known outcomes → PS3 shows the third one's.

**P26. PS5 carries the last 6 decisions with their outcomes, and the
refusals.** *(F9 important/spec)*
- PS5 (dossier_position.py:176-184; dossier.py:409-410) has `notes = []` today.
  It gains:
  - the last 6 decisions: time, action, cited ids, expectation, outcome;
  - every refusal since the previous wake, from the validator and the officer,
    with the rule id and fixed words.
- These are fenced as T1 views (fence.py:7-9; `FENCE_CAPS["mind"]` = 300) and
  trimmed third in `TRIM_ORDER` (`ps5_notes`, constants.py:304).
- Everything in PS5 has passed P22 at write time.
- Proof: a refusal at wake N appears in wake N+1's PS5.

**P27. The quiet-wake facts hash covers the plan version.** *(F20
minor/spec)*
- `facts_hash` (wake.py:123-138) adds the plan version. DECIDE whether it also
  adds the plan's watched level ids. Then a wake after a plan change is not
  judged quiet (F6) on facts no model saw.
- [derived, map_wakes.md trap 3] F6 compares against the hash of the last
  VALIDATED answer, `Orc.last_facts_hash` (models.py:102). It never compares
  against the render-time proxy `seen["answered_hash"]` (wake.py:761-763). So a
  wake refused for budget never makes the next metronome quiet.
- Proof: the same market facts, with the plan going v1 → v2 → the wake is not
  quiet.

**P28. W3 watches the plan's levels.** *(F21 minor/spec)*
- W3 (wake.py:200-229) reads only the thesis's `close_beyond` levels.
- Add the plan's trim and add-trigger levels, written to `Orc.watches`
  (models.py:94). They follow the same `W3_NEAR_ATR1H` and
  once-per-level-per-`W3_ONCE_H` rule (constants.py:325-328).
- Proof: a plan trim level at P1h-H1 → the mark within 0.1 × ATR(1h) wakes the
  Orc.

**P29. S may say "nothing binds" and "graded against the mechanical care".**
*(F17 minor/spec, judged FALSE)*
- **Why it was judged false** (inferred): both claims are true in O2.
  - PS1 already says "L0 shadow" (dossier_position.py:72), and every seat is L0
    (ranks.py:10-18).
  - The O arm is graded against the care ghost (ghost.py:6-10;
    constants.py:157). The Book says the same ("grades them against what the
    care alone would have done", core/book_content.py:588-590).
  - The fence's doctrine is that facts win and the Orc is told the truth
    (fence.py:4-13).
- **Required:**
  - S states the Orc's authority from the same source as PS1;
  - S is versioned and stored as a dossier block (dossier.py:5;
    `S_TOKENS_RESERVE = 3930`, constants.py:299-300), so a replay prints it;
  - each decision records S's version, so grades taken under "nothing binds"
    are never pooled with grades taken once something binds (O3);
  - a test pins S's authority sentence to the code: S may say "nothing binds"
    only while no seat is above L0.

### A.6 Would-mode arithmetic (the officer)

**P30. I12 counts in would-mode.** *(F15 important/spec)*
- I12's counters `steps_today`, `bars_since_add` and `bars_since_trim` have no
  writer.
- Keep them from the Orc's own shadow acts accepted in would-mode, never from
  the care's real acts.
  - Store them on the officer's state.
  - Reset `steps_today` at the trading-day roll (constants.py:371).
  - Advance the bar counters on each final bar of the decision frame.
- Restate I12's limits in the spec (they were lost).
- Proof: shadow tightens beyond the day's limit → the officer's verdict reads
  "would be refused (I12)".

**P31. Would-mode follows §2.2.** *(F24 minor/spec)*
- Restate §2.2 from what survives:
  - `MAX_ADDS 2`, `RISK_SHARES`, `ADD_PRE_SHUT_H`, `EVENT_WAIVER_FLOOR_R` and
    `GAP_MIN_SAMPLES` (constants.py:69-74);
  - `GROSS_MAX_R 2.0` (constants.py:381-383);
  - the gap waiver (gaps.py:74-91);
  - the type's parameters (army.py:35-54).
- Fix the four lost deviations:
  1. **I3c counts costs**: the round trip and the exit's spread, as the menu's
     BE row does ("the entry plus its round trip", menu.py:26-27).
  2. **I4 CUTS an add to fit** and refuses only below a minimum size. DECIDE
     that minimum.
  3. **The exit cost is counted at the stop.**
  4. **Prior losses are counted**: the idea's realized losses from trims and
     closed legs. Today PS4's "loss" is a hard-coded +0.00R
     (dossier_position.py:169).
- Proof: each rule, with numbers in R.

**P32. C17: a queued shadow exit goes stale.** *(F18 minor/spec)*
- An intent waits for the first tick after its validation. One writer per
  phase: the tick while the row is open, the beat once it has closed
  (ghost.py:38-42; deploy/RUNBOOK.md:1423-1425).
- It carries `expires_at`. DECIDE the TTL; recommend I10's mark freshness
  (`MARK_MAX_AGE_S = 120`, constants.py:258), or the tick's cadence.
- It is applied to the O arm only if both hold:
  - that tick comes before it expires;
  - the integrity verdict at that tick is not critical for its kind.
- Otherwise it is marked expired and journaled, and the O arm keeps the care's
  path. It is never simulated at a later price, such as a reopen gap.
- Restate C17 in the spec (it was lost).
- Proof: an exit validated at Friday's close → expired at the Monday reopen,
  not filled at the gap.

**P33. The O arm's shadow stop is the menu's stop beyond the crowd.** *(F28
important/tests)*
- An Orc that names a level gets that level's `stop`, never the raw level
  `price`. The `stop` is pushed beyond the crowd and snapped to the
  instrument's precision (`menu._stop_for`, menu.py:111-126).
- The playbook's T-STRUCT already does this (playbook.py:68-98; line 88 takes
  `latest["stop"]`).
- The O arm and the playbook arm are then graded on the same stop for the same
  level.
- Proof: the Orc and T-STRUCT both name S1h-L1 → the two arms hold the same
  stop.

### A.7 Commands

**P34. Every command that sends a model call goes through the wake path's
gates.** *(F6 minor/safety; F27 minor/spec)*
- The lost `orcs record --yes` had three faults:
  - it took any rung from a scenario file (r5 called Fable with a $2 bound);
  - it never asked `can_spend`;
  - it ran with the switch OFF.
- That command, and `orcs smoke --row` ("§10.2's `orcs smoke --row` (O2)",
  ai_agents/management/commands/claude_smoke.py:33), must:
  - be dry by default, printing the plan and the bound;
  - refuse `--yes` while the `orcs` switch or the minds switch is OFF;
  - take only rungs of `ORC_LADDER_V1` (ai_agents/catalog.py:505-520) allowed
    in O2a. DECIDE: the fixed rung, plus h0. A scenario file never names a rung
    outside them;
  - ask `can_spend(line="orcs", tier=<the rung's tier>, estimated_usd=<the
    whole run's bound>)` before the first call, as `claude_smoke` asks for its
    own bound (claude_smoke.py:521-555);
  - bill to the Orcs line (P2).
- List the commands on the ops page (core/ops_commands.py:140-152) and in the
  RUNBOOK.

**P35. Fable from `orcs record` in O2.** *(F36 minor/tests, judged FALSE)*
- **Why it was judged false** (inferred):
  - r5 is Fable by design ("extreme, gate passes; real money only, under a
    quota", ai_agents/catalog.py:518-519);
  - an operator's tool may reach Fable behind an explicit flag, as the smoke
    does (`--with-fable`, claude_smoke.py:37; deploy/RUNBOOK.md:1324);
  - calling Fable is not itself the defect. The defects were the unbounded rung,
    the missing `can_spend` and the OFF switch, all confirmed under P34.
- **Required:**
  - Fable is reachable from a command only behind an explicit flag, and only
    through P34's gates;
  - Fable is never reachable from the O2a wake path. r5 is reached only through
    O2b's router and the frontier quota (`FRONTIER_PER_DAY`, weather.py:33).

### A.8 Tests

**P36. The zero-call proof must be able to fail.** *(F37 minor/tests)*
- The lost `NoCallProvider` raised an assertion inside the code under test, and
  the assertion was swallowed. Every Orc step is fenced by `except Exception`:
  - each tick step (observe.py:104-109);
  - each wake of the render pass (wake.py:793-831);
  - a dispatcher fences each wake the same way.
- The fake provider therefore records every call into a list the test owns, and
  the test asserts on that list AFTER the code has run. This is the O1 pattern
  at tests/orcs/test_orc_seen_off.py:329-366.
- A no-network guard is applied to every O2 test module. The lost
  `NoNetworkMixin` was never used.
  - Patch `requests.Session.request`, `requests.get` and `requests.post`,
    `ClaudeProvider.complete`, the anthropic client and socket connect.
  - A meta-test proves that every TestCase in the O2 modules inherits the
    guard.
- Every zero-call branch is executed, because two branches of the lost proof
  never ran.
  - The branches: switch OFF, line at 0, day cap, triage, spacing, dead Orc,
    row closed, over_budget, quiet, merged and stale.
  - Each branch's code is asserted, with an empty call list.

**P37. No vacuous assertion.** *(F38 minor/tests)*
- Each test asserts a specific value that the change produces.
- Each test is red first: run it on the base, see it fail, and record that.
- Banned forms:
  - `assertTrue` on a constant;
  - membership in the list the test just built;
  - `len(x) >= 0`;
  - asserting a mock the test itself called;
  - an `assertRaises` around code that never runs.

**P38. End to end through the mind, for every world and both menus.** *(F39
minor/tests)*
- The chain: detection → render → admission → claim → fake model → validation
  → plan and intents → the O arm's step → the grade.
- Run it for:
  - a real-money bot row;
  - a manual (hand ticket) row;
  - an eToro demo row;
  - a paper row.
- Use a menu without F5, where exits and trims are allowed, and one with F5.
- Assert:
  - no AssetBotTrade write beyond `metadata["orc"]`;
  - no order or stop call;
  - the booking on the Orcs line;
  - the day counters.

**P39. Every requirement has its test, red first, with a fake model.**
*(house principle)*
- No test makes a live call (P36).
- The O1 boundary pins change on purpose, never by deletion (map_wakes.md
  §2.7). These must stay green as they are:
  - tests/test_ai_spend_lines.py (the line off at 0);
  - tests/test_model_catalog.py:456-525 (no model id outside the catalog);
  - tests/orcs/test_orc_notes.py:37-43 and :498-521 (no money key, no Orc
    verb, a mode on every outcome).
- Each tests-lens finding that repeats a spec finding (F29-F35) is proven by
  the test of the requirement it maps to (table A.10).

### A.9 Process (from the recovered build)

**P40. Push every commit; commit the way the house commits.**
- The lost O2a was never pushed and died with the container. The rule since
  the reset is to push each commit as soon as it exists.
- Commit through the commit tooling, which recounts `TESTS_GREEN` from the
  index. That count is shown on the Wall (core/wall_facts.py:52, :81; today
  14527).
- Use the two trailers exactly, and no model id in the body.
- Do not commit stray churn in core/wall_facts.py. The lost build restored it
  after its commit (REC:7).

### A.10 Traceability: every recovered finding and fix

| F | Finding (short) | sev / lens | real | → P |
|---|---|---|---|---|
| F1 | routine wake ignores the day's wake count and dollar cap (per-Orc "D18") | important / safety | yes | P5 |
| F2 | `dispatch_due` re-stamps `enqueued_at` every 5 min; no stall seen | minor / safety | yes | P9 |
| F3 | silence counts code-answered and skipped wakes; false takeovers | minor / safety | yes | P11 |
| F4 | money filter misses common forms; reaches card, page, PS5 | minor / safety | yes | P22 |
| F5 | 15-min spacing decided at admission only, never at claim | minor / safety | yes | P12 |
| F6 | `orcs record --yes` takes any rung (r5 Fable, $2), never asks can_spend | minor / safety | yes | P34 |
| F7 | rule 2 counts plan changes older than 24 h; two refusals → care | important / spec | yes | P19, P17 |
| F8 | dossier shows the expectation result from two decisions ago | important / spec | yes | P25 |
| F9 | PS5 lacks the last 6 decisions; officer's refusals never reach the model | important / spec | yes | P26 |
| F10 | V10 writes no refusal; not in the invalid-output rate | important / spec | yes | P20 |
| F11 | V6 passes an intact exit naming an unreached pool; no level_reached fact | important / spec | yes | P21 |
| F12 | plan clauses not checked against allowed_actions, F5, C14, risk_share | important / spec | **no** | P24 |
| F13 | triage inverted: paper urgent can spend the reserve; live routine stops at 60% | important / spec | yes | P6, P7 |
| F14 | silence sends the Orc to the care after a code-answered routine wake | important / spec | yes | P11 |
| F15 | I12 never counts: steps_today, bars_since_add/trim have no writer | important / spec | yes | P30 |
| F16 | a good wake returns from care_owned without reading the takeover | minor / spec | yes | P13 |
| F17 | S claims "nothing binds" and "graded against the mechanical care" | minor / spec | **no** | P29 |
| F18 | queued shadow exits simulated without C17's staleness | minor / spec | yes | P32 |
| F19 | re-enqueue every 5 min defeats the 20-min queue stall | minor / spec | yes | P9 |
| F20 | quiet-wake facts hash omits the plan version | minor / spec | yes | P27 |
| F21 | W3 ignores the plan's trim and add-trigger levels | minor / spec | yes | P28 |
| F22 | the validated next_wake is dropped | minor / spec | yes | P23 |
| F23 | a burst-deferred wake held > 30 min is always skipped as stale | minor / spec | yes | P14 |
| F24 | would-mode differs from §2.2: I3c costs, I4 cut, exit cost, prior losses | minor / spec | yes | P31 |
| F25 | a timed-out or errored call booked at $0, reservation released | minor / spec | **no** | P8 |
| F26 | frozen urgent flag taken before a newer wake absorbs an older urgent one | minor / spec | yes | P15 |
| F27 | `orcs record --yes` calls the model with the switch OFF | minor / spec | yes | P34 |
| F28 | shadow stop is the raw level, not the menu's stop beyond the crowd | important / tests | yes | P33 |
| F29 | routine wakes ignore the day totals: a 13th wake, dollars past per_orc_daily_usd | important / tests | yes | P5 |
| F30 | silence counts a run-time code answer as a due model wake | minor / tests | yes | P11 |
| F31 | rule 2 counts yesterday's changes, then pushes the Orc to the care | minor / tests | yes | P19 |
| F32 | money redaction misses forms; the note carries the amount on | minor / tests | yes | P22 |
| F33 | V6 bypassed by naming any pool level on an exit | minor / tests | yes | P21 |
| F34 | queue-stall census never fires while the render pass re-enqueues | minor / tests | yes | P9 |
| F35 | an Orc whose row closes during the call still gets an intent, a plan, last_good_wake_at | minor / tests | yes | P16 |
| F36 | `orcs record --yes` can call Fable in O2 | minor / tests | **no** | P35 |
| F37 | zero-call proof weak: assertion swallowed, NoNetworkMixin unused, two branches never run | minor / tests | yes | P36 |
| F38 | several assertions vacuous | minor / tests | yes | P37 |
| F39 | no e2e test with a real-money or manual row, or a non-F5 menu | minor / tests | yes | P38 |

| Fix | What survives (REC:7) | → P |
|---|---|---|
| 1 | routine wake answered by code once the day's whole wake count or dollars are used, even by urgent wakes (`day_cap`) | P5 |
| 2 | paper urgent stops at 60% of the Orcs line; order real urgent, real routine, paper urgent, paper routine | P6 |
| 3 | stall clock from the first send (`first_enqueued_at`); > 30 min closed stale, not re-sent; if sent, the care takes the idea; a worker's claim resets the clock | P9, P10 |
| 4 | silence counts only wakes that waited for a worker (pending, running, failed, closed stale); never code-answered, merged, unbudgeted or dead | P11 |
| 5 | spacing checked again in `run()` for non-urgent wakes | P12 |
| 6 | the takeover is a code fact of kind care; an Orc comes back from the care only through a wake r[...] (cut here) | P13 |
| 7-26 | lost | the P derived from each finding's own words |

---

## Part B. What the platform promises the operator about the Orcs

Each promise has an id, its words, its place, and what O2 must do with it.
- **K**: it must stay true through all of O2.
- **U**: its words become false, or stale, when O2 lands or when the minds
  switch and the line are ON. The usual cure: the words read the switch and the
  line, and stay true while both are OFF (map_wakes.md §2.8).
- **D**: O2 must deliver what the words promise.

"Guard" names the test that pins the words. A guarded line is changed by
changing its pin on purpose.

### B.1 The Book (core/book_content.py)

- **K-B1** "nothing an Orc writes sends an order or moves a stop"
  - Where: the chapter "The Orcs" (:591-592) and the 23 October milestone
    (:1548-1549).
  - Keep it in every commit of O2.
- **U-B2** "No model is called" (chapter, :591) and "It calls no model and
  sends no order." (lexicon "Orc", :1740-1744)
  - These become false once the minds switch and the line are ON.
  - Rewrite them conditionally, for example "with a second switch on and its
    budget line set, it reads its dossier with a model, in shadow".
  - Keep "sends no order".
  - Guard: tests/test_the_book.py:2164-2180, which pins "one open idea, its
    legs together" in the lexicon entry and the chapter's opening words.
- **K-B3** "An Orc is a journal whose every fact is written by code, in prices
  and R" (chapter, :584-586)
  - Model text is a note, a plan or an intent. It is never a fact: no F-id.
  - The plan's prices are rendered by code.
  - The owner's thesis stays "in their own words" (pinned by
    tests/test_the_book.py:2181-2192).
- **K-B4** "code replays a few other ways of managing the same idea and grades
  them against what the care alone would have done" (chapter, :588-590)
  - The O arm, with its shadow intents, is graded against the care ghost.
  - This is also why F17 was judged false (P29).
- **K-B5** "every real-money idea, and by default up to ten at once in
  simulation and demo together" (chapter, :582-584; milestone, :1545-1546)
  - `MAX_PAPER_ORCS = 10` stays.
  - Guard: tests/test_the_book.py:2004-2005.
  - The budget triage (P6) must not change who gets an Orc. It decides only who
    thinks first.
- **D-B6** The bench, `IN_PROGRESS` "The Orcs' shadow minds" (:1600-1606)
  - The words: "gives each Orc a model that reads that dossier when it wakes,
    in shadow, on an AI budget line of its own that stays at zero until then."
  - Deliver exactly that: the model reads the stored dossier, in shadow, on the
    Orcs line, and the line ships at zero (P2).
  - On landing, the line moves to `MILESTONES` with its hash, and the bench
    kicker says the bench is empty.
  - Guards: tests/test_the_book.py:2223-2238 (it reads "from O2" in the
    `orcs_drums` description as the tripwire), :1620-1628 and :2320-2327.
  - DECIDE when the line moves: at the PR's merge (all four commits), or at
    O2a. Recommend the merge; the bench names the whole second release.
- **K-B7** The lexicon "Shadow": "A part that records what it would do, and is
  graded on it, while nothing that trades reads what it writes." (:1724-1726)
  - Nothing that trades may read `Orc.plan`, an intent or a note (P3).
- **K-B8** Every switch called "off on arrival" ships off, and `orcs` is not a
  live-money switch.
  - Guard: tests/test_the_book.py:1650-1670 ("moves money now: rewrite 'The
    council', 'The Orcs' and the lexicon's 'Shadow'").
  - Add every new O2 switch to that test's named list.
  - None of them joins `LIVE_MONEY_SWITCHES` in O2.
- **K-B9** The dated lines stay as dated
  - The 23 October milestone, the October timeline ("the Orcs' journals in
    shadow", :129, :813) and the era summary (:1017) are not rewritten.
  - O2 adds a new milestone. It says what stands, never "no longer", "was
    handed", "used to carry" or "once carried" (tests/test_the_book.py:2240-2250).
- **K-B10** House precedent: the reviewer is "given no account figure", walked
  key by key (tests/test_the_book.py:2253 onward, `TheReviewerIsGivenNoAccountFigure`).
  - Give the Orc's request the same walk: every system, shared and private
    block, keys and values.
  - The RUNBOOK already promises "the position (in R only, never money)"
    (U-R13).

### B.2 The Wall (templates/landing/the_wall.html)

- **K-W1** "AI never sends an order." (:2324)
  - The Orcs' models never send one (P3).
- **K-W2** "Specialised agents powered by Claude, each on the model tier its
  work calls for, from the fastest to the frontier" (:2321)
  - O2a's fixed rung and O2b's router keep this true.
- **U-W3** The Horde card
  - Its words: "With their switch on, the Orcs sit in its seats in shadow, each
    a journal of one open idea whose every fact is written by code, beside a
    thesis its owner may add in their own words." and "Each open idea the
    platform looks after, options aside, gets one: every real-money idea, and
    by default up to ten at once in simulation and demo together." (:3175-3176)
  - With minds ON, these are still true but incomplete. Add one conditional
    sentence on the shadow mind.
  - Guard: tests/test_the_wall.py:1204-1226 pins both sentences verbatim;
    change the pin on purpose.
- **K-W4** The Wall's counts are real.
  - `TESTS_GREEN` (core/wall_facts.py:52) is recounted at commit (P40).
- **K-W5** House precedent: Horizon's two promises (:4108-4109).
  - "The row is written before the model is called, so a provider outage is an
    error row, never a silent gap."
  - "A garbled answer is kept and marked rejected ... but it is never treated
    as a view."
  - Match them for the Orcs: the OrcWake row exists before the call, and an
    invalid answer is kept, journaled as refused, and never becomes a plan.

### B.3 The RUNBOOK (deploy/RUNBOOK.md)

"The AI budget lines and the provider smoke" (:1272-1356)

- **U-R1** "Nothing about today's spending changes until the Orcs arrive (O2)"
  (:1274-1275) and "It stays `0` until O2" (:1285)
  - The line still ships at 0 after O2.
  - Say how the operator turns it on: `.env` `ORC_DAILY_BUDGET_USD`, then
    `./deploy/dc up -d`.
  - Say that the minds switch is a second, independent gate.
- **K-R2** "At `0` (the default) the line is off: no Orc call is allowed and
  nothing is held back for them." (:1283-1285)
  - Also: "The cap holds even with `AI_DAILY_BUDGET_USD=0`" (:1285-1288).
  - See P2.
- **K-R3** The core line is "the total minus what the Orcs have actually spent
  today minus a $3 floor kept for their live urgent wakes. The deep and
  frontier tiers stop at 70% of a line's live allowance" (:1289-1293)
  - Keep it.
  - Only live urgent and confirm wakes may pass `deep_share_exempt` (D30;
    spend.py:34-36).
- **K-R4** "Both variables are read when the containers start" (:1295-1300)
  - Every new env variable in O2 follows this rule.
  - OrcSetting keys bind at once. Say which kind each new knob is.
- **K-R5** The TODAY cell's two forms (:1302-1306) stay word for word
  (`spend.lines_summary`, spend.py:297-325).
- **U-R6** "The card 'The Orcs (read-only)' ... read by the router from O2; no
  tier setting on this page ever moves it, and no override can be saved for an
  Orc agent name." (:1308-1312)
  - Keep: no override, and tier settings never move it.
  - Update: say which rung O2a uses, and that O2b routes in shadow.
- **K-R7** The smoke's pattern: "dry by default", and "`--yes` ... refuses when
  the day's budget would not cover the bound" (:1319-1335)
  - Every new sending command follows it (P34).
- **K-R8** The smoke's FAIL verdict: "the Orcs' router must change model and
  effort per epoch, never per wake" (:1346-1348)
  - O2a's cache layout and O2b's router honour the smoke's recorded verdict.
  - The spec must say which verdict it assumes.

"The Orcs (O1: journals, no model)" (:1360-1723)

- **U-R9** The heading (:1360), and "**No model is called, no order is sent and
  no stop is moved.**" (:1368-1369)
  - Becomes: a model is called in shadow, behind the minds switch and the line;
    no order is sent, no stop is moved.
  - The O1c and O1d paragraphs repeat "(still no model)" (:1414, :1494, :1497,
    :1637, :1647). Update each one, or say "O1" plainly.
- **K-R10** "The Orcs write their own tables and one stamp on the trade row
  (`metadata["orc"]`), nothing else." (:1369-1370)
  - See P3.
- **K/U-R11** "OFF on arrival ... While it is OFF the platform behaves exactly
  as before ... It is not a live-money switch, so the System group's 'all on'
  turns it on with the rest." (:1372-1376)
  - Every O2 switch ships OFF.
  - DECIDE whether "all on" arms the minds switch. map_wakes.md recommends
    `BULK_ENABLE_EXEMPT` (core/platform_control.py:126-127), because it spends
    dollars. The RUNBOOK must say which.
- **K-R12** Adoption lines go to "its owner's own channel (never the alarm
  group) ... Quiet hours apply" (:1394-1397)
  - O2a sends no new notification.
  - Any later notification follows the same rules.
- **K-R13** "at most 10 Orcs outside real money ... An eToro demo row sits on
  its own `demo` seat, never on the real-money one, so its evidence is never
  pooled with real money." (:1397-1401)
  - See P7. Grades and seats never pool worlds.
- **U-R14** "Switching it OFF stops new births, new journal lines and the
  census at the next tick; the Orcs already born keep what they wrote."
  (:1407-1408)
  - Add the O2 behaviour: OFF (`orcs` or minds) stops new calls at the next
    claim; pending wakes close with a code; a call in flight finishes and is
    booked.
- **K-R15** "The kill switch ends every idea in its scope, whatever the orcs
  switch says" (:1410-1412)
  - A dead Orc's pending wakes close with code `dead`, and no call is made
    (P1, P16).
- **K-R16** The arms "never move a stop, send an order or call a model ...
  While the row is open the tick alone moves them; once it has closed, the
  `orc-track-ghosts` beat alone does ... An arm walks only the bars after its
  birth" (:1422-1427)
  - The mind's worker writes an intent. Only the tick, or the beat, applies it
    (P32).
  - Forward only.
- **U-R17** The grade: "R only: the Orc against the care ghost and the playbook
  ... No seat reads it in O1." (:1455-1463)
  - In O2 the grade includes the Orc's shadow intents and its AI cost
    (`OrcGrade.ai_cost_usd` is written 0 today, grading.py:181).
  - Seats are computed in shadow in O2d.
- **K-R18** "Urgent reasons are recorded at once; the others at most every 15
  minutes. A reason read from a state ... fires once for the life of the
  position." (:1512-1514)
  - Also enforced at the claim (P12).
- **K-R19** "The tick only records the wake and its reasons (a quiet tick costs
  no query, a recorded wake a handful)" (:1515-1516)
  - Dispatch never moves into the tick (asset_engine/base.py:1396-1409).
- **U-R20** "Its status reads `skipped` ("no model before O2"), or `quiet` ..."
  (:1520-1523)
  - The new statuses and their words (P18).
- **K-R21** "A wake whose render fails is marked `failed` in its components and
  is not retried" (:1523-1525)
  - It is not counted as worker silence either (P11).
- **K-R22** "The dossier is what a model will read from O2 ... the position (in
  R only, never money) ... Headlines and calendar titles are fenced as
  untrusted text, a model's words as views; instruction-like text is withheld;
  no news body is read. Every block is stored once and a wake keeps the list,
  so any dossier can be printed again" (:1527-1540)
  - The request is exactly the stored blocks, plus S stored as a block.
  - `orcs dossier ROOT --wake N` prints S, the answer and the validation
    (map_wakes.md §2.2 h).
- **K-R23** Under a critical verdict, "the Orc's menu holds no exit, trim,
  waiver or add: hold, a plan revision and a tighten only" (:1548-1551)
  - The validator binds F5 (P24).
- **K-R24** "A posture that is not measured ... only print a dash and never
  stop anything." (:1551-1553)
- **U-R25** "Four beats, on the `slow` queue by exact name, behind `orcs`"
  (:1555)
  - O2 adds the `orcs` queue and its worker (P4).
  - Document the container and the check that it consumes.
- **K-R26** The drums
  - The words: "Prices and ATR only: never another position's R or money, and
    never a calendar title" (:1588-1590).
  - **D**: "In O1 a drum wakes nobody: the switch `orcs_drums` (System, OFF on
    arrival) changes nothing until O2, where it lets a drum wake the Orcs it
    reaches" (:1590-1594).
  - O2c delivers W12. Until then, O2a's admission lets no drum wake anyone.
- **K-R27** The tape "sends nothing until eToro's headroom is measured AND the
  switch `orcs_tape` ... is ON" (:1598-1602)
  - O2 adds no broker request. The mind reads the stored blocks only.
- **K-R28** O1d
  - "switching `orcs` OFF puts every page back to what it was before the Orcs,
    byte for byte, and `/orcs/` ... answer 404" (:1640-1644).
  - "Nothing here sends an order, moves a stop, calls a model or notifies
    anyone." (:1646-1647)
  - No page view may trigger a model call. O2d's Q&A goes through the
    dispatcher and the line.
- **K-R29** On Telegram: "R and prices only: never a balance, an amount or a
  quantity ... 'Withheld: this line may name an amount of money.'"
  (:1663-1666)
  - The model's note obeys the same rule (P22).
- **U-R30** "`/orc 12 <question>`, `/orc 12 stand down` and `/orcs off`
  answer in words and change nothing: no Orc reasons or acts in this release."
  (:1669-1671)
  - "No Orc reasons" becomes false when minds is ON.
  - Q&A arrives in O2d.
  - Stand-down and off still change nothing (O4a).
- **U-R31** The Horde: "the complexity score of its last detected wake ("No
  model (code only)")" (:1678-1679)
  - Show the rung that answered, or the code that answered.
- **U-R32** The positions page: "... no plan yet ..." (:1684) and "the
  comparison with the care" (:1688-1691)
  - The plan is rendered by code.
  - The comparison now measures the Orc's shadow arm.
- **K-R33** The close dialog: "Information only: the close itself, its PIN
  rule and close-all are unchanged." (:1692-1696)
- **K/U-R34** `/orcs/`: "Staff also see the AI spend lines there." (:1697-1699)
  - Add the Orcs line's calls today.
- **K-R35** `/orcs/<number>/`: "the journal (facts written by code and notes
  drawn apart, your words marked as yours)" (:1700-1704)
- **K-R36** "Your thesis ... is journaled as yours, never as a fact, and
  changes nothing the care does." (:1705-1708)
  - In the dossier it stays a view (PS2), never a T0 fact.
- **U-R37** `/orcs/seats/`: "In this release no Orc takes a step, so Δ measures
  the care ghost against the care, and no seat holds any power." (:1713-1714)
  - The first half becomes false once shadow intents step the O arm.
  - "No seat holds any power" stays true.

### B.4 The Orc pages' words (dashboard/views_orcs.py, templates/dashboard/orc*.html, bot_program/orcs/notes.py, bot_program/orcs/surfaces.py)

- **K-P1** views_orcs.py:1-20: "nothing here calls a model, a broker or an
  order path".
  - Also "OFF IS TODAY": every URL is a plain 404 while `orcs` is OFF.
- **U-P2** orcs_list.html:3, the page title "ORCS · JOURNALS BY CODE".
- **K-P3** orcs_list.html:78: "Every seat is L0 · Snaga: it watches and writes,
  in shadow. Seats hold no power in this release."
- **U-P4** orcs_list.html:87: "off (no Orc calls a model in this release)".
  - Read the line and the switch.
  - Never say "in this release".
- **U-P5** orc_detail.html:105: "Wakes detected (recorded only: no model is
  called)".
  - Show each wake's status: answered in shadow, answered by code (with its
    code), stale, merged.
- **U-P6** orc_detail.html:130: "Graded (shadow, no Orc action)".
- **K-P7** orc_detail.html:68, the legend "fact written by code · note an Orc's
  reading · yours your own words"
  - Model text is drawn as `note` (author `orc`; `AUTHOR_STYLE`,
    views_orcs.py:52-55).
- **U-P8** views_orcs.py:38, `NO_INTENTS` "No intents: an Orc proposes nothing
  until it reasons."
  - List the shadow intents with their mode.
- **U-P9** views_orcs.py:39-41, `SEATS_NOTE` (the same claim as U-R37).
- **U-P10** notes.py:140-146, `STATE_WORDS`
  - "born": "Watching: a journal written by code, no model."
  - "active" and "care_owned" already have words. They are written from O2
    (P13).
- **U-P11** notes.py:151-156, `COMMISSION_WORDS` "advise: journal and notes
  only; the care runs as it always has"
  - It also plans in shadow from O2. Keep "the care runs as it always has".
- **K-P12** notes.py:171, `PLAN_NONE` "No plan yet: Orcs write plans once they
  reason."
  - Still true for an Orc with no plan.
  - `plan_line` (notes.py:507-510) renders the plan by code.
- **U-P13** notes.py:176-177, `COMPARE` "...; the Orc has taken no step."
- **U-P14** notes.py:179-182: "Next wake {when} UTC: detected and recorded
  only, no model." / "No wake scheduled: no model is called."
- **U-P15** notes.py:184 `RUNG_NONE` "No model (code only)".
  - notes.py:441 hard-codes it and ignores the card's `rung_t`.
- **K-P16** notes.py:22-28: the slot carries "no cost, token, model, R-money or
  spend key at any depth".
  - Guard: tests/orcs/test_orc_notes.py:37-39 and :498-509 (`MONEY_KEYS`
    includes `cost_usd`, `tokens_in`, `model_used`, `spend_today_usd` and
    `ai_cost_usd`).
  - O2's model, tokens and cost go on the journal and OrcWake rows and on staff
    pages, never into the slot.
- **K-P17** notes.py:22-25: "no Orc verb is printed", and every outcome key
  carries `mode`.
  - Guard: tests/orcs/test_orc_notes.py:40-43 and :511-521 (`VERB`: "Orc ...
    decided|closed|trimmed|tightened|added|moved|exited"; `BY`: "... by the
    Orc").
  - Shadow intents are worded with "would", and mode is `shadow` or `refused`.
- **K-P18** notes.py:29-30: "Every sentence that names an Orc is listed in
  RESERVED_SENTENCES or matches RESERVED_PATTERNS".
  - Guard: tests/orcs/test_orc_notes.py:523 onward.
  - Register each new O2 sentence.
- **U-P19** surfaces.py:35-36, `QUESTION_LATER` "Orcs do not answer questions
  yet: none calls a model."
  - Keep "do not answer questions yet" until O2d.
  - Drop "none calls a model".
- **U-P20** surfaces.py:45 `MODEL_CALLS` "Model calls today: 0".
  - It is printed on every `/orc` reply (surfaces.py:268).
  - Print the Orc's real count (`llm_wakes_today`): a count, never money.
- **U-P21** surfaces.py:46-48, `HELP_LINES` "... (no model)".
- **U-P22** surfaces.py:39-40, `ORCS_OFF_NONE` "no Orc acts on a position;
  each keeps a journal only, and the care holds every position."
  - "Each keeps a journal only" becomes false. "No Orc acts" stays true.
- **K-P23** surfaces.py:20-21: "Every reply carries R and prices only: never a
  balance, an amount, a quantity or an account figure."
- **K-P24** dashboard/horde.py:274-290: "No Orc", "No Orc seated.", "No Orc has
  written a thesis for this seat yet."
  - Unchanged. The slot's `v` is 2 while `orcs` is ON (constants.py:385), and
    its keys are additive.

### B.5 The /ai-models/ page (templates/dashboard/ai_models.html, dashboard/views_ai_models.py, ai_agents/catalog.py)

- **U-A1** ai_models.html:153-156
  - The words: "The ladder the Orcs' router will pin ... an unvalidated prior;
    read by the router from O2; tier settings never move it. Their calls bill
    the Orcs' own budget line, which stays off until O2 (ORC_DAILY_BUDGET_USD).
    No Orc runs today."
  - Keep "tier settings never move it".
  - "No Orc runs today" must read the line, the switch and the ledger.
  - Say which rung O2a uses.
- **K-A2** ai_models.html:174-176, with views_ai_models.py:89-105: "Agent names
  on the Orcs' line (no override is read for them)"
  - The names: `orc`, `orc_confirm`, `orc_question`, `orc_postmortem`,
    `orc_tribunal`, `orc_emperor`, `orc_skeptic`, `captain`.
  - O2 bills only under these names.
  - A new name joins both `ORC_AGENT_KEYS` and spend's membership
    (spend.py:95-97). It is never writable through `KNOWN_AGENT_KEYS`.
- **K-A3** ai_models.html:27-31, the TODAY cell (the RUNBOOK's K-R5).
- **K/D-A4** The ladder's notes, shown on the page (catalog.py:505-520)
  - h0: "a paper probe only; never decides".
  - r0: "routine".
  - r1: "paper material; real money only for questions".
  - r2: "real-money material".
  - r3: "complex".
  - r4: "extreme when the Fable gate fails; Fable's blind twin".
  - r5: "extreme, gate passes; real money only, under a quota".
  - O2b routes by these words, or updates them with the table's version.
  - O2a's fixed rung must not contradict them (for example, h0 never decides).
- **U-A5** views_ai_models.py:91, :94-95 ("No Orc calls a model before O2") and
  :230 ("the Orcs' line (off until O2)"). These are comments, but they are read
  as the page's intent; update them.

### B.6 The switches, the commands and the budget's own words

- **K-C1** core/platform_control.py:323-325, `orcs` "Orcs (journals, no
  model)" ... "No model, no order, no stop moved."
  - Recommend keeping `orcs` exactly so, with the mind behind its own switch
    (map_wakes.md §2.1 a). Then these words stay true.
- **D-C2** core/platform_control.py:330-332, `orcs_drums` "In O1 this switch
  changes nothing; from O2, on, a drum also wakes the Orcs it reaches."
  - O2c delivers it.
  - Its "from O2" is the Book's landing tripwire (D-B6).
- **U-C3** core/ops_commands.py:140-152, the `orcs` entry "(O1: journals
  written by code; no model, no order, no stop moved)"
  - Add the new subcommands, each dry by default (P34).
- **U-C4** ai_agents/spend.py:23-24 ("0 = the line is off, which it is until
  O2 turns it on") and :79-81 ("O2 turns it on")
  - These read as if O2 itself turns the line on. That conflicts with "OFF on
    arrival", with the bench's "stays at zero until then" (D-B6) and with
    K-R2.
  - O2 keeps the default at 0 (tests/test_ai_spend_lines.py).
  - Reword: "the operator turns it on".
- **K-C5** ai_agents/spend.py:28-36
  - "on a calm Orc day the brain may spend what the Orcs did not" (the core
    line is never reduced by the Orcs' cap, only by their actual spend and the
    floor).
  - D30's exemption is "a live urgent or confirm wake" only.

### B.7 Which commit owns which promise

| Commit | Promises it must keep | Words it must update or deliver |
|---|---|---|
| O2a | K-B1, K-B3, K-B4, K-B5, K-B7, K-B8, K-B10, K-W1, K-W2, K-W5, K-R2-R5, K-R7, K-R10-R13, K-R15-R16, K-R18-R19, K-R21-R24, K-R27-R29, K-R33, K-R35-R36, K-P1, K-P3, K-P7, K-P12, K-P16-P18, K-P23, K-A2-A3, K-C1, K-C5 | U-B2, U-W3, U-R1, U-R6, U-R9, U-R14, U-R17 (AI cost), U-R20, U-R25, U-R30 (first half), U-R31, U-R32, U-R34, U-R37, U-P2, U-P4-P6, U-P8-P11, U-P13-P15, U-P20-P22, U-A1, U-A5, U-C3, U-C4 |
| O2b | K-W2, K-R8, K/D-A4 | U-R6 (routing in shadow), U-R31 (the rung), U-P15 |
| O2c | K-R26 | D-C2 (drum wakes, W12), D-R26 |
| O2d | K-R28 (Q&A through the dispatcher), K-P3 | U-R30 and U-P19 (Q&A answers), U-R17 (seats in shadow), U-R37 and U-P9 (seats) |
| The PR's landing | K-B9 | D-B6 (the bench line moves to `MILESTONES` with its hash; the new milestone avoids "no longer"), K-W4 (`TESTS_GREEN`) |
