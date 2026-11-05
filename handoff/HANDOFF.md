# Sauron Vision — handoff for the next Claude session

Read this first, whichever Claude account runs the session. It holds the state of every open line of work, the operator's standing decisions, and the house rules. It is kept on branch `claude/handoff` (never merged), and is updated at each milestone. Last update: 2026-11-05 ~06:45 UTC, by the session working since 2026-10-31. A weekly usage limit stopped this session from 2026-11-02 05:39 to 2026-11-04 20:00 UTC; the unfinished work was saved on `claude/wip-*` branches (§3).

Nothing private lives here. The repository is public. The operator's account figures, positions, personal or family matters, and any partner or investor document never enter git. Those live in the operator's own claude.ai documents and in files he keeps.

## 1. How to resume

1. **Clone `Zzcorp/Sauron_Vision`.** Then `git fetch origin` and read `git log --oneline -1 origin/main`. At this update, main is `47e70d0`: PR #85 is merged.
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
| **Unblock trading (first)** | — | — | In progress with the operator | Found 2026-11-05: every platform switch was already ON; his manual lanes 7-10 (forex, commodity, crypto, stock; live) are ON; config 12 belongs to another, paper user. Bots 1-5 and 14-30 (live) were stopped by Morgul's margin brake on 2026-11-01 19:15 UTC, before PR #83; bot 6 has been off since before 2026-10-07. "Sized to zero" on his ticket: the live manual lanes' pools are tiny (tens of USD) and the default risk per ticket is 0.25% of the pool; he was told LANE KNOBS risk per ticket = 7 (PIN) and sent a read-only diagnostic (switches, equity, cash, withdrawal hold, lanes' follow/share/knobs, bots' leverage). Next: fix the pools' size from that output; re-arm the bots only after MAX BOT LEVERAGE is set (with etoro_leverage_live ON an 'auto' bot goes up to 30x on forex). |
| `claude/botlev` | 47e70d0 (main) | building | Workflow running | MAX BOT LEVERAGE (x) on the /setup/ Risk Limits: a nullable limits-book field, blank on arrival (nothing changes), capping only the bots (the auto pick, and a typed number clamps to the cap), never the TAKE TRADE ticket. Fixes the stale /ops/ text of etoro_leverage_live. Then PR, merge, sheet: set the number, then `bot on 1 2 3 4 5 14 ... 30 --yes`. |
| PR #85 | merged 47e70d0 | — | Sheet sent (verified) | A hand-taken SELL proposes the highest multiplier, like a BUY. The sheet also carries PR #84's prune rule 2 step (dry run, `--yes`, dry run again) before the bots are re-armed. Nits left for a follow-up: the ticket's short note says "Only 1x is measured" from an empty table while the FIRST SHORT box reads the demo proofs; "Pick a lower one" shows even after a lower pick; two docs still say a manual forex ticket goes at 1x. |
| `claude/usedfix` | ec54dd5 | U1 2032398, U2 4fd9fe8, U2b f985154 | U3 unfinished: `claude/wip-usedfix-u3` d0d600f holds the whole U3 diff and its tests; its commit message is ready | U3's full suite reached 8179 of 15006 tests with one failure, `tests.orcs.test_orc_notes...test_no_money_or_spend_key_at_any_depth`, which passes alone. Finish: full suite, commit U3, two reviews, rebase onto 9fda140, PR. U3 makes the gates value an eToro row at max(Sauron's figure, eToro's amount): tighter, so ship it after the unblock. Spec `plans/usedfix_spec.md`. |
| `claude/etbudget` | ec54dd5 (rebased, unreviewed) | 14 commits, tip c640e51 on `claude/wip-etbudget-rebased`; `claude/etbudget` still holds the old 3397593 on ba71a9f | Review the rebase, then rebase onto 9fda140, suite, force-push `claude/etbudget`, PR | The eToro request budget: one budget per key with priorities, a shared 429 pause, a batched rates read, pooled connections. The sheet must give `python manage.py etoro_rates_shape --user <operator>` after the deploy: the batched rates wait for that demo measurement. |
| po3 1h backfill | — | — | Owed to the operator | PR #84's guard is in. Still to give, verified: `backfill_bars --proving --intervals 1h --bars 9000 --dry-run`, then the real run (`--proving` takes its symbols from the 4h universe). Not urgent: the rule is at research. |
| Orcs O2 "shadow minds" | — | — | Spec done (`plans/orcs2/o2_spec.md`); French plan sent 2026-11-02 (`plans/orcs2/plan_fr.md`) | Waiting on the operator's answers to the plan's 10 questions (the defaults are in the spec's last section). Then build O2a to O2d, one PR each: O2a wakes and the mind on r0 (Sonnet 5.5, low effort), O2b routing in shadow, O2c honor, temperaments, Captains, the Emperor and the drums, O2d ranks, the council of war, the post-mortem, `/orc N question`. Everything arrives OFF with the Orcs budget at 0; no live model call (the about-$1 smoke included) without his word. |

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

The sheets for #81, #82 and #83 were sent. Small follow-ups from the #83 sheet review: the alarm group's G6-at-100% line should say it stops nothing; the ticket says 'never read' / 'not stored' when the last read carried no available cash; the chart's remembered frame is one click behind (pre-existing).
