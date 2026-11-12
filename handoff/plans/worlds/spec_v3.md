# SPEC: the worlds apart (third edition)

Written on 2026-11-07 against main `15dd487`, read only in `.claude/worktrees/mainread`. Main moved from `227e03b` by one merge, PR #97 (Oculus O0), which touched only the Oculus files, `core/wall_facts.py` and `deploy/RUNBOOK.md`. Every `path:line` of the rebase report therefore holds, and every `path:line` below is at `15dd487` unless a branch and commit are named.

Branches read: OC0 `claude/opscenter0` at `0f93142`; S1a `claude/uis1a` at `c6f1822`; F1 `claude/feedf1` at `9f054fd`; O2c `claude/orcs2c` (no commits yet).

> "we need to separate much more the paper from the live, have different tabs in the horde, have selection possibilities between brokers and accounts available to open trades please, also, have curves and pnl and stats in separate tabs or else, but make it clean and usable and easy to view."

This edition replaces the second edition (`worlds/spec.md`, written at `dbfe0a9`) for scope, order, decisions, tests, acceptance and money direction. Where it says "as the second edition §n", that section stands word for word except its line numbers, which Appendix A maps to `15dd487`. Appendix B lists what the second edition said that is withdrawn or corrected.

The repository is public. No account figure, id, host or key appears here; the test figures are synthetic.

---

## 0. Decisions

### 0.1 His decisions since 2026-10-31

1. **D1 and D4: yes.** The limits that protect real money count real money only. Demo leaves the real-money risk (D1) and the account size the limits are measured against (D4). This is **Stage L**: shadow first, behind a new PIN switch, `real_only_limits_live`, that is OFF on arrival.
2. **D2: yes.** eToro REAL and eToro DEMO are selectable side by side on the ticket, and a ticket that targets REAL asks for **a second PIN confirmation**. This is **Stage C4**: per-world reads first, then two lanes behind a second PIN switch, `etoro_two_worlds_live`, OFF on arrival.

### 0.2 Taken here (the French plan asks him to confirm each)

1. **D1a. Demo is judged as a world of its own.** Under the real-only rule a demo order meets the same percentages as real money, measured on demo's own rows against the demo account's equity. Demo is a rehearsal of real money. If it ran unbounded, it would produce trades and evidence that real money could never produce. The other choice (demo stays in the "live" venue, which then drops its rows) would leave demo stopped only by real losses. Either choice is neutral for real money.
2. **The second PIN is a second step, not a second box.** On a REAL ticket the PIN is typed in the dialog as today. The server checks it, judges the order and answers with a final REAL MONEY panel that shows what will be sent. The PIN is typed again there, and only then is the order sent (8.3). Typing the same PIN twice in one form would add nothing but friction.
3. **The REAL lane is the class's existing broker lane.** It keeps its knobs, pool and history. C4b pins it to `etoro:live` through the arming ceremony. DEMO is a new lane, `manual-demo`, pinned to `etoro:demo`. PAPER is C3's `manual-paper`. One lane per account: the pool, the dedupe, the double-click claim and the PIN demand stay per account, because they are per config today.
4. **The Demo box on /brokers/ stays the bots' world** until D3 is decided. Its guards are unchanged. With C4 on, ticking Demo is also refused while the REAL lane holds a real position.
5. **L counts in the per-config checks and the capital desk.** A live config's slots and its own day, `capital_desk.book_risk` and the desk's live budget all count real money only when the switch is ON. Demo rows left open after an untick otherwise keep holding real room that nothing can free.
6. **One world rule before more copies (W0).** Five places already define a row's or an account's world. C1, C3 and L would have added three more.
7. **C4 can never be ON while L is OFF.** With both worlds trading and the gate still counting demo as live, a REAL ticket placed while the bots are on demo would be measured against the demo equity (`account_equity` checks no world). The C4 code refuses this at call time (8.2, 8.3), not only the switch order.

### 0.3 Still open

- **D3.** What do the bots trade once both worlds exist? The default stays the Demo box. The other choice is a world per bot config.
- **D5** (second edition, unchanged). Should the hand ticket refuse carriers with no proof table (Saxo, OANDA, Alpaca, Binance live) when they are a class's route?
- **D6 (new).** The desk's evidence lanes (`capital_desk.py:381-392`), the grading (`bot_grading.py:70-83`) and the share plans' grading (`share_allocator.py:1601`) count every non-paper close as live evidence, demo included. That shapes real sizes. It is outside D1 as he approved it, so it is a separate decision with its own shadow. The recommended answer is yes, after L.

---

## 1. What changed since the second edition

### 1.1 Merged since `dbfe0a9`

| PR | What it changes for this plan |
|---|---|
| #89 eToro's own P&L | Display only (`services.py:1022-1026`: `venue_pnl` does not feed the book value). Open eToro rows carry eToro's figure, the cockpit OPEN P&L and PORTFOLIO titles changed (`base.html:1058-1073, 890`), the seats' `_ccy` is USD for eToro's own (`horde.py:1419`). A new AT ETORO cell, `head.etoro` with a `world` key (`horde.py:2018-2022, 2058`; `sv-horde.js:906-911`; `the_horde.html:115`) |
| #90 the signal rail | Not on these paths. The rail's TAKE uses `svTakeTrade` (C3 keeps it) |
| #93 manual smallest size | The ticket's venue minimum. C4c's first REAL ticket is taken at that floor |
| #94 ticket lost answer | `tradeFlow` grew from 107 to 436 lines (`base.html:3514-3949`). It added `ticket_ref`, `dup_seen`, `shown_qty` and `shown_raised` (`views.py:5234-5357`) and the ticket record (`dashboard/ticket_outcome`) |
| #95 eToro request budget | `bot_program/engine/etoro_budget.py`: one budget per user key for both worlds, P0/P1 never refused. The sync runs every 60 s, so the 2-hour fallback means 120 missed syncs (`risk_gate.py:338-341`) |
| #96 tests | None |
| #97 Oculus O0 | The Oculus's REAL column counts real money only (`world_of`). Its desk sentence credits "C1–C3 (real-only limits, planned)" with taking demo out of the desk (`dashboard/oculus.py:1002, 1059`). That is L's work, and L2 rewrites the sentence |
| threefix (`6562ddb`) | eToro's own used and free (`bot_program/etoro_used.py`), the re-read after orders and closes (`tasks.refresh_etoro_cells`), lane knobs |

### 1.2 In flight

| Work | State | Overlap with this plan |
|---|---|---|
| OC0 `claude/opscenter0` `0f93142` | Being built, approved | DEMO rows read DEMO on /command/ and /eye/. Worlds are never summed on /command/. The armed pill counts REAL-account bots. It brings `config_worlds` and `_DEMO_ACCOUNTS` (`core/context_processors.py:677-745`), `views_command._world_stamps` and `_realized_24h_by_world` (496-534), and `views_eye._pnl_24h` (394-490; 420-421 has no paper guard). W0 folds these into one rule |
| S1a `claude/uis1a` `c6f1822` | Review fixes done; PR next | The kit: `.sv-world` with `--sv-real/--sv-demo/--sv-paper` (`static/css/sv-kit.css:81-96`), `.sv-tabs/.sv-tab` and `.sv-seg/.sv-seg-btn` (1124-1139, CSS only, no keyboard behaviour), shown at `design_kit.html:193`. C1's world switch is built on these |
| F1 `claude/feedf1` `9f054fd` | Building | The harm counters and their fence (`bot_program/feed_fence.py`, `feed_harm_models.py`, migration `bot_program/0051`). This is the pattern L2's shadow record copies. F1 edits `manual_close.py` (54-57, 366-372, 572-576), `engine/kill_switch.py` and `portfolio/services.py` (the venue-source rule) |
| O2c `claude/orcs2c` | No commits | None |
| Planned, approved, not started | — | S1b (shell; the 32 px status bar takes the cockpit cells), S2.1 (ticket and instrument page), OC1 (one page, eToro first; it retires `_command_portfolio.html` and the OC tabs), O1/O2a, the Bettor (26 commits), Orders at a price (P1–P5), usedfix U3 (`etoro_used`, `treasury.html`) |

### 1.3 Done elsewhere, taken out of these stages

| Second edition item | Done by | What is left here |
|---|---|---|
| The Eye's open table prints DEMO rows as REAL MONEY (§3.5) | OC0: `metadata` and `world` on each row (`views_eye.py:207-208` at `0f93142`), a World column | Nothing |
| The OC LIVE tab's row markers | OC0 | Nothing. The tab's name is moot: OC1 (one page, approved) removes the tabs |
| Per-world 24 h P&L on the OC LIVE tab | OC0 (`views_eye._pnl_24h`) | W0 aligns its "not measured" rule with the gate's |
| The armed pill and the BOTS tab by the account's world (second edition C4b) | OC0 (`config_worlds`) | W0 moves the helper into `bot_program`, because L needs it at gate time |
| "All worlds pooled" labels on the OC PORTFOLIO and HISTORY tabs (§4.7, in part) | OC0: pooled R and win rate are labelled "all worlds", and money is split by world | C2 adds the link to Results by World |
| The Oculus split by world | O0 | L2 corrects the desk sentence |
| eToro's own P&L on open eToro rows | #89 | C1 shows the AT ETORO cell on its own world's tab |

### 1.4 Facts that moved or changed

These are listed in full in Appendix B. The ones that change the design:

- **The eToro cells now carry a world.** `last_margin_world` (`bot_program/models.py:440`) is written in the same save as the equity (`tasks.py:1314`). A Demo-box flip drops the equity cells (`views_brokers.py:497-498, 998-1004`). `etoro_stored_equity` refuses another world's equity (`capital_truth.py:75-122`, check at 107-112). But `account_equity` (`capital_truth.py:450-475`) checks no world, and `venue_book_value` reads it (`risk_gate.py:362-371`). With Demo ticked, the real-money limits are measured against the demo equity from the first sync after the flip. L fixes this under its switch, and C4 depends on that fix.
- **Morgul already counts real money only.** Its daily-loss guard G7 reads "paper and demo excluded" (`morgul.py:1174`) and has its own world reader (423-429). Today the gate and Morgul disagree whenever demo closes; L makes them agree.
- **`_preview` has five call sites, not three:** `manual_trade.py:2525, 2535, 589, 3093-3094, 3196-3197`, plus `ai_agents/agents/council.py:1362`.
- **The manual lane's name has ten readers, not eight.** The new ones are `bot_program/asset_engine/base.py:531-533` and `preflight_live.py:1089-1090, 1100`.
- **The duplicate rule is a warning on the hand ticket** (`manual_trade.py:1498-1510`). The ticket refuses only a holder it never showed (1512-1540; checked at 2836-2843, 3020-3032, 3466-3473).
- **ENGAGED is already split by row world**, real money only (`services.py:437`), so demo lands in PAPER ENGAGED. Only FREE is by config mode.
- **D1's list in the second edition missed** `open_risk_state` (`risk_gate.py:849-936`, MAX OPEN RISK) and `capital_desk.book_risk` (`capital_desk.py:611-618`).
- **Two world tools already exist:** `AssetBot.VENUE_WORLDS` (`base.py:3904-3905`, used by `venue_stamps` 7623-7668) and `DemoOnlyEtoroTrader` (`etoro_client.py:4231-4266`).
- **Who reads the gate's live venue.** Besides the bots and the ticket, these do: the Horde (`horde.py:830-833`), the Council band (`council_band.py:1208, 1228, 1243`), the Council agent (`council.py:1492, 1509, 1535`), `council_mood.py:396`, the Orcs (`orcs/sources.py:656`), `views_ops.py:378` and the /setup/ cards (`views.py:4076`, unnamed). Under L they read the real-only figure without edits, because the rule sits inside the gate.

---

## 2. The stages, in order

Sizes: **S** is under 300 changed lines with tests, **M** is 300 to 1,000, **L** is over 1,000.

| # | Stage | What he gets | Money direction | Size | Can start | Must wait for |
|---|---|---|---|---|---|---|
| 1 | **W0 · One world rule** | Nothing visible, except "not measured" for exit-unpriced closes on /command/ and /eye/ | None | S | When OC0 merges | OC0 |
| 2 | **C1 · The worlds apart and the Horde's tabs** | The Horde gets REAL, DEMO, PAPER (and HAND) tabs, each with its own figures; an ENTRY GATE line while the gate counts demo; the cockpit per world; the close dialog says DEMO | Display only | L | After W0 | W0; S1a's kit (or the second edition's CSS block if S1a slips) |
| 3 | **L1 · One book value per world** | Nothing visible | Neutral | M | After W0, parallel to C1 | W0 |
| 4 | **L2 · Real-only limits, in shadow** | A new switch row on /ops/, OFF; a report command; the gate line and the Oculus name the switch | Neutral while OFF | L | After L1 | L1 |
| 5 | **C2 · Results by World** | /bot-charts/ becomes Results by World: the world switch, then Curves, P&L and Stats | Display only | M | After C1 | C1 |
| 6 | **C3 · The account on the ticket** | An account choice on TAKE TRADE and the deal ticket (PAPER, or the broker in the Demo box's world); never escalates | Tightens, with paper-side cases named | L | After C1 | C1, W0; rebases on L2 in `manual_trade.py` |
| 7 | **L3 · He turns it on** | A demo loss no longer stops real bots; the gate line goes | Looser and tighter for real money, listed in 7.4 | — | After the shadow's acceptance (7.5) | 14 days of shadow |
| 8 | **C4a · Both eToro worlds read** | eToro REAL and DEMO cells both read; demo rows left after an untick become closable | Neutral for real money | L | After W0, parallel to C3 | W0; U3 if it lands first |
| 9 | **C4b · Two eToro lanes, in shadow** | The HQ arm card shows a REAL lane and a DEMO lane; /brokers/ says the Demo box is the bots' world | Neutral while OFF | L | After C3, C4a and L2 | C3, C4a, L2 |
| 10 | **C4c · Both on the ticket, REAL asks the PIN twice** | eToro · REAL and eToro · DEMO both selectable; a final REAL MONEY panel | Looser and tighter, listed in 8.4 | M | After C4b | C4b; its switch needs L3 ON |
| 11 | **C5 · The remaining world filters** | /positions/, /portfolio/, fills, the Treasury and the scorecard CLI per world | Display only | M | After C1 | C1; U3 for `treasury.html` |

**Why this order.**
- W0 comes first, so C1, C3 and L each read one rule.
- L1 and L2 start early because the shadow needs at least 14 days. It accumulates while C2 and C3 are built.
- C3 and L2 both edit `manual_trade.py`. Whichever lands second rebases.
- C4 needs C3's account choice and L's world-checked denominator, and its switch needs L3.
- C5 is display and can go any time after C1.

**Every stage** writes its tests first and sees them fail. Then it builds, runs its own tests and the full suite, takes the screenshots it names in the real shell at 1280 and 390, and states its money direction in its commit message in the words of §10.

---

## 3. W0 · One world rule

**Goal.** One definition for each world question before C1, C3 and L each write their own. This is the rebase report's "Where one world rule must be shared instead of copied".

**He will see.** Nothing new, with one exception. On /command/ and /eye/, a close whose exit price was unavailable now reads "not measured" in its world's 24 h figure, instead of counting as 0.00.

**What it adds or moves:**

| Question | The one rule | Replaces |
|---|---|---|
| A trade row's world | `position_summary.world_of` (253-270) for Python. `bot_grading._world_filter` (90-116) for filtering a queryset. **New** `position_summary.world_case()`, a SQL `Case` expression that annotates the same word for grouped sums. **New** `position_summary.realized_by_world(user, *, hours=24, now=None, bots_only=False)` built on it, with **the gate's "not measured" rule**: `pnl` NULL **or** `metadata.exit_price_unavailable` (`risk_gate.py:675-678`) | OC0's `views_command._world_stamps` and `_realized_24h_by_world` (496-534 at `0f93142`) and `views_eye._pnl_24h` (420-421, which has no paper guard); the second edition's planned `world_q`. Morgul's `_world` (`morgul.py:423-429`) is **not** touched here, because Morgul brakes bots; L2 aligns it under the switch |
| An account row's world | **New** `capital_truth.account_world(acct) -> "live" \| "demo" \| ""`, built on `broker_env` (426-440) plus IBKR's port (an unknown port is live), OANDA practice and Alpaca paper | OC0's `_DEMO_ACCOUNTS` (`context_processors.py:677-683` at `0f93142`); `etoro_used.py:350`; C3's planned table in `accounts.py` |
| A config's world | **New** `bot_program/worlds.py`: `config_worlds(user, cfgs)` and `config_world(user, cfg)`, **moved verbatim** from OC0's `core/context_processors.config_worlds` (691-745 at `0f93142`). An unreadable route is "live" | OC0's copy. The context processor imports it |
| A client's world | **New** `worlds.client_world(client) -> "live" \| "demo" \| "paper" \| None`. `PaperTrader` gives paper. Otherwise `AssetBot.VENUE_WORLDS` on `client.env` gives "live", or "demo" for every other mapped spelling. `IBKRTrader.paper` gives demo or live. Anything else is None, **never a default to live** | The second edition's planned table in `accounts.py`. `venue_health.world_of` (98-101) keeps its own job, the health keys |
| Risk at the stops | Two named numbers, as words in `position_summary`: "at the stops now" (the gate's `_row_risk`, `risk_gate.py:829-846`, on the current stop; the Horde and the gate) and "at the opening stops" (the desk's arithmetic, `capital_desk.py:624-634`, copied by O0's `_risk_at_stop`, `oculus.py:878-891`). Each page that prints one says which | Two unnamed numbers |

**Files:** `dashboard/position_summary.py`, `bot_program/capital_truth.py`, `bot_program/worlds.py` (new), `core/context_processors.py`, `dashboard/views_command.py`, `dashboard/views_eye.py`, `bot_program/etoro_used.py` (350), `dashboard/oculus.py` (the risk words only), `tests/test_one_world_rule.py` (new).

**Conflicts and order.**
- W0 lands after OC0 merges and replaces OC0's private copies. OC0's tests stay as they are, except the one rule named above.
- It must come before C1, C3, L and C4.
- No other branch in flight edits these functions.

**Tests written first** (`tests/test_one_world_rule.py`):
1. `test_world_case_agrees_with_world_of`. Fixture: every stamp combination (`paper` True, False or None; `broker` "paper", "etoro" or absent; `broker_env` "paper", "live" or absent) and one legacy `Position`. For each row, the annotation equals `world_of(row)`, and `_world_filter(qs, w)`'s pks equal the rows whose `world_of` is `w`.
2. `test_realized_by_world_uses_the_gate_rule`: `pnl=None` and `exit_price_unavailable` both count as unmeasured; the window is [now − 24 h, now]; no world is summed.
3. `test_realized_by_world_agrees_with_the_gate` (the second edition's C1 test 11, moved here): live + demo equals `realized_since(...)["live_realized"]`, and paper equals `paper_realized`. A second case adds one closed Main-book `Position`.
4. `test_account_world_per_row`: eToro demo and live; Saxo sim and live; IBKR paper port, live port and unknown port (live); OANDA practice; Alpaca paper; no row gives "".
5. `test_config_world_moved_verbatim`: OC0's `config_worlds` tests pass against the new import path.
6. `test_client_world_per_adapter` (the second edition's C3 test 18, moved here): `EtoroTrader(env="demo")` is demo; `SaxoTrader(env="sim")` is demo; `OANDATrader(env="practice")` is demo; `AlpacaTrader(env="paper")` is demo; `IBKRTrader(paper=True)` is demo; `PaperTrader` is paper; a `SimpleNamespace(env="live")` is None; `env="weird"` is None.
7. `test_oc0_figures_unchanged`: on OC0's fixture, /command/ and /eye/ print the same per-world figures before and after, except one close with `exit_price_unavailable`, which now reads "not measured".

**Acceptance (measured).**
- OC0's query budgets do not rise: page ≤ 105, live ≤ 50, portfolio ≤ 22, history ≤ 14, bots ≤ 14, metrics ≤ 25, measured after `cache.clear()`.
- `rg` finds exactly one definition each of `account_world`, `config_worlds`, `client_world` and `world_case`.

**Money direction.** None. No gate, router, lane, order path or sizing reads anything W0 adds or moves (`config_world` is read by display only until L2). Display change: on /command/ and /eye/, a close whose exit price was unavailable reads "not measured" instead of 0.00.

**Size:** S.

---

## 4. C1 · The worlds apart and the Horde's tabs

**Goal.** As in the second edition §3: one world switch, the Horde with one tab per world and figures that are never summed, and the screen places that add demo or paper to real money fixed. The scope is reduced by what OC0, O0 and #89 did (1.3).

**He will see.**
- **The Horde:** as the second edition §3.1, with these changes:
  - The switch is S1a's `.sv-seg` (segments carry the world chip; REAL is the solid red chip, `--sv-real`), with the second edition's ARIA tablist and keyboard script on top. S1a's classes carry no keyboard behaviour.
  - The **AT ETORO** cell sits on the tab of its own world (`head.etoro.world`). Demo equity never shows on the REAL tab.
  - The **ENTRY GATE** line follows the switch. While `real_only_limits_live` is OFF, or before L exists, it shows whenever demo seats or shared Main-book rows change the gate's figure, in the gate's own tone (calm, near, past). After L3 it shows only for Main-book legacy rows (`extra_rows`), which the gate counts as live while the Horde shows them under HAND.
  - The **REAL tab's own figure is what the gate will read once L is ON**, so he can watch the difference during the shadow.
- **The cockpit:** this list is done by C1 only if S1b has not merged when C1 starts. Otherwise C1 provides the context-processor keys and S1b's status-bar cells print them, as the OC spec §9 asks of S1b.
  - **OPEN P&L** leads with real money (`base.html:1058-1073`). The sub-line "real + paper across …" (1062) becomes "real money · n positions", with DEMO and PAPER beside it, never added.
  - **PORTFOLIO** takes OC0's words: **PLATFORM BOOK**, no currency sign, with its title "cash typed on /setup/ + the REAL and DEMO positions' notional + paper's open and realized P&L, not converted; not a balance" (890-893).
  - **REALISED 24H** is real money (951; `context_processors.py:860-878, 1061-1071`), with demo, paper and no-venue beside it, from W0's `realized_by_world`.
  - **BOT 24H P&L** is real money (1119).
  - **ENGAGED** has three worlds instead of two (937-940). `services.py:437` puts demo into PAPER ENGAGED today.
  - **FREE** is per world from W0's `config_worlds`, with **the account counted once per world** under shared capital (`services.py:403-409`, `mode_pool`).
  - **POOLS** is labelled per world (913-915).
- **The close dialog** names the world. Today it reads "This flattens a LIVE position at the broker" on a DEMO row (`base.html:4048`; `manual_close.py:412` sends `"venue": "live"` for every non-paper row). The new words:
  - REAL: "This flattens a REAL-MONEY position at the broker…".
  - DEMO: "This closes a DEMO position at eToro: simulated money…".
  - PAPER: as today.
  - A demo close still asks for the PIN (`position_summary.py:224-229`).

**What is left of the second edition §3 (the rest is done, 1.3):**
- §3.2: the Horde server, with `book_world` from W0's `account_world(broker_backed(user))` and `realized` from W0's `realized_by_world`.
- §3.2.1: the side per world. The `gate` dict also carries `"rule": "today" | "real_only"`, read from the switch once per board.
- §3.2.2: pools per world, placed by `config_worlds` and combined once per world.
- §3.4: the client.
- §3.5: the cockpit rows, as listed above.
- The Horde tab's demo side (`horde.py:2097-2106`).
- `_unseated` reads the world from `account_world` instead of the `env_label` prefix (1786).
- **Withdrawn:** the Eye row (OC0 did it), `world_q` (W0's `world_case` replaces it), and the OC LIVE tab rename (OC1 removes the tabs).

**Files** (lines in Appendix A):
- `dashboard/horde.py`
- `templates/_partials/the_horde.html`, `templates/_partials/world_switch.html` (new)
- `static/js/sv-horde.js`, `static/js/sv-world-switch.js` (new)
- `static/css/sv-horde.css`; `static/css/sauron.css` (only if S1a has not merged); otherwise `sv-kit.css` classes plus a small block
- `core/context_processors.py` (the strip keys)
- `templates/base.html` (the strip, if S1a's successor S1b has not merged; the close dialog at 4048)
- `bot_program/manual_close.py` (412: adds `"world": world_of(trade)`, keeps `"venue"` for old readers)
- `portfolio/services.py` (`capital_summary`: ENGAGED and FREE per world, display keys only)
- tests

**Absent from the diff, checked with `git diff --stat`:** `portfolio/risk_gate.py`, `bot_program/asset_engine/base.py`, `bot_program/manual_trade.py`, `bot_program/engine/broker_router.py`.

**Conflicts and order.**
- After W0. After S1a (the switch on its kit). If S1a slips past C1's start, C1 ships the second edition's `_proposed.css` block and S1a maps it to the kit.
- S1b moves the Horde's launch point and the strip. If S1b goes first, C1 keeps to the keys.
- F1 edits `manual_close.py` far from line 412, so the rebase is trivial.
- Bettor commit 4 (Horde banner display) comes after C1 and rebases on the tabs.
- O1 and O2a share only `position_summary` (W0).

**Tests written first.** As the second edition §3.6, with these changes:
- **Withdrawn:**
  - Test 13 (`world_q`): W0's test 1 covers it.
  - Test 23 (the Eye): OC0.
  - Test 11: moved to W0.
- **Renamed:** test 14 is the existing `test_a_warm_board_costs_the_same_for_3_and_30_seats` (`tests/test_the_horde.py:1345`, 10 queries at 1352).
- **Changed:** tests 3 to 5 become `test_the_gate_line_follows_the_switch`:
  - switch absent or OFF, one demo seat: the line is there, in the gate's tone, with the second edition's 15.5% past and 12.5% near cases;
  - switch ON, one demo seat and no Main-book row: no line;
  - switch ON with one Main-book legacy row: the line names only "1 row of the shared Main book".
- **New:**
  - `test_the_etoro_cell_sits_on_its_world_tab`: `head.etoro.world == "demo"` appears on DEMO only, never on REAL.
  - `test_engaged_is_per_world`: a demo row's capital is in DEMO ENGAGED and never in PAPER ENGAGED.
  - `test_free_counts_the_account_once_per_world`: shared capital ON with two REAL followers gives the real pool once.
  - `test_the_close_dialog_names_demo`: `preview_close` of a demo row gives `world == "demo"`, the dialog source keys its words on `p.world`, and `requires_pin` is still True.
  - `test_no_money_cell_adds_two_worlds` (OC0's scan pattern): with REAL +10.00, DEMO +1.00 and PAPER +100.00 rows, open and closed, the Horde payload, the strip and the board never print 11.00, 101.00, 110.00 or 111.00.
- Strip tests (`tests/test_cockpit_strip_worlds.py`): as the second edition test 22, with PLATFORM BOOK words.

**Acceptance (measured).**
- The warm board stays at 10 queries.
- The context processor's query count is unchanged (`assertNumQueries` on a fixture page against `15dd487`).
- The phone head at the smallest sheet fits in 227 px (the second edition measured 178).
- Screenshots: the second edition §3.7, items 1 to 9 (item 10, the Eye, is withdrawn). Item 1 adds the AT ETORO cell on REAL; item 2 shows it on DEMO when the row is in Demo.

**Money direction.** Display only.
- `risk_gate.py`, `base.py`, `manual_trade.py` and `broker_router.py` are absent from the diff.
- The REAL tab's figures read lower than the gate's while the gate counts demo. The gate line keeps the gate's own figure, in the gate's tone.

**Size:** L.

---

## 5. C2 · Results by World

**Goal and what he sees.** As in the second edition §4: `/bot-charts/` becomes **Results by World**, with the world switch, then Curves | P&L | Stats. Every figure comes from one world and one lane.

**Changes from the second edition:**
- **The world switch** is S1a's `.sv-seg` in links mode, as C1 builds it.
- **The Operations Center line (§4.7).** OC0 already labels the pooled figures "all worlds" and splits money by world, so C2 adds only the link "per world: Results by World ›".
  - If OC1 has merged (one page; `_command_portfolio.html` retired), the link goes into OC1's Review region.
  - On `/portfolio/` the line goes at `portfolio_overview.html:149` (was 132).
- **`_counts_by_world`** uses W0's `world_case` (one grouped query) instead of a Python loop.
- **`_monthly`** is extracted from `dashboard/views.py:3278-3304` (was 3094-3120) into `position_views.monthly_realized`.
- **`_account_drawdown`** reads `capital_truth.py:921-954` (was 796-830).
- **The account curve** reads `BrokerEquityReading.env` as the sync writes it (`tasks.py`, about 1171: `"paper"` for demo, `"live"` for real).
  - Until C4a, the DEMO curve exists only for the days the row was set to Demo, and its empty sentence says so.
  - After C4a, both worlds are written and the sentence drops the clause.

**Files.** As the second edition §4, at Appendix A's lines, plus the OC1 Review template if OC1 merged first.

**Conflicts and order.**
- After C1.
- If OC1 lands first, the link moves into OC1's Review.
- F4 (the feed) edits `portfolio_overview.html` and `_command_portfolio.html`; C2's one line rebases trivially.
- S2.4 (signals and portfolio pages) and C2 rebase in whichever order they land.

**Tests written first.** As the second edition §4.6, tests 1 to 22. Test 22 (`test_the_pooled_pages_point_here`) asserts the link on whichever OC template exists (`_command_portfolio.html` or OC1's Review).

**Acceptance (measured).**
- At most 6 queries on the page after `cache.clear()`.
- The second edition §4.8 screenshots 1 to 9.
- `test_worlds_never_meet` passes on the seed with distinct figures per world.

**Money direction.** Display only. The page writes the `sv_perf_world` and `sv_perf_tab` cookies.

**Size:** M.

---

## 6. C3 · The account on the ticket

**Goal and what he sees.** As in the second edition §5. TAKE TRADE and the deal ticket get an account choice:
- PAPER, and the class's broker route in the world the eToro row is set to.
- The other eToro world is listed "one world at a time" until C4.
- The default is what the ticket does today.
- The order goes to the chosen account or nowhere.
- No control ever suggests an account with more real money at stake.

**Changes from the second edition:**
1. **Ten readers of the manual lane's name**, all switched to `is_manual_lane` / `name__in=MANUAL_LANE_NAMES`:
   - `core/context_processors.py:663-665`
   - `bot_program/share_allocator.py:409-419`
   - `dashboard/views_system_health.py:528-538`
   - `dashboard/views_brain.py:97-103, 338-350`
   - `bot_program/telegram_eye.py:428-430`
   - `bot_program/management/commands/preflight_live.py:1089-1090, 1100`
   - `bot_program/management/commands/why_no_trade.py:117-124, 183`
   - **`bot_program/asset_engine/base.py:531-533`**: MAX BOT LEVERAGE never limits a manual lane, and the paper lane is one

   The words at `bot_program/manual_close.py:235` ("your hand-taken") are checked too.
2. **Five `_preview` call sites**, each passing the resolved `account`:
   - the two entry points (2525, 2535);
   - `_concentration_guard`'s probe (589);
   - `_execute` before the funding closes (3093-3094) and under the lock (3196-3197);
   - the Council brief (`council.py:1362`, with `create_lane=False`).
3. **The seen facts belong to one preview.** `dup_seen`, `shown_qty` and `shown_raised` (#94) are reset whenever the account changes. If they were carried over, a holder visible only on the new account's book would pass as "seen". The client's `keep` carries `qty`, `stop` and `target` only.
4. **`accounts.py` reads W0's `account_world` and `client_world`.** It adds no table of its own.
5. **The ticket record names the account.** `dashboard/ticket_outcome` stores the resolved key, so a lost answer's lookup says which account was asked.
6. **`_parse_trade_body`** (`views.py:5234-5357`) parses `account` and answers 400 on a bad shape, beside `dup_seen`, `shown_qty` and `shown_raised`.
7. **The HQ arm card** (`views.py:4477-4520`) still calls `manual_config_for` on a GET (about 4519). It becomes `manual_config_if_any`, as the second edition said.
8. **A PAPER ticket's book advisory reads the paper book.** The unnamed `preflight` (`manual_trade.py:1746`) judges open risk on the live venue even for a paper ticket (`risk_gate.py:2088-2090`). C3 passes the chosen account's venue (`"paper"` for PAPER, `"live"` otherwise). This changes a warning only: a PAPER ticket stops showing real-money limit warnings and shows the paper book's.
9. **The venue-health advisory** (`manual_trade.py:1204-1218`, world at 1213-1218) takes the client's world (W0) when it is readable.
10. **The C4 hook.** The key space already holds `etoro:live` and `etoro:demo`. `accounts_for` lists the other eToro world as not selectable with "one world at a time", and C4c lifts that.

**Files.** As the second edition §5.2 to §5.4, at Appendix A's lines, plus `dashboard/ticket_outcome.py`, `bot_program/asset_engine/base.py` (531-533, the predicate only) and `preflight_live.py`.

**Untouched, checked by the reviewer:** `bot_program/engine/broker_router.py`, `portfolio/risk_gate.py`, `bot_program/engine/venue_close.py`, `arm_manual_lane`, the Demo-box guards in `views_brokers.py`, and `venue_health.world_of`.

**Conflicts and order.**
- After C1 (vocabulary, `.sv-world` words) and W0.
- C3 and L2 both edit `manual_trade.py`; the second to land rebases.
- S2.1 (ticket and instrument page) rebases on C3 ("UI yields to money work").
- The Bettor's ticket commits (6, 8, 22) come after C3.
- Orders at a price (P1–P5, approved): a resting order belongs to the lane of its account. Whichever starts second rebases and carries the key.

**Tests written first.** As the second edition §5.5, tests 1 to 20 (test 18 moved to W0), plus:
- `test_the_five_preview_sites_pass_the_account`: mock `_preview` and assert `account` and `create_lane` at each site.
- `test_seen_facts_reset_on_account_change`: preview on A carries A's `dup_seen`. Re-preview on B, then execute with A's facts. A holder visible only on B's book is refused as unseen, and nothing is sent.
- `test_the_paper_lane_is_never_bot_levered` (`base.py:531-533`).
- `test_preflight_live_names_the_paper_lane` (1089-1090, 1100).
- `test_a_paper_ticket_reads_the_paper_book`: a PAPER preview's `book_advisory` comes from `venue="paper"`, and a real-money open-risk breach produces no warning on it.
- `test_the_lost_answer_names_the_account`: the #94 lookup carries the key.
- `test_an_old_client_without_account_gets_today_s_ticket`: a body with no `account` gets the default key, and its answer equals today's.

**Acceptance (measured).**
- The second edition §5.6 screenshots.
- In every refusal test, `market_order` is never called (mock).
- `assertNoMoney` on the choice for a non-staff user.
- `git diff --stat` shows the untouched list untouched (`base.py` only at 531-533).
- **On his server after deploy:**
  - a PAPER ticket taken beside his armed live lane books on `manual-paper`;
  - the default ticket goes where it went before, with the same PIN;
  - the ticket record shows no new 400 from a cached page without `account`.

**Money direction.** It tightens. New refusals, each before anything is sent:
- the route no longer matches the chosen account (at preview, under the lock, and right after the client is built);
- the client's world cannot be read;
- the lane changed mode between the preview and the send;
- an eToro proof gap, now refused at preview (it was already refused at execute, after the PIN);
- facts seen on another account.

It never escalates.

**Looser or moving cases, named:**
1. **Paper.** A new paper lane per class is an enabled config, and its capital joins the paper desk budget (`capital_desk.venue_capital(user, "paper")`, 640-). The desk may place more paper while `capital_desk_mode_live` is ON. It also raises ALL POOLS, ALL FREE and PAPER FREE (display).
2. **The real-money fallback denominator.** A paper hand ticket's P&L moves the platform book value (`services.py:968-986`). That value sizes the real-money limits only when the broker reading is missing or older than 2 hours. A paper gain loosens that fallback; a paper loss tightens it. Paper bots already do this. L removes it when ON.
3. **Warnings.** A PAPER ticket no longer carries real-money limit warnings; it carries the paper book's.

Bots are unchanged.

**Size:** L.

---

## 7. L · Real-only limits (D1 and D4), shadow first

### 7.1 The rule

**Three worlds:**
- `live`: rows whose `world_of` is live, plus the shared Main book's legacy `Position` rows, which the gate counts as live today.
- `demo`: rows whose `world_of` is demo.
- `paper`: rows whose `world_of` is paper. This includes a non-paper row stamped with the simulator carrier.

Under the **real-only** rule each world is judged on its own rows against its own denominator (7.2). Under the **today** rule, `demo` is judged exactly as `live` is today (live and demo rows, the live denominator). The today rule is byte-identical to `15dd487`, and a test pins it (test 1).

**The switch.** `real_only_limits_live`, in the System category:
- in `LIVE_MONEY_SWITCHES` (`core/platform_control.py:97-110`), so it takes the PIN at every door (`PIN_SWITCHES`, 132; `core/switch_pin.py`);
- excluded from "all on" (`BULK_ENABLE_EXEMPT`, 153-154);
- counted on the Wall (`core/wall_facts.py:440-441`);
- OFF on arrival; turning it OFF never asks for the PIN.

`risk_gate.limits_rule()` reads it **once per judgement** and passes it down as `rule=`.

**One read, two answers.** Each state function buckets its rows by world in its single loop and returns:
- the binding answer, for the rule in force;
- `shadow`, the other rule's answer;
- `parts`, the per-world pieces.

The shadow therefore costs no extra row query. Only the per-world denominators are read twice (two cached-cell reads).

**The order's world at gate time:**

| Caller | World |
|---|---|
| `AssetBot.can_open_new` (`base.py:4716-4740`) | `worlds.config_world(user, cfg)` for a live-mode config (unreadable gives live); paper for a paper config |
| `AssetBot.execute_entry` (open risk at 6261, notional at 6279, duplicate at 6329, theme at 6337) | `worlds.client_world(client)` for a live-venue candidate (None is judged live: an unknown world is real money); paper for a paper-venue candidate |
| The elite allowance at the send (`base.py:6406-6416`) and at the gate (4731-4732) | The candidate's world |
| Correlation taper (`base.py:5384-5387`) | The candidate's world |
| `_paper_book_refusal` (7673-7683) | Paper (unchanged) |
| The hand ticket: `_concentration_guard` (612-620), correlation note (770, 2483), the book advisory (1746), concentration (2046-2054), duplicate and theme (2073-2081), notional (2093-2095), `_judge_ticket` (2836-2837), the unseen-holder checks (3025-3028, 3466-3469), theme under the lock (3235-3236) | After C3, the chosen account's world. Before C3, `client_world` of the lane's client, or paper for a paper lane |

### 7.2 The denominators (D4)

| World | Real-only rule | Today rule (unchanged) |
|---|---|---|
| live | The **live-world** broker reading, world-checked (eToro's `last_margin_world == "live"`, the rule of `etoro_stored_equity`; other brokers through `account_world`), when it is no older than `LIVE_EQUITY_MAX_AGE_S`. Otherwise **`Portfolio.real_book_value`** (L1): cash plus the marked notional of rows whose world is live or legacy. Never demo notional, never paper P&L | `account_equity` with no world check, then `gate_book_value` (cash + every non-paper notional + paper P&L) |
| demo | The **demo-world** reading, world-checked, when it is no older than 2 h. Otherwise the last demo reading, said with its age ("stale"). With no reading ever, the demo limits abstain and say so (demo only) | Same as live |
| paper | **`Portfolio.paper_book_value`** (L1): cash plus paper's open and realized P&L (`_simulated_realized_pnl`) | `gate_book_value` |

### 7.3 Sub-stages

**L1 · One book value per world (storage).**
- A migration on `portfolio.Portfolio` adds `real_book_value`, `paper_book_value` and `world_books_at`, all nullable. `PortfolioSnapshot` gains `real_value`, `demo_notional` and `paper_value`, all nullable, with no backfill.
- `live_book_value(user)` (`services.py:968-986`) returns `real_marked`, `demo_marked`, `simulated_pnl` and `simulated_realized` beside today's `value`, which is unchanged and stays the PLATFORM BOOK on screen.
- `store_book_value` (`portfolio/tasks.py:123-149`) writes the two new columns beside `current_value`, under the same no-partial rule **per world**: a world with an unpriced row keeps its last value.
- The daily snapshot (`portfolio/tasks.py`, about 290-370) writes its three new columns. `total_value`, `max_drawdown` and `sharpe_ratio` are unchanged.
- Nothing reads the new columns until L2's shadow.
- **Files:** `portfolio/models.py`, a migration (the next free number), `portfolio/services.py`, `portfolio/tasks.py`, `tests/test_world_book_values.py`.

**L2 · The world rule in the gate, in shadow.**
- **`portfolio/risk_gate.py`** at `15dd487`, each function taking `world` or `venue` in (live, demo, paper) and `rule`:
  - `gate_book_value` (285-335) and `venue_book_value` (344-373);
  - `open_capital_at_work` (479-594), `realized_since` (595-716, adds `demo_realized`), `daily_loss_state` (717-828);
  - `open_risk_state` (849-936). The legacy-mirror skip uses the judged world's bot symbols (898, 909-910).
  - `elite_entries_since` (937-949; `world=`, with `paper=` kept as an alias);
  - `exposure_state` (950-1083), `open_notional` and `notional_state` (1090-1192; legacy skip 1118, 1124-1125);
  - `_one_venue` (1403-1415) becomes `_one_world`, and so do its callers: `symbol_side_exposure` (1425-), `concentration_state` (1481-), `duplicate_state` (1607-1698), `theme_state` (1836-) and `correlation_state` (1945-);
  - `preflight` (2040-2137). Unnamed, as the cards call it, it returns each world apart.
- **The desk** (`bot_program/capital_desk.py`): `book_risk` (579-; venue becomes world in its row filter, 611-618), and `venue_capital_detail` (689-): the live budget sums only configs whose `config_world` is live.
- **Per-config checks** in `can_open_new`: the slots (4754-4756) and the config's own day (4766-4790) count the config's rows of its own world.
- **Morgul's own world reader** (`morgul.py:423-429`) follows `world_of` when the switch is ON.
- **Display keyed on the switch:**
  - C1's gate line.
  - The Oculus desk sentence (`dashboard/oculus.py:1059`, docstring 1002). While OFF: "The real-only limits are in shadow (switch OFF): the desk and the gate count demo rows as live." While ON: the count is 0 and the sentence says the desk counts REAL rows only.
  - The /ops/ row's description.
  - `preflight_live` prints the switch's state.
- **The shadow record** (`portfolio/limits_shadow_models.py`, new):
  - `LimitsShadow` has `at`, `user_id` and `config_id` (integers, no foreign key), `lane` ("bot_gate", "bot_entry", "ticket_preview" or "ticket_send"), `symbol`, `side`, `world`, `today` and `real_only` (allow, refuse, elite or warn), and `direction` (same, looser or tighter). `checks` (JSON) holds each check's verdict under both rules, its percentage of its world's denominator, and the `parts` (real, demo, legacy, simulator-carrier and paper-P&L figures). It also holds `explained` (bool), the counterfactual fields (`price`, `stop`, `target`, `horizon_h`, `counterfactual_r`) and `ref`, which is unique per (lane, ref).
  - `LimitsShadowTally` holds `(day, lane, direction, n)`.
  - It is written after the money path's transaction commits, in its own short transaction, through a fence that logs and never raises into the money path. This is F1's `feed_fence` pattern; L2 reuses it if F1 has merged and twins it otherwise.
- **What is recorded:**
  - every bot entry judgement that reaches a book limit in `execute_entry`;
  - every ticket preview and send;
  - `can_open_new` only when the two rules disagree, deduplicated per (config, direction, hour). Its agreements go to the daily tally.
- **The grade against today.**
  - `explained` is True when today's figure equals the real-only figure plus the parts removed, to the cent, for each additive check (open risk, exposure, notional, realized, the fallback book).
  - For a **looser** bot entry (refused today, allowed real-only), the nightly pass prices what it would have made with `capital_desk.walk_bracket` (1364) over `_decision_bars` (1338), as the desk prices its displaced rows.
- **The report:** `manage.py real_only_limits --days N [--list looser|tighter]`. It prints:
  - per lane, n judged, same, looser and tighter;
  - per check, looser and tighter;
  - the elite-mode differences;
  - the count of unexplained records, which must be 0;
  - the looser entries' counterfactual R.

  It prints counts, percentages and R. It never prints money.
- **RUNBOOK:** a section "Real-only limits": what the switch does, the report, and how to turn it on and off.
- **Files:**
  - `portfolio/risk_gate.py`, `portfolio/limits_shadow_models.py`, a migration;
  - `bot_program/asset_engine/base.py` (the callers above), `bot_program/manual_trade.py` (the callers above), `bot_program/capital_desk.py`, `bot_program/morgul.py` (423-429);
  - `core/platform_control.py` (the switch and its row), `core/wall_facts.py`, `dashboard/oculus.py`, `dashboard/horde.py` (the rule key);
  - `bot_program/management/commands/real_only_limits.py`, the nightly hook in `bot_program/tasks.py`;
  - `deploy/RUNBOOK.md`;
  - tests.

**L3 · He turns it on.**
- After the acceptance in 7.5, he turns `real_only_limits_live` ON at /ops/ with the PIN.
- **Rollback:** turn it OFF. The next judgement uses today's rule, and nothing stored needs undoing.

### 7.4 Money direction, the switch ON (L3)

L1 and L2 are neutral while the switch is OFF. Byte-identical verdicts are pinned by test 1 of 7.6. With the switch ON, for real money:

**Looser: allowed sooner or larger.**
1. **Open risk.** Demo rows' risk at their stops leaves the real MAX OPEN RISK (`open_risk_state`, rows at 888-890). Real entries are refused later.
2. **Exposure.** Demo capital at work leaves the real MAX TOTAL EXPOSURE (`open_capital_at_work` 538-543, through `exposure_state` 1004-1012).
3. **Notional cap.** Demo notional leaves the real MAX NOTIONAL MULTIPLE (`open_notional` 1106-1107).
4. **Daily loss.** Demo losses leave the real day (`realized_since` 679-684; `daily_loss_state` 763-770). The daily stop, then the elite-only mode, then the absolute stop (800-821) trip later.
5. **Elite.** A demo loss no longer puts real money in elite mode, so a real entry goes at **full size** where today it goes at half (`ELITE_SIZE_SCALE`), and real money gets more entries than 2 a day. The elite allowance stops counting demo elite entries (946; bots 4731-4732, 6411-6412).
6. **Duplicate, theme, concentration and correlation for the bots.** A demo holding no longer refuses a real entry on the same idea and no longer counts toward a currency theme's legs. It no longer **tapers a real entry's size** by correlation, so the size can be **larger** (`_one_venue` callers at 1642-1644, 1902-1905, 1990-1992; bots at 6329, 6337 and 5384-5387).
7. **Per-config checks.** A live config's slots and its own day stop counting rows of the other world, such as demo rows left open after an untick.
8. **The capital desk**, when `capital_desk_mode_live` is ON. Demo rows leave `book_risk`, so the real budget's marginal risk is lower and the desk resizes and displaces less. That means larger or more real entries. With the desk in shadow, only its record changes.
9. **The hand ticket.** It shows fewer warnings (book limits, duplicate, theme, concentration). The unseen-holder **refusal** no longer fires on a demo holder.
10. **Simulator-carrier rows.** A non-paper row stamped with the simulator carrier (`world_of` reads it as PAPER) leaves the real counts, including Morgul's own checks.
11. **The biggest practical effect.** Demo rows left open after an untick stop holding room in every real-money limit. Unticking does not wait for demo positions to close (`views_brokers.py:634-694`), and reconcile never closes them (`reconcile_asset.py:183-191`).
12. **The real fallback denominator without paper P&L.** It is looser while paper is net negative.
13. **In demo mode** (the box ticked), the real-money denominator moves from the demo equity to the real fallback. That is looser when the demo equity is smaller than the real fallback. Today no real eToro order can be placed while Demo is ticked (`views_brokers.py:788-832`).

**Tighter.**
1. **Demo gains stop offsetting real losses.** Both are summed into one live total today (679-684). The daily stop, the elite-only mode and the absolute stop trip sooner on real losses.
2. **Legacy Main-book rows stop being skipped** when only a demo bot row held their symbol (898, 909-910; 1118, 1124-1125). They are counted in open risk and the notional cap.
3. **The real fallback denominator loses the demo notional** (`services.py:979-982`) whenever the reading is missing or older than 2 h (`risk_gate.py:368-372`). It loses paper P&L too, which is tighter while paper is net positive.
4. **The desk's live budget** stops summing the capital of live-mode configs routed to demo, when the desk is live.
5. **The hand ticket's daily-loss warning** fires sooner (a warning only).
6. **In demo mode** with a demo equity larger than the real fallback.

**Demo** (simulated money; decision D1a). Demo entries meet demo's own limits against the demo account. They can be refused where today only real rows could refuse them, and allowed where today real rows refused them.

**Paper.** The paper denominator loses real and demo notional, which is tighter for paper.

**Unchanged:**
- the single-position cap (each caller's own pool: `base.py:6238-6245`; `manual_trade.py:612-620, 2046-2054`);
- `pool_vs_book`, `declared_book` and `sizing_gap` (1193-1311);
- the eToro cash gate, which already checks the world (`base.py:8784-8790`);
- the share allocator's sizing (`share_allocator.py:200-206`; `capital_truth.py:896-900`);
- the PIN, the proof gate and the venue minimum.

The evidence lanes stay outside L, under D6.

### 7.5 Acceptance (measured, before L3)

1. **At least 14 days in shadow with the bots running**, and at least 100 recorded entry judgements (bot entries and tickets). If 30 days pass with fewer than 100, he decides on what exists.
2. **Unexplained = 0.** The identity holds on every record.
3. **He has read `--list looser`.** That is every entry the change would have let through, with its counterfactual R.
4. **On the same instant,** the Horde REAL tab's own open risk equals the shadow's real-only open risk (a test, and one spot check on his server).
5. **After ON:** for 24 h, every record's binding verdict equals its real-only one, and `preflight_live` reports the switch ON.

### 7.6 Tests written first

**L1:** `tests/test_world_book_values.py`
- `value == cash + real_marked + demo_marked + simulated_pnl + simulated_realized`, to the cent, on a fixture with live, demo, paper and legacy rows.
- `store_book_value` writes `current_value` byte-identically, plus the two new columns. A world with an unpriced row keeps its old column.
- The snapshot writes its new columns. `total_value`, `max_drawdown` and `sharpe_ratio` are unchanged.
- OC0's pin `live_book_value(user).value` is unchanged.
- The migration is reversible.

**L2:** `tests/test_real_only_limits.py`
1. **`test_off_is_byte_identical`.** On a fixture with every world, each state function, `preflight`, `can_open_new`, `execute_entry`'s checks and the ticket's preview and send give the same binding answers with the switch OFF as golden JSON recorded at `15dd487`.
2. **`test_the_identity`.** Today's figure equals the real-only live figure plus demo plus the simulator-carrier rows, for open risk, exposure and notional. Today's `live_realized` equals live plus demo. The today fallback equals real plus demo notional plus paper P&L.
3. **One test for each looser case 1 to 13 of 7.4, with the switch ON.** Each asserts the real entry is allowed (or not halved, not tapered, not warned) and that the shadow record says "looser".
4. **One test for each tighter case 1 to 6.** For example: live −100 and demo +80 against a −50 floor is refused ON and allowed OFF.
5. **`test_demo_is_judged_on_its_own`.**
   - A demo order is refused by demo's open-risk limit against the demo equity.
   - A demo order is never refused by real rows.
   - With no demo reading ever, the demo limits abstain and say so.
6. **`test_unknown_world_is_real`.** `client_world` None is judged as live.
7. **`test_the_switch_is_a_live_money_switch`.**
   - It is in `LIVE_MONEY_SWITCHES` and in `DEFAULT_COMPONENTS` (system), and OFF on arrival.
   - "All on" leaves it OFF.
   - ON needs the PIN at every door; OFF never asks.
   - The Wall's count rises by one.
   - `tests/test_ops_cockpit.py` passes.
8. **`test_shadow_is_fenced`.**
   - An exception in the recorder never reaches the money path.
   - Nothing is written before the commit, and a rolled-back judgement leaves no row.
   - There is no foreign key.
9. **`test_one_row_per_entry`.**
   - One row per bot entry judgement and per ticket preview and send.
   - `can_open_new` writes a row only when the two rules disagree, deduplicated hourly; the tally counts agreements.
10. **`test_the_report_prints_no_money`.** A `PAGE_FIGURES`-style scan of the command's output finds counts, percentages and R only.
11. **`test_counterfactual_is_graded`.** The nightly pass sets `counterfactual_r` on a looser bot entry from `walk_bracket`.
12. **`test_the_oculus_desk_sentence_names_the_switch`**, and C1's `test_the_gate_line_follows_the_switch`.
13. **Existing suites stay green with unchanged assertions:**
    - `test_venue_book_limits`, `test_venue_split`, `test_venue_expression_gates`, `test_open_risk`;
    - `test_elite_past_daily_stop`, `test_gate_denominator`, `test_risk_limits_bind`, `test_book_notional_cap`;
    - `test_capital_desk`, `test_desk_grading`, `test_shared_capital`, `test_free_cash_decides_alone`, `test_pledged_ceiling`;
    - `test_take_trade`, `test_take_trade_live`, `test_manual_*`, `test_morgul`;
    - `test_brain_reads_venues`, `test_money_world`, `test_switch_pin`.

### 7.7 Conflicts and order

- After W0 (`config_world`, `client_world`, `account_world`).
- Parallel to C1; C1 reads the switch key, which is absent until L2 and reads as OFF.
- C3 and L2 both edit `manual_trade.py`; the second to land rebases.
- **The Bettor:**
  - its rails (commit 5 and later) read L1's per-world book values and L2's world parameter;
  - commit 14 (gates re-keyed in shadow, `risk_gate.py`) comes after L2;
  - its real-money binding (commit 21 and later), which its spec makes depend on "Live/paper apart C1-C3", depends on **L3 ON and C4a** (a demo equity of its own).
- **F1** edits a different function in `portfolio/services.py` (the venue-source rule), so the rebase is trivial.
- **Migrations:** L1 and L2 take the next free numbers at build time (F1 holds `bot_program/0051`).

**Sizes:** L1 M, L2 L.

---

## 8. C4 · eToro REAL and DEMO side by side

### 8.1 C4a · Both eToro worlds read

**Goal.** Read and keep each eToro world's figures apart, and manage each row in its own world. Nothing in C4a changes what a real-money order, limit or size reads.

**He will see.**
- The Horde and the strip show eToro REAL's and eToro DEMO's cells, each on its own tab, both read.
- Demo positions left open after an untick become closable and managed.
- /brokers/ shows both worlds' cash and equity, each with its age.

**What it builds:**
- **Per-world cells.**
  - A new `EtoroWorldCells(account, world)` table holds the cell set of `EtoroAccount` (`models.py:396-453`): equity and its currency and time, positions and their time, available cash, used margin, margin time, P&L, frozen cash and balance.
  - `sync_etoro_accounts` (`tasks.py:1014-1210`) writes the box world's cells **into the row, as today, and into `EtoroWorldCells(box world)` in the same save**. Every existing reader is therefore unchanged.
- **The other world is read**, at P2 (refusable), when a lane pins it (C4b) or when open rows of that world exist. History rows already carry their `env` (1167-1173).
- **The account follow** (1186-1187) runs per world in C4b, not here.
- `refresh_etoro_cells(acct, world)` builds its client from the world, not from the box (1387).
- **`etoro_cells`** notes and refreshes are keyed by (account, world) (`etoro_cells.py:130-153, 185-253, 327-`).
- **Readers.** `capital_truth.cells_of(user, world)`, plus `world=None` on `etoro_stored_equity` and `account_equity`, where None means the box world, as today. Each reader that has a subject chooses its world:

  | Reader | World |
  |---|---|
  | `withdrawals.py:273` (the reserve) | live |
  | `preflight_live.py:745` | live |
  | Morgul G6 (`morgul.py:959-1010, 1329-1332`) | Brakes on live cells only; demo cells give warnings |
  | `alerts/digest_book.py:134-141` | Per world, display |
  | `etoro_used.account_used` (322-, world at 350-354) | Per world |
  | `services._etoro_holdings` and `venue_pnl` (1106-1133, 1386-) | The row's own world |
  | The Horde and strip eToro cells (`horde.py:2018-2022`; `context_processors.py:545-547`) | Per world |

- **Rows managed in their own world.**
  - **New `broker_router.client_for_trade(trade, purpose)`.** For an **eToro** row stamped `broker_env` it builds the stamped world: "paper" is demo, "live" is live. For an unstamped row or another carrier it returns `client_for_symbol(user, trade.symbol, trade.config)` exactly as today.
  - **Users:**
    - reconcile (`reconcile_asset.py:477, 745, 1010, 1177`; the sweep at 1313-1314);
    - the follow-up sites of the second edition's map (management, the CLOSE button, the pending-close drain, the kill switch, stop moves, the Eye, the Council and the in-doubt probe).
  - **Kept:**
    - the world-mismatch guard (`reconcile_asset.py:183-191`);
    - `close_or_refuse`'s carrier and world refusals (`venue_close.py:99-141`) as the safety net.
- **The request budget** (`bot_program/engine/etoro_budget.py`).
  - Demo-world requests in the execution and lookups families are **taken** (refusable), with a floor `FLOOR_DEMO = 0.5`: demo may use at most half of each family a minute. They are never sent-and-counted the way real P0/P1 requests are.
  - A 429 met in **either** world pauses both worlds' P2 to P5 for that key, because eToro meters per key (header lines 3-8; the pause is per key and world today, 399-400, 601-).
  - **Load at the 60 s sync:** at most 4 account reads a minute per account, plus one /portfolio read per world per reconcile pass. That fits the guessed 30 a minute.

**Files:**
- `bot_program/models.py`, a migration, `bot_program/tasks.py`, `bot_program/etoro_cells.py`, `bot_program/capital_truth.py`;
- `bot_program/engine/broker_router.py` (`client_for_trade`), `bot_program/reconcile_asset.py`;
- the follow-up sites (`asset_engine/base.py`, `manual_close.py`, `pending_closes.py`, `engine/kill_switch.py`, `adjust_levels.py`, `telegram_eye.py`, `dashboard/views_council.py`);
- `bot_program/engine/etoro_budget.py`, `bot_program/withdrawals.py`, `bot_program/morgul.py`, `alerts/digest_book.py`, `bot_program/etoro_used.py`, `portfolio/services.py`, `dashboard/horde.py`, `core/context_processors.py`;
- `bot_program/management/commands/preflight_live.py`, `dashboard/views_brokers.py` (display).

**Tests written first** (`tests/test_etoro_two_worlds_reads.py`):
1. The sync writes the box world's cells into the row and into `EtoroWorldCells(box)` in one save, identically.
2. With other-world open rows, the sync reads that world into its own cells, never into the row's. The history row carries its `env`.
3. `cells_of(user, "live")` never returns demo cells, and the reverse. `etoro_stored_equity(user)` is unchanged. `etoro_stored_equity(user, world="live")` refuses demo cells.
4. The budget counters show at most 4 account reads a minute per account with both worlds read.
5. Reconcile reads a demo row's demo book when the box is live; a real row always meets the live book.
6. `client_for_trade`:
   - an eToro row stamped demo gets a demo client whatever the box says;
   - an eToro row stamped live gets a live client;
   - an unstamped row or a non-eToro row gets exactly today's `client_for_symbol` result (pinned).
7. Every follow-up site calls `client_for_trade`: an AST scan, plus behaviour tests on the close, the kill switch and the drain.
8. `close_or_refuse` still refuses a world mismatch (a live-stamped row given a forced demo client).
9. The budget:
   - demo execution takes are refused past half the family, while real P0/P1 are never refused;
   - a 429 in either world pauses both worlds' P2 to P5 for the key.
10. The named readers: withdrawals read live cells, Morgul G6 brakes only on live cells, and the digest is per world.
11. Existing suites stay green: `test_etoro_budget`, `test_etoro_rate_pause`, `test_etoro_cheaper_reads`, `test_reconcile_*`, `test_morgul`, `test_withdrawals`, `test_venue_pnl`, `test_preflight_live`.

**Acceptance (measured, on his server):**
- For 7 days, `EtoroWorldCells(box)` equals the row's cells on every pass (a check in `preflight_live`).
- At most 4 account reads a minute per account.
- No 429 in either world in the budget's counters, by world.

**Money direction.** Neutral for real-money orders, limits and sizes. No gate reads the second world's cells, and real rows' follow-ups go to the same world as today: no real eToro row can be open while Demo is ticked (`views_brokers.py:788-832`).

What changes:
- demo rows of the other world are reconciled, managed and closed in their own world (simulated money);
- with the other world read, there are at most 2 more account reads a minute per account, at P2;
- a burst of demo orders or closes can no longer take room from real orders in the request budget;
- a 429 met in either world pauses both worlds' background reads.

**Size:** L.

### 8.2 C4b · Two eToro lanes and their money gates, in shadow

**Goal.** Give each eToro world its own lane, its own pinned route and its own money gates, all computed and recorded while the switch is OFF.

**He will see.**
- **The HQ arm card** shows, per class carried by eToro, a **REAL lane** (the existing broker lane) and a **DEMO lane** (`manual-demo`), each with its own arm action.
- **/brokers/** labels the Demo box "the bots' world: REAL | DEMO" (D3 default).
- A new switch row, **"eToro REAL and DEMO side by side"**, OFF.

**What it builds:**
- **The lanes.**
  - The REAL lane is the class's existing `manual` lane, pinned `extras["account"] = "etoro:live"`. The DEMO lane is the new `manual-demo` (`MANUAL_DEMO_NAME`, covered by C3's `is_manual_lane` and its ten readers), pinned `"etoro:demo"`. Its capital is copied from the broker lane at creation, as C3's paper lane is.
  - **A pin is written only by the arming ceremony** (`arm_manual_lane`, `manual_trade.py`):
    - REAL: the PIN, then a second confirmation, and a REAL reading fresh within `TRACKING_FRESH_SECONDS` from C4a's live cells.
    - DEMO: the PIN and a fresh demo reading.
  - A pin is refused while the lane holds an open row of the other world.
  - Disarming removes the pin.
  - A pin on a config that is not a manual lane is never read.
- **The pinned route.**
  - `client_for_symbol(user, symbol, cfg)` honours the pin on a manual lane only.
  - It builds **`DemoOnlyEtoroTrader`** (`etoro_client.py:4231-4266`) for `etoro:demo`, and a new **`LiveOnlyEtoroTrader`** twin for `etoro:live` that refuses the demo segment on the wire.
  - A pin that names a carrier other than the class's route gives a `PaperTrader`, which a live lane refuses loudly, and C3's `route_matches` refuses it too.
  - **While the switch is OFF the router builds today's client.** The pinned client is computed and recorded only (below).
- **The shadow route record.**
  - For every eToro ticket preview while OFF, it records today's client world and the pinned world (W0's `client_world`) in a `RouteShadow` table beside `LimitsShadow` (`portfolio/limits_shadow_models.py`), written through the same fence.
  - Acceptance needs equality for the box world (8.5).
- **Money gates per world:**
  - **`_cash_gate`** (`base.py:8784-8790`) judges with `cells_of(user, order world)`. Its world check compares the cells' world with **the order's**, not the box's.
  - **`_pledged_since`** (8520-8573, filter at 8556-8559) filters rows by world (`broker_env`) as well as carrier.
  - **`_leverage_headroom`** reads the cells of the order's world.
  - **`tracking_freeze_reason(user, cfg)`** (`capital_truth.py:587-606`) reads the reading of the config's world.
  - **`_follow_the_account`** (`tasks.py:672-`) runs per world. Followers (`capital_truth.followers_of`, 692-701) are grouped by `config_world`, and each world's followers share that world's reading. The sync calls it once per world it read. **A real-world pool is never sized from the demo equity.**
  - **`venue_health_advisory`** (`manual_trade.py:1204-1218`) takes the client's world.
- **The Demo box guards** (`views_brokers.py`) are unchanged in kind. Ticking Demo is also refused while the **REAL lane** holds a real eToro position, because those rows are real positions.
- **The switch.**
  - `etoro_two_worlds_live` is in `LIVE_MONEY_SWITCHES`, OFF on arrival, PIN to turn on, excluded from "all on".
  - **It refuses to turn ON while `real_only_limits_live` is OFF.** The /ops/ door says why.
  - Every pinned path re-checks both switches at call time and refuses with "both eToro worlds side by side need the real-only limits ON". This holds even if a shell flips the row.

**Files:**
- `bot_program/manual_trade.py` (lanes, `arm_manual_lane`, `venue_health_advisory`), `bot_program/accounts.py` (C3's);
- `bot_program/engine/broker_router.py` (208-240 and the pinned branch), `bot_program/engine/etoro_client.py` (`LiveOnlyEtoroTrader`);
- `bot_program/asset_engine/base.py` (8520-8573, 8784-8790, `_leverage_headroom`), `bot_program/capital_truth.py`, `bot_program/tasks.py`;
- `dashboard/views.py` (HQ arm card 4477-4520), `dashboard/views_brokers.py`;
- `core/platform_control.py`, `core/switch_pin.py` (the refusal while L is OFF), `core/wall_facts.py`;
- `deploy/RUNBOOK.md`, tests.

**Tests written first** (`tests/test_etoro_two_lanes.py`):
1. Arming:
   - the REAL pin needs the PIN, the second confirmation and a fresh REAL reading;
   - the DEMO pin needs the PIN and a fresh demo reading;
   - a pin is refused while the lane holds rows of the other world;
   - a bot config with `extras["account"]` routes exactly as today.
2. The router:
   - pinned clients are built only in the pin's world;
   - `DemoOnlyEtoroTrader` and `LiveOnlyEtoroTrader` refuse the other segment, on the attribute and on the wire;
   - an unbuildable pin gives `PaperTrader`, and the live lane refuses it.
3. While OFF, the router returns today's client on every path, and the shadow record holds both worlds.
4. `_cash_gate` per order world:
   - a REAL order while the box is ticked is judged on live cells;
   - stale live cells refuse REAL only;
   - demo cells never gate a REAL order, and the reverse.
5. `_pledged_since` per world: a demo row is never charged against live cash.
6. The follow per world:
   - with the box ticked, the REAL lane's pool follows the live reading and the DEMO lane's follows the demo reading;
   - no real-world follower ever takes the demo equity.
7. `tracking_freeze_reason` per world.
8. The switch:
   - turning it ON is refused while L is OFF;
   - a pinned path refuses at call time when L is OFF, even with the C4 row ON;
   - it takes the PIN at every door and is excluded from "all on".
9. The /brokers/ tick guard counts the REAL lane's rows.

**Acceptance (measured).** At least 50 eToro ticket previews in shadow, with the pinned route equal to today's for the box world and no difference.

**Money direction.**
- Neutral while OFF: the router builds today's client, and the shadow only records.
- The money gates per world change no verdict while one world trades:
  - the cells read are the box world's, as today;
  - no demo row is opened while live cash is read, and the reverse.

  This is pinned by the existing `test_free_cash_decides_alone`, `test_pledged_ceiling` and `test_shared_capital`.
- The arming ceremony and the tick guard only refuse more.

**Size:** L.

### 8.3 C4c · Both on the ticket; REAL asks for the PIN twice

**He will see.**
- TAKE TRADE and the deal ticket list **eToro · REAL** and **eToro · DEMO**, both selectable, with PAPER.
- The default is today's: the lane of the box's world, or PAPER when that lane is not armed.
- A REAL ticket ends on a **REAL MONEY** panel that asks for the PIN a second time.
- A DEMO ticket asks for the PIN once, as today. PAPER asks for none.

**Selectable** (`accounts_for`): both switches ON, the keys present, the lane armed with its pin, and its world's cells fresh. Otherwise the other world stays listed with its reason, for example "both eToro worlds side by side need the real-only limits ON".

**The second PIN, step by step:**
1. The dialog's **TAKE TRADE · REAL MONEY** posts the order with the PIN, as today.
2. The server checks the PIN at the ACT door (`dashboard/views.py:5185-5190, 5769-5772`; counted) and runs the full preview on the REAL lane. It answers `{"confirm_real": {"nonce", "summary"}}` and **sends nothing**.
3. The dialog shows the final REAL MONEY panel: the account, symbol, side, quantity, stop, target and leverage as the server judged them. The words are: "Real money at eToro. Type your PIN again to send."
4. The second post carries the nonce and the PIN.
5. The server checks the PIN again (counted), then the nonce:
   - one use;
   - at most 120 s old;
   - bound to the user, the account key, symbol, side, quantity, stop, target, leverage and the preview's fingerprint;
   - kept in the cache. With no cache, REAL is refused: it fails closed.
6. Only then does it take the lock. Under the lock (`manual_trade.py:3181-3188`) the locked lane's pin decides. **REAL needs both the nonce and the second PIN verdict**, so a ticket that started DEMO cannot finish REAL on one PIN.

Five wrong PINs sign the session out, as today. The nonce never carries money.

**Also:**
- C3's words per world, and the success alert names the account.
- `dup_seen`, `shown_qty` and `shown_raised` reset on an account change (C3).
- The Council brief argues the chosen account (C3).

**Files:**
- `bot_program/accounts.py`;
- `dashboard/views.py` (the two ticket executes, 5159-5218 and 5753-5793; `_parse_trade_body` 5234-5357 for `real_nonce`);
- `bot_program/manual_trade.py` (3181-3188);
- `templates/base.html` (`sizeDialog` and the REAL panel; `tradeFlow` 3514-3949);
- `dashboard/ticket_outcome.py` (the record notes the confirm step);
- `tests/test_real_second_pin.py`.

**Tests written first** (`tests/test_real_second_pin.py`):
1. A REAL ticket with one PIN is refused with "confirm on the REAL MONEY panel", and `market_order` is never called.
2. A nonce that is stale, replayed, belongs to another user, or carries a different quantity, stop, target or leverage is refused. A nonce for quantity 1,000 cannot send 2,000.
3. Under the lock, REAL is refused without the nonce even when the preview said DEMO.
4. DEMO keeps one PIN; PAPER needs none; five wrong PINs sign out.
5. With no cache, REAL is refused.
6. A DEMO ticket and a REAL ticket on the same symbol, back to back, with L ON:
   - neither refuses the other;
   - each books its own world (stamps);
   - each closes in its own world;
   - the kill switch flattens both, each in its world.
7. No money appears in the choice or the panel's markup for a non-staff user.
8. Dialog source assertions: the REAL panel exists and its words are present.

**Acceptance (measured, on his server):**
- His first REAL ticket through the REAL lane is at the smallest size (#93's floor), confirmed twice, and its row is stamped live.
- His first DEMO ticket is taken while the bots trade real, and its row is stamped demo.
- Each closes in its own world from the CLOSE button.
- The ticket record shows the confirm step.

**Size:** M.

### 8.4 Money direction, C4c ON (needs L3 ON)

**Looser: allowed sooner.**
1. **A REAL ticket while the bots trade demo.** It can be taken with the Demo box ticked. Today no real eToro order is possible while Demo is ticked.
2. **A DEMO ticket while the bots trade real.** It can be taken with the box unticked.
3. **Cash is charged per world.** A demo order is never charged against real cash, and real orders never against demo cash (`_pledged_since` per world). Today only one world trades at a time, so no such charge happens.
4. **The REAL lane's pool follows the real equity.** With Demo ticked, today the broker lane's pool follows the demo equity and the lane trades demo. Afterwards the REAL lane follows the real equity and trades real money.

**Tighter.**
1. REAL tickets ask for the PIN twice.
2. The REAL lane's arming needs the PIN, a second confirmation and a fresh real reading.
3. The cash gate judges each order on its own world's cells: a REAL order never passes on demo cells.
4. A real-world pool is never sized from the demo equity.
5. Demo requests can no longer take real orders' room in the request budget (C4a).
6. Ticking Demo is refused while the REAL lane holds a real position.

**Bots: unchanged.** They keep the Demo box's world (D3).

### 8.5 Conflicts and order

- C4a can run parallel to C3 after W0. It comes after usedfix U3 if U3 lands first (`etoro_used`).
- C4b comes after C3, C4a and L2. C4c comes after C4b. **C4c's switch needs L3 ON.**
- **The feed:**
  - F2b's 429 rule and C4a's budget change share `etoro_budget.py`; the second to land rebases.
  - F4's `/pnl` reads (real at most 6 a minute, demo at most 2) are per world, which is consistent with C4a's cells.
  - F12's private stream joins per world.
- **The Bettor:** commit 1 (the eToro free-cash rail) reads the cells per world after C4a.
- **Orders at a price:** resting orders carry their lane's pin.
- **S2.1:** rebases on C4c's panel ("UI yields to money work").

---

## 9. C5 · The remaining world filters

**Goal.** The second edition's display leftovers, minus what OC0 did and OC1 will do.

**He will see:**
- `/positions/` and `/portfolio/` filter by world (REAL | DEMO | PAPER). Today their VENUE filter's "live" includes demo (`dashboard/position_views.py:66, 131`).
- `/eye/fills/` filters by world (`?world=` instead of `?mode=live`).
- The Treasury says "n REAL" instead of "n LIVE" where it counts real money.
- `manage.py scorecard --world live|demo|paper` replaces `--venue live`, which stays as an alias with a deprecation line.
- The capital pools say "FOREX REAL" and All Books says "REAL", from `config_world`.

**Withdrawn from the second edition's C4b:**
- the armed pill and the BOTS tab (OC0);
- the OC LIVE tab's name (OC1 removes the tabs);
- the strip's ENGAGED and FREE (C1).

**Files:** `dashboard/position_views.py`, the two templates, `dashboard/views_eye.py` (the fills view), `templates/dashboard/treasury.html`, the scorecard command, and the pool words.

**Tests written first:**
- One per surface: a demo row appears only under DEMO, and the REAL filter's rows equal `_world_filter(qs, "live")`.
- The alias still works.

**Acceptance:**
- Screenshots per surface at 1280 and 390.
- Query counts are unchanged or lower.

**Conflicts:** U3 edits `treasury.html` (C5 rebases). S2.2 (positions) and S2.4 (portfolio) rebase in whichever order they land.

**Money direction:** display only.

**Size:** M.

---

## 10. The money line of each commit (house rule: said plainly)

| Commit | The line |
|---|---|
| W0 | "Money: none. Display: a close with no exit price reads 'not measured' on /command/ and /eye/ instead of 0.00." |
| C1 | "Money: display only. risk_gate.py, base.py, manual_trade.py and broker_router.py are not in this diff." |
| C2 | "Money: display only." |
| C3 | "Money: tightens. New refusals, all before anything is sent: route mismatch, unreadable client world, lane changed mode, eToro proof gap at preview, facts seen on another account. Never escalates. Looser, named: (1) each new paper lane's capital joins the paper desk budget (paper only); (2) a paper hand ticket's P&L moves the platform book, the real-money limits' denominator when the broker reading is missing or older than 2 h: a paper gain loosens it, a paper loss tightens it; (3) a PAPER ticket no longer shows real-money limit warnings." |
| L1 | "Money: neutral. Stores one book value per world beside today's; no gate reads them." |
| L2 | "Money: neutral while real_only_limits_live is OFF (verdicts byte-identical, pinned). When ON, looser for real money: open risk, exposure, notional, the daily day and the elite mode stop counting demo; real entries are no longer halved by a demo loss nor tapered by demo correlation (larger); a demo holding stops refusing a real entry, bot or ticket; a config's slots and day, the capital desk's book risk and Morgul's own checks count real only; rows left in the other world stop holding real room; the fallback denominator without paper P&L (looser while paper loses) and, in demo mode, the real fallback instead of the demo equity (looser when the demo equity is smaller). Tighter: demo gains stop offsetting real losses; legacy Main-book rows are no longer skipped behind a demo row; the fallback loses the demo notional; the desk's live budget loses demo-routed configs; the ticket's daily-loss warning fires sooner. Demo meets its own limits against the demo account." |
| C4a | "Money: neutral for real-money orders, limits and sizes. Demo rows in the other world become managed and closable in their own world; up to 2 more account reads a minute per account at P2; demo requests can no longer take real orders' room; a 429 in either world pauses both worlds' background reads." |
| C4b | "Money: neutral while etoro_two_worlds_live is OFF (today's client on every path, pinned). The arming ceremony and the tick guard only refuse more." |
| C4c | "Money (switch ON, needs real_only_limits_live ON): looser: a REAL ticket while the bots trade demo, a DEMO ticket while they trade real; cash charged per world; the REAL lane's pool follows the real equity. Tighter: REAL asks the PIN twice; the REAL lane's arming needs a second confirmation and a fresh real reading; each order judged on its own world's cells; no real pool sized from demo equity. Bots unchanged." |
| C5 | "Money: display only." |

---

## 11. Asks of the other plans (each owner decides)

- **The Oculus.** The desk sentence (`oculus.py:1002, 1059`) credits "C1–C3 (real-only limits, planned)". The work is L's, and L2 rewrites the sentence (its file list).
- **Operations Center.** The OC spec §9 asks C1–C3 to word the close dialog for DEMO, and C1 does it. Its line "C1–C3 … change the gate's live side" now belongs to L: C1–C3 change no gate.
- **S1b.** The status bar's OPEN P&L, REALISED 24H, ENGAGED and FREE read C1's per-world keys. PLATFORM BOOK wears OC0's words.
- **The Bettor.** Its "Live/paper apart C1-C3" dependency (commit 21 and later) becomes **L3 ON and C4a**. Its rails read W0's world rule and L1's per-world book values. Commit 14 comes after L2.
- **The feed (F4, F12).** Per-world reads match C4a's cells and keys.
- **Orders at a price.** A resting order is filed on its account's lane and carries the pin.

---

## 12. Risks

- **The shadow's volume.** `can_open_new` runs per config per tick. That is why it is recorded only when the two rules disagree (deduplicated hourly) and tallied otherwise. Entries and tickets are always recorded.
- **Golden answers at `15dd487`.** Test 1 of L2 records the binding answers on a fixed fixture. A later merge that changes a gate legitimately must re-record them in its own commit, with its reason.
- **Two lanes on one key pair.** A wrong `env` is one bug away from real money. Four guards stand in front of it:
  - the pinned clients refuse the other segment on the wire;
  - `close_or_refuse` keeps its world check;
  - the cash gate compares the cells' world with the order's;
  - the second PIN shows the final order before it is sent.
- **The tick guard (C4b) can keep the bots off demo** while he holds REAL hand positions. That is the safe default; D3 revisits it.
- **`base.html` churn.** C1, C3, C4c, S1b and S2.1 all edit it. The UI plan yields to money work; C1 limits itself to the strip keys if S1b goes first.

---

## Appendix A. Line map: second edition (`dbfe0a9`) to `15dd487`

Unchanged lines are not repeated. These sections of the second edition stand at these lines:
- **`dashboard/horde.py`:**
  - SIDE_LABELS 217→228, DEMO_NOTE 222→233, GATE_EXTRA 223→234;
  - `_head_raw` 760-783→818-841 (gate quotes 830-833; now `capital_summary(user, shared=_shared_switch())`);
  - `_bot_seat` 1197-1199→1270-1272, `_ccy` 1344→1419, `_legacy_seat` 1360-1386→1435-1461, `_book_sizes` 1465-1475→1540-1550;
  - `_line` 1549-1577→1624-1652, `_groups` 1610-1660→1685-1735 (share and band 1703-1725), `_stragglers` 1663-1673→1738-1748, `_unseated` 1700-1772→1775-1847 (`env_label` at 1786);
  - `_head` 1865-1965→1940-2050 (loop 1944, live side 1954-1958, shared-pool note 2012, eToro cell 2018-2022, MARKS 2023-2043);
  - `_tab_of` 1999-2059→2085-2145 (demo side 2097-2106).
- **`static/js/sv-horde.js`:**
  - Unchanged: 49, 51, 188, 203-205, 602-628, 698-706, 710, 711-714, 715-747, 752-813, 845-854, 874-876.
  - Moved: `paintTable` 855-921→855-933 (eToro cell 901-912), `groupBand` 1117-1191→1135-1209 (pills 1139-1141), arrows 1266-1276→1284-1294.
- **Horde templates and CSS:** `the_horde.html:58-64` unchanged (eToro cell at 115); `sv-horde.css` 164-167, 593-684, 622, 632-634, 681 and 686-700 unchanged.
- **`templates/base.html`:**
  - sidebar 489-491→496-498, PORTFOLIO 883→890, POOLS 906-908→913-915, ENGAGED and FREE 915-918→937-940, 920→942, REALISED 24H 929→951, 969→991;
  - OPEN P&L 1034-1048→1058-1073 (sub-line 1062), BOT 24H P&L 1094→1119, Horde 1583-1584→1678-1679;
  - `sizeDialog` 1931→2298, Venue fact 2172→2670, `tradeFlow` 2859-2965→3514-3949, refused 2868-2872→3523-3527, relever 2881-2889→3536-3544, success 2949→3641;
  - `svTakeTrade` 2966-2976→3950-3960, `svTakeTradeAsset` 2977-2981→3961-3965, close dialog 4048, tour 7231→8582.
- **`dashboard/views.py`:**
  - monthly 3094-3120→3278-3304, HQ arm card 4224-4253→4477-4520;
  - `instrument_detail` 4755-4775→5063-5083 (lane mode 5073-5082), `take_trade_preview` 4805-4820→5114-5129, `_preview_leverage` 4823→5132;
  - `take_trade_execute` 4850-4897→5159-5218 (PIN 5185-5190), `_parse_trade_body` 4913-5004→5234-5357;
  - `asset_trade_preview` 5271-5287→5734-5750, `asset_trade_execute` 5290-5323→5753-5793 (PIN 5769-5772).
- **`bot_program/manual_trade.py`:**
  - `manual_config_for` 277-291→330-344, `manual_config_if_any` 318-332→371-385, `venue_health_advisory` 1017-1031→1204-1218;
  - `_preview` 1307-1971→1687-2511 (lane 1731, book advisory 1743-1766, market shut 1775-1780, client 1786, `live` 1796, no paper fallback 1797-1804);
  - venue calls 1581→2051, 1599→2074, 1607→2081, 1621→2095, 1943→2483;
  - entry points 1974-1992→2514-2535, `_execute` 1995→2874 (lane 2942), lock 2209-2238→3172-3200, broker leg 2624→3457 (fallback refusal 3457-3464), theme 2433→3236;
  - execute wrappers 3001-3028→3917-3951;
  - The duplicate check at 2429 moved to `_judge_ticket` (2836-2837) and before the live order (3468-3469, `paper=False`).
- **`portfolio/risk_gate.py`:**
  - `gate_book_value` 285-335 unchanged, `LIVE_EQUITY_MAX_AGE_S` 340→341, `venue_book_value` 343-372→344-373;
  - live branch 537-542→538-543, 678-683→679-684, `open_risk_state` rows 887-889→888-890, notional 1106→1106-1107, `_one_venue` 1402-1414→1403-1415.
- **`portfolio/services.py`:**
  - pools 367-373→390-409 (`mode_pool` 403-409), 397-451→436-507 (ENGAGED 437), totals 428-430→482-488;
  - `_simulated_realized_pnl` 779→837, `live_book_value` 910-927→968-986 (funded 979-982).
- **`bot_program/capital_truth.py`:** `broker_backed` 202-254→326-378, `broker_env` 302-316→426-440, `equity_drawdown` 796-830→921-954; `account_equity` is at 450-475.
- **`core/context_processors.py`:** 466-490→598-622, 531-533→663-665, 728-746→860-878, 929-939→1061-1071.
- **`static/css/sauron.css`:** `.sv-world` 2395-2421→2424-2450.
- **Tests:**
  - `tests/test_the_horde.py`: 502-509 and 752-772 unchanged; the rest +32 (1975→2007, 2036-2041→2068-2073, 2105-2106→2137-2138, 2569-2578→2601-2610, 2580-2593→2612-2625, 2595-2608→2627-2640, 2841-2851→2873-2883, 3087-3089→3119-3121); the warm board test is at 1345.
  - `tests/test_capital_truth.py:224` and `tests/test_bot_charts.py:24-31` are unchanged.
- **Other templates:**
  - Moved: `portfolio_overview.html` 132→149, `chart_widget.html` 717→799.
  - Unchanged: `_command_portfolio.html:51` (81 in OC0, titled "the platform book"), `_command_history.html:113`.

The full mechanical map of every one of the second edition's 239 references is `worlds/v3/refmap_out.txt`. The 21 bare `(:NNN)` references assigned to the wrong file are in `worlds/v3/refmap_fixed_out.txt`.

## Appendix B. Withdrawn or corrected from the second edition

| Second edition | Now |
|---|---|
| §1: "the equity cell carries no world stamp" | It does (`last_margin_world`). The conclusion holds, because `account_equity` checks no world and `venue_book_value` reads it (1.4). |
| §1: "`_preview` has three callers" | Five call sites (1.4, 6) |
| §5.3: "the 8 readers" | Ten (6, item 1) |
| §3.5: LIVE ENGAGED and LIVE FREE are both config mode | Only FREE is. ENGAGED is per row world, and demo lands in PAPER ENGAGED (4) |
| §3.6 test 14 "test_a_warm_board_still_costs_10" | `test_a_warm_board_costs_the_same_for_3_and_30_seats` (1345) |
| §3.3 `world_q` | W0's `world_case` |
| §3.5: the Eye fix; the OC LIVE tab's markers | OC0 |
| §3.5 and §7 C4b: rename the OC LIVE tab | OC1 removes the tabs |
| §7 D1 list | Adds `open_risk_state`, `capital_desk.book_risk`, the desk's live budget, the per-config checks and Morgul's own reader (7.3) |
| §7 D1/D4: "approval" | Approved, as a shadow-first stage behind `real_only_limits_live` (7) |
| §7 D2 "needs decisions D2 and D3" | D2 approved with the second PIN (8). D3 still open |
| §1: the 2-hour fallback is "eight missed syncs" | 120 missed syncs (the sync runs every 60 s) |
| §5.4 `_execute` broker leg "2429 dedupe" | `_judge_ticket` (2836-2837) and before the live order (3468-3469) |
| §0.8: "Choosing eToro DEMO and eToro REAL side by side … is C4 … C3 prepares it and does not fake it" | Unchanged for C3. C4 is now specified (8) |
