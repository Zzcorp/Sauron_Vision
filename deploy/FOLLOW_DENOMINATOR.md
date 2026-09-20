# THE FOLLOW DENOMINATOR — WHY IT IS NOT BEING CORRECTED

Written 2026-09-20, after three independent designs were scored by nine
judges (three lenses each). Committed rather than left in a scratchpad
because the next person to see this arithmetic — including a later me — will
be tempted by the same shortcut, and the reason not to take it is not
obvious from the code.

## THE ARITHMETIC IS WRONG, AND THE WAY IT IS WRONG IS SAFE

`bot_program/tasks.py:507` `_follow_the_account` computes the share plan over
**every** follower (`capital_truth.followers_of`, venue-blind) and then, in
the loop that applies it, refuses the followers that trade at a venue other
than the book (`tasks.py:559`). So the denominator counts pools the next
lines will skip.

With Saxo the book, one Saxo pool and one eToro pool both automatic, each is
planned at 50%: the Saxo pool is written to **half** the Saxo account when it
is the only pool that account can size, and the eToro pool is never retuned
at all. `/shares/`, `follow --list`, `shares --list`, the preflight and
`evidence` all print "auto 50%", so the number looks deliberate.

The error is always in the direction of **too small**. No pool is ever sized
against money another pool already claims; that is what `allocate_shares`
exists to prevent and it still does.

## WHY CORRECTING IT IS WORSE THAN LIVING WITH IT

Three shapes were designed and each judged from three lenses. None scored
above 6/10 and every one of them breaks something the platform guarantees:

**Scope the denominator** (scored 3, 3, 4). Descoping only ever SHRINKS the
denominator, so every surviving automatic share RISES. Measured: a Saxo pool
beside an eToro pool goes from 50,000 to 100,000 on a 100,000 account — a
live pool's capital **doubles** on the next 15-minute beat. With an explicit
60% beside it, 40,000 to 100,000. And a fleet that is over-allocated today
(deliberately frozen, nothing retuned, `_alert_over_allocation` firing) would
suddenly fit and start writing. House rule 3 forbids all of it. Guarding
against the rise instead — retune nothing while a refused follower exists —
turns `tests/test_monday_evening.py:568` red, and that assertion
(`"the book's own follower is retuned"`) is a written contract, not an
accident.

**Each venue retunes its own followers** (scored 4). Requires making the
FOLLOW multi-account while `broker_backed` stays single, which splits the one
number the operator reads: `/treasury/`, `tracking_freeze_reason`, the
preflight comparisons at `preflight_live.py:644` and `:697`, and the gate
denominators would each answer from a different account.

**Refuse and say so** (scored 5, 6, 6 — the best). It provably moves no
pool's capital by one cent. But it **disarms the automatic drawdown de-risk**
for exactly the fleet it fires on: `share_allocator` can no longer lower a
live pool, so a shock at the book leaves the fleet at full share until a
human acts. Turning off a live-money safety organ to correct a sizing
fraction is not an improvement, and the fraction errs small already.

## THE STATE IS ALSO HARD TO REACH — FROM ONE DIRECTION

`bot_program/manual_trade.py:2051` already refuses to arm an off-book
follower, and says why: *"the pool would be sized from one account and traded
on another"*. So a cross-venue following fleet is not a state the manual
arming path will create. It arises from a book FLIP after arming — or from a
path that does not check.

## WHAT IS BEING FIXED INSTEAD, AND IT IS THE LEAK NOT THE ARITHMETIC

**Four writers, not one.** The scouting for this work, and the first design
built on it, both said `_follow_the_account` was the only writer of a
following pool's capital. A money judge disproved it:

- `dashboard/views_admin_hq.py:946` — the `/asset-bots/` **Follow button**
  calls `allocate_shares(followers_of(request.user, include=cfg))` and writes
  `cfg.capital` at `:959` with **no venue test anywhere in the handler**. It
  is the one easy way to create the state `manual_trade.py:2051` refuses, and
  it is the page both existing alerts send the operator to.
- `bot_program/manual_trade.py:2069` — writes capital from the same plan, but
  behind the `:2051` refusal.
- `bot_program/share_allocator.py:1364` — writes `account_share_pct`, the
  share the sync multiplies, over the same blind denominator.
- `bot_program/tasks.py:572` — the sync.

**Order-dependence.** `tasks.py:551` asks `broker_name_for_symbol(user,
symbols[0], cfg)`. Routing is per SYMBOL — `runner.py:127` calls
`client_for_symbol` inside `for symbol in cfg.symbols` — so a pool holding
one Saxo symbol and one eToro symbol is refused or retuned according to
**which one the operator typed first**, and `cfg.symbols` is a JSONField list
in typing order.

Both of those are one-directional: they make the platform refuse more, never
resize more, and neither can raise a pool's capital. They are in the same
commit as this document.

## WHAT WOULD MAKE THE ARITHMETIC CORRECTABLE

Not a cleverer denominator. Either:

1. `broker_backed` becomes plural — the book is a set of accounts, and
   `/treasury/`, the preflight, `tracking_freeze_reason` and the gate
   denominators are all taught to read the account that carries the pool
   asking. That is a large, deliberate change with its own refutation round,
   and it is the honest version of "each venue retunes its own followers".
2. Or following is restricted, by rule, to pools whose whole symbol list
   reaches the book — enforced at all four writers. Then the denominator is
   correct by construction and nothing needs scoping. Cheaper, and it takes
   something away from the operator, which is their call and not mine.

Until one of those is chosen, the fraction stays small and honest, and the
leak is shut.
