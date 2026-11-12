# THE LORE — exact map at main 15dd487 (2026-11-07)

Read from the read-only export `scratchpad/lore/tree` (all paths below are repo-relative, `file:line`).
Verified by running code, on a COPY (`scratchpad/lore/run/tree`, SQLite, no model call, no network):
the five Lore test modules pass (`Ran 109 tests … OK (skipped=1)`, the skip is the git check-ignore test, no `.git` in the export),
and a scratch test file (`scratchpad/lore/run/tree/tests/test_zz_map_checks.py`) checked the behaviours quoted in §2 and §3.
History: the whole app is one commit, `bcb0e42` (2026-10-15), merged as PR #60 (`555a64d`, 2026-10-16). Nothing under `lore/` or `templates/lore/` changed since.

---

## 0. In one paragraph (the answer to his question)

The Lore is **not** an independent, prophetic voice. In the code it is a **passive, staff-only library**: entries about strategies, fund playbooks, past episodes and concepts, written "in our own words" with sources. Each claim is filed as *documented*, *reputed, not proven* or *breaks when*. It never speaks, never predicts, makes no model call, has no Celery task, and writes nothing by itself. Rows arrive only by a file import or by hand in the admin, always as DRAFT. No agent reads a row until a person ticks five checks and clicks "Mark reviewed". Exactly two readers exist, each behind a switch that is OFF on arrival: `lore_staff` (Ask Sauron, staff web questions) and `lore_background` (the 06:00 UTC strategist, as unquoted background). It can change no rule, gate, size, limit or order. The "Sauron's lesson" kind (Sauron's own record) and its writer ("the distiller") are vocabulary only, with no writer anywhere. What he describes, a voice that people observe, fear and support, is the **Prophecies** (task #106) plus the **Court** (task #105): studied, not built. Their only traces are the empty `"prophecies": "—"` in the Orcs' market dossier (`bot_program/orcs/dossier_market.py:139-142`) and `"prophecies — (not built)"` in the synthetic smoke dossier (`ai_agents/management/commands/claude_smoke.py:169-170`).

---

## 1. What the Lore is, and is not

### 1.1 The app and its rows
- App: `lore` ("The Lore", `lore/apps.py:4-11`: "Reference data for agents, never an instruction"), installed at `config/settings.py:131-133`.
- `LoreEntry` (`lore/models.py:18-118`): slug, kind, title, summary, mechanism, works_when, markets_text, small_account_can/cannot, evidence_grade, six `"|a|b|"` facet columns (tags, classes, regimes_works, regimes_breaks, horizons, families), code_refs, origin, status, audience, proposed_by, review fields, version, content/imported/reviewed sha, search_text. "No numeric field … other than version and position" (`lore/models.py:3-8`). Custom permission `review_loreentry` "Can mark a library entry reviewed" (`lore/models.py:73-74`).
- `LoreSource` (`:121-155`): position S1..Sn, title, by, url, date_text/date_kind, kind, note, quote ≤300, `found_via` default "search_summary" (`:138-139`), checked_on/by.
- `LoreClaim` (`:158-176`): side documented/reputed/breaks, text, basis ("believed but not proven; say why"), episode ("Seen in"), sources (1-based positions).
- `LoreLink` (`:179-192`): related / illustrates / contradicts.
- `LoreRevision` (`:195-214`): append-only history ("supersede, never edit").
- `LoreRead` (`:217-241`): the ledger, one row per non-empty block an agent received. It stores the terms and a sha1 of the question, "never the question itself".
- Migration `lore/migrations/0001_initial.py`: schema only (a test pins "the migration holds no data", `tests/test_lore_library.py:487`).

### 1.2 Vocabularies (`lore/constants.py`)
| Item | Values | Line |
|---|---|---|
| Kinds | strategy, fund_playbook ("Fund playbook"), episode, concept, lesson ("Sauron's lesson") | `:14-20` |
| Importable kinds | strategy, fund_playbook, episode, concept ("`lesson` is written only by the distiller") | `:22-23` |
| Origins | world ("The world"), sauron ("Sauron's own record") | `:25` |
| Statuses | draft, reviewed, retired, rejected | `:26-31` |
| Audience | **one value only**: staff ("Staff only") | `:33` |
| Proposers | seed, staff, distiller ("the distiller"), keeper ("the keeper") | `:34-39` |
| Evidence grades | strong, moderate, weak, none | `:40-45` |
| Claim sides | documented, reputed ("Reputed, not proven"), breaks ("Breaks when") | `:71-75` |
| Revision vias | import, admin, review, draft, retire, restore, reject, distill, keeper | `:81-85` |
| Regimes / classes / families | the Mind's regimes minus unknown (risk_on, risk_off, mean_reverting, trending, blow_off), `core.constants.AssetClass`, the proving ground's 20 families | `:118-135` |

### 1.3 Who writes "lesson" rows: the distiller does not exist
- **Not built.** There is no module, no Celery beat entry (`config/celery.py` has no lore/distill entry), no `PlatformComponent` switch (the only Lore rows are `lore_staff`/`lore_background`, `core/platform_control.py:198-207`), no command, and no code path that writes `kind="lesson"`, `origin="sauron"` or `proposed_by="distiller"`/`"keeper"`. A grep over non-test code finds only the vocabulary.
- `lore/` makes no model call and has no task (grep for provider/complete/anthropic/BaseAgent/shared_task in `lore/` is empty). `tests/test_llm_ledger_truth.py:78-80` scans `lore` "so the keeper's call is caught the day it lands". So **"the keeper" is a planned model-calling proposer, also not built.** (Elsewhere in the code "keeper" means the human second keeper, Gandalf, `core/passation.py:7-8`, or the Saxo session keeper. Neither is related.)
- What the lesson rules already say (for a future distiller): imports cannot create Sauron lessons (V26, `lore/validate.py:161-162`). Only a lesson may cite an internal "record" source, whose URL must start with "/" (V23, `:225-230`). A lesson cannot carry a money amount or a long identifier ("say it in R, rates and counts", V15, `:334-337`). Lessons are read only by the research reader (`lore/policy.py:17, 34-35`). The strategist never sees them (world kinds and origin only, `:18, 36-37`; proven in `tests/test_lore_readers.py:243-266`).
- Today a person *could* hand-write a lesson in the admin (the admin mode does not apply V26). No code does.

### 1.4 The curate path (human curation)
`lore/curate.py`: the canonical export dict and the content sha256, with review/state fields and `related` left out (`:33-157`); search text (`:162-181`); `refresh` (`:184-193`); append-only revisions (`:198-204`); writing from a dict (`:209-270`, every source lands as "search summary only"). Then the transitions: `REVIEW_CHECKS` (`:279-289`), `mark_reviewed` (`:292-316`), `set_status` (`:319-331`), `mark_source_opened` (`:334-342`), and `content_changed_in_admin` (`:345-360`), which bumps the version and sends a reviewed entry back to draft when the text moved.

### 1.5 The pages
- URLs: `/lore/` (index), `/lore/<slug>/` (entry), `/lore/<slug>/review/` (POST) (`lore/urls.py:7-11`), mounted before the catch-alls (`config/urls.py:33-35`).
- Access: every view is `@staff_member_required` (`lore/views.py:50, 136, 184`). That means an active login with `is_staff`. Others are redirected to the admin login, and investors are held by the investor gate before this (`lore/views.py:1-3`). Responses are private and no-store (`:30-32`). The nav link "The Lore" (❧) shows to staff only (`templates/base.html:547-548`). The review action also needs the `lore.review_loreentry` permission (`lore/views.py:189-192`; a superuser has it).
- Index (`templates/lore/index.html`): lead "Sauron's library … Staff only." and "Reference data. Nothing here can change a rule, a gate, a size, a limit or an order." (`:35-36`). Strip: ENTRIES (reviewed · drafts · retired), SOURCES (opened by a person · search summary only), AGENTS ("Ask Sauron (staff, web): on/off · Strategist background: on/off"), LAST READ (`:38-64`). Search with Kind / Regime / Asset class / Horizon / Evidence / Status filters and "Relevant to the current regime (…)". Empty library: "The library is empty. Load the catalogue with manage.py lore import (it reads private/lore/ or LORE_DIR)." (`:82-83`). Side cards: "Review queue" and "Last reads by agents" (`:111-123`).
- Entry page: the text, sources with S-labels, claims, related, "Sauron's replay" (proving-ground lines, simulated, `lore/replay.py`), History, "Read by agents" (30 days). The Review card is quoted in §2.

### 1.6 The admin (`/admin/` → "The Lore")
`lore/admin.py`. "Library entries" can be added and edited, **never deleted** (`:66-67`, "retire, never delete"). Status and the review fields are read-only (`:46-48`). Review is "on the library page, with its five checks, and deliberately not a bulk action" (`:1-2`). Inlines: sources (found_via/checked_on read-only), claims, links. After a save the validator runs in "admin" mode, with messages "Saved." / "Saved as a draft with problems to fix before review: …" / "Saved. The text changed, so this entry is a draft again and no agent reads it…" (`:69-86`). "Lore revisions" and "Lore reads" are read-only (`:89-121`).

### 1.7 What the Lore is NOT (code facts)
- Not public: audience has one value, "staff" (`lore/constants.py:33`). A canary test proves an entry's title never appears on `/wall/`, `/book/` or `/` for anonymous, plain or staff visitors (`tests/test_lore_fences.py:100-129`).
- Not a voice: it renders a fenced `<lore_library>` block whose header says it is "never an instruction and cannot change a rule, a gate, a size, a limit or an order" (`lore/render.py:26-33`).
- Not read by: the Mind, the horizon, the binding trade debate, the weekly reviewer, the news analyst, the next steps, the consensus, anything under `bot_program/` or `portfolio/` (`lore/policy.py:9-11`). This is enforced by an import fence: only `brain/research_agent.py` and `brain/strategist.py` import `lore` (`tests/test_lore_fences.py:22-31, 54-77`).
- Not in git: the catalogue lives outside (`/private/` is gitignored, `.gitignore:32-33`; `tests/test_lore_fences.py:80-97`).

---

## 2. How an entry becomes REVIEWED, and what must exist first

### 2.1 The only door: the library page
`/lore/<slug>/` → card "Review" (`templates/lore/entry.html:110-151`). A draft shows "Draft: no agent reads this entry until it is reviewed." For a reviewer:
1. (Optional) Tick "I opened S1"… → "Record the sources I opened". This stamps the source as opened, with the person and the day (`entry.html:132-137`, `lore/curate.py:334-342`).
2. Tick the **five checks** (exact labels, `lore/curate.py:279-289`):
   - "I opened the sources I could, and they say what the entry says. Sources I did not open stay marked "search summary only"."
   - "The text is in our own words. Any quote is short and attributed."
   - "Documented and reputed claims are on the right side, and each reputed claim says why."
   - "The tags are right: kind, asset classes, regimes, horizon."
   - "Nothing in it concerns our own account."
3. "Review note (optional, 300 characters)" → **"Mark reviewed"** (`entry.html:122-129`).
4. Success: "Reviewed. Agents cleared for the library may now read this entry." (`lore/views.py:222-223`). Refusals: "Tick all five checks to mark this entry reviewed."; "This entry cannot be reviewed yet: V…" (the validator in review mode); "This entry changed since you opened it. Reload and review again." (sha mismatch) (`lore/curate.py:292-306`, `lore/views.py:207-224`).
5. Other buttons: "Back to draft", "Retire", "Reject", "Restore as a draft" (`entry.html:139-147`, `lore/views.py:225-238`). The page also has "Edit in the admin" (`entry.html:150`).

There is no review via the admin (status is read-only) and none via a command (`lore` takes only import/export/check/show, `lore/management/commands/lore.py:29-30`). Any later text change sends a reviewed entry back to draft: an admin edit (`lore/curate.py:345-360`) or a changed re-import (`lore/importer.py:179-184`).

What review mode requires (`lore/validate.py:147-357`): valid kind and slug (3-60 characters, lowercase, hyphens, not reserved); title; summary of 4-8 sentences (V03); mechanism and works_when (V04); length caps (V20). A world entry needs ≥1 source with an http(s) URL, title, author/publisher, a date in YYYY / YYYY-MM / YYYY-MM-DD and a date kind (V05-V07, V22). It needs ≥1 documented claim citing an existing source (V08); every reputed claim needs a "basis" (V09); vocabularies must be valid (V16-V19, V21). **V27: asset classes tagged, and a horizon for a strategy.** Text rules everywhere: no quoted run of 200+ characters (V11); no `<<`, `>>`, triple backticks, `lore_library` or `<tag` (V12); English only (two or more French function words, or >1% non-ASCII letters outside capitalised names, fails V13); no "our/my/your/the operator's account|balance|equity|book|portfolio|positions|trades" (V14); no private term (V24, read from `LORE_PRIVATE_TERMS` or `LORE_DIR/private_terms.txt`, `:69-88`).

### 2.2 Is a reviewed entry possible WITHOUT a catalogue? Yes, by hand in the admin
Verified on the copy (scratch test `test_admin_then_review_then_read`):
- `/admin/lore/loreentry/add/` → fill Identity (slug, kind, title; origin "world"), the text fields, the facets **with pipes** (for example `index|forex`; a comma would make one unknown class), and evidence grade. Add one **source** row (position 1, title, by, url `https://…`, date_text `2012-05`, date kind, kind e.g. paper) and one **claim** row (side documented, position 1, text, Sources `[1]`). Save → "Saved." → the entry exists as draft (version 2).
- Then on `/lore/<slug>/` tick the five checks → "Mark reviewed" → status reviewed ("Reviewed. Agents cleared for the library may now read this entry.").
- With the inlines missing, the admin answers "Saved as a draft with problems to fix before review: V05 … V08 …" and review is refused with the same codes (seen in the scratch run).
- Any later admin edit sends it back to draft (seen: `{'changed': True, 'back_to_draft': True}`).

### 2.3 The catalogue (the 50-70 entry seed): where it would live and its format
- **Where:** `settings.LORE_DIR` = env `LORE_DIR`, else `BASE_DIR/private/lore` (`config/settings.py:139-141`). In the container that is `/app/private/lore` (`Dockerfile.prod` WORKDIR /app). `private/` is gitignored but **not** dockerignored, so `COPY . /app` (`Dockerfile.prod:56`) puts it in the image **at build time only** (`.gitignore:32-33`: "private/ on a checkout, copied into the image, never committed"). `deploy/docker-compose.yml` mounts no volume for it. **Files placed in `~/Sauron_Vision/private/lore/` reach the web container only after `./deploy/dc up -d --build`.**
- **Status today:** no seed text in git (`tests/test_lore_fences.py:93-97`) and none on this container's disk. The code was written against a real seed ("the seed's longest summary is 1,215", `lore/constants.py:103`). Whether a copy exists on his VPS or his PC is unknown; the read-only dry run in §6 tells.
- **Files read** (`lore/importer.py:68-96`): a single file, or a directory of `*.json` read in sorted order, skipping names that start with `export-`. `seed_overlay.json` is the overlay (applied unless the entry carries the key inline, `:99-108`). Each file holds a list of entries, `{"entries": [...]}`, or one entry object. The tests name the expected trio: `private/lore/seed.json`, `seed_overlay.json`, `private_terms.txt` (`tests/test_lore_fences.py:88-92`). Private terms: one per line, `#` comments (`lore/validate.py:69-88`).
- **Entry schema** (`lore/validate.py:27-37`; canonical shape `lore/curate.py:90-142`; a working stand-in at `tests/test_lore_library.py:29-60`):
  - core keys: `slug, kind, title, summary, mechanism, works_when{regimes (text), asset_classes [display strings]}, fails_when[{how, episode, src[]}], evidence[{title, by, url, date, type, note, date_kind, quote}], documented[{claim, src[]}], reputed[{claim, basis, src[]}], evidence_grade, related[slugs], small_account{can, cannot}, sauron_code[{ref "path:line", note}], tags[], accessed "YYYY-MM-DD"`;
  - overlay keys (inline or in `seed_overlay.json` by slug): `asset_classes, regimes_works, regimes_breaks, horizons, families` (platform vocabularies);
  - accepted export keys (ignored on import): `status, reviewed_at, proposed_by, origin`. `origin: "sauron"` is refused (V26), and a source carrying `found_via` is refused (V25, `:215-220`);
  - `src` indices are **0-based** in the file and become 1-based S-labels in the rows (`lore/curate.py:225-238`).
- **What an import does:** each entry runs through the validator in import mode, then is created / updated / kept / same / refused in its own transaction. Every created row is `status="draft"`, `origin="world"`, `proposed_by="seed"` (`lore/importer.py:162-189`). A row edited on the platform since the last import is "kept" unless `--force-slug`. `related` links are made both ways; an unknown related slug or a drifted code reference is a warning (`:203-230`). The command exits non-zero if anything was refused (`lore/management/commands/lore.py:69-71`; in a dry run that message still says "the others were imported", but nothing is written).

### 2.4 Exact commands (verified on the copy; on the box prefix `cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py …`)
| Command | Effect | Output seen |
|---|---|---|
| `component list --category agent` | read | `  OFF  lore_background                    Lore: background readers` / `  OFF  lore_staff                         Lore: staff readers` |
| `lore check` | read: DB rows in review mode | `All 0 entries pass.` (or `  slug: V27 …` + `N problems in M entries.`) |
| `lore check private/lore` | read: a catalogue in import mode | per-entry problems |
| `lore import --dry-run` | read: nothing written | `No catalogue at /app/private/lore. Put the files in private/lore/ or set LORE_DIR.`, or `Read N entries from …` + `created … (draft)` lines + `Nothing written (dry run).` |
| `lore import` | writes drafts | as above, without the dry-run line |
| `lore show research --viewer <username> --query "…"` | read (no ledger row) | **`Empty block: switch off.` while lore_staff is OFF, whatever else is given** (the switch is checked first, `lore/read.py:126-127`), so it cannot preview before the switch is on. Once ON: `Empty block: viewer is not staff.` without `--viewer`, `Empty block: nothing matched.` with no reviewed match, else `Block: N entries (k cards, m short), about T tokens of a 3000 cap.` |
| `lore show strategist --regime trending` | read | `Empty block: switch off.` while OFF |
| `lore export [PATH]` | writes a JSON file (default `LORE_DIR/export-YYYYMMDD.json`, inside the container) | `Wrote N entries to …` |

Note: the `lore` command is **not** in the `/ops/` command registry. `core/ops_commands.py` covers bot_program/brain/signals/core only (`:17-20`), so the operator learns it from `--help` or this map.

---

## 3. The two switches, exactly

Both are `PlatformComponent` rows in the **Agents** group, OFF on arrival (`core/platform_control.py:198-207`; `seed_components` never touches `is_enabled`). Neither is a PIN switch or a live-money switch. "All on" never arms them (`BULK_ENABLE_EXEMPT`, `:142-154`). /ops/ says so beside the group: "all on leaves … OFF — each is a decision of its own … by its own toggle or `component on <key>`" (`templates/dashboard/ops.html:106-109`; `dashboard/views_ops.py:103-124`). To turn one on: /ops/ → Agents → row `lore_staff` / `lore_background` → "turn on" (no PIN), or `component on lore_staff`. A missing row reads OFF (`core/platform_control.py:72-77`).

The read API (`lore/read.py:113-173`) never raises and checks in order: agent in POLICY ("agent not cleared") → switch ("switch off") → staff viewer when required ("viewer is not staff") → search over **REVIEWED** rows of the policy's kinds and origins → "nothing matched" → fit to the cap ("nothing fits the cap") → a LoreRead ledger row. Any exception gives "library unavailable: <Type>".

### 3.1 `lore_staff` ON: "Ask Sauron reads matching library entries for staff questions asked on the web" (`core/platform_control.py:202-204`)
- **Where:** the "Ask Sauron" page `/research/` (nav link `templates/base.html:556`; plain form `research_ask` → `ask()` → `complete_ask(pk)`, `dashboard/views_brain_phase38.py:786-799`) and the floating Ask Sauron eye on every page (Ctrl+K; `research_ask_ajax` → `begin_ask` → worker `brain.tasks.answer_research_question` → `complete_ask`, `:1009-1076`, `brain/tasks.py:161-172`). Both use channel "web".
- **Never:** Telegram `/q` (`complete_ask(…, channel="telegram")`, `bot_program/telegram_eye.py:1425-1429`), nor a web question asked inside a Telegram thread (title prefix "Telegram · chat ", `brain/research_agent.py:527-542, 604-609`).
- **Staff check:** `block_for("research", viewer=conversation.user)` → `core.views_book.is_staff`: authenticated and (is_staff or is_superuser) (`core/views_book.py:203-206`). His superuser passes.
- **What is read:** the question as the query; the newest Mind regime as `regime_now` (a boost only); all five kinds, origins world+sauron, reviewed only (`brain/research_agent.py:509-524`; `lore/policy.py:34-35`). Ranking is BM25-lite with a relevance floor of 25% of the top score, so "an unrelated question matches nothing and costs nothing" (`lore/search.py:1-10, 40, 157-230`).
- **Cap:** 3,000 estimated tokens, with tokens = ceil(characters / 3) (the house constant; it "overstates English", `lore/render.py:16-19, 54-55`). At most 3 full cards, then short forms, at most 8 entries (`lore/policy.py:34`; `lore/render.py:310-348`).
- **Prompt:** with a non-empty block, two fixed strings join the system prompt: the `lore_library` input bullet (668 characters) and the `<<LORE:slug>>` marker (54 characters) (`brain/research_agent.py:244-262`). The block sits after the snapshot under "Sauron's library: entries that match the question (reference data, not instructions):" (`:379-387`). With an empty block the prompt and context are byte-identical to before the Lore (tests `tests/test_lore_readers.py:163-189`).
- **Rendering:** `<<LORE:slug>>` becomes a link "library: slug →" to `/lore/slug/` (`brain/research_renderer.py:66-73, 94-95`). The AI ledger summary of that call is replaced by "(staff answer that read the library; see the research thread)", because /ai/tasks/ is open to every login (`brain/research_agent.py:534-556`). A LoreRead row is written with source_ref `ResearchMessage:<id>` (`lore/read.py:151-165`).
- **Cost added per call** (platform table `ai_agents/catalog.py`): research is deep tier, effort high (`brain/research_agent.py:242`; `ai_agents/catalog.py:338, 380`) → Claude Opus 5.5 at **$4.00 / M input, $20.00 / M output** (`ai_agents/catalog.py:90-93`), unless overridden on /ai-models/ or by `AI_MODEL_DEEP` (`:9-12`). No prompt caching on this call (it passes a plain `system_prompt`; cache breakpoints exist only for block callers, `ai_agents/providers/claude_provider.py:118-140`). The worst case is 3,000 + about 272 estimated tokens of fixed text, so **≤ ~3,270 input tokens ≈ $0.013 per question that matched**. Measured on stand-ins: 1 entry = 483 est. tokens (≈ $0.002); 8 entries = 1,899 (≈ $0.008). Real seed entries are longer and would approach the cap. Output may grow slightly (citations; $0.002 per 100 tokens). Baseline: "~$0.10-0.30" per question (`brain/research_agent.py:23`); budget check `can_spend(tier="deep", estimated_usd=0.3)` (`:591`).

### 3.2 `lore_background` ON: "The strategist reads library entries for the current regime as unquoted background; its briefing never names or quotes them" (`core/platform_control.py:205-207`)
- **Which run:** the beat `sauron-strategist-daily`, **06:00 UTC daily** (`config/celery.py:179-182`) → `brain.tasks.run_strategist`. It has **no component switch**, only `@spend_guard(tier="deep", estimated_usd=0.3)` (`brain/tasks.py:59-65`). The other trigger is the staff button "▶ Run strategist now (admin)" on /briefing/ (`templates/dashboard/briefing.html:163-172`, `dashboard/views_brain_phase38.py:512-525`). The run is skipped (no model call, no Lore read) when the newest brain report is more than 12 h old (`brain/strategist.py:675-695`).
- **What the briefing is** (`brain/strategist.py:348-366, 491-573`): `outlook_md` (1-3 paragraphs); `posture` defensive|balanced|aggressive, which is "advice to the operator and sizes nothing" (`:402-413`); `posture_rationale`; `watchlist` ≤5 (kind, ref, what_to_watch); `ideas` ≤5. Ideas with `hypothesis_kind` are posted as Hypothesis rows and graded. Model: Opus 5.5 deep, effort high (`:3, 373`; `ai_agents/catalog.py:378`), "~$0.30/day" (`:20`).
- **What it reads:** world origin only, kinds strategy/concept/episode/fund_playbook, **short forms only** (0 cards), at most 6 entries, cap **1,500** estimated tokens (`lore/policy.py:36-37`). Filters are the Mind's newest regime (works in OR breaks in) and the newest report's top concerns as query words (`brain/strategist.py:578-604`). So an entry with no regime tag never reaches it while the regime is known, and with concern words an entry must also match them.
- **Prompt:** the system prompt gains the "LIBRARY (background only)" rule (590 characters): "do not quote it, do not name an entry, its title or its slug, and do not write <<LORE:…>> markers" (`brain/strategist.py:375-389`). The block sits after the snapshot (`:456-468`).
- **The scrub** (`lore/guard.py:18-91`): before anything is saved, pushed or posted as a hypothesis, `outlook_md`, `posture_rationale` and **every string** inside `watchlist` and `ideas` lose `<<LORE:…>>` markers, library tag fragments and the hyphenated slugs of shown entries. They also lose **every sentence sharing an 8-word run with the shown block** (`brain/strategist.py:734-738`). If the scrub itself fails, it **fails closed**: the briefing keeps only its posture (`:607-619`). The AI ledger keeps the scrubbed JSON, or "(strategist output that read the library; not kept)" on failure (`:622-639, 719-725`). An error shows only its type (`:719-722`). The ledger row records `source_ref StrategistBriefing:<id>` and the `scrubbed` count (`:642-649`; `lore/read.py:197-213`).
- **Cost added per run:** ≤ 1,500 + ~197 estimated tokens ≈ **≤ $0.007 per briefing** at $4/M, so **≤ ~$0.21 a month**. Measured: 6 short stand-ins = 962 tokens (≈ $0.004).

### 3.3 Either switch ON with ZERO reviewed entries
Verified (`test_zero_entries_switches_on`): `block_for("research", …)` → reason **"nothing matched"**, 0 tokens, empty text. `block_for("strategist", …)` → **"nothing matched"**, 0 tokens. **LoreRead rows: 0.** The callers then build the old prompt (`lore=bool(lore_text)` is False), byte-identical, so **cost $0**: only a few cheap SQL reads (the switch row and one filtered query). The /lore/ AGENTS cell would say "on" and "LAST READ: Never". A query with no searchable words also returns "nothing matched".

---

## 4. Decision D1: where the strategist's briefing goes

D1 as written: "lore_background only after decision D1 (the briefing reaches readers who are not staff)" (`core/platform_control.py:144-146`; `tests/test_lore_pages.py:299-301`).

| Reader of the briefing | What of it | Who can see it | A non-staff person with ONE account (his superuser)? |
|---|---|---|---|
| `/briefing/` (`@login_required`, `dashboard/views_brain_phase38.py:418-511`) | everything, any past briefing via `?id=` | any login | **no**, only his login |
| `/intelligence/` (`@login_required`, `:1229-1244`; template `intelligence.html:58-64`) | posture, outlook ≤600 characters | any login | no |
| Council band, "on the right edge of every staff page" (`dashboard/council_band.py:1-3, 943-963`; view `@login_required`) | posture title, rationale ≤160 | logins | no |
| Bell row (each opted-in user, `bot_program/notifications.py:413-431`) | title, outlook ≤800, rationale, ≤3 idea summaries | that user | no |
| **Telegram push** (`notify_strategist_briefing_to_all`, `bot_program/notifications.py:2375-2490`, called at `brain/strategist.py:751-758`) | same text | **every member of the chat at his `telegram_chat_id`**, which the code calls the group "Sauron Vision" (`bot_program/telegram_eye.py:4-8`) | **YES if the group has other members.** It is sent only if "Daily Sauron's Mind briefing (06:00 UTC)" is ticked (`receive_strategist_briefing`, default **False**, `alerts/models.py:203-204`; UI `templates/dashboard/user_notifications.html:35` on `/notifications/settings/`), his channel is telegram (`portfolio/trader_profile.py:85-90`), and outside his quiet hours (`notifications.py:433-438`) |
| Email push (`notifications.py:468-477, 768-784`) | HTML briefing | his inbox | no |
| Discord push (`notifications.py:478-480, 787-800`) | title + body | the webhook's channel | yes if that channel has others |
| Hypotheses from ideas (`brain/strategist.py:534-573`) | claim text = idea summary | `/hypotheses/` (`@login_required`, `views_brain_phase38.py:205-206`) | no |
| AI ledger `AgentTask.response_summary` (scrubbed) | scrubbed JSON | `/ai/tasks/` (`@login_required`, `dashboard/views.py:3526-3527`); `/api/ai/tasks/` staff only (`dashboard/api/ai_views.py:1-33`) | no |
| Research snapshot `latest_briefing` (`brain/research_agent.py:131-151`) | staff web: full. **Telegram `/q`**: posture, watchlist kinds/refs, ideas minus summary, no outlook (`:47-60`) | his /research/; **the group via `/q` answers** | partly: no prose, only posture and refs, already scrubbed |
| Orcs' market dossier, MK8 and MK-now "brief" (`bot_program/orcs/sources.py:383-413`; `dossier_market.py:196-208, 357`) | posture, rationale ≤500, outlook ≤600, watchlist strings, idea titles | the Orc Minds (models, shadow; `core/platform_control.py:122-127`), which he turned on today | not a person. This is a second-hand path for the library's influence into a model that is otherwise a never-reader; shadow only |
| Public pages `/wall/`, `/book/`, `/` | nothing (canary test, `tests/test_lore_fences.py:100-129`) | anyone | no |
| Weekly newsletter (`alerts/newsletter_service.py:290-364`) | not the briefing (it is the weekly review, a never-reader) | — | — |
| Monday plan, next steps | do not read the strategist briefing (`ai_agents/monday_plan.py`, `ai_agents/next_steps.py:47-53` read daily_briefing/weekly/monday/eod) | — | — |
| Nav activity dot (`dashboard/views.py:5628-5630`) | a timestamp only | — | — |

Not to confuse: the old "Morning Briefing" (`ai_agents.tasks.generate_daily_briefing`, switch `agent_daily_briefing`) goes to every active account's bell via `Notification.create_for_all` (`ai_agents/tasks.py:707-783`). It is not the strategist and not a Lore reader (`ai_agents/tasks.py` is on the NEVER list, `tests/test_lore_fences.py:28-31`).

**Is the Telegram group staff-only? No, by the code's own words.** "The Lore is staff-only, and the group is not" (`bot_program/telegram_eye.py:1359-1361`). "The group can hold people who are not staff" (`:1426-1428`; `brain/research_agent.py:51-53, 510-513`). The platform chat (TELEGRAM_CHAT_ID, "the group the Eye answers in") carries release notes that "the viewers and the loyals read" (`core/announcements.py:4-5, 13-14`). The Eye authorises by **chat id only**: any human member of that chat can use its commands (`telegram_eye.py:28-34, 555-581, 1532-1566`). The second keeper (Gandalf) "keeps the house on the same account" (`core/passation.py:7-8`), so on the platform he counts as staff.

**Conclusion for ONE account.** On the platform's pages, no non-staff person can read the briefing: every login is his account, staff by the code's rule, whoever holds it. Off the platform, **one real channel exists: the briefing push to his Telegram chat** (or a Discord webhook). It applies only if "Daily Sauron's Mind briefing (06:00 UTC)" is ticked and his channel is telegram/discord, and it matters only if that chat holds anyone besides him and the bot. A minor second route is `/q` in the same group, which exposes posture and watchlist refs but no prose. The library's own words never reach the group: there are three guards in the Eye, and the briefing is scrubbed and forbidden to quote. So with one account, D1 shrinks to one fact he can check: who is in that Telegram group, and does the briefing go there.

---

## 5. The nine files, and what each says or does about the Lore

| File | About the Lore |
|---|---|
| `core/announcements.py` | Nothing about the library. Its "lore" means the house narrative of Telegram release notes ("with great styling and lore", the folded "who-is-who": Sauron, Morgul, Aragorn…) (`:1-17, 89-95`). Useful D1 fact: those notes go to TELEGRAM_CHAT_ID, "the group the Eye answers in", read by "the viewers and the loyals" (`:4-5, 13-14`). No `lore` import. |
| `core/management/commands/announce.py` | Same narrative sense ("the release notes the viewers read, in the house style, with the lore", `:1-2`). It sends `october_turn` to the Telegram group. No library. |
| `core/ops_commands.py` | Only the "announce" registry row says "lore", in the same narrative sense (`:668-680`). The Lore's own `manage.py lore` command is **not** in the registry (its scope is bot_program/brain/signals/core, `:17-20`), so /ops/ does not list it. |
| `dashboard/views_ops.py` | `_switches`: the two Lore readers are in each group's "held" list because they are in `BULK_ENABLE_EXEMPT` (comment `:103-109`, code `:110-124`). The page prints "all on leaves … OFF — each is a decision of its own" and gives a plain "turn on" toggle without a PIN (`templates/dashboard/ops.html:106-109, 127-129`). `:207 def research()` is about the research fleet (bots), not the Lore. |
| `bot_program/telegram_eye.py` | Three guards so the library never reaches the group. A Telegram thread uses the research agent's prefix, so it never gets the block, "even for a question asked on the web" (`:1271-1275`). The `LORE` marker is dropped from group text, "the Lore is staff-only, and the group is not" (`:1359-1361`). `/q` answers call `complete_ask(…, channel="telegram")`, "the staff owner's clearance is not the reader's" (`:1425-1429`). |
| `brain/research_agent.py` | **Reader #1** (`research`). The prompt strings (`:244-262`), the block placement (`:379-387`), `_lore_block_for_ask` (`:509-524`), the Telegram-thread rule (`:527-542`), the ledger scrub (`:534-556`), and channel "web" only with the staff snapshot rule (`:559-611`). It also withholds strategist and Mind prose from non-staff and Telegram snapshots (`:43-60`). |
| `brain/research_renderer.py` | `<<LORE:slug>>` becomes a markdown link "library: slug →" to `/lore/<slug>/` when the value is slug-shaped ("the page is staff-only in any case"); anything else stays verbatim (`:66-73, 94-95`). |
| `ai_agents/agents/strategy_mutator.py` | **Nothing.** The only grep hit is "explore the space" (`:47`). It does not import `lore` (import fence `tests/test_lore_fences.py:54-57`) and is not a reader. |
| `core/book_content.py` | Public `/book/` text (`core/views_book.py:1-6`): the third edition, 14-16 October, says "the Lore and the Big Money board arrive, information that no order reads" (`:1004-1015`). The milestone "The Lore" (2026-10-15, commit bcb0e42) reads: "A library of strategies, fund playbooks, episodes and concepts that Sauron's agents read, with its switches on, only once a person has reviewed each entry, and only as reference: it changes no rule, gate, size or order." (`:1486-1490`). No entry content (canary test). |

Also relevant: `core/platform_control.py:142-154, 198-207` (switch rows, exemption, the D1 sentence); `config/settings.py:131-141`; `config/urls.py:33-35`; `templates/base.html:547-548`.

---

## 6. Verdict for the operator, with exact steps

### 6.1 Verdict (English, for the orchestrator)
- **Now, as things stand (almost surely zero reviewed entries):** turning either switch on is harmless and free (§3.3) but changes nothing. The first thing needed is not a switch but **reviewed entries**.
- **Order:** (1) get entries in (the seed catalogue if it still exists, otherwise a few hand-written ones in the admin) and review them on `/lore/`; (2) **`lore_staff` ON**: with his single staff account there is no exposure (answers only on /research/ and the Ask Sauron eye, never on Telegram), and it costs ≤ ~$0.013 per web question that matches an entry; (3) **`lore_background` last**, once reviewed **world** entries carry **regime tags**, and only after the D1 check below.
- **D1 with one account:** if the briefing push is off, goes by email, or goes to a Telegram chat holding only him and the bot, D1 is moot and `lore_background` can go ON (≤ ~$0.007 a day). If the group holds other people (the second keeper, viewers, loyals), it is his call. Either they receive each morning a briefing shaped by the library (never quoting or naming it, scrubbed), or he keeps `lore_background` OFF, or he unticks "Daily Sauron's Mind briefing" so the briefing stops going to the group. Separate from the Lore: a "you should…" briefing reaching third parties is advice-shaped text whether or not the Lore is on. The Court study's EU/France lens (investment recommendations, finfluencers) covers that question, not this switch.
- **Nothing here touches money:** the library cannot change a rule, gate, size, limit or order (`lore/read.py:1-10`, `lore/render.py:26-33`). The briefing's posture word sizes nothing (`brain/strategist.py:402-413`). The strategist's graded ideas do not move the bots' trust number, which is the Mind's (`brain/strategist.py:144-164`).

### 6.2 Exact steps (box commands; `<username>` = his login, never written down here)
**A. Read-only status (changes nothing)**
```
cd ~/Sauron_Vision
./deploy/dc exec -T web python manage.py component list --category agent
./deploy/dc exec -T web python manage.py lore check
./deploy/dc exec -T web python manage.py lore import --dry-run
./deploy/dc exec -T web python manage.py shell -c "
from django.contrib.auth.models import User
for u in User.objects.order_by('pk'):
    p = getattr(u, 'notification_prefs', None)
    t = getattr(u, 'trader_profile', None)
    chat = (p.telegram_chat_id or '') if p else ''
    print(u.username, 'active' if u.is_active else 'inactive', 'staff' if u.is_staff else 'not-staff', 'superuser' if u.is_superuser else '-', 'briefing_push=' + str(bool(p and p.receive_strategist_briefing)), 'channel=' + (t.notify_channel if t else 'no-profile'), 'telegram_chat=' + ('group' if chat.startswith('-') else ('private' if chat else 'none')))
"
```
The last command was tested on the copy. It prints one line per account: staff/superuser flags, whether the briefing push is on, the channel, and whether the Telegram chat is a group (negative id) or private. It never prints the id. A line "N objects imported automatically" before it is Django's and harmless. Then, in Telegram, open the group's member list.

**B. Get reviewed entries**
- If he has the catalogue files: put them in `~/Sauron_Vision/private/lore/` (`seed.json`, optionally `seed_overlay.json`, `private_terms.txt`), then `./deploy/dc up -d --build` (the image is the only way in), then:
  ```
  ./deploy/dc exec -T web python manage.py lore import --dry-run
  ./deploy/dc exec -T web python manage.py lore import
  ./deploy/dc exec -T web python manage.py lore check
  ```
  (`lore check` lists what still blocks review, for example V27.)
- If nobody has it: write a few entries by hand at `/admin/lore/loreentry/add/` (§2.2), or rebuild the seed (a writing task of its own: English, own words, sources, `lore check` clean).
- Review each one: `/lore/` → Status "Draft" → open → (optional "I opened S1" → "Record the sources I opened") → tick the five checks → "Mark reviewed".

**C. `lore_staff` ON**
/ops/ → Agents → `lore_staff` (Lore: staff readers) → "turn on", or `./deploy/dc exec -T web python manage.py component on lore_staff`. Check it with `./deploy/dc exec -T web python manage.py lore show research --viewer <username> --query "<words of an entry title>"` → `Block: …`. Then ask on Ask Sauron: the answer cites "library: <slug> →", and `/lore/` LAST READ shows "research".

**D. `lore_background` ON (after D1)**
/ops/ → `lore_background` → "turn on", or `component on lore_background`. Check it with `lore show strategist --regime <current regime key>` (the key is visible on `/lore/` as "Relevant to the current regime (…)"; keys: risk_on, risk_off, mean_reverting, trending, blow_off). After the next 06:00 UTC briefing (or "▶ Run strategist now (admin)" on /briefing/, one strategist run, ~$0.30 estimated), `/lore/` shows "Last reads by agents: strategist · N entries", and `/admin/lore/loreread/` shows `StrategistBriefing:<id>` with the scrubbed count.

**E. Off at any time:** "turn off" on /ops/, or `component off lore_staff lore_background` (no PIN).

### 6.3 Ready to adapt for him (FR, tu; code labels kept in English)
> **Le Lore, tel qu'il est dans le code aujourd'hui.** Non, ce n'est pas une voix indépendante. C'est la **bibliothèque** de Sauron : des fiches sur des stratégies connues, des méthodes de grands fonds, des épisodes de marché passés et des concepts, écrites avec nos mots. Chaque affirmation est rangée en « Documented » (une source le montre), « Reputed, not proven » (on le dit, sans preuve) ou « Breaks when » (quand ça casse). Elle est réservée au staff, donc à toi.
> - Elle ne parle pas et ne prédit rien. Elle n'écrit rien seule : une fiche entre par un import ou à la main dans l'admin, toujours en brouillon. Aucun agent ne la lit tant que tu ne l'as pas validée sur sa page (cinq cases, puis « Mark reviewed »).
> - Il y a deux lecteurs seulement, chacun derrière son interrupteur, éteint à l'arrivée : `lore_staff` (Ask Sauron, pour tes questions posées sur le web) et `lore_background` (le stratège de 06:00 UTC, en fond, sans jamais citer ni nommer une fiche). Elle ne peut changer ni règle, ni seuil, ni taille, ni ordre.
> - Les « leçons de Sauron » (sa propre mémoire) sont prévues dans le modèle. L'agent qui les écrirait n'existe pas encore.
>
> Ce que tu décris, une voix de Sauron un peu prophétique que les gens observent, craignent ou soutiennent, ce sont **les Prophéties** (étudiées le 9 octobre) et **la Cour** (étudiée le 8 octobre). Ni l'une ni l'autre n'est construite. Seule trace : une case vide « prophecies : — » dans le dossier de marché des Orcs. Le Lore pourrait un jour leur servir d'étagère de preuves (épisodes, concepts), mais la voix elle-même serait une chose nouvelle.
>
> **Les interrupteurs, avec un seul compte (le tien).** La bibliothèque est très probablement vide : il n'y a aucun catalogue dans le dépôt. Les allumer aujourd'hui ne change rien et ne coûte rien. D'abord des fiches validées. Ensuite `lore_staff` : sans risque, tu es le seul lecteur, et ça coûte au plus environ 0,01 $ par question qui touche une fiche. `lore_background` en dernier, après une vérification : est-ce que le briefing du matin part dans ton groupe Telegram, et qui est dans ce groupe ? Si tu es seul avec le bot, ou si tu ne reçois pas le briefing là, vas-y. Si d'autres personnes y sont, c'est la décision D1 : leur envoyer chaque matin un briefing nourri en fond par la bibliothèque, ou non.

---

## Appendix: verification on the copy
- `python manage.py test tests.test_lore_library tests.test_lore_read tests.test_lore_readers tests.test_lore_pages tests.test_lore_fences` → `Ran 109 tests … OK (skipped=1)`.
- Scratch checks (`run/tree/tests/test_zz_map_checks.py`):
  - zero entries with both switches ON → `'nothing matched'` ×2, 0 tokens, LoreRead 0;
  - `lore show` with the switch OFF → `Empty block: switch off.`;
  - import with no catalogue → `No catalogue at …/nothing-here. Put the files in private/lore/ or set LORE_DIR.`;
  - admin add → `Saved.` → review → `Reviewed. Agents cleared…` → research block 483 est. tokens / strategist 302 → an admin edit sends it back to draft;
  - 30 matching entries → research shows 8 (3 cards, 1,899 est. tokens), strategist 6 short forms (962).
- Read-only commands run on a migrated scratch SQLite DB: `component list --category agent` (both Lore rows OFF), `lore check` (`All 0 entries pass.`), `lore import --dry-run` (no catalogue message), `lore show research` (`Empty block: switch off.`), `lore show mind` (`Agent mind is not cleared to read the library.`).
