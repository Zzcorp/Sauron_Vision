# Sauron Vision — handoff for the next Claude session

Read this first, whichever Claude account runs the session. It holds the state of every open line of work, the operator's standing decisions, and the house rules. It is kept on branch `claude/handoff` (never merged), and is updated at each milestone. Last update: 2026-11-04 ~22:45 UTC, by the session working since 2026-10-31. A weekly usage limit stopped this session from 2026-11-02 05:39 to 2026-11-04 20:00 UTC; the unfinished work was saved on `claude/wip-*` branches (§3).

Nothing private lives here. The repository is public. The operator's account figures, positions, personal or family matters, and any partner or investor document never enter git. Those live in the operator's own claude.ai documents and in files he keeps.

## 1. How to resume

1. **Clone `Zzcorp/Sauron_Vision`.** Then `git fetch origin` and read `git log --oneline -1 origin/main`. At this update, main is `9fda140`: PR #84 is merged.
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
| **Unblock trading (first)** | — | — | Waiting on the operator's diagnostic output | 2026-11-04: he closed a forex position in the eToro app, and reports every bot OFF and manual tickets and signals blocked. He was asked for `bot list`, `why_no_trade --symbols 1`, `preflight_live`, `morgul` (read-only) and the OFF rows of `component list`, plus screenshots of the ticket's refusal and leverage menu. Then: exact commands to turn everything back on (`bot on <ids> --yes`; PIN switches on /ops/), and code fixes for any block that is wrong. |
| `claude/manualmax` | 9fda140 (main) | building | Workflow running | His order: manual BUY and SELL at the highest leverage by default. A SELL with no pick proposes the highest choice, like a BUY; the choices and the bots are unchanged. PR, merge, sheet. Open question to him: "plus mesurer pour les bots" = A (bots keep their measured, capped leverage, as today) or B (no more demo proofs before a bot shorts). |
| `claude/usedfix` | ec54dd5 | U1 2032398, U2 4fd9fe8, U2b f985154 | U3 unfinished: `claude/wip-usedfix-u3` d0d600f holds the whole U3 diff and its tests; its commit message is ready | U3's full suite reached 8179 of 15006 tests with one failure, `tests.orcs.test_orc_notes...test_no_money_or_spend_key_at_any_depth`, which passes alone. Finish: full suite, commit U3, two reviews, rebase onto 9fda140, PR. U3 makes the gates value an eToro row at max(Sauron's figure, eToro's amount): tighter, so ship it after the unblock. Spec `plans/usedfix_spec.md`. |
| `claude/etbudget` | ec54dd5 (rebased, unreviewed) | 14 commits, tip c640e51 on `claude/wip-etbudget-rebased`; `claude/etbudget` still holds the old 3397593 on ba71a9f | Review the rebase, then rebase onto 9fda140, suite, force-push `claude/etbudget`, PR | The eToro request budget: one budget per key with priorities, a shared 429 pause, a batched rates read, pooled connections. The sheet must give `python manage.py etoro_rates_shape --user <operator>` after the deploy: the batched rates wait for that demo measurement. |
| PR #84 sheet | — | — | To write and verify | The barsguard PR is merged (9fda140). The sheet: rebuild; `prune_offgrid_4h` dry run, then `--yes`; then the po3 1h backfill (`backfill_bars --proving --intervals 1h --bars 9000 --dry-run`, then the real run; `--proving` takes its symbols from the 4h universe). |
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
| #84 | 9fda140 (2026-11-02) | the backfill keeps out of a venue's bars; the 4h clean-up clears two old grids side by side (sheet not sent yet) |

The sheets for #81, #82 and #83 were sent. Small follow-ups from the #83 sheet review: the alarm group's G6-at-100% line should say it stops nothing; the ticket says 'never read' / 'not stored' when the last read carried no available cash; the chart's remembered frame is one click behind (pre-existing).
