# Sauron Vision — handoff for the next Claude session

Read this first, whichever Claude account runs the session. It holds the state of every open line of work, the operator's standing decisions, and the house rules. It is kept on branch `claude/handoff` (never merged), and is updated at each milestone. Last update: 2026-11-06 ~08:50 UTC, by the session working since 2026-10-31. A weekly usage limit stopped this session from 2026-11-02 05:39 to 2026-11-04 20:00 UTC; the unfinished work was saved on `claude/wip-*` branches (§3).

Nothing private lives here. The repository is PUBLIC: it was private only from 2026-11-05 to 2026-11-06, and everything pushed to any branch, this one included, is public. The operator's account figures, positions (which instruments he holds or traded, their sizes, prices and P&L), personal or family matters, and any partner or investor document never enter git: not in code, tests, commit messages, PR bodies or this file. Describe a case generically ("a live forex ticket", "one of his eToro rows"). Before opening a PR, scan the branch's commit messages and added lines for such data. Those live in the operator's own claude.ai documents and in files he keeps.

## 1. How to resume

1. **Clone `Zzcorp/Sauron_Vision`.** Then `git fetch origin` and read `git log --oneline -1 origin/main`. At this update, main is `d81a035`: PR #88 (Orcs O2a) is merged.
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
| `claude/etbudget` | being rebased onto d81a035 | 14 commits, tip c640e51 on `claude/wip-etbudget-rebased` (backup); `claude/etbudget` is force-pushed by workflow etbudget-finish-faster | Workflow: rebase onto main, review, then the faster refresh the operator asked on 2026-11-06 (public forex quotes 600 s → 60 s; eToro's own bid/ask for held instruments about every 30 s; the eToro account sync 300 s → 60 s), full suite, PR | The eToro request budget: one budget per key with priorities, a shared 429 pause, a batched rates read, pooled connections. The sheet must give `python manage.py etoro_rates_shape --user <operator>` after the deploy: the batched rates wait for that demo measurement. The sheet must also state the new request rates against eToro. |
| `claude/pnltruth` | d81a035 (main) | building | Workflow etoro-pnl-truth (map, build, review, fix), then PR | The operator saw one of his eToro forex rows with a P&L several dollars away from eToro's, of the opposite sign ("Vrai problème"). Entries match eToro exactly; the gap is the mark: Sauron marks eToro rows at the public last price (refreshed every 10 min, no bid/ask), eToro at its own closing side. Fix: an eToro row shows eToro's own `netProfit` from the last account read first, Sauron's mark only as the fallback, and says which one it shows. |
| po3 1h backfill | — | — | Owed to the operator | PR #84's guard is in. Still to give, verified: `backfill_bars --proving --intervals 1h --bars 9000 --dry-run`, then the real run (`--proving` takes its symbols from the 4h universe). Not urgent: the rule is at research. |
| Orcs O2 "shadow minds" | d81a035 (main) | O2a: PR #88 merged as d81a035 (13 commits); its sheet `sheet_pr88.md` is in three-lens verification. O2b building on `claude/orcs2b`: commit 1 363d06c (wakes record the rung a pure router would choose; r0 still answers every one) pushed, commit 2 (routed rung) building; its suite rebases onto main | Operator 2026-11-05: "le dev des orcs full et conseil" = all four steps with the spec §4 defaults | Workflow orcs-o2a-build (plan into at most 6 commits, build each tests-first with the fake model and push, three review lenses, fix, full suite). Then O2b, O2c, O2d, one PR each: O2a wakes and the mind on r0 (Sonnet 5.5, low effort), O2b routing in shadow, O2c honor, temperaments, Captains, the Emperor and the drums, O2d ranks, the council of war, the post-mortem, `/orc N question`. Everything arrives OFF with the Orcs budget at 0; no live model call (the about-$1 smoke included) without his word. |

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
- The PR88 sheet went out verified (2026-11-06): the fetch check runs alone with `GIT_TERMINAL_PROMPT=0`, because the private repo could make his server's HTTPS fetch ask for a password; he must never type or send one. The repo went public again the same day, so the fetch should pass; keep `GIT_TERMINAL_PROMPT=0` in fetch and pull lines anyway. For the later Orcs turn-on sheet: the six RUNBOOK steps assume the `orcs` journals switch and the platform master are ON; if `orcs status` first line reads `The orcs switch is OFF.`, a seventh step is needed.

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

The sheets for #81, #82 and #83 were sent. Small follow-ups from the #83 sheet review: the alarm group's G6-at-100% line should say it stops nothing; the ticket says 'never read' / 'not stored' when the last read carried no available cash; the chart's remembered frame is one click behind (pre-existing).
