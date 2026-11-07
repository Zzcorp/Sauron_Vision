# Sauron Vision — handoff for the next Claude session

Read this first, whichever Claude account runs the session. It holds the state of every open line of work, the operator's standing decisions, and the house rules. It is kept on branch `claude/handoff` (never merged), and is updated at each milestone. Last update: 2026-11-07 ~07:25 UTC, by the session working since 2026-10-31. A weekly usage limit stopped this session from 2026-11-02 05:39 to 2026-11-04 20:00 UTC; the unfinished work was saved on `claude/wip-*` branches (§3).

Nothing private lives here. The repository is PUBLIC: it was private only from 2026-11-05 to 2026-11-06, and everything pushed to any branch, this one included, is public. The operator's account figures, positions (which instruments he holds or traded, their sizes, prices and P&L), personal or family matters, and any partner or investor document never enter git: not in code, tests, commit messages, PR bodies or this file. Describe a case generically ("a live forex ticket", "one of his eToro rows"). Before opening a PR, scan the branch's commit messages and added lines for such data. Those live in the operator's own claude.ai documents and in files he keeps.

## 1. How to resume

1. **Clone `Zzcorp/Sauron_Vision`.** Then `git fetch origin` and read `git log --oneline -1 origin/main`. At this update, main is `ede54d0`: PRs #91 to #95, #89 and #90 are all merged (2026-11-06/07). The container restarted twice on 2026-11-06/07 (worktrees and the scratchpad survived; running workflows had to be resumed from their run ids).
2. **For each branch in §3, check out its worktree:** `git worktree add .claude/worktrees/<name> origin/claude/<name>`. Check where it stands against §3 with `git log --oneline origin/main..HEAD`.
3. **Set up the tests.**
   - Run `DB_ENGINE=sqlite python manage.py test <modules> --parallel 4`. The full suite takes 20 to 35 minutes on 4 cores.
   - tblib must be importable for parallel runs.
   - Run `python manage.py collectstatic --noinput` once per worktree.
   - `core/wall_facts.py` `TESTS_GREEN` must equal the test count discovered from a checkout of the index. Recount it when you commit; never edit it by hand.
4. **Talk to the operator in French.** He reads French and is not a developer. Platform text, code, comments and commit messages stay English.

## 2. Standing orders and house rules (non-private)

**The operator's standing orders**
- "Fusionne tout quand c'est vert": merge a PR once its CI is green and it is mergeable.
- Then send him a French command sheet: what changed, the money effects, the commands with their expected output, and what to watch. Verify every sheet against the code before sending. Three lenses have caught real errors every time: commands, truth, safety.
- "Fais les bons choix", "fais au mieux", "continue le travail": decide rather than ask, then say what you decided.
- Push every step. Every commit goes to its `claude/<branch>` the moment it exists.

**Money safety**
- Sauron trades ONE operator's REAL money at eToro. Shadow before power: a new power runs in shadow, graded against today, behind a switch that is OFF on arrival, and goes live only through a PIN-gated switch.
- Every commit message states its money direction plainly, including every case where something is sent or allowed sooner than before.
- Never weaken a test or drop an assertion. Write tests first, and make sure they fail before the change.
- Never call a broker or a model from a test; use fakes.
- No live model call without the operator's approval.

**Never**
- Never put a key, token or `.env` content in chat or in git.
- Never run `./deploy/ibkr-apply`.
- Never tick Demo on /brokers/.
- Never set a mode to paper to disarm (use `bot off`).
- Never add an eToro venue spelling without eToro's measured id.

**Public pages, alerts and commits**
- The Book and the Wall are public pages: no account figures, identifiers, hosts or commands.
- No money figures in alarm texts.
- Commit messages and PR bodies carry no model identifiers. Commits end with the two trailer lines (`Co-Authored-By:` and `Claude-Session:`) the session gives you.

**Limits**
- Keep workflows small: about ten agents at most.
- Write every intermediate spec into this branch as soon as it exists. A container reset and a weekly limit have each lost unpushed work before.

## 3. Open lines of work

| Branch | Base | Commits | State | Next |
|---|---|---|---|---|
| Unblock trading | — | — | Done on Sauron's side, 2026-11-05 | Switches ON; bots 1-5 and 14-30 ON (no MAX BOT LEVERAGE typed yet; their configs carry fixed 20x forex, 10x commodity, 5x stock, 2x crypto); manual lanes 7-10 back to the whole account (`shares rollback 165 155 154 153 --yes`); `share_allocator_auto_derisk` OFF; shock plan #174 left PROPOSED (do not apply). The last lock is eToro's free cash at 0: his own open positions (one opened from Sauron's ticket, one he opened himself in the eToro app, which Morgul reports as Drift; expected). |
| PR #86 | merged ccc824d | — | Sheet sent (verified) | MAX BOT LEVERAGE (x) on /setup/ Risk Limits, blank on arrival = no cap; caps only the bots (auto pick; a typed number above it goes at the cap or eToro's step under it); never the ticket. The sheet orders: deploy, MAX ACCOUNT PLEDGED still 100, type the number and Save Risk Limits, check `preflight_live | grep -i -E "enabled=|MAX BOT LEVERAGE|leverage_live is OFF"` and `morgul` (no [critical], no Brake:), the 4h prune, then `bot on 1 2 3 4 5 14 15 ... 30 --yes`; `bot brake <same ids>` to stop them without closing anything. Waiting on his number. |
| PR #87 | merged 7fb18c2 | — | Done | Built while the repository was private (2026-11-05 to 11-06), when Actions minutes counted against a monthly quota (a serial run took about 56 of its 60 minutes). It is public again since 2026-11-06: minutes are free, and the server's anonymous HTTPS fetch works again. Operator approved: tests in parallel (tblib in CI only), on pull requests only (+ workflow_dispatch), timeout 90, the time-sensitive tests made deterministic. |
| PR #85 | merged 47e70d0 | — | Sheet sent (verified) | A hand-taken SELL proposes the highest multiplier, like a BUY. The sheet also carries PR #84's prune rule 2 step (dry run, `--yes`, dry run again) before the bots are re-armed. Nits left for a follow-up: the ticket's short note says "Only 1x is measured" from an empty table while the FIRST SHORT box reads the demo proofs; "Pick a lower one" shows even after a lower pick; two docs still say a manual forex ticket goes at 1x. |
| `claude/usedfix` | ec54dd5 | U1 2032398, U2 4fd9fe8, U2b f985154 | U3 unfinished: `claude/wip-usedfix-u3` d0d600f holds the whole U3 diff and its tests; its commit message is ready | U3's full suite reached 8179 of 15006 tests with one failure, `tests.orcs.test_orc_notes...test_no_money_or_spend_key_at_any_depth`, which passes alone. Finish: full suite, commit U3, two reviews, rebase onto 9fda140, PR. U3 makes the gates value an eToro row at max(Sauron's figure, eToro's amount): tighter, so ship it after the unblock. Spec `plans/usedfix_spec.md`. |
| `claude/etbudget` | PR #95, top of the stack | 18 commits + text fix 9ac5350 + merges; head 36b45ff | CI, merge LAST (after #94) | The eToro request budget (one budget per key, six priorities, P0/P1 never held, a shared 429 pause), a batched rates read OFF until the measurement, pooled reads, eToro's own quotes for held instruments every 30 s, the eToro sync every 60 s (Yahoo forex stays 300 s), feed asks P-a and P-c. No migration. The sheet must give `python manage.py etoro_rates_shape` (measurement M1; read its `--help` on main for the exact flags) and state the request rates against eToro. |
| `claude/pnltruth` | PR #89, stacked on #90 | head 2789623 | CI, merge right after #90 | Open eToro rows print eToro's own P&L, else eToro's quote side, else a labelled estimate; display only. Tier 1 reads `/portfolio` `netProfit`, which eToro does not list for open positions: probably empty. The feed plan's F4 reads `/pnl` next. |
| po3 1h backfill | — | — | Owed to the operator | PR #84's guard is in. Still to give, verified: `backfill_bars --proving --intervals 1h --bars 9000 --dry-run`, then the real run (`--proving` takes its symbols from the 4h universe). Not urgent: the rule is at research. |
| Orcs O2 "shadow minds" | main | O2a: PR #88 merged (d81a035), sheet sent. O2b: PR #91 merged (acaabe3). The turn-on sheet `sheet_orcs_on` was sent; the operator turned Orc Minds ON on 2026-11-07 ("je viens d'activer les orcs minds"). Next O2c, then O2d | Operator 2026-11-05: "le dev des orcs full et conseil" = all four steps with the spec §4 defaults | Workflow orcs-o2a-build (plan into at most 6 commits, build each tests-first with the fake model and push, three review lenses, fix, full suite). Then O2b, O2c, O2d, one PR each: O2a wakes and the mind on r0 (Sonnet 5.5, low effort), O2b routing in shadow, O2c honor, temperaments, Captains, the Emperor and the drums, O2d ranks, the council of war, the post-mortem, `/orc N question`. Everything arrives OFF with the Orcs budget at 0; no live model call (the about-$1 smoke included) without his word. |

**Open PRs and branches at 07:25 UTC (2026-11-07)** — merge each when green ("Fusionne tout quand c'est vert"), then one verified French sheet per deploy (several PRs may share one sheet). No PR is open right now.

STACKING. Every branch touches `core/wall_facts.py` TESTS_GREEN, so merging one PR forces a recount and a new CI round on every other. When several PRs are green together, stack them in merge order (each branch has the previous one merged in, TESTS_GREEN recounted for the union: `scratchpad tools/merge_recount.sh <worktree> origin/<previous branch>`; a conflict outside wall_facts aborts and must be resolved by hand), push all, wait for one CI round, then merge them in order. This merged #90, #89, #94 and #95 in one round on 2026-11-07; #94's merge had one real conflict in `dashboard/views.py` `_parse_trade_body` (#93's shown_qty/shown_raised and #94's ticket_ref, both kept).
- `claude/oculus0` (O0 done: 3e312ef + review fixes 8e1b745, full suite OK; main merged in as b67199e, pushed; PR waits for #96): Oculus stage O0, display only. The REAL column stops counting eToro demo rows; every dash is named; windows, ages and constants are stated; "not due yet" is no longer amber; `oculus()` drops from 81 queries to 30 or fewer; the forge's file walk runs once per build. Spec in `handoff/plans/oculus/`.
- `claude/uis1a` (workflow ui-s1a-foundation resumed as run wf_e73d451d-01d; build done in 33b45e3 and 5a77278): UI stage S1a, the design tokens, Inter + JetBrains Mono, the component kit at /design/kit/, the calm background. The workflow merges origin/main into it, reviews by three lenses (money controls and hooks, regressions, merge integrity), fixes, runs the full suite; then PR. After it merges: O1 (the Oculus in the new kit), then S1b.
- PR #96 `claude/weekendtests` (1cc6476): tests only. tests.test_venue_pnl ThePositionPageNotesTests failed every weekend on main (the forex fixture's market is shut on Saturdays, so the page rightly prints the shut-market note); the market is now pinned open there. assertNoFigure cuts ISO times before scanning (microseconds could spell "3456"). Merge it first: every PR's CI is red on weekends without it.
- `claude/opscenter0` (workflow opscenter-oc0-build, run wf_bc20a923-626): Operations Center stage OC0, truth and cost in today's look (a DEMO row no longer reads REAL MONEY; worlds never summed; the armed pill counts REAL-account bots only; PORTFOLIO VALUE renamed PLATFORM BOOK with honest words; profit factor = gross wins / gross losses; CLOSE sticky; bot buttons hidden from users the endpoint refuses; the page's poll stops stamping the session and stops when hidden or locked; tabs 60-90 % lighter). Spec and French plan in `handoff/plans/opscenter/` (the six OKs asked; P1-P5 proposals; §9 lists corrections for the Oculus O2a spec and mock).
- The combined deploy sheet for #89-#95 was SENT on 2026-11-07 (verified by three lenses, then re-checked after he turned Orc Minds on). Waiting for his outputs: the M1 measurement (point 3) and the five `orcs status` lines (point 6).
- UI plan (`handoff/plans/ui/`): Bloomberg × TradingView in Sauron's identity, dark, desktop first, drawings last; stages S0-S5. The operator approved the preview canvas ("Magnifique attaque").
- Oculus plan (`handoff/plans/oculus/`): O0 now, O1 after S1a, then O2a (status line, needs-you list, cycle map, money safety, last hour), O2b (what acts, AI spend, prices and the eToro budget; after #95 and #90), O3 with the feed's F6/F7. The French note asks him two OKs: the order of the blocks, and the slow cycles below the "now" blocks.
- Feed plan (`handoff/plans/feed/`): F1 (truth core, one venue-source rule, pins, harm counters, replay harness) is building on `claude/feedf1` (workflow feed-f1-truth-core, run wf_99a1fdf2-338). After F1: F2a, F2b, F3 and F5 in parallel, one PR each; F4 after his measurement M3a (which needs F3's probes).
- The combined French deploy sheet for d81a035..ede54d0 (#91-#95, #89, #90) is being written and verified (workflow sheet-stack-deploy, run wf_a1e481fd-524; final at scratchpad sheet_stack_fr.md): migrations bot_program 0050, dashboard 0003, portfolio 0019; every new switch OFF; LANE KNOBS advice; the eToro P&L tiers; `etoro_rates_shape` (M1); whether the unrun Orcs turn-on sheet is still exact after O2b.

**Designed, not started**
- Orders at a price, P1 to P5 (`plans/orders_spec.md`). The operator said yes to all. P1 is cancelling a pending close; P1b needs demo measurements M7 and M8 of eToro's close-order read and DELETE.
- Live and paper apart, worlds C1 to C3. The operator said yes to real-only limits, and to eToro REAL and DEMO side by side on the ticket with a second PIN confirmation. The spec was lost and must be redone.
- The Bettor and the Horde reinforcements (`plans/bettor_spec.md`, `plans/bettor_operator_choices.md`).
- TPO and volume profile. Lost, to be redone.
- The Saxo hold for closes in doubt (`plans/saxo_hold.md`). No Saxo row is live.

## 4. The operator's decisions (log)

**2026-10-31**
- Shorts fully possible.
- At a 100% account pledge ceiling, eToro's free cash decides alone.
- The used capital is just shown ("juste montrer"): outside money is never added to the gates.
- More chart timeframes.
- A brain that bets intelligently instead of fixed caps, with only survival rails (the Bettor).
- A second position on one asset as a Horde action.

**2026-11-01**
- Models moved to the 5.5 generation (PR #79).
- Bearish rules born at research (PR #80).
- The decisions taken for him on the used capital: a stood-down lane still closes its real rows; Sauron never adopts a position tied to its own in-doubt order; the gates value an eToro row at max(Sauron's figure, eToro's amount). The reason for the last one: eToro blocks more than notional over leverage on two USD-based exotic pairs at the same leverage.
- He will cancel at eToro a close that eToro queued at the weekend shut, so the row stays CLOSE_PENDING and blocked: the drain sends nothing. Two follow-ups: the demo short-proof runner must not wait on such a row (U2b), and a lookup failure must not spend that row's attempts (U2).
- He may run the work on two or three Claude subscriptions: this file is what lets any of them resume. Keep it current before each limit.

**2026-11-06**
- A live ticket of his showed 'Network error' while the order went through at eToro; he says it is settled. Owed: the ticket must say the order may have gone when the connection drops after the PIN.
- The P&L gap between Sauron and eToro on his eToro rows is a "vrai problème": show eToro's own result (`claude/pnltruth`).
- "Augmenter to the maximum le taux de refresh des valeurs et de eToro surtout": public forex quotes every minute, eToro's own prices for held instruments about every 30 s, the eToro account read every minute, inside the request budget (`claude/etbudget`).
- Then: "Toute les 5min c'est beaucoup beaucoup beaucoup beaucoup trop long pour du trading. I want sauron to be alike etoro on Price data flow and feed you understand? Same grade" — eToro's own bid/ask on screen about as fast as eToro's app, P&L like eToro's to the cent, the account read far more often. And: "le jonglage entre les sources des prix soit parfaite et non pénalisante ou possiblement blessante même" — source switching harmless by construction (one authoritative source per instrument, flagged fallbacks used for no money decision, no false jump, alarm, stop, exit, entry or P&L swing on any transition, protective actions never blocked). Workflow etoro-grade-feed-design is writing the spec (to be copied to `handoff/plans/feed/`). The etbudget interim cadences stay as a first step and a fallback.
- "Lancer les étapes de lancement d'orcs svp": he approves the Orcs minds turn-on and its AI cost (claude_smoke about $1; the Orcs line $6 a day; the total raised by $9). The verified turn-on sheet is being prepared (`sheet_orcs_on`, steps 0-5).
- The signal rail shows only the five newest active signals (core/context_processors.py panel_recent_signals and panel_top_signals), so a burst hides signals he could act on. He wants no hidden cap, a real lifecycle (a signal leaves when past, invalidated, no longer supported, or its rule not effective and profitable) and filters and display choices in the headband for the signals and the watchlist (by asset class and more). Display only: the engine and the take-trade path must see exactly what they saw (`claude/railfilters`).
- The PR88 sheet went out verified (2026-11-06): the fetch check runs alone with `GIT_TERMINAL_PROMPT=0`, because the private repo could make his server's HTTPS fetch ask for a password; he must never type or send one. The repo went public again the same day, so the fetch should pass; keep `GIT_TERMINAL_PROMPT=0` in fetch and pull lines anyway. For the later Orcs turn-on sheet: the six RUNBOOK steps assume the `orcs` journals switch and the platform master are ON; if `orcs status` first line reads `The orcs switch is OFF.`, a seventh step is needed.

- His UI plan, points 1-5 (`plans/charts_signals_plan.md`): a more high-end, elegant design, "un smart melange de bloomberg et trading view sous sauron"; signal popups placed better, opened and scrolled on click, not hover; full responsive; rectangles, lines and their styles "comme trading view in sauron style", LAST; dark, desktop first.
- "Sized to zero ... débride la machine quand il s'agit du manuel": the manual ticket opens at the smallest size the venue takes, within the 7% hard cap, its risk said before the PIN (PR #93). The next gate on a small pool is the lane's notional cap and MAX SINGLE POSITION (20% by default): /admin-dashboard/ LANE KNOBS.
- "Améliorer oculus système aussi svp" and "Magnifique attaque" (the approval of the preview and the go-ahead to build).
- "Je n'ai pas activé les orcs encore": the Orcs turn-on sheet stands; he will run it.

**2026-11-07**
- "Do the same for the opération center please": the Operations Center (/command/, his home) gets the Oculus treatment: map, screenshots, design as his trading desk in the new style (boundary: machine health stays in the Oculus), French proposal and mock, stages OC0 (truth and cost, today's look, no approval needed) to OC3 (live with F4/F7). Workflow opscenter-improve-design (run wf_ce86da72-281), outputs in scratchpad `opscenter/`, to be copied to `handoff/plans/opscenter/`.
- "Je voudrai aussi que l'on creer une page qui s'affiche apres que l'utilisateur se connecte ... seulement l'oeil au centre et des particules ou des elements animes qui soient les elements de chaque page ainsi que leur interconnection entre eux marquee ... avec en graphique sur chaque cote et en chiffre les elements detailles et donnant vue aux perfs du portfolio": a post-login page after the kept /intro/ animation (LOGIN_REDIRECT_URL stays "intro"): the Eye at the centre, the platform's pages as animated linked elements (the real data flows, labelled; particles on real events only, never a number or a fake label), the portfolio's performance per world on the left and the activity on the right. Workflow eye-hall-design (run wf_1cc2c37a-b26), outputs in scratchpad `eyehall/` (spec, French note, animated mock, video, the board `Eye.dc.html` for the preview canvas). Build E1 after S1a.
- Correction minutes later: "Garder l'animation action actuelle de chargement svp cependant": today's /intro/ loading animation is KEPT exactly (look, timing, skip, once per browser session); the new Eye page comes right AFTER it (the intro's handoff target changes from /command/ to the new page; a second login in the same session lands on it too). The design workflow was restarted with this correction.
- "Mais garder la thematique initiale pour le design et theme please ... we still feel the magic or something alike, the prestige too": the new look keeps Sauron's initial theme. Discipline for DATA (numbers crisp, no glow behind a number, ≥11 px, ≥4.5:1, no fake data); MAGIC in the FRAME (the Eye alive, the display face for titles, the neon green as light on live and active elements, calm embers behind opaque cards with no fake labels, prestige details, motion on real events), with an Ambiance preference he controls. Workflow sauron-magic-layer (run wf_c9eb943d-faa) writes the addendum, a canvas board and the S1a change list. HOLD the S1a PR until that magic commit is on `claude/uis1a`; the Oculus O1, the Operations Center and the Eye page follow the same layer.
- "Revolut pour 10-15 k€ ?": answered (no for that size; better routes in France; never take investors' money as trading capital without an AMF authorisation); a verified French note is being researched (workflow funding-revolut-question, run wf_d2b59c88-a96).
- "Je viens d'activer les orcs minds" (about 09:05 UTC): Orc Minds is ON at his site, on the code he runs (PR #88 O2a, or later if he pulled). Asked him for the step-5 status lines of `sheet_orcs_on` to confirm the budget lines (Orcs $6, total $24) and the model calls. The combined deploy sheet's Orcs section must now say: the minds stay ON through the deploy (a deploy changes no switch); O2b's three new switches (orcs_router, orcs_probes, orcs_frontier) arrive OFF and stay OFF; check with the six-line `component list --category system` grep and the five-line `orcs status` grep after the deploy.
- "6 okay" (about 10:25 UTC), answering the six OKs of `plans/opscenter/plan_fr.md`: read as ALL SIX approved (told him so; he may correct): (1) the block order; (2) eToro's own figures first and larger, PORTFOLIO VALUE (the platform book) moved down to Review in its own box; (3) the loop, THE BEAT and the 24 h strip folded at the bottom; (4) one page instead of four tabs (old ?tab= links keep working); (5) P2, the "since you last looked" stamp (TraderProfile.pages_seen["command_seen"], moved after 5 s on screen or "mark as read"); (6) P1, the bots' Toggle and "▶ Tick" leave the home (they stay on the bots page and in Admin HQ). P1 ships as an extra commit on the OC0 PR; (1)-(4) in OC1 after S1a; (5) in OC2.
- "ok continue, envoie la fiche dès qu'elle est prête": send the combined deploy sheet as soon as it is verified.
- "ok pour l'ordre des blocs de l'Oculus": the Oculus block order of `plans/oculus/plan_fr.md` is approved (status line, needs you, the cycle, money safety, prices and requests, what acts, AI, the last hour, then the slow cycles below, then the forge and the not-measured list). Decided for him under "fais au mieux": the slow cycles' explanations sit one click away, as proposed; he may ask for them always open. O1 follows S1a; O2a follows O1; O2b follows O2a.

**2026-11-05**
- "Le dev des orcs full et conseil": build O2a to O2d, the council of war included, with the spec's §4 defaults (my recommendations in the French plan).
- He opened a position himself in the eToro app; Sauron does not manage it (Morgul's Drift on it is expected).

**2026-11-04**
- He closed a forex position himself in the eToro app.
- "Restaurer achat et vente manuel en leverage max": a hand-taken SELL proposes the highest leverage by default, like a BUY.
- "Fix it all, fast": every bot back on, and every block that wrongly stops him trading or acting on signals fixed.

## 5. Merged today

| PR | Merge | What |
|---|---|---|
| #79 | 645a135 | models |
| #80 | 62a2a18 | bearish |
| #81 | 9d74a19 | chart feeds, eToro pace and re-reads, eToro's own used figure |
| #82 | 49b6b57 | shorts everywhere, demo short proofs (`short_proofs_demo` arrives ON, demo only), no eToro request follows a redirect |
| #83 | ec54dd5 | at a 100% pledge ceiling eToro's free cash decides alone; chart candles of 10m, 30m, 2h and 1w |
| #84 | 9fda140 (2026-11-02) | the backfill keeps out of a venue's bars; the 4h clean-up clears two old grids side by side (its step is in the #85 sheet) |
| #85 | 47e70d0 (2026-11-05) | a hand-taken SELL proposes the highest multiplier, like a BUY |
| #86 | ccc824d (2026-11-05) | MAX BOT LEVERAGE on /setup/, bots only; the merge commit states the full money direction |
| #87 | 7fb18c2 (2026-11-05) | tests in parallel, on pull requests only |
| #88 | d81a035 (2026-11-06) | Orcs O2a: wakes, and a model reads an Orc's dossier in shadow; everything OFF, the Orcs budget at 0, a new `worker-orc` service, migration bot_program 0049 |
| #91 | acaabe3 (2026-11-06) | Orcs O2b: routing in shadow; switches orcs_router, orcs_probes, orcs_frontier, all OFF behind the PIN; migration bot_program 0050 |
| #92 | 38ed1ab (2026-11-06) | UI S0: six display defects; the rail no longer covers /positions/, CLOSE stays in view |
| #93 | 7026ef7 (2026-11-06) | a manual ticket sized to zero opens at the smallest size the venue takes, under the 7% cap; the send holds to the size shown |
| #90 | 795a40b (2026-11-07) | the signal rail lists every actionable signal, with a lifecycle, filters and click popups; migrations dashboard 0003, portfolio 0019 |
| #89 | 8be4725 (2026-11-07) | open eToro rows print eToro's own P&L, else eToro's quote side, else a labelled estimate; display only |
| #94 | e5ef5c8 (2026-11-07) | the ticket says an order may have gone when its answer is lost, and looks it up (read-only endpoint) |
| #95 | ede54d0 (2026-11-07) | the eToro request budget, cheaper reads, eToro's own quotes every 30 s, the eToro sync every 60 s; no migration |

The sheets for #81, #82 and #83 were sent. Small follow-ups from the #83 sheet review: the alarm group's G6-at-100% line should say it stops nothing; the ticket says 'never read' / 'not stored' when the last read carried no available cash; the chart's remembered frame is one click behind (pre-existing).
