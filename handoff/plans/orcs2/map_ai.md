# MAP 2: the AI stack and the budget, for O2 "shadow minds"

**Source.** The read-only checkout of main `9d74a19` (2026-11-01) at
`/home/user/Sauron_Vision/.claude/worktrees/orcsread`. Every `file:line` is in
that tree. A bare file name such as `wake.py` is under `bot_program/orcs/`.
O0 is PR #62 (merge `27348c3`), O1 is PR #71 (merge `9b6917d`).

**Where the numbers come from.**

* **Prices:** `ai_agents/catalog.py` (`PRICES_READ_ON = "2026-10-15"`, `:53`).
  I checked every ladder price against the live pricing page on 2026-11-01
  (https://platform.claude.com/docs/en/about-claude/pricing), and all of them
  match.
* **API rules:** the live pages on structured outputs, effort, and refusals and
  fallback (all fetched 2026-11-01), plus the bundled Claude API reference
  (cached 2026-10-06) for prompt caching.
* **Sizes:** the caps in `bot_program/orcs/constants.py`, `dossier.py`,
  `dossier_instrument.py` and `dossier_market.py`, estimated with O1's own
  `dossier.estimate_tokens`.
* **Arithmetic:** `orcs2/calc/map_ai_costs.py` in the scratchpad (full path in
  §8). It imports the catalog and the O1 estimator from the checkout, so a
  price or a cap that moves changes the tables. Run it with
  `/home/user/Sauron_Vision/venv/bin/python -I <path>`.

"$" always means AI spend in USD. No account figure appears in this file.

**Legend.** **DECIDE** = the code leaves a choice the spec must make.
**ASSUMED** = a number nobody has measured yet; §7 says how to measure it.

---

## 0. The answer on one page

1. **The Orc call is a direct `provider.complete()`.** It is the only path that
   takes the cache blocks, the effort-only message, the schema, the bound and
   the fallbacks. `BaseAgent.run()` passes none of them
   (`ai_agents/base_agent.py:134-148`).
2. **The provider never asks the budget before the call itself.** Its `line=`
   argument is read only by the client-side refusal re-run
   (`claude_provider.py:78-100, 680-681`). The Orc code asks
   `can_spend(line="orcs", ...)` itself, before every call.
3. **`can_spend` sees only finished `AgentTask` rows** (`spend.py:143-154`).
   O2 must reserve each call's bound before it is sent and release it after
   the row lands. The column already exists: `OrcWake.est_usd`
   (`models.py:168`).
4. **The prompt cache works only under all of these:**
   * one byte-stable S;
   * immutable MK blocks;
   * the top-level effort pinned at each model's default;
   * the rung's effort sent only in the effort-only message;
   * **one JSON schema for every Orc call** (changing `output_config.format`
     invalidates the prompt cache);
   * the MK breakpoint on the last closed session block, not on MK-E.
5. **The schema goes to the API raw**, so the raw API's rules apply:
   * `additionalProperties: false` on every object;
   * no `minimum`, `maximum`, `minLength` or `maxLength` (each is a 400);
   * no field named `reasoning`, `thinking` or `trace`: that draws a
     `reasoning_extraction` refusal, which is billed even with no output;
   * a `max_tokens` stop with some text comes back as a *success*
     (`claude_provider.py:669-670`), so code must check `stop_reason`.
6. **A realistic prompt is about 26,400 tokens as the API will count it.** That
   is O1's own estimate of about 21,600 tokens, with the measured 1.27
   correction on everything but S. About 12,300 tokens of it are cached, about
   14,100 are not. A **central call** costs:

   | Rung | Cost per call |
   |---|---:|
   | h0 | $0.0020 |
   | r0 | $0.044 |
   | r1 | $0.079 |
   | r2 | $0.119 |
   | r3 | $0.179 |
   | r4 | $0.299 |
   | r5 (uncached) | $1.26 |

   The reservation bound runs from $0.17 (r0) to $2.44 (r5) (§3.6).
7. **O1's detectors record about 18 wakes per Orc per weekday** for a 4h Orc in
   a 24-hour market. W2 and the W11 metronome run on separate 4-hour clocks,
   which gives 12 routine wakes a day. F6 almost never makes one quiet (§4.2).
8. **A day at O1's rates with no wake cap**, central, with r5 at O1's
   per-class quota:

   | Open positions | Calm day | Stormy day |
   |---:|---:|---:|
   | 5 | $8.9 | $21.4 |
   | 10 | $14.1 | $29.2 |
   | 20 | $24.6 | $45.6 |

   At O1's own display caps: $7.1 to $39.2 (§5.3). On a stormy day the Fable
   quota alone is $12.5.
9. **A day under the caps a sane O2 would set** (§6: real money 12/14/16 wakes,
   paper 6, Fable off, triage shares), central:

   | Open positions | Calm | Eventful | Stormy |
   |---:|---:|---:|---:|
   | 5 | $3.4 | $4.9 | $6.6 |
   | 10 | $5.9 | $8.5 | $11.5 |
   | 20 | $11.4 | $16.6 | $22.6 |

   With a $10 line, 10 positions fit on calm and eventful days. 20 positions
   bind it every day. The cut falls on paper first.
10. **Three numbers are ASSUMED and drive everything:**
    * output tokens per rung;
    * the band mix;
    * the real token count of the dossier.

    O1 is already recording the band mix and the dossier estimate on every
    `OrcWake`. The first O2 week gives the output tokens per rung. Size the
    line again from the p90 of those, not from this map (§7).

---

## 1. The stack at main 9d74a19

### 1.1 The provider: `ai_agents/providers/claude_provider.py`

**Signature** (`:333-351`):

```
complete(system_prompt="", user_message="", model="claude-sonnet-5-5",
         effort=None, agent_name="unattributed", record=True, source_ref="", *,
         system_blocks=None, user_blocks=None, shared_user_blocks=None,
         private_user_blocks=None, turn_effort=None, output_schema=None,
         max_tokens=None, fallbacks=None, line="core",
         client_refusal_rerun=True, timeout_s=None, task_budget=None,
         speed=None, answer_tokens=None) -> (text, usage)
```

The keyword-only arguments came in O0a for the Orcs. Today only the smoke
passes them. `line` must be `"core"` or `"orcs"`, or the call raises
(`:436-437`).

**Checks before anything is sent.** `build_request()` (`:167-317`) raises
`ValueError` in these cases (nothing is sent and nothing is billed):

* both `system_prompt` and `system_blocks` given (`:188-189`);
* `private_user_blocks` without `shared_user_blocks` (`:198-200`);
* `turn_effort` without the two-turn layout, not in `EFFORT_LEVELS`, or on a
  model without per-message effort (`:201-210`);
* `max_tokens` not a positive int, or given together with `answer_tokens`
  (`:213-225`);
* `task_budget` below 20,000 or on a model without it (`:226-232`);
* a `fallbacks` form the model does not take (`:238-253`; Sonnet 5.5 takes
  `"default"` only, Haiku 5.5 none);
* more than 4 cache breakpoints (`:271-273`);
* a 1h breakpoint after a 5m one (`:274-276`).

**Blocks and turns.**

* A block is `{"text": str, "cache_ttl": "5m" | "1h" | None}`, turned into a
  text block with `cache_control` (`:116-138`).
* The two-turn layout is: the shared user turn, then
  `{"role": "system", "content": [], "output_config": {"effort": turn_effort}}`,
  then the private user turn (`:141-164`).

**Effort and schema.**

* The top-level `effort` is sent only when the model supports effort
  (`:290-291`).
* `output_schema` becomes
  `output_config.format = {"type": "json_schema", "schema": ...}` (`:292-294`).
  It is sent raw: the SDK's `.parse()` is never used.

**Betas.** Each beta is added only when its keyword is used (`:43-47, :300-313`):

* `mid-conversation-output-config-2026-07-01` for the effort-only message;
* `server-side-fallback-2026-07-01` for `"default"`, and `-2026-06-01` for the
  list form;
* task budgets and fast mode.

Any beta sends the call through `client.beta.messages` (`:454`). The live page
says the 07-01 header accepts both fallback forms, so both values are valid.

**Transport, timeouts and retries.**

* Every call is streamed with `api.stream(**call)` and `get_final_message()`
  (`:471-477`).
* There is no hook for the first token. The caller sees only the finished
  message.
* The app retries twice, waiting 2 s then 4 s, only when the error text
  contains `overloaded`, `internal_server_error` or `'type': 'api_error'`
  (`:14-20, :478-492`).
* The client is built with the SDK defaults (`:327-331`): 2 retries and a
  600 s timeout. `AI_CONFIG["timeout_seconds"]` (60) and `["max_retries"]` (3)
  are read by nothing (`config/settings.py:480-481`).
* `timeout_s` becomes the SDK's per-request `timeout` (`:314-315`). That is an
  httpx timeout: it fires on a stalled connection, not on a long live stream.
* `duration_seconds` covers every attempt (`:468-472, :493`).

**`max_tokens`.**

* With no bound given, the provider uses 8,192 for the answer plus 23,808 for
  thinking on a thinking model, so 32,000 (`:53-71, :285-286`). All four ladder
  models think by default (`catalog.py`, `"thinking": True`).
* **A `max_tokens` stop with no text** is raised as a billed failure
  (`:655-668`).
* **A `max_tokens` stop with some text** only logs a warning and returns the
  cut-off text as a success (`:669-670`). For an Orc that is an invalid answer,
  billed in full.

**The ledger.** `complete()` writes one `AgentTask` row itself (`:600-641`)
unless `record=False`.

* The usage is computed first, before any verdict on the answer (`:502-597`).
* The cost is cache-aware, through `catalog.cost_usd`.
* With `fallbacks`, the row books the model that served (`:536-539`) and every
  attempt from `usage.iterations` at its own price (`:540-573`). It adds
  `asked_model` to the row when the server switched models (`:613-615`).
* `source_ref` is written into `structured_output` (`:613, 632`).
* `agent` is cut to 30 characters (`:622`).
* A billed failure (a refusal, `max_tokens` with no text, an empty answer)
  writes the row, then raises `RuntimeError` with `.usage` attached
  (`:643-650, :716-719`).

**Refusals.**

* With `client_refusal_rerun=True` (the default), a refusal is re-run once on
  `claude-opus-5` (`:28, :671-715`).
* For a `deep` or `frontier` model that re-run is **never budget-checked**:
  `_fallback_held` returns "" at once for those tiers (`:92-93`).
* The docstring sets the Orc rule: "Every Orc call passes False and relies on
  `fallbacks` alone" (`:406-408`).

**`count_tokens()`** (`:724-742`) is free and never ledgered. It leaves out the
effort-only message. O1's dossier modules are pinned never to call it
(`tests/orcs/test_orc_source_pins_o1c.py:33-40`).

### 1.2 The catalog: `ai_agents/catalog.py`

Prices are in $ per million tokens. A cache write costs the input price × 1.25
for a 5-minute TTL and × 2 for a 1-hour TTL (`:54-55`). Every figure matches
the live page of 2026-11-01. Footnote 2 there: "Cache hits and refreshes on
Claude Opus 5.5 and Claude Sonnet 5.5 are priced at 0.05x". The bundled
reference's $0.20 for Sonnet 5.5 is stale; the catalog's $0.10 is right.

| Model (ladder role) | Input | 5m write | 1h write | Cache read | Output | Min cache | Default effort | Per-message effort | Server fallback | Source |
|---|---:|---:|---:|---:|---:|---:|---|---|---|---|
| `claude-haiku-5-5` (h0) | 0.10 | 0.125 | 0.20 | 0.01 | 0.50 | 512 | medium | yes | none | `:266-293` |
| `claude-sonnet-5-5` (r0, r1) | 2.00 | 2.50 | 4.00 | 0.10 | 10.00 | 512 | high | yes | `"default"` only | `:171-195` |
| `claude-opus-5-5` (r2-r4) | 4.00 | 5.00 | 8.00 | 0.20 | 20.00 | 512 | medium | yes | both forms | `:90-110` |
| `claude-fable-5-1` (r5) | 10.00 | 12.50 | 20.00 | 0.25 | 50.00 | 512 | high | yes | both forms | `:67-89` |
| `claude-opus-5` (the client re-run; a list-form fallback) | 5.00 | 6.25 | 10.00 | 0.50 | 25.00 | 512 | high | yes | both forms | `:111-129` |
| `claude-sonnet-5` (possibly in Sonnet 5.5's default route) | 2.00 | 2.50 | 4.00 | 0.20 | 10.00 | 1024 | high | **no** | none | `:146-170` |

Haiku 5.5 switches to its long-context card above 100,000 prompt tokens
(`:283-284`). An Orc prompt is about 26,000 tokens, so that never happens.

**The ladder, `ORC_LADDER_V1`** (`:505-520`). It is display-only in O0, and an
unvalidated prior "until each band boundary has two completed probe blocks"
(`:500-504`). `tests/test_model_catalog.py:434-452` pins it.

| Rung | Model | Effort | Note in the catalog |
|---|---|---|---|
| h0 | Haiku 5.5 | low | a paper probe only; never decides |
| r0 | Sonnet 5.5 | low | routine |
| r1 | Sonnet 5.5 | high | paper material; real money only for questions |
| r2 | Opus 5.5 | medium | real-money material |
| r3 | Opus 5.5 | high | complex |
| r4 | Opus 5.5 | xhigh | extreme when the Fable gate fails; Fable's blind twin |
| r5 | Fable 5.1 | max | extreme, gate passes; real money only, under a quota |

**The tier for `can_spend`** is `MODELS[model]["tier_hint"]`: Haiku `fast`,
Sonnet `balanced`, Opus `deep`, Fable `frontier`. The 70% deep share applies to
`deep` and `frontier` (`spend.py:268`), so it reaches r2 to r5.

**A model id lives only in `catalog.py` and `config/settings.py`.** Any other
quoted `claude-...` literal fails `tests/test_model_catalog.py:455-498`, which
allows only three old ones (`:463-469`). So a v2 ladder goes into `catalog.py`.
`bot_program/orcs` names models by family only (`constants.py:277-296`).

### 1.3 The budget: `ai_agents/spend.py`

**Values.**

* **`AI_DAILY_BUDGET_USD`** is the **total** stop. Default 15 (`:60`,
  `.env.example:32`). The comment says 15 "covers the measured full burn
  (~4/day)" (`:57-58`).
* **`ORC_DAILY_BUDGET_USD`** is the Orcs' **cap**. Default 0, which means the
  line is off (`:79-81`, `.env.example:34-40`). A typo in it falls back to 0,
  logged (`:63-76`).
* **`ORC_LIVE_FLOOR_USD = 3.00`** (`:84`) and **`DEEP_TIER_SHARE = 0.7`**
  (`:87`).
* Both environment values are read at import. A new value binds only after
  `./deploy/dc up -d` (`deploy/RUNBOOK.md:1295-1300`).
* `AI_CONFIG` carries no budget keys, so the environment rules. Tests override
  with `AI_CONFIG["daily_budget_usd"]` and `["orc_daily_budget_usd"]`
  (`tests/test_claude_provider_keywords.py:91-98`).

**The day is the UTC day.** `_today()` filters
`created_at >= timezone.now().replace(hour=0, ...)` (`:143-146`), with
`TIME_ZONE = "UTC"` and `USE_TZ = True` (`config/settings.py:445-447`). The
trading day and the weather roll at 17:00 New York (`sessions.py:129-137`), so
the two clocks differ by 2 to 3 hours. **DECIDE** which day the per-Orc caps
count on (§6).

**The Orcs line.** A row is on it by agent `orc` or `captain`, by an agent name
starting `orc_` or `captain_`, or by a `source_ref` starting `Orc:` or
`Captain:` (`:93-97, :130-140`).

**The core line.** While the Orcs line is on, the core line's allowance is
`total − Orcs spent today − 3.00` (`:157-170`). Off, it is the whole total, from
one query.

**`can_spend(tier, estimated_usd=0.05, line, total_only, deep_share_exempt)`**
(`:208-276`) runs in this order:

1. With `line="orcs"`, a cap of 0 and `total_only` false: refuse, "the Orcs
   line is off (ORC_DAILY_BUDGET_USD=0)" (`:229-230`).
2. Refuse once the whole ledger has reached the total, **on either line**
   (`:241-243`).
3. On the Orcs line, budget = cap and spent = the Orcs' own rows (`:247-248`).
4. remaining = `min(budget − spent, total − spent_all)` (`:254-255`). Refuse at
   or under 0 (`:256-262`).
5. Deep share: refuse a `deep` or `frontier` call once the **line's** spend
   (any tier) passes 70% of the line's budget. `deep_share_exempt` lifts this on
   the Orcs line only (`:267-272`).
6. Refuse when `estimated_usd > remaining` (`:273-275`).

**What `spend.py` does not do. O2 must build each of these itself.**

* **No in-flight accounting.** Two workers can both pass on the same remaining
  amount.
* **No per-Orc caps, no triage shares, no frontier quota.**
* **The floor does not protect the Orcs from every core caller.** Core spend
  can reach the total and so starve the Orcs line (steps 2 and 4).
  * The core callers that ask the core line respect the floor:
    * the brain's beats, through `@spend_guard` (`brain/tasks.py:20, 37, 60, 69,
      80, 108`);
    * the position reviewer, the council, the research chat, the close advisor
      and the horizon command.
  * `BaseAgent.run` callers ask the **total only** (`base_agent.py:74-91`): the
    news analyst, the anomaly detector, the strategy advisor, the weekly
    reviewer and the debate's two sides.
  * The inline daily briefing and Monday plan ask **nothing at all**
    (`ai_agents/tasks.py:76-112, 193-204`).

  Raising the total (§6) makes starvation unlikely, not impossible.
* **The floor is held back from the core even when the Orcs cannot use it**:
  with a cap under $3, or once the cap is spent (`:170, :252`). It is O0 code,
  so the spec decides whether to change it.

`lines_summary()` (`:297-325`) feeds the TODAY cell on /ai-models/.

### 1.4 `BaseAgent.run(source_ref=)`: `ai_agents/base_agent.py`

* **The gate.** `can_spend(tier=self.default_tier, line="core", total_only=True)`
  (`:74-91`). It raises `BudgetRefused` before anything is sent (`:103-109`). A
  budget it cannot read refuses nothing (`:87-90`).
* **The call.** `provider.complete(system_prompt, user_message, model, effort,
  agent_name, record=False, [source_ref], [answer_tokens])` (`:134-148`). It
  reaches none of the O0a keywords.
* **The ledger.** `run()` writes its own row on success (`:156-172`) and on a
  billed failure, from the usage hung on the exception (`:177-204`).
* **The `source_ref`.** It rides into both rows (`:169, :200-201`), so
  `source_ref="Orc:..."` bills a debate to the Orcs line. A model's own output
  can never move a core row onto that line (`:206-224`).
* **What this means for O2.** A debate billed to an Orc through
  `run(source_ref="Orc:...")` is gated by the total only. The Orc caller must
  ask `can_spend(line="orcs")` first. The debate runs on Opus 5.5 (deep tier),
  so on a refusal it is re-run on Opus 5 without any budget check (§1.1). The
  spec should either accept that or give the Orc's debate its own direct call.

### 1.5 How an existing agent calls a model, end to end

**The position reviewer** (`brain/position_review_agent.py`) is the nearest
shape to an Orc:

1. a free deterministic layer writes the domain row first;
2. caps per pass and per day: 3 and 12 (`:57-66`);
3. only an **answered** row suppresses a same-facts re-ask (`:621-653`);
4. `can_spend(tier=default_tier, estimated_usd=0.02)` on the core line
   (`:760-761`), with the refusal written onto the row (`:762-766`);
5. `agent.provider.complete(..., agent_name=agent.agent_name,
   source_ref=f"PositionReview:{review.pk}")` (`:661-670`);
6. clamp the answer and copy tokens and cost onto the domain row (`:680-695`);
7. grade it later (`:799`).

**The trade debate** (`ai_agents/agents/trade_debate.py`):

* It runs on Opus 5.5 at low effort (`:45`), estimated at $0.03 a side (`:47`).
* It asks `can_spend(tier="fast", estimated_usd=0.06)` (`:382-384`). Passing
  `fast` for an Opus call means the deep share never applies to it. O2 must
  not copy that: pass the model's `tier_hint`.
* Two `BaseAgent.run()` threads, one 60 s deadline for the pair (`:50,
  :396-420`).

**The council** (`ai_agents/agents/council.py`):

* It prices the text it actually sends: `estimate_usd`, characters ÷ 3 for
  input plus `COUNCIL_OUT_TOKENS = 1500` for output, × 1.5 (`:99, :2120-2131`).
  The ÷ 3 comes from the close advisor: "three, not the usual four, because
  indented JSON of numbers and keys tokenises denser than prose"
  (`brain/close_advice.py:175-185`).
* One `can_spend(line="core")` per wave of voices (`:2210`).

**The smoke** (`ai_agents/management/commands/claude_smoke.py`) is the template
for the Orc request:

* `layout()` (`:296-307`):
  * S in `system`, cached 1h;
  * the MK blocks, the last one cached 1h;
  * IN cached 5m;
  * PS and the tail private and uncached.
* The top-level `effort=default_effort(model)`; the rung's effort goes in
  `turn_effort` (`:386-393, :455-463`).
* `output_schema=DECISION_SCHEMA` (`:65-76`).
* `max_tokens` 8,000 on Sonnet and Haiku, 16,000 on Opus and Fable (`:79-84`).
* `client_refusal_rerun=False`, `line="core"`, agent `claude_smoke`, source
  `Smoke:<UTC>:<model>:<effort>` (`:452-466`).
* Its bound: every prompt token at the 1h write price with a 1.35 tokenizer
  headroom, plus `max_tokens` of output, for both calls (`:375-384`).
* **PASS** means call B (xhigh) read A's (low) cache **and** wrote at least
  twice A's output, both stopped at `end_turn`, and both answers fit the schema
  (`:487-516`).
* **The verdict is recorded nowhere in the repository.** The only smoke
  measurements kept in code are `S_TOKENS_RESERVE = 3930` and
  `TOKEN_FACTORS = 1.0` for Haiku, Sonnet and Opus (`constants.py:288-300`).

**Every new direct caller must be registered.**

* A new `provider.complete(` site must go into `BYPASS_SITES`
  (`tests/test_llm_ledger_truth.py:48-63`).
* Its `agent_name=` must sit within 500 characters of the call (`:273-280`).
* The completeness scan matches only the literal `provider.complete(` or
  `_provider.complete(` (`:282-297`). Name the variable `provider`, or the scan
  goes blind.
* `record=False` is allowed only in `ai_agents/base_agent.py` and
  `ai_agents/tasks.py` (`:67, :299-311`).

### 1.6 The /ai-models/ page: `dashboard/views_ai_models.py`, `templates/dashboard/ai_models.html`

What it shows today:

* the tiers and per-agent rows, with an override form for each;
* the catalog with cache-read prices and minimums;
* the 30-day spend **per model**, Orcs and core mixed (`views_ai_models.py:204-216`);
* the TODAY cell (`ai_models.html:21-32`). With the line on, its third line
  reads:
  `AI $x of $y (= $T − Orcs spent − $3.00 floor) · Orcs $z of $C · total $t of $T`;
* the read-only card "The Orcs" (`:150-177`): the v1 ladder and the agent names
  on the Orcs line (`ORC_AGENT_KEYS`, `views_ai_models.py:96-105`: `orc`,
  `orc_confirm`, `orc_question`, `orc_postmortem`, `orc_tribunal`,
  `orc_emperor`, `orc_skeptic`, `captain`). No override can be saved for them.

What O2 must change (platform text stays in English):

* the card's sentence "stays off until O2 ... No Orc runs today"
  (`ai_models.html:152-157`), which becomes false;
* any new O2 agent name, added to `ORC_AGENT_KEYS`;
* new readouts:
  * the Orcs line's spend per rung for today and the last 7 days (from
    `source_ref` or the cost columns on `OrcJournal`);
  * the cache-read share per model;
  * the refusal and invalid-answer counts;
  * the recorded smoke verdict;
  * the ladder version the router uses, still marked "unvalidated prior".

### 1.7 What O0 and O1 already prepared for the calls

* **Columns.** They exist, and nothing writes them yet:
  * `OrcWake.model` and `est_usd` (`models.py:167-169`);
  * `Orc.llm_wakes_today`, `routine_wakes_today`, `spend_today_usd` and
    `routine_spend_today_usd` (`:103-109`);
  * `OrcJournal.model`, `tokens_in`, `tokens_out`, `cache_read`,
    `cache_write` and `cost_usd` (`:206-212`);
  * `OrcGrade.ai_cost_usd` and `n_llm`;
  * `OrcSeat.model_routine` and `model_decisive`.
* **The switch.** `orcs` is System and OFF on arrival; an unreadable switch
  reads OFF (`switches.py:1-28`). It is "not a live-money switch". The model
  calls need their own switch, OFF on arrival (§6).
* **The pins.**
  * The 18 O1c modules (`sessions` through `notes`, `wake` and `tasks`
    included) must not name `ai_agents`, `anthropic` or `count_tokens`
    (`tests/orcs/test_orc_source_pins_o1c.py:18-21, 33-40`).
  * `wake.py` must never write `status="pending"` (`:66-71`).

  So the module that makes the call must be new (for example
  `bot_program/orcs/mind.py`), or O2 must revise these pins on purpose and say
  so.

---

## 2. How an Orc call must be made

### 2.1 So that the budget binds

1. **The locks, in order.** Each must hold, or **code** answers the wake (a
   `budget` journal entry) and nothing is sent.
   1. The `orcs` switch is ON, the O2 minds switch is ON (§6), and
      `ORC_DAILY_BUDGET_USD > 0`.
   2. O2's own gates:
      * the per-Orc day caps on model wakes and dollars (D18; urgent wakes
        count too);
      * the triage share of the line for this world and urgency;
      * the frontier quota (r5);
      * the 15-minute spacing, checked **again at claim** for non-urgent wakes.
   3. The reservation, step 2.
   4. Last, `can_spend(...)`, step 3.

   A refusal never lowers the rung. Lowering it would bias the grading of the
   rungs and break "no consequence lowers the tier of a live decision"
   (`complexity.py:23-25`).
2. **Reserve under a lock.**
   * In one transaction holding one lock (for example `select_for_update` on a
     single `OrcSetting` row), read `spent_today("orcs")`, `spent_today("total")`
     and Σ `est_usd` of today's `running` wakes.
   * Check that `spent + Σ reserved + B` stays within this wake's triage share
     of the cap, and within the total.
   * Write `est_usd = B`, `status = "running"` and `started_at`.
   * B is the rung's bound (§3.6).
   * Expire a reservation whose `started_at` is older than the call's worst wall
     time: about 3 × `timeout_s` + 60 s. That covers a worker killed mid-call.
3. **Ask the house gate with the in-flight money included:**

   ```
   can_spend(tier=MODELS[model]["tier_hint"],
             estimated_usd=B + reserved_by_others,
             line="orcs",
             deep_share_exempt=<a real-money urgent or confirm wake only, D30>)
   ```

   * Never omit `estimated_usd`: its default is $0.05 (`spend.py:208`).
   * The deep-share test reads ledger spend only, so O2's own check in step 2
     must also hold back r2 to r5 at 70% of the cap.
4. **Make the call so that the provider's own row lands on the Orcs line:**
   * `record=True` (the default);
   * `agent_name="orc"`, or `orc_confirm`, `orc_question` and the rest of
     `ORC_AGENT_KEYS`;
   * `source_ref=f"Orc:{orc.pk}:w{wake.pk}:{rung}"`;
   * `line="orcs"` and `client_refusal_rerun=False`;
   * an explicit `max_tokens` and `timeout_s` per rung (§6);
   * `fallbacks` as in §6: none on Haiku and Sonnet, the list form on Opus and
     Fable.
5. **Settle after the call.** On success, and on a `RuntimeError` that carries
   `.usage`:
   * copy `usage` onto the journal entry's model, token and cost columns;
   * add to the Orc's day counters;
   * release the reservation (`est_usd = 0`, the status out of `running`).

   Between the row landing and the release, the money counts twice. That only
   refuses slightly early, which is safe.
6. **Other failures.**
   * **A `ValueError`** from `build_request`: nothing was sent and nothing is
     billed.
   * **A network error or timeout:** no usage comes back, so no row is written.
     Anthropic may still bill tokens it generated before the cut.

   In both cases, release the reservation, journal an `error`, and count it in
   the failure rate. This gap is rare; it is the one place the ledger can read
   low.
7. **Tooling.** Every manual path that sends must go through the same switch,
   rung list, bound and line gate (`orcs record --yes`, `orcs smoke --row`, any
   replay). The lost O2a was flagged twice on exactly this:
   * it accepted r5 with a $2 bound and never asked `can_spend`;
   * it called the model with the `orcs` switch OFF.
8. **Mind the total.** Core callers can spend the total down to the Orcs' cap
   (§1.3). Raise `AI_DAILY_BUDGET_USD` with the cap (§6), and show the Orcs
   line's remaining amount on the Orc pages.

### 2.2 So that the prompt cache works

**The layout.** It is the smoke's, with one change: the MK breakpoint moves.
Four breakpoints at most, longer TTLs first, which `build_request` enforces:

```
system_blocks       = [ {S,             "1h"} ]
shared_user_blocks  = [ {MK0,           None},
                        {session 1..k-1, None},
                        {session k,     "1h"},   # the last CLOSED session
                                                 # (MK0 itself before any closes)
                        {MK-E,          "1h"},
                        {IN-slow,       "5m" only when another wake on the
                                         same (symbol, model) is queued,
                                         else None} ]
turn_effort         = <the rung's effort>        # the effort-only message
private_user_blocks = [ {PS, None}, {tail, None} ]   # never a breakpoint
```

`day_hashes()` puts MK-E after the sessions (`dossier_market.py:290-308`), so
the breakpoint must not sit on MK-E alone:

* **With the smoke's layout**, a session close or the Emperor's order rewrites
  the whole MK at the 1h price, 7 times a day.
* **With this layout**, a close writes only its new block. Writes bill only
  past the longest cached prefix, and earlier requests left an entry at the end
  of the previous session block. The Emperor's line writes only MK-E.

**The rules.**

1. **Pin the top-level effort at `catalog.default_effort(model)` on every Orc
   call**: medium on Opus 5.5 and Haiku 5.5, high on Sonnet 5.5 and Fable 5.1.
   * Sending a model's default is the same as omitting it.
   * A top-level change "restarts the cache" (live effort page).
   * The rung's effort travels only in the effort-only message, which "preserves
     the prompt cache" on all four ladder models (live effort page).
2. **One schema for every Orc and every model.** "Changing the
   `output_config.format` parameter will invalidate any prompt cache for that
   conversation thread" (live structured-outputs page).
   * So: no per-Orc `enum` (allowed actions, level ids, fact ids). The smoke's
     `level_id` enum was synthetic.
   * Code checks those values after the answer (§2.3).
   * A new schema means a new version for every Orc at once.
3. **S is byte-identical across all Orcs and wakes.** No time, no Orc id, no
   army type, no rank, no temperament: those belong in PS.
4. **MK is already byte-stable.** It is content-addressed, sorted-key JSON, and
   immutable once built (`dossier.py:47-57`). It is shared across users, since
   MK carries no user's book (`dossier_market.py:29-32`).
5. **Render the dossier for the routed model's family.** O1 renders for
   `"sonnet"` only (`wake.py:728`; `dossier.py:360`). MK and IN-slow blocks are
   keyed by family (`dossier_market.py:57-61`; `dossier_instrument.py:278-279`).
   Caches are per model in any case, and per workspace on the Claude API.
6. **r0 and r1 share Sonnet's cache, and r2 to r4 share Opus's, only if the
   smoke's C2/C3 passed.** The verdict is not in the repository.
   * Record it (for example an `OrcSetting` the operator writes after
     `claude_smoke --yes`).
   * Gate per-wake effort on it.
   * Without a PASS, change model and effort per epoch, never per wake. That is
     the smoke's own FAIL rule (`claude_smoke.py:504-509`).
7. **r5 and h0 carry no breakpoint.**
   * r5 runs 0 to 1 times a day; a 2× write would never be read.
   * Caching h0's S and MK changes its cost by about $0.001 a call either way:
     12,335 tokens at $0.10 against $0.01.
8. **IN-slow takes no 1h breakpoint.**
   * It is keyed per (symbol, newest final 1h bar, family)
     (`dossier_instrument.py:271-284`), so its bytes change every hour.
   * Two wakes of one Orc inside one bar pay 2.05× with a 1h entry against 2×
     uncached.
   * A 5m entry for a queued twin pays 1.30× against 2×.
9. **Bursts.** Every 4h Orc gets W2 at the same final bar, and every USD row
   gets W5 at the same offsets. "A cache entry becomes readable only after the
   first response begins streaming" (bundled reference, prompt caching).
   * The provider has no first-token hook.
   * So when a model's cache is presumed cold (no call on it in the last 55
     minutes), run that model's first call alone and release the rest when it
     returns.
   * With the layout above and an `orcs` worker at concurrency 2, a warm burst
     costs at most one extra session-block write: 1,383 tokens × (4.00 − 0.10)
     $/MTok, about $0.005.
10. **No pre-warming.** `max_tokens: 0` is rejected together with
    `stream: true` and with `output_config.format` (bundled reference,
    "Rejected combinations"). The provider always streams. A pre-warm without
    the schema would key a different entry.
11. **The minimum does not bite.** It is 512 tokens on all four ladder models
    (`catalog.min_cache_tokens`); S alone is 3,930.
12. **Check the cache after every change.** `usage` returns
    `cache_read_input_tokens` and the TTL split (`claude_provider.py:585-597`),
    and the row books `cache_read_tokens` and `cache_write_tokens`.
    * Record the reads per wake.
    * Alert when a model goes a day with zero reads.
    * Add a test that two Orcs on one model produce a byte-identical `system`
      and shared turn.

### 2.3 So that the answer is schema-checked

1. **The schema, under the raw API's rules** (live structured-outputs page):
   * `additionalProperties: false` on every object;
   * no `minimum`, `maximum` or `multipleOf`;
   * no `minLength` or `maxLength`;
   * no array constraint beyond `minItems` 0 or 1;
   * no recursion;
   * at most 24 optional parameters and 16 union-typed ones across the request;
   * "If you use an unsupported feature, you'll receive a 400 error";
   * compiled grammars are cached "for 24 hours from last use", with a 180 s
     compile timeout and "Schema is too complex for compilation" as a 400;
   * the injected format prompt makes the "input token count slightly higher".
2. **No field asks for reasoning.**
   * A `reasoning`, `thinking` or `trace` field draws a `reasoning_extraction`
     refusal.
   * That category is **billed even before any output** (live refusals page).
   * Use a short `note`, capped by code at 140 characters
     (`constants.FENCE_CAPS["note"]`), and `facts_cited`.
   * The schema cannot enforce the 140 characters, because `maxLength` is
     unsupported.
3. **Validate in code, in this order.**
   1. `usage["stop_reason"] == "end_turn"`. A `max_tokens` stop with text
      arrives as a success (`claude_provider.py:669-670`) and is an invalid
      answer.
   2. `json.loads`.
   3. The shape, hand-written like `claude_smoke.validate_decision`
      (`:310-332`). `jsonschema` is not in `requirements.txt`, and pydantic is
      only an unpinned dependency of the SDK.
   4. The V-rules:
      * the allowed actions;
      * the menu level ids, where V6 accepts reached pools only;
      * the cited facts are real T0 facts of the kinds `V10_RELEVANCE` allows
        (`constants.py:227-241`);
      * the `next_wake` bounds;
      * the plan-change rule;
      * the money filter on every free-text field **before** it is stored, put
        on a card, or fed back as a PS5 note.
4. **A refusal raises `RuntimeError` with `.usage`.**
   * Journal a `refusal` entry and keep the plan as it was.
   * When a server fallback served, `usage["model"]` names the model that
     answered; record it.
5. **Count every failure.** Refusals, cut-off answers and every V-rule failure
   go into the invalid-output rate, each with its cost. The lost O2a was flagged
   for leaving V10 out.

### 2.4 What the tests must prove, with a fake model and no network

**How to fake it.**

* Inject the fake client into the **real** provider, using
  `tests/test_claude_provider_keywords.py:43-84`: `ClaudeProvider()` with
  `p.client = _Client(...)`.
* The ledger, the costs and the refusal paths then run for real.
* Assert on what the fake recorded (`client.calls`). Never rely on an assertion
  raised inside a fake provider: the Orc code catches every exception. That was
  a finding on the lost O2a.

**What the tests must pin.**

* A refused gate makes no call.
* The row lands on the Orcs line: `spent_today("orcs")` rises by the booked
  cost.
* Two concurrent claims where only one fits make one call.
* An expired reservation is released.
* The `system` block and the shared turn are byte-identical across two Orcs on
  one model, and across r0 and r1 apart from the effort-only message.
* The schema is the same object for every Orc.
* A refusal, a cut-off answer and a V10 failure each count as invalid.
* `BYPASS_SITES` is updated (`tests/test_llm_ledger_truth.py`).
* No model id appears outside the catalog (`tests/test_model_catalog.py`).
* The O1 source pins still pass, or are changed on purpose in the same commit.

---

## 3. What each rung costs per call

### 3.1 Prompt sizes, from the dossier's caps

O1 estimates every block as prose characters ÷ 4 + 8.5 tokens per bar row, × the
family factor (`dossier.py:102-107`; `constants.py:288-298`). A bar row's
characters are counted as prose too, so a row counts twice. That is by design:
`tests/orcs/test_orc_dossier.py:573` pins 400 characters plus 10 rows at 185.

| Part | O1-estimated tokens | Source |
|---|---:|---|
| Whole dossier, the cap | **22,000** | `constants.py:217` `DOSSIER_MAX_TOKENS` ("§10.7 verbatim") |
| S, the doctrine (a **count**, not an estimate) | **3,930** | `constants.py:299-300` `S_TOKENS_RESERVE`, measured by the 2026-10-16 smoke |
| MK0, the day header | 686 | built with `dossier_market.build_mk0`'s shape (script) |
| One closed session block, planned | ≤ 900 | `constants.py:224` `MK_SESSION_MAX_TOKENS`, with headlines 6 → 4 → 3 (`dossier_market.py:212-238`) |
| One session block, built (no brief) | **1,088** at 3 headlines | script: the 11-symbol board, the Mind's view, 2 prints, 3 headlines |
| The session block where the brief lands | **1,556** at 3 headlines | script: the strategist's daily brief adds its views |
| MK-E | 19 (O1's dash); the Emperor's order is longer in O2c | `dossier_market.py:258-268` |
| IN-slow, full | **4,497** | 120 1h + 60 4h + 60 1d rows (`dossier_instrument.py:35-36`), 24 menu levels, structure, positioning, COT, gaps (script) |
| IN-slow, cut | 3,701 | 1h rows cut to `IN1_1H_KEEP = 72` (`:38, :218-225`), only when the dossier would not fit |
| PS + tail | **6,600** | `dossier_instrument.py:39-41` `PS_TAIL_RESERVE` (PS about 2,900, the tail about 3,700) |

**Three findings the spec must take in.**

1. **The session blocks are likely stored over their cap.** By O1's own
   estimator, a block still holds about 1,090 tokens at the fewest headlines
   it allows (3), and about 1,560 where the brief lands. The board, the Mind's
   view and the prints alone come to about 900. `build_session` then stores
   the block once, marked `over_budget` (`:231-238`). The end-of-day MK is
   therefore about **6,600** tokens, not the planned 5,200.
2. **IN-slow is about 60% larger than the spec's midday 2,830**
   (`claude_smoke.py:60`). The cut fires only when the budget
   `22,000 − 3,930 − MK − 6,600` is exceeded (`dossier_instrument.py:215-217`).
   For the Sonnet family that is rare. For Fable (× 1.35) it fires, and the
   block is stored anyway, because nothing checks it a second time.
3. **The 22,000 is a flag, not a limit.** `trim` empties only the parts in
   `TRIM_ORDER` (`dossier.py:159-174`). PS, the tail's head, MK and IN-slow are
   never cut, and `render` only sets `over_budget` (`:441`).

**The prompts I price.**

| Prompt | S | MK | IN-slow | PS + tail | Total | Cached (S + MK) | Uncached |
|---|---:|---:|---:|---:|---:|---:|---:|
| Midday as O1 estimates it (3 sessions closed) | 3,930 | 4,437 | 4,497 | 6,600 | 19,464 | 8,367 | 11,097 |
| End of the trading day, as O1 estimates it | 3,930 | 6,613 | 4,497 | 6,600 | 21,640 | 10,543 | 11,097 |
| Midday as the API will likely count it | 3,930 | 5,639 | 5,716 | 8,389 | 23,674 | 9,569 | 14,105 |
| **End of day as the API will likely count it: the day model's prompt** | 3,930 | 8,405 | 5,716 | 8,389 | **26,440** | **12,335** | **14,105** |
| The reservation's prompt: the cap with the smoke's 1.35 headroom | 3,930 | 8,928 | 6,557 | 8,910 | 28,325 | 12,858 | 15,467 |

**Where the 1.27 comes from.**

* The smoke's synthetic S is **12,367 characters** (`claude_smoke.py:141-149`,
  measured by the script).
* O1's rule reads that as 3,092 tokens; `count_tokens` counted **3,930**. So the
  real count is **1.271 ×** the estimate, or 3.15 characters a token.
* `TOKEN_FACTORS = 1.0` is a ratio *between models* ("the same counts on Opus
  5.5 and Haiku 5.5 as on Sonnet 5.5", `constants.py:288-290`). It is not a
  calibration of the 4-characters rule.
* The close advisor's rule of 3 characters a token for JSON points the same way.
* Bar rows may tokenize closer to their (double-counted) estimate. So 1.27 is
  conservative for IN-slow and about right for the JSON blocks.
* Applied to all but S. S is already a count; the real S does not exist yet
  and must fit the 3,930 reserve.

### 3.2 Output tokens per rung, thinking included (ASSUMED)

No Orc output has ever been measured. O1 has no model, and the smoke's output
counts were not kept. The answer itself is a few hundred tokens: a JSON plan or
intent, a 140-character note and fact ids. Everything else is thinking, which
the effort sets. What the platform knows:

* the smoke's PASS needs xhigh to write at least twice what low writes on the
  same dossier (`claude_smoke.py:510-515`);
* the council's per-voice estimate is 1,500 output tokens (`council.py:99`);
* the close advisor allows 2,000 plus 400 per position (`close_advice.py:183-184`);
* the reviewer's "measured ~$0.01 per call" (`position_review_agent.py:58-59`)
  dates from before the current models, on a short prompt.

| Rung | Lean | **Central** | High | `max_tokens` (the bound) |
|---|---:|---:|---:|---:|
| h0 Haiku low | 500 | **1,000** | 2,000 | 8,000 |
| r0 Sonnet low | 800 | **1,500** | 3,000 | 8,000 |
| r1 Sonnet high | 2,500 | **5,000** | 10,000 | 16,000 |
| r2 Opus medium | 1,500 | **3,000** | 6,000 | 16,000 |
| r3 Opus high | 3,000 | **6,000** | 12,000 | 24,000 |
| r4 Opus xhigh | 6,000 | **12,000** | 24,000 | 32,000 |
| r5 Fable max | 10,000 | **20,000** | 32,000 | 32,000 |

### 3.3 The formula and worked lines

Every price is in $ per MTok, from §1.2.

```
input  = (S + MK) x cache_read  +  (IN + PS + tail) x input     # warm
output = output_tokens x output_price
call   = (input + output) / 1,000,000
```

Each line below is on the day model's prompt: 12,335 cached and 14,105 uncached
tokens, 26,440 in all.

* **r0, Sonnet 5.5 at low effort:**
  12,335 × 0.10 = 1,234 µ$; 14,105 × 2.00 = 28,210 µ$; 1,500 × 10 = 15,000 µ$.
  **Total $0.0444.**
* **r2, Opus 5.5 at medium:**
  12,335 × 0.20 = 2,467 µ$; 14,105 × 4.00 = 56,420 µ$; 3,000 × 20 = 60,000 µ$.
  **Total $0.1189.**
* **r5, Fable 5.1 at max, no cache:**
  26,440 × 10 = 264,400 µ$; 20,000 × 50 = 1,000,000 µ$.
  **Total $1.2644.**
* **h0, Haiku 5.5 at low:**
  12,335 × 0.01 + 14,105 × 0.10 = 1,534 µ$; 1,000 × 0.50 = 500 µ$.
  **Total $0.0020.**

### 3.4 Cost per call ($)

The input is warm and r5 is uncached. The last three columns read
lean / **central** / high output.

| Rung | Midday, O1 estimate (19,464), central | End of day, O1 estimate (21,640), central | Midday, real count (23,674), central | **End of day, real count (26,440)**: lean / central / high |
|---|---:|---:|---:|---:|
| h0 | 0.0017 | 0.0017 | 0.0020 | 0.0018 / **0.0020** / 0.0025 |
| r0 | 0.0380 | 0.0382 | 0.0442 | 0.0374 / **0.0444** / 0.0594 |
| r1 | 0.0730 | 0.0732 | 0.0792 | 0.0544 / **0.0794** / 0.1294 |
| r2 | 0.1061 | 0.1065 | 0.1183 | 0.0889 / **0.1189** / 0.1789 |
| r3 | 0.1661 | 0.1665 | 0.1783 | 0.1189 / **0.1789** / 0.2989 |
| r4 | 0.2861 | 0.2865 | 0.2983 | 0.1789 / **0.2989** / 0.5389 |
| r5 | 1.1946 | 1.2164 | 1.2367 | 0.7644 / **1.2644** / 1.8644 |

What the table says:

* **On r0, 96% of the input cost is the uncached 14,105 tokens** (IN-slow, PS
  and the tail). The cache saves $0.024 a call on Sonnet; it cannot save more.
* **From r1 up, output is half the cost or more:** r2 50%, r1 63%, r3 67%, r4
  80%. Effort is the lever there, not the cache.

### 3.5 Input cost by cache state ($ per call, day model's prompt)

| Model | Warm (S, MK read) | MK cold (MK written 1h) | All cold (S, MK written 1h) | No breakpoint | Warm, IN written 5m |
|---|---:|---:|---:|---:|---:|
| Haiku 5.5 | 0.0015 | 0.0031 | 0.0039 | 0.0026 | 0.0017 |
| Sonnet 5.5 | 0.0294 | 0.0622 | 0.0776 | 0.0529 | 0.0323 |
| Opus 5.5 | 0.0589 | 0.1244 | 0.1551 | 0.1058 | 0.0646 |
| Fable 5.1 | 0.1441 | 0.3101 | 0.3878 | **0.2644** | 0.1584 |

### 3.6 The reservation bound per rung, on the 28,325-token prompt

The bound puts every cached token at the 1h write, IN-slow at the 5m write, PS
and the tail at input, and the output at `max_tokens`. The fallback is priced
only where the spec pins it: the list form `[{"model": "claude-opus-5",
"max_tokens": 8000}]` on Opus and Fable. "A mid-stream refusal bills the input
tokens and the output already streamed", plus the rescue (live refusals page).

| Rung | `max_tokens` | Primary bound | Opus 5 fallback (8,000 out) | **Reserve** |
|---|---:|---:|---:|---:|
| h0 | 8,000 | 0.0083 | none (Haiku has no server fallback) | **0.008** |
| r0 | 8,000 | 0.1656 | none in O2a (§6) | **0.17** |
| r1 | 16,000 | 0.2456 | none in O2a | **0.25** |
| r2 | 16,000 | 0.4913 | 0.4141 | **0.91** |
| r3 | 24,000 | 0.6513 | 0.4141 | **1.07** |
| r4 | 32,000 | 0.8113 | 0.4141 | **1.23** |
| r5 | 32,000 | 2.0282 | 0.4141 | **2.44** |

Worked lines:

* **r0:** 12,858 × 4.00 + 6,557 × 2.50 + 8,910 × 2.00 + 8,000 × 10
  = 51,432 + 16,393 + 17,820 + 80,000 µ$ = **$0.1656**.
* **r2's fallback, on Opus 5's card:** 12,858 × 10 + 6,557 × 6.25 + 8,910 × 5
  + 8,000 × 25 = **$0.4141**.

r5 sends no breakpoint, so its true primary bound is 28,325 × 10 + 32,000 × 50
= **$1.88**. The "fallback credit" (live refusals page) only lowers a rescue's
cache cost, never raises it. The reservation is released when the row lands,
so it matters only near the edge of the line.

---

## 4. The wake rates O1's constants imply

O1 **records** wakes. In O2 every recorded wake goes to a model unless F6 makes
it quiet or a cap answers it by code. Detection runs on the bot tick, every 5
minutes (`config/celery.py:453-456`). The census adds W5, W7 and W10 every 5
minutes (`:467-471`).

### 4.1 Per reason, per Orc, per day while the position is held

| Reason | Rule (source) | Per weekday |
|---|---|---:|
| **W2**, the decision bar | each final venue bar of the decision timeframe (`wake.py:163-175`; `dossier.decision_tf`) | 4h: **6**; Mercenary 1h: 24; Olog-hai 1d: 1; a US stock's 4h: about 2 |
| **W11**, the metronome | 4h after the last **W11**, only while the market is open; a stock or ETF also at open + 60 min and close − 90 min; 2h before a weekend (`constants.py:319-322`; `wake.py:296-331`). Its clock resets only on a W11 or the birth (`wake.py:667-669`), **so it is not aligned with W2** | 24-hour market: **6**; a stock: about 3 |
| **W5**, the print clock, **urgent** | T−180, T−60 and T+15 around each high-impact print on the row's currencies; a stock's earnings at T−24h (`constants.py:313-316`; `wake.py:873-943`). Every non-forex row reads USD; forex reads both legs (`situation.py:93-99`). Sources `forexfactory` and `fmp_macro`, impact `high` (`position_care.py:182-187`) | 3 per print time; about 1.5 USD print times a weekday (my estimate, §7) gives **4.5** |
| **W4**, the R thresholds | +1R, +2R, +3R; −0.5R and −0.75R (urgent); the give-back. Each once in a position's life (`constants.py:308-311`) | under 1 |
| **W3**, near invalidation, **urgent** | the mark within 0.1 × ATR(1h) of a `close_beyond` level, at most once per level per 4h (`constants.py:325-328`) | 0 to 2 |
| W6, W7, W8, W9, W10, W1 | the care's stop moves, the book, predicates met, hand edits, doubts, the birth (`wake.py:9-21`) | about 1.5 together |

Non-urgent reasons wait 15 minutes after the last recorded wake
(`constants.py:257`; `wake.py:386-393`). Reasons merge only when one tick holds
them all. So, per Orc and per weekday:

| Orc type | Recorded wakes a day |
|---|---:|
| **4h Orc in a 24-hour market** (forex, index, gold, oil, crypto) | **about 18** (6 + 6 + 4.5 + 1.5) |
| Mercenary (1h) | about 36 |
| Olog-hai (1d) in a 24-hour market | about 13 |
| US stock or ETF | about 11 |

Weekends cost close to nothing outside crypto, because the shut market silences
W2, W11 and W5.

**Bursts.** W2 fires for every 4h Orc together, about 10 to 15 minutes after
00, 04, 08, 12, 16 and 20 UTC: the bar is final at its end plus 600 + 120 s
(`constants.py:190-191`). W5 fires for every USD row at the same offsets.

### 4.2 F6 almost never makes a wake quiet

A wake is quiet only when two things hold (`complexity.py:242-249`):

* every reason is a W2 or a W11;
* the facts hash has not changed since the last *answered* wake.

The hash includes the distance to the next print **in whole hours**
(`wake.py:123-138`). The next print is any high-impact print on the row's
currencies in [now − 1h, now + 72h) (`dossier.py:287-296`). For a USD row that
count changes every hour, weekends included, because Monday's prints are inside
72 hours from Saturday. Two routine wakes 2 to 4 hours apart therefore always
differ.

Moving the calendar distance into bands in a *versioned* hash (more than 24h, 3
to 24h, under 3h) would turn many routine wakes into code readings. Each one
saves about $0.044 (an r0 call).

### 4.3 O1's own caps (display only in O1)

From `weather.py:29-42`:

| Cap | Calm | Eventful | Stormy |
|---|---:|---:|---:|
| Model wakes a day, real money | 12 | 14 | 16 |
| Model wakes a day, paper (paper and demo) | 12 | 12 | 12 |
| Frontier quota, **per (user, class)** | 1 | 2 | 4 |
| Probes | yes | yes | no |

* `MAX_PAPER_ORCS = 10` covers paper and demo together (`constants.py:53-56`).
  Real-money Orcs have no cap on their number.
* **A day is stormy** on a stressed, crisis or recovery posture (only while
  `crisis_mode` measures it), on **three or more high-impact prints today on the
  class's currencies**, or at a day score of 55 or more
  (`complexity.py:320-331`). USD days with NFP, CPI or FOMC carry three
  high-impact rows each. So on USD classes stormy days are common, not rare.

### 4.4 The rung mix (ASSUMED) and where it comes from

The bands are routine < 30, material < 55, complex < 75, then extreme
(`constants.py:244-248`). The band needs 5 points to cross a boundary, and it is
held 60 minutes after an urgent wake (`complexity.py:287-308`).

**A routine 4h wake on a calm day** scores about 15 from the weights
(`constants.py:261-264`):

* prints in 24h: 20 × 0.12 = 2.4;
* the reversibility of an exit on the table, halved in shadow: 37.5 × 0.10
  = 3.75;
* the stop, size, vol, regime, news and disagreement terms add about 9.

The stakes then add 10 for real money and 5 for a hand ticket
(`constants.py:249-252`). So a real-money wake sits near 25. It crosses into
material (35 needed from routine) on:

* a print within 3 h (+3.6 to +9.6);
* a stop within 1 ATR(1h) (+4 to +10);
* decision points (+3.6 to +6);
* a vol spike or a regime flip (+5 to +12).

A real-money birth is raised to complex by floor F2 (`complexity.py:268-269`),
which means r3.

| World and day | r0 | r1 | r2 | r3 | r4 |
|---|---:|---:|---:|---:|---:|
| Real money, calm | 75% | — | 20% | 5% | — |
| Real money, stormy | 35% | — | 40% | 20% | 5% |
| Paper, calm | 92% | 6% | — | 2% | — |
| Paper, stormy | 60% | 30% | — | 10% | — |

An eventful day is taken as halfway between calm and stormy.

**Replace these guesses with the real mix before the line is sized.** `OrcWake`
already stores `score`, `band` and `day_class` for every wake O1 records
(`wake.py:747-760`). See §7.

---

## 5. What a day costs

### 5.1 Assumptions

* **The fleet:**

  | Open positions | Real money | Paper (and demo) |
  |---:|---:|---:|
  | 5 | 3 | 2 |
  | 10 | 5 | 5 |
  | 20 | 10 | 10 (paper's cap) |

  §5.2 gives costs per Orc-day, so any other split is easy to work out.
* **Every Orc is a 4h Orc in a 24-hour market** (18 recorded wakes a weekday),
  on a weekday.
* **Every call is priced on the day model's prompt** (26,440 tokens, §3.1) at
  the §4.4 mix and the §3.2 outputs.
* **h0 probes:** one beside each paper wake on calm and eventful days, at $0.002.
* **r5 at O1's quota for 2 classes** (2, 4 and 8 calls on calm, eventful and
  stormy days), each with its r4 blind twin: $1.26 + $0.30 = $1.56. At 4
  classes, double it.
* **Cache upkeep: about $0.32 to $0.38 a day.**
  * Sonnet writes the day's MK once (MK0, five blocks, MK-E: 8,405 tokens) and
    one cold S plus half an MK (8,132) at (4.00 − 0.10) $/MTok: **$0.065**.
  * Opus pays one cold S plus half an MK per cluster of calls more than an hour
    apart, at (8.00 − 0.20): 5 clusters on a calm day gives **$0.32**, 4 on a
    stormy day **$0.25**.
* **Not included:** the agents O2c and O2d add (the Emperor's daily order, the
  Captains, the council of war, Q&A, post-mortems, the Skeptic's co-sign). A
  rough guess at rung prices: Emperor 1 × r3, 4 Captains × r2, 2 post-mortems ×
  r2, Q&A 0 to 3 × r1. That is about **$1 a day**, to be sized in their own
  spec.

### 5.2 Per model wake and per Orc-day ($, central)

| World, day | Per model wake | Orc-day at 6 wakes | 12 | 14 | 16 | 18 |
|---|---:|---:|---:|---:|---:|---:|
| Real money, calm | 0.066 | 0.40 | 0.79 | 0.93 | 1.06 | 1.19 |
| Real money, eventful | 0.090 | 0.54 | 1.08 | 1.26 | 1.44 | 1.62 |
| Real money, stormy | 0.114 | 0.68 | 1.37 | 1.59 | 1.82 | 2.05 |
| Paper, calm | 0.049 | 0.30 | 0.59 | 0.69 | 0.79 | 0.89 |
| Paper, eventful | 0.059 | 0.35 | 0.71 | 0.82 | 0.94 | 1.06 |
| Paper, stormy | 0.068 | 0.41 | 0.82 | 0.96 | 1.09 | 1.23 |

At high output, a real-money stormy Orc-day of 16 wakes is $2.87 and a paper
stormy day of 6 wakes is $0.63.

Example: real money, calm, 0.75 × 0.0444 + 0.20 × 0.1189 + 0.05 × 0.1789
= **$0.0661**.

### 5.3 The day, for 5, 10 and 20 open positions

Each cell reads lean / **central** / high output, in $ per day.

**A. The wake rates O1's constants imply, with no wake cap.** 18 model wakes per
Orc-day; F6 never quiet; r5 at O1's quota.

| Open positions | Calm | Eventful | Stormy |
|---:|---|---|---|
| 5 | 6.57 / **8.92** / 12.89 | 9.42 / **13.65** / 20.57 | 14.08 / **21.43** / 32.97 |
| 10 | 10.70 / **14.07** / 20.15 | 14.36 / **20.17** / 30.32 | 19.75 / **29.22** / 45.06 |
| 20 | 19.13 / **24.63** / 35.12 | 24.60 / **33.74** / 50.67 | 31.64 / **45.62** / 70.57 |

**B. O1's display caps.** Real money 12/14/16, paper 12, r5 at the per-class
quota.

| Open positions | Calm | Eventful | Stormy |
|---:|---|---|---|
| 5 | 5.14 / **7.12** / 10.32 | 8.05 / **11.84** / 17.86 | 12.99 / **19.93** / 30.65 |
| 10 | 7.89 / **10.55** / 15.16 | 11.62 / **16.55** / 24.90 | 17.42 / **26.03** / 40.13 |
| 20 | 13.51 / **17.59** / 25.14 | 19.11 / **26.50** / 39.84 | 26.97 / **39.24** / 60.72 |

In A and B, **r5 alone is $3.13, $6.25 and $12.51** on calm, eventful and
stormy days. The per-class Fable quota is the first number O2 must change.

**C. The caps a sane O2 would set.** §6: real money 12/14/16, paper 6, r5 off,
triage shares.

| Open positions | Calm | Eventful | Stormy | Under a $10 line |
|---:|---|---|---|---|
| 5 | 2.75 / **3.37** / 4.66 | 3.71 / **4.86** / 7.18 | 4.83 / **6.60** / 10.17 | fits; binds only on a stormy day at high output |
| 10 | 4.75 / **5.88** / 8.23 | 6.43 / **8.47** / 12.62 | 8.35 / **11.48** / 17.78 | fits calm and eventful; binds on stormy days (paper first) |
| 20 | 9.11 / **11.38** / 16.08 | 12.50 / **16.59** / 24.89 | 16.38 / **22.63** / 35.23 | binds every day; paper routine goes first |

### 5.4 Worked example: 10 positions, a calm day, under C, central

| Part | Arithmetic | $ |
|---|---|---:|
| Real money | 5 Orcs × 12 wakes × $0.0661 | 3.96 |
| Paper | 5 × 6 × $0.0492 | 1.48 |
| h0 probes | 5 × 6 × $0.0020 | 0.06 |
| Cache upkeep | Sonnet 0.065 + Opus 5 × 8,132 × 7.80 / 10⁶ = 0.317 | 0.38 |
| **Total** | | **5.88** |

The calls that day:

| Day | r0 | r1 | r2 | r3 | r4 | Model wakes |
|---|---:|---:|---:|---:|---:|---:|
| Calm | 72.6 | 1.8 | 12.0 | 3.6 | — | 90 |
| Stormy | 46 | 9 | 32 | 19 | 4 | 110 |

That is more than one Sonnet call an hour, so S and MK stay warm on Sonnet.

**When the line binds, the cut goes in triage order.** Paper routine goes
first, then paper urgent, then real non-urgent. Real urgent and confirm wakes
keep the whole line and are exempt from the deep share (D30).

---

## 6. The caps a sane O2 would set (my proposal; every number traced above)

| Setting | Value | Why |
|---|---|---|
| A minds switch (for example `orcs_minds`, System) | **OFF on arrival**; it governs only shadow calls | Shadow before power. The live switch (O3+) is a separate, PIN-gated one. |
| `ORC_DAILY_BUDGET_USD` | **0 on arrival.** The operator sets **5.00** for the first week, then **10.00**, or the measured p90 day + 20% | $5 covers 5 positions on any central day (§5.3 C). $10 covers 10 positions on calm and eventful days. |
| `AI_DAILY_BUDGET_USD` | **raise it by cap + floor**: 15 → 23 with a $5 cap, → 28 with $10 | Core = total − Orcs spent − $3 (`spend.py:170, :252`). At 28 the core keeps its 15 even when the Orcs spend their whole cap. |
| Model wakes per Orc-day (D18) | real money **12 / 14 / 16** (O1's `WAKES_PER_DAY`); paper and demo **6** (O1 says 12) | The 4h Orc records 18. Paper evidence is cheaper to come by; real money is what will ever go live. |
| Dollars per Orc-day (D18) | real money **$2.00**, paper **$0.50** | Above the stormy central: 16 × $0.114 = $1.82 real, 6 × $0.068 = $0.41 paper. The high case binds, which is the point. |
| Urgent wakes and the count | Urgent wakes count toward both caps. Once the count is used, a routine wake goes to code; an urgent one still runs inside the dollars, its triage share and the line. | The lost O2a's fix (`day_cap`, recovered notes). |
| Triage shares of the line | real urgent and confirm **100%** (deep-share exempt, D30); real non-urgent **cap − $3 floor** (70% at $10); paper urgent **60%**; paper non-urgent **40%** | The recovered fix set the order and the 60%. The other two are mine, tied to the floor so the last $3 stays for real urgent wakes. |
| Deep share | 70% unchanged (`DEEP_TIER_SHARE`) on r2 to r5, mirrored in O2's own reservation check | `spend.py:264-272` reads only the ledger. |
| Frontier, r5 | **0 in O2a and O2b.** Afterwards at most **1 a day for the whole fleet, not per class**: real money, extreme band, gate passed, with its r4 twin ($1.56) | O1's per-class quota allows $3 to $12.5 a day at 2 classes (§5.3). The ladder is an unvalidated prior (`catalog.py:500-504`). The effort page warns that `max` "can lead to overthinking" on structured-output tasks. |
| h0 probes | paper wakes on calm and eventful days only | `caps_for` turns probes off on a stormy day (`weather.py:41`). $0.002 a probe. |
| `max_tokens` | h0 and r0 8,000; r1 and r2 16,000; r3 24,000; r4 and r5 32,000 | The smoke used 8k and 16k; the provider's default is 32,000. §3.6 prices each. |
| `timeout_s` | h0 and r0 120; r1 and r2 180; r3 300; r4 and r5 600 | The SDK default is 600 s with 2 retries (§1.1). The stall watchdog must allow 3 × this. |
| `fallbacks` | Haiku: none (it has none). Sonnet: **none in O2a**; a refusal is a billed failure, journaled and counted, until the smoke proves `"default"` works with the effort-only message. Opus and Fable: **`[{"model": "claude-opus-5", "max_tokens": 8000}]`** | The list form must be "valid as a direct request to every model named". Opus 5 takes per-message effort and the schema. Sonnet 5.5's default route "is not published", and Sonnet 5 rejects per-message effort with a 400 (live pages). |
| Reservation | the bound per rung (§3.6): r0 $0.17 to r5 $2.44, released when the row lands, expired after 3 × `timeout_s` + 60 s | §2.1. |
| The `orcs` queue and worker | concurrency **2** | Bursts at the 4h closes and the prints (§2.2 item 9). Today's workers are `fast,default -c 3` and `slow,ai -c 2` (`deploy/docker-compose.yml:165, 175`). |
| The day the per-Orc caps count on | **DECIDE.** I recommend the UTC day, so the caps and the line reset together | The line's day is UTC (`spend.py:143-146`); the weather's is the trading day. |

**Cost levers once O2 has measured.**

* **Reset W11 on any recorded wake**, so that "4 hours without a wake" means
  what it says. That removes about 6 of a 4h Orc's 18 wakes. At 10 positions on
  a stormy day under C, it saves about 5 × 4 × $0.114 = $2.3.
* **Put the calendar distance in bands in a versioned F6 hash** (§4.2). Each
  routine wake made quiet saves $0.044.
* **Haiku for routine.** h0 costs $0.002 against $0.044 for r0, 22 times less.
  Move routine to Haiku if the shadow grades show it matching r0.
* **The Batch API at −50%** for work that does not need minutes: post-mortems,
  re-grading. It refuses `fallbacks`, so it is not for O2a wakes.

---

## 7. What O2 must measure before it can trust sections 3 to 5

1. **The band mix and the recorded wakes per Orc-day** (§4.4). O1 already
   writes them. This is read-only and prints counts only:

   ```
   ./deploy/dc exec -T web python manage.py shell -c "from bot_program.orcs.models import OrcWake as W; from django.db.models import Count; from django.utils import timezone as tz; from datetime import timedelta as td; q=W.objects.filter(created_at__gte=tz.now()-td(days=7)); print(q.count(), q.values('orc').distinct().count()); print(list(q.values('orc__paper','day_class','band').annotate(n=Count('id')).order_by('orc__paper','day_class','band'))); print(list(q.values('status').annotate(n=Count('id'))))"
   ```

2. **The real token counts.** Count stored `OrcDossierBlock` texts with
   `count_tokens`, which is free and never ledgered. Do it from a new command,
   because the O1c modules are pinned against it. Count S when it is written:
   it must fit the 3,930 reserve. Watch the 1.27 factor of §3.1, and the
   session blocks over their cap.
3. **Output tokens per rung, p50 and p90**, from the first week of `AgentTask`
   rows by `source_ref` rung. Then size the line again from p90, not from §3.2.
4. **The smoke's C2/C3 verdict** per model, written where the router reads it.
   Without a PASS, change effort per epoch only.
5. **One paid smoke call on Sonnet 5.5 with `fallbacks="default"` and the
   effort-only message**, before Sonnet uses any server fallback. The docs do
   not say whether the default route keeps the message.
6. **The refusal and invalid-answer rate per rung**, and the cache-read share
   per model (§2.2 item 12).
7. **The high-impact print times per weekday per currency**, from
   `EconomicEvent` (`source in (forexfactory, fmp_macro)`, `impact = high`).
   This checks the 1.5 USD print times a day in §4.1.

---

## 8. Files

* This map: `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/orcs2/map_ai.md`
* The arithmetic, which prints every table in §3 and §5:
  `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/orcs2/calc/map_ai_costs.py`
* Companion: `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/orcs2/map_wakes.md`
  (the wakes, the dispatch seam and the dossier hooks).
