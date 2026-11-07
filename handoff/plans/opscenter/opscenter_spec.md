# The Operations Center as his desk and home: spec

Spec, 2026-11-07, revised the same day after two critiques (the truth and money-safety critique in `scratchpad/opscenter/critique_truth/`, and the usefulness and consistency critique). `scratchpad/opscenter/changes.md` lists each finding, applied or rejected, and why.

It reads `main` at `ede54d0` (PR #95 merged), through the scratch copy `scratchpad/opscenter/app` (git archive of `ede54d0`, SQLite, synthetic fixture only). It also reads, without touching them, three branches in flight: `claude/oculus0` (Oculus O0), `claude/uis1a` (S1a, at `b37cde1`) and `claude/feedf1` (feed F1).

Inputs:
- the Operations Center map (`scratchpad/opscenter/`: shots, `tools/report_*.json`, `tools/profile_*.json`, the scale runs);
- the Oculus proposal (`scratchpad/oculus/oculus_spec.md`, `oculus_fr.md`, the mock), whose block order he approved on 2026-11-07;
- the approved UI plan (`scratchpad/uiplan/ui_plan_spec.md`: palette §3, type §4, density §5, kit §7, motion §8, money controls §10, live hooks §11, stage S2.3) and its preview boards (`scratchpad/preview/project/*.dc.html`);
- the eToro feed spec (`scratchpad/feed/etoro_feed_spec.md`: F4 eToro's own P&L, F6 the feed, F7 the same grade on screen).

This is a plan. Nothing is built here, and nothing in any worktree was written.

**The mock.** A static mock of the page after OC2 and before F4 sits at `scratchpad/opscenter/opscenter_mock.html`. It uses synthetic data, is 1,440 px wide, and is drawn in the S1b shell on S1a's 1,280–1,679 px tokens: Inter and JetBrains Mono, rows of 44, 32 and 28 px, 40 px card heads, 20 px figures, 13 px status values. It is built by `scratchpad/opscenter/design/tools/mock_build.py`, which computes every figure from one table of rows, closes and counts, and refuses to write the page when they disagree: each world card must equal its rows, the windows must nest (since you last looked ⊂ today ⊂ 24 h), the alarms must equal the Horde's, and every dash drawn must be listed in "How to read this page". It is rendered offline by `scratchpad/opscenter/design/tools/mock_shot.js`:
- `shots/mock_1440x900_first.png` is the first screen;
- `shots/mock_1440_full.png` is the whole page (3,555 px).

The render measured 871 text nodes, none under 11 px, no horizontal overflow, nothing clipped and no text cut. A dashed line marks where the first screen at 1,440 × 900 ends. The clock reads 12:53:20 UTC on a weekday: US CPI prints at 13:30 UTC (winter time), 37 min away, and New York's cash session opens at 14:30 UTC, so AAPL is shut. Before F4, every open P&L is an estimate and says which price it used.

**The house line.** Every stage is one pull request that changes display only. The engine, the bots, the Orcs, the gates, the desk, the ticket, the close dialog and every money switch see exactly what they see today. Every commit message says "Money direction: none. Display only."
- Two display changes reach shared code, and each is listed where it lands: OC0 splits the shell's `_bot_truth` by account world (the armed pill's count), and OC2 adds fields to the Horde's seat.
- The few changes that are not display are listed apart in §6.4, each waiting for his OK.
- §6.3 lists every place a stage touches a money control, or a module that hosts a money path.

---

## 0. In one page

**What the Operations Center becomes.** Today it is four tabs under a hero and a 1,628 px "A DAY OF SAURON" section, so the trading content starts two screens down (tabs at y=2,023 at 1,440 × 900). Several of its money figures add REAL, DEMO and PAPER together, one prints a DEMO row as REAL MONEY, and the armed pill counts bots on a DEMO account as real money. It becomes his desk, on one page, in this order:

1. **The hero row.** One row answers:
   - which positions need him (the Horde's alarms, with its watch lights beside);
   - what eToro holds for him (equity and available cash, eToro's own, with their age);
   - the next event and how many positions it touches;
   - how many signals are on the rail, and how many touch what he holds;
   - the brain's regime, with its age;
   - the Oculus's BEAT, with a link to the Oculus;
   - how old the money reading is.
2. **Three worlds, never added.** REAL, DEMO and PAPER side by side. Each card is the sum of its rows below and shows:
   - the open P&L in its tier's words (an estimate says so and names its price);
   - open R and the risk at the stops;
   - what it realized in 24 h, and how that was booked;
   - its account line. For REAL that is eToro's own account P&L and margin, and what eToro holds outside Sauron's rows.

   One line under the cards says what happened since he last looked.
3. **Positions.** One table for the whole book: real money first, then the newest, in an order that holds while he looks.
   - The Horde's light and words sit in place on each row.
   - A close Sauron gave up on is a row of its own.
   - What eToro holds outside Sauron is listed under the table.
   - CLOSE stays in a sticky right column: the same dialog, steps and PIN as today.
4. **The market on what he holds and watches**, beside **signals to act on**.
   - The market: events ahead by the care's own rule, the day change and news on what he holds, his starred instruments, and the brain.
   - The signals: the rail's own list. A click opens the card in the rail, where TAKE TRADE and PASS already live.
5. **Bots and Orcs**, beside **since you last looked**.
   - Bots and Orcs: the program's state, each world's 24 h, the exposure caps' refusals, each bot's health from its own tick, and the Orcs on watch with their shadow intents.
   - Since you last looked: trades, alerts and refusals since his last visit.
6. **The cycle.** The seven stages the Oculus speaks, as one strip. Each tile opens its stage on the Oculus. For a trader it is question 8 of 9, so it comes after the desk.
7. **Below, on demand:**
   - Review: performance by world and window, history and bots, with the platform book in its own box;
   - the loop, drawn and folded;
   - how to read the page, with every dash named.

**The stages.**

| Stage | One PR | What he will see | Starts when |
|---|---|---|---|
| OC0 | Truth and cost, today's look | DEMO no longer printed as REAL MONEY, and the armed pill no longer counts DEMO-account bots; money never added across worlds (three lines in the hero, REAL-first tab heads, avg win, avg loss, profit factor and P&L by class per world); "PORTFOLIO VALUE" named for what it is, with eToro's line beside it at today's size; "profit factor" computed as gross wins over gross losses; every money cell with two decimals and its currency; windows and ages printed; dashes named; CLOSE never scrolled off; the bot buttons hidden from those they refuse; the page's own poll stops holding the session open; 60 to 90 % fewer queries per tab and a PORTFOLIO tab six times faster | Now; needs no approval (like S0 and O0) |
| OC1 | The look, and the order | The same facts on S1a's kit, in the new order: hero row, three worlds, one positions table in a stable order, the cycle strip, then Review; eToro's figures first and larger; the loop folded at the foot by default; nothing under 11 px; refresh by small server-rendered parts | S1a merged; supersedes UI plan S2.3 (§8, OC1) |
| OC2 | The desk | The Horde's lights and words on every row, the close given up, and what eToro holds outside Sauron; NEEDS YOU from the Horde's alarms; the market, signals to act on, bots and Orcs, and since you last looked | OC1; P2 (his OK) for "since you last looked", otherwise the last 24 h |
| OC3 | Feed-grade live | eToro's own P&L on REAL rows about every 11 s while a held market is open, and on DEMO rows about every 30 s (F4's own cadence); prices and badges pushed (F7); the desk's poll halved | F4, then F7 |

**The boundary with the Oculus, in three lines.**
1. The Oculus answers "is the machine turning, and is my money protected": guards, stops at eToro, the kill switch, the request budget, feeds, AI spend, tasks. The Operations Center answers "what is my money doing, and what should I do now".
2. Both speak one vocabulary, from the same readers: the seven stages from `day_live_payload`, the Horde's lights for each position, and the band's worlds. The home shows one strip, a BEAT cell named and worded like the Oculus's, and a POSITIONS · NEED YOU cell that links to the Oculus's Needs you. It never shows task lists, guard rows, budgets or feeds.
3. Money actions stay where they are today: CLOSE and RETRY CLOSE on the home's positions, TAKE TRADE through the rail's card. The Oculus stays display-only and links to the pages that act.

**What we need from him** (the French note asks it):
1. OK on the order of the blocks (§3.1).
2. OK that eToro's own figures lead the page, first and larger, and that "PORTFOLIO VALUE" (the platform book) moves to Review, in a box of its own, with its explanation.
3. OK that the loop drawing, THE BEAT and the 24-hour strip fold at the foot, closed by default.
4. OK that the four tabs become one page: LIVE spread over the regions, and PORTFOLIO, HISTORY and BOTS under Review. Old `?tab=` links keep working.
5. P2: OK to remember when he last looked at the home, in the same map as the menu's dots, for "since you last looked". Without it, the block shows the last 24 h.
6. P1: OK that the bots' "Toggle" and "▶ Tick" leave the home page. They stay on the bots page and in Admin HQ.

---

## 1. Inputs and constraints

**His words (2026-11-07, verbatim):** "Do the same for the opération center please", after the Oculus proposal. This sits within the UI plan's orders: "un smart melange de bloomberg et trading view sous sauron", "sombre, surtout sur ordinateur, dessins en dernier". The Operations Center is his home (`/` redirects to it, `dashboard/views.py:32-38`), and he trades from it with the rail and the instrument ticket.

**What the map measured, and where each finding is fixed:**

| Finding (map §) | Evidence | Fixed in |
|---|---|---|
| A DEMO row printed REAL MONEY (0.1, 5.1) | `views_eye.py:146-165` builds a dict without `metadata` or `world`; `_world_key` (`sauron_tags.py:552`) then reads it as live | OC0 |
| Bots on a DEMO account counted as real money (critique) | `_bot_truth` counts every enabled `mode == "live"` config as armed with real funds (`core/context_processors.py:712, 832-834`), and the topbar pill prints that count (`templates/base.html:642-647`). A config's world is the flag of the account its symbols route to (`bot_program/engine/broker_router.py:243-299`) | OC0 |
| Worlds added (0.2, 5.2) | Tab heads ("11 OPEN +198.31"), the PORTFOLIO strip, its lifetime avg win, avg loss and profit factor, the 24 h and 90 d stats, the Eye's "P&L by asset class" (summed over every world and printed as a percentage of the limits book, `views_eye.py:326-375`, `_eye_body.html:203-215`), DEPLOYED 34,481 with paper's 21.7k, ACT "open now, live money" (`views_day.py:522` counts `paper=False`, DEMO included). The band beside them splits LIVE +18.86, PAPER +163.50, DEMO +0.05 | OC0 (split and labelled), OC1 (the worlds row) |
| PORTFOLIO VALUE is no balance (0.3, 5.3) | Typed /setup/ cash in EUR, plus the REAL and DEMO notional in USD (hand-recorded rows too), plus paper's open and realized P&L, never converted (`portfolio/services.py:910-986`). 17,572.85 EUR beside eToro's 10,453.61 USD | OC0 (named), OC1 (eToro's own leads; the book moves to Review, in its own box) |
| "Profit factor" is a payoff ratio (critique, traced here) | `views_command.py:836` divides the average win by the average loss | OC0 |
| Trading content two screens down (0.4, 6.7) | Tabs at y=2,023 (1440), 1,949 (1280), 1,514 (1920) | OC1 |
| Hero "· 24h" a dash until 23:30 UTC (0.5, 5.4) | Today's snapshot only (`views_command.py:405-416`), written at 23:30 (`celery.py:357-359`) | OC0 (named, with yesterday's dated), OC1 (leaves the hero; P5 would give eToro's own) |
| CLOSE scrolled off and a red slab (0.6) | 918 px table in a 486 px card at 1440; `btn-danger` gradient (§10 forbids) | OC0 (sticky column), S1a (neutral `.btn-danger`), OC1 (the kit's CLOSE) |
| Bot buttons for everyone (0.7) | "Toggle"/"▶ Tick" rendered for non-superusers, who get a 403; Tick runs a tick inside the request | OC0 (hidden where refused), P1 (off the home) |
| The idle lock polls more, and the page holds the session open (0.8) | 20.8 requests/min locked against 12.7 visible. The metrics poll sends no `X-Requested-With` and is not under `/api/`, so `_is_human` counts it and stamps the session every 45 s: the server's idle backstop never fires while /command/ is visible (`command.html:414`; `core/idle_lock.py:89-104, 132, 152-165`) | OC0 (the page's own poll), P4 (the shell's) |
| Fragments pay for the shell (0.9) | About 74 queries of context processors per fragment; PORTFOLIO reads 20,181 closed rows (937 ms at six months) | OC0 |
| Readability (0.10, 6) | 36–54 % of text under 11 px; 221 of 578 nodes under 4.5:1; 30 ellipses at 1280 rail open; ring text at 6.2–9.9 px; 8-decimal quantities; the CSS rendered twice | OC0 (numbers, CSS twice), OC1 (the rest) |
| Stale shown as fresh (5.5) | "Auto-refresh every 10s" false on /command/; regime and trust without age; "last" without source; undated drawdown and gate times | OC0 |
| P&L words (5.6) | Tier 1 prints only a title; tiers 2–3 print "yfinance_public"; the LIVE head's title says "eToro's own" over a sum with paper marks | OC0 (words), OC1 (S1a's `src_name`) |
| Money without currency, truncation, windows (5.7–5.9) | DEPLOYED `floatformat:0`, head `,.0f`, prices `floatformat:4`; three win rates with no window | OC0 |
| The same quantity disagreeing (5.10) | OPEN POS 11 vs 10; Active bots 8 vs ENABLED 5; ALIVE 6H 6 > ENABLED 5; GATE 24H 12 vs DECIDE 2 | OC0 |
| Eight meanings of "—"; zeros meaning none (5.11, 5.12) | No meaning printed | OC0 (titles and a footer), OC1 (R11) |
| World from the bot's mode, health from trades (5.13, 5.14) | `{% money_world cfg.mode %}` reads REAL for a demo account; ALIVE from trades in 6 h, not `extras.last_tick_at` | OC0 |
| Colour (5.15) | −0.004R the darkest red; heads flash Eye green on a loss | OC0 |
| ACT contradicts itself (5.16) | "OFF · switched off" beside "9 trades opened today" | OC0 (words) |
| Overlap with the Oculus; missing exits (5.17) | The ring is the Oculus R3 on the same payload; no link to the Oculus, the kill switch, CLOSE ALL or /brokers/ | OC0 (links), OC1 (the ring folds) |

**Work in flight that touches the Operations Center's inputs:**

| Branch or plan | State | What it means here |
|---|---|---|
| `claude/oculus0` (Oculus O0) | Pushed 2026-11-07; `dashboard/oculus.py`, `views_oculus.py`, `oculus.html`, `core/wall_facts.py`, RUNBOOK, tests | No /command/ file. RUNBOOK sections differ (trivial rebase) |
| Oculus O1, O2a, O2b, O3 | Spec approved; after S1a | The stage tile arrives with O2a's cycle map (Oculus spec R3), not with O1. OC1 lands first and creates `sv-stage.css`; O2a loads it (§3.4, §9). The Oculus's anchors (`#needs`, `#money`, `#prices`, `#stage-<key>`) exist after O2a; until then the home links to `/oculus/` |
| `claude/uis1a` (S1a) | Building | Tokens; the kit (`.sv-panel`, `.sv-kpi`, `.sv-pnl`, `.sv-table`, `.sv-chip`, `.sv-state`, `.sv-fresh`, `.sv-src`, `.sv-est`, `.sv-world`, `.sv-tabs`, `.sv-seg`, `.sv-notice`); the filters `qty` and `src_name`; a neutral `.btn-danger`. Its `.sv-table` has a sticky header only, with no sticky action column and no column priorities (`sv-kit.css:872-886`), and there is no NO VENUE chip: OC1 adds both (§3.4). Its `tests/test_live_hooks_inventory.py` pins hook counts per /command/ file (§6.2). OC1 waits for it |
| S1b (shell) | After railfilters and pnltruth (both merged) | First content at y≈92, the 32 px status bar (PORTFOLIO, OPEN P&L, POSITIONS, SIGNALS, BOT, ALERTS, DRAWDOWN, HORDE), Gollum, the Eye and the Horde docked. The mock draws that status bar with the two proposals of §9. OC1 measures its overlap acceptance after S1b |
| PR #89 (pnltruth) | Merged `8be4725` | `venue_pnls`, `shown_open_rows`, `shown_book`, the tiers `etoro`, `etoro_quote`, `estimate` and their words (`portfolio/services.py:1040-1042`, 1280-1345). Tier 1 reads `netProfit` from eToro's holdings list, a key the client stores but calls unmeasured on this account (`bot_program/engine/etoro_client.py:2939-2958`), and the feed spec expects it empty until F4. Tier 2 reaches only the instruments of open REAL rows that are not stand-ins (`bot_program/etoro_quotes.py:19-32`) |
| PR #90 (railfilters) | Merged `795a40b` | `dashboard/signal_rail.py` (`rail_snapshot`, memoised per request), `window.svRailFocus` (`base.html:1935`), `RailDeparture` |
| PR #94 (ticketnet) | Merged `e5ef5c8` | The ticket's lost-answer lookup. Untouched here |
| PR #95 (etbudget) | Merged `ede54d0` | eToro quotes every 30 s, the account sync every 60 s. The desk part's 30 s cadence follows them |
| `claude/feedf1` (F1) → F4, F6, F7 | F1 building; F4 after M3a | F4 reads eToro's own P&L for REAL about every 11 s while a held market is open (60 s when every held market is shut) and for DEMO about every 30 s while a DEMO row is open (feed spec §4.7.1). F4's file list edits `_command_portfolio.html`, which OC1 retires (§9). F7: the venue push, `sv-venue.js`, the "live prices paused" chip. OC3 listens to them and owns none of them |
| Worlds C1–C3 | He said yes; not built | The desk and the gate stop counting DEMO as live. The home never prints the gate's live side, so nothing here waits for them. The close dialog's "This flattens a LIVE position at the broker" on a DEMO row (`manual_close.py:412`) is theirs to word (§9) |
| The Orcs (O2a, O2b) | Merged; he turned the minds ON on 2026-11-07 | Every O2 intent is `shadow` or `refused` by construction (`bot_program/orcs/constants.py:440-443`). `Orc.latest_note` is the mind's own text (`orcs/mind.py:968-972`); the Horde shows Orc lines only through its plain words (`_orc_plain`, `dashboard/horde.py:485`) |

**House rules that bind every stage:**
- Display only, except the proposals of §6.4, each behind his OK.
- No broker call and no model call to draw the page. Tests prove it (§6.5). The CLOSE preview's own read of eToro's rate (`manual_close.py:362`) is the dialog's, unchanged, and is not made by the page.
- Never weaken a test. A test that pins a look is updated to the new look with the reason in the commit; a test that pins a meaning is kept.
- Every query budget is asserted cold, after `cache.clear()`, and measured on the scratch harness at six months.
- Synthetic data only in fixtures, screenshots, mocks and tests. The repository is public.
- Faces from Google Fonts only (Inter, JetBrains Mono; Orbitron for the wordmark). Tokens and components come from S1a.
- Staff and viewer stay apart exactly as today (§5.8).

---

## 2. The questions it answers at a glance, in priority order

The order is "my money, then what I must do, then what I could do, then the machine". Each question has a glance (a hero cell or a block's first line) and a depth (its block, or the page it links to).

| # | Question | At a glance | In depth | Who |
|---|---|---|---|---|
| 1 | What is my money doing, in each world? | EQUITY AT ETORO and AVAILABLE AT ETORO (eToro's own, with age) | R2: REAL, DEMO and PAPER apart, each the sum of its rows: open P&L with its words, open R and risk at the stops, realized 24 h with how it was booked, the account line | Each user, his own book |
| 2 | Which positions need me, and why? | POSITIONS · NEED YOU: `⨯ 2 alarms · 6 watch` | R3: every open row with the Horde's light and words in place; the close given up; what eToro holds outside Sauron | Own book |
| 3 | How is each position doing? | — | R3: mark with its source and age, P&L with its words, R now and the distance to the stop, who holds it | Own book |
| 4 | What is the market doing on what I hold and watch? | NEXT EVENT `US CPI 13:30 · in 37 min · touches 7 of 8`; REGIME `TRENDING · 2 h ago` | R5: events in the next 24 h by the care's rule, the day change and news on what he holds, his starred instruments, the brain's reading | All; the brain's concern text for staff |
| 5 | What can I act on now? | SIGNALS `13 · 3 on what you hold` | R6: the rail's cards on what he holds, voting now, new since he looked; a click opens the rail card | Own rail state |
| 6 | What did my bots and the Orcs do? | (status bar BOT) | R7: the program, each world's 24 h, the exposure caps' refusals, each bot's health from its tick, the Orcs on watch and their shadow intents | Own bots |
| 7 | What changed since I last looked? | The line under the worlds | R8: trades, alerts and refusals since his last look | Own events |
| 8 | Is the machine turning? | BEAT `▲ 2 late · Oculus ›` | R4: the seven stages; the depth is the Oculus | States for staff |
| 9 | How have I done? | — | R9 Review: performance, history and bots by world and window; the platform book apart | Own book |

**What it deliberately leaves to others, with the link that takes him there:**

| Left to | What | Link on the home |
|---|---|---|
| The Oculus | Machine health (stage task lists, components), Morgul's guards and the protection checklist, the kill switch's state and history, the eToro request budget and the 429 pause, feeds, AI spend, the forge, the slow cycles, the desk's own budgets | BEAT cell; each stage tile (`/oculus/#stage-<key>` after O2a); "The Oculus answers ›" under the worlds (`#money`); NEED YOU's title (`#needs`) |
| /positions/ | The full book with every column, CLOSE ALL with its "(whole book)" words, the analytics | "All on /positions/ ›", "Close all is on /positions/ ›" |
| The instrument page | The chart, the deal ticket (LONG/SHORT), news on the symbol | Every symbol |
| The rail | The signal cards, TAKE TRADE and PASS, the filters, "left the rail" | Every signal row (`svRailFocus`), "Open the rail ›" |
| /eye/ | The exposure caps by theme, currency and sector; the gate's last 30 decisions; the old crypto bot's open rows | "Exposure caps ›" in R7; R3's foot when an old crypto-bot row is open |
| /asset-bots/, Admin HQ, /ops/ | Bot on/off, Tick, platform switches and the brake | "Bots page ›", "Switches · /ops/ ›" |
| Admin HQ (superusers) | The kill switch form and its PIN (`admin_dashboard#flattenForm`) | "Kill switch, with your PIN ›" (superusers only) |
| /brokers/, /treasury/, /withdrawals/ | Keys and world, treasury, withdrawals | The REAL card's "outside Sauron's rows ›" (/treasury/), the footer links |
| The Activity drawer | Every event, routine pipeline lines included | "N more in the Activity drawer ›" (staff) |

---

## 3. The page, top to bottom

### 3.1 Wireframes

**1,440 × 900, S1b shell** (content 1,136 px; first content line at y≈92; status bar at y=868). The y values are the mock's.

```
+-------------+--------------------------------------------------------------------------------+----+
| [eye]SAURON | OPERATIONS CENTER  your desk...    12:53:20 UTC  6/14  ● eToro·live  [REAL ARMED] |    |
|             | EURUSD 1.08745 +0.12% ● | XAUUSD 2,661.30 -0.39% ● | ...        || News ...       | D  |
| AMON HEN    +--------------------------------------------------------------------------------+ O  |
|  Oculus     | POSITIONS·NEED YOU | EQUITY AT ETORO | AVAILABLE | NEXT EVENT | SIGNALS | REGIME | BEAT | MONEY READ |  y 92-144
| >Ops center | ⨯ 2 alarms         | $10,453.61 REAL | $5,955.11 | US CPI 13:30 | 13    | TRENDING | ▲ 2 late | 12 s |
|             +--------------------------------------------------------------------------------+ C  |
| THE BOOK    | [REAL] 3 open              | [DEMO] 2 open            | [PAPER] 2 open             | K  |  y 156-319
|  ...        | ≈ +$76.26 estimates        | ≈ +$66.90 eToro tick, 3m | ≈ +$6.60 Yahoo, 3 min      |    |
|             | +1.48R · $107.00 stops     | +1.38R · $117.08         | +0.43R · $37.00 (1 of 2)   |    |
|             | 24 h +$12.40 eToro's price | 24 h — nothing closed    | 24 h -$40.81 simulated     |    |
|             | eToro P&L +$96.40 · margin $4,402.10 · outside $1,150.00 in 2 | EURJPY apart, in JPY  |    |
|             | never added · MSFT in no world · the Oculus ›  /  since 09:42: 6 trades · 2 alerts ... |  y 331-366
|             +--------------------------------------------------------------------------------+    |
|             | POSITIONS · 8 open: 3 real · 2 demo · 2 paper · 1 no venue · 1 close given up · ⨯ 2 › |  y 378
|             | ⚠ EURUSD LONG REAL  1.08745  ≈ +$65.00  +1.25R  A high-impact print is near: ... [CLOSE] |
|             | ⨯ XAUUSD SHORT REAL ...  Closing: the broker refused the close...  [● CLOSING][RETRY CLOSE] |
|             | ⚠ AAPL · ⨯ USDCAD (close given up: Story ›) · ⚠ USDJPY · ⚠ NAS100 · ⚠ GBPUSD · ⚠ EURJPY |
|             | ○ MSFT NO VENUE ...  Nothing on the platform manages, trails or closes this position  —  |
| ---- first screen ends (y 868) ------------------------------------------------------------------ |
|             | AT ETORO, NOT ON SAURON · 2 (BTCUSD, ETHUSD) · All on /positions/ › · Close all ›     |
|             +---------------------------------------------+----------------------------------+ |
|             | THE MARKET ON WHAT YOU HOLD AND WATCH       | SIGNALS TO ACT ON · 13           | |  y 1012
|             | ahead 24 h · you hold 8 · you watch 4       | on what you hold 3 · voting 9    | |
|             | the brain                                   | +6 in the rail · left today 6    | |
|             +---------------------------------------------+----------------------------------+ |
|             | BOTS AND ORCS                               | SINCE YOU LAST LOOKED · 09:42    | |  y 1656
|             | program · each world 24 h · caps · bots     | 6 trades · 2 alerts · 5 refused  | |
|             | the Orcs · links                            | 8 lines · 7 more ›               | |
|             +--------------------------------------------------------------------------------+ |
|             | THE CYCLE · SEE ▲ | THINK ▲ | DECIDE ● | ACT ● | WATCH ● | TELL ● | LEARN ●      | |  y 2314
|             | REVIEW: PERFORMANCE | HISTORY | BOTS  [REAL|DEMO|PAPER] [24 h|30 d|90 d|lifetime] | |  y 2482
|             |   by world · then THE PLATFORM BOOK in its own box (all worlds)              | |
|             | ▸ THE LOOP, DRAWN (closed) · HOW TO READ THIS PAGE · THE DASHES · 16          | |
+-------------+--------------------------------------------------------------------------------+----+
| (G) PORTFOLIO 60,809.79 EUR+USD | OPEN P&L REAL ≈ +$76.26 DEMO ≈ +$66.90 PAPER ≈ +$6.60 | POSITIONS 8 | ... | HORDE ⨯ 2 |
```

The first screen at 1,440 × 900 holds the hero row, the three worlds, the two lines under them and the positions table up to nine rows (here eight positions and the close given up), with the "At eToro, not on Sauron" list at the fold. A longer book pushes the rest down. Past 12 rows, the rows fold in place, in the same order, under a disclosure that renders them (§R3). Machine health is question 8 for a trader, so its strip comes after the desk; the BEAT cell answers it at a glance, and the Oculus is one click away.

**In today's shell** (before S1b: first content at y=184, reading height 655), the first screen holds the hero row, the worlds and the first five or six rows. Today the first screen holds the hero and the top of A DAY OF SAURON, and no position at all: the first open-position row sits at about y = 3,280 on the LIVE tab.

**1,920 × 1,080 (S1b, content ≈ 1,600 px).**
- The hero row's cells widen; the worlds row gains a fourth card when a hand row exists ("NO VENUE · 1 · in no world").
- The positions table shows LEVELS (stop and target) and the row's mission ("Your ticket · signal #4113", "fixture live forex") as their own columns.
- Market (4 of 12), signals (4) and bots and Orcs (4) share one row; since you last looked (6) and the cycle (6) share the next; Review follows.

**2,560 × 1,440 (S1b, content ≈ 2,216 px, reading height 1,316).**
- Positions (8 of 12) and signals (4) share a row.
- Market, bots and Orcs, and since you last looked share the next (4 + 4 + 4).
- Everything but Review and the footer is on the first screen.

**1,280 × 800 with the rail open (S1b, content ≈ 836 px).** Every block reacts to its container (`container-type: inline-size`, UI plan §6.3), so the rail needs no page code:
- the hero row wraps to two rows of four cells;
- the worlds stay three across down to 760 px, then stack REAL first;
- the positions table keeps the light, POSITION, OPEN P&L, the Horde's words and CLOSE (`.sv-p1`); MARK and R NOW move under the P&L as its second line (`.sv-p2`, `.sv-p3`); CLOSE stays sticky on the right;
- R6 collapses to its counts while the rail is open beside it (the rail already shows the cards);
- the cycle tiles go 4 + 3 (container 760–1,099 px);
- the blocks below stack in one column.

**390 × 844 (phone; S3 owns the polish, the page must not break before it).**

```
+------------------------------------------+
| ☰  OPERATIONS CENTER   [REAL ARMED] (G)  |  topbar (phone tier)
| EURUSD 1.08745 +0.12% ●  XAUUSD ...  →   |  band (one row, swipe)
+------------------------------------------+
| NEED YOU          | EQUITY AT ETORO REAL |  hero: 2 × 2 cells
| ⨯ 2 alarms        | $10,453.61 · 40 s    |
| AVAILABLE         | SIGNALS              |
| $5,955.11         | 13 · 3 on what you hold |
| [ 4 more: next event, regime, beat, read ▸ ]
+------------------------------------------+
| [REAL] 3 open   ≈ +$76.26 ▲ estimates    |  worlds stacked, REAL first
|   +1.48R · 24 h +$12.40 · 2 closes       |
| [DEMO] 2 open   ≈ +$66.90 ▲ eToro tick   |
| [PAPER] 2 open  ≈ +$6.60 ▲ Yahoo, 3 min  |
+------------------------------------------+
| POSITIONS · 8 · ⨯ 2 alarms               |  stacked cards (.sv-stack)
| ⚠ EURUSD LONG 20,000 [REAL] ≈ +$65.00 ▲  |
|   A high-impact print is near: US CPI …  |
|   [ CLOSE (44 px) ]                      |
| ⨯ XAUUSD SHORT 1.5 [REAL]   ≈ +$15.42 ▲  |
|   Closing: the broker refused the close… |
|   ● CLOSING  [ RETRY CLOSE (44 px) ]     |
| ... the other rows, one card each        |
+------------------------------------------+
| SIGNALS TO ACT ON (3 on what you hold)   |
| MARKET (events ahead, what you hold)     |
| BOTS AND ORCS · SINCE YOU LAST LOOKED    |
| THE CYCLE (list) → Oculus                |
| REVIEW ▸ (folded) · the loop: the Wall › |
+------------------------------------------+
| Home | Positions | Portfolio | Briefing | Menu |  phone nav
```

Phone rules: no horizontal page scroll; every money button 44 px tall (UI plan S3); the Horde pill and the Eye stay in the phone nav's menu, not over content (today they overlap the WATCH and TELL tiles); the loop is never drawn on a phone (a link to the Wall).

### 3.2 The regions

Each region is a kit card (`.sv-panel`: bg-1, 1 px line-2, radius 6, a 40 px head with the title in 12 px uppercase ink-2 and the meta in 11 px ink-3 on the right). The meta always says where the figures come from and how old they are.

#### R1. The hero row (OC1 with today's cells; OC2 completes it; 52 px)

Eight cells in the shared status-cell row (`sv-stage.css`, §3.4), the Oculus's own row: 52 px, label 11 px uppercase ink-3, value mono 13, sub 11 ink-3. Every cell is a link to its block or its page.

| Cell | Value (mock) | Sub | Source (existing) | Stage |
|---|---|---|---|---|
| POSITIONS · NEED YOU | `⨯ 2 alarms` (coral); `● all clear` when none (the Oculus's calm words) | `6 watch · 9 checked ›` | The Horde tab's `alarms` (the seats' alarm lights plus the closes Sauron gave up on, `dashboard/horde.py:2089`) and its watch count, from the same board R3 prints. Watch lights (an event within the hour, a missing USD stamp) are counted beside, never in. A click scrolls to the first lit row; the title links the Oculus's Needs you | OC2. OC1 reads `closes pending 1 · no stop 0 (2 of the Horde's checks)` and never "all clear" |
| EQUITY AT ETORO + the account's world chip | `$10,453.61` | `eToro's own · 40 s` | `bot_program/etoro_used.account_used(user)`: `total_t`, aged by `total_own_age_t` when it is set and by `age_t` otherwise (a re-read after an order moves the cells and never the total, `etoro_used.py:378-387`); its `currency` | OC1 |
| AVAILABLE AT ETORO | `$5,955.11` | `57.0% of equity` | `account_used`'s `available`, eToro's own word (the order gate uses it less pledges, `etoro_used.py:17-20`). The percentage is printed only when `total_own_age_t` is empty; otherwise a dash titled "the equity is older than the cells" | OC1 |
| NEXT EVENT | `US CPI 13:30` | `in 37 min · touches 7 of 8` | `position_care.upcoming_events(horizon_minutes=1440)` and `event_for(row, events=[ev], before_minutes=1440)` for each open row: the care's own rule (§R5) | OC2 |
| SIGNALS | `13 on the rail` | `3 on what you hold` | `rail_snapshot(request)` `n`, `held_n` (`dashboard/signal_rail.py:818`) | OC2 |
| REGIME | `TRENDING` | `0.62 · 2 h ago` | The newest `BrainReport` with `error=""` (as `views_command.py:430-441`), now with its age | OC0 (age), OC1 |
| BEAT (staff) | `● last task 40 s` / `▲ 2 late` / `✕ 1 broken` / `○ master off` | `Oculus ›` | `day_live_payload()["beat"]` (`dashboard/views_day.py:349`), named and worded as the Oculus's BEAT cell. After O2a, the cell shows the Oculus's VERDICT instead, if O2a exposes it as one cached reader that fits the `act` part's budget; otherwise BEAT stays | OC1 |
| MONEY READ | `12 s ago ⟳` | `every 30 s` | The `desk` part's render time, ticking in the browser. The other cells print their own ages | OC1 |

Not in the hero, on purpose: the REAL ARMED pill and the sessions count (the topbar has them on every page); the platform book (§R9); a 24-hour change of eToro's equity, which no stored reading can give today (`capital_truth.account_equity` reads `last_equity` only, `bot_program/capital_truth.py:450-475`; P5 would store one a day).

#### R2. Three worlds, never added (OC0 in today's look; OC1 as cards)

Three cards, REAL first with the 3 px REAL edge (UI plan rule 8). There is no total cell anywhere, and a test asserts it. Each card is the sum of the rows R3 prints for its world (`open_by_world` over the same rows), so a card and its rows can never disagree on the page.

Each card shows:
- **The head:** the world chip and `N open`; on the right, the coverage in words (`estimates on 3 of 3`, later `eToro's own on 3 of 3`).
- **The open P&L**, in the 20 px figure, with its tier's words (§5.3). Before F4 it is an estimate: drawn in ink-1 with `≈`, naming its price (`≈ +$66.90 · estimate: eToro tick price, 3 min`).
- **`open R · at the stops`:** the rows' R summed, and the rows' own risk at the stops summed. The risk is each seat's `risk.v`, the gate's figure for one row (`horde.py` `_row_risk`); it reads `k of n` when a row has none in USD. It is never the Horde tab's `sides[world]`: that reads the gate's live side for both REAL and DEMO (`horde.py:2097`), which adds the two worlds.
- **`realized · 24 h`:**
  - REAL: `+$12.40 ▲ · 2 closes at eToro's price · fees not counted`. A REAL close is booked at eToro's exit price when eToro reported one, else at the mark, and fees are not counted (`bot_program/asset_engine/base.py:4405-4442`; `bot_program/pending_closes.py:366-377`). It reads "at the mark" when any close in it was.
  - PAPER: `-$40.81 ▼ · 5 simulated closes`, in ink-1. A paper scale-out banks into the open row and reaches `pnl` only at the final close (`position_care.py:64-71`).
  - A world that closed nothing: `— nothing closed` (a named dash, never 0.00).
- **The account line:**
  - REAL: `eToro's account P&L +$96.40 · all positions · eToro's own · 40 s`, then `margin used $4,402.10 · 42.1% · outside Sauron's rows $1,150.00 in 2 ›`. These are `account_used`'s `pnl`, `used`, `outside` and `positions` (`etoro_used.py:375-376, 429-457`); the link opens /treasury/. The open P&L above is labelled as Sauron's rows only, so eToro's own account P&L and the rows' sum are never mistaken for one figure.
  - DEMO: `— not read: the sync reads the eToro account in its current world` (`account_used`'s `world`).
  - PAPER: `simulated · none moves`.
- **A row whose P&L is not in USD** is named apart under its card, in its own currency (`apart, no USD stamp · EURJPY ≈ +1,240.00 JPY`), and never added. This is a forex row with no USD stamp: its P&L is in the quote currency (`portfolio/services.py:214-237, 1267-1277`), and the Horde leaves it out of every total (`horde.py:1225-1234`).

Under the cards, two lines:
- `Three worlds, never added; each card is the sum of its rows below. MSFT, recorded by hand, states no venue and sits in none of them. Is the money protected (stops at eToro, closes, ceilings)? The Oculus answers ›`
- `Since you last looked (09:42 UTC): 6 trades · 2 alerts · 5 entries refused by the exposure caps · 3 new signals · 1 Orc note · below ›` (R8's counts; "the last 24 h" without P2).

**Sources, one reading per figure:**
- The rows are R3's (the Horde's seats). The worlds are their split by `dashboard.position_summary.open_by_world` (:282), the platform's one split helper, which works "from figures the rows ALREADY carry — never a second valuation".
- The band (status bar) and the Oculus's money region print `_panel_detail`'s 20 s cache (`PANEL_TTL_SECONDS`, `core/context_processors.py:20`): they may lag the cards by up to 20 s, and each prints its age. On the fixture, with the cache cleared, a test pins that each card equals `panel_open_pnl_live/_demo/_paper`.
- Realized 24 h: one read of the user's `AssetBotTrade` closed in 24 h (`values("paper", "metadata", "pnl", "realized_r")`), split by `world_of` (`position_summary.py:253`) in Python, never a second world rule in SQL. 1 query, 1 ms on the fixture, 20 ms at six months (no `closed_at` index, P3). Legacy `Position` closes state no world and are listed apart (`no venue`), as the band does.
- eToro's cells: `account_used(user)`, read directly (3 queries, measured cold). They are never read through `_panel_detail`: its 20 s cache is cold on two polls in three, and it is never read from cache under the test runner (`context_processors.py:1026-1044`).

#### R3. Positions (OC1 table; OC2 lights)

One table for the whole open book:
- the user's `AssetBotTrade` rows in OPEN and CLOSE_PENDING, and his legacy `Position` rows (the Horde's seats);
- the closes Sauron gave up on (the Horde's stragglers: ERROR with no `closed_at`, which may still be open at eToro, `horde.py:755-762`).

It replaces the LIVE tab's Eye table and the PORTFOLIO tab's table. Header: `POSITIONS · 8 open: 3 real · 2 demo · 2 paper · 1 no venue · 1 close given up · ⨯ 2 alarms ›` (a count may be totalled beside its split; money never). Meta: `real money first, then the newest · words: the Horde's · read 12 s ago`.

| Column | Content | Source |
|---|---|---|
| (edge) | 3 px REAL edge on real rows | the row's world |
| light | `⨯` alarm (coral), `⚠` watch (amber), `◆` order (ink-2), `○` unheld (ink-3), blank when calm; `+N` under it when more than one reason fired | `horde.light(facts)["tone"]` (:934) |
| POSITION · QTY @ ENTRY | Line 1: the symbol (mono 13/500, a link to its instrument page), the side chip and the world chip (REAL solid, DEMO gold outline, PAPER grey outline, NO VENUE dashed). Line 2: `20,000 @ 1.08420 · 41 min` | the seat; quantities through S1a's `qty`, prices through `{% px %}`; `world_of` on the trade, never on a dict without metadata |
| MARK | The mark (mono) and its badge: `● eToro quote · 12 s`, `● eToro tick · 4 min`, `○ eToro · closed`, `● Yahoo · 3 min`, or, for a stand-in with no recent venue stamp, `waiting for the venue's price` (the Horde's `MARK_WAIT`) | the seat's `mark`, plus OC2's additive `mark.age_s` and `mark.feed` (today the seat carries only `word`, "venue" or "feed", `horde.py:1246-1248`) |
| OPEN P&L | `≈ +$65.00 ▲` and its words: `estimate: eToro quote, 12 s` (§5.3); a row in another currency prints it (`≈ +1,240.00 JPY`) | the seat's `money` (PR #89's words on eToro rows; the page's own words on paper and hand-kept rows, from OC2's additive `money.pnl_at` and mark fields) |
| R NOW · TO STOP | `+1.25R` and `2.25R to stop 1.08160` | the seat's `r_v`, its stop, and the Horde's `near_stop_r` |
| THE HORDE'S WORDS | The first reason, verbatim, two lines at most (`Closing: the broker refused the close, so it is still open there; Sauron retries it.`; `A high-impact print is near: US CPI at 13:30 UTC.`). When it fits one line, the seat's mission and the holder's short words follow, verbatim (`fixture live forex · Full care`). The row's detail holds the full list, the holder's sentence and, for a close pending, the failed attempts (`metadata["close_retry_attempts"]` and `close_retry_last_at`, `pending_closes.py:1214-1224`), named as the row's own close record | `light()["why"][i]["t"]` (`horde.py:934-1033`, words :100-205), `holder()` (:881), the seat's `mission` |
| (action) | `CLOSE`; or the `● Closing` state (dot and word, the kit's `.sv-state--pending`) above `RETRY CLOSE`; `Story ›` (`/forensics/<id>/`) on a close given up; `—` titled "no close path exists for a row recorded by hand"; sticky on the right, never scrolled off | the existing `data-sv-close-trade="<id>"` and `svCloseTrade` (`base.html:4119`), unchanged |

**Order:** REAL, DEMO, PAPER, then no venue; within a world, the newest first. The order never depends on a light, a price or an R, so a refresh that changes a light or a mark never moves a row or its CLOSE (UI plan rule 7: "A button never moves under the pointer when a price ticks"). A new or closed row does change the table, and even then the desk part does not swap while a dialog is open, a close is in flight, or the pointer or focus is in the table (§4.1). The lit rows are reached from POSITIONS · NEED YOU and from the header's `⨯ 2 alarms ›`, which scroll to them and outline them.

**Past 12 rows,** the rest fold in place, in the same order, under `+N more, in the same order · show` at the table's foot. They are rendered (hidden) with their keys and their CLOSE buttons, counted in the world cards, and opened by the disclosure or by a NEED YOU link that points into them. The open state holds for the visit. Nothing is sent to another page to be closed.

**Under the table:**
- **At eToro, not on Sauron · N** (OC2): the Horde's `unseated` rows, matched by symbol, side and count (`horde.py:1761-1836`). Each row gives the symbol, side, units and the value eToro's list gives: a dash when it gives none, since eToro's `/portfolio` rows carry no mark (`horde.py:1828`). The Horde's words follow: `Not matched to an open seat as of this read (40 s ago).` There is no CLOSE: these are closed in the eToro app.
- **The old crypto bot's open rows** (legacy `BotTrade`: no close path, and nothing ticks them). Today's Eye lists them (`views_eye.py:168-189`). R3's foot says `N open rows of the old crypto bot: no close path · on /eye/ ›` when any exist (one count; none on the fixture), and /eye/ keeps the list.
- The links: All on /positions/ ›, Close all is on /positions/ ›.

**Source:** `dashboard.horde.board(user)` (:2167): the seats, `stragglers`, `unseated` and the tab's `alarms` in one call. It costs 47 queries cold and 16 warm on the fixture, and 181 ms cold at six months (§7.2). It values a real row through the positions page's own row, so the home, the Horde and /positions/ print the same digits.

**Before OC2** (OC1), the same table is built from what the page reads today (`_open_book` and `shown_open_rows`). Its lights are the two the rows already carry, in the Horde's words: `CLOSE_PENDING`, and no stop on a real or demo row. NEED YOU and the header then read `closes pending 1 · no stop 0 (2 of the Horde's checks)`.

#### R4. The cycle (OC1; one vocabulary with the Oculus's cycle map; after R8)

Seven compact tiles in one row: the shared stage tile's compact variant (§3.4). Each tile holds:
- the stage name (11 px uppercase ink-2) and the state in the words of `STAGE_STATES` (`views_day.py:47`): `● live` Eye, `▲ stale` amber, `✕ broken` coral, `○ off` hollow, `· quiet` ink-3;
- `ran 6 s · 1 of 21 late` (`stages[k]["words"]`, as on the Oculus's tile);
- two metrics from `stages[k]["metrics"]`, in the payload's own units and words.

A tile is a link to `/oculus/#stage-<key>` (O2a). It never expands in place, so the page never shifts.

- **The metrics:**
  - SEE: instruments priced under 15 min, and the newest quote's age in whole minutes (`0 min, newest quote`; the payload counts minutes, `views_day.py:214-216`);
  - THINK: signals raised today, active now;
  - DECIDE: gate refusals today, and minutes since the freshest bot tick. Its configs count (`of 7 bot configs enabled`) includes the TAKE TRADE lane (`views_day.py:247-259`), while `_bot_truth` leaves it out, so the home leaves that count to the bots page;
  - ACT: opened today, closes pending (OC0 fixes the words that count DEMO as live money);
  - WATCH: guards ran, findings standing;
  - TELL: notifications today, unread;
  - LEARN: AI calls today, trades graded today (`views_day.py:546-549`).
- **Header meta:** `the seven stages the Oculus speaks · 64 tasks, 2 late · a click opens the stage on the Oculus · read 40 s ago`.
- **Source:** `day_live_payload(user)` (`views_day.py:349`), the payload `/api/day/live/` serves, rendered by the server. It is in the page at first paint, then refreshed every 60 s by the `cycle` part (OC1), which OC2 folds into the `act` part. The tiles leave `#dayHome`, so the tile painter of `static/js/sv-day-live.js` (:99-119, scoped to that section) finds none and paints nothing.
- **Viewer:** the tiles show each stage's job sentence (`STAGES`, `core/day_of_sauron.py:31`) and `states are staff's`. A viewer's page has no `cycle` part and never asks `/api/day/live/` (it answers a viewer 403 today, :665).

#### R5. The market on what you hold and watch (OC2)

- **Ahead · 24 h.** High-impact calendar rows in the next 24 h, each with the positions it touches and the time left: `13:30 US CPI (USD, high) · touches EURUSD, XAUUSD, AAPL, USDJPY, NAS100, GBPUSD, MSFT · in 37 min`.
  - Which event touches which position is the care's own rule, called for each row as `event_for(row, events=[ev], before_minutes=1440)`. The default of 60 min would make "FOMC minutes in 6 h" touch nothing.
  - The rule as the code has it (`bot_program/position_care.py:358-418`):
    - a forex row is touched by either leg's currency;
    - a stock or ETF by its own earnings within 24 h, and by every USD macro print;
    - every other class (commodities, indices, crypto) by USD macro prints;
    - options never.
  - The header names the calendar's age from its task's state: `calendar read 2 h ago: its task is late (every 30 min)`. An unreadable calendar answers `[]` (`:349-351`), which looks like "no event", so it prints a dash titled with that state.
- **You hold · N.** One line per held instrument, with what R3 does not print:
  - the day change with its feed (`+0.12% · eToro`): `change_pct` is the feed's day change, it defaults to 0, and it may come from another feed (`market_data/models.py:37-44`), so it prints a dash when `change_source` is blank;
  - the event that touches it;
  - news today on it.

  Its price and badge are R3's, and they are not repeated here.
- **You watch · N starred, not held.** The rail's watchlist (`Instrument.is_watchlist`): price, day change with its feed, and the badge. A stand-in says so (`Yahoo future · 3 min`, `Yahoo cash index · 3 min`).
- **The brain.** `regime TRENDING, confidence 0.62 · trust MEDIUM · its report of 10:51 UTC, 2 h ago`. Staff also see its first concern (`BrainReport.top_concerns[0]`) with a link to /brain/.

Sources and cost:
- the held rows are R3's (0 queries);
- one `LiveQuote` read for the starred instruments, with `select_related` (1);
- `upcoming_events` (1);
- news today by held instrument, one aggregate on `ai_affected_instruments` (1);
- the newest `BrainReport` (1).

#### R6. Signals to act on (OC2)

The rail's own list, never a second ranking:
- **On what you hold · N.** The rail's cards whose `held` is true, each with the facts from R3's rows: `you hold it: REAL short 1.5`. It never says "adds to" or "against": the rail's held map keeps one world per symbol and no side (`signal_rail.py:341-377`), and what an order does is the ticket's to say.
- **Voting now · N · new since you looked · N.** The first four in the rail's own order, with `the bots count its vote · 20 h left` (the card's `vote_words`) or `new since you looked`.
- **Foot:** `+6 more in the rail · left the rail today 6: 3 superseded · 2 aged · 1 stop crossed · your passes 2 · taken 1` (the rail's counts and PR #90's `RailDeparture`), with "Open the rail ›" and "All signals ›".
- **While the rail is open beside the page,** R6 collapses to its counts: `13 · 3 on what you hold · 9 voting · open in the rail`.

**A row acts only by opening the rail's card:** `window.svRailFocus(id)` (`base.html:1935`), which opens the rail, scrolls to the card and pins its popup, or goes to /signals/ when the card is filtered out. TAKE TRADE, ADD and PASS stay in that card with their words, steps and the PIN unchanged. The home has no TAKE TRADE button of its own.

Source: `rail_snapshot(request)`, memoised on the request and already computed by the shell's rail in the same render (`core/context_processors.py:1516`): 0 extra queries at first paint. In the `act` part it costs 36 queries cold and 10 warm (its rule facts are cached 300 s).

#### R7. Bots and Orcs (OC2; today's BOTS tab content folds in)

- **The program line:** `● LIVE · 2 bots armed on your REAL account · 0 on a DEMO account · 2 paper · 0 shadow · 0 halted · tick 3 min ago (every 5)`.
  - It comes from `_bot_truth` after OC0's split (§8, OC0). A config's world is the world of the account its symbols route to (`broker_router.client_for_symbol`, :243-299). A config whose route cannot be read counts as REAL.
  - Until OC0's split lands, the line says what the code counts: `live mode: 3 (2 on a REAL account, 1 on a DEMO account)`.
- **Each world · 24 h** (bots and his tickets): opened, closed, realized (and how it was booked), realized R, wins and losses, open R. A world that closed nothing reads a dash in each of those cells.
- **The exposure caps:** `The exposure caps refused 12 bot entries in 24 h: theme 7 · currency 3 · sector 2. The book limits and the daily stop are not logged as events. Allows are sampled, so no rate is drawn.`
  - These are `OrchestratorEvent` rejects grouped by their fixed prefixes: `orchestrator: <x> theme cap`, `currency cap`, `sector cap` (`bot_program/orchestrator.py:437-463, 511-529`). One aggregate.
  - The book limits and the daily stop belong to `portfolio/risk_gate.py`, and they are not logged there.
  - Each count says its window: the DECIDE tile `today`, R7 `24 h`, R8 `since 09:42`.
  - The words carry over the LIVE tab's own reason for never drawing an accept rate (`views_command.py:607-615`).
- **Bots:** the ones that traded first, then the rest. Each row gives the name, the world chip from its account, the state (`● ON`, `○ OFF`), the last tick, its open rows and its realized 24 h.
  - Health comes from each bot's own heartbeat (`safety.heartbeat_age_seconds`, `bot_program/asset_engine/safety.py:203`) against its cadence, as DECIDE and `panel_bot` read it. It is never "traded in 6 h".
  - The section's sub says `world: its account · health: its own tick`.
- **The Orcs:** `● ON · 7 on watch, one per open position (bots' and your tickets') · minds ON · intents in shadow: 3 today (2 tighten, 1 trim), nothing placed · latest note, in the mind's words: EURUSD "would tighten to 1.08350 before CPI" · 12:38 UTC`.
  - "nothing placed" comes from `OrcIntent.mode` counts today (every O2 intent is `shadow` or `refused`). It never comes from `minds_on()`, which only says that the four model-call gates are on (`bot_program/orcs/switches.py:95-97`).
  - The note is read from the board's Orc slot after the Horde's plain words (`_orc_plain`), never from `Orc.latest_note` raw, and it is drawn in the model colour (`--sv-ai`).
  - Sources: the switch from the shared component rows, `Orc` alive (1 aggregate) and `OrcIntent` today by kind and mode (1 aggregate).
- **Links:** Bots page ›, Orcs ›, Exposure caps ›, Switches · /ops/ ›, and for superusers "Kill switch, with your PIN ›" (`admin_dashboard#flattenForm`). Exposure caps › opens `/eye/exposure/`, with the Horde head's `exposure.ok/reason` for each gate side in its title (`horde.py:1980-1983`).

#### R8. Since you last looked (OC2)

- **Header:** `SINCE YOU LAST LOOKED · 09:42 UTC`, meta `3 h 11 min ago · the drawer, the rail and the Orcs`, and a `Mark as read` button (P2).
- **Chips by kind:** `6 trades · 2 alerts · 5 refused by the caps · 3 new signals · 1 Orc note`.
  - Trades, alerts and gate refusals are counted from one `activity_events(user, since=<stamp>, limit=200)` read: the drawer's own reader, 6 bounded queries. When 200 lines come back, the chips say `at least`.
  - New signals are the rail's cards created after the stamp (from `rail_snapshot`, 0 queries).
  - Orc notes come from one read of `Orc.latest_note_at > stamp`.
  - Neither signals nor Orc notes is a kind of the drawer (`dashboard/activity_feed.py:65`).
- **Lines:** up to eight, newest first: trades, alerts, the Orc's note in the mind's words, and the gate refusals as one summary line. Routine pipeline lines are hidden. Then `N more in the Activity drawer ›` (staff).
- **For a viewer:** his own trade, gate, bot and alert lines only, and no drawer link. The drawer is staff-only, and its ai, pipeline and system lines are platform-wide (`activity_feed.py:40-45`).
- **The stamp** (P2, his OK).
  - It is the time he last looked at the home, kept under its own key (`TraderProfile.pages_seen["command_seen"]`) in the same map and endpoint as the sidebar's dots (`dashboard/views.py:5648 nav_activity_json`), with `command_seen` stamped but lighting no dot.
  - The GET reads it and writes it into the part's URL: `hx-get=".../act/?since=<stamp>"`. The part checks it (not later than now, not older than 7 days) and never re-reads `pages_seen`, so a refresh never empties the block. The page-load beacon stamps every load (`static/js/sv-nav-activity.js:87-91`), so the block must not use it.
  - The stamp moves only when R8 has been on screen for 5 s in a visible tab, or when he presses `Mark as read`. Passing through "/" does not move it.
  - Without his OK, the region reads `the last 24 h` and says so.

#### R9. Review (OC1; today's PORTFOLIO, HISTORY and BOTS, fixed in OC0)

Three tabs (32 px), `Performance`, `History` and `Bots`, with two segmented controls:
- the world: `REAL` by default, `DEMO`, `PAPER`. The segments carry their world chip, the REAL one solid red (UI plan §7);
- the window: `24 h`, `30 d`, `90 d`, `lifetime`.

**Loaded on demand** when the section is revealed (`hx-trigger="revealed"`) or a tab is clicked. It is never polled, and ⟳ refreshes it. The meta says `on demand · not refreshed while open`.

**Performance, by world** (the selectors apply):
- closed and win rate;
- profit factor (gross wins over gross losses) and payoff (average win over average loss), each named;
- total R;
- average win and average loss, with their currency;
- exposure now (the notional at the marks) and risk at the stops now.

Every figure says its window and how its closes were booked (`all 41 closes booked at eToro's exit price; fees not counted`). All are computed in the database (OC0). A realized figure wears jade or coral only when every close in it was booked at eToro's exit price.

**The platform book, in its own box,** titled `the platform book: all worlds, mixed currencies`. The world selector does not apply to it, and the box says so.
- The value, with no currency sign: `60,809.79 · EUR + USD, not converted · not a balance`.
- Its words: `The cash typed on /setup/ (EUR 10,000.00) + the REAL and DEMO positions' notional in USD, hand-recorded rows too + paper's open and realized P&L, not converted. Paper limits divide by its hourly copy (60,781.40, stored 12:00 UTC); the live side's limits use eToro's equity while it was read under 2 h ago. eToro's own equity is at the top of the page.`
  - The paper limits use `gate_book_value`, the stored `Portfolio.current_value` written hourly (`portfolio/risk_gate.py:285-335`; `portfolio/tasks.py:123-145`; `config/celery.py:312-314`). On the scratch fixture that copy is 10,000.00, because the hourly task never ran there.
  - The live side's limits use eToro's equity while it was read under 2 h ago (`risk_gate.py:338-373`); until C1–C3, DEMO rows sit on that side too.
  - Paper rows add only their open P&L and their realized P&L since inception, never their notional (`services.py:937-986`, 837-849). An unstamped forex row's P&L enters in its own quote currency.
- Max drawdown, Sharpe and Sortino, with the snapshot's date.
- The equity curve of the daily snapshot (23:30 UTC).
- The allocation donut in the categorical palette.

**History:** bot closes by world and window. It holds:
- the cumulative R per day (one point per day) and the rolling win rate;
- the weekday map, coloured by |avg R| with a floor (§5.6);
- per rule × class, with the P&L per world and its currency;
- the top five rules;
- the session pulse, and the best and worst of the window, dated;
- the decay alerts;
- the recent closes, with their world chip and currency.

**Bots:** today's BOTS table, with the world chip from the account, health from the heartbeat, and P&L 24 h with its currency. Its quick links stay (Bot Performance, Backtest, Allocator). Today's toggles stay or leave per P1 (§6.4).

#### R10. The loop, drawn (OC1; folded by default)

One line: `▸ The loop, drawn · the Wall's ring with today's states, THE BEAT and the 24-hour day · closed · read only while open, every 60 s, and drawn still`. Open, it is today's ring, THE BEAT panel and the 24-hour strip (`sv-day-scheme.js`, `sv-day-live.js`, `sv-day-scheme.css`). It is `#dayHome` as today, with the tiles moved out.
- **Folded by default.** Today `readCollapsed()` folds a section only when its stored key reads '1' (`sv-day-live.js:69-70, 80`), so with no stored choice the section opens. OC1 makes one change to `sv-day-live.js`: a section with `data-day-collapsed-default="1"` starts folded when no choice is stored. A node test covers it, and his own choice is still kept per browser under `sv-day-collapsed`.
- **Open,** it reads `/api/day/live/` every 60 s: one more request and 22 queries a minute, on top of the `act` part. Folded, it reads nothing (`sv-day-live.js:216-220`).
- **Drawn still.** `sv-day-scheme.js` creates endless SMIL animations (`:105-129`), and UI plan §8 allows two on a work page. When the section opens, `sv-command.js` calls the ring's `pauseAnimations()`. That is S2.3's "calmer" loop.
- Its SVG text is drawn at 11 px or more (§8, OC1). It is not drawn on a phone.

#### R11. How to read this page, the dashes, the stamp (OC0 content; OC1 look)

- **The dashes on this page · N.** One line per dash: its place (`Demo card · realized 24 h`) and its reason (`Nothing closed in the demo world in 24 h: not a zero`). N is the number drawn, and a test counts them. The mock lists all 16.
- **Three rules:**
  - "A dash means no figure here, and its line says why; 0 is a measured zero."
  - "Three worlds, never added."
  - "Every stored reading says its age; an estimate starts with ≈ and names its price."
- **The stamp:** `Read 12:53:20 UTC. The money and the positions refresh every 30 s and at once on a fill or a close; the market, signals, bots and since-you-looked every 60 s; only while this tab is visible. This page's own refreshes stop while the tab is hidden or locked; the frame's own polls go on until P4.` It replaces the Eye footer's false "Auto-refresh every 10s".

### 3.3 The viewer's page (non-staff)

The same order and regions over his own book: his worlds, positions, market, signals, bots and Orcs, and since he last looked.
- Staff-only parts are withheld in words, never dropped:
  - the BEAT cell reads `staff only`;
  - the cycle tiles show the job sentences;
  - the brain's concern text is replaced by a dash titled `staff only`, as on /brain/ (`views_command.py:778-780`);
  - the rule ladder's counts (today's RULES cell) read `staff only`;
  - R8 shows his own trade, gate, bot and alert lines, with no drawer link;
  - the loop draws from the schedule, as the Wall does.
- The page never asks `/api/day/live/` for a viewer.
- The bot buttons are never rendered for a user the endpoint refuses (OC0).

The investor login never reaches /command/ (`core/investor_gate.py`), as today.

### 3.4 Components

**From S1a's kit, unchanged:**
- `.sv-panel` (+ head, title, meta, body, foot);
- `.sv-kpi`/`.sv-kpis`, `.sv-kv`;
- `.sv-table` (sticky header, the REAL edge);
- `.sv-pnl` (value + `.sv-pnl-src`);
- `.sv-fresh`, `.sv-src`, `.sv-est`;
- `.sv-world`, `.sv-chip`, `.sv-state` (CLOSING is `.sv-state--pending`: a dot and a word, never an outlined chip), `.sv-count`;
- `.sv-notice`, `.sv-tabs`/`.sv-tab`, `.sv-seg`, `.sv-meter-*`, `.sv-empty-state`;
- the filters `qty` and `src_name`.

**Added to the kit by OC1** (`sv-kit.css`, additive, after S1a merges):
- `.sv-col-act`: the sticky right action cell;
- `.sv-p1`, `.sv-p2`, `.sv-p3`: column priorities by container width;
- `.sv-world--none`: the NO VENUE chip, a dashed outline.

S1a's `.sv-table` has a sticky header only (`sv-kit.css:872-886`). S2.2 (/positions/) reuses these classes. One table partial shared by R3 and /positions/, with the light column optional, is offered to S2.2 (§9); it is not done here.

**Shared with the Oculus, in `static/css/sv-stage.css`, created by OC1.** OC1 lands before the Oculus's O2a, whose cycle map is the first Oculus region to draw the stage tile (Oculus spec R3). The sheet holds:
- the stage tile and its compact variant;
- the status-cell row (52 px, values mono 13);
- the three-world card (figure 20 px).

O2a's file list loads `sv-stage.css` instead of drawing these in `sv-oculus.css` (§9), so the two pages never draw them two ways and neither edits the other's page sheet.

**Page-only**, in `static/css/sv-command.css` (≈ 200 lines, on tokens only):
- the light column and the Horde's words cell;
- the "At eToro, not on Sauron" list;
- the signal row;
- the activity row.

No literal colours and no `rgba(0,232,104`. A sweep test pins it, as S2.8 does.

---

## 4. What updates live, and how

### 4.1 The mechanism: small server-rendered parts on readers that exist

The pattern is the Oculus's (O2a §4.1), so one mechanism serves both pages.

- **Parts.** Each region group is one template partial; the full page includes them all at first paint. `GET /partials/command/<part>/` serves one part alone:
  - `desk`: R1's money cells and NEED YOU, R2 and R3 with its lists, in one response, so the verdict, the worlds and the rows always come from one reading;
  - `cycle` (OC1, staff): R4's tiles and R1's BEAT; OC2 folds it into `act`;
  - `act` (OC2): R5, R6, R7, R8, and R1's NEXT EVENT, SIGNALS and REGIME by `hx-swap-oob`; for staff, the tiles and BEAT;
  - `review`: R9's active tab, on demand.
- **Not a part:** the loop (R10) keeps `/api/day/live/` and `sv-day-live.js`, read only while it is open.
- **The view.** One view with a whitelist of part names, `@login_required @never_cache @require_GET`, each part's staff rule enforced in it.
  - It renders with `render_to_string(template, context)` and no request, so no context processor runs.
  - A part that holds a form gets `csrf_token=get_token(request)` and `can_operate=request.user.is_superuser` in its context. Only R9's Bots tab holds forms, and only if P1 keeps them.
- **Why `/partials/`.** htmx sends `HX-Request`, so `core/idle_lock._wants_json` (`idle_lock.py:89-104`) answers a locked session 423 there, never the lock page. `_is_human` reads the same rule, so the parts never stamp activity: only `/api/session/ping/` and his own clicks do.
- **htmx 1.9.10** is already in the shell. Each part carries `hx-get` and `hx-trigger="every 30s [document.visibilityState === 'visible']"` (or 60 s), with `hx-swap="outerHTML"`.
- **`static/js/sv-command.js`** (≈ 160 lines, node-tested):
  - it stops a part on 423, on a redirected response and on the `session_locked` eye event, and resumes on `sv:pin-unlocked` and when the tab is visible again (the contract `sv-day-live.js` already follows);
  - it re-fetches `desk` 800 ms after an eye event of kind `fill_open`, `fill_close`, `close_pending` or `scale_out`, and `act` after `new_signal`, `fill_open`, `fill_close`, `notification`, `gate_reject` or `run_complete`, all on the shell's `sv:eye-event` (`base.html` re-dispatches every `/ws/eye/` payload). There is no new socket;
  - **it holds a `desk` swap** while an `SV.overlay` dialog is open, while a close is in flight (from the click on a `data-sv-close-trade` button to its answer), and while the pointer or focus is inside the positions table. The held swap lands when they end, as the shell's sweep does for its regions (`live_region.html:200-210`). When a close answers, it re-fetches `desk` at once. A swap during the dialog would detach the row the close greys after success (`base.html:4078-4082`), and the visible row would read OPEN again: the guard against a second press;
  - it moves R8's stamp after 5 s on screen (P2);
  - it ticks MONEY READ and the "N s" ages locally each second, with no request;
  - it schedules nothing while the tab is hidden.
- **Refresh keeps the frame** (UI plan §8). A part being fetched keeps its last render, at 70 % opacity after 300 ms. There is no skeleton and no layout jump. Identical numbers re-render identically.
- **Nothing flashes its text colour.** The page's money and price cells carry the platform's unique row keys and `data-sv-noflash` (§6.2). A price cell (OC3) takes the up/down wash for 600 ms, at most once a second (F7's own limit). A button never moves.

### 4.2 Each part's refresh

Queries are counted cold, after `cache.clear()`, on the fixture (measured, §7.2), plus the 3 every request pays (the session, the user, the investor gate).

| Part | Refresh while visible | Also on (eye event, +800 ms) | Reads per refresh (all existing) | Queries, cold | Who |
|---|---|---|---|---|---|
| desk (R1 money and NEED YOU, R2, R3) | 30 s (eToro quotes are 30 s, the account sync 60 s: PR #95) | `fill_open`, `fill_close`, `close_pending`, `scale_out` | `horde.board(user)` (47 cold, 16 warm: its Block B is cached 20 s on the fingerprint, `horde.py:88, 818-841`, so a 30 s poll finds it cold unless the Horde band is open); `account_used` (3); closes 24 h by world (1) | ≤ 55 (measured 51 + 3) | Own book |
| cycle (OC1; R4, R1 BEAT) | 60 s | `run_complete` | `day_live_payload` (17) | ≤ 20 | Staff |
| act (OC2; R5–R8; R1 NEXT EVENT, SIGNALS, REGIME; for staff R4 and BEAT) | 60 s | `new_signal`, `fill_open`, `fill_close`, `notification`, `gate_reject`, `run_complete` | `rail_snapshot` (36 cold, 10 warm: rule facts cached 300 s); `_bot_truth` (18, not cached); `activity_events(since, 200)` (6); `upcoming_events` (1); starred `LiveQuote` (1); news on held (1); exposure caps 24 h by reason (1); `Orc` and `OrcIntent` aggregates (2); Orc notes since the stamp (1); newest `BrainReport` (1); for staff `day_live_payload` (17) | ≤ 90 staff, ≤ 72 viewer (measured 85 + 3) | Own; the tiles and the brain's concern text for staff |
| /api/day/live/ (R10 only) | 60 s, only while the loop is open | as today | `day_live_payload` (17) | 22 with auth | Staff |
| review (R9) | Never | — | Today's tab builders after OC0 (§7.3) | ≤ 22 | Own |

### 4.3 What stays on refresh, and why

- **R9 Review** changes per close and per night, and is read when he looks at it.
- **The loop's drawing** (R10) reads only while it is open.
- **R11's dash list** is rendered with the parts that hold the dashes, through `hx-swap-oob`.

Polling the review would cost queries without telling him anything new.

### 4.4 After F4 and F7 (OC3)

- **F4** (eToro's own P&L). It follows F4's own cadence (feed spec §4.7.1):
  - REAL about every 11 s while a held market is open, and every 60 s when every held market is shut;
  - DEMO about every 30 s, while a DEMO row is open;
  - one extra read 11 s after each fill or close.

  F4's push is the per-user `marks` message, keyed by the page's row key `{{ p.key }}` (feed spec §4.6.1). It updates the P&L cells in place in F4's own tiers (§4.7.4): `eToro · live` (F7), `eToro's own · N s` up to 60 s, `eToro's figure · N min ago` past that, and `awaiting eToro` (Sauron's estimate beside it only as "estimate, not eToro's"). The ages tick locally. Totals carry `partial k of n` whenever a row is on the last tier.

  The cards stay the sum of the rows: `sv-command.js` re-sums every row of a world, the folded ones included (they are rendered hidden with their keys), and never adds two worlds. The `desk` part then refreshes every 60 s, for structure (a new row, a light).
- **F7** (prices). The MARK cells and their badges take the per-row `marks` push; R5's prices take `venue_quotes` through `sv-venue.js`'s public hook. They degrade in the same frame as the grade (feed spec §5.6: degrade at once, hold 5 s, recover on the second confirmation; the kit only draws). "Live prices paused" (F7's topbar chip) turns every badge hollow, and the page says it is his socket to Sauron, not the eToro feed.
- **If F7's display switches are OFF,** the parts return to their timers, with no code path left half on.

### 4.5 Requests and queries per minute

| | Today | OC1 | OC2 | OC3 |
|---|---|---|---|---|
| The page's own requests per minute while visible (staff, loop folded) | 2.33 (metrics 1.33, day 1) | 3 (desk 2, cycle 1) | 3 (desk 2, act 1) | 2 (desk 1, act 1; P&L and prices pushed) |
| The page's own queries per minute while visible, cold | ≈ 79 (metrics 57, day 22) | measured in its PR (its desk reads today's book walk, not the board) | ≤ 200 (desk 2 × 55, act 90) | ≤ 145 (desk 55, act 90) |
| While hidden | 0 (the 45 s and 60 s timers run only while visible) | 0 | 0 | 0 |
| While locked in place | metrics 1.2 (302, each followed to /locked/); the poll also stamps the session while visible | 0 | 0 | 0 |
| The shell's own (health 10 s, band 60 s, rail 60 s, nav 45 s, exchange 60 s) | 10.3/min visible; 6/min hidden; about 18/min locked in place | unchanged until P4 | unchanged until P4 | unchanged until P4 |

OC2 reads more per minute than today (≈ 200 cold against 79), because it shows the Horde's lights on every row, the rail, the activity and the bots in place. Its first screen, though, costs ≤ 160 queries in one request, against 271 in three today. If the cost matters, the desk can poll every 60 s: a fill or a close still refreshes it at once.

---

## 5. Truth rules: the Oculus's §5, kept, plus the desk's

### 5.1 The four values

| Value | Means | Drawn as |
|---|---|---|
| A number | Measured now | Mono, ink-1 (ink-2 when inert) |
| `—` | No figure here, for a named reason | ink-3 dash with a `title` naming the reason, and its line in R11 |
| The gate | The switch or state that decides what the number means | A state in words beside the number: `ARMED · 2 bots`, `● ON`, `minds ON · intents in shadow · nothing placed` |
| A stored reading | A figure a writer stored: eToro's cells and holdings, the brain's report, the daily snapshot, the rail's rule facts | The figure plus its age (`eToro's own · 40 s`, `2 h ago`, `snapshot 2026-11-06`). With no age, it is not shown: it is treated as `—` |

### 5.2 Worlds and money

- **REAL, DEMO and PAPER are never added.** No total cell exists anywhere on the page. A count may be totalled beside its split (`8 open: 3 real · 2 demo · 2 paper · 1 no venue`); money never.
- **DEMO is never in REAL**, in any cell, chip, count, pill or word. The world is always `world_of` on the trade, and on the routed account for a bot. It is never `paper` alone, never `mode` alone, and never a dict without its metadata.
- **A legacy row states no venue.** It sits in no world and prints `NO VENUE`, with the Horde's title: "Recorded by hand or imported: this row does not say whether it is real or simulated money. The book limits treat rows like it as real money." (`horde.py:110-112`).
- **Money is grouped, with two decimals.** P&L carries its sign and ▲/▼. `int()`, `floatformat:0` and `,.0f` never touch money. The currency is the figure's own:
  - eToro's account figures are in the account's currency (`account_used(...)["currency"]`, its `last_equity_currency`; USD on the fixture). This is "the account currency" of UI plan §4.4, whose example `€10,453.61` assumed euros (the Oculus mock follows it; §9);
  - a P&L carries the currency of its answer: USD for eToro's tiers and for rows with a USD stamp;
  - a forex row with no USD stamp is in its quote currency (`+1,240.00 JPY`), never `$`. It is left out of every sum, and the sum says so;
  - the platform book is mixed and wears no currency sign: `60,809.79 (EUR + USD, not converted)`.
- **Prices** use the instrument's own decimals (`{% px %}`). **Quantities** use `qty` (S1a) or `position_summary.quantity` before it: never 8 decimals.
- **R** is `+1.25R`, with two decimals. It is a ratio and carries no currency.

### 5.3 P&L words: PR #89's three tiers, as the code has them

| Tier (`venue_pnl` source) | When | Value | Line under it |
|---|---|---|---|
| `etoro` | eToro's own `netProfit` for the position, from the holdings read ≤ 15 min ago, in the row's own world and in USD (`services.py:1197-1236`) | `+$65.00 ▲`, in jade or coral | `eToro's own · 8 s` (the age of the holdings read) |
| `etoro_quote` | An eToro-written quote's closing side (bid for a long, ask for a short), ≤ 900 s old, converted here (`services.py:1221-1236`, 1296-1312) | `≈ +$64.10 ▲`, ink-1 | `estimate: eToro quote, 12 s` |
| `estimate` | The platform's own mark (`services.py:1319-1343`) | `≈ +$6.60 ▲`, ink-1 | one of three forms: `estimate: <feed> quote, <age>` (the LiveQuote, the feed's name through `src_name`); `estimate: eToro <fill \| tick \| candle \| close-dialog> price, <age>` (a venue stamp); `estimate` |

What the tiers reach:
- **Before F4, tier 1 is expected to be empty.** It reads `netProfit` from eToro's holdings list, a key the client stores but calls "unmeasured on this account" (`etoro_client.py:2939-2958`). The feed spec says it plainly: "Tier 1 is probably always empty". The mock therefore draws REAL rows in tiers 2 and 3, and "eToro's own" for each row belongs to OC3 (F4).
- **Tier 2 reaches only the instruments of open REAL rows that are not stand-ins.** The 30 s quotes read eToro's rates for the instruments of open REAL eToro rows on an account not flagged Demo (`etoro_quotes.py:19-32, 164-188`). A DEMO row reaches tier 2 only when the same instrument is held REAL; otherwise it reads tier 3.
- **A stand-in never gets an eToro quote:** XAUUSD's platform quote is the GC=F future, SPX500's is ^GSPC (`market_data/public_feed.py:50, 64, 189-205`). Such a row is valued on the venue's stamp (`estimate: eToro tick price, 4 min`). With no stamp in four days it gets no price at all (`waiting for the venue's price`, `bot_program/venue_mark.py:384-430`).
- **PR #89 answers only eToro rows** (`venue_pnls` skips paper and legacy rows). A paper row's and a hand-kept row's words (`estimate: Yahoo quote, 3 min`) are the page's own, built from OC2's additive mark fields. They are not PR #89's.
- **No "stale" before F6.** No rule before F6 makes a quote stale (`venue_mark.py:104, 137-140`). The Horde's only stale mark is a REAL row priced on the venue's last print (`venue_stale`), with its age (`horde.py:989-991`), and the page prints that one in the Horde's words: `Priced at the venue's last rate, 5 min old.`

How the tiers look:
- **Colour.** Jade and coral sit only on a figure eToro states (eToro's own P&L for a position, eToro's account P&L) and on realized money booked at eToro's exit price. R follows its P&L. Everything else wears ink-1, with its sign and ▲/▼: estimates, the simulator's closes, and a close booked at the mark. That is the preview board's own rule: polarity colour is for a figure eToro states.
- **Coverage.** A world card says how many rows are each tier's (`estimates on 3 of 3`).
- **An open, unmarked world.** The band's words for an unmarked real row (`live_book_words`) are used verbatim: the card's value is a dash with that sentence as its reason.

### 5.4 Ages

Every stored reading prints its age:
- eToro's equity, with `total_own_age_t` when it is older than the cells, and the cells with `age_t`; greyed past one hour (`BROKER_STALE_S`);
- each P&L of tier 1 or 2, and each estimate's price;
- each mark's badge;
- the brain's regime and trust (the hero had none);
- the cycle's read, and the calendar's (from its task's state);
- the rail's rule facts (`rule facts 2 min old`, cached 300 s);
- the Review's snapshot-based figures (`snapshot 2026-11-06`);
- every gate decision's time, with its date when it is not today.

MONEY READ and the "N s" ages tick in the browser.

### 5.5 Windows

Every count says its window: `now`, `24 h` (rolling, as the band's), `today` (since 00:00 UTC, as the cycle's), `since you last looked (09:42 UTC)`, `30 d`, `90 d`, `lifetime`. The windows nest, and the figures agree: a count since he looked is never larger than today's, and today's never larger than the 24 h one. Two figures with the same name and different windows never sit side by side without their windows. Today the page prints three win rates (51.9 % lifetime, 49.3 % 90 d, 50.0 % 24 h) with none named.

### 5.6 Colour means state

- **Jade and coral** mean polarity only (P&L, R, side, ▲/▼), and on money only for a figure eToro states or booked at its price (§5.3). An estimate is ink-1.
- **Amber** appears only for a watch light, a pending close, a stale stage or a late task, always with ⚠, ▲, a dot and words.
- **Coral ⨯** marks an alarm, with words.
- **The solid red** is only the REAL chip and edge; DEMO is the gold outline and PAPER the grey outline.
- **Eye green** is only a live dot, `● all clear` and the selected tab.
- **Violet** (`--sv-ai`) is a mind's own words: the Orc's note.
- **The weekday map** (R9) colours by |avg R| with a floor: under 0.05R it is neutral. Its count is text, never shade (today −0.004R over 37 trades is the darkest red).
- **A changed value** never flashes Eye green. Today the tab heads do, on a loss too, and the shell's sweep would do it to any colliding key (§6.2).

### 5.7 Named dashes

**The rule:** a dash means no figure here, and its line says why; 0 is a measured zero.

The eight meanings the map found:

| Meaning | Words on the page (title and R11) |
|---|---|
| Not measured (a source failed) | `not measured: <source> could not be read` |
| Not yet (first poll, today's snapshot) | `not yet: the daily snapshot is written at 23:30 UTC` |
| None (nothing closed, no cooldown) | `nothing closed in this world in 24 h` |
| No close path | `no close path exists for a row recorded by hand` |
| Ungraded | `closed with no R: no opening stop was recorded` |
| The gate was not asked | `the gate was not asked in 24 h` |
| No stop | `no stop recorded: no R, not a zero` |
| No weekday closes | `no close on this weekday in the window` |

Zeros that mean "none" become dashes with these words:
- the day metrics' fallbacks (`views_day.py:217, 264, 300, 304`: `[0, "… — no run recorded"]`). In the payload (OC0), a dash is the string `"—"` with its reason in the metric's words, never `null`: both painters call `fmt(metric[0])`, and `String(null)` prints "null" (`sv-day-live.js:57, 103`; `sv-day-scheme.js:43, 192`);
- the Eye's rule control "left at 0" (`views_eye.py:265-270`);
- `_pnl_24h`'s 0.00 when nothing closed.

### 5.8 Staff and viewer

- The staff rule stays as today: `request.user.is_staff` for `/api/day/live/` (`views_day.py:665`), and `core.views_book.is_staff` (:203) for the brain's concern text.
- Every staff-only cell and region is withheld in words, never dropped.
- R8 shows a viewer his own trade, gate, bot and alert lines only.
- The bot forms render only for a user the endpoint accepts (superuser): the endpoint refuses everyone else (`views_admin_hq.py:23-39`).

### 5.9 One figure, one reader

No figure on the page is computed a second way:
- the worlds are the rows' split (`open_by_world`), so the cards equal their rows on the page. The band and the Oculus print `_panel_detail`'s 20 s cache and may lag by up to 20 s, each with its age;
- the lights and words are the Horde's, and NEED YOU is the Horde tab's `alarms`;
- one alarm has one grade on both pages: a Horde alarm is the Oculus's ⨯, a Horde watch its ⚠ (§9);
- the signals' order and words are the rail's;
- the event touching a position is the care's (`event_for`);
- the stage states are `day_live_payload`'s (`_stale_after_s`, `views_day.py:122`);
- each bot's health is its heartbeat's, and its world is its account's (`_bot_truth`, one helper for the pill, the band, the Oculus and R7).

Each region's tests pin the reader it calls, with mock `wraps`.

---

## 6. Money safety

### 6.1 The money controls on the page, and their look

There are exactly two, and both exist today:

| Control | Where | Words, steps, PIN, endpoint (unchanged by every stage) | Look (UI plan §10) |
|---|---|---|---|
| CLOSE / RETRY CLOSE per row | R3's sticky right column | `data-sv-close-trade="<id>"` → `svCloseTrade` (`base.html:4119`) → `/positions/<id>/close/preview/` (`views_close.py:75`) → the close dialog (`base.html:4001-4116`) → `/positions/<id>/close/`. For a REAL or DEMO row (`venue:"live"`, `manual_close.py:412`) the dialog says "This flattens a LIVE position at the broker" and asks the Trading PIN; a paper row offers "CLOSE POSITION (ANYWAY)". "Connection lost — the close may have gone" when the answer is lost. The word for a close pending is RETRY CLOSE, as on /positions/ and in §10 | Neutral outline "CLOSE" (S1a's `.btn-danger` is the neutral outline); RETRY CLOSE under the amber `● Closing` state (dot and word); sticky on the right at every width, never scrolled off; 44 px on a phone. Never a red fill; never hidden behind a sideways scroll |
| TAKE TRADE / ADD / PASS | The rail's card, opened from R6 by `svRailFocus(id)` | The rail's own popup (`.sr-pop-btn-act`, `.sr-pop-btn-pass`) → `svTakeTrade` (`base.html:3950`) → `/signals/<id>/take-trade/preview/` → execute → the outcome lookup (`/api/take-trade/outcome/`, PR #94) | The rail's own look (§10: TAKE TRADE in the signal's side, PASS ghost-neutral). The home adds no button |

Not on the home, as today, and linked: CLOSE ALL (/positions/, "(whole book)"), the kill switch (Admin HQ form, PIN, reason), the Morgul brake and the switches (/ops/), bot on/off and Tick (/asset-bots/, Admin HQ; see P1).

### 6.2 The live hooks (§11) and S1a's inventory

- **Kept, unchanged:** `data-sv-close-trade`, `data-sv-position-row`, `svCloseTrade`, `SV.overlay`, `.sv-unknown`, `.up`/`.down`, `data-sv-count` (counts only; never on money), `data-flash`/`data-sv-noflash`, `#railSignals`, `#railSignalsBody`, `svRailFocus`, the `sv:eye-event` contract, and the page's own `#dayHome`, `#dayScheme`, `#dayPanel`, `data-day-*`. `#dayTiles` and `[data-day-tile]` leave with the tiles (OC1): none is in the §11 inventory, and `test_day_live`'s placement tests are updated deliberately.
- **Added (OC0), for F4 and F7:** `data-sv-live-key="{{ p.key }}.pnl"`, `.last` and `.pnlsrc` on every P&L, mark and P&L-words cell, with `data-mark-source` and `data-sv-at` beside them and `data-sv-noflash` on each. The key is the platform's row key (`bot-<id>`, `pos-<id>`), as on /positions/ (`portfolio_overview.html:252-255`; `views.py:1832`). F4's `marks` push uses the same key (feed spec §4.6.1). The §11 inventory takes them in.
  - **Why the row key:** the shell's sweep snapshots every `[data-sv-live-key]` in the document and pulses any whose text differs from its snapshot (`live_region.html:60-83`), turning the text `--accent` green (`sauron.css:4749-4753`), which §10 forbids on P&L. A key used twice differs from itself on every sweep, so it would flash every minute: `pnl:<trade id>` collides between an `AssetBotTrade` and a `Position` with the same id, and `mark:<symbol>` repeats when two rows share a symbol. Unique keys outside the sweep's regions never change inside one sweep, so they never pulse.
  - P4 also makes the sweep's pulse honour `data-sv-noflash`.
- **Retired with their markup (OC1):** `data-oc-metric`, `data-oc-hero`, `data-ws-events`, `#ocTabs`, `#ocTabBody`. None is in the §11 inventory. Their tests are updated deliberately (`test_page_carries_the_refresh_hooks` becomes "the parts carry `hx-get` and the eye-event map").
- **S1a's `tests/test_live_hooks_inventory.py`** pins hook counts per file: `data-sv-close-trade` in `_command_portfolio.html` (1) and `_eye_body.html` (1); `.up`/`.down`/`.sv-unknown` in `_command_*.html`; `data-sv-count` in `_command_bots.html` (5) and `_command_history.html` (3).
  - OC0 never lowers a recorded count in these files. It only adds.
  - OC1 moves hooks with their content: `data-sv-close-trade` goes from `_command_portfolio.html` to `_command/positions.html`. The recorded inventory is updated in the same commit, and a test asserts that the page's total per hook never decreases. `_eye_body.html` keeps its own, since it still serves /eye/.

### 6.3 Where a stage touches a money control or a money path, and what never changes

No stage changes a step, a PIN, an endpoint, a focus order or the behaviour of a money control. Five places come near one; each is listed with its proof.

1. **OC0 edits `dashboard/views_command.py`, which hosts `_open_book`.**
   - The chain: `live_book_value` imports `_open_book` (`portfolio/services.py:910`); `recalculate_exposure` writes the result hourly into `Portfolio.current_value` (`portfolio/tasks.py:95, 123-145`); that column is the paper limits' denominator (`portfolio/risk_gate.py:285-335`).
   - OC0 does not edit `_open_book`, `_reprice_legacy` or `live_book_value`. Only their callers pass the result through.
   - Proof: a test pins `live_book_value(user).value`, and the value `store_book_value` writes, on the fixture before and after.
2. **OC0 renders the BOTS fragment without a request.**
   - Its two POST forms carry `{% csrf_token %}` (`_command_bots.html:93-103`), which renders empty without a request, and hiding them needs the user. OC0 passes `csrf_token=get_token(request)` and `can_operate=request.user.is_superuser` into the fragment's context.
   - Proof: a superuser POST of the rendered Toggle form passes CSRF (a byte comparison is not enough), and a non-superuser's fragment holds no form.
3. **OC0 changes the armed pill's count** (`_bot_truth`).
   - DEMO-account bots leave the count. A config whose route cannot be read stays in it, so the pill never under-counts real money.
   - Proof: a live-mode config routed to a demo account is not counted; one whose account cannot be read is.
4. **OC1 changes one word and keeps CLOSE's reach.**
   - PORTFOLIO's `RETRY` becomes `RETRY CLOSE`, the word /positions/, the LIVE tab (`_eye_body.html:130`) and §10 use (`_command_portfolio.html:143`).
   - Every open row keeps its CLOSE on the home: rows past 12 fold in place, rendered with their buttons. Today's Eye table gave up to 50 rows (`views_eye.py:139-142`) and PORTFOLIO 20.
   - The old crypto bot's open rows have no close path today and keep none; /eye/ keeps listing them.
5. **OC1 and OC2 refresh the table that holds CLOSE.**
   - A desk swap waits while a dialog is open, a close is in flight, or the pointer or focus is in the table. The desk is re-fetched when the close answers (§4.1).
   - The row order never depends on a light or a price (§R3).

The proof for all five:
- a form and button diff: every `<form>`'s action, method, hidden inputs and PIN fields, and every `data-sv-close-trade` button's text, before and after (one intended change: RETRY → RETRY CLOSE);
- the close-dialog tests are re-run: `test_manual_close`, `test_close_advice`, `test_close_liveness`;
- the take-trade tests are re-run: `test_signal_acted_and_sizing`, `test_ticket_outcome`;
- the §10 rows in `test_money_controls_look.py` are re-run;
- a measured test: a refresh that changes one light, or one mark, leaves every CLOSE at the same y; a desk refresh during an open dialog is held until the dialog closes.

### 6.4 Proposals that change behaviour: each needs his OK, none is in a display PR

| # | Proposal | Why | If he says no |
|---|---|---|---|
| P1 | The bots' "Toggle" and "▶ Tick" leave the home page. The BOTS review shows states and "Bots page ›"; both controls stay on /asset-bots/ and in Admin HQ, unchanged | "Toggle" does not say on or off. "▶ Tick" runs a bot tick inside the web request, with no PIN or confirm, and a live bot can open or close REAL positions under its own gates (`asset_engine/runner.py:61-91`). Both land on Admin HQ, away from the desk | They stay for superusers exactly as today (OC0 hides them only from the users the endpoint refuses, and keeps their CSRF token) |
| P2 | Remember when he last looked at the home: a stamp of its own (`TraderProfile.pages_seen["command_seen"]`, the same map and endpoint as the sidebar's dots), written by the home's script when R8 has been on screen for 5 s in a visible tab, or by `Mark as read` | The map's seventh question. One small write per look, as the menu's dots already do on every page | R8 reads "the last 24 h" and says so |
| P3 | An index on `AssetBotTrade.closed_at` (a migration) | The 24 h and 90 d counts filter on it; 20 ms at six months for R2's read, more for HISTORY | The reads stay as measured; the budgets in §7.3 hold without it |
| P4 | The shell's polls stop while the tab is hidden or locked: `/api/live/health/` (10 s, never stops), the band sweep (`/getting-started/`, a full shell render, 763 KB/min), and the socket fallbacks that arm on lock. The sweep sends `X-Requested-With` (today it stamps the session like a click, `live_region.html:259`), and its pulse honours `data-sv-noflash` | Measured on the home: 20.8 requests/min locked against 12.7 visible | A shell PR for S1b's owner. The page's own polls stop either way (OC0) |
| P5 (optional) | Store eToro's equity once a day at 00:00 UTC (one stored reading a day) | The hero could then say how eToro's equity moved today. No stored history exists (`capital_truth.account_equity` reads `last_equity` only), so the hero shows no 24 h change | The hero shows no 24 h change, as in this plan |

P1 and P2 are his to decide now; the French note asks. P3, P4 and P5 are technical: each comes as its own small PR, with his OK asked in its deploy sheet (P3 adds a migration to run, P5 a beat entry).

### 6.5 No broker or model call

- **A source scan** (pnltruth's pattern) proves that `dashboard/views_command.py`, the new `dashboard/command_desk.py` and the part view import no broker adapter, no `client_for_symbol`, no model client and no `ai_agents` gateway. `account_used`, `broker_view` and `horde.board` read stored columns only.
- **At runtime,** the page and every part render with `EtoroTrader`, `client_for_symbol`, `http.client.HTTPConnection.connect`, urllib3's `urlopen` and the model gateway patched to raise.
- **The CLOSE preview's read of eToro's rate** is the dialog's, after his click, unchanged. In the map's run it was the only outbound attempt (to a dead local proxy).

---

## 7. Performance

### 7.1 Today (the map, SQLite, indicative)

- **The page GET (staff):** 128 queries, of which 74 are the shell's context processors and 54 the page's own. It takes 213 ms on the fixture and 403 ms at six months, and weighs 881 KiB (365 KB of it the shell's inline JS).
- **The LIVE fragment, loaded right after:** 121 queries (48 its own), 85 → 262 ms. **The first screen therefore costs 271 queries in three requests:** the page, LIVE, and `/api/day/live/` (22).
- **The other fragments:** PORTFOLIO 94 queries (20 own), 77 → 937 ms (20,181 closed rows read). HISTORY 86 (12 own), 48 → 154 KiB (10,139 points). BOTS 132 (58 own; about 7 per config). The metrics poll, every 45 s: 43 queries, 46 → 180 ms.
- **The open book is walked three times per GET** and per metrics poll (`_open_book` ×3, `unified_open_positions` ×3, `venue_pnls_for_rows` ×2, `live_book_value` ×2).

### 7.2 What the reused readers cost (measured for this spec, cold and warm)

`scratchpad/opscenter/work/fin_measure/tools/measure_parts.py`, through `manage.py shell` on a private copy of the scratch app (offline: every proxy pointed at a dead port), medians of 5. "Cold" clears the cache before each run. Fixture → six-month scale (`db_scaled.sqlite3`); logs in `scratchpad/opscenter/work/fin_measure/logs/parts_*.json`. The critique's own cold run (`critique_truth/tools/cold_*.json`) agrees on the board and `_panel_detail`.

| Reader | Queries cold / warm | ms cold (fixture → six months) | Note |
|---|---|---|---|
| `horde.board(user)` | 47 / 16 | 40 → 181 (warm 17 → 88) | Block B is cached 20 s on the book fingerprint: a 30 s poll finds it cold unless the Horde band is open |
| `account_used(user)` | 3 / 3 | 3 → 30 | eToro's cells, read directly |
| `_bot_truth(user, …)` | 18 / 18 | 14 → 127 | Not cached; in the `act` part only (the GET reuses the shell's `panel_bot`) |
| `rail_snapshot(request)` | 36 / 10 | 20 → 219 (warm 9 → 30) | Memoised per request; the shell's rail computes it in the same render; rule facts cached 300 s |
| `activity_events(since, 200)` | 6 / 6 | 11 → 17 | The drawer's own |
| `upcoming_events(24 h)` | 1 | ≤ 1 | The care's own |
| `day_live_payload(user)` | 17 / 17 | 13 → 48 | Already polled every 60 s |
| Closes 24 h split by `world_of` | 1 | 1 → 20 | P3 would index it |
| Exposure caps 24 h by reason | 1 | ≤ 1 | |
| `Orc` and `OrcIntent` aggregates | 2 | ≤ 2 | |
| The desk part's readers together | 51 / 20 | — | board, `account_used`, closes |
| The `act` part's readers together (staff) | 85 / about 59 | — | rail cold, `_bot_truth`, the rest |
| For reference: `_panel_detail(user)` | 44 / 4 | 49 → 342 (warm 3 → 20) | The shell's band; no part calls it. Under the test runner it never reads its cache (`context_processors.py:1026-1044`) |
| For reference: the shell's `ui_extras` | 53 | 62 → 49 | The shell's cost, not the page's |

### 7.3 Budgets (asserted in tests after `cache.clear()`; measured with the scratch harness in every PR)

| Measure | Today | After OC0 | After OC2 |
|---|---|---|---|
| Page GET, staff: total (own) | 128 (54) | ≤ 105 (≤ 30) | ≤ 160 (≤ 85: the board cold, the tiles' payload included) |
| The first screen: queries / requests | 271 / 3 | ≤ 180 / 3 (fragments lose the shell) | ≤ 160 / 1 (one GET holds the desk and the tiles) |
| `tab/live/` (OC0) → its regions (OC1+) | 121 | ≤ 50 | — (in the GET) |
| `tab/portfolio/` → Review Performance | 94; 937 ms at six months | ≤ 22; ≤ 150 ms | ≤ 22; ≤ 150 ms |
| `tab/history/` → Review History | 86; 154 KiB at six months | ≤ 14; ≤ 60 KiB | same |
| `tab/bots/` → Review Bots | 132 | ≤ 14 | same |
| The 45 s metrics poll → the `desk` part | 43 | ≤ 25 (one book walk; the world split by `open_by_world` over the rows it walks; no `_panel_detail`) | ≤ 55 per 30 s |
| The `act` part | — | — | ≤ 90 per 60 s (staff), ≤ 72 (viewer) |
| Page median, staff, six-month fixture | 403 ms (+ 262 ms LIVE, + 76 ms day) | ≤ 330 ms | ≤ 500 ms, one GET (the board alone is 181 ms cold) |
| The page's own requests/min: visible / hidden / locked in place | 2.33 / 0 / 2.4 (1.2 polls, each followed to /locked/) | 2.33 / 0 / 0 | 3 / 0 / 0 |

**The harness.** It is `scratchpad/opscenter/tools/` (fixture, scale, profile, capture, watch, watch_lock), plus `design/tools/` (`measure_readers.py`, `mock_build.py`, `mock_shot.js`, `crop.js`) and `work/fin_measure/tools/measure_parts.py`. It is copied to `claude/handoff` under `handoff/tools/opscenter/`, as the UI plan and the Oculus did. It is never merged, and the fixture password is read from the environment.

---

## 8. The stages

Each stage gives its goal, what he will see, its files, its conflicts and order, its tests (written first), its acceptance and its size. Screenshot pairs come from the harness, on the synthetic fixture.

### OC0. Truth and cost, today's look (ships now; no approval needed)

**Goal.** Fix what is false or wasteful on the page today, without waiting for the kit.

**He will see:**
- **Worlds.**
  - The USDJPY DEMO row reads DEMO, not REAL MONEY.
  - The armed pill counts bots on a REAL account only. `_bot_truth` reads each enabled live-mode config's world from the account its symbols route to (`broker_router.client_for_symbol`), and counts a config whose route cannot be read as REAL. Its state line says `LIVE · 2 bot(s) armed with real funds · 1 on a DEMO account` when one is. One helper serves the pill, the band, the Oculus and R7.
  - The hero gains three world lines from the band's own split, with the band's coverage words: on the fixture `REAL +18.86`, `DEMO +0.05`, `PAPER ≈ +163.50`, never added.
  - The tab heads lead with REAL and keep a count beside its own money: LIVE `5 REAL OPEN · +$18.86`, its title `11 open, all worlds`; BOTS `REAL realized 24 h`.
  - PORTFOLIO's UNREALIZED, average win, average loss and profit factor, and the Eye's "P&L 24h" and "P&L by asset class", become per world. The Eye's percentage of the limits book is dropped. DEPLOYED becomes per world, in USD.
  - ACT reads `open now: 5 real · 1 demo` (`views_day.py:522`).
  - The 24 h R, the session pulse, best and worst, and the recent fills carry a world chip per row and the label `all worlds · R only`.
  - HISTORY's per-rule P&L is split by world.
- **The book's name.** "PORTFOLIO VALUE" becomes `PLATFORM BOOK`, with no currency sign (`17,572.85 (EUR + USD, not converted)`), and its words: `cash typed on /setup/ (EUR) + the REAL and DEMO positions' notional (USD, hand-recorded rows too) + paper's open and realized P&L, not converted; not a balance`.
  - eToro's own line (equity, its world and its age) sits beside it, at today's size. Putting it first and larger waits for OC1 and his OK (decision 2).
  - The "· 24h" dash is named (`today's snapshot is written at 23:30 UTC`), with yesterday's change and its date beside it.
- **Profit factor.** It is computed as gross wins over gross losses. Today's figure, the average win over the average loss (`views_command.py:836`), stays beside it under its own name, payoff.
- **Numbers.**
  - Two decimals and the currency on every money cell (`position_summary.money`); DEPLOYED and the PORTFOLIO head no longer cut to whole units.
  - Prices through `{% px %}` (EURUSD 1.08412, not 1.0841); quantities through `position_summary.quantity` (1,000, not 1000.00000000).
- **Ages and windows.**
  - Ages: the regime and trust in the hero (`2 h ago`); the PORTFOLIO "last" column with its source and age; Sharpe, Sortino and MAX DRAWDOWN with their snapshot's date; gate decision times with their date when not today; best and worst with their date.
  - Windows: `lifetime` on PORTFOLIO's win rate, profit factor and averages; `Gate events · the last 30, any age`; "Top 5" shows five, or says three.
- **Agreement.**
  - `OPEN POS 11` against the Eye's `10 bot rows · 1 recorded by hand, not listed: no close path`.
  - `Active bots 8` becomes `8 configs · 5 enabled`.
  - ALIVE counts enabled bots from their heartbeat.
  - GATE 24H and DECIDE "today" carry their windows.
  - The donut is labelled `share of marked notional (all worlds) and cash typed on /setup/`.
- **Dashes and zeros.** Every `—` has a title naming its reason (§5.7). A footer `What a dash means here` lists the reasons on the page. The day metrics' "0 · … no run recorded" and the Eye's "left at 0" become dashes with words. In the payload, a dash is the string `"—"`, never `null`.
- **The bots tab.**
  - The world chip comes from the account (DEMO for a live-mode bot on a demo account). `LIVE-MODE` becomes `REAL-MONEY BOTS N · DEMO N`.
  - Health (ALIVE / IDLE / OFF) comes from each bot's heartbeat against its cadence.
  - "Toggle" and "▶ Tick" are not rendered for users the endpoint refuses; for a superuser they keep their CSRF token.
- **The hero pill.** The amber "● LIVE" becomes `bots: live mode` in ink-2. The topbar's red armed pill stays the one REAL marker, now counting REAL-account bots only.
- **Colour.** The weekday map shades by |avg R| with a 0.05R floor. The tab heads no longer flash Eye green.
- **ACT's words.** When a stage is off but its counts are not zero, the tile's title says `its scheduled tasks are off; these counts are the book's`.
- **Links.** The hero's right side gains "Oculus ›", "All positions · Close all ›" (/positions/), "Kill switch, with your PIN ›" (superusers) and "Brokers ›".
- **CLOSE.** The LIVE table's CLOSE column is sticky on the right (page-local CSS, today's styles), so it is never scrolled off. The words and the dialog are unchanged; S1a turns `.btn-danger` neutral.
- **Stamps.** The Eye footer's "Auto-refresh every 10s" is gone on /command/, replaced by `read HH:MM:SS UTC · refreshed on fills`.
- **The page's own poll.** The metrics poll sends `X-Requested-With`. It no longer stamps the session (today it does, every 45 s, so the server's idle backstop never fires while /command/ is visible), and it gets a 423 when locked. It stops on 423, on a redirect, and while hidden.
- **Cost.**
  - Each tab is lighter: LIVE 121 → ≤ 50 queries, PORTFOLIO 94 → ≤ 22 and 937 → ≤ 150 ms at six months, HISTORY 154 → ≤ 60 KiB, BOTS 132 → ≤ 14.
  - The page's own polls stop while hidden or locked.
  - The page's CSS is rendered once.

**Files:**
- `dashboard/views_command.py`:
  - one open-book walk per request: `shown_open_rows`, `live_book_value(book=…)` and `shown_book(venues=…)` are passed the walk the caller already holds, as PORTFOLIO already does. `_open_book`, `_reprice_legacy` and `live_book_value` themselves are not edited (§6.3);
  - the world split from `open_by_world` over the rows it walks, never `_panel_detail`;
  - REAL-first tab heads, with titles;
  - PORTFOLIO's lifetime stats per world, the profit factor and payoff, and the top five, as database aggregates;
  - HISTORY's cumulative R per day;
  - BOTS aggregates in three grouped queries, the world from the account, health from the heartbeat;
  - money, quantity and price formatting through `position_summary.money`, `quantity` and `{% px %}`;
  - fragments rendered with `render_to_string` and no request; the BOTS fragment gets `csrf_token` and `can_operate`.
- `dashboard/views_eye.py`: `world` (and `metadata`) on each row dict; P&L by class per world, without the percentage; dashes with reasons.
- `dashboard/views_day.py`: the ACT words (`:522`, `open_live` split by `world_of` over the open rows already counted); the fallbacks as `"—"` with their reason (`:217, 264, 300, 304`).
- `core/context_processors.py`: `_bot_truth`'s world split (display only; §6.3).
- `templates/dashboard/command.html`: the hero's world lines and labels, the links, `{% block extra_css %}` moved out of `{% block content %}` (`:480`), and the metrics poll (`X-Requested-With`; stops on 423, a redirect or hidden).
- `templates/dashboard/_command_live.html`, `_command_portfolio.html`, `_command_history.html`, `_command_bots.html`, `_eye_body.html`: content only (labels, windows, ages, chips, dashes, the row keys of §6.2), in today's styles.
- `tests/test_command_truth.py` (new), `tests/test_command_metrics.py`, `tests/test_command_center.py`, `tests/test_day_live.py` (the ACT words; the dash strings), `tests/js/command_metrics.test.js` (new).
- `deploy/RUNBOOK.md`: "## The Operations Center" (worlds, the platform book's words, what each tab's window is).

**Conflicts.**
- No branch in flight edits the /command/ files. `core/context_processors.py` is the shell's: OC0 adds keys to `_bot_truth` and changes the count of its `live` key, and S1b rebases on it.
- `claude/oculus0` edits RUNBOOK.md (another section): a trivial rebase.
- `views_day.py`'s ACT words and its dash strings also reach the Oculus's cycle map (O2a, not built), which takes the payload as it is (§9).
- S1a's hook inventory: OC0 only adds hooks in these files (§6.2). If OC0 merges first, S1a's recorded counts still hold. If S1a merges first, OC0 rebases with no count lowered.
- F4 later patches the P&L cells through the row keys OC0 adds; F4's file list names `_command_portfolio.html`, which OC1 retires (§9).

**Tests (written first):**
- **Worlds.**
  - A DEMO row renders `sv-world--demo` on `/command/tab/live/`, and a REAL row `sv-world--live`.
  - With one REAL (+10.00), one DEMO (+1.00) and one PAPER (+100.00) row, open and closed, no money cell anywhere in the page or its fragments prints a sum (11.00, 101.00, 110.00, 111.00) or an average across worlds (5.50, 50.50, 55.00, 37.00).
  - Average win, average loss, profit factor and the by-class P&L are per world.
  - The hero's three lines equal `panel_open_pnl_live/_demo/_paper`.
  - ACT splits real and demo.
  - The pill: a live-mode config routed to a demo account is not counted; one whose route cannot be read is.
- **Money paths.**
  - `live_book_value(user).value`, and the value `store_book_value` writes, are equal before and after on the fixture.
  - A superuser POST of the rendered Toggle form passes CSRF; a non-superuser's BOTS fragment holds no form posting to `/admin-dashboard/asset-bots/`.
- **Words.**
  - The platform book's label carries its words and no currency sign; eToro's line sits beside it when an eToro row exists.
  - The profit factor is gross wins over gross losses, and the payoff is named.
  - The "· 24h" dash names the 23:30 snapshot.
- **Numbers.**
  - No 8-decimal value appears in the HTML; prices use the instrument's decimals.
  - Every money cell has two decimals and a currency; 34,481.4 prints as 34,481.40.
- **Windows and ages.** Each statistic's label carries its window; the regime, the snapshot-based cells and the gate times carry their age or date.
- **Dashes.**
  - Every `—` in the page and its fragments carries a title, and the footer lists them.
  - The payload's dashes are strings with words, and both painters print no "null" (node).
- **Bots tab.**
  - A live-mode config on a demo account reads DEMO.
  - Health comes from `last_tick_at`, not from trades.
- **Cost.**
  - Query budgets after `cache.clear()`: page ≤ 105, live ≤ 50, portfolio ≤ 22, history ≤ 14, bots ≤ 14, metrics ≤ 25.
  - Each fragment's HTML is identical with and without the shell's context processors, the CSRF token aside.
  - PORTFOLIO's aggregates equal the old Python loop on a fixture with unknown, zero and legacy rows.
  - HISTORY's per-day cumulative R equals the per-close line at each day's end.
  - The BOTS aggregates equal the per-config loop.
- **Node.** The metrics poll sends `X-Requested-With`, stops on 423 and on a redirected response, schedules nothing while hidden, and resumes on `sv:pin-unlocked`.
- **Kept:** the meaning tests of `test_command_center` (19), `test_command_metrics` (46) and `test_day_live` (57).
- **Updated deliberately,** each with its reason:
  - the tests that pin the summed head words (`test_tab_bar_metrics_visible`; `test_counts_positions_and_bot_trades_together` keeps counting both books);
  - the ALIVE words;
  - `test_day_live.py:298`, which pins the zero of "Morgul guards ran — no run recorded" (now a dash with words);
  - the CSS position test, if any.

**Acceptance (measured on the scratch harness):**
- The map's findings 1, 2, 3, 5, 6, 7 (display part), 8 (the page's part), 9, and 10 (numbers and CSS) are resolved, and so are the pill and the profit factor.
- The queries above. PORTFOLIO at six months ≤ 150 ms.
- The page's own requests/min: 0 hidden, 0 locked (`watch_lock.js`); no session stamp from the page's poll (the server's idle backstop fires on an idle visible tab).
- Screenshot pairs: `command_staff_live_1440x900(_full)`, `…_portfolio…`, `…_bots…`, `command_viewer_bots_1440x900`.

**Size:** M.

### OC1. The look, and the order (after S1a merges; supersedes UI plan S2.3)

**Goal.** The page he lands on puts his money and his positions first, on S1a's kit, readable, in one page.

**He will see:**
- R1 with the cells the page already reads: EQUITY AT ETORO and AVAILABLE AT ETORO first and larger (decision 2), REGIME, BEAT and MONEY READ. NEED YOU reads `closes pending 1 · no stop 0 (2 of the Horde's checks)`.
- R2, the three world cards.
- R3, one positions table for the whole book: in its stable order, with CLOSE sticky, its two OC1 lights, and RETRY CLOSE as the word for a close pending.
- R4, the cycle strip.
- R9 Review: PORTFOLIO, HISTORY and BOTS as tabs, world and window chosen, loaded on demand; the platform book in its own box.
- R10, the loop folded at the foot by default, and drawn still when opened; R11, the dashes and the stamp.
- Inter for words and JetBrains Mono for numbers; nothing under 11 px; contrast ≥ 4.5:1; no log lines behind numbers (S1a).
- The LIVE tab is gone: every one of its facts has a new home (Appendix A).

**Which part of S2.3 this supersedes.** S2.3 said:
- a hero with the portfolio in mono hero, the 24 h change with its source, and the REAL / PAPER / DEMO split;
- the tiles never truncated;
- the loop calmer and collapsible, with THE BEAT beside it;
- tabs and tiles on the kit;
- the positions table on the number rules.

OC1 keeps all of it, the calmer loop included (drawn still when open), except four things:
- the hero leads with eToro's own figures, and the platform book moves to Review (decision 2);
- the loop and THE BEAT fold at the foot instead of staying in place (decision 3);
- the four tabs become one page (decision 4);
- the hero's 24 h change leaves it. No stored eToro equity history exists, and the platform book's change is not his money's change. P5 would give one.

S2.3 is therefore dropped from the UI plan, and its acceptance is carried here: 0 ellipsised tiles at 1,280 with the rail open (today 30), no table scrolling sideways at ≥ 1,440, and pairs 01/01b at 1,440 and 1,920.

**Files:**
- `templates/dashboard/command.html`, rewritten on the kit.
- New `templates/dashboard/_command/`: `hero.html`, `worlds.html`, `positions.html`, `cycle.html`, `review.html`, `loop.html`, `footer.html`.
- `_command_portfolio.html`, `_command_history.html` and `_command_bots.html` become the Review tabs. `_command_live.html` is retired; its hooks and facts are re-homed (§6.2, Appendix A).
- New `static/css/sv-command.css` (tokens only). The page's 12.3 KB `<style>` leaves.
- New `static/css/sv-stage.css`: the stage tile and its compact variant, the status-cell row, the three-world card (§3.4).
- `static/css/sv-kit.css`: `.sv-col-act`, `.sv-p1..3` and `.sv-world--none`, additive (§3.4).
- `static/css/sv-day-scheme.css`: the ring's text at ≥ 11 px at every width (its SVG text scales with the ring: the folded ring gets a `min-width` that keeps its labels at 11 px, and scrolls inside its own box below that, never the page).
- `static/js/sv-day-live.js`: one change, `data-day-collapsed-default` (R10), node-tested. Its tile painter, scoped to `#dayHome`, finds no tile.
- `dashboard/views_command.py`: `command_desk(user)`, which builds the desk regions from the reads OC0 left; the part view `partials/command/<part>/` (`desk`, `cycle`, `review`).
- `dashboard/urls.py`: one path.
- New `static/js/sv-command.js`.
- New `tests/test_command_look.py`, `tests/test_command_parts.py`, `tests/js/sv_command.test.js`, `tests/js/sv_day_live_fold.test.js`.
- `deploy/RUNBOOK.md`.

**Conflicts.**
- After S1a (tokens, kit, `qty`, `src_name`, neutral `.btn-danger`). OC1's additions to `sv-kit.css` are additive; any S2 stage editing the kit at the same time rebases trivially.
- Independent of S1b; measured again after S1b (overlap 0). Before S1b, OC1 adds 96 px of end padding so the page's last rows scroll clear of Gollum and the Horde.
- OC1 creates `sv-stage.css` before the Oculus's O2a, which loads it (§9).
- S1a's hook inventory is updated in the same commit (§6.2).
- F4 and F7 later write into the row keys OC0 added.

**Tests:**
- **String:**
  - no `font-size` under 11 px in `sv-command.css`, `sv-stage.css` or the partials;
  - no `#3a6850` or `--text-muted`;
  - no inline `style=` except computed widths;
  - no money cell without a currency;
  - no world-summed cell (the OC0 test, kept);
  - `hx-get` on every part, and none on a staff-only part for a viewer.
- **Render:**
  - the regions in order;
  - the REAL edge on real rows only;
  - CLOSE inside a sticky cell on every row with a close path, folded rows included;
  - RETRY CLOSE on a close pending;
  - every hook of §6.2 present the right number of times.
- **Parts:**
  - each part renders without context processors;
  - each answers 423 to a locked `HX-Request` and never stamps the session;
  - a viewer's GET of a staff-only part answers 403;
  - query budgets per part, after `cache.clear()`.
- **Node:**
  - a 423, a redirect or `session_locked` stops a part;
  - hidden schedules nothing;
  - `fill_close` re-fetches `desk` once within 800 ms;
  - other kinds do not;
  - a `desk` swap is held while an `SV.overlay` dialog is open, while a close is in flight, and while the pointer is in the table, and lands after;
  - the ages tick with no request;
  - the loop starts folded with no stored choice and keeps his choice when one is stored; open, the ring's animations are paused.
- **Measured** (Chromium where present, the `_chrome()` pattern) at 1,280, 1,440, 1,920 and 2,560, rail closed and open:
  - first number y;
  - CLOSE inside the viewport on every row;
  - a refresh that changes one light leaves every CLOSE at the same y;
  - 0 text under 11 px;
  - every text role ≥ 4.5:1 on its computed background;
  - 0 ellipsised elements among the tiles' names and metrics, the hero's labels and values, the world cards' figures, and the positions table's symbols, figures and buttons (a secondary meta line may be cut only when its full text is in the row's detail);
  - no table or page scrolling sideways at ≥ 1,440;
  - the ring's text ≥ 11 px when open.
- **Kept:** every meaning test of OC0 and of `test_day_live` (the payload's).
- **Updated deliberately,** each with its reason in the commit:
  - `test_day_live`'s placement tests (`test_it_sits_between_the_hero_and_the_tabs`, `test_the_section_and_its_parts`): the tiles now sit after the desk and the ring folds at the foot; the payload tests are untouched;
  - `test_command_center`'s tab tests (`test_all_four_tabs_present`, `test_tab_buttons_use_htmx`, `test_query_param_selects_tab`, `test_no_bots_defaults_to_portfolio`, `test_enabled_bot_defaults_to_live`, `test_invalid_tab_falls_back_to_live`): one page with three Review tabs. `?tab=portfolio`, `?tab=history` and `?tab=bots` keep working (they open that Review tab, scrolled into view), and `?tab=live` opens the top, so bookmarks still land;
  - `test_command_metrics.test_page_carries_the_refresh_hooks` and `test_page_listens_on_the_shared_eye_event`: the parts' `hx-get` and the eye-event map replace the JSON painter.

**Acceptance (today's shell plus S1a, 1,440 × 900):**
- The positions table's top is at y ≤ 460 and its first row at y ≤ 540 (today the first row is at about y = 3,280 on the LIVE tab). After S1b: ≤ 380 and ≤ 450 (the mock: 378 and 446).
- Page height ≤ 3,200 px (from 5,356); after OC2, ≤ 3,600 (the mock: 3,555).
- 0 text nodes under 11 px (today 232 of 578 on LIVE).
- 0 roles under 4.5:1 (today 221 nodes).
- 0 ellipses, as defined above, at 1,280 with the rail open (today 30).
- The page's own requests/min ≤ 3 visible (none for the loop while it is folded), 0 hidden or locked.

After S1b: fixed-chrome overlaps 0. Screenshot pairs: staff and viewer at 1,440, 1,920 and 2,560, the rail open at 1,280 and 1,440, and 390.

**Size:** L.

### OC2. The desk (after OC1)

**Goal.** The questions a trader asks at his home, answered from readers that already exist.

**He will see:**
- R3 with the Horde's lights and words on every row, in place, the holder on the rows whose reason fits one line, the close given up as a row, and "At eToro, not on Sauron" under the table.
- R1's POSITIONS · NEED YOU from the Horde's alarms, plus NEXT EVENT, SIGNALS and REGIME from the `act` part.
- R5, the market on what he holds and watches, with the events ahead and their touches.
- R6, signals to act on, each opening its rail card.
- R7, bots and Orcs.
- R8, since he last looked (or the last 24 h without P2), and the line under the worlds.
- R4, the cycle, after R8.
- The parts `act` and `desk` refreshing as §4.2 says.

**Files:**
- New `dashboard/command_desk.py`. It holds the assembly of the new regions only, and imports without editing:
  - `horde.board` and `light`;
  - `signal_rail.rail_snapshot`;
  - `activity_feed.activity_events`;
  - `position_care.upcoming_events` and `event_for`;
  - `etoro_used.account_used`;
  - `context_processors._bot_truth` (after OC0's split);
  - `position_summary.world_of` and `open_by_world`;
  - `safety.heartbeat_age_seconds`;
  - `bot_program.orcs.models`;
  - `bot_program.orchestrator_models`.
- `dashboard/horde.py`: additive seat fields, with the Horde's own tests. No key is changed or removed; `sv-horde.js` ignores keys it does not read. The fields are:
  - `mark.age_s` and `mark.feed` (today the seat's mark carries only `word`, `horde.py:1246-1248`);
  - `money.pnl_at` (`_live_row` has it, `views.py:1943`; the seat's `money` does not);
  - words for paper and legacy seats, which carry no P&L words today (`horde.py:1502-1510`).
- `dashboard/views_command.py`: the `act` part, which takes in `cycle` for staff.
- `templates/dashboard/_command/market.html`, `signals.html`, `bots_orcs.html`, `since.html`; `positions.html` (lights, stragglers, unseated).
- `static/js/sv-command.js`: the `act` part and its events; R8's 5 s stamp (P2).
- `dashboard/views.py`: `nav_activity_json` accepts `command_seen` as a stamped page that lights no dot (only with P2).
- `tests/test_command_desk.py`, `tests/test_command_parts.py`, `tests/test_the_horde.py` (the additive fields).
- `deploy/RUNBOOK.md`.

It may ship as two PRs: OC2a (R3 lights and lists, R1, R5, R8) and OC2b (R6, R7, R4's move).

**Conflicts.**
- After OC1.
- The Horde's board shape is extended, never changed. A test on this side pins the keys it reads (`light`, `money`, `mark`, `world`, `holder`, `mission`, `stragglers`, `unseated`, `tab.alarms`), so a Horde change fails here, not silently.
- `_bot_truth` and `light` are private names: if one is renamed, the desk test fails at once. A public alias is a one-line follow-up.
- PR #90's rail is merged. The Orcs' minds are ON and their intents in shadow: R7's words follow O2c/O2d when those land.
- C1–C3 do not change any figure here: the home prints worlds from the rows, not the gate's live side.

**Tests:**
- **Sources pinned:** each region calls its reader (mock `wraps`).
- **No second rule:** the event that touches a row is `event_for(row, events=[ev], before_minutes=1440)`'s; the worlds are `open_by_world`'s; the order of R6 is the rail's; the cards equal their rows on the page.
- **Needs you:**
  - NEED YOU equals the Horde tab's `alarms` (seat alarms plus stragglers), and the watch count sits beside it, never in it;
  - a calm book prints `● all clear · 8 checked`, an empty one `no open position`;
  - the rows keep their order when a light changes.
- **Lists:** a straggler renders as an alarm row with `Story ›` and no CLOSE; unseated rows render with the Horde's words and no CLOSE.
- **Events:** an unreadable calendar renders a named dash, never "no event".
- **Worlds:** each card equals the sum of its rows on the page, and equals the band's `panel_open_pnl_<world>` on the fixture after `cache.clear()`; a row with no USD stamp is named apart, in its own currency, and added nowhere.
- **Signals:** no TAKE TRADE, ADD or PASS button and no `svTakeTrade(` in the home's HTML; every row carries `data-signal-id` and calls `svRailFocus`; no "adds to" or "against" anywhere.
- **Since you last looked:**
  - with P2, the GET writes the stamp into the part's URL, and the part never re-reads `pages_seen`;
  - a `since` older than 7 days or later than now is refused;
  - the stamp moves only after 5 s on screen, or on Mark as read;
  - without P2, the region says `the last 24 h`;
  - a viewer never sees ai, pipeline or system lines.
- **Bots:** health from the heartbeat; a demo-account bot reads DEMO; the exposure caps' words never form a rate, and never name book limits or the daily stop.
- **Orcs:** `nothing placed` from `OrcIntent.mode` counts, never from `minds_on`; the counts equal `OrcIntent` today by kind; the note passes `_orc_plain`.
- **No broker or model call:** the source scan and the runtime patches (§6.5).
- **Budgets, after `cache.clear()`:** desk ≤ 55; act ≤ 72 for a viewer and ≤ 90 for staff; page GET ≤ 160.

**Acceptance:**
- On the fixture, NEED YOU lists the fixture's alarms: the CLOSE_PENDING row (GBPUSD in the map's fixture), the real or demo row without a stop, and any close given up.
- R5's prices equal the band's and the watchlist rail's for the same instruments, except stand-ins: the band's XAUUSD is the GC=F future, while R3's mark is eToro's.
- R6's first rows are the rail's first `held` cards.
- First screen ≤ 160 queries in 1 request (today 271 in 3).
- Page median at six months ≤ 500 ms.
- 3 requests/min visible, 0 hidden or locked (network log).
- 0 broker or model calls (pinned).
- Screenshot pairs as in OC1, plus the needs-you rows empty against full.

**Size:** L (or M + M as OC2a, OC2b).

### OC3. Feed-grade live (F4, then F7)

**Goal.** P&L and prices on the home at the eToro feed's grade, live, with fewer requests.

**He will see:**
- **From F4:** REAL rows' P&L, and the REAL card, moving with eToro's own figure about every 11 s while a held market is open (every 60 s when every held market is shut). DEMO rows and the DEMO card follow about every 30 s while a DEMO row is open. The words are F4's tiers (`eToro's own · N s`, `eToro's figure · N min ago`, `awaiting eToro`), and a total says `partial k of n` when a row has no eToro figure.
- **From F7:**
  - the marks and R5's prices moving with the push;
  - badges degrading in the same frame as the grade;
  - the price cells' background wash (never their text colour);
  - "live prices paused" greying every badge.
- The `desk` part at 60 s instead of 30 s: 2 requests a minute in all.

**Files:**
- `static/js/sv-command.js`: subscribe to F4's `marks` and F7's events through `sv-venue.js`'s public hook. Re-sum a world's card from all its rows, folded ones included; never add two worlds. Drop the desk timer to 60 s while the push is healthy.
- `templates/dashboard/_command/positions.html` and `worlds.html`: no new hooks (OC0 added them).
- Tests.

**Conflicts.** After F4, then F7. F7 owns `sv-venue.js`, the shell's `onmessage` and the paused chip; the home only listens.

**Tests:**
- F4's and F7's payload fixtures are replayed into `sv-command.js`.
- A world card always equals the sum of its rows (folded ones included) after any sequence of pushes, and a DEMO push never moves the REAL card.
- No cell moves backwards in eToro's time (F4's I4 rule).
- A badge degrades in the same frame.
- The desk timer returns to 30 s when F7's display switches are OFF.
- An unknown grade renders a dash with its title, never LIVE.

**Acceptance:**
- The F7 fault test: `./deploy/dc stop stream-etoro` degrades the badges at once with growing ages, and no P&L or price cell jumps or steps back. Bringing the stream back recovers by the feed's trust rule.
- 0 requests for prices from the home while the push is up (network log).

**Size:** S–M.

---

## 9. Sequencing with the work in flight

| Order | Stage | Can start | Must wait for | Yields to |
|---|---|---|---|---|
| 1 | OC0 | Now (base `ede54d0`) | Nothing | S1a's hook counts (only adds); `claude/oculus0` (RUNBOOK); S1b (`_bot_truth` keys) |
| 2 | P3, P4, P5 (own small PRs) | Now | His OK in each PR's sheet; P4 belongs to the shell (S1b's owner) | S1b (P4 edits shell pollers) |
| 3 | OC1 | After S1a merges | S1a | S1b (shell lines only; OC1 edits none); the Oculus's O2a loads OC1's `sv-stage.css` |
| 4 | OC2 (a, b) | After OC1 | P2 for R8's stamp (optional) | F4/F7 (they later move its cells), O2c/O2d (the Orcs' words) |
| 5 | OC3 | After F4, then F7 | F4, F7 | — |

C1–C3, when they land, change nothing on the home's figures (it prints the rows' worlds). They change the gate's live side, which the home never prints.

The Oculus and the home ship in parallel and never edit each other's page files. They share `day_live_payload` (read by both, owned by `views_day.py`), the Horde's board, the band's worlds, and `sv-stage.css` (created by OC1, loaded by O2a). A change to any of these is tested on both pages.

**Corrections this plan asks of other plans.** Each owner decides; none is made here.
- **The Oculus (O1, O2a), its spec and its mock.**
  - DEMO is never "eToro's own": tier 1 refuses another world's holdings (`services.py:1197-1201`). Before F4, REAL is not either (§5.3). The Oculus mock's DEMO "eToro's own · 8 s" should read as a tier 2 or 3 estimate, and its REAL one as an estimate too until F4.
  - The account currency comes from `account_used`'s `currency` (USD on the fixture), not `€`. The Oculus mock prints `€10,453.61`, and its status bar's PORTFOLIO shows eToro's equity, not S1b's platform book.
  - A close pending is the Horde's alarm. The Oculus's Needs you grades it ⚠ (a Morgul warning), while the Horde grades it ⨯. One mapping, Horde alarm = Oculus ⨯ and Horde watch = Oculus ⚠, tested by rendering the same fixture on both pages.
  - The calm words are `● all clear` on both pages.
  - LEARN's metric is "trades graded today", not "rules graded", and SEE's quote age is in whole minutes, not seconds (`views_day.py:214-216, 546-549`).
  - The stage tile, the status-cell row and the three-world card come from OC1's `sv-stage.css`, which O2a's file list loads.
  - O2a's "money ≤ 6" budget must be measured cold: `_panel_detail` costs 44 queries cold and is never read from its cache under the test runner.
  - The payload's dashes become strings with words in OC0 (§5.7). O2a's reader takes them as they are.
  - Both mocks show one instant. The home mock is re-clocked to 12:53:20 UTC, where US CPI at 13:30 is 37 min away and AAPL is shut; at its old 14:53 UTC, "US CPI 15:30" and "AAPL closed" were both false in winter. The Oculus mock, still at 14:53:20, should follow.
- **S1b (the shell).**
  - The status bar's OPEN P&L prints REAL, DEMO and PAPER apart, never a summed cell.
  - PORTFOLIO (the platform book) wears no currency sign: `60,809.79 EUR+USD`.
  - The armed pill reads "Real armed", its count from `_bot_truth`'s REAL-account split (OC0).
  - P4's sweep header and pulse rule.
- **S2.2 (/positions/).** Reuse `.sv-col-act`, `.sv-p1..3` and `.sv-world--none`. One table partial with R3 is offered.
- **The Positions board** (`preview/project/Positions.dc.html`): its DEMO rows as estimates, as above.
- **F4.** It patches `_command/positions.html` and `worlds.html` through OC0's row keys, not `_command_portfolio.html`, which OC1 retires.
- **C1–C3.** The close dialog says "This flattens a LIVE position at the broker" on a DEMO row (`manual_close.py:412`: the venue is "live" for every non-paper row). That is theirs to word; the home does not touch the dialog.

---

## 10. Decisions, risks, and what is not in this plan

**Decisions for him** (in the French note):
1. The order of the blocks (§3.1).
2. eToro's own figures lead, first and larger; the platform book moves to Review, in its own box, with its words.
3. The loop, THE BEAT and the 24-hour strip fold at the foot.
4. One page instead of four tabs.
5. P2 (remember when he last looked at the home).
6. P1 (the bot buttons leave the home).

**Decisions taken here, and why:**

| Decision | Why |
|---|---|
| The positions table is the Horde's seats, with its stragglers and unseated rows | The richest per-position reader already exists, prints /positions/' digits, and already knows the closes given up and what eToro holds outside Sauron |
| A stable row order (world, then the newest), lights in place | A light or a price must never move a CLOSE under his pointer (UI plan rules 1 and 7); NEED YOU and the header reach the lit rows |
| NEED YOU counts the Horde's alarms; watch is counted beside | An hour before every US print the care lights every row it manages in USD as WATCH; counting those would make the cell noise. The Horde's own "need attention" counts alarms only |
| The worlds are the rows' split | The cards can never disagree with the rows on the same page; one split helper (`open_by_world`) |
| eToro's cells read directly (`account_used`), never through the band's cache | 3 queries, cold or warm; the band's cache is cold on most polls and never read under tests |
| TAKE TRADE only through the rail's card | One place to act on a signal, with its words and PIN; the home lists, the rail acts |
| The seven stages as a strip after the desk, linking to the Oculus | One vocabulary; the depth lives in one place; the home's job is the desk |
| Parts under `/partials/`, server-rendered, the Oculus's mechanism | One mechanism for both pages; 423 on lock; no session stamp; no formatting duplicated in JS |
| The review on demand, never polled | It changes per close and per night; polling it costs without informing |
| The loop folded, not deleted | The platform keeps every feature (UI plan rule); he can open it; the Wall keeps it too |
| Budgets set cold | A warm budget hides two polls in three |

**Risks:**
- **More queries per minute than today** (≈ 200 cold against 79), for far more on the page (§4.5). The desk can go to 60 s if it matters, with fills and closes still refreshing it at once.
- **The Horde's board is computed per call**, and its Block B is cached 20 s. The home's desk part and an open Horde band each compute it. Caching the board for the desk's 30 s was considered and rejected: the Horde does not cache its board on purpose ("marks move inside the fingerprint's blind spot"), and a 30 s copy would let the band and the desk show two marks for one row.
- **Watch lights before every US print.** Every row the care manages in USD, or with a USD leg, turns ⚠ in the hour before a high-impact USD event. The page shows the Horde's lights as they are; NEED YOU does not count them.
- **`_bot_truth` and `light` are private names.** The tests pin them, so a rename fails loudly. Public aliases are one-line follow-ups.
- **Wider faces in OC1.** Inter and JetBrains Mono are wider; the measured tests catch truncation at 1,280 with the rail open.
- **The ring's text at 11 px** needs a minimum ring width. Below it, the folded ring scrolls in its own box, never the page. It is folded by default and not drawn on a phone.
- **His habit.** The page he has landed on for months changes order. The French note shows him the order first and asks for his OK before OC1.

**Not in this plan:**
- No new money control on the home: no TAKE TRADE button, no CLOSE ALL, no kill switch, no toggle.
- No change to what the engine, the bots, the Orcs, the desk or the gates read.
- No new writer except P2's stamp and P5's daily equity reading, each behind his OK; no new index except P3, as its own PR.
- No change to /positions/, the Oculus, the rail or the Activity drawer; the Horde gains additive fields only (OC2). The home reads them.
- No drawing tools on the home (S5 is the instrument page's), and no chart on the home outside Review.

---

## Appendix A. Where each of today's elements goes

| Today | New home | Changes |
|---|---|---|
| Hero PORTFOLIO VALUE (+ "· PLATFORM BOOK") | R9, the platform book's own box | Named for what it is, no currency sign; eToro's own leads R1 |
| Hero "· 24h" | R9 (snapshot-dated); the hero has none (P5) | Named dash in OC0; leaves the hero in OC1 |
| Hero eToro line (`broker_account.html`) | R1 EQUITY AT ETORO, AVAILABLE AT ETORO; R2 REAL account line | With its age, world and currency; eToro's account P&L and what it holds outside Sauron |
| Hero REGIME, BRAIN TRUST | R1 REGIME; R5 the brain | With the report's age |
| Hero ● LIVE pill, UTC clock, ⟂ WS | The topbar's armed pill and clock; MONEY READ | The amber pill goes (one REAL marker, now counting REAL-account bots only) |
| A DAY OF SAURON tiles | R4, after R8 | Compact; "ran X ago" kept; links to the Oculus |
| The ring, THE BEAT, the 24-hour strip | R10 (folded by default, drawn still when open) | Text ≥ 11 px |
| Tab heads LIVE / PORTFOLIO / HISTORY / BOTS | R2 (worlds), R9 tabs | No summed money |
| LIVE: REGIME / conf / trust / age | R1, R5 | |
| LIVE: GATE 24H | R7, the exposure caps' line | Rejects by cap, 24 h; allows never a rate |
| LIVE: DEPLOYED, cash % | R9 Performance: exposure now (notional at the marks), per world | Per world, USD |
| LIVE: ETORO USED | R2 REAL account line (margin used, outside Sauron's rows) | eToro's own words |
| LIVE: OPEN POS, bots enabled | R3 header; R7 | |
| LIVE: 24H R, W/L, closed, win % | R2 realized 24 h; R7 each world's 24 h (realized, realized R, W/L); R9's `24 h` window | Per world |
| LIVE: RULES active/paused/research | Oculus R6 (the ladder); R7 links | Platform-wide, staff's; a viewer reads `staff only` |
| LIVE: CONCERNS | R5 the brain (staff) | With its age |
| LIVE: Session pulse, Best/Worst 24h | R9 History (the session pulse, best and worst of the window) | Dated, per world |
| LIVE: Recent fills | R8 | With world chips |
| Eye stat strip | R2, R7 | Split per world; counts agree |
| Eye theme exposure, per currency, sector | /eye/exposure/, linked from R7 ("Exposure caps ›") | Not on the desk; the brain's concern about a cap links there |
| Eye Open Positions + CLOSE (up to 50 bot rows) | R3 | One table; CLOSE sticky on every row; rows past 12 fold in place, with their buttons |
| Eye legacy crypto `BotTrade` rows (no close path) | /eye/, which keeps them; R3's foot names them when any is open | One count on the home |
| Eye Recent Gate Decisions (30) | R8 (refusals since you looked); /eye/ keeps the list | Dated |
| Eye Bot Health, 24h P&L by class, rule pills | R7; R9 Bots and History (P&L by class per world); Oculus R6 | Heartbeat health; per world |
| Eye footer "Auto-refresh every 10s" | R11 stamp | True words |
| PORTFOLIO strip, curve, donut, Top 5, open positions (RETRY) | R9 Performance (by world) and the platform book's box (curve, donut, max drawdown, Sharpe, Sortino); R3 (RETRY CLOSE) | Windows; database aggregates; the table moves to R3 |
| PORTFOLIO's "book" column (bot or portfolio) | R3: the mission on the row (`fixture live forex`, `Your ticket · signal #4113`) and its detail; own columns at ≥ 1,920 | The Horde's words |
| HISTORY (Top 5 rules included) | R9 History | Per world, per day points |
| BOTS strip and table, quick links | R7, R9 Bots (quick links kept) | World from the account, heartbeat health; P1 |

## Appendix B. New cells and their sources

| Cell | Reader (file:line) | Cost (cold) | Cache |
|---|---|---|---|
| Rows, lights, words, holder, mission, marks, P&L words, stragglers, unseated, alarms | `dashboard/horde.py:2167 board`, `:934 light`, `:881 holder`, `:1738 _stragglers`, `:1761 _unseated`, `:2089` the tab's `alarms`; OC2's additive `mark.age_s`, `mark.feed`, `money.pnl_at` | 47 | Block B 20 s |
| Worlds' P&L, R, risk at the stops | `dashboard/position_summary.py:282 open_by_world` over the rows; each seat's `risk.v` | 0 | — |
| eToro's cells (equity, available, P&L, used, outside, currency, ages) | `bot_program/etoro_used.py:322 account_used` | 3 | — |
| The program line, the pill's split | `core/context_processors.py:668 _bot_truth` (after OC0) | 18 | — |
| Realized 24 h by world | `AssetBotTrade` closed 24 h, split by `world_of` (`position_summary.py:253`) | 1 | — |
| Regime, trust, concern | `BrainReport` newest `error=""`; `brain/context.py` trust band | 1–2 | — |
| Next event, events ahead, touches | `bot_program/position_care.py:312 upcoming_events(horizon_minutes=1440)`, `:358 event_for(…, before_minutes=1440)` | 1 | per call |
| Starred prices, day change with its feed | `LiveQuote` for the instrument ids, `select_related`; `change_source` | 1 | — |
| News on held | `NewsArticle.ai_affected_instruments`, today, one aggregate | 1 | — |
| Signals | `dashboard/signal_rail.py:818 rail_snapshot` | 0 at GET, 36 in `act` (10 warm) | per request; rule facts 300 s |
| Exposure caps' refusals | `bot_program/orchestrator_models.py:13 OrchestratorEvent` rejects 24 h, grouped by reason prefix | 1 | — |
| Bot health | `bot_program/asset_engine/safety.py:203 heartbeat_age_seconds` | 0 (from `_bot_truth`) | — |
| Bot world | The account the config's symbols route to (`bot_program/engine/broker_router.py:243 client_for_symbol`; the eToro row's `demo` flag, `bot_program/models.py:360-375`) | 0 | — |
| Orcs | `bot_program/orcs/models.py:47 Orc` (alive, `latest_note_at`), `:233 OrcIntent` today by kind and mode; the note through the board's slot (`horde.py:485 _orc_plain`) | 2 | — |
| Since you last looked | `dashboard/activity_feed.py:640 activity_events(since, 200)`; the rail's cards after the stamp; `Orc.latest_note_at`; `TraderProfile.pages_seen["command_seen"]` (`portfolio/trader_profile.py:166`), read at GET and passed in the URL | 7 | — |
| Stage states and metrics, BEAT | `dashboard/views_day.py:349 day_live_payload`, server-rendered (the `cycle`, then `act` part) | 17 | — |
