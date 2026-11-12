# Recovery: the Court (#105), the Prophecies (#106), the Lore (#107), the elections study (#114)

Written 2026-11-07 for the lore-prophecies-answer workflow (main 15dd487). Read-only: nothing in the repository was changed.

## 0. The short version

- **The two studies are lost.** The Court study (#105, 2026-10-08) and the Prophecies study (#106, 2026-10-09) were finished, with a synthesis, a critic and a French summary each. All their files lived in the scratchpad and in workflow journals, and the container reset between 2026-10-26 and 2026-10-31 wiped them. Neither was ever committed or pushed. No conclusion text survives. What survives:
  - the task-list descriptions of each study;
  - one roadmap line in the Lore's commit;
  - the code hooks the Prophecies design was meant to build on.
- **The Lore survives in git, but its seed does not survive anywhere I can reach.** The Lore was built and merged (PR #60, 2026-10-15). Its seed catalogue had 64 entries, 251 sources and 305 claims. The seed was kept outside git in `private/lore/` of the lore worktree, and the reset wiped that worktree. The transcript (from 2026-10-24) has no trace of:
  - the seed being delivered to the server;
  - `lore import` being run;
  - any entry being reviewed;
  - any operator decision on D1.
  This is **unknown, not proven absent**. Section 5.6 gives the read-only commands that settle it.
- **The original architecture was already "library ≠ voice".** The Lore commit's roadmap puts:
  - the Prophecies as a future **reader** of the Lore (PR5);
  - the members' Court as a consumer of a **read-only export** (PR6);
  - "Sauron's own record" (PR2) as the place for his own lessons and notes.
  None of PR2 to PR6 was built.
- **My two answers today need two corrections, plus one wording fix.** See section 8. The strategist's briefing is pushed only to accounts that opted in (default off), though any login can read it on the web. The Lore holds no "Sauron's lessons" today, because no distiller exists. The dossier's prophecies cell is a bare dash.

## 1. What I searched

| Source | What it held for this question |
|---|---|
| Transcript `/root/.claude/projects/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c.jsonl`: 10,720 lines, 2026-10-24 20:40 to 2026-11-07 12:05, compactions at lines 0, 1510, 3177, 4934, 6913, 8509, 10374 | **The conversation of 8 to 16 October is not in it.** It starts with a compaction. The pre-October-24 history survives only as the **old task list**, 123 tasks, in line 0 (`compactMetadata.preCompactTaskList`) and repeated as attachments up to line 584. Besides that it holds today's exchange (lines 10311 to 10718) and a legal research of 2026-10-24 (lines 64, 330, 333, 337, 354). Extracted copy: `scratchpad/lore/recover_tools/tasklist_line0.json` |
| Scratchpad, outside `lore/` | 797 entries, **all dated 2026-10-31 or later**. No court, prophecies, elections or Lore seed file. The text hits are code-tree copies and today's specs only (eyehall, uiplan, competence) |
| Handoff branch `origin/claude/handoff` f7794b8 (2026-11-07 11:47) | `HANDOFF.md` and plans for bettor, eyehall, feed, oculus, opscenter, orcs2, orders, ui, usedfix. **Nothing on the Court, the Prophecies, the Lore's state or the elections** |
| Git, all refs (`log --all -S` and `--grep`) | No file or message holds "Prophec", "agora", "Knights", "the Court", "forum" (as a feature) or "elections". Hits: the Lore commit bcb0e42 and its PR (they also hold the comment naming D1); the council commit 6881bbc ("season objective", "campaign plan record"); Horizon 464633f; the Orcs dossier e519e0b and c1bcc73 (the MK9 dash); the PIN commit c962b4a (lore_staff is not a PIN switch); the Book's third edition 6c3410a |
| GitHub PR #60 | Its body is quoted below. No comments |
| Workflow journals (`.../workflows/`, `.../subagents/workflows/`) | Only runs since 2026-10-31. Not there: wf_2bacce63-60d (Court), wf_5410fd01-29b (Prophecies), wf_b6b511d7-653 (Lore), wf_471c1951-88e (elections), wf_b053c63a-afe (global uses) |
| The operator's claude.ai artifacts (8) and docs | None mentions the Lore, the Court or the Prophecies. Two are private planning docs of 5 and 6 November (funding, business model, a client and copy-trading direction). Do not quote them; they bear only on the law lens (section 10). The lawyer note (2026-11-01) is about the partner deal |

## 2. LOST and SURVIVES

| Item | Status | Where it survives, or what replaced it |
|---|---|---|
| Court study #105 (five lenses, synthesis, critic, French summary) | **LOST** | Task #105 text only. The task is marked completed with a French summary. That summary was probably sent to him (not recorded explicitly), so **he may still have it** |
| Prophecies study #106 (forces with signposts, platform design, law and credibility, synthesis, critic, French summary) | **LOST** | Task #106 text only. Same as #105: he may still have the French summary |
| Lore design docs (code map, two designs plus a judge, the seed workflow's catalogue) | **LOST** | The design survives as code: `lore/`, the commit message bcb0e42, PR #60's body |
| Lore seed catalogue (64 entries, 24 strategies, 15 fund playbooks, 15 episodes, 10 concepts, 251 sources, 305 claims) | **LOST from every place I can reach.** Only the operator's server could hold it | It lived in `.claude/worktrees/lore/private/lore/` (gitignored); that worktree is gone. It exists on the server only if it was ever copied to `~/Sauron_Vision/private/lore/`, or if it was imported into the database. The topics of some entries are named in the commit (Renaissance, Winton, LJM, Park and Irwin 2007, the COT outage, the yen carry unwind, the SEC order, eToro's triple overnight fee) |
| Lore deploy sheet (probably `sheet_pr60.md`) | **LOST, and its content is unknown** | Nothing in the transcript or the old task list. Task #107 says only "review, commit" |
| Ops switch guide of 2026-10-23 (`opsguide/ops_switches.md`, 75 switches) and his switch state (`current_state.txt`) | **LOST** | He has the guide (it was sent). The 2026-10-24 summary records his pasted `component list`: "62 on, 13 off, 75 total". Which 13 were off is not recorded |
| Elections spec and global-uses study #114 (`elections/spec.md`, `elections/global/study.md`, two RESUME_FR.md) | **LOST** | Task #114 text only. He received both French summaries (2026-10-22 to 24) |
| Big Money PR2 "the dark side" spec (`bigmoney/spec_pr2_darkside.md`; operator 2026-10-09: "dark pools and secondary markets in times of turmoil") | **LOST**, never built | Task #103 text only. It shares the "manipulation" theme of the same day |
| Legal research of 2026-10-24 ("manager-recap-check": France, EU, UAE, HK, eToro, plus a code exposure map) | **SURVIVES in the transcript only** | Lines 330, 333, 337 (results) and 354 (French answer). Its file `scratchpad/manager_digest.txt` is gone |
| The reset itself | Recorded | Line 723 (2026-10-31 17:30), my French message: "la réinitialisation a effacé ce qui n'avait pas encore été envoyé sur GitHub : … mes notes de conception". Line 623: the scratchpad listing was empty and only the main checkout remained |

## 3. The Court (#105, 2026-10-08)

### 3.1 The request, as recorded
Old task list #105:
- **Subject:** "Study the members-only court (agora in the Tolkien world, like TradingView ideas) with Sauron's continuous voice: product, law, security, naming".
- **Description:** "Operator (2026-10-08): a members-only space (Knights, heroes) where people discuss themes and markets and Sauron posts thoughts, visions, dreams, hypotheses; \"think it through before\"." Only **"think it through before"** is in quotation marks. The rest is my paraphrase.

### 3.2 How it was studied
"Study workflow wf_2bacce63-60d (five lenses incl. EU/France law on investment recommendations and finfluencers, security separation from the trading box, Tolkien IP), synthesis, critic, French summary. **No build.**" Status: completed.

### 3.3 What it concluded
**Lost.** Three later records show where it pointed. They are not the study's text:
1. **Lore roadmap (2026-10-15, bcb0e42):** "PR6, a read-only export for the members' court." The Court was to read a separate, read-only export of the library, never the live system. That fits the "security separation from the trading box" lens.
2. **Code exposure map (2026-10-24, transcript line 337):** "F[low] Members' court, forum or ideas board | (none on main; lore/constants.py:59 'court' is only a source type, 'Court record') | today: Not present. exposure: None today. If built, posting trade ideas to members would be a recommendations or community-signals service."
3. **My advice of 2026-10-24 (line 354):** "Si Sauron leur envoie des signaux, c'est du conseil." And: "Aucun extérieur ne reçoit un login Sauron avant l'avis de l'avocat."

### 3.4 Traces in today's code
- **None.** No members' space, forum or Knights exist at 15dd487. The only "court" in the code is the Lore's source kind "Court record" (`lore/constants.py`, SOURCE_KINDS).
- **The Telegram group is the nearest thing to an audience today.** `core/announcements.py:1-8` says the release notes are read by "the viewers and the loyals". That is the group the Eye answers in (TELEGRAM_CHAT_ID), so people other than the operator read it.

## 4. The Prophecies (#106, 2026-10-09)

### 4.1 The request, as recorded
Old task list #106:
- **Subject:** "Study the Prophecies: long-horizon theses on the great forces and documented power/manipulation mechanisms, falsifiable signposts, graded over years, a forum pillar".
- **Description:** "Operator (2026-10-09): add the prophecies part, the big forces exercising power and gravity over the world and the markets, and the manipulations; a forum topic." This is my paraphrase; no verbatim words survive.

### 4.2 How it was studied
"Study workflow wf_5410fd01-29b (forces with signposts, platform design on HorizonView + hypothesis market + the Emperor's campaign, law and credibility incl. MAR art. 12 and defamation), synthesis, critic, French summary. **No build.**" Status: completed.

### 4.3 What it concluded
**Lost.** The scope above shows its shape:
- theses on great forces, each with falsifiable signposts, graded over years;
- built on three existing parts: the Horizon, the hypothesis market and the Emperor's campaign;
- a law and credibility lens: MAR art. 12 (manipulation, including scalping) and defamation when naming manipulators;
- "a forum pillar", that is, one topic of the Court.

The Lore roadmap then placed it as a **Lore reader**: "PR5, the council, the Orcs, Big Money and the Prophecies".

### 4.4 The hooks it named, as they stand at 15dd487

| Hook | What exists | Note for the design |
|---|---|---|
| **HorizonView** (`brain/horizon_models.py:31`, `brain/horizon.py`, `/horizon/`, `manage.py horizon`, switch `agent_horizon`) | 464633f (2026-09-12): a monthly 5-10 year sector view on the frontier tier. Each thesis carries direction calls at 6 and 12 months, graded by the existing resolver. "The share allocator's fifth factor: 1 + 0.05 × tilt × confidence per asset class (0.90..1.10 at most)" | **It touches sizing.** So the Horizon is a Lore **never-reader**. `tests/test_lore_fences.py:27-32` says why: "Never readers: a size, a gate or a binding vote sits one hop away". A prophecy that feeds the Horizon would move money weights, however weakly. A prophecy that reads the Lore must therefore not feed the Horizon |
| **Hypothesis market** (`brain/hypotheses.py`, `/hypotheses/`, `@login_required`, on the public Wall as "Hypothesis Market") | Falsifiable claims graded confirmed or refuted. The council's Theorist posts "falsifiable theories ... under his own name" (6881bbc; `ai_agents/agents/council.py:408-418`) | Its grading is short-horizon. Direction calls are clamped (`clamp_horizon`, 1440 h by default; the Horizon passes `max_horizon_hours`). Grading "over years" needs signposts with long or explicit deadlines |
| **The Emperor's campaign / season objective** | The Emperor is told "The operator has set no season objective: do not invent one" (`council.py:446-447`) and "season objective: none set by the operator" (`council.py:1613`). 6881bbc lists as out of scope "the campaign plan record (decision 3)" | **Still unset.** He was never asked again |
| **The calls ledger** (c8c2e79, "NO PROSE WITHOUT A CLAIM THE PLATFORM CAN GRADE") | Every prose agent ends with a fenced calls block. The nightly resolver grades it. Ungraded is never wrong | A house principle the Prophecies should keep |
| **Orcs dossier MK9, "the long view"** (`bot_program/orcs/dossier_market.py:139-142`) | `{"horizon": ..., "prophecies": "—", "season": "no season objective set by the operator"}`. The words "prophecies — (not built)" appear only in the synthetic smoke header (`ai_agents/management/commands/claude_smoke.py:169-170`) | **The only place the word survives in code.** The slot was reserved by the Orcs spec, which knew the Prophecies were not built |
| **Big Money board** (4e785a6; switch `big_money_board`) | "Reads the flows the large players are obliged to make ... grades every read against the prices that followed" | The built side of "power and gravity". The "dark side" PR2 (dark pools, turmoil) was specified, then lost, and never built |

## 5. The Lore (#107)

### 5.1 The request (verbatim, quoted in bcb0e42)
"Add a Lore or Knowledge place, a library, vast, that knows the strategies used now and in the past by others or by big funds. A knowledge place, readable and usable by any agent."
- Task #107 adds "later the forum".
- **He coined the name "Lore" himself, for a library.**

### 5.2 What was built
- **PR and commits:** PR #60, "The Lore: a staff-only library of strategies, fund playbooks, episodes and concepts, read by agents through one fenced API". Commit bcb0e42, merge 555a64d. Merged 2026-10-15 17:51 UTC by Zzcorp, stacked on PR56 to PR59.
- **The seed:** "lives outside git (private/lore/, gitignored) and is loaded by `manage.py lore import` ... 64 entries ... Every row lands as a DRAFT."
- **The review:** "No agent reads anything until a staff member reviews it on /lore/<slug>/ with five checks (sources opened, own words, the right sides, the tags, nothing about our own account); there is no bulk review."
- **The adversarial review** confirmed 27 findings, all fixed. Nine of them corrected seed facts with sources. So the full seed existed and was checked on 2026-10-15.
- **The readers:** `lore_staff` (Ask Sauron, staff web questions) and `lore_background` (the strategist, world entries as unquoted background, output scrubbed, fails closed). Both arrive OFF and are exempt from "all on". "With both switches off, both prompts and contexts are byte-identical to what they were before the Lore."
- **The Book (public)** describes it at `core/book_content.py:1486`: "A library ... that Sauron's agents read, with its switches on, only once a person has reviewed each entry, and only as reference: it changes no rule, gate, size or order."

### 5.3 The roadmap that was planned and never built
bcb0e42: "What follows: PR2, Sauron's own record (nightly tallies, lesson drafts, margin notes, the forum's first form); PR3, the keeper; PR4, the background readers (critic, position reviewer, close advice, strategy generator) after D1 and two weeks of LoreRead; PR5, the council, the Orcs, Big Money and the Prophecies; PR6, a read-only export for the members' court."

At 15dd487 **none of PR2 to PR6 exists**:
- No distiller or keeper exists, and no code writes `origin="sauron"`.
- The kind `lesson` ("Sauron's lesson", "written only by the distiller") exists only in the vocabulary.

### 5.4 Decision D1 and "the library review"
- **D1** (PR #60 body): "D1 is still open: whether the strategist may read the library in the background. Both switches stay off until you turn them on, one at a time."
- **The code** (`core/platform_control.py:142-146`, written by bcb0e42 itself and unchanged since; c962b4a only reworded the sentences around it): "lore_staff after the first entries are reviewed, lore_background only after decision D1 (the briefing reaches readers who are not staff)".
- **No later decision exists.** Nothing in the transcript, git or the handoff records an answer to D1, a reviewed entry, or a ruling on either switch, beyond my answers today.
- **"The library review"** (today's summary: "lore_background stays OFF pending decision D1 and the library review") means the per-entry review on `/lore/<slug>/`. For 64 entries that is 64 × 5 checks, with no bulk path.
- **Several decisions are named D1.** Don't mix them up:
  - PIN-wide's D1 was answered ("Oui fait les deux", PR70);
  - the Orcs' D1-D31;
  - orders D1 (cancel a pending close, answered);
  - bettor D1;
  - UI D1 (a breakpoint).
  Only the Lore's D1 matters here, and it is unanswered.

### 5.5 Was the seed sent? Imported? Reviewed?
**Unknown.** The evidence:
- The transcript starts 2026-10-24. In it the operator never pasted any `lore` output, any `/lore/` content, or any lore switch line. All 100 of his messages were checked; only today's two mention the Lore.
- `private/` is gitignored, so the server could get the seed only by a hand transfer. Delivery would have to be a file sent in chat and copied to the server; nothing records that.
- Once the files are in `~/Sauron_Vision/private/lore/`, they do reach the container. `.gitignore:30-33` says "copied into the image, never committed", and `Dockerfile.prod:56` has `COPY --chown=sauron:sauron . /app`.
- A weak hint: today he asked only about "lore background" and the commentator, not about "Lore: staff readers", which sits on the next row of the Agents group. `lore_staff` may already be ON, or he may simply not have asked. **This is an inference, not a fact.**
- Most likely: the seed never reached the server, or reached it but was never reviewed. Either way **no agent has read a single entry**, because the read API serves REVIEWED rows only.

### 5.6 Read-only commands that settle it
I owe him these ("Je te donnerai la commande pour vérifier s'il y en a sur ton serveur", 11:54). I checked each against the code at 15dd487 by reading it; I did not run them. Same form as his usual pastes:

1. Switch states. Prints `ON`/`OFF`, the key and the name, per row of the Agents group:
   `cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py component list --category agent`
2. Entries by status, and how often the library was read:
   `cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py shell -c "from lore.models import LoreEntry as E, LoreRead as R; from django.db.models import Count; print(dict(E.objects.order_by().values_list('status').annotate(n=Count('id')))); print('reads', R.objects.count())"`
   - `{}` means nothing was ever imported.
   - `{'draft': 64}` means imported but never reviewed.
3. Whether the seed files are on the server. Writes nothing (`lore/importer.py`: the dry run only compares). It prints "No catalogue at … Put the files in private/lore/ or set LORE_DIR." when absent (`lore/management/commands/lore.py:59-63`):
   `cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py lore import --dry-run`
4. Optional, to confirm "que le mien" and that his account is staff. The research reader needs a staff viewer, and the pages are staff-only. Prints counts only, never names:
   `cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py shell -c "from django.contrib.auth.models import User as U; q=U.objects.filter(is_active=True); print(q.count(), q.filter(is_staff=True).count())"`

**If entries exist only in his database**, `manage.py lore export` writes them to `private/lore/export-YYYYMMDD.json`, which keeps a copy. The importer skips `export-*` files when it reads a folder. **If nothing exists**, the seed must be rebuilt: the old catalogue is gone.

## 6. The elections spec and the global-uses study (#114, 2026-10-22)

- **Task #114:**
  - **Subject:** "Elections spec and global-uses study delivered (scratchpad/elections/spec.md, global/study.md); awaiting the operator's decisions D6, D12, D13, D23, D24, D5, D22 and the PIN-path question".
  - **Description:** "Operator said go (2026-10-22). Spec workflow wf_471c1951-88e ... → scratchpad/elections/spec.md and RESUME_FR.md. Plus the operator's addition (2026-10-22): the global uses that could make the market more unified and valuable for all — study workflow wf_b053c63a-afe ... → scratchpad/elections/global/study.md and RESUME_FR.md. Send both French summaries together."
- **The decisions were never answered** as far as the record shows. They appear as "Older pending items: elections decisions ..." in the summaries of 2026-10-24, 2026-11-01 (twice) and 2026-11-02, then silently drop out from 2026-11-06 on.
- **What "elections" means cannot be recovered.** No code, commit, file or message says.
  - It is **not** the US midterms; nothing mentions them.
  - The nearest built thing is the council's Hand, whose "influence [is] earned by record" (19f30d4, 2026-10-22, the same day).
  - "The market" in "global uses" may be the **hypothesis market**. That would tie #114 to the Prophecies' "hypothesis market" pillar. **Unverified.**
- **Relation to today's question:** possible, unproven. Best move: ask the operator, who holds both RESUME_FR files, or leave #114 out of the note.

## 7. The operator's own words

| Date | Words | Provenance |
|---|---|---|
| 2026-10-03 | "make the telegram bot send it in his group... with great styling and **lore**" | `core/announcements.py:4-5` (verbatim). **He uses "lore" in the storytelling or Tolkien sense** |
| 2026-10-08 | members-only space (Knights, heroes) ... Sauron posts thoughts, visions, dreams, hypotheses; "think it through before" | Task #105 (paraphrase plus one quoted phrase) |
| 2026-10-09 | "Add a Lore or Knowledge place, a library, vast, that knows the strategies used now and in the past by others or by big funds. A knowledge place, readable and usable by any agent." | bcb0e42 (verbatim). **He uses "Lore" in the library sense** |
| 2026-10-09 | the prophecies part, the big forces exercising power and gravity over the world and the markets, and the manipulations; a forum topic | Task #106 (paraphrase) |
| 2026-10-09 | dark pools and secondary markets in times of turmoil | Task #103 (paraphrase) |
| 2026-10-16 | a voice that predicts better should gain in influence ... the people could be happy or not depending on the book | 19f30d4 (paraphrase). The answer then was "yes for the Emperor, no for the members, one exception for the Skeptic, and a mood that may only counsel caution" |
| 2026-10-22 | the global uses that could make the market more unified and valuable for all | Task #114 (paraphrase) |
| 2026-11-07 08:53 | "mais garder la thematique initiale pour le design et theme please, you understand that we still feel the magic or something alike, the prestige too..." | Transcript line 9517 |
| 2026-11-07 11:37 | "Je ne devrai pas activer lore background ni agent commentator?" | Line 10311 |
| 2026-11-07 11:48 | "que le mien pour le moment mon ami, mais j'ai une question le lore, n'est pas une fonctionnalité "indépendant" un peu prophétique que sauron fait et qui est observer, craint, supporté, etc et etc?" | Line 10520 |

The UI specs also record "the lore" as the Tolkien layer:
- `handoff/plans/eyehall/eyehall_spec.md:118-120`: "In the lore the Eye sits at the summit of Barad-dûr ... the operator already uses the lore's words: the Horde, the Orcs, Morgul, Aragorn, Gollum".
- `handoff/plans/ui/ui_plan_spec.md:17`.

**Both senses are his.** Today's question likely blends the second sense with the Prophecies idea.

## 8. What my answers today said, and what to correct

**11:38 (line 10349), before his answer about accounts.**
- **On the commentator:** "« Market Commentator » (`agent_commentator`) : oui si tu veux, avec une condition." The condition: "il envoie ce bilan à tous les comptes actifs de Sauron ... Si tu es seul sur Sauron, aucun souci ... [sinon] peut compter comme une recommandation d'investissement aux yeux de l'AMF."
- **On the background reader:** "« Lore: background readers » (`lore_background`) : non, laisse-le éteint pour l'instant." Why: "ce briefing du matin part lui aussi à tous les comptes. Le code a donc été prévu pour qu'on ne l'allume qu'après une décision écrite ... Et la bibliothèque doit d'abord être relue."
- **The order given:** "1. relire les premières entrées de la bibliothèque ; 2. allumer « Lore: staff readers » ... 3. ensuite seulement le background." Then it asked: "y a-t-il sur Sauron d'autres comptes que le tien ?"

**11:54 (line 10658), after "que le mien".**
- **The go-ahead:** "Tu es le seul compte : tu peux donc allumer **agent commentator** sans risque." The path: "/ops/ → Switches → groupe **Agents** → ligne « Market Commentator » → **turn on**. Pas de PIN." And: "N'appuie pas sur « all on »", 17:30 UTC, "dans ta cloche", "À revoir le jour où tu ajoutes un autre compte".
- **The Lore:** "**Le Lore est la bibliothèque de Sauron**, ce qu'il lit. Ce n'est pas sa voix, ce qu'il dit." And: "Ses deux interrupteurs ne lisent que des fiches relues (« reviewed »)."
- **The Prophecies and the Court:** "Ce que tu décris existe dans tes demandes, mais n'a jamais été construit." It named the Prophecies (9 October) and the Court (8 October).
- **What it promised:**
  - "une proposition de Prophéties telles que tu les décris : Sauron parle seul, sur le long terme, on l'observe, on le craint ou on le soutient, et chaque prophétie est notée avec le temps. Elle ne passera jamais un ordre";
  - "le cadre légal : en privé pour toi seul, c'est simple ; pour des membres ou le public, il faudra l'avis d'un avocat";
  - "Tu auras une fiche en français avec ton choix à faire."

**12:05 (line 10718):** "Lore et Prophéties : l'étude que je t'ai annoncée tourne."

**Corrections for the note:**

| Claim made today | What is true at 15dd487 | Fix |
|---|---|---|
| "ce briefing du matin part lui aussi à tous les comptes" (11:38) | Two things are mixed. (1) The strategist runs at 06:00 UTC. It stores its briefing on `/briefing/`, which any login can open (`@login_required`, `dashboard/views_brain_phase38.py:418-419`). It posts its ideas as hypotheses on `/hypotheses/`, also any login. It **pushes** "Sauron briefing — …" only to users with `receive_strategist_briefing`, **default False** (`alerts/models.py:203`; `brain/strategist.py:749-756`). (2) The "Morning Briefing — …" bell for **all** accounts (`create_for_all`, `ai_agents/tasks.py:778-780`) is the daily_briefing agent. **It never reads the Lore** | Say: what the strategist writes after reading the library becomes visible to every account (its page and its ideas on the Hypothesis Market), and is sent to those who opted in. With one account (his own) D1's risk does not apply today, but it stays an explicit decision |
| The Lore contains "les leçons que Sauron tire de ses propres trades" (11:54) | The kind `lesson` exists, but nothing writes it. The distiller (PR2) was never built, and no row has `origin="sauron"` | Say the library was **designed** to also hold his lessons later, and that this part was never built |
| "une case vide, « prophecies — (not built) », dans le dossier de marché des Orcs" (11:54) | The dossier's value is a bare "—" (`dossier_market.py:141`). "(not built)" is only in the smoke test's synthetic header | Say "une case vide (un tiret)" |
| Commentator "dans ta cloche", no PIN, "Market Commentator", 17:30 UTC, fast tier | Confirmed. `create_for_all` makes bell rows for every active user plus a live web push; no Telegram path in that function (`alerts/models.py:301-325`). `agent_commentator` is not a PIN switch. Celery runs it at 17:30 UTC. `market_commentator.default_tier = "fast"`. Its inputs: quotes, top movers, active signals, 24 h news, calendar (`ai_agents/tasks.py:1371-1420`) | Keep |

**One nuance on "que le mien":** `bot_program/withdrawal_models.py:3-4` says Gandalf ("the second keeper") "signs in on the SAME account". The Telegram group has "viewers and loyals" (`core/announcements.py`). So "one account" does not mean "one reader". It does not change the commentator advice (bell only), but it matters for any voice posted to Telegram.

## 9. Surviving law material (2026-10-24 research), as pointers to re-verify

Source: transcript lines 330 (France digest), 333 (UAE/HK), 337 (code exposure map), 354 (my French answer). The digest lines are truncated snippets: re-verify each at its primary source. Never quote the private parts (family accounts, people, amounts).
- **Public newsletter, Telegram or signals channel:** "anyone who produces or spreads investment recommendations on financial instruments within MAR's scope (shares, and CFDs on them) must present them objectively and disclose interests and confli[cts]" (line 330, item 25).
- **Personal recommendations:** "Signals tailored to each licensee's account, size or risk are personal recommendations (Delegated Regulation 2017/565 Art 9), i.e. investment advice that needs CIF or PSI status" (item 34).
- **France, marketing:** "electronic ads for CFD-based investment services to retail and paid influencer promotion of CFDs are banned (Code de la consommation L.222-16-1, CMF L.533-12-7; influencer law Art 4 V, up to 2 years and EUR 300,000)" (item 40). Also: "The influencer law applies only to promotion made 'à titre onéreux' (law 2023-451 art 1)", with an eToro Popular Investor example (item 69).
- **UAE:** "The UAE finfluencer regime: Resolution 10/R.M of 2025 ... A natural person who publicly gives recommendations to buy, sell or hold a financial product or virtual asset must register first" (line 333).
- **Hong Kong:** "paid signals are being prosecuted as unlicensed Type 4 advice. Nov 2025: 6 weeks' imprisonment for a subscription Telegram group" (line 333).
- **Copy trading:** ESMA's 2023 briefing treats it as portfolio management or advice (ESMA35-42-1428; lines 330 and 333).
- **The house rule I set that day:** "Aucun extérieur ne reçoit un login Sauron avant l'avis de l'avocat" (line 354).
- **Today (line 10228), on the name:** "Le nom « Sauron » vient de l'œuvre de Tolkien. Avant un vrai lancement commercial, fais vérifier les droits sur la marque." The brochure already carries a trademark note. This matches the Court study's "Tolkien IP" lens.

## 10. What the recovery implies for the design (input, not decisions)

1. **Keep the October architecture.** The Lore is the library. The Prophecies are a voice that may **read** it (PR5). The Court, if ever built, gets a **read-only export** (PR6). "Sauron's own record" (PR2) is where his lessons and margin notes were meant to live. The answer to his question is "no, but the thing you describe was planned on top of it".
2. **Mind the Horizon fence.** The Horizon must never read the Lore because it is one hop from sizing (share allocator 0.90 to 1.10). A prophecy that reads the Lore must not feed the Horizon or anything that sizes, gates or votes. That includes the Lore's never-readers: the Mind, the binding debate, bot_program, portfolio, and so on.
3. **Grading over years needs long deadlines.** Direction calls are clamped at 1440 h by default. The Horizon's 6 and 12 month calls show the existing extension point (`max_horizon_hours`). Signposts "graded over years" must store their own deadline, and stay ungraded, never wrong, when no data exists.
4. **Fill the empty slots, and ask for the one decision.** Two reserved slots wait: MK9 "prophecies": "—" in the Orcs dossier, and the Emperor's "season objective: none set by the operator". Filling the first, and **asking** him for the second, is the natural way in; never invent a season objective.
5. **Three audiences, as his earlier studies framed them:**
   - **private** (one account, today: simple);
   - **members** (the Court: recommendations, MAR and influencer law, a lawyer first);
   - **public** (Book, Wall, Telegram "viewers and loyals": the strictest).
   His business plans (private docs, 5-6 November) look toward clients and copy trading. A "prophetic voice" tied to a copied profile is the riskiest case under the influencer law.
6. **Use his own words.** He says "lore" both for the library and for the Tolkien storytelling ("with great styling and lore"), and he wants "the magic ... the prestige". A voice that is "observé, craint, supporté" fits the storytelling sense. The note can say that plainly.

## 11. Files

- This file: `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/lore/recover.md`
- Old task list extract: `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/lore/recover_tools/tasklist_line0.json`
- Today's investigation dump: `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/lore/recover_tools/today_investigation.txt`
- Operator messages (2026-10-24 to 2026-11-07): `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/lore/recover_tools/operator_msgs.txt`
- 2026-10-24 legal research: `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/lore/recover_tools/L330.txt`, `L333.txt`, `L337.txt`, `L354.txt` (contain private matters; quote only the generic legal points above)
- Search tools: `.../scratchpad/lore/recover_tools/tsearch.py`, `showrange.py`
