# Sauron's voices at 15dd487: who speaks forward, who hears it, what it costs, what grades it, what it can move

Read-only map of the export at `scratchpad/lore/tree` (main 15dd487). Written 2026-11-07 for the operator's question:
"le lore, n'est pas une fonctionnalité "indépendant" un peu prophétique que sauron fait et qui est observer, craint, supporté, etc et etc?"

Conventions used below
- **Cost per run**: the code's own figure where it has one (the `@spend_guard(estimated_usd=...)` on the task, a docstring, the page's button). Where the code has none, a figure **computed** from the catalog prices (`ai_agents/catalog.py`: fast = Haiku 5.5 $0.10/$0.50 per Mtok, balanced = Sonnet 5.5 $2/$10, deep = Opus 5.5 $4/$20, frontier = Fable 5.1 $10/$50) and marked "(computed)". The real figure is per row on the AgentTask ledger (`/ai-models/`, `/briefing/` "cost 14d", the Horizon's "Runs" table).
- **"any login"** = `@login_required`: any signed-in account (staff or not; investor logins are held at `/investor/` by `core/investor_gate.py`). Today the operator's is the only account, so "any login" = him.
- **Switch state**: every switch below arrives OFF (`core/platform_control.py`); whether he turned one on is not knowable from the code.
- No live model call, no database read: everything below is read from the code.

---

## 1. Two facts first, for the Lore question

1. **The word "lore" means two different things in this code.**
   - `lore/` (built 2026-10-14) is the **library**: staff-only pages (`lore/views.py`, `staff_member_required`), two readers deny-by-default (`lore/policy.py`: `research` behind `lore_staff`, `strategist` behind `lore_background`), only REVIEWED rows searched. It **says nothing on its own**: no beat, no agent, no output. Its one "own voice" is declared but **not built**: kind `lesson` = "Sauron's lesson", "written only by the distiller" (`lore/constants.py:19-37`), and no code anywhere writes a lesson or implements a distiller (only the constants and the migration name it).
   - "lore" in the operator's own sense of 2026-10-03 is the **mythology**: `core/announcements.py:1-9` ("what the platform tells its group, in the house style and in the lore", quoting him: "make the telegram bot send it in his group... with great styling and lore"; "a folded record ... for the lore's who-is-who": Sauron the Eye, Morgul, Aragorn, the proving ground, the Wall). That lore is **hand-written**, sent by a command, and is not generated, forward-looking or graded.
2. **The only traces of "prophecies" in the code** are empty seats:
   - `bot_program/orcs/dossier_market.py:139-142` (MK9, "the long view" of the Orcs' market dossier): `{"horizon": <the Horizon's tilts>, "prophecies": "—", "season": "no season objective set by the operator"}`.
   - The Emperor's prompt (`ai_agents/agents/council.py:446`): "The operator has set no season objective: do not invent one." and THE WAR's last line (`council.py:1613`): `season objective: none set by the operator`.
   - The provider smoke's synthetic dossier (`ai_agents/management/commands/claude_smoke.py:169-170`): "prophecies — (not built)".
   - No election, geopolitics, "great forces" or "power/gravity" anywhere. "manipulation" appears only as the ICT session phase (`bot_program/power_of_three.py`: accumulation / manipulation / distribution).
3. **Nothing lets people react.** No forum, comment, post, like, follow or vote model for users. `HypothesisVote` (`brain/knowledge_models.py:172-201`, stances `co_sign` / `dissent` / `refine`) is for **agents** (one per agent per hypothesis). The Telegram Eye drops reactions ("edits, channel posts, joins and reactions are no command", `bot_program/telegram_eye.py:131`). "The people's mood" (`ai_agents/council_mood.py`) is a gauge **computed by code from the real-money book** (steady / uneasy / restless / afraid), not people.
   Roles that exist: staff, any login, investor (one book, panel only), the public (`/wall/`, `/book/`). No member / Knight role, no members-only space.

---

## 2. The map in one table

| # | Voice | What it produces | When (`config/celery.py`) | Model · cost per run | Switch | Seen by, where | Graded later? | Can it touch money? |
|---|---|---|---|---|---|---|---|---|
| 1 | **Horizon** (the long view) | 5-10 year sector theses, tilt -2..+2 per sector and per asset class, direction calls at 6/12 months, "regime claims" | monthly, the 1st, 04:45 UTC (L196-199) | frontier (Fable 5.1, effort high) · **~$1.5** (code) | `agent_horizon` | `/horizon/` (any login; "Run now" superuser), `manage.py horizon`, the council's THE WAR, Orcs MK9; described on the **public** Wall `#horizon` | sector calls: yes (calibration resolver, needs `pipeline_calibration`). Regime claims: **no** | **Yes, indirectly**: 5th factor of the share allocator, 0.85-1.15 |
| 2 | **The Mind** (BrainReport) | regime + confidence, health, top concerns, theme pressures, rule overlay (active / watch / pause_recommended), narrative, 1-3 falsifiable predictions | hourly (L159-162); skips on stale bars | deep (Opus 5.5, high) · **~$0.15** (code), so up to ~$3.6/day | **none** (AI budget only) | `/brain/`, `/knowledge/`, `/hypotheses/` (any login), council band (staff), Orcs MK7, input of the strategist, Horizon, Ask Sauron | yes: hourly resolver + nightly hypothesis market; its trust feeds back into its own power | **Yes, directly** (section 4) |
| 3 | **Critic + hypothesis market** | co-sign / dissent / refine votes, counter-hypotheses; the market of graded claims | critic every 2 h (L171-174); market resolved nightly 03:00 (L175-178) | deep · **~$0.40/pass** (code) | none (budget) | `/hypotheses/` (any login) | it IS the grader (Brier, trust) | adjacent: a refuted generator claim pauses that generated rule (`brain/demoter.py`) |
| 4 | **Strategist briefing** | outlook, posture word, watchlist (5), ideas (3) | daily 06:00 UTC (L179-182); skips if the Mind is >12 h stale | deep (Opus 5.5, high) · **~$0.30** (code) | **none** (budget); `lore_background` OFF | `/briefing/` (any login); bell + Telegram / email / Discord for users who ticked `receive_strategist_briefing` (default off); Orcs MK8 | ideas carrying `regime_holds` / `rule_avg_r` go to the hypothesis market | no ("YOUR posture word is advice to the operator and sizes nothing") |
| 5 | Morning briefing (legacy) | "Market Overview, Key Signals, Strategy Watch, News Highlights, Events to Watch" + calls block | daily 06:00 UTC (L365-368) | balanced (Sonnet 5.5, high) · ≈$0.02-0.06 (computed) | `agent_daily_briefing` | bell of every active account ("Morning Briefing — <date>", 2,000 chars) linking to `/briefing/`, which shows the strategist, not this text | calls block → calibration (1 h to 60 days) | only through Next Steps (a person approves) |
| 6 | **Monday plan** | "Weekly Macro Outlook, Priority Strategies, Key Levels to Watch, Economic Event Risk, Position Sizing Guidance, Risk Management Reminders" + calls | Sunday 18:00 UTC (L402-405) | balanced (Sonnet 5.5, high) · ≈$0.03-0.08 (computed) | `agent_monday_plan` | `/briefing/#monday-plan` (whole, last 5), bell summary, staff Telegram group | calls → calibration | only through Next Steps |
| 7 | **Weekly review = the newsletter** | ten sections, incl. "NEXT WEEK OUTLOOK", + calls | Saturday 10:00 UTC (L394-397); sent Sunday 08:00 Paris (`send-due-newsletters`, L906-909) | deep (Opus 5.5, high, 16,384-token answer) · ≈$0.2-0.8 (computed) | `agent_weekly_review`; sending behind `newsletter_send` | staff told (bell + Telegram); the letter by email or own Telegram chat to every active non-investor account with an address (opt-out); `/newsletters/` (any login) | calls → calibration | only through Next Steps |
| 8 | **Council of ten + the Emperor** | each voice's verdict; the Emperor's `fight` / `fight_smaller` / `refuse`, "battle", "war_cost", "plan"; the Theorist's theories; the Awakened's trap | on events: after a LIVE bot order has left (≤12/day) or on "Ask the council" (≤12/day) | Opus 5.5 at effort low per voice (`DEBATE_MODEL`) · **≈$0.45-0.85 per sitting** | `council_bots`, `council_ticket` | `/council/`, `/council/<id>/`, the ticket dialog, the council band "Sauron's voices" (staff) | **yes**: every voice nightly at 03:30 on what the market did next; the Hand; overrulings graded | no for the eight (shadow); the Executioner/Champion debate is separate (`trade_debate`, binding after 30 graded trades) |
| 9 | **Market Commentator** | ≤500 words "Bloomberg or Reuters style": overview, sectors, macro, levels, "Forward outlook" | daily 17:30 UTC (L369-372) | fast (Haiku 5.5, low) · **< $0.001** (computed) | `agent_commentator` | bell of every active account ("Daily Market Commentary", first 1,000 chars, no link). No page renders it | **no** (no calls block) | no |
| 10 | **Telegram Eye** | `/status`, `/positions`, `/why`, `/help`, `/q` question, `/orc`, the brake | poll every 15 s (L919-922) | none, except `/q` → Ask Sauron | `telegram_eye` | the configured staff group: **anyone in that chat** | no | brake only: bots OFF, never ON |
| 11 | Ask Sauron (research, the Palantír orb) | an answer with citations | on demand | deep · $0.10-0.30 (docstring), guard $0.30 | budget; `lore_staff` OFF | `/research/` and the orb (any login), Telegram `/q` | no | no (read-only) |
| 12 | **Announcements** | release notes "in the house style and in the lore" + who-is-who | by hand: `manage.py announce NAME` | none | none (a command) | the platform Telegram group | no | no |
| 13 | **The Book and the Wall** | the story, the machine, the rules, the road, the bench; the Wall is the front door | static text; counts cached (`core/wall_facts.py`) | none | none | **public** (`/book/`, `/wall/`, no login) | no (counts only) | no |
| 14 | Orcs' dossier MK9 (+ MK-E) | `horizon` (tilts), `prophecies: "—"`, `season: "no season objective set by the operator"`; MK-E "— (no order yet today)" | at the day roll (L532-535) | none (code) | `orcs` | read by the Orc minds (shadow), `/orcs/` (staff) | n/a | no (shadow) |
| 15 | **Big Money board** | where the large players must move: rebalancing, London fix, COT, trend followers, the tide, forced flows ahead | 05:20 UTC daily, 23:20 UTC Mon-Fri (L948-957) | none (code) | `big_money_board` | `/big-money/` (any login), the morning digest, the ticket note, the Awakened | **yes**: every cell against later closes; calibration agent `big_money`, 120 h | no (source-scan test) |
| 16 | Digests (morning, end of day) | the book, signals, events, news, Big Money lines | 07:00 / 17:00 UTC | none | `pipeline_digest` | Telegram / email | no | no |
| 17 | Dormant | `speech_analyst` (central-bank hawkish/dovish), `macro_interpreter` | never: not wired to any task | fast / balanced | none | listed on `/ai-models/` only | n/a | n/a |

---

## 3. Voice by voice

### 3.1 Horizon: "the 5-10 year view" (the closest to a long-view voice)
- Code: `brain/horizon.py` (agent `horizon`, `default_tier = "frontier"`, L340-380), `brain/horizon_models.py` (`HorizonView`), `brain/tasks.py:78-92` (`@guarded_task("agent_horizon")` then `@spend_guard(tier="frontier", estimated_usd=1.5)`), `dashboard/views_horizon.py`, `templates/dashboard/horizon.html`, `brain/management/commands/horizon.py`.
- What it writes: `summary_md` (5-12 sentences), per sector of a fixed universe of 16 (11 US sector ETFs + gold, oil, long Treasuries, the dollar, bitcoin): `thesis_md`, drivers, risks, catalysts, `tilt` -2..+2, `confidence`, `calls` (symbol, up/down, 4380 h or 8760 h); asset-class tilts; `regime_claims` ("falsifiable sentences about the macro regime at 6 or 12 months, for the record").
- Its prompt makes it confront itself: `previous_view` = its own last answer and how its calls graded ("say what changed, what was wrong").
- Persistence: the row is written BEFORE the call (`running`), then `ok`, `rejected` (raw text kept, "you paid for it and you get to read it") or `error`. Cost per run stored on the row.
- **The Horizon's two promises** (the phrase is not in the code; these are the two commitments its module, `deploy/RUNBOOK.md` "Horizon: the 5-10 year view" and the Wall all make):
  1. **"No prose without a gradable claim"**: each sector thesis ends in direction calls at 6 and 12 months, graded by the calibration resolver against the first bar at or after the deadline (Brier, trust; `/horizon/` shows "—" until 10 graded calls). The Wall adds: "The first of those calls come due in 2027 — until then this page claims nothing about how right they were".
  2. **"A weak prior by construction"**: the asset-class tilt reaches the share allocator as 1 + 0.05 × tilt × confidence (±10% at weight 1), "never a vote that outweighs graded evidence"; a view older than 45 days reads ×1.00.
  Gaps in promise 1: the **regime claims are stored and never graded** (only sector calls are registered, `register_view_calls`, L694-782); one live call per (agent, symbol), so after the first view most monthly calls are "held by a standing call" and not registered (at most 16 graded calls per 6 months). Grading also needs `pipeline_calibration` ON.
- The command: `python manage.py horizon list | show [ID] | run [--yes] | grade` (`run` without `--yes` prints the cost and does nothing).
- A first live view existed on 2026-09-12 (the `call_key` docstring quotes two of its calls, as the operator read them on the page that day).
- Public face: the Wall section `#horizon`, "The Only Agent Looking Past Friday." (`templates/landing/the_wall.html:4054-4115`). The Book does not mention it.
- Money: yes, indirectly (section 4).

### 3.2 The Mind (BrainReport, regimes)
- Code: `brain/synthesizer.py` (`SauronMindAgent`, L564; prompt L576-604; `synthesize_now`, L1048), `brain/models.py` (`BrainReport`), `brain/tasks.py:13-25` (**no component switch**, only `@spend_guard(tier="deep", estimated_usd=0.15)`), `brain/calibration.py` (hourly resolver), `brain/context.py`.
- Tone: "Tone: terse, concrete, ZERO hedging. You are Sauron, not a weather forecaster." The most "Sauron" voice in the code.
- Regimes: `risk_on`, `risk_off`, `mean_reverting`, `trending`, `blow_off`, `unknown`; hysteresis on flips (0.65 or two votes).
- Never handed P&L, size or order id (`MIND_HIDDEN_KEYS`), but it reads the open positions and each rule's record by venue, so its narrative is not public material.
- Graded: hourly (`resolve_brain_predictions`) and nightly (hypothesis market). Its trust decides whether its pause binds (a low-trust report's pause is softened to watch, `brain/context.py:366-379`).
- Gates: a "feed gate" (no call when fewer than 2 fresh regime probes, staff alerted) and the AI budget. Nothing else: it runs whenever an API key exists.

### 3.3 The hypothesis market and the critic
- `brain/hypotheses.py` (post, vote, resolvers `regime_holds`, `rule_avg_r`, `anomaly_persists`, `price_direction`), `brain/critic.py` (deep, every 2 h, ~5-10 calls a day, "co_sign | dissent | refine", a counter-hypothesis when it dissents at ≥0.7).
- This is the platform's ledger of claims: claim text, deadline, outcome (`pending`, `confirmed`, `refuted`, `unresolvable`), agent votes, per-agent trust. Unresolvable is never counted as wrong.
- Horizons are short: the Theorist's theories 6-720 h; the calibration clamps every direction call at 60 days except the Horizon (8,760 h).
- `KnowledgeNode.KIND_NARRATIVE_THREAD` ("ongoing market narrative", `brain/knowledge_models.py:50`) is declared and **never written**: a dormant seat for a long-running narrative.

### 3.4 The strategist's daily briefing
- `brain/strategist.py` (agent `strategist`, deep; "the platform's daily user-facing voice"; "Cost target: ~$0.30/day").
- Gates: **no component switch** (budget only) and the history gate (no call when the newest Mind report is older than 12 h).
- The Lore: with `lore_background` ON it reads world entries as unquoted background; the output is scrubbed (`lore/guard.py`) before anything is saved, pushed or posted.
- Fan-out: `bot_program/notifications.py:2375` `notify_strategist_briefing_to_all`: title "Sauron briefing — <POSTURE · measured: ...> (<date>)" to every user with `receive_strategist_briefing` (default False), through their one channel (in-app, Telegram, email, Discord).

### 3.5 Morning briefing (legacy), Monday plan, weekly review / newsletter
- `ai_agents/tasks.py`: `DailyBriefingAgent` (L43, balanced), `generate_daily_briefing` (L707-793), `MondayPlanAgent` (L140, balanced), `generate_monday_plan` (L1431-1553), `generate_weekly_review` (L1084-1231) with `ai_agents/agents/weekly_reviewer.py` (deep, `answer_tokens = 16384`).
- All three end in the calls block (`CALLS_INSTRUCTION`, `ai_agents/calibration.py:387`): direction calls graded nightly; horizons clamped to 1 h-60 days.
- No account money in their prompts since 2026-10-24 (percent, R and counts only).
- The weekly review IS the week's letter (`alerts/newsletter_service.py`, `weekly_draft` L1162, `announce_draft` L1208): READY at once, sent Sunday 08:00 Paris unless cancelled. It is the only recurring voice that goes **out** to people on its own (email or their own Telegram chat), opt-out, investors excluded. Archive `/newsletters/` (login; an edition kept for staff shows only its title to others).
- **Next Steps** (`ai_agents/next_steps.py`, switch `agent_next_steps`, fast tier) reads these reports back and proposes `pause_rule` / `reduce_size` / `watch` / `note` on `/briefing/#next-steps`. "NOTHING ACTS ON ITS OWN": an approved pause or size cut becomes a RuleAction proposal that an admin applies under `actuator_mode_live`.

### 3.6 The Council of ten and the Emperor (visions, moods, the Hand)
- `ai_agents/agents/council.py` (law L1-55), `ai_agents/council_grading.py`, `ai_agents/council_mood.py`, `dashboard/council_band.py`, `dashboard/views_council*.py`.
- The operator's own words in the header: "the visionary platform we aim at ... a global, clear and omniscient vision of the market."
- The most mythic prompts in the code:
  - the Emperor (L437-495): "balanced, smart, patient, visionary. You do not trade battles; you win a war", "follow the long-term view (the Horizons)", "the balance of the whole campaign"; his WAR brief carries the Horizon's tilt for the class (L1555-1572) and "season objective: none set by the operator".
  - the Awakened (L380-406): "You see the game behind the tape and you despise how it is rigged ... name the trap, the hunter and the prey ... a trap without a footprint is a conspiracy theory and you do not deal in those." The nearest thing to the Prophecies' "manipulations", held to cited footprints.
  - the Theorist (L408-432): "explicit, falsifiable theories" posted to the hypothesis market (6-720 h).
- The Hand of the Emperor: the best-measured voice per (regime, class), after 30 graded calls in that cell at weight ≥1.15. The people's mood: computed by code from the real-money book, "may only counsel caution, never boldness".
- It sits only on a trade (a live bot order that left, or a live ticket when its owner clicks "Ask the council"): it is **not independent**. Gated by `platform_master` and its lane switch (L2455-2470). Paper and demo are never argued.
- Cost: each voice is priced before the call by `estimate_usd` (L2127: chars / 3 × $4 + 1,500 × $20 per Mtok, × 1.5, floor $0.03): about $0.05-0.08 per voice, ten voices, so ≈$0.45-0.85 a sitting.

### 3.7 The Market Commentator
- `ai_agents/agents/market_commentator.py` (35 lines, `default_tier = "fast"`), `ai_agents/tasks.py:1370-1424`.
- Context: 20 live quotes (watchlist first), the top 5 movers, 10 active signals, 5 headlines, events ±24 h. Nothing from the account.
- Output: `Notification.create_for_all('system', 'Daily Market Commentary', commentary[:1000])`: an in-app bell row and live banner for every active account (`alerts/models.py:301-325`), no Telegram, no email, no link. `/api/market-commentary/` (login) returns the newest such notification; no template calls it. The full text survives only in its AgentTask row.
- Its prompt asks for a "Forward outlook" but carries no calls block: **the only scheduled forward-looking prose on the platform that is never graded**, against the runbook's "No prose without a claim the platform can grade".

### 3.8 The Eye's Telegram voice, the alarm, Morgul, announcements
- `bot_program/telegram_eye.py` (header L1-87): replies in English, house style; `/q` goes to Ask Sauron; "Its only write to trading state is the brake: /stop and /stopall turn bots OFF, never on."
- **It authorises by chat, not by sender** (L1525-1600: the chat id must belong to exactly one active staff user; the sender id is only logged). Anyone in that group can read `/status` and `/positions` and press the brake.
- `core/announcements.py`: one announcement today (`OCTOBER_TURN`, "THE EYE TURNS · Sauron Vision, October 2026"), sent once per chat by `manage.py announce`, "Nothing here says a number of the book, promises a return, or names a person."
- `core/day_of_sauron.py` names the platform's voices itself: stage TELL = "Two Telegram voices, the dashboard, the public Wall."

### 3.9 The Book and the Wall
- `/book/` "THE BOOK OF SAURON" (`core/views_book.py`, `core/book_content.py`) and `/wall/` (`core/views_wall.py`): public, no login, read-only, counts from `core/wall_facts.py`, the public text walked for private terms (`core/leak_walk.py`). One staff-only chapter is read from outside git.
- The Book's rules (`book_content.py:28-39`): no name, no account figure, no ticker held, plain English, every sentence traceable. Static: they tell the story, they do not foretell.

### 3.10 The Orcs' dossier MK9 and the Emperor's line
- `bot_program/orcs/dossier_market.py`: MK0 is built at the day roll (21:03/22:03 UTC) and is immutable for the day; MK9 = the long view, quoted in section 1. MK-E (L258-267) "the Emperor's line" holds "— (no order yet today)" until O2c writes "the Emperor's daily order (§4.6)".
- Read only by the Orc minds, in shadow (`orcs_minds`, turned on by the operator today).

### 3.11 The Big Money board
- `bigmoney/` ("Where the large players MUST move ... Information, never a gate", `bigmoney/__init__.py`; the page's lede in `bigmoney/words.py`). Pure code, no model. Two reads a day. Every cell graded against its proxy's later closes (`bigmoney/score.py`; one automatic rule: a footprint that works against its claim drops to weight zero, never raised).
- Read by: `/big-money/` (any login), the morning digest, the TAKE TRADE ticket note, the Awakened. A source-scan test keeps it off every money path.
- The nearest code to the Prophecies' "big forces", at a horizon of days to weeks.

---

## 4. Can it touch money? (it must not)

Read in the code, at 15dd487:

| Voice | Who reads it on a money path | How |
|---|---|---|
| **The Mind** | `bot_program/asset_engine/base.py:4977-5016` | a rule `pause_recommended` (fresh report or the remembered KnowledgeNode) **skips a bot entry, real money included** (fail-open) |
| | `signals/rules/bearish_rules.py:297` `regime_gate` | `risk_off` at ≥0.65 opens the bearish rules |
| | `bot_program/market_stress.py:79-88, 229-236` | 10% of the crisis score; the posture sizes real-money entries while `crisis_mode` is ON |
| | `bot_program/share_allocator.py:238` `market_state`, L641 | `risk_off` / `blow_off` at ≥0.65 puts plans in SHOCK (de-risk); the regime-fit factor |
| | `bot_program/persona_mix.py` | the regime moves the personas' share bands |
| **Horizon** | `bot_program/share_allocator.py:86-101, 662` `horizon_for` | the fifth factor 1 + 0.05 × tilt × confidence × persona weight (scalp 0, swing 0.5, position 1.5), clamped 0.85-1.15, in every SharePlan. Plans are shadow; applied with the PIN in LIVE mode (`share_allocator_mode_live`), or automatically for a SHOCK plan that only lowers shares (`share_allocator_auto_derisk`) |
| Hypothesis market | `brain/demoter.py` | a refuted generator hypothesis pauses that generated rule |
| Briefing, Monday plan, weekly review | Next Steps | only as proposals a person approves, then an admin applies |
| Strategist, council (eight), commentator, announcements, Book, Wall, Big Money, Lore, Ask Sauron | none found | the strategist's posture "sizes nothing"; the council is shadow (`tests/test_council_shadow.py`); Big Money and the Lore are fenced by tests |
| Telegram Eye | the brake | bots OFF only, never ON |

Consequence: **the two voices with the most "prophetic" nature (the Mind, the Horizon) are wired to money.** Neither can become a free, public, prophetic voice as it is: a voice people watch must have no reader on a money path, so it must be a new agent with its own table and a fence test (the precedents: `lore/policy.py` "never readers" with `tests/test_lore_fences.py`; `tests/test_big_money_board.py`'s source scan). It may READ the Mind, the Horizon, Big Money and the Lore; nothing may read it back.

---

## 5. Which existing feature is closest to what he describes?

His words, as criteria: (a) **independent** (runs by itself, not tied to a trade or a question), (b) **prophetic** (forward-looking, the long view, the world), (c) a **lasting record**, (d) **graded** against what happened, (e) **observed** (seen beyond staff), (f) **feared / supported** (people react), (g) **money-free**.

| Candidate | a | b | c | d | e | f | g |
|---|---|---|---|---|---|---|---|
| **Horizon** | yes (monthly) | **yes** (5-10 y), sectors only | yes (HorizonView rows) | partly (sector calls yes; regime claims no) | partly (page needs a login; told on the public Wall) | no | **no** (allocator prior) |
| The Mind | yes (hourly) | short (hours to days) | yes | yes | login | no | **no** (wired) |
| Strategist | yes (daily) | short (24-72 h) | yes | partly (ideas) | login + opt-in push | no | yes |
| Weekly review / newsletter | yes (weekly) | short (next week) | yes (`/newsletters/`) | partly (calls) | **yes** (the only voice sent out to people by default, opt-out) | no | yes |
| Council (Emperor, Awakened, Theorist) | no (sits on a trade) | short (24-168 h; theories ≤720 h) | yes | **yes** (best graded) | staff | no (the "mood" is the book) | yes (shadow) |
| Hypothesis market | a place, not a voice | short (≤720 h) | yes | yes | login | agents only (co-sign / dissent / refine) | adjacent |
| Big Money board | yes (2 reads a day) | short (days to weeks), the big players | yes | yes | login | no | yes |
| Book / Wall / announcements | no (hand-written) | no | yes | no | **yes** (public, the group) | no | yes |
| Market Commentator | yes (daily) | mild ("Forward outlook") | no (bell, cut) | **no** | every account's bell | no | yes |
| The Lore (library) | no (silent; the distiller is not built) | no | yes | no (evidence grades, not outcomes) | staff only | no | yes |

**Answer.** Nothing at 15dd487 does all seven.
- **Closest in spirit: the Horizon.** Independent, the long view, a lasting record, graded, and already presented publicly ("The Only Agent Looking Past Friday"). But it is OFF on arrival, sector-and-asset-class only (no "great forces", no manipulations), wired to money through the share allocator, behind a login, with half its claims (regime claims) never graded, and nobody can react to it.
- **Closest in audience: the Book, the Wall and the announcements** (public, mythic, the who-is-who), but hand-written and silent about the future.
- **Closest in mechanics for "supported / feared": the hypothesis market** (claim, deadline, outcome, votes, trust), but only agents vote and the horizons are short.
- **Closest in character: the council's Emperor and Awakened** (the war, the campaign, the season, the rigged game), but bound to single trades and staff-only.
- What he describes is the **Prophecies** (studied 2026-10-09: the great forces, power and manipulations, falsifiable signposts, graded over years, a forum pillar) with the **Court** for the people (studied 2026-10-08). Neither was built. MK9's `"prophecies": "—"` is the empty seat waiting for it.

---

## 6. What is missing to get there

1. **Independence from money.** A new agent (not the Mind, not the Horizon), its own table, nothing on a money path reading it, a fence test (lore / Big Money precedents). It may read the Mind, the Horizon's tilts, Big Money and the Lore (a new reader in `lore/policy.py` is a decision: today the Horizon and the Mind are listed "never readers").
2. **Its own subject.** No agent covers the great forces (central banks, debt, energy, demographics, geopolitics, elections) or documented manipulation mechanisms. `speech_analyst` and `macro_interpreter` exist but are wired to nothing. FRED series and COT are stored and could serve as signposts.
3. **Long-horizon grading.** The calibration clamps direction calls at 60 days except the Horizon's 8,760 h; the hypothesis market's resolvers are `regime_holds`, `rule_avg_r`, `anomaly_persists`, `price_direction`. A prophecy graded over years needs dated **signposts** (thresholds on FRED series and prices, each with a deadline), multi-year deadlines, honest "unresolvable", and a public score that "claims nothing until the first calls come due" (the Wall's rule for the Horizon).
4. **A lasting record people can see.** HorizonView, Hypothesis and AgentPrediction rows are internal. A public or members' "book of prophecies" needs dated, immutable published text (hashed, like the audit chain), each prophecy's signposts, status and grade, the leak walk (`core/leak_walk.py`) and the Book's rules (no account figure, no ticker held, no name).
5. **Visibility beyond staff.** Today: staff, any login, investors (one book), the public pages. No member / Knight role, no members-only space (the Court). On Telegram, the Eye's group accepts `/positions` and the brake from anyone in it: a prophecy feed must never go there; it needs a separate read-only channel. The newsletter (opt-out audience, delivery ledger) is the one existing carrier that already reaches people.
6. **People reacting (watch / support / fear).** Nothing exists. `HypothesisVote` is the pattern to copy for people (one stance per member per prophecy, counts shown; perhaps members' own graded predictions). "The people's mood" exists only as a gauge of the book.
7. **Law and tone** (studied in #105 and #106): public forward-looking statements about markets → MAR art. 12 / investment-recommendation rules and the AMF's finfluencer line; named actors with "manipulation" → defamation; no promise of returns; no instrument call to non-staff; Tolkien names. A law pass before anything leaves staff.
8. **Switches.** OFF on arrival, exempt from "all on" (like the Lore readers), and a second, separate decision for publication beyond staff (the `lore_background` / D1 precedent).
9. **Cost.** Small: a monthly frontier pass is ~$1.5 (the Horizon's precedent), a weekly deep pass ~$0.3-0.5, against the Mind's ~$0.15 every hour.

What a build could reuse as it is: `AgentPrediction` + the calibration resolver with `max_horizon_hours` (the Horizon's 12-month path); the hypothesis market (claims, outcomes, Brier, trust, the vote model); the HorizonView pattern (row before the call, rejected answers kept); `lore/policy.py` + `lore/guard.py` (deny-by-default readers, scrubbed output); `core/leak_walk.py`; `core/announcements.py` + `alerts/channels/telegram_alert.fit_text` (the house style); `alerts/newsletter_service.py` (audience, opt-out, delivery ledger); MK9's `prophecies` slot for the Orcs.

---

## 7. Side findings (outside the question, worth knowing)

1. **The Mind and the strategist have no component switch.** They run whenever an API key exists, bounded only by the AI budget (and their feed / history gates). The Mind is the largest recurring AI cost (~$0.15 an hour by its own estimate).
2. **The Telegram Eye trusts the chat, not the person.** Anyone in the configured group can read `/positions` (the open book) and press `/stop` / `/stopall` (OFF only). `core/announcements.py` speaks of "the viewers and the loyals" reading that group: if anyone besides the operator and the keeper is in it, they see the book and hold the brake. (Code fact; who is in the group is not in the code.)
3. **The Market Commentator's "Forward outlook" is never graded**, its text is cut to 1,000 characters in the bell, and no page shows it. Safe to turn on today (one account, Haiku, under a tenth of a cent a run), but it is the one forward-looking voice that breaks the "no prose without a claim" rule.
4. **The Horizon's regime claims are never graded**, and the one-live-call-per-symbol rule leaves most monthly calls unregistered after the first view.
5. **The legacy morning briefing's bell links to `/briefing/`**, which shows the strategist's briefing, not that text.
6. **Declared, never built**: the Lore's distiller ("Sauron's lesson"), `KIND_NARRATIVE_THREAD`, MK9's prophecies, the Emperor's season objective, the Emperor's daily order (O2c).
7. `Notification.create_for_all` reaches every active account, investor logins included (moot with one account; it matters for any members' design).

---

## 8. En deux mots (pour la note en français)

- Non, le Lore n'est pas ça : c'est la bibliothèque de Sauron, réservée au staff, qui ne dit rien d'elle-même (même son "distiller", qui devait écrire les leçons de Sauron, n'est pas construit).
- Ce qui s'en approche le plus aujourd'hui, c'est **Horizon** : une vue à 5-10 ans, une fois par mois, notée à 6 et 12 mois. Mais il est OFF à l'arrivée, limité aux secteurs, visible seulement une fois connecté, et il pèse (un peu) sur l'allocation : il ne peut pas devenir la voix publique telle quelle.
- Ce que tu décris, une voix indépendante, prophétique, que les gens regardent, craignent ou soutiennent, ce sont **les Prophéties** (étudiées le 9 octobre) avec **la Cour** (le 8 octobre). Rien n'a été construit ; la place est réservée dans le dossier des Orcs : `"prophecies": "—"`.
