# The Oculus as mission control: spec

Spec, 2026-11-06. It reads `mainread` at `d81a035` and `origin/main` at `38ed1ab` (S0 merged). Between the two, none of the Oculus files changed (`git diff d81a035 origin/main` on `dashboard/oculus.py`, `dashboard/views_oculus.py`, `templates/dashboard/oculus.html`, `tests/test_oculus.py` is empty). Only `core/platform_control.py` gained the Orc switches.

Inputs:
- the Oculus map (`scratchpad/oculus/`: shots, `tools/report.json`, scale runs);
- the approved UI plan (`scratchpad/uiplan/ui_plan_spec.md`) and its preview boards (`scratchpad/preview/project/*.dc.html`);
- the eToro feed spec (`scratchpad/feed/etoro_feed_spec.md`);
- the branches in flight (`claude/etbudget`, `claude/pnltruth` = PR #89, `claude/railfilters` = PR #90, `claude/uis1a`).

This is a plan. Nothing is built here, and nothing in any worktree was written.

**The mock.** A static mock of the page after O2b sits at `scratchpad/oculus/oculus_mock.html`. It uses synthetic data, is 1,440 px wide, and is drawn in the S1b shell and the approved preview's style. It is built by `tools/mock_build.py` and rendered offline by `tools/mock_shot.js`:
- `shots/mock_1440x900_first.png` is the first screen;
- `shots/mock_1440_full.png` is the whole page.

It has no text under 11 px and no horizontal overflow. A dashed line marks where the first screen at 1440 × 900 ends.

Every stage below is one pull request that changes display only. The engine, the bots, the Orcs, the gates, the desk, the ticket and every money switch see exactly what they see today. Every commit message says "Money direction: none. Display only."

---

## 0. In one page

**What the Oculus becomes.** The Oculus stays the page "every cycle this platform runs, on one screen", the first row of AMON HEN. Today it is a long column of counts that starts below the fold. It becomes a mission control in the new kit:
- **One status line** answers the questions in one row: does anything need me, is real money armed, the kill switch, the guards, the prices, the beat, the bots, AI spend, and how old this reading is.
- **A "needs you" list** names what is wrong, why, since when, and which page fixes it.
- **The cycle map** shows the seven stages the platform already speaks (SEE, THINK, DECIDE, ACT, WATCH, TELL, LEARN, from `core/day_of_sauron.py`). Each has its state, its last run judged against its own schedule, and its task list one click away.
- **The money block** puts REAL, DEMO and PAPER side by side, never summed. Beside them it shows eToro's own account cells and a protection checklist: stops held at eToro, stuck closes, margin and free cash, daily loss, drift, the kill switch and the Morgul brake. It is display only: every action is a link to the page that already holds it, behind the PIN.
- **The other blocks:** prices and the eToro request budget; what acts and what only watches; AI spend; and the last hour.
- **The eleven cycles of today stay below, grouped by stage.** They are dense and readable, and every count now carries its window and its threshold.

**The house truth rules are kept, and extended.**
- A number is measured; a dash is not measurable; a switch is shown beside what it gates.
- Every dash is named at the foot of the page, the book's included.
- Every stored reading prints its age.
- Every count says its window.
- Amber appears only when a stated threshold is crossed, and always with ⚠ and words.

**Cost goes down.** Every new block reuses a reader that already exists, and none of them is new arithmetic:
- `day_live_payload`, the /command/ ring;
- `activity_events`, the Activity drawer;
- the headband's cached `_panel_detail`;
- the Morgul summary in the cache;
- `spend.lines_summary`;
- `etoro_budget.report`, which reads the cache only;
- `feeds.feed_states`.

The existing cycles go from 81 queries to about 30. The forge's file walk and migration plan run once per build, not on every staff GET.

**The stages.**

| Stage | One PR | What he will see | Starts when |
|---|---|---|---|
| O0 | Cost and truth, today's look | REAL no longer counts eToro demo rows; every dash named, the book's too; probe and forge readings dated; every count with its window; "not due yet" no longer amber; about a third of the queries | Now; needs no approval (like S0) |
| O1 | The look | The same facts in the new kit: a one-line promise, the book in three worlds, the eleven cycles grouped by stage in dense cards, the forge as a strip; nothing under 11 px; amber only past a threshold | S1a merged |
| O2a | Is it safe, is it turning | Status line, needs-you list, cycle map with every task against its own schedule, money safety with the protection checklist, the last hour; live by small parts on existing readers | O1; uses PR #89's words when merged |
| O2b | What acts, what it costs | What acts vs what only watches (bots, the 12 money switches, desk and allocators, ladder, Orcs, Council), AI spend per line with Orc wakes, feeds and held-instrument price ages, eToro's request budget and the 429 pause, the signal rail's lifecycle | O2a; etbudget merged (budget), PR #90 merged (rail) |
| O3 | Feed-grade live | Per held instrument LIVE / RECENT / STALE / CLOSED / NONE with confirm and print ages, stream up or down, latency, transitions in the timeline; badges and eToro P&L ride F7's push with no Oculus poll | F6 (server side), then F7 (push) |

**What we need from him** (the French note asks it):
1. OK on the order of the blocks: status line, needs you, cycle map, money, prices, what acts, AI, last hour, then the slow cycles.
2. OK that the eleven slow cycles move below the "now" blocks, grouped by stage, with their explanations one click away.

---

## 1. Inputs and constraints

**His words (2026-11-06, verbatim):** "Améliorer oculus système aussi svp". This sits within the UI plan's orders: "un smart melange de bloomberg et trading view sous sauron", "sombre, surtout sur ordinateur".

**What the map measured, and where each finding is fixed:**

| Finding (map ref) | Evidence | Fixed in |
|---|---|---|
| The answer starts below the fold (B1.1) | First number at y=674. First cycle at y=1,410 (1440), 1,365 (1920), 1,333 (2560). Page 5,030 px tall at 1440. 9–10 of 75 numbers above the fold | O1 (order), O2a (status line, needs you) |
| Fixed chrome covers the book (B1.2) | Gollum's bubble and the Horde bar over the left column | S1b (shell); O1 adds end padding only |
| Text under 11 px, labels at 3.15:1 (B1.3) | 106 of 352 text nodes under 11 px; `#3a6850` on questions, qualifiers, caveats, OFF chips | O1 (on S1a's tokens) |
| Amber means "read twice", not "act now" (B1.4) | 28 caution facts amber whatever their value; a dash in a caution row turns amber (`tr.caution .ocu-v` beats `.ocu-v.dash`) | O0 (thresholds in data), O1 (paint) |
| Money unreadable (B1.5) | No currency or grouping; `int()` truncates 473.8 to 473 and −0.6 to 0 | O0 (values), O1 (format) |
| Grid waste (B1.6) | Rows stretch to the tallest card (1,039 px); cards 349 px wide; the book 2,200 px wide at 2560 | O1 |
| Fake text behind numbers (B1.7) | Ambient log lines show through the translucent cards | S1a (calm background) |
| Sparks and chips hard to use (B1.8) | No axis, no today, brand green; chips print raw keys | O1 |
| Is it turning? Missing: last run against schedule, bot heartbeat, /health/ verdicts, feed health, request budget, Orcs and AI spend, rail lifecycle (B2.1) | `_gate` reads `last_run_at` and `last_status` and the template drops them (oculus.py:234-235) | O2a, O2b, O3 |
| Is my money safe? Missing: armed money switches, kill switch, Morgul, stops at eToro, stuck closes, cash and margin, drift, daily loss, worlds, Brokers/Treasury/Withdrawals links (B2.2) | None on the page | O0 (worlds), O2a |
| "LIVE · REAL MONEY" counts eToro demo rows (B3.1) | `book_risk` filters on `paper` only (capital_desk.py:614-618). In the fixture, one demo row carried 450 of the 473.8 shown as real and turned "budget left" into −403. The Horde said REAL 4, the book said 5 | O0 |
| The paper column's capital includes live configs (B3.2) | 28,500, of which 3,500 is live | O0 (labelled) |
| Pool capital ≠ equity; budget ≠ open-risk limit (B3.3) | Two ceilings, neither named | O0 (words), O2a (eToro's own cells beside) |
| Governor "100" ambiguous though `budget_for` knows (B3.4) | `reason`, `drawdown_pct`, `currency`, `not_summed`, `n_other_currency` dropped | O0 |
| Lifetime totals read as current state (B3.5) | No window shown | O0 |
| "Unresolved", "never graded", "awaiting a grade" include what is not due (B3.6) | The resolver's own `not_due` (opportunity_scanner.py:2223-2232) | O0 |
| Probe counts undated; "Nothing is cached" half-true (B3.7) | The stored `at` is ignored (oculus.py:844-850) | O0 |
| The footer misses the book's dashes; failures logged at DEBUG (B3.8) | The loop at 1019-1021 reads `cycle["facts"]` only | O0 |
| Expectancy gap coloured on 4 trades (B3.9) | `min_n=1`, red at −1.13 | O0 (floor in words), O1 (paint) |
| Constants and dated prose (B3.10) | "personalities defined 3", "tests on the wall 15250", "about 179 instruments", "ten panels", "thirty dashboards", the `L'` comment | O0 |
| The forge on every staff GET (B4.1) | 1,297 `.py` files (24.9 MB) read, and a migration plan built, per GET | O0 |
| 81 queries per call, 157 per page (B4.2) | PlatformComponent 14, Signal 7, AgentPrediction 5, RuleControl 5, … | O0 |
| Lifetime counts on unindexed columns (B4.3) | `AgentPrediction.prediction_type`, `Signal.is_active` alone, `DeskPlan.mode`; trust 193 ms at the six-month scale | O0 (aggregates), cache only if the measurement misses |
| No caching, no partial refresh (B4.4) | Each reload is the whole page | O0 (forge), O2a (parts) |

**Work in flight that touches the Oculus's inputs:**

| Branch | State | What the Oculus takes from it |
|---|---|---|
| `claude/uis1a` (S1a) | Building; the preview was approved | Tokens, faces, the kit (card, state chip, fresh badge, KPI tile, notice, table, world chips), the calm background. O1 waits for it |
| S1b (shell) | After railfilters and pnltruth | First content at y≈92, 32 px status bar, Gollum and the Horde docked. The Oculus measures its overlap acceptance after S1b |
| PR #89 `claude/pnltruth` | Open | eToro's own P&L per row (`venue_pnls`), the band's `panel_etoro` (eToro's used, available, P&L and total, with ages), the coverage words. The money block prints them; without them it prints the marks' P&L with its source words |
| PR #90 `claude/railfilters` | Open | `dashboard.RailDeparture` (why a signal left the rail, and passes and takes), and the rail's counts. The THINK cycle shows them (O2b) |
| `claude/etbudget` | Rebasing | `bot_program/engine/etoro_budget.report()` and `pause_left()`, which read the cache only. The budget meters (O2b) |
| `orcs2b` | Merged (`acaabe3`) | `ORC_MIND_SWITCHES`; `bot_program/orcs/switches.py` (`orcs_on:40`, `minds_on:95`, `router_on:109`, `probes_on:120`, `frontier_on:130`); `OrcWake` statuses. O2b |
| Feed F6, F7 | Spec | F6: `feed_status`, `FeedTransition`, Morgul G10v, the eToro feed in `/api/live/health/`. F7: the venue push, `sv-venue.js`, latency on /health/. O3 |
| Worlds C1–C3 | He said yes; not built | The desk stops counting demo (real-only limits). Until then O0 says, in words, how many demo rows the desk's live budget still counts |

**House rules that bind every stage:**
- Display only. "Money direction: none" in every commit.
- No broker call and no model call to draw the page. Tests prove it (§6).
- Never weaken a test.
  - A test that pins a look is updated to the new look, with the reason in the commit.
  - A test that pins a meaning is kept: the dash rule, staff-only switches, the book per viewer, the governor's "TWO", the expectancy caveat, every drill-down reverses.
- Synthetic data only in fixtures, screenshots, mocks and tests. The repository is public.
- Faces from Google Fonts only (Inter, JetBrains Mono). Tokens and components come from S1a.
- Staff and viewer stay apart exactly as today (`STAFF_ONLY_CYCLES`, `/health/`'s rule).

---

## 2. The questions it answers at a glance, in priority order

The order is "consequence × urgency". Money comes before machinery. The first question is a projection of all the others, so nothing urgent can hide below the fold.

| # | Question | At a glance (status line cell) | In depth (block) | Who |
|---|---|---|---|---|
| 1 | Does anything need me now, and why? | VERDICT: `● all clear` / `⚠ 2 need you` / `⨯ 1 critical` | Needs you: what, why, since when, the page that fixes it | Everyone, own items; staff, platform items too |
| 2 | Is my real money protected right now? | REAL MONEY (armed, how many bots), KILL SWITCH (ready, or fired when and why), GUARDS (quiet or findings, age) | Money safety: REAL / DEMO / PAPER, eToro's account cells, stops at eToro, closes, margin and free cash, daily loss, drift, kill switch, brake | Own book for everyone; guards for staff |
| 3 | Is every cycle turning? | BEAT (last task, how many late or broken) | Cycle map: seven stages, each against its own schedule, its tasks one click away | Staff (states); the viewer sees the stages without states |
| 4 | Are prices live, and is eToro's request budget holding? | PRICES (`eToro · live`, n of m feeds) | Prices and requests: feeds, each held instrument's source and age (grades from F6), the four request families, the 429 pause | Feeds for everyone; budget for staff |
| 5 | What acts on real money, and what only watches? | BOTS (LIVE / PAPER / SHADOW / HALTED / STALLED, tick age) | What acts: bots, 12 money switches, desk and allocators, the ladder, the Orcs, the Council | Own bots for everyone; switches for staff |
| 6 | What is AI spending? | AI TODAY (`$3.12 of $15.00`) | AI: per line against its cap, Orc calls and wakes, top spenders | Staff |
| 7 | What changed in the last hour? | (needs you, when it matters) | Last hour: fills, closes, refusals, guard findings, PIN switch flips, Orc answers, alerts; feed transitions from F6 | Staff |
| 8 | Is the platform learning, or only running? | — | The slow cycles by stage: scan, signals, ladder, personalities, allocation, evolution, backtests, the simulator against execution, confidence, horizon | As today |
| 9 | Which code is running? | — | The forge strip | Staff |

---

## 3. The page, top to bottom

### 3.1 Wireframes

**1440 × 900, S1b shell** (content 1,136 px; first content line at y≈92; status bar at y=868):

```
+-------------+-------------------------------------------------------------------------+----+
| [eye]SAURON | OCULUS                        14:53 UTC  6/14  ● eToro·live  [REAL ARMED] [bell][lock] |
|             +-------------------------------------------------------------------------+ D  |
| AMON HEN    | EURUSD 1.08745 +0.12% ● | XAUUSD 2,648.12 -0.39% ● | ...   || headline  | O  |
| (o) Oculus  +-------------------------------------------------------------------------+ C  |
|     Ops ... | ⚠ 2 NEED YOU | REAL ARMED·2 | KILL ready | GUARDS ⚠1 | PRICES ● | BEAT ● 40 s | BOTS LIVE | AI $3.12/$15 | 12 s ⟳ |  52
|             +-------------------------------------------------------------------------+ K  |
|             | NEEDS YOU · 2                                                            |    |
|             | ⚠ Stuck close  XAUUSD (REAL) pending at eToro 42 min, 8 retries     Positions ›|  ~122
|             | ⚠ 2 tasks late  calendar (every 30 min) 2 h · anomaly (hourly) 4 h  Health ›   |    |
|             +-------------------------------------------------------------------------+    |
|             | THE CYCLE                                  64 tasks · 62 on time · 2 late    |    |
|             | [SEE ▲]→[THINK ▲]→[DECIDE ●]→[ACT ●]→[WATCH ●]→[TELL ●]→[LEARN ●]          |  ~186
|             |  ↺ LEARN feeds THINK the next morning                                      |    |
|             +---------------------------------------------+---------------------------+    |
|             | MONEY SAFETY · display only                 | PRICES AND REQUESTS        |    |
|             | [REAL] | [DEMO] | [PAPER]   never summed    | feeds · held · eToro budget|    |
|             | eToro account: equity · used · free cash    |                            |    |
|             | protection: stops · closes · margin · ...   |                            |    |
+-------------+---------------------------------------------+---------------------------+----+
| (G) PORTFOLIO | OPEN P&L | POS | SIG | BOT | ALERTS | DD | +6 | HORDE                    (Eye) |  32
+---------------------------------------------------------------------------------------------+
   below the fold: WHAT ACTS | AI · LAST HOUR · the slow cycles by stage · THE FORGE · NOT MEASURED · stamp
```

The first screen at 1440 × 900 (S1b) holds the status line, the needs-you list, the cycle map, the three worlds, eToro's account cells and the first protection rows. That is two rows with two needs (the mock's first screen), and about five when the list is one 36 px line because nothing needs him.

**In today's shell** (before S1b: first content at y=184, reading height 655) the first screen holds the status line, the needs-you list and the cycle map. That is three answers above the fold instead of nine of 75 numbers with none of the answers.

**1920 × 1080 (S1b):** content 1,600 px. Same order. What acts, AI and the last hour sit in one row (4 + 4 + 4 columns), and its headers show above the fold. The slow cycles run in three columns.

**2560 × 1440:** content ≈ 2,216 px.
- Money, prices and what acts sit in one row (5 + 4 + 3).
- AI, the last hour, and the forge with "not measured" sit in the next row (3 + 6 + 3).
- The slow cycles run in four columns.
- Everything but the slow cycles is on the first screen.

**1280 × 800 (S1b):** content ≈ 976 px.
- The status line wraps to two rows (container under 1,100 px).
- The cycle tiles keep one metric line each.
- Money and prices stay 7 + 5. What acts and AI stay 6 + 6.

The **rail open** narrows the main column. Every region reacts to its container (`container-type: inline-size` on the main column, UI plan §6.3), so the same rules apply with no page code.

### 3.2 The regions

Each region is a kit card: bg-1, 1 px line-2, radius 6, a 40 px header with its title (12 px uppercase ink-2) on the left. The header's right side carries the meta: "read 12 s ago", "staff", "display only", and a ⟳ that re-fetches only that region.

#### R1. The status line (O2a; 52 px, full width)

One row of status cells, as in the UI plan's status bar (§7): label 11 px uppercase ink-3, value mono 13, sub-text 11 ink-3, and a state dot with its word. A cell is a link to its region or its page.

| Cell | Who | States (dot + words) | Source (existing) |
|---|---|---|---|
| VERDICT | All | `● all clear` (Eye) / `⚠ N need you` (amber) / `⨯ N critical` (coral) | The count of R2's rows by level |
| REAL MONEY | All | The REAL chip `armed · N bots` (the armed pill's style, the one solid red), or `not armed` in ink-3. Its title (staff) says `M of 12 money switches on`; R6 lists them | `panel_bot.live` (`core/context_processors.py:549 _bot_truth`); the component rows ∩ `LIVE_MONEY_SWITCHES` (platform_control.py) |
| KILL SWITCH | All | `ready` with `■ page ›` (superusers), or `⚠ fired 2 h ago · <reason>` while within 7 days | `panel_bot.kill_at`, `kill_reason` (context_processors.py:656-677, the read at 660) |
| GUARDS | Staff | `● quiet · 12` / `⚠ N` / `⨯ N critical` / `⚠ last ran 22 min ago` (summary older than 900 s) / `○ off`. Sub: `ran 2 min ago · brake armed` | `cache.get("morgul:summary")` (morgul.py:151, 156 `SUMMARY_STALE_S`); `_brake_armed()` (morgul.py:1772) answered from the shared component rows |
| PRICES | All | The live-health pill's own verdict: `● live` / `⚠ degraded` / `⨯ offline` / `○ idle`. Sub: `n of m feeds` | `market_data.feeds.feed_states()` (feeds.py:352), the verdict `/api/live/health/` computes (dashboard/live_health.py) |
| BEAT | Staff | `● last task 40 s` / `▲ N late` / `✕ N broken` / `○ master off` | `day_live_payload()["beat"]` (views_day.py:349) |
| BOTS | All | `panel_bot.state` in its words (LIVE / PAPER / SHADOW / HALTED / STALLED / OFF / NONE). Sub: `tick 3 min · every 5` | `panel_bot` (`state`, `tick_ago`, `cadence_min`) |
| AI TODAY | Staff | A violet dot with `$3.12 of $15.00`, `⚠` at ≥ 80 % of a line, `⨯` when a line is spent | `ai_agents.spend.lines_summary()` (spend.py:298) |
| READ | All | `12 s ago ⟳`. The age of this reading, ticking in the browser | The part's render time |

For a viewer, the staff cells render as `GUARDS · staff only`, with the same words as the withheld panels (`/health/`'s rule). They are not dropped.

#### R2. Needs you (O2a; only when non-empty)

A list of kit notices, 36 px per row: the glyph (⨯ coral / ⚠ amber), a title, one line of why, the age ("since 14:11" or "2 min ago"), the source (guard, task, feed, budget), and the page that fixes it.

Order:
1. critical first;
2. then rows about REAL money;
3. then newest first.

Up to six rows show; the rest sit under `+N more`.

When it is empty, one line remains: `Nothing needs you · checked: 12 guards, 64 tasks, 5 feeds, closes, kill switch · 2 min ago`. It says what was checked, so an empty list is never a silence.

It adds no read of its own. Every row is a projection of what the regions below already read. A Morgul finding's "since" is its `first` stamp in Morgul's own memory (`morgul:state`, morgul.py:2224), which is one cache read.

| Source | Condition | Level | Words (example) | Fix page |
|---|---|---|---|---|
| Morgul summary | A finding, critical | ⨯ | `Live without a stop · EURUSD (REAL) has no stop at eToro` | `positions_list` |
| Morgul summary | A finding, warning | ⚠ | `Stuck close · XAUUSD (REAL) close pending at eToro 42 min` | `positions_list` |
| Morgul summary | Older than 900 s while `morgul_guards` is on | ⚠ | `The guards last ran 22 min ago (every 5 min): nothing has checked the book since` | `system_health` |
| Morgul component | Off while REAL is armed | ⚠ | `Real money is armed and no guard watches the book` | `ops_dashboard` |
| Master switch | Off or absent | ⨯ if REAL is armed, else ⚠ | `The master switch is off: every scheduled task is skipped` | `ops_dashboard` |
| Components | `broken` (last pass in error) | ⚠, or ⨯ for a money-path component (`pipeline_asset_bots`, `scraper_etoro`, `morgul_guards`, `telegram_alarm`) | `Signal engine · last run failed 12 min ago · <first line of last_message>` | `system_map` |
| Components | `stale` against their own cadence | ⚠ (grouped past 3) | `2 tasks late · calendar (every 30 min) 2 h · anomaly (hourly) 4 h` | `system_health` |
| Bot program | HALTED or STALLED with bots enabled | ⨯ when a live bot is among them | `panel_bot.reason` | `asset_bots_dashboard` |
| Kill switch | Fired within 24 h | ⚠ | `The kill switch fired 2 h ago (manual): every bot is off until re-armed` | `notifications_inbox` |
| Closes | Any `CLOSE_PENDING` | ⚠ | `1 close pending at the venue, retried every 5 min` | `positions_list` |
| Feeds | The quote-freshness verdict is `fail` | ⚠ | `OANDA stream not delivering` | `system_health` |
| eToro account | Cells older than 1 h (`BROKER_STALE_S`) while REAL rows are open | ⚠ | `eToro's account was read 2 h ago: cash and margin may be stale` | `brokers_page` |
| Request budget (O2b) | A 429 pause holds | ⚠ | `eToro asked us to slow down: marks, proposals and candles wait 41 s; closes and orders never wait` | — |
| Request budget (O2b) | P0 or P1 past a family's rate this window | ⚠ | `Closes went past the execution rate 2 times this minute (never held back)` | — |
| AI (O2b) | A line spent | ⚠ | `The Orcs' AI line is spent for today: their wakes are refused until 00:00 UTC` | `ai_models_dashboard` |
| Forge | Migrations pending > 0; probe found pages raising | ⚠ | `3 migrations not applied on this database` | `ops_dashboard` |

A non-staff viewer gets only the rows about his own book: his closes, his bots, his kill switch, his eToro cells.

#### R3. The cycle map (O2a; ≈186 px)

Seven tiles, left to right, with thin arrows between them: SEE → THINK → DECIDE → ACT → WATCH → TELL → LEARN. The header's meta reads `64 tasks · 62 on time · 2 late · 0 broken · each against its own rhythm · ↺ LEARN feeds THINK the next morning` (`NEXT_OF`, day_of_sauron.py:42).

This is the platform's own vocabulary: the /command/ ring, the Wall, the phone tiles. The Oculus takes it rather than inventing an eighth.

Each tile:
- **Head:** the stage name (11 px uppercase ink-2), then the state chip in the five words of `views_day.STAGE_STATES`:
  - `● live` (Eye);
  - `▲ stale` (amber);
  - `✕ broken` (coral);
  - `○ off` (hollow ink-3);
  - `· quiet` (ink-3).
- **Line 2:** `ran 6 s · 1 of 21 late`, or `ran 3 min · on time`. That is `stages[k]["words"]` and the stage's own task counts.
- **Lines 3–4:** two metrics from `stages[k]["metrics"]`, the ones /command/ already shows:
  - SEE: instruments priced under 15 min, minutes since the newest quote;
  - THINK: signals today, active;
  - DECIDE: bots on, gate refusals today;
  - ACT: opened today, closes pending;
  - WATCH: guards ran, findings standing;
  - TELL: notifications today, unread;
  - LEARN: AI calls, trades graded today.
- **Foot:** a thin 4 px segmented bar of its task states (live in the Eye, stale amber, broken coral, off line-3, quiet line-2). It has no text; line 2 carries the figures (dataviz: thin segmented bar). The tile's title repeats them in full.

**A click on a tile jumps to its stage section in R9**, where the stage's task list opens at the top. The strip itself never expands, so the first screen never shifts. Each row of the task list is one beat entry:
- its words (`STAGE_OF`);
- its component key in mono;
- the state chip;
- `last ran 2 h ago`;
- its rhythm (`every 30 min`, from the scheme's cadence and `views_topology._fmt_cadence`).

A shared record says `shared with <owner>` (`day_live_payload()["tasks"][k]["shared_with"]`), never a borrowed green. This is "last run per component against its own schedule" (map B2.1). Its thresholds are day_live's, the digest's and the system map's own (`_stale_after_s`, views_day.py:122), never a second rule.

**Source:** `dashboard.views_day.day_live_payload(user)`. It is the payload `/api/day/live/` serves to /command/ every 60 s. The Oculus imports it and changes nothing in it.

**Viewer:** the tiles show each stage's job sentence (`STAGES`, day_of_sauron.py:31) and `states are staff's`, as the public Wall draws the ring from the schedule.

#### R4. Money safety (O0 worlds; O2a in full)

**Header:** `MONEY SAFETY`. Meta: `display only · every action opens its own page, with your PIN · read 12 s ago`.

**a) Three worlds, side by side, never summed** (O0 adds them in today's look; O2a puts them in the kit).
- REAL, then DEMO, then PAPER. The REAL column carries the 3 px REAL edge (UI plan rule 8). The world chips are the kit's: REAL is the solid red, DEMO is a gold outline, PAPER is a grey outline.
- Each world shows:
  - open positions;
  - open P&L with its source line: `eToro's own · 8 s`, or `≈ estimate · Yahoo quote, 3 min`. These are pnltruth's words when #89 has merged, and the band's `mark_source` words otherwise;
  - risk at the stops;
  - positions with no measured stop;
  - for REAL, closes pending.
- **The rows.** One read of the viewer's OPEN and CLOSE_PENDING rows, split by `dashboard.position_summary.world_of` (position_summary.py:253), the platform's one world rule.
- **The risk arithmetic** is `capital_desk.book_risk`'s formula: qty × |entry − `initial_stop_loss`| × `value_per_unit`. A test pins that the three worlds' risks add up, over the same rows, to `book_risk(live) + book_risk(paper)`. The display can never drift from the desk's own sum, and the desk is not touched.
- **The open P&L per world** comes from the band's cached `_panel_detail(user)`: `panel_open_pnl_live/_demo/_paper` and their coverage words (context_processors.py:883, `PANEL_TTL_SECONDS = 20`). The page and the headband therefore print the same digits.
- **No total row exists.** A test asserts it.

**b) eToro's own account** (REAL, or whichever world the sync read). It has five cells:
- equity;
- used (margin);
- available (free cash);
- eToro's P&L;
- the cells' age.

They come from `panel_etoro` (capital_summary's `etoro`, `bot_program/etoro_used.account_used`): the sync's stored cells, never a broker call. Beside them:
- `pledged 42 % of equity · ceiling 60 % (MAX ACCOUNT PLEDGED)`, as a meter. The ceiling is `asset_engine/base.pledged_ceiling()` (base.py:416).
- At a 100 % ceiling the words change: `ceiling 100 %: eToro's free cash decides alone · free cash €0.00`. That is `CASH_ALONE_CEILING`.
- `Brokers ›`, `Treasury ›` and `Withdrawals ›` (`brokers_page`, `treasury_page`, `withdrawals`) answer map B2.2's missing drill-downs.

**c) The protection checklist** (O2a; staff for the guards). A one-column key–value list, the most consequential first. Each row has a state dot with words, the figure the page already holds where it has one, and the guard's key on the right.

Some rows always show:
- the six money rows: stops, closes, margin and cash, daily loss, drift, bot tick;
- the brake;
- the kill switch.

The six other guards fold into one line while they are quiet (`6 more guards quiet: …`). A guard with a finding, or one that could not run, unfolds to its own row, in the table's order.

| Row | Quiet reads | A finding reads | Figure beside it (existing) |
|---|---|---|---|
| Stops at eToro (`no_stop`) | `every REAL row holds one` | `⨯ EURUSD (REAL) without a stop at eToro` | — |
| Closes (`stuck_close`) | `none pending` | `⚠ XAUUSD pending 42 min` | `CLOSE_PENDING` count (day_live ACT metric) |
| Margin and cash (`margin`) | `inside the ceiling` | `⨯ past the limit` | Pledged %, ceiling, free cash (b) |
| Daily loss (`daily_loss`) | `realized REAL losses (24 h) inside the configs' daily stop` | The finding's own label, which carries the numbers | — (the guard's own arithmetic, check_daily_loss morgul.py:1096; never a second implementation) |
| Sauron and eToro agree (`drift`) | `snapshot agrees` | `⨯ a position at eToro no row claims` | — |
| Bot tick (`heartbeat`) | `ticked 3 min ago · every 5 min` | `⨯ the tick has stopped` | `panel_bot.tick_ago`, `cadence_min` |
| Real stops held (`stop_overshoot`) | `quiet` | finding | — |
| Proofs and ceilings (`proofs`) | `quiet` | finding | — |
| Market-shut bookings (`market_shut`) | `quiet` | finding | — |
| Prices near the market (`price_sanity`) | `quiet` | finding | — |
| Duplicates (`duplicates`) | `quiet` | finding | — |
| Short read-back (`short_readback`) | `quiet` | finding | — |
| The brake | `armed: a critical finding on market-shut, proofs or margin stops the bots it names` / `off: findings are told, nothing stops` | — | `_brake_armed()` |
| Kill switch | `not fired in 7 days` | `fired 2 h ago (manual) · left open now: 1 (closing)` | `panel_bot.kill_at` / `kill_reason`; "left open now" is the current `CLOSE_PENDING` count plus REAL rows still OPEN after `kill_at` |

How the rows read the summary:
- A guard named in the summary's `failed` list reads `could not run at the last pass`.
- A summary older than 900 s greys every row and prints its age in the header.
- With `morgul_guards` off, every guard row reads `off: nothing watches the book`, which is exactly the words of morgul.py:2489.
- The guard names come from `morgul.GUARDS` (morgul.py:1659), so a thirteenth guard appears by itself.

**The kill switch row's link** (superusers): `Kill switch (PIN) ›` goes to `admin_dashboard#flattenForm`, the form that holds the PIN and the reason. `flatten_all_positions` itself is POST-only and superuser-only (views_admin_hq.py:23-34, 119), and the Oculus never posts.

**d) What the desk sizes with.** This is today's book, kept and labelled. By default it is collapsed to two lines:
- the live budget and its warning, with the demo rows it counts;
- the paper budget and the governor with its reason.

The full table opens on click. It stays in the DOM, so the book's tests keep reading it.
- It shows two venues, live and paper, exactly as `budget_for` (capital_desk.py:710) answers them:
  - `pool capital (assigned to enabled configs, not your equity)`;
  - `risk the desk counts`;
  - `budget for new risk this tick (2 % of pools × governor)`;
  - `positions it cannot measure`;
  - `governor 0.97 — 1.2 % under the high-water mark`. This is `reason`, so "100 means TWO things" is resolved in words, and the qualifier with "TWO" stays;
  - the currency and `not_summed`.
- A sentence says, in numbers, what C1–C3 will change: `The desk's live venue counts 2 eToro DEMO rows (286.00 at their stops) as live; the REAL column above does not. C1–C3 takes demo out of the desk.`
- The paper venue says `divides by paper and live pools: 28,500 = 25,000 paper + 3,500 live`.
- The two venues stay two (the test that pins `["live", "paper"]` is kept).

#### R5. Prices and requests (O2b; O3 upgrades it)

**Feeds** (all logins; `/api/live/health/` already serves the same rows to every page's pill). One row per declared feed, from `feeds.feed_states()`:
- its human label (`src_name` filter, S1a: "Yahoo", not "yfinance_public");
- its state (`live`, `yielding`, `off · no key`, `never delivered`, `stale`);
- its age;
- its one-line note.

**Held instruments** (per viewer). Each open row's symbol, world chip, price source and age (`● eToro · 12 s`, the kit's `.sv-fresh`), from the band's own rows (`panel_open_rows`: `mark_source`, `mark_age_s`). No new read.
- Before F6 the badge prints source and age, plus `stale` where `venue_mark` already says so. Sauron computes no feed grade before F6, and the badge does not pretend to.
- F6 adds the grades (O3).

**eToro request budget** (staff, after etbudget). Four meters, one per family, read from `etoro_budget.report()` (etoro_budget.py:874), which reads the cache only.
- **The meters.** Each shows the rolling minute's count against its rate: market 60, account 30, execution 20, lookups 18 (`RATE_*`, etoro_budget.py:131-134).
- **The ticks.** Each meter has 1 px ticks at the priority limits: P5 at 50 %, P4 at 60 %, P3 at 90 % and P2 at 95 % of the rate (`FLOOR_P2..P5`, etoro_budget.py:150-153).
- **Below the meters:**
  - refusals this window by priority and reason (`P5 candles · 2 · floor`);
  - the 429 pause per world (`none`, or `⚠ live world paused 41 s: P3–P5 wait; P0 closes and P1 orders never do`);
  - `P0/P1 past the rate: 0 this minute (counted, never held back)`.
- The key is never shown, and neither is its hash. The words are `1 eToro key`.
- Meter look (dataviz): the track is bg-3, the fill ink-2. The fill turns amber with ⚠ once the family holds the P3 line, and coral with ⨯ on a P0/P1 overrun. The values are in ink, never in the fill colour.

#### R6. What acts, what only watches (O2b)

A compact table: subject | state chip | what it means, in words. The state chips are the kit's (`ON` Eye, `OFF` hollow, `SHADOW` and `LIVE` as words). A real-money row carries the REAL chip by its name, as on /ops/ (UI plan §10).

| Row | Example | Source |
|---|---|---|
| The bot program | `LIVE · 2 real · 3 paper · 0 shadow · 0 halted · tick 3 min (every 5)`; the six bots on expand | `panel_bot` (`state`, `live`, `paper`, `shadow`, `halted`, `bots`) |
| Real-money switches | `3 of 12 on` with the three named; the rest on expand. Words: `turning one on takes the PIN at /ops/` | Component rows ∩ `LIVE_MONEY_SWITCHES` |
| The capital desk | `SHADOW: chooses and records; every candidate runs at full size` / `LIVE: the fleet obeys the desk` | `capital_desk_mode_live`, `pipeline_capital_desk` |
| The share allocator | `SHADOW · auto de-risk off: a plan applies only with the PIN` | `share_allocator_mode_live`, `share_allocator_auto_derisk` |
| Rules on the ladder | `2 live full · 5 live reduced · 19 paper · 26 research · 3 paused`, with the words `only live rules place real orders` | The ladder's aggregate (one query, shared with R9) |
| The Orcs | `ON · 7 on watch · minds ON in shadow: intents recorded, nothing placed · router ON · probes OFF · frontier OFF` | `orcs_on`, `minds_on`, `router_on`, `probes_on`, `frontier_on` answered from the shared rows; `Orc` alive count (one query) |
| The Council | `voices ON (shadow) · binding trade debate OFF (a real-money switch)` | `council_bots`, `trade_debate` |
| Aragorn, crisis mode, smart money | One line each, REAL chip, state | Component rows |

A viewer sees the bot program row only (his own bots). Every other row is a switch state and is staff's.

#### R7. AI minds and spend (O2b; staff)

- **Today, total:** a meter `$3.12 of $15.00`. The fill is violet (`--sv-ai`) and the track a dim violet. The fill turns amber with ⚠ at ≥ 80 % and coral with ⨯ when spent.
- **Core line:** `$2.40 of $11.28`, with the formula in words, `= $15.00 − Orcs spent − $3.00 floor` (`core_formula`).
- **Orcs line:** `$0.72 of $3.00`. Then `41 Orc calls today` and the wakes today by status: `38 answered · 9 quiet · 2 refused · 1 late`. Answered is `done`; the words follow `WAKE_STATUSES`.
- **Top spenders today:** up to five agents, with `other` folded. A table, not a chart.
- **Sources:**
  - `lines_summary()`: one aggregate;
  - `views_orcs._orc_line()`: one count;
  - `OrcWake` today by status: one aggregate;
  - `AgentTask` today by agent: one aggregate.

  `AgentTask.created_at` bounds all three to today.
- No model is called; the ledger is read.

#### R8. The last hour (O2a; staff)

A log, newest first, 28 px rows. Each row has:
- `HH:MM` in mono;
- a kind chip (trade, gate, ai, pipeline, bot, alert, system; `feed` from O3);
- a level glyph;
- a title;
- a detail line in ink-3;
- a link `›`.

**Sources:**
- `dashboard.activity_feed.activity_events(user, since=now − 1 h)` (activity_feed.py:640). It holds six bounded queries, pinned by `tests/test_activity_drawer.py`, and is the drawer's own reader.
- Morgul's findings, merged as kind `guard` at their `first` stamp, and the brake's stops (`braked`, `stopped`), all from `morgul:state` (morgul.py:2213-2227). This is one cache read, and staff only.

**Filter:** warnings, errors, trades and system lines show by default. `show routine` adds the pipeline and AI lines. At most 12 rows show, then `N more in the Activity drawer ›`. The page has no nested scroll.

**Switch flips:** PIN switches are on the audit chain (`core/switch_pin.py` → `bot_program.audit.record_switch`), so they appear. A non-PIN switch flip leaves no record today. The region says `switch flips: PIN switches only` in its meta rather than imply completeness. Recording every flip is a write, so it is not in this plan.

#### R9. The slow cycles, by stage (O1; today's eleven, kept whole)

Each stage section starts with a header that repeats its tile's state and links back to the tile. Under the header comes the stage's **task list** (R3's drill-in):
- the late and broken entries are shown;
- the on-time entries are folded under `19 on time ▸`.

The task lists refresh with the `now` part, in the same response as the tiles, through out-of-band swaps (`hx-swap-oob`). The tiles and the lists therefore never disagree.

Under the task list sit today's cycles, re-homed. SEE and TELL have no cycle of their own: their section is their task list.

| Stage | Cycles (today's keys) |
|---|---|
| THINK | The scan (`scan`), The signals (`signals`) |
| DECIDE | The promotion ladder (`ladder`), Personalities (`personas`), Allocation (`allocation`) |
| ACT | The book (`book`) is rendered by R4; the stage header points there |
| WATCH | The switches (`gates`) |
| LEARN | Evolution (`evolution`), The backtests (`backtests`) with "What the simulator promised, against what execution returned" moved here from the book, Confidence (`trust`), The horizon (`horizon`) |
| The platform | The forge (`forge`): R10 |

Every key, title, question, fact label, qualifier, caveat and drill-down stays. The tests that pin them are kept.

**Card anatomy (O1):**
- **Header.** The title, then the gate chips in words: the component's name, then a text node `pipeline_signals · on` (kept as one text node, because `test_staff_reads_both_as_before` reads it), then `ran 4 min ago · every 15 min` (`_component_state`, views_topology.py:315, and `_fmt_cadence`).
  - `absent` stays amber: `no row: the gate reads it OFF`.
  - A viewer sees `switches · staff only`, as today.
- **Fact rows**, 32 px, or 44 px with a qualifier line:
  - the value: mono 13, right-aligned in a 72 px column;
  - the label: Inter 13 ink-1;
  - the window chip: 11 px ink-3, one of `now`, `today`, `7 d`, `30 d`, `all time`;
  - the qualifier on the second line: Inter 12 ink-3, at most two lines.
- **Tones and thresholds:**
  - **Inert** values (cannot act) are ink-2, never ink-3 or ink-4.
  - **Caution** keeps its meaning, "read twice", and draws it with the qualifier, not with colour.
  - **Amber** comes only from a crossed threshold (§5.3). It carries ⚠ and its words: `−323.00 ⚠ past the ceiling: no new risk this tick`.
  - **A dash** is ink-3, never amber. That fixes the cascade bug.
- **Spark.** It stays bucketed on creation stamps (the meaning tests are kept). Its look:
  - 30 bars in ink-3, today's bar in ink-1 (emphasis, dataviz);
  - a zero day is a 1 px line-3 tick;
  - a solid hairline baseline;
  - the caption `30 d · peak 39/day · today 12`;
  - `a grey bar is a real zero` stays in the title.
- **Caveat.** It sits behind `Why these numbers read this way ▸` (`<details>`). It is still in the DOM, so `every cycle states its caveat` holds. Hover never gates it (UI plan rule 9).
- **Links** stay the same (`CYCLE_PAGES`), as kit ghost buttons.

**Layout:** cards align to their own height (`align-items: start`), so none stretches to the tallest in its row. Two columns at 1,100–1,599 px of container, three at 1,600–2,199, four from 2,200. The expectancy table is capped at 960 px and right-aligned in mono.

#### R10. The forge strip (O1; staff)

One compact strip, eight values with labels in one row (two at 1280):
- `commit a1b2c3d`;
- `built 9 h ago`;
- `migrations pending 0 · checked 4 min ago`;
- `guarded tasks with no switch 0 · checked at this build`;
- `pages that raise — · no probe since the cache was cleared (deploy, 9 h ago)`;
- `pages answering 404 —`;
- `tests on the wall 15,250 · constant, recounted at each merge`.

Its caveat sits behind `Why ▸`. A viewer gets the strip's title, `staff only — platform-wide, as on /health/`, and its links, exactly as today's withheld panel.

#### R11. Not measured, how to read, the stamp (O0 content, O1 look)

- **What could not be measured — N.** One row per dash:
  - the place, e.g. `forge · pages that raise`, or `book · live · budget left` (new in O0);
  - the reason in words: `table missing (migration not applied)`, `no probe since the cache was cleared`, `the builder raised <ExceptionType>` (type only, never the message), `venue unreadable`;
  - the fix hint (`manage.py probe_routes`, `manage.py migrate`).
- **How to read this page.** The three rules, kept word for word where tests read them: `a dash is not a zero`, `not measurable`. They come with the one-line promise and the `TWO`-style qualifiers. The status line carries a `?` link to it.
- **The stamp.** `Read 14:53:20 UTC. Counted at load; a stored reading prints its age. Live parts refresh every 30 s while this tab is visible.` This replaces "Nothing is cached", which O0 makes untrue for the forge.

### 3.3 The viewer's page (non-staff)

Same order, same regions:
- the status line with REAL MONEY, KILL SWITCH, BOTS, PRICES and READ, and the staff cells withheld in words;
- needs you, his own rows only;
- the cycle map, stages without states;
- money safety, his own book, with the guard rows withheld in words;
- prices (feeds and his held instruments);
- what acts (his bot program row);
- the slow cycles (as today);
- the forge strip and the switches card withheld, as today.

The tests that pin "no switch key followed by ` ·` in a viewer's page" and "no forge label" keep holding: the new regions print no switch key for a viewer.

### 3.4 Components

From S1a's kit, unchanged:
- card;
- notice (info, warn, danger);
- state chip;
- world chip;
- fresh badge (`.sv-fresh`);
- AI dot;
- KPI tile;
- key–value grid;
- table (compact 28 px rows, sticky head);
- count bubble;
- ghost and secondary buttons (for ⟳ and links only);
- the meter (UI plan "score meter");
- the empty state.

Oculus-only, in `static/css/sv-oculus.css` (≈ 250 lines, on tokens only):
- **The status cell row:** the S1b status cell at 44 px with a wrap rule.
- **The stage tile** with its arrow and segmented foot.
- **The fact row:** value | label | window | qualifier.
- **The 30-bar spark.**
- **The forge strip.**

There are no literals and no `rgba(0,232,104` anywhere in them. A sweep test, as in S2.8, pins that.

---

## 4. What updates live, and how

### 4.1 The mechanism: small server-rendered parts on readers that exist

- **Six parts.** Each region is one template partial, and the full page includes them all at first paint. `GET /partials/oculus/<part>/` serves one part alone. The parts are:
  - `now`: the status line, needs you, the cycle tiles and the seven stage task lists, in one response. The task lists sit in R9 and arrive by `hx-swap-oob`, so the verdict, the list and the stages always come from one reading;
  - `money`;
  - `prices`;
  - `costs`: what acts, and AI;
  - `events`;
  - `slow`: R9's cards, R10 and R11.
- **The parts view.** It is one view with a whitelist of part names. It is `@login_required @never_cache @require_GET`, with each part's staff rule enforced in it. It renders the partial without context processors (`render_to_string` with no request), so a refresh never recomputes the whole headband. The money part reads `_panel_detail(user)`, which is already cached 20 s per user and per book fingerprint, the band's own cache.
- **Why `/partials/`.** htmx sends `HX-Request`, and `/partials/` is matched by path. `core/idle_lock._wants_json` (idle_lock.py:89-104) therefore answers a locked session 423, never the lock page as HTML. Polls do not stamp activity (only `/api/session/ping/` does, idle_lock.py:74), so the page never holds a session open.
- **htmx 1.9.10** is already loaded by the shell (base.html:65). Each part carries `hx-get`, `hx-trigger="every 30s [document.visibilityState === 'visible']"` and `hx-swap="outerHTML"`.
- **A small `static/js/sv-oculus.js`** (≈ 120 lines, node-tested):
  - it stops a part on a 423 and resumes when the tab is visible and unlocked again (the same contract as `sv-day-live.js`);
  - it re-fetches `now`, `money` and `events` at once when the layout re-broadcasts an eye event of kind `fill_open`, `fill_close` or `notification` (`sv:eye-event`, base.html:7696). There is no new socket;
  - it ticks the READ ages each second without a request;
  - it stops everything while the tab is hidden.
- **Refresh keeps the frame** (UI plan §8). A part being fetched keeps its last render, at 70 % opacity after 300 ms. There is no skeleton and no layout jump. Identical numbers re-render identically, so nothing moves unless a value moved.
- **Nothing flashes.** Price-flash rules do not apply to the Oculus's numbers.

### 4.2 Each region's refresh

| Part | Refresh | Also on | Reads per refresh (all existing) | Who |
|---|---|---|---|---|
| now (status line, needs you, cycle tiles, the seven task lists) | 60 s (the /command/ cadence) | `sv:eye-event` fill, close or notification | `day_live_payload(user)` (≈ 18 queries: one component read, seven fenced metric groups); the Morgul summary and state (cache); `_panel_detail` (cached 20 s); `lines_summary` (1); `feed_states` (1); `etoro_budget.report()` (cache); the forge cache | All; staff cells and stage states for staff |
| money | 30 s | Eye fill or close | `_panel_detail` (cached), the world split of open rows (1), `budget_for` ×2 (as today), the Morgul summary (cache), `pledged_ceiling()` (1) | All (own book); guards for staff |
| prices | 60 s; O3: the push | — | `feed_states` (1); held rows from `_panel_detail` (0); `etoro_budget.report()` (cache only) | Feeds for all; budget for staff |
| costs (what acts, AI) | 60 s | — | Component rows (1), `panel_bot` (cached), ladder aggregate (1), `Orc` alive count (1); `lines_summary` (1), Orc calls (1), wakes by status (1), spend by agent (1) | Staff (own bot row for all) |
| events | 30 s, with `?since=` | Eye event | `activity_events` (≤ 6 bounded); `morgul:state` (cache) | Staff |
| slow (R9 cards, R10, R11) | Only on ⟳ or reload | — | `oculus(user)` after O0 (≈ 30) | As today |

**Requests while visible:** about seven a minute per open Oculus tab: `now` 1, `money` 2, `events` 2, `prices` 1, `costs` 1. There are none while the tab is hidden or locked. The shell's own polls do not change (`/api/live/health/` every 10 s, the rail and the ticker every 300 s).

### 4.3 What stays on refresh, and why

The slow cycles (R9), the forge (R10) and "not measured" (R11) change per night, per build or per deploy. They are read at load, stamped `read 3 min ago`, and re-read only on ⟳ (a GET of the `slow` part) or a reload. Polling them would be a cost without information.

### 4.4 After F7 (O3)

- **The prices region** stops polling while the push is healthy. Each held instrument's badge listens to F7's venue push (`sv-venue.js`, the per-user marks on the user's eye group). It degrades in the same frame as the grade (feed spec §5.6: degrade at once, hold 5 s, recover on the second confirmation; the kit only draws).
- **The money block's eToro P&L cells** take F7's per-user marks when `venue_pnl_delta_display` is ON, and eToro's own figure with its age otherwise. Calibration, parity and the newest-by-time rule are F7's.
- **"Live prices paused"** is the browser's socket to Sauron, F7's topbar chip. It greys every badge on the page. It is not the eToro feed being down, and the page says which.
- **If F7's display switches are OFF,** the Oculus returns to O2b's 30 s part, with no code path left half on.

---

## 5. Truth rules: kept, and extended

### 5.1 The three values, plus one

| Value | Means | Drawn as |
|---|---|---|
| A number | Measured now | Mono, ink-1 (ink-2 when inert) |
| `—` | Not measurable: the table is missing, the builder raised, or the source never ran | ink-3 dash with the title `not measurable — this is not a zero`, and its row in R11 |
| The gate | The switch that writes it, beside it | A state chip in words, with its last run and its rhythm |
| A stored reading (new rule) | A figure some writer stored: the probe, the Morgul summary, eToro's cells, the forge cache, the budget window | The figure plus its age, `· 3 min ago`. With no age it is not shown: the reading is treated as `—` |

### 5.2 Degraded, named

- Every dash on the page is listed in R11 with its place and reason: the book's facts, a whole book venue, and the expectancy table (map B3.8). `oculus()["degraded"]` gains `book.<venue>.<label>`, `book.<venue>` and `book.expectancy gap`.
- A dead cycle is still reported dead, never dropped (the test is kept).
- Failures log at WARNING, once per process per fact name, not at DEBUG (oculus.py:161, 316 today).
- Withheld is not unmeasured: a staff-only cycle never names itself in `degraded` (the test is kept).

### 5.3 Colour means state, and amber needs a reason

Each fact may declare `alert_when` (data in `oculus.py`, not template logic). The template paints amber or coral only when it holds, with ⚠ or ⨯ and the stated words. The tone values `plain`, `caution` and `inert` keep their names (the test that pins the tuple is kept); `alert` is a separate boolean.

| Fact | Alert when | Words |
|---|---|---|
| Desk budget left (live, paper) | < 0 | `past the ceiling: no new risk this tick` |
| Positions whose risk is not measured | > 0 | `open with no readable stop: on the book, on no budget` |
| Governor | < 1.00 | `the desk trades smaller: N % under the high-water mark` |
| On but never run | > 0 | ⚠ |
| Last pass in error | > 0 | ⨯ |
| Detections past due, unresolved (new split) | > 0 | `the resolver is late` |
| Signals closed with no grade (new split) | > 0 | `an opinion with no answer is not evidence` |
| Calls past due, ungraded (new split) | > 0 | `nobody is grading` |
| Views in error, views left "in progress" | > 0 | ⚠ (`no reaper`) |
| Age of the horizon view in use | > 45 d | `the allocator ignores it and uses 1.00` |
| Migrations pending, guarded tasks with no switch, pages raising, pages 404 | > 0 | ⚠ |

Neutral information ("computed before the 09-14 fix", "signals a run could not simulate", "graded no price") is ink-2 with ⓘ, never amber.

### 5.4 Windows and constants

- Every count names its window: `now`, `today` (00:00 UTC), `24 h`, `7 d`, `30 d`, `all time`.
- A code constant says `constant`: "personalities defined", "tests on the wall".
- Prose that cites a date says `as of <date>`. The scan's "about 179 instruments, 09:00 UTC" becomes the setups' count read in the same aggregate, plus the schedule's own time (`STAGE_OF` / the beat entry).

### 5.5 Worlds and money words

- REAL, DEMO and PAPER are never summed, anywhere on the page, and there is no total cell.
- DEMO is never in REAL.
- An estimate says so with `≈` and its source line.
- Money is grouped, with two decimals; P&L carries its sign and ▲ or ▼; the account currency is a symbol prefix and any other currency a code suffix (UI plan §4.4). `int()` never touches money (O0).
- Freshness never recolours a number; only STALE dims it.

### 5.6 Staff and viewer

- The staff rule stays `/health/`'s rule, as `oculus()` applies it today (`is_staff or is_superuser`, or no user, which is the shell).
- Every new staff-only cell, row and part is withheld in words, never dropped:
  - the guards;
  - the component states;
  - the budget;
  - AI spend;
  - the last hour;
  - the cycle map's states.

---

## 6. Money safety: the display-only contract

- **No form, no POST, no button that acts.** The page carries no `<form`, no `method="post"`, no `hx-post`, no `data-sv-close-trade`, no `svTakeTrade(` and no `svCloseTrade(`. The only buttons are disclosures (`<summary>`, `aria-expanded`) and ⟳, which is a GET. A test renders the page as staff with every region populated and greps the HTML.
- **Every action is a link to the page that holds it, behind its own PIN:**
  - the kill switch: `admin_dashboard#flattenForm`, superusers only;
  - CLOSE: `positions_list`;
  - switches: `ops_dashboard`;
  - keys: `brokers_page`;
  - `treasury_page`, `withdrawals`;
  - `asset_bots_dashboard`;
  - `ai_models_dashboard`.

  A test reverses every one.
- **No broker or model call.** Two tests prove it:
  - A source scan (pnltruth's pattern) proves `dashboard/oculus.py`, `dashboard/oculus_now.py` and `dashboard/views_oculus.py` import no broker adapter, no `client_for_symbol`, no model client and no `ai_agents` gateway.
  - At runtime, the page and every part render with `EtoroTrader`, `client_for_symbol`, `http.client.HTTPConnection.connect`, `urllib3`'s pool `urlopen` and the model gateway patched to raise.
- **The REAL chip** appears only on REAL figures and the armed state. It is the one solid red (UI plan §3.5), and S1a's test pins it.
- **Stale is never shown as fresh.** Every money figure prints its source and age, and the eToro cells grey past `BROKER_STALE_S`.
- **The desk is not touched.** The world split is a display helper over the same rows. The desk's own numbers are printed as the desk computes them, with words saying what C1–C3 will change. No money module is edited by any O stage.

---

## 7. Performance

### 7.1 Today (map A7, SQLite, indicative)

- `oculus()` makes 81 queries for staff and 74 for a viewer; a GET makes 157 and 150 (the shell adds 76, of which 44 are `LiveQuote`).
- At the six-month fixture:
  - `oculus()` takes 811 ms for staff and 379 ms for a viewer;
  - the page median is 705 ms for staff and 513 ms for a viewer;
  - the slowest cycles are trust 193, forge 137, book 72, allocation 65 and signals 57 ms.

### 7.2 Fixes (O0), each exact or fenced

1. **One component read per render.** `oculus()` reads `PlatformComponent.objects.values(key, name, is_enabled, last_run_at, last_status, last_message, run_count, error_count)` once. `_gate(*keys)` reads from that memo during a render and keeps its own query when called alone (the test calls it alone). The switches' four counts come from the same rows. 14 queries become 1.
2. **One aggregate per table, still one fence per fact.** Each table's facts read one memoised `aggregate(Count(filter=Q(...)))`, as personas already memoises its map. If the aggregate fails, each fact's own fence catches it, and each fact is named in `degraded`.
   - Signal 7 → 2 (the aggregate plus the spark).
   - AgentPrediction 5 → 1 + spark.
   - RuleControl 5 → 1 (`values("promotion_stage")` plus `paused`).
   - GeneratedSetupProposal 5 → 2.
   - HorizonView 5 → 2 (counts plus the newest `ok`).
   - BacktestRun 4 → 1; BotBacktestRun 2 → 1.
   - OpportunitySetup 2 → 1; OpportunityFlag 3 → 2.
   - SharePlan 3 → 1; DeskPlan 2 → 2 (the counts plus the spark).
3. **The forge, once per build.**
   - The guard scan is cached under `oculus:forge:guards:<sha>`. With a sha it never expires: the code cannot change without a new image. Without a sha (dev) it lasts 10 minutes.
   - The migration plan is cached 10 minutes under `oculus:forge:migrations:<sha>`, because `migrate` can run on the same image.
   - Both print `checked N ago`.
   - The probe prints its stored `at`. A missing entry reads `—` with `no probe since the cache was cleared`, never "0 pages raise".
   - With Redis (production) the cost is paid once per 10 minutes for the whole platform, not per worker and per GET.
4. **The backtests' Python loops.**
   - "Computed before the 09-14 fix" becomes `BotBacktestRun.objects.filter(status="complete").exclude(stats__has_key="unmeasured").count()`. This is exact: a list, null or non-dict `stats` lacks the key, as the loop counted it. The test covers all four shapes.
   - "Signals a run could not simulate" keeps its tolerant Python sum (bad values are skipped, not cast), cached 10 minutes under `oculus:slow:unsimulated` with its age printed.
5. **The not-due splits** use indexed columns:
   - **Flags:** a flag is not due while `scanned_at + horizon_days days > now`, as a database expression (`ExpressionWrapper(F("horizon_days") * timedelta(days=1))`, which Django 5.2 runs on Postgres and SQLite). This is the resolver's own rule (opportunity_scanner.py:2231).
   - **Signals:** `outcome=""` grouped by `is_active`, on the (`outcome`, `expired_at`) index.
   - **Predictions:** `expected_resolution_at > now` (indexed).
6. **Measure, then cache.** Nothing else is cached in O0. If the six-month run misses the target, the next to cache are the all-time aggregates of `AgentPrediction` (no `prediction_type` index) and `DeskPlan` (no `mode` index), 10 minutes each with their age printed. An index migration is a separate proposal, not part of a display PR.

### 7.3 Budgets (asserted in tests; measured with the scratch harness in every PR)

| Measure | Today | After O0 | After O2b (all regions) |
|---|---|---|---|
| `oculus()` queries, staff / viewer | 81 / 74 | ≤ 30 / ≤ 26 (`assertNumQueries`) | Unchanged (the slow cycles) |
| First paint, body queries, staff | 81 | ≤ 30 | ≤ 70 (≈ 30 slow + 18 cycle + ≤ 22 for the new regions) |
| Forge per staff GET | 1,297 files read + plan | 0 when warm; once per 10 min | Same |
| `oculus()` staff at the six-month fixture | 811 ms | ≤ 300 ms | Same |
| Page median, staff, six-month fixture | 705 ms | ≤ 400 ms | ≤ 500 ms |
| Part refresh, staff | — | — | `now` ≤ 24 queries, `money` ≤ 6, `events` ≤ 7, `prices` ≤ 2, `costs` ≤ 8 |
| Requests per minute while visible | 6 (shell) | Same | + ≈ 7; 0 while hidden or locked |

**The harness.** `scratchpad/oculus/tools/` (`fixture.py`, `scale.py`, `profile.py`, `capture.js`, `crops.js`) is copied to `claude/handoff` under `handoff/tools/oculus/`, as the UI plan did for its harness. It is never merged, and the fixture password is read from the environment.

---

## 8. The stages

Each stage gives its goal, what he will see, its files, its conflicts and order, its tests, its acceptance and its size. Screenshot pairs come from the harness, on the synthetic fixture.

### O0. Cost and truth, today's look (ships now; no approval needed)

**Goal.** Fix what is false or wasteful on the page today, without waiting for the kit.

**He will see:**
- The REAL column no longer counts eToro demo rows. In the fixture: 4 open, not 5, which now agrees with the Horde; risk 23.80, not 473.8.
- A DEMO column, and the desk's own numbers labelled as the desk's, with how many demo rows it still counts.
- The governor's reason in words.
- The paper capital explained (`25,000 paper + 3,500 live`).
- Every count with its window.
- Every dash in the footer, the book's included.
- The probe's age, and the forge's `checked N ago`.
- "Not due yet" separated from "late" in the scan, signals and confidence.
- Constants marked as constants.
- A page that loads in about half the time.

**Files:**
- `dashboard/oculus.py`:
  - the component memo;
  - per-table aggregates;
  - the forge cache;
  - `has_key`;
  - the not-due splits;
  - windows and `kind="constant"`;
  - money facts kept to two decimals (no `int()`);
  - `alert_when` data;
  - the book's world split (a display helper with the `book_risk` formula);
  - the desk block with `reason`, `currency`, `not_summed`, `n_other_currency`;
  - the book's dashes in `degraded`;
  - WARNING logs.
- `templates/dashboard/oculus.html`: content only, in today's styles. The book's three worlds and the desk block, windows, ages, the R11 rows, the stamp's words, and amber taken off the dash.
- `dashboard/views_oculus.py`: the docstring ("eleven cycles and the book").
- `tests/test_oculus.py`.
- `deploy/RUNBOOK.md`, "## The Oculus":
  - eleven cycles and the book;
  - what is cached and how it is dated;
  - the REAL and DEMO words.

**Conflicts.** No branch in flight touches these files. RUNBOOK.md is touched by many branches, so a rebase there is trivial (another section).

**Tests:**
- New:
  - query budgets: staff ≤ 30, viewer ≤ 26;
  - the forge runs the scan and the plan on a cold cache, not on a warm one, and again for a new sha;
  - the world split: one REAL row plus one eToro demo row plus one paper row. REAL risk excludes the demo row; the three worlds equal `book_risk(live) + book_risk(paper)` over the same rows; the desk sentence names the demo rows;
  - `has_key` equivalence on four `stats` shapes;
  - each not-due split: inside its horizon or due date is "not due", past it is "past due";
  - every all-time fact carries `all time`, every constant `constant`;
  - a book dash is listed in `degraded` and in R11;
  - money: 473.8 prints 473.80, and −0.6 prints −0.60, never 0;
  - a dash never carries the alert class;
  - `alert_when` raises the flag only past its threshold.
- Updated deliberately, with the reason:
  - `test_the_forge_reads_nothing_for_a_viewer_who_may_not_see_it`. Its staff half asserts the scan runs "on a cold cache" (the meaning, "never for a viewer", is kept).
  - The `L'` comment.
- Kept: the other 35 tests, as they are.

**Acceptance:**
- **Queries:** 81 → ≤ 30 (staff), 74 → ≤ 26 (viewer).
- **Time** (six-month fixture): `oculus()` staff 811 → ≤ 300 ms; page median 705 → ≤ 400 ms.
- **Forge, warm:** 0 file reads.
- **The fixture's book:** REAL 4 open, 23.80 at risk; the desk's live budget printed with its demo sentence.
- **Screenshot pair:** `oculus_staff_1440x900_full`.

**Size:** S–M.

### O1. The look (after S1a merges)

**Goal.** The same facts, readable and dense in the new kit, with the answer near the top.

**He will see:**
- A one-line promise in place of the 302 px intro.
- The book in three worlds, first on the page.
- The eleven cycles grouped under SEE … LEARN, in dense cards that no longer stretch.
- Gate chips in words, with their last run and rhythm.
- Sparks with a baseline and today marked.
- Caveats one click away.
- The forge as a strip, "not measured" with reasons, and the three rules at the foot.
- Inter for words, JetBrains Mono for numbers, nothing under 11 px.
- Amber only past a threshold, with ⚠ and words.
- No log lines behind the numbers (S1a).

**Files:**
- `templates/dashboard/oculus.html`, rewritten on the kit.
- New `templates/dashboard/_oculus/` partials: `book.html`, `stage.html`, `cycle_card.html`, `forge_strip.html`, `not_measured.html`.
- New `static/css/sv-oculus.css` (tokens only), loaded in `extra_css`. The page's 80-line `<style>` block leaves.
- `dashboard/oculus.py`: a `stage` per cycle, and gate words from the component's name, `_component_state` and `_fmt_cadence`, read from the memo.
- New `tests/test_oculus_look.py`.
- `deploy/RUNBOOK.md`.

**Conflicts.**
- After S1a, which provides the classes and tokens.
- Independent of S1b. Before S1b, the Gollum and Horde overlap remains (shell); O1 adds 96 px of end padding so the page's last rows can scroll clear of them.
- No branch touches the Oculus files.

**Tests:**
- String:
  - no `font-size` under 11 px in `sv-oculus.css` or the partials;
  - no `--text-muted` or `#3a6850`;
  - no inline `style=` except computed widths (spark heights, meter fills);
  - the alert class only beside ⚠ or ⨯ and words.
- Render:
  - every fact row prints its window;
  - every money fact is grouped, with two decimals and its currency;
  - a dash is never in an alert row;
  - every caveat is in the DOM inside `<details>`;
  - gate chips keep the text node `<key> · on`;
  - a viewer page holds no `<key> ·` and no forge label.
- Measured (Chromium, skipped where absent; the `_chrome()` pattern), at 1280, 1440, 1920 and 2560, rail closed and open:
  - first number y;
  - page height;
  - 0 text under 11 px;
  - every text role ≥ 4.5:1 on its computed background;
  - no card taller than its content + 24 px;
  - the expectancy table ≤ 960 px wide;
  - no horizontal scroll.
- Kept: every meaning test in `tests/test_oculus.py`.

**Acceptance (today's shell plus S1a, 1440 × 900):**
- first number y ≤ 280 (from 674);
- first cycle card y ≤ 1,100 (from 1,410);
- page height ≤ 3,400 px (from 5,030);
- numbers above the fold ≥ 20 (from 9–10);
- text nodes under 11 px: 0 (from 106);
- roles under 4.5:1: 0 (from 7 at 3.15:1).

After S1b: fixed-chrome overlaps 0. Screenshot pairs: staff and viewer at 1440, 1920 and 2560, plus the rail open at 1440.

**Size:** M.

### O2a. Is it safe, is it turning (after O1)

**Goal.** The status line, needs you, the cycle map, money safety in full, and the last hour, all live on existing readers.

**He will see.** R1, R2, R3, R4 (with the checklist and eToro's cells) and R8, refreshing every 30 or 60 s while the tab is visible. A fill or a close updates the status line, the money block and the last hour at once.

**Files:**
- New `dashboard/oculus_now.py`. It holds the new readers' assembly only: status, needs, cycle, money, events. It imports:
  - `views_day.day_live_payload`;
  - `activity_feed.activity_events`;
  - `context_processors._panel_detail`;
  - `morgul` (`SUMMARY_KEY`, `GUARDS`, `_brake_armed` semantics on the shared rows);
  - `capital_desk.budget_for`;
  - `asset_engine.base.pledged_ceiling`;
  - `position_summary.world_of`.

  It edits none of them.
- `dashboard/views_oculus.py`: the parts view (the view module still holds no query of its own, and that test is kept).
- `dashboard/urls.py`: one path, `partials/oculus/<str:part>/`.
- `templates/dashboard/_oculus/status.html`, `needs.html`, `cycle.html` (the `now` part renders the three together, plus `stage_tasks.html` out-of-band), `money.html`, `events.html`.
- New `static/js/sv-oculus.js`.
- `templates/dashboard/oculus.html`: the regions in order, and the script tag.
- New `tests/test_oculus_now.py` and `tests/test_oculus_parts.py`; a node test `tests/js/sv_oculus.test.js` (or the repo's node test pattern).
- `deploy/RUNBOOK.md`.

**Conflicts.**
- After O1.
- PR #89 is not required. With it, the money block prints eToro's own P&L words; without it, the marks' words. A follow-up commit is needed only if #89 lands after O2a, and it is template-only.
- `views_day.py`, `activity_feed.py`, `context_processors.py` and `morgul.py` are imported, never edited.

**Tests:**
- Sources pinned: each part calls the named reader (mock `wraps`).
- No broker or model call: the source scan, plus the runtime patches of §6.
- Display only: no form, no POST, no `hx-post`; every link reverses; the kill switch link only for superusers.
- Staff rules: a viewer's GET of a staff-only part answers 403, as `/api/day/live/` does. The viewer's own page never asks for one: its withheld cells carry no `hx-get`. The viewer's status line holds no GUARDS, BEAT or AI value.
- Needs you:
  - critical first, then REAL rows, then newest;
  - an empty list prints what was checked;
  - a stale Morgul summary is one ⚠ row;
  - guards off with REAL armed is one ⚠ row.
- Money:
  - the three worlds are never summed;
  - DEMO is not in REAL;
  - the checklist reads `could not run` for a guard in `failed`;
  - a summary older than 900 s greys the rows;
  - the account cells print their age and grey past one hour.
- The cycle map is the payload's: states, words, tasks and `shared_with`, with no second threshold.
- Query budgets per part (§7.3).
- The idle lock: a locked session's `HX-Request` gets 423.
- Node:
  - a 423 stops the part's polling;
  - a hidden tab schedules nothing;
  - `sv:eye-event` of kind `fill_close` triggers `now`, `money` and `events`, and other kinds do not;
  - the READ age ticks without a request.

**Acceptance:**
- At 1440 × 900 (S1b) the first screen holds R1, R2, R3, the worlds, the account cells and the first checklist rows: two with two needs, about five with none.
- On the fixture, needs you lists the fixture's problems:
  - BOT STALLED, which the old page hid while the bottom band said it;
  - the components in error;
  - the unmeasured stop.
- First paint ≤ 70 body queries for staff; page median ≤ 500 ms at the six-month fixture.
- About 7 requests a minute while visible, 0 hidden (network log).
- 0 broker or model calls (pinned).
- Screenshot pairs: 1440, 1920 and 2560, staff and viewer, rail open, and the needs-you list empty versus full.

**Size:** L.

### O2b. What acts, what it costs (after O2a; etbudget for the budget, #90 for the rail)

**Goal.** Engaged versus shadow, AI spend, prices with the request budget, and the signal rail's lifecycle.

**He will see.**
- R6 and R7.
- R5's feeds, held-instrument ages and eToro's request budget.
- In the THINK stage, The signals card gains:
  - `on the rail 13`;
  - `left today 6: 3 superseded · 2 aged · 1 stop crossed`;
  - `your passes 2 · taken 1`.

  These come from PR #90's `RailDeparture` (`departed_at` indexed, one aggregate) and the rail's own counts.

**Files:**
- `dashboard/oculus_now.py`: acts, ai, prices, rail.
- `templates/dashboard/_oculus/acts.html`, `ai.html`, `prices.html`.
- `templates/dashboard/_oculus/cycle_card.html`: the rail rows.
- `static/js/sv-oculus.js`: no change, or the part list only.
- `tests/test_oculus_now.py`, `tests/test_oculus_parts.py`.
- `deploy/RUNBOOK.md`.

**Conflicts and order.**
- The budget block waits for etbudget's merge. Until then R5 ships without it and says nothing about it, never a block of dashes pretending to be a feature (the forge's own rule).
- The rail rows wait for #90.
- The Orc switches are on main.

**Tests:**
- `report()` is read and never written; no key or hash appears in the HTML.
- The floors' ticks are at `limit()`'s values.
- A pause renders its words and its seconds left.
- P0/P1 overruns render as ⚠ and never as a refusal.
- Spend:
  - the formula words are `lines_summary()`'s;
  - a spent line is ⚠ in R2;
  - the wakes' words cover every `WAKE_STATUSES` value.
- Acts:
  - every money switch row carries the REAL chip;
  - a viewer gets the bot program row only;
  - `SHADOW` and `LIVE` follow the mode flags.
- Rail: departures by reason, today; the viewer's own passes only.
- Query budgets per part.

**Acceptance:**
- The fixture's R6 says what the switches say on /ops/, row for row (a test compares the two).
- R7's total equals /ai-models/' total for the same ledger.
- R5's feeds equal `/api/live/health/`'s rows.
- Screenshot pairs as in O2a.

**Size:** M.

### O3. Feed-grade live (F6 for the server side, then F7)

**Goal.** Prices on the Oculus at the eToro feed's grade, live, at no extra request.

**He will see:**
- **From F6:**
  - each held instrument's grade, `LIVE`, `RECENT`, `STALE`, `CLOSED` or `NONE`, with confirm and print ages, its channel (stream or REST) and the stream connected or down;
  - the last feed transitions in the last hour (kind `feed`, at most the feed's own 6 per instrument per minute, the rest as `+N`);
  - Morgul's G10v in the checklist (by itself, from `GUARDS`).
- **From F7:**
  - the badges and eToro P&L cells moving with the push, degrading in the same frame;
  - latency p50 and p99 in the PRICES cell;
  - the "live prices paused" chip greying the badges.

**Files:**
- `dashboard/oculus_now.py`: F6's feed status reader (the function behind `manage.py feed_status`) and `FeedTransition` for held instruments.
- `templates/dashboard/_oculus/prices.html`.
- `static/js/sv-oculus.js`: subscribe to F7's venue events through `sv-venue.js`'s public hook; stop the prices poll while the push is healthy.
- Tests.

**Conflicts.**
- After F6, then F7. F7 owns `sv-venue.js` and the shell's `onmessage`; the Oculus only listens.
- S4 is not needed.

**Tests:**
- F7's payload contract fixtures replayed into `sv-oculus.js`.
- A badge degrades in the same frame as the grade.
- No prices poll while the push is healthy; the 30 s part returns when F7's display switches are OFF.
- Transitions are capped as the feed caps them.
- An unknown grade renders `—` with its title, never LIVE.

**Acceptance:**
- The F7 fault test:
  - `./deploy/dc stop stream-etoro`: the Oculus's badges turn degraded at once with growing ages, the timeline shows the transitions, and no cell jumps or steps back;
  - bringing the stream back recovers after the trust rule (§5.6 of the feed spec).
- Zero Oculus requests for prices while the push is up (network log).

**Size:** S–M.

---

## 9. Sequencing with the work in flight

| Order | Stage | Can start | Must wait for | Yields to |
|---|---|---|---|---|
| 1 | O0 | Now | Nothing | — |
| 2 | O1 | After S1a merges | S1a | S1b (shell lines only; O1 edits none) |
| 3 | O2a | After O1 | — (#89 optional) | F7 (prices later), C1–C3 (the desk sentence updates when demo leaves the desk) |
| 4 | O2b | After O2a | etbudget (budget), #90 (rail) | — |
| 5 | O3 | After F6, then F7 | F6, F7 | — |

C1–C3, when it lands, removes the desk's demo rows. The O0 sentence then reads `the desk counts REAL rows only` by itself, because it prints the measured count of demo rows the desk includes, and that count becomes 0. The same O0 test keeps pinning it.

---

## 10. Decisions, risks, and what is not in this plan

**Decisions for him** (in the French note):
1. The order of the blocks (§3.1).
2. The slow cycles below the "now" blocks, explanations one click away.

**Decisions taken here, and why:**

| Decision | Why |
|---|---|
| The seven stages of `core/day_of_sauron.py` are the cycle map | One vocabulary across /command/, the Wall and the Oculus; the thresholds already exist (`views_day`), so no second rule |
| Every new block reuses an existing reader | "No new heavy read"; one truth per fact |
| Parts are server-rendered fragments under `/partials/`, on htmx, not JSON painted by JS | One template per region; the idle lock answers 423; no duplicated formatting in JS |
| A per-part `render_to_string` with no request | A refresh must not recompute the whole headband; the band's own 20 s cache is reused |
| The REAL column follows `world_of`; the desk block stays the desk's | Truth now, with no money change; C1–C3 changes the desk |
| The forge is cached per build | It cannot change without a new image; migrations get 10 minutes because `migrate` can run on the same image |
| Amber is data (`alert_when`), not a tone | Colour must mean "past a threshold"; the tones keep their test |
| Every action is a link, never a button | Display only; the PIN lives on the action's own page |

**Risks:**
- **`day_live_payload` changes shape on /command/'s side.** The Oculus reads its keys; a test on the Oculus side pins the keys it reads, so a change fails here and not silently.
- **`_panel_detail` is private.** It is imported as the band's cache. If pnltruth or railfilters rename it, the money part's test fails at once. A public alias is a one-line follow-up, if wanted.
- **The parts multiply polls.** They stop when hidden or locked, and the budgets are pinned. Seven requests a minute per open tab is about what the shell already spends.
- **Morgul's summary carries labels, not numbers.** The checklist prints the guard's own words and never re-derives a figure (daily loss), so it can never contradict the guard.
- **Wider faces in O1.** Inter and JetBrains Mono are wider; the measured tests catch truncation at 1280.
- **Non-PIN switch flips have no record.** The last hour says "PIN switches only" rather than imply completeness.

**Not in this plan:**
- No action from the Oculus: no kill switch, close or toggle on the page.
- No change to what the engine, the bots, the Orcs, the desk or the gates read.
- No new writer (no flip recording, no stored preflight verdict) and no new index. Each is a separate proposal if wanted.
- No change to /command/, /health/, the Activity drawer or the Horde. The Oculus reads them.
- No phone redesign. The page must not break at 390 (one column, the status cells 2 × N, the stages as a list); S3 owns the rest.

---

## Appendix A. Where each of today's facts goes

| Today's cycle | New home | Changes to its facts |
|---|---|---|
| The book (`book`) | R4 (worlds, account, checklist, desk block); the expectancy table goes to R9 LEARN | Three worlds by `world_of`; the desk block keeps `venues` live and paper with `reason`, currency, not-summed and the demo sentence; money to two decimals; dashes named; expectancy colour only at n ≥ 10 on both sides (`n < 10 · not judged`) |
| The forge (`forge`) | R10 | Cached per build, ages printed, probe dated, constant marked |
| The switches (`gates`) | R9 WATCH, plus R2 and R3 | Same four counts; `last pass in error` ⨯ when > 0 |
| The scan (`scan`) | R9 THINK | `still unresolved` → `not due yet` (inert) and `past due, unresolved` (alert); windows; the "179 instruments" prose from the setups' count |
| The ladder (`ladder`) | R9 DECIDE, plus R6 | Same; `transitions` stays `30 d` |
| The signals (`signals`) | R9 THINK | `never graded` → `still live` (inert) and `closed with no grade` (alert); rail rows from #90 (O2b) |
| Evolution (`evolution`) | R9 LEARN | Windows (`all time`) |
| Personalities (`personas`) | R9 DECIDE | `defined` marked constant |
| Allocation (`allocation`) | R9 DECIDE, plus R6 | Windows; `desk passes` all time and 30 d |
| The horizon (`horizon`) | R9 LEARN | `age of the view in use` alert past 45 d; dated prose `as of 2026-09-12` |
| The backtests (`backtests`) | R9 LEARN | `has_key`; the unsimulated sum cached 10 min with age |
| Confidence (`trust`) | R9 LEARN | `awaiting a grade` → `not due` (inert) and `past due` (alert) |

## Appendix B. New cells and their sources

| Cell | Reader (file:line) | Cost | Cache |
|---|---|---|---|
| Stage states, tasks, beat, stage metrics | `dashboard/views_day.py:349 day_live_payload` | ≈ 18 queries | none (60 s part) |
| Component states and rhythm | `dashboard/views_topology.py:315 _component_state`, `_fmt_cadence`, `_expected_cadence:234` | 0 (memo rows) | — |
| Bot program state, kill switch | `core/context_processors.py:549 _bot_truth` via `_panel_detail:883` | 0 (cached) | 20 s (band) |
| Worlds' P&L and coverage, eToro cells | `_panel_detail` keys `panel_open_pnl_live/_demo/_paper`, `panel_etoro` (capital_summary → `bot_program/etoro_used.py:322 account_used`) | 0 (cached) | 20 s (band) |
| Worlds' counts and risk | `dashboard/position_summary.py:253 world_of`; `capital_desk.book_risk` formula (capital_desk.py:577) | 1 | — |
| Desk block | `bot_program/capital_desk.py:710 budget_for` | as today | — |
| Pledge ceiling | `bot_program/asset_engine/base.py:416 pledged_ceiling` | 1 | — |
| Guards, brake | `cache.get(morgul.SUMMARY_KEY)` (morgul.py:151); `GUARDS` (1659); `_brake_armed` (1772) semantics on memo rows | 0 | Morgul's own (5 min beat) |
| Findings' first-seen, brake stops (R2 "since", R8 `guard` lines) | `cache.get(morgul.STATE_KEY)` entries `first`, `braked`, `stopped` (morgul.py:2213-2227) | 0 | Morgul's own |
| Feeds | `market_data/feeds.py:352 feed_states` | 1 | — |
| Request budget, pause | `bot_program/engine/etoro_budget.py:874 report` (claude/etbudget) | 0 DB | Its own cache |
| AI spend | `ai_agents/spend.py:298 lines_summary`; `dashboard/views_orcs.py _orc_line`; `OrcWake`, `AgentTask` today | 4 | — |
| Orc switches | `bot_program/orcs/switches.py` (`orcs_on:40`, `minds_on:95`, `router_on:109`, `probes_on:120`, `frontier_on:130`), answered from memo rows | 0 (+1 alive count) | — |
| Last hour | `dashboard/activity_feed.py:640 activity_events` | ≤ 6 | — |
| Rail lifecycle | `dashboard.RailDeparture` (#90), `departed_at` indexed | 1 | — |
| Feed grades, transitions (O3) | F6 `feed_status` reader, `FeedTransition` | ≤ 2 | — |
