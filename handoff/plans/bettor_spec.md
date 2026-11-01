# The Bettor and the Horde's reinforcements: design spec (v2, after the review)

Repository: `/home/user/Sauron_Vision/.claude/worktrees/invest`, main at `dbfe0a9` (2026-10-31), read only. Nothing is built. Every file:line below is at that commit. The two maps this spec builds on are `scratchpad/bettor/map_sizing.md` (what sets a size today) and `scratchpad/bettor/map_horde.md` (the Horde, the Orcs and one position per asset). The worked examples are computed by `scratchpad/bettor/tools/example_v2.py`; the readiness power figures by `scratchpad/bettor/tools/power.py`.

**The operator's decisions (2026-10-31).**
- Second position on a held asset: "oui et non, faites le intelligent et smart, une organisation ou action de la horde par exemple". In English: yes and no; make it intelligent, for example an organisation or an action of the Horde.
- Per-trade limits: "pas de limites reellement non, juste un cerveau qui parie de maniere intelligente". In English: no real limits, just a brain that bets intelligently.
- Also on 2026-10-31: at 100% pledged, eToro's free cash decides alone (yes); positions opened in the eToro app outside the platform are shown, never adopted (shown only).

**Our position, kept throughout.**
- The brain decides the size, and the fixed per-trade caps give way to it.
- A few survival rails stay, because bad data happens. The operator has just seen price spikes on the charts, and a bad tick must never become a huge bet. The rails are:
  1. eToro's own free cash;
  2. the daily loss stop;
  3. a maximum drawdown circuit;
  4. the venue minimum;
  5. one sanity ceiling per bet, set by the operator and wide by default;
  6. **the book ceiling** (added by the review): the same sanity ceiling for the whole book. One bet's ceiling cannot stop twenty bets that each pass it, so the book carries one too: open risk at the stops (the operator's own 15%) and the loss on a tail move (50% by default). It is not a per-trade limit.
- Everything else is the brain's judgment.

**The platform's principle, kept throughout: shadow before power.** Every new power works like this:
- It arrives behind a switch that is OFF.
- It first runs in shadow, graded against what the platform does today.
- It goes live only through a switch that takes the trading PIN, one world at a time: paper, then demo, then real money.

**What the review changed** (section R lists every finding and what became of it):
- The estimator keeps every loss (capped at −20R) and drops only wins past +20R, like the proving judge. It reads R net of eToro's fees and overnight financing, and counts an unpriced close as a loss.
- Certainty is measured in the target world's own closes: paper and demo can move the mean, never end real-money exploration. The prior is sceptical, the cautious bound is one standard error until 50 own closes, and a key's stake grows with its real closes.
- A sixth rail bounds the whole book. MAX OPEN RISK stays inside it. Every open bet's risk is measured from the mark to its stop, so a locked winner still counts.
- The drawdown circuit measures from a high-water mark anchored where the operator last armed it, never a rolling 90 days, and catches a slow bleed. Binding is impossible while it is OFF.
- The shadow is graded on a book of its own, the bets only one arm took are graded by the proving simulator, and readiness is a paired sequential test. The operator is told plainly how long an answer takes.
- The ticket's own script judges by the rails while binding, a stop edit re-asks the Bettor, and the operator gets one dial, Boldness.
- The Horde's deciding component is renamed **the Marshal** (Standard-bearer is already the L3 rank). Its legs go through the bots' gates and the fleet's lock, and real-money legs need a seat the operator arms with his PIN.

---

## 0. Summary

1. **The Bettor** is one deterministic function, `bot_program/bettor/brain.size(ctx, *, book)`.
   - **Who calls it:** every candidate bet. That is the bot lane, the TAKE TRADE ticket and the Horde's legs.
   - **The formula:** the stake is a fraction of the world's account equity, put at risk at an *effective* stop:
     - fractional Kelly (a quarter) on a *cautious* edge for that (rule, instrument class, side, world);
     - the edge is a Bayesian posterior: the proving ground's verdict (net of eToro's fees, less a measured drag) is the prior, then the rule's other side, then the key's own fills, time-decayed, net of fees, losses kept;
     - the cautious edge sits one standard error below the posterior until the key has 50 closes in that world, then half;
     - the stake is blended with a small exploratory stake while the world's own record is thin, and it grows with that record (the earned-stake ramp);
     - it is multiplied by a conviction factor that is 1.0 until each voice is graded out of sample, by the drawdown governor, and by the operator's Boldness;
     - the risk already riding on correlated open bets, measured from the mark to the stop, is subtracted;
     - the brain plans inside half the per-bet ceiling on a tail move (the tail fit);
     - only the six rails can cap it after that.
2. **The effective stop is the bad-tick defence.**
   - **The sizing stop:** the worst of the stop, half an ATR(1h) and the measured gap at the next shut.
   - **When the ATR or the bankroll is stale:** the size falls to the exploratory stake, never above.
   - **The sanity ceiling:** "the most one bet may lose, at its stop or on a tail move". It refuses (never clamps) and names the input that drove the size. Because the brain plans inside half of it, a crossing is a symptom.
3. **What gives way to the Bettor:**
   - the 7% risk clamp;
   - the notional caps that widen the stop;
   - MAX SINGLE POSITION;
   - the attack tiers;
   - the quarter cuts (proof, stage, probation);
   - the allocator weight;
   - the correlation taper;
   - the posture scales;
   - the desk's 2% budget and shares;
   - theme legs, concentration, the notional multiple, total exposure and the pledge cap.
4. **What stays:**
   - the gates (cost filter, FAILED proof, stage venue, timing, quote sanity, breakers);
   - the debate's cut;
   - the admin's "reduced";
   - the elite exception;
   - the six rails, MAX OPEN RISK among them (the book ceiling's open-risk half).
   Section A5 gives the full table.
5. **Shadow first.**
   - **Recording:** every bet records the Bettor's size beside today's in a `BetSizing` row, the ticket's refused previews included.
   - **A book of its own:** in shadow the Bettor sizes against a shadow book that carries its own equity, cash, open risk, daily stop and circuit.
   - **Grading:** every night. A bet both arms took is graded from the real fill, each arm net of its own fees. A bet only the Bettor took is graded by the proving simulator.
   - **The /bettor/ page:**
     - compares money, log growth and drawdown, world by world, and never sums the worlds;
     - shows the Bettor's calibration;
     - shows a verdict per world: NOT YET, SAFE (no worse, rails held) or BETTER (proven better), from a paired sequential test, with the bets still needed and a projected date.
   - **Binding:** PIN switches, `bettor_sizes_paper`, then `bettor_sizes_demo`, then `bettor_sizes_live`, each readable only while `drawdown_circuit` is ON.
6. **The ticket.**
   - **The Bettor's block** sits inside the Size fieldset. It leads with what set the size and how it compares with today's, then every step of why.
   - **The override:** the operator may type any size, and only the rails judge it while binding, in the browser as on the server. The override is recorded and graded.
   - **The rails card:** one card on /setup/, behind the trading PIN, with the Boldness dial. Loosening a rail asks for the PIN; tightening never does.
7. **The Horde.**
   - **The banner:** a second (or further) position on a held (world, symbol, side) exists only as a named Horde action of that asset's banner.
   - **The deciding component:** one deterministic component, the Marshal (`bot_program/orcs/marshal.py`). It decides each action with a written reason.
   - **REINFORCE** adds to a proven winner. The leg has reached +1R on a final bar and every stop is at break-even or better. A newer confirmation fact is needed. It is sized on the measured continuation edge, less the risk the idea's legs still carry from the mark to their stops.
   - **SECOND FRONT** is another rule or timeframe with an independent thesis. It becomes a new Orc under the same banner, sized after subtracting the banner's risk times the measured correlation of the two rules' outcomes (0.8 when unmeasured).
   - **REGROUP** closes the weakest leg, or unifies the stops of two legs to the tighter one. Its triggers: a broken thesis, or the banner's risk more than 1.25 times what the Bettor would now allow.
   - **Never:** averaging down by a bot, a hedge, or a widened stop.
   - **Real-money legs** need a seat the operator arms himself with the PIN, after 60 graded legs with real fills on demo.
8. **Plumbing first.** The close-retry drain, the "still holds" check and the reconcile must judge sibling legs by eToro position id. The band shows banners, and the peer table lists the sibling. Both are needed before any leg exists, and they help today: the operator already holds hand-opened siblings.
9. **The order of work.**
   - **First commits:** pure arithmetic and readers, the plumbing fix and the band display, all neutral.
   - **Then:** the ledger and grading in shadow, the page, the rails card and the drawdown circuit.
   - **Then binding,** world by world: paper first, then demo, then real money.
   - **The money-moving commits come last:** real-money binding, the ticket default, the operator's second ticket as a leg, and real-money legs. Each sits behind its own PIN switch, OFF on arrival.

---

## 1. Principles this design keeps

1. **Deterministic and explained.**
   - No model sizes anything; the capital desk's doctrine is kept (`capital_desk.py:8-14`).
   - Every number the Bettor uses is stored on the bet's row, with the sentence the operator reads.
2. **Measured, never believed.**
   - An input moves a size only through its graded effect, measured out of sample.
   - An unmeasured input is neutral (1.0), or cautious where neutral would be generous (a correlation counts its class default, never 0). Its absence is said, never assumed away.
3. **Refuse, never clamp, on bad data.**
   - The sanity ceiling refuses. The brain plans inside half of it, so a size past it is a symptom (an override, a price that ran before the send, or bad data), not a preference.
   - Free cash and the book ceiling fit a size down, because a full account is a real constraint, not bad data.
4. **Worlds apart.**
   - Real money, eToro demo and paper are never summed.
   - Their evidence is never pooled without a world weight and a measured drag (`bot_grading._world_filter`, `bot_grading.py:90-116`), and another world's closes never count as certainty for this one.
5. **Stopping is never harder than starting.**
   - Turning a switch OFF never asks for the PIN, and tightening a rail never does.
   - Loosening a rail, arming a binding switch, re-arming a tripped circuit or arming a seat always does.
   - A switch that turns OFF takes every switch that depends on it OFF too, so nothing resumes without its own PIN.
6. **A failure inside the Bettor never costs an entry while it is in shadow.** While it binds, a failure refuses (`rail_unreadable`): the rails fail closed.

---

# PART A: THE BETTOR

## A1. What it is and where it sits

One package, `bot_program/bettor/`, with one entry point:

```
size(ctx: BetContext, *, book: Book) -> BetVerdict
```

`book` is the real book while the world binds, and the world's shadow book while it is in shadow (A10). The Bettor reads every open bet, the cash and the rails from it, so a shadow Bettor is never sized against positions it did not take.

It has three callers, each with its own context builder:

| Lane | Built where | When |
|---|---|---|
| Bot | `context_for_candidate(cand)` | in `AssetBot.propose_entry`, after the gates and before `_judge_final_size` (`base.py:4554-4720`); again at the send in `execute_entry`, on the last look's fresh price, immediately before `client.market_order` (`base.py:6214`) |
| Ticket | `context_for_ticket(...)` | in `manual_trade._preview` (`manual_trade.py:1477-1700`), again on every stop or leverage edit, and in `_execute` (`:1995-`) |
| Horde leg | `context_for_leg(orc, action)` | in the Marshal (Part B), inside the fleet pass |

**With the desk.**
- The capital desk keeps its ranking (`capital_desk.choose`, `:830-1065`): expected R per unit of marginal risk.
- When the Bettor binds in a world, the desk's choice is replaced by `brain.size_tick(ranked, user, world)`. It sizes the tick's candidates in the desk's rank order, and each one sees the earlier picks as open bets.
- `size_tick` and the Marshal's binding step run inside the fleet pass, under `TICK_LOCK_KEY` (`tasks.py:44-64`), so a leg and a bot entry are never sized against a book the other is changing.
- The desk's fixed budget, shares and `DESK_MIN_MULT` give way to that.
- `DeskDecision` rows are still written. `size_mult` is then `bettor_qty / qty_default` and may exceed 1.0, which the binding branch of `execute_entry` accepts (section A12).

**Without the desk** (the legacy config-after-config loop), the Bettor sizes each candidate against the rows already booked in the tick, so it is sequential by construction.

## A2. The formula

Notation for one candidate bet in money world `w` (live, demo or paper, as `world_of` names them):

| Symbol | Meaning |
|---|---|
| `B` | the bankroll: the world's account equity |
| `d_stop` | money lost per unit at the stop sent: `abs(entry - stop) * vpu` |
| `d_eff` | money at stake per unit for sizing (A2.2) |
| `c` | `d_stop / d_eff`, at most 1: the share of the stake actually lost at the stop sent |
| `r_i` | graded realized R of past closes, net of fees (A2.3) |
| `f` | the stake: the fraction of `B` put at risk at `d_eff` |
| `tail_c` | the class's tail move as a fraction of price (A2.2) |

`qty = f * B / d_eff`, rounded down to the venue's granularity. The money at the stop sent is `f * B * c`.

### A2.1 The bankroll `B`

| World | Source | Fresh |
|---|---|---|
| live | eToro REAL equity: `risk_gate.venue_book_value(user, portfolio, "live")` (`risk_gate.py:343-372`), real-only once Live/paper apart (C1-C3) lands; until then `capital_truth.account_equity` (`capital_truth.py:326`) when `broker_env == "live"` | ≤ 7,200 s (`LIVE_EQUITY_MAX_AGE_S`, `risk_gate.py:340`) |
| demo | the eToro demo equity reading (env "paper"): today the same row with `EtoroAccount.demo` ticked; after Live/paper apart, the demo account's own reading | same |
| paper | `capital_truth.combined_capital` of the user's paper configs (`capital_truth.py:626-643`): one pool, never N times (fixes desk defect D6) | live rows |

**The bankroll-jump guard (bad data).**
- When a reading is more than 20% above the median of that world's readings over the last 24 h, and `capital_truth.paid_flows_for` (`capital_truth.py:738`) records no deposit, the Bettor uses the median.
- It says so: "bankroll held at the 24 h median: the newest reading jumped +31%".
- A reading below the median is used as it is.

**Unmeasured bankroll.** This covers no reading, a stale reading, or another currency (nothing in the codebase converts, as with the desk's one-currency rule, `capital_desk.py:573-600`).
- `B` falls back to the config's own pool (`cfg.capital`, today's denominator).
- The stake is capped at the exploratory stake (A2.5).

**Pools stop being a denominator** when the Bettor binds.
- With `shared_capital_live` ON, every follower is already the whole account.
- With it OFF, a config's share still bounds that config's capital at work, through the cash rail (A4).

### A2.2 Volatility normalisation: the effective stop `d_eff` and the tail move

Size is already risk-denominated (`sizing.py:1-41`), so an ATR stop normalises volatility. Two things are not normalised by the stop alone. The Bettor sizes on the worst of them:

```
d_eff = max(d_stop, d_noise, d_gap)
```

| Term | Value | Source | When unmeasured |
|---|---|---|---|
| `d_noise` | 0.5 × ATR(1h) × vpu. A stop inside half an hour's range is noise, and its tightness must not buy size. The 0.5 is `orcs.constants.MIN_STOP_ROOM_ATR`, pinned equal by a test | venue 1h bars through `orcs/bars.py`, or the newest `TechnicalIndicator` ATR, read **with an age check** of 2 × its timeframe (fixes D7, `risk_levels.py:89-96`) | `d_noise = JUMP_PCT[class] × entry × vpu` (the class's bad-tick bar, `mark_sanity.py:53-54`: forex 0.5%, crypto/stock/etf 3%, index 1.5%, commodity 2%), **and the stake is capped at exploration** |
| `d_gap` | the measured p90 gap at the next shut, when the planned hold (`cand.horizon_hours`) spans one | `orcs/gaps.py` (n ≥ 8; 12 for Corsairs) | when a shut falls inside the hold: `JUMP_PCT[class] × entry × vpu`; otherwise 0 |

**No cost term.** The first draft added the spread (`d_cost`) to `d_eff`. Live fills already carry the spread and the edge is now net of every fee (A2.3), so adding it again counted the spread twice. Costs live in the edge and in the worth rule (A2.5), and nowhere else.

**The tail move `tail_c`** is what a real move can cost a position, not a spike-detection bar. `JUMP_PCT` is "generous on purpose: a crash is confirmed by its second print" (`mark_sanity.py:50-54`), so real moves pass it.

| Class | Floor | Measured |
|---|---|---|
| forex | 3% | the p99 daily or gap move of that symbol over 2 years of venue daily bars, when larger than the floor |
| index | 6% | same |
| commodity | 8% | same |
| etf | 8% | same |
| stock | 15% (an earnings gap) | same |
| crypto | 20% | same |

The floors are our starting values (CPI, the SNB day and the GBP flash crash moved majors about 3%; single stocks gap 15% on earnings; crypto moves 20% in a day). They are constants pinned by a test, and the measured p99 replaces a floor only upward.

**What `d_eff` does not change.**
- The **stop placed**: the Bettor is a sizing brain and never moves a level.
- **R grading**: realized R is still measured against the stop sent (`bot_grading.py:145-301`).
- `d_eff` and `c` are stored on the row, so the grading and the words know how much money the Bettor really put at stake.
- `apply_stop_floor` (`sizing.py:182-224`), the notional cap that **widens** the stop, no longer runs in a world where the Bettor binds. `d_eff`, the tail fit and the sanity ceiling take over its job (map_sizing, summary item 4).

**The unit.** Kelly's edge and second moment are in R at the stop sent, the unit every row measures. When `d_eff > d_stop`, the money at the stop is `f × B × c`: the real Kelly multiple at the stop is `λ × c`, not λ. The words say so, the worth rule multiplies by `c` (A2.5), and the temperament arms record `λ × c`.

### A2.3 The edge: a posterior, never the raw mean

**The key.** The key is (rule, instrument class, side, world).
- The instrument's class is `Instrument.asset_class` by symbol, cached per tick: a row is filed under its config's class, which can differ (`base.py:8191-8193`).
- The side is `AssetBotTrade.side`. The per-side record is a query, not a migration (fixes D1).
- The world is `bot_grading._world_filter`, which keeps eToro demo out of real money (fixes D2 for the Bettor).

**The population.**
- CLOSED rows with an outcome in `capital_desk.GRADED_OUTCOMES` (`capital_desk.py:133`), and rules not in `EXCLUDED_RULES` (`:138`). Window 365 days.
- **Unpriced closes are losses, never absences.** The reconcile and the close-retry drain close a row they could not price with `pnl = NULL` (`reconcile_asset.py:755-772`, `pending_closes.py:1390-1395`: "a stop-out that cost real money is not a scratch"), and such a row has no `realized_r` (`bot_grading.py:288-290`). The estimator counts it at the worse of −1R and the class's p90 gap in R at that row's stop, and its words name it ("2 closes could not be priced: counted at −1R").
- **Inferred exits** (`metadata["exit_price_inferred"]`, `reconcile_asset.py:746-754`) are kept at their inferred R and counted.
- When unpriced and inferred rows together exceed 5% of a key's closes, the key is **unmeasured**: it bets the exploratory stake and says why.
- For the ticket's hand lane, `manual_take` rows by (class, side, world) are read, and only there (A6).

**Costs inside R.** Every `realized_r` the platform books is gross: every close path books `(exit − entry) × qty × FX` (`base.py:3130-3137`, `pending_closes.py:614-633`, `reconcile_asset.py:701-721`), and eToro's fee fields "ride there for the record; no consumer reads them" (`etoro_client.py:2382`). The Bettor nets each close before it reads it:
- **Proportional costs** (crypto 1% a side, `risk_levels.py:345-360`; the overnight financing of every CFD: every ETF, every short and every multiplier above 1, `etoro_client.py:2124-2126`) are taken from eToro's stored close payload where present, otherwise from `risk_levels.venue_fee_fraction` (`:363`) at the booked notional plus a per-night financing model for CFD settlement. In R they do not depend on size, so they are subtracted from `r_i`.
- **Fixed fees** (stocks 1.00 USD a side, `ETORO_STOCK_FEE_USD_PER_SIDE`) depend on size, so they are not in `r_i`. They are charged at the candidate's own size in the worth rule (A2.5).
- The result is stored once per close in a `TradeCost` row (A8), with its source (`venue` or `schedule`).
- Paper rows are netted at the schedule the row would have paid at eToro, so paper never looks cheaper than the venue it stands in for.

**Bad-data defence inside the estimator: one-sided, like the proving judge.** The judge's guard is one-sided "so it can never flatter a rule": a win past +20R is excluded, a loss past −20R is kept, capped there (`backtester/proving/judge.py:19-36`, `sane_trades` `:61-81`). A live `realized_r` comes from real fills, so a large live loss is real money, not a bad print.
- A **win** above +20R, or a win whose exit fill fails mark sanity, is excluded and listed.
- A **win** between +5R and +20R counts as +5R (conservative on the mean).
- **Every loss is kept**, capped at −20R at most. The loss side is never winsorised, for the mean or for the second moment.
- A loss suspected to be bad data goes through the existing unpriced and unmanaged flags (`bot_grading.py:297`), never through an |R| rule.

**Weights.** Each close `i` is weighted by:

```
w_i = world_weight(target w ← row world) * 0.5 ** (age_days_i / 90)
```

| Target world (rows) ← evidence world (columns) | live | demo | paper |
|---|---|---|---|
| live | 1.0 | 0.7, shifted by the demo-to-live drag | 0.5, shifted by the paper-to-live drag |
| demo | 1.0 | 1.0 | 0.6, shifted by the paper-to-demo drag |
| paper | 0.8 | 0.8 | 1.0 |

Each cell is pinned in `tests/test_bettor_evidence.py` (demo→live 0.7, paper→live 0.5, live→live 1.0).

**The drag between worlds** (`evidence.world_drag(rule, inst_class, src, dst)`, new). `bot_grading.paper_live_expectancy_gap` (`:535`) cannot serve: it splits by venue, so its "live" side holds demo (`bot_grading.py:577-582`, `_venue_filter` `:118-137`), it has no demo-to-live gap and no side, and "nothing in the decision path consumes this yet" (`:570-572`).
- It is computed on `_world_filter` for each pair (paper→live, demo→live, paper→demo), per (rule, class), as the difference in mean net R.
- It is shrunk toward the class-level drag with `DRAG_N0 = 20`, and its standard error is kept.
- Until both worlds hold at least 10 closes, the default is used and the words say "unmeasured": −0.10R paper to live, −0.05R demo to live, −0.05R paper to demo, each with a standard deviation of 0.10R.

**The measure of certainty is weight mass, not Kish.** The Kish `n_eff = (Σ w)^2 / Σ w^2` does not move when every weight is scaled, so a world weight of 0.5 never reduced certainty in the first draft. Now:
- `W = Σ w_i` (world weight and decay both inside) is the precision of the evidence, in the mean and in its standard error alike.
- `W_own` is the mass of the target world's **own** closes, and `n_own` their raw count in the window. Only these end exploration (A2.5): paper and demo can move the mean, never retire real-money exploration.
- `W_x = W − W_own` is the cross-world mass, whose mean is shifted by the drag.

**The prior, built in two steps.**
1. **The proving ground's verdict** for the same key (`proof.newest_verdict`, `proof.py:115`), read net of eToro's fees: `evidence.proving_prior` recomputes the holdout expectancy from the holdout `ProvingTrade` rows with eToro's fee schedule (the simulator charges `DEFAULT_COST_BPS`, `simulate.py:10-11, 115`, 10 bps on crypto against about 200 at eToro). The verdict itself is untouched.
   - **PROVEN** (simulated): `mu0 = holdout_net + drag_sim`, where `drag_sim` is the measured simulated-to-world drag (below). The prior's variance is `var0 = se_holdout^2 + var(drag_sim)`, and `n0 = min(30, s0^2 / var0)` with `s0 = 1.45R`.
   - **LIVE_PROVEN** is treated as UNPROVEN for the prior: that tier is chosen by the rule's own live record (`proof.py:18-24`), which then updates the prior again, so it would be counted twice.
   - **UNPROVEN** with a verdict row: `mu0 = min(0, holdout_net + drag_sim)`, `n0 = 30`.
   - **No verdict:** `mu0 = 0`, `n0 = 30`: a sceptical zero-edge prior worth 30 trades, so a lucky streak does not buy a large stake.
   - FAILED never reaches the Bettor: the gate refuses (`base.py:4589-4621`).
   - **The simulated drag `drag_sim`** is measured, not assumed. For keys that have both a verdict and at least 10 graded closes in a world, it is the mean of (graded net mean − holdout net expectancy), by class, shrunk toward the default with `DRAG_N0`. It absorbs the three biases a flat deduction hid: the winner's curse (PROVEN requires a holdout above 0, `judge.py:4-12`, so a zero-edge key that passed it with 20 holdout trades shows about +0.26R), survivorship (`run.universe()` keeps only today's active instruments, `run.py:56-62`), and the cost gap to eToro. Until measured: −0.15R with a standard deviation of 0.15R, said as "unmeasured".
   - **The words name the survivorship:** "proving universe: today's active instruments only".
2. **The rule's other side**, (rule, class, other side, world), **with this key's own closes left out**. When its own mass is at least 10, its posterior (from step 1 and its own closes) becomes this key's prior, with `n0 = min(its mass, 15)`. A thin side borrows from the other side, never from itself.

Then the key's own record updates that prior.

**The posterior** (normal-normal, with a variance prior):

```
mu_hat   = (n0 * mu0 + Σ w_i r_i) / (n0 + W)              # r_i of other worlds shifted by their drag
s^2      = (10 * 1.45^2 + Σ w_i (r_i - mu_hat)^2) / (10 + W)    # 1.45R: sizing.py:31-32
var_mu   = s^2 / (n0 + W) + (W_x / (n0 + W))^2 * var_drag     # the drag's own uncertainty
sigma_mu = sqrt(var_mu)
z        = 1.0 while n_own < 50, else 0.5
mu_edge  = mu_hat - z * sigma_mu                              # the cautious edge
```

`var_drag` is the measured drag's standard error squared plus a between-rule term (the spread of the class's drags), or the default's 0.10² when unmeasured.

**Why z = 1 until 50 own closes.** About 100 (rule, class, side) keys are read at once. At half a standard error, a zero-edge key shows a cautious edge above zero about 31% of the time, so several always would. The proving judge corrects for the number of candidates it tried (`judge.py:8-9`). One standard error (16%) plus the earned-stake ramp (A2.5) does the same job for live keys, and it is a per-key count the operator can read.

### A2.4 Conditioning: the score and the regime

Conviction enters through the edge wherever it can be measured, so nothing is counted twice. The desk warns about counting one edge three times (`capital_desk.py:22-26`).

**The decision score** (fixes D3: `composite_score` is stored on every row and never calibrated).
- The score conditions the edge only after a **monotone score effect has been shown out of sample**: the tercile cut points are fitted on the older half of the key's rows (or its parent's), and the effect is tested on the newer half.
- Each tercile must then hold at least 30 rows by weight.
- A tercile's prior is the key's posterior **without that tercile's rows**, with `n0 = 100` until the between-tercile variance is measured by empirical Bayes. A 10-row tercile has a standard error of 0.46R, so a weak prior let it replace the edge with noise.
- The candidate's tercile edge then replaces `mu_edge`.
- This replaces the attack tiers' raw thresholds (`base.py:8125-8178`) with a measured map.

**The regime.**
- **One taxonomy:** the bar-derived label the proving ground uses (`simulate.regimes`, `simulate.py:127-141`: trend or range, `+hi_vol`), computed for every live entry at entry time on the decision frame's venue bars, and stamped on every BetSizing row. Live rows before this build carry none, so `n_reg` starts at 0.
- **The weight `tau` is graded, not trusted.** It is the regime-conditioned edge's measured out-of-sample improvement in predicting R for the key (fitted on older rows, scored on newer), clipped to [0, 1] and shrunk by `n_reg / (n_reg + 30)`. It is 0 until 100 rows carry a regime.

  ```
  mu_c = tau * mu_edge(regime) + (1 - tau) * mu_edge
  ```

- **The Mind's market label** (risk_on, risk_off, trending: `brain/models.py:83-98`, `brain/synthesizer.py:647`) is a shadow voice of K until graded (A2.6). Its trust score (`brain/context.py:168-202`), a Brier proxy on its predictions, says nothing about whether the label changes a rule's R, so it no longer gates anything.

### A2.5 The Kelly stake, exploration, the ramp and declining

**The fractional Kelly stake:**

```
m2   = s^2 + sigma_mu^2 + mu_hat^2
f_K  = 0.25 * max(mu_c, 0) / m2
```

- Kelly for R multiples maximises `E[log(1 + f R)]`, which gives about `mu / E[R^2]`.
- The quarter (λ = 0.25) is the brain's temperament, not a cap. At the stop sent it is `λ × c` (A2.2).
- The uncertainty enters twice: in the cautious edge, and in the predictive second moment.

**Exploration:**

```
f_x    = x_w * risk_fraction(cfg)        # x_live = 0.4, x_demo = x_paper = 1.0
omega  = W_own / (W_own + 20)            # the target world's own closes only
```

- `risk_fraction(cfg)` is `sizing.py:140-161`, 0.25% by default, so live exploration is 0.10%.
- The config's own `extras['risk_per_trade_pct']`, and a persona's 0.15 / 0.25 / 0.40, become that config's exploration base.
- **Exploration pays eToro's costs only where they are small.** An exploratory bet is placed only when its round-trip costs at this stake (fixed fees over the money at the stop, plus the proportional fees and financing in R) are at most `FEE_MAX_R = 0.25R`.
  - When they are larger at `f_x`, the **fee floor** is the smallest stake at which they are 0.25R. The key explores there only when that stake is at most 0.5% of `B` (`EXPLORE_MAX_FRACTION`) and its cautious edge from every world is positive and pays the fixed fees at that stake.
  - Otherwise it skips with `COSTS_EXCEED`: "learns on demo: eToro's 2.00 USD of fees would be 1.1R of a 1.80 USD stake".
  - The exploratory stake actually used is `f_x0` (`f_x` or the fee floor).

**The blend and the earned-stake ramp:**

```
f_base = min( omega * f_K + (1 - omega) * f_x0 ,  f_x0 * (1 + n_own / 10) )
```

- A key's stake grows with its own closes in that world: at most twice the exploratory stake after 10 closes, six times after 50, eleven times after 100. A lucky 25-close streak at +0.8R bought 2.43% of the real account in the first draft; it now buys at most 0.35%.
- The ramp's slope (10) is temperament, graded in the temperament arms (A10).
- **For a key that closes rarely, exploration never ends completely.** Under the 90-day decay, a key closing 4 times a month holds an own mass near 17 and an `omega` near 0.46 for good. That is deliberate: such a key's recent record is never more than a few dozen trades. The half-life itself is graded in the temperament arms.

**The multipliers:**

```
f_stand = f_base * K * D * Boldness
```

`K` is A2.6, `D` is A2.7, and Boldness is the operator's dial on the rails card (A7), 1.0 by default.

**Declining.** The stake is 0 in three cases:
- When `n_own ≥ 20` and `mu_hat + sigma_mu < 0`: the rule is confidently losing in this world. The skip code is `BETTOR_DECLINED`, and its words give the numbers.
- **The worth rule**, for a Kelly bet: the expected gain at the stop sent must cover the fixed fees, `mu_c × f × B × c > fixed round-trip fees`. `mu_c` is already net of proportional costs.
- `COSTS_EXCEED`, for an exploratory bet (above).

### A2.6 The conviction factor `K`: graded voices only

```
K = clip( Π_i (1 + v_i * (g_i - 1)), 0.5, 1.5 )
```

- `g_i` is a voice's raw suggestion.
- `v_i` in [0, 1] is its **measured validity**:
  - computed nightly from the BetSizing ledger;
  - the shrunk out-of-sample regression coefficient of `(realized R − mu_c)` on `(g_i − 1)`, fitted on the older bets and checked on the newer ones, clipped to [0, 1];
  - 0 until the voice has at least 100 graded bets and its coefficient's lower bound is positive at 95%, corrected for the number of voices and spent over the nightly looks (O'Brien-Fleming alpha spending). An 80% bound over 30 bets, read nightly across four voices, would validate a pure-noise voice within months; at n = 30 a slope's standard error is about 1.3.
- **At launch every `v_i` is 0, so `K = 1.0`.**

| Voice | `g_i` | Note |
|---|---|---|
| Proof verdict | — | already in the prior (A2.3); never also in K |
| Score, regime | — | already in the edge (A2.4) |
| The Mind's market label | its posture scale | shadow voice; graded like the others |
| Thesis | army type (`orcs/army.py:85-112`), and the operator's typed thesis on a ticket | graded per (army type, class) |
| Smart money | its entry scale, 0.5 or 0.75 (`smart_money.py:639-705`) | replaces that scale's direct multiply while the Bettor binds |
| Council (the Gambler) | all_in 1.25, press 1.10, normal 1.00, small 0.75 (`council.py:321-343`) | **a law change**: "nothing in an order path, sizing ... reads them" (`council.py:36-50`). Shadow arm only (A10) until the operator says yes. It can exist before an order only for a ticket where he clicked "Ask the council", and for a Horde leg (the root's sitting already exists) |
| Trade debate | — | not in K. The Executioner's binding cut stays after the Bettor, as today (`base.py:6016-6126`) |

### A2.7 The drawdown factor `D`

```
D = share_allocator.governor_for(dd_w)
```

- This is the platform's existing governor (`share_allocator.py:329-336`): 1.0 down to 0.4 as the drawdown runs from 5% to 20% (`DD_KNEE`, `DD_MAX`, `DD_FLOOR`, `:74-76`).
- `dd_w` is the **drawdown circuit's own measure** (A4): the world's equity under the high-water mark anchored where the operator last armed the circuit, net of flows. It is never the rolling 90-day `capital_truth.equity_drawdown` (`capital_truth.py:796-829`), under which a slow bleed reads as no drawdown at all.
- It applies whatever `crisis_mode` says (fixes D8).
- Kelly on current equity already shrinks as the account shrinks. `D` adds the humility of a model that may be wrong while it is losing.

### A2.8 Correlation with open bets

This is portfolio Kelly for one marginal bet, holding the others fixed. With R units normalised, the optimum is the standalone stake minus the risk already riding on correlated bets:

```
f = max(0, f_stand - Σ_j rho_eff(i, j) * f_j)
```

**The open bets `j`.**
- Every OPEN or CLOSE_PENDING row of the user in world `w` (of the book: real or shadow), the manual lane included, plus this tick's earlier picks.
- **`f_j` is row j's risk from the mark to its stop**, as a fraction of `B`: `qty × |mark − stop| × vpu / B`, at the worse of the stop sent and the stop eToro holds (the pair the Horde reads, `horde._venue_stop_state`, `horde.py:788-818`), plus the gap shock (`qty × entry × vpu × gap p90`) when a shut falls inside its hold.
  - **A locked winner still counts.** `B` is broker equity, open profit included (`capital_truth.account_equity`, `capital_truth.py:326-345`), so a leg whose stop sits at break-even can still give back all of its open profit. The first draft counted it 0, which let every REINFORCE take a full standalone stake (Part B).
  - A row with no stop counts its notional × `tail_c`.
- **Not the desk's reading.** The desk counts the initial stop (`capital_desk.py:573-627`).

**The correlation `rho`: the Bettor's own matrix** (`bettor/correlation.py`). The desk's matrix (`capital_desk.correlation_matrix`, `capital_desk.py:441-568`) reads `PriceData` by instrument, timeframe and time only, with no source filter, on raw log returns. The chart diagnosis (`scratchpad/issues/chart.md` C3, C5) found the 1h and 4h series mixing eToro bars with Yahoo stand-ins (the GC=F future against eToro spot, about 1% apart) and a stored bar with low = 0. One seam or one spiked close drags a Pearson correlation toward 0. The Bettor therefore:
- reads **one source per series**, venue first, as `orcs/bars.py` does, never mixed within a window;
- uses 4h bars, 45 days, timestamp-aligned, at least 60 shared bars;
- uses **rank (Spearman) correlation** of log returns, which one spiked close cannot dominate;
- counts a symbol as **unmeasured** when its window holds a suspect bar (a move past `JUMP_PCT` unconfirmed by the next bar, a low or close at or below 0, a source seam);
- signs the correlation by the direction of each bet.
- The desk keeps its own matrix; the risk gate's index-aligned matrix (D4, `portfolio/correlation.py:108-111`) is never read.

**When unmeasured or suspect, the class default, never 0:**

| Pair | rho |
|---|---|
| same symbol, same side | 1.0 |
| shared currency leg, same commodity complex (`risk_gate._theme_legs`, `:1731-1738`), same sector, crypto majors, same index family | 0.8 |
| same class otherwise | 0.6 |
| different classes | 0.3 |

At rho 0.7, five correlated coins carry about 1.4 stakes in all; at the floor of 0.2 they carried five.

**Floors by market posture.** The posture level comes from `market_stress` (`market_stress.py:187-330`), read whatever `crisis_mode` says; a reading older than 2 h counts as "stressed".

| Posture | Same class | Different class |
|---|---|---|
| calm | 0.2 | 0.1 |
| stressed | 0.4 | 0.2 |
| crisis | 0.6 | 0.4 |

- `rho_eff = max(rho, floor)`.
- **A negative measured `rho` counts as 0** before the floor. A diversifier gets its standalone stake, never more: a noisy negative correlation must not buy size.

**What this bounds, and what it does not.** With every pair at least at `rho_floor`, the stakes form a geometric series, so the book's heat is at most `max_bet_loss_pct / rho_floor`. With the 10% ceiling that is 100% of `B` across classes in calm and 50% within one class. That is no bound the operator would accept, so the book ceiling's open-risk half (rail 6, his own 15%) stays. /bettor/ shows the Bettor's realised heat beside it.

### A2.9 Quantity, the tail fit, the minimum and worth

1. **The raw quantity:** `qty = f * B / d_eff`, rounded **down** to the venue's granularity. That is `_round_qty` with the venue's fractional answer, as today (`base.py:4697-4708`).
2. **The tail fit (the brain's own).** The brain plans no bet whose tail-move loss passes half the operator's per-bet ceiling:

   ```
   qty <= TAIL_SHARE * max_bet_loss_pct * B / (entry * vpu * tail_c)       # TAIL_SHARE = 0.5
   ```

   When this binds, `binding = tail_fit` and the words say "held to half your ceiling by a 3% EURUSD tail move". A forex bet at 10% ceiling is held near 1.7 times the account in notional. `TAIL_SHARE` is temperament, graded in the temperament arms. Because the brain plans inside half the ceiling, the ceiling itself refuses only a symptom.
3. **The venue minimum,** from eToro's `minPositionExposure` (`base.py:7630-7720`).
   - When `qty` is below it, the Bettor rounds up to the minimum only when **`mu_c > 0`** and `qty_min * d_eff ≤ VENUE_MIN_ROUNDUP × f × B` (2×). There is no absolute term: the first draft's `max(2 f B, 0.5% B)` could raise any exploration stake to 0.5% of the account.
   - Otherwise it skips with `VENUE_MIN_SIZE` and states both numbers.
   - Every round-up is recorded with `binding = venue_min_up` and graded as its own arm on /bettor/, so "take everything at the minimum" is never credited to the Kelly arithmetic.
4. **The worth rule** (A2.5) is checked on the final quantity: `mu_c × qty × d_stop > fixed round-trip fees`.
5. **Leverage is unchanged.** It moves margin, never risk (`base.py:7024-7200`). The attack mode's cash half stays.

### A2.10 The rails cap it, and only the rails

The rails are checked in this order, at the proposal and again at the send on the last look's fresh price (A4). The order differs from the rails' numbers, which A4 uses throughout; A4 gives each one in full.

| Order | Rail (A4 number) | What happens |
|---|---|---|
| 1st | Drawdown circuit (3) | tripped: size 0 |
| 2nd | Daily loss stop (2) | SHUT: 0. ELITE ONLY: the elite verdict (`base.py:8268-8347`), at × 0.5 (`ELITE_SIZE_SCALE`, `risk_gate.py:240`), at most 2 per 24 h |
| 3rd | Sanity ceiling per bet (5) | refuses when `max(qty * d_eff, qty * entry * vpu * tail_c) > max_bet_loss_pct * B`. It never clamps |
| 4th | Book ceiling (6) | **fits** the size down so that, after this bet, (a) the open risk from the marks to the stops is at most `max_open_risk_pct` of `B` and (b) `Σ notional × tail_c` over every open bet, break-even legs included, is at most `max_book_tail_pct` of `B`; then re-applies the minimum and the worth rule; refuses below them |
| 5th | eToro free cash (1) | **fits** the size down to the free margin, then re-applies the minimum and the worth rule; refuses below them |
| 6th | Venue minimum (4) | never below (A2.9) |

### A2.11 Inputs and their sources

| Input | Source | Fresh | Unmeasured means |
|---|---|---|---|
| Bankroll `B` | A2.1 | ≤ 2 h; jump guard | exploration cap, config pool |
| Graded closes | `AssetBotTrade`, `bot_grading._world_filter`, netted by `TradeCost` | live query, cached 15 min per key | prior only (`omega` 0) |
| Unpriced and inferred closes | `pnl` NULL; `metadata["exit_price_inferred"]` | same | over 5% of the key: unmeasured |
| Proving prior | `ProvingVerdict` via `proof.newest_verdict`; holdout `ProvingTrade` rows, netted | nightly 03:40 (`config/celery.py:540`) | `mu0 = 0, n0 = 30` |
| Drag between worlds | `evidence.world_drag` on `_world_filter` | per read, cached 15 min | default drag, said "unmeasured" |
| Simulated drag | `evidence.sim_drag` | nightly | −0.15R ± 0.15R |
| Score terciles | `AssetBotTrade.composite_score` | per read | no conditioning |
| Regime | `simulate.regimes` on venue bars at entry | at entry | `tau = 0` |
| ATR(1h) | venue bars, age-checked | 2 × timeframe | `d_noise = JUMP_PCT`; exploration cap |
| Gap p90 | `orcs/gaps.py` | memoised daily | `JUMP_PCT` if a shut is in the hold |
| Tail move | p99 of venue daily bars over 2 years | memoised daily | the class floor |
| Costs | `TradeCost`; `risk_levels.venue_fee_fraction`; financing model | per close; per tick | the schedule |
| Open bets, marks and stops | the book's OPEN / CLOSE_PENDING rows; eToro's held stop; the venue mark | live rows | no stop: notional × `tail_c` |
| Correlation | `bettor/correlation.py` (600 s cache) | per tick | the class default, then floors |
| Posture | `market_stress` | 900 s; stale after 2 h | "stressed" floors |
| Drawdown | the circuit's anchored measure (A4) | after each equity sync | `D = 1.0`, said; the circuit holds its last state |
| Free cash | `_leverage_headroom` cells (`base.py:7441-7570`) | ≤ 3,600 s, refused past it; re-read after every booking (pace fix F1) | refused, as today |
| Venue minimum | eligibility row | cached | refused, as today |
| Mark | `mark_sanity` entry read (`mark_sanity.py:273-348`) | this tick, and again at the last look | bots refuse (gate). While binding, an unreadable last look refuses (`rail_unreadable`). On a ticket the Bettor offers no suggestion on a suspect quote |

Cost: at most 8 queries per candidate, cached per (key, tick). With the `bettor` switch OFF there are no queries and no rows (pinned by a test).

### A2.12 Worked examples

The examples were computed with `scratchpad/bettor/tools/example_v2.py`.

**Example 1: EURUSD long on the operator's book today.**
- **Book:** `B` is 1,800 USD of real equity; 412 USD free; 1× only (`etoro_leverage_live` OFF).
- **Record:** 34 real closes on forex long, own mass 28, average +0.22R net of eToro's overnight fees, s.d. 1.35. No demo or paper closes are used here.
- **Prior:** PROVEN, holdout +0.18R net over 60 trades; the simulated drag is unmeasured (−0.15R), so `mu0` is +0.03R and `n0` is 30.

| Step | Value |
|---|---|
| `mu_hat` | (30 × 0.03 + 28 × 0.22) / 58 = **+0.122R** |
| `s`, `sigma_mu` | 1.377; 1.377 / √58 = 0.181 |
| `z` | 1.0 (34 own closes, under 50) |
| `mu_c` | 0.122 − 0.181 = **−0.059R**, so Kelly is 0 |
| `omega` | 28 / 48 = 0.58: 0.42 × 0.10% = **0.042%** (the ramp allows 0.44%) |
| `D` | drawdown 6%: × 0.96, so **0.040%** |
| Correlation | GBPUSD long carries 0.30% from its mark to its stop, rho 0.62: −0.19%. AAPL long 0.20%, measured 0.05, floored to 0.1: −0.02%. Result **0** |

- **The Bettor would not bet:** "the cautious edge is below zero at 34 closes, and GBPUSD long already carries more of the same bet".
- **Today's platform** would risk 0.25%, or 4.50 USD: 833 units, about 904 USD, under eToro's 1,000 USD minimum. It refuses too (`VENUE_MIN_SIZE`, `base.py:5853-5910`). The first draft's Bettor took this trade at the minimum; with the review's fixes, 34 closes are not yet enough to show a cautious edge above zero.

**Example 1b: the same pair with a strong record.**
- **Record:** 120 real closes, own mass 90, +0.35R net, s.d. 1.40; the same prior.

| Step | Value |
|---|---|
| `mu_hat`, `sigma_mu` | +0.270R; 0.128 |
| `z`, `mu_c` | 0.5 (120 own closes); **+0.206R** |
| `f_K` | 0.25 × 0.206 / 2.064 = **2.49%** |
| Blend | `omega` 0.82: 2.06% |
| Ramp | 120 own closes allow 0.10% × 13 = **1.30%**, so 1.30% |
| `D` | × 0.96: 1.25% |
| Correlation | −0.21%: **1.04%**, 18.76 USD at stake, 3,473 units, 3,769 USD (2.1 × `B`) |
| Tail fit | a 3% EURUSD move would cost 113 USD (6.3%); half the 10% ceiling allows **2,765 units**, 3,000 USD: 14.93 USD at the stop (0.83%) |
| Worth | 0.206 × 14.93 = 3.07 USD expected, against no fixed fee on forex: passes |
| Rails | ceiling: 0.83% at the stop, 5.0% on the tail. Book: open risk 1.33% of 15%; tail 186 USD, 10.3% of 50%. **Cash at 1×:** 3,000 USD needed, 412 free, which buys 379 units, under the 1,000-unit minimum: **refused (`rail_cash`)**. At 30× it needs 100 USD and passes |

**Example 2: the bad tick.**
- **The situation:** a frozen feed leaves EURUSD with a 0.03% stop, and the ATR row is 3 hours old.
- **Today's arithmetic:** at 2% that would be 66 times the pool in notional (map_sizing, summary item 4).
- **The Bettor's reading:** the ATR is unmeasured, so the stake is capped at exploration (0.10%, 1.80 USD). `d_noise = 0.5% × 1.085`, so `d_eff = 0.0054` and `c = 0.06`: 332 units, 360 USD, 0.11 USD at the stop.
- **The minimum:** 332 is under eToro's 1,000 units, and the round-up needs a positive cautious edge and 5.43 USD ≤ 2 × 1.80; neither holds. **No bet.**
- **Had anything still produced a huge size,** the tail fit and then the ceiling would stop it, and the staff alert would name the input: "stop 0.03% from a 3 h old ATR".

**Example 3: what the record keeps.**
- A close booked at +40R by a bad print is excluded and listed. A +9R close counts as +5R.
- A −28R gap through a 0.09% forex stop counts as −20R and lowers the edge. A −8R gap counts as −8R.
- **Why it matters:** 100 closes, 40 at +2R, 57 at −1R and 3 gaps at −8R, have a mean of −0.01R and an `E[R^2]` of 4.09: Kelly is 0. The first draft's clip at −3R read +0.14R and 2.44, and would have bet a quarter Kelly of 1.43% on a losing rule.

**Example 4: a new rule with no record, on real money.**
- **The prior:** no verdict, so `mu0 = 0, n0 = 30`; `mu_c = −0.26R` (z = 1), Kelly 0, `omega = 0`: the stake is `f_x` = 0.10%, 1.80 USD.
- **Forex, index, commodity:** under eToro's 1,000 USD minimum, and no round-up without a positive cautious edge: skipped.
- **Stocks:** eToro's 2.00 USD round trip would be 1.1R of a 1.80 USD stake: `COSTS_EXCEED`, skipped. The fee floor (8 USD, 0.44%) needs a positive cautious edge that pays the fees there; a new rule has none.
- **Crypto:** 2% of notional round trip is 0.5R at a 4% stop: skipped. At a 10% stop it is 0.2R and the rule explores at 0.10%.
- **So on a 1,800 USD real account a new rule learns on demo and paper,** at the full 0.25% of those books. Today's platform pays 0.44R in fees on every stock ticket at its 0.25% default on this book; the Bettor makes that cost visible.

**Example 5: REINFORCE with the root measured from its mark** (Part B).
- The root, EURUSD long, 2,000 units, entered at 1.08188 with its stop 0.0027 away (5.40 USD, 0.30% at risk); it is at +1.2R (1.08512) with its stop at break-even (eToro holds 1.08190). From the mark to the stop it carries 1.2 × 5.40 = 6.48 USD, **0.36%**.
- The continuation stake is 0.65% (a quarter Kelly on +0.06R cautious, `m2` 2.2, × 0.96).
- **The add is 0.65% − 0.36% = 0.29%**, 1,636 units at 1.08512, its stop at the root's break-even 0.00324 away (5.30 USD). The first draft counted the root as 0 and sized 3,636 units.
- **The banner after:** 11.78 USD from the marks to the stops (0.65%), average entry 1.08334.

## A3. A rule with little or no record

- **The stake is the exploratory one:** `f_x` = 0.4 × the config's risk fraction on real money (0.10% by default), the full fraction on demo and paper.
- **Exploration pays eToro's costs only where they are at most 0.25R** (A2.5). On a small real account that means most learning happens on demo and paper.
- **It fades smoothly** as the target world's own record grows (`omega`), never because another world's record grew. It never jumps at a threshold.
- **The stake grows with real closes** (the ramp): at most 2 × `f_x` after 10, 6 × after 50.
- **A clearly losing rule is declined** in that world: `n_own ≥ 20` and the upper bound below 0. It keeps trading wherever its stage and Aragorn already send it (paper). The Bettor never chooses a venue.
- **Unread inputs fall to `f_x`, never above:** bankroll, ATR, an evidence lane that raises, a key with too many unpriced closes.
- **No exploration on a held asset on real money:** a Horde leg needs a measured edge (Part B). Paper may explore adds at `f_x` to build their record.

## A4. The survival rails

| Rail | Definition | Default | Lanes | Unmeasured | Where |
|---|---|---|---|---|---|
| **1. eToro free cash** | margin (notional / L) ≤ the cash cell − pledged since − the withdrawal hold. The pledge ceiling goes: the operator said yes to "at 100%, eToro's free cash decides". It also binds early on a losing book, because it divides by an equity that carries the losses (digest:118) | eToro's own number | bots and ticket, **in the preview too** (pace fix F2) | refused past 3,600 s, as today | `base.py:7441-7570`; ticket `manual_trade.py:2670-2697` |
| **2. Daily loss stop** | realised P&L over the trailing 24 h ≤ −X% of the real book. Past it, elite only (× 0.5, at most 2 per 24 h); nothing past 1.5 × X. **Real money only**, once Live/paper apart lands (`realized_since` counts demo today, `risk_gate.py:662-683`) | the stored `max_daily_loss_pct` (the comments record the operator's 8%) | bots hard; the ticket follows the card's toggle "apply to my tickets" (OFF = a warning, as today) | the per-config fallback (`base.py:4080-4144`) | `risk_gate.daily_loss_state` (`:716`) |
| **3. Drawdown circuit** (new) | equity ≥ X% under its **anchored high-water mark**, or a **slow bleed** of X/2 in 30 days: **no new entries and no Horde legs** in that world. Each world has its own circuit | 25% (the governor already floors size at 0.4 from 20%) | bots and Horde hard; the ticket is refused with "re-arm on the rails card" | unreadable equity: the circuit holds its last state and says so | new `bettor/rails.py`, reading the equity readings directly |
| **4. Venue minimum** | never below eToro's minimum; the round-up rule of A2.9 | the venue's | all | refused, as today | `base.py:5853-5910`; `manual_trade.py:1485-1520` |
| **5. Sanity ceiling per bet** (new) | the most one bet, or one **banner** (Part B), may lose: `max(qty * d_eff, notional * tail_c)` ≤ X% of `B`, where `tail_c` is the class's tail move (A2.2). **Refuses, never clamps**, and alerts the staff with the dominant input | 10% (today's 7% risk clamp, plus a tail half that covers the per-class notional caps' job) | all, including overrides | the tail half uses the class floor | new `bettor/rails.py` |
| **6. Book ceiling** (new) | after this bet, over every open bet of the world, break-even legs included: (a) the open risk from the marks to the stops ≤ `max_open_risk_pct` of `B`; (b) `Σ notional × tail_c` ≤ `max_book_tail_pct` of `B`. **Fits down**, then the minimum and the worth rule; refuses below them | (a) the stored MAX OPEN RISK, 15% (the operator's own "15% de risque ouvert max", `risk_gate.py:856-858`); (b) 50% | bots and Horde hard. Ticket: (b) hard; (a) follows "apply to my tickets" (OFF = a warning, as today) | no mark: the entry price; no stop: notional × `tail_c` | new `bettor/rails.py` |

**Why the book ceiling exists.** With MAX SINGLE POSITION, MAX NOTIONAL MULTIPLE, MAX TOTAL EXPOSURE and the pledge cap gone, nothing bounded the book's notional but eToro's free cash, about 30× at `LEVERAGE_MAX` (`etoro_client.py:382`). `notional_state` records why the 4× cap was written: "two yen crosses worth twenty-nine times itself ... silent about what a 3.3% move does to a book thirty times smaller than its positions" (`risk_gate.py:1139-1147`). One forex bet at 2% on a 0.10% effective stop is 20 × `B`; a 3% USD move then costs 60% of the account. Rail 6(b) bounds the sum of what every position loses on its class's tail move, so the account survives the day the operator's charts showed spikes for real.

**The drawdown circuit.**
- **Its mark** is `DrawdownCircuit.hwm`: the highest equity reading, net of deposits and withdrawals (`capital_truth.paid_flows_for`), since the operator last armed the circuit. There is no rolling window: under the 90-day window a loss of 2% a week reaches −65% in a year while the 90-day drawdown never passes 1 − 0.98^13 = 23% (`capital_truth.py:750-829`), and an account down 30% that stays there reads 0% after 90 days.
- **The mark rises only on a confirmed reading:** one that passes the bankroll-jump guard (A2.1) and is matched by the next reading. A spiked equity print cannot lift the mark and then trip the circuit on the next honest reading.
- **States.**
  - ARMED, then TRIPPED on a fresh reading at or past X under the mark ("depth"), or when equity is X/2 or more below its reading 30 days earlier, net of flows ("slow bleed").
  - TRIPPED, then ARMED automatically only on a genuine recovery: two confirmed readings within X/2 of the same anchored mark.
  - Otherwise TRIPPED, then ARMED only by the operator with the PIN on the rails card. **That re-arm restarts the mark at today's equity:** the operator accepts the loss as the new base, and `D` returns to 1.0.
  - The state survives the switch: turning `drawdown_circuit` OFF and ON again finds it as it was, TRIPPED included, with the same mark.
- **In shadow** (switch `drawdown_circuit` OFF) it records "WOULD TRIP" and says so on the card, on /bettor/ and on Telegram, once per crossing.
- **What the operator is told** when it trips or re-arms while ON, on the main chat (and the alarm chat when he chooses it), once per event, in percent only (the alarm law, B7):

  ```
  REAL MONEY: no new entries and no Horde legs. The drawdown circuit tripped:
  the account is 25.3% under its high-water mark since you armed it on
  2 Nov (circuit 25%). It re-arms by itself if the account recovers to within
  12.5% of that mark, or on the rails card with your PIN (the mark then
  restarts at today's equity).
  ```

  The slow-bleed variant reads "tripped on a slow bleed: down 12.6% in 30 days (half the circuit)". The re-arm reads "REAL MONEY: entries resume. The drawdown circuit re-armed: the account is back within 11.9% of its mark" or "re-armed by you with the PIN; the mark restarts at today's equity". The Horde band's head shows the same line on that world's tab, and `SKIP_WORDS` gains `rail_circuit` in these words.

**At the send: the last look, and failing closed.** The rails are judged at the proposal price, but the order goes at market after the debate and the last look, which lets the price run up to half the way to the target (`DEBATE_DRIFT_MAX = 0.5`, `base.py:4904, 4936-4947`). On a 2:1 target the entry-to-stop distance can double.
- While binding, `execute_entry` re-reads the last look's fresh price, recomputes `d_stop`, `d_eff`, notional and `c`, fits `qty` down (never up) so the money at stake stays the Bettor's `f`, and re-runs `rails.judge` immediately before `client.market_order` (`base.py:6214`). A crossed ceiling, book, cash or circuit refuses with its rail's code.
- While binding, `rails.judge` **fails closed**: an exception or an unreadable input (the last look's ticker included, which today lets the order pass, `base.py:4915-4928`) refuses with `rail_unreadable`. The platform's own `risk_gate.check` fails open on an exception (`risk_gate.py:1978-1984`); the rails do not. Pinned by a test.
- In shadow the same re-judge is computed and recorded, and costs nothing.

**The layers against bad data,** none of which alone has to be perfect:

| Layer | What it does |
|---|---|
| 1 | The entry-quote sanity: bots refuse (`mark_sanity.py:273-348`); the ticket's Bettor makes no suggestion |
| 2 | The bankroll-jump guard; the circuit's mark rises only on confirmed readings |
| 3 | `d_eff` floors: noise, gap, bad-tick bar |
| 4 | Age checks on the ATR and the bars, leading to the exploration cap |
| 5 | The estimator excludes wins past +20R and keeps every loss; unpriced closes count as losses |
| 6 | The correlation reads one source per series, by rank, and counts a suspect window as unmeasured |
| 7 | The tail fit: the brain plans inside half the ceiling |
| 8 | The sanity ceiling refuses; the book ceiling fits down |
| 9 | The last look re-judges every rail at the send, failing closed |
| 10 | A new Morgul guard, G11, "a bet, banner or book past its ceiling", which should never fire. It is critical, and `morgul_brake` acts on it as on any critical finding |

## A5. What happens to each existing cap

"Binding" means "while `bettor_sizes_<world>` is ON for the world of the order" (and, for the ticket, `bettor_ticket_<world>`, A11). While it is OFF, everything below is exactly as it is today.

| Cap or multiplier | Today | Under the Bettor | How |
|---|---|---|---|
| Default risk 0.25%; persona fractions (`sizing.py:50`; `personas.py`) | the stake | **Replaced** | it becomes the exploration base `f_x` |
| `MAX_RISK_FRACTION` 7% (`sizing.py:80`), bots and ticket | refuses | **Replaced by rail 5** | the sanity ceiling (10% by default, the operator's own number) |
| `AGGRESSIVE_RISK_FRACTION` 2% (`sizing.py:86`) and the stop-floor note | the ticket's appetite warning (`manual_trade._risk_appetite`, `:575-628`: "{f}% of the pool per trade — ten losses in a row ...", and "tighter stops get WIDENED to it") | **Rewritten** while binding | "this pool's 0.40% is now only the Bettor's exploration stake"; the widening note is dropped, because nothing widens |
| Notional cap per class and the stop floor (`sizing.py:102-122, 182-224`) | widens the stop | **Replaced** | `d_eff`, the tail fit and the ceiling's tail half; no widening |
| ATR stop band 0.2%-25% (`risk_levels.py:26-60`) | a level rule | **Kept** | not a size |
| Attack tiers 0.50 / 0.75 / 1.00 (`base.py:8095-8178`) | risk scale | **Replaced** | the score terciles, once shown out of sample (A2.4). The cash half ("auto" leverage) is kept |
| Smart money size scale (`smart_money.py:639-705`) | × 0.5 / × 0.75 | **Replaced** | a K voice, neutral until graded. Its stop move is kept |
| Cost filter (`base.py:4539-4552`) | gate | **Kept** | gate |
| Stage `live_small` × 0.25 (`rule_actuator.py:73-125`) | size | **Replaced** | the prior, the record and the ramp; the stage still chooses the venue (research, paper, live) |
| Aragorn probation × 0.25 (`aragorn.py:84`) | size | **Replaced** | same; the bench (to paper) is **kept** as a gate |
| Posture scales: stressed, recovery, drawdown governor, streak (`posture.py:56-230`) | size, crisis mode only | **Replaced** | posture into the correlation floors, the governor into `D`, the streak into the time decay. Crisis to paper for risk-on longs is **kept** as a gate |
| Size by proof: unproven × 0.25 (`proof.py:76-81`) | size | **Replaced** | the sceptical prior. FAILED refused is **kept** as a gate |
| Admin "reduced" × 0.5 (`rule_actuator.py:128-142`) | size | **Kept** | the operator's own hand, applied after the Bettor |
| Allocator weight [0.10, 3.00] (`meta_allocator.py:285-301`) | size | **Removed** while binding | the same evidence would count twice; the allocator keeps proposing in shadow |
| Correlation taper (`base.py:4642-4673`) | × 1.0 down to 0.25 | **Replaced** | A2.8, on the Bettor's own matrix |
| Elite past the daily stop × 0.5, at most 2 | size and count | **Kept** | part of rail 2 |
| MAX SINGLE POSITION 20% (`risk_gate.py:1313-1384`; `manual_trade.py:294-315`) | refuses | **Removed** | rail 5 per bet, rail 6 for the book, rail 1 for cash |
| MAX OPEN RISK 15% (`risk_gate.py:848-933`) | refuses | **Kept, as rail 6(a)** | measured from the marks to the stops, break-even legs included; moves to the rails card, the PIN to loosen |
| MAX NOTIONAL MULTIPLE 4× (`risk_gate.py:1130-1189`) | refuses | **Replaced by rail 6(b)** | the book's loss on each class's tail move ≤ 50% of `B`. A tail move is comparable across classes; a notional multiple treats a forex and a crypto book alike |
| MAX TOTAL EXPOSURE 100% | refuses | **Removed** | rails 1 and 6 |
| MAX ACCOUNT PLEDGED (`base.py:396-426`) | refuses | **Removed** | rail 1, the operator's yes on 100% |
| Theme legs 3 (`risk_gate.py:1751`) | refuses | **Replaced** | rho 0.8 on shared legs (A2.8) |
| Concentration, 2 clips (`risk_gate.py:1480-1550`) | ticket warning | **Replaced** | the banner's budget (Part B) |
| Duplicate expression (`risk_gate.py:1606-1664`) | refuses | **Re-keyed** to banners (Part B) | |
| Desk budget 2%, shares 40 / 60 / 50%, min mult 0.25 (`capital_desk.py:78-128`) | size ≤ 1 | **Replaced** | the sequential `size_tick` (A1); the desk's ranking is **kept** |
| Debate cut and veto (`trade_debate.py:38-54`) | ≤ 1, binding after 30 graded | **Kept** | a graded pre-order power, after the Bettor |
| Breakers per config, 4 losses or 10% (`safety.py:242-367`) | gate | **Kept** | gate, Horde legs included (B3) |
| Per-config daily loss 2% (fallback) | gate | **Kept** | part of rail 2 |
| `max_concurrent_positions` | gate | **Kept** | a style setting; counts banners (Part B) |
| Cooldown after a close | gate | **Kept** | |
| Ticket: 7% risk, notional per class, pool free, MAX SINGLE POSITION (`manual_trade.py:789-848, 1679-1692`) | hard | **Replaced** while `bettor_ticket_<world>` binds | rails 1, 4, 5 and 6 only, in the browser as on the server (A6); the funding proposal keys on free cash |
| Ticket warnings: open risk, exposure, notional, theme, cost, R:R, proof, timing, venue health | warnings | **Kept** as warnings | information; the replaced caps join them |
| Cash and pledge | hard | **Rail 1** | |
| Venue minimum | hard | **Rail 4** | |
| Daily loss | bots hard, ticket warning | **Rail 2** | the ticket follows the toggle |

**What /setup/ says while a world binds.** Each replaced or removed field on the Risk Limits card (`setup.html:136-230`: MAX TOTAL EXPOSURE, MAX SINGLE POSITION "refused with the arithmetic", MAX ACCOUNT PLEDGED "refused, never shrunk", MAX NOTIONAL MULTIPLE, CORRELATION SIZE TAPER, MAX THEME LEGS) shows its state per world: "Given way to the Bettor on REAL MONEY (bettor_sizes_live ON); still applies to DEMO and PAPER." The personas page's "0.40% per trade, three at a time" (`personas.py:328`) gains "on a binding world, this is the exploration stake". MAX OPEN RISK and MAX DAILY LOSS become read-only there, with a pointer to the rails card. Pinned in `tests/test_rails_card.py`.

## A6. The manual ticket

**The preview.** `manual_trade._preview` adds one block to its payload (beside `proof_advisory`, `:1906`):

```
"bettor": {
  "mode": "shadow" | "binding",
  "qty": 2765, "stake_money": 14.93, "stake_pct": 0.83,
  "at_stop_money": 14.93, "at_stop_pct": 0.83,
  "today_qty": 833,
  "binding": "tail_fit",
  "confidence": "measured" | "thin" | "unmeasured",
  "headline": "...", "lines": [...the why, in order...],
  "terms": {"f": 0.0083, "B": 1800, "d_noise": ..., "d_gap": ..., "tail_c": 0.03,
            "tail_cap_qty": 2765, "venue_min_qty": 1000},
  "rails": {"cash": {...}, "daily": {...}, "circuit": {...},
            "ceiling": {...}, "book": {...}, "venue_min": {...}},
  "bet_id": 9123
}
```

**The evidence for a ticket.**
- A ticket on a Signal reads the signal's rule key (rule, class, side, world). The Signal lane (`capital_desk._signal_rs`, `:229`) joins with the paper weight and drag.
- A ticket from the instrument page reads **the hand's own record**: `manual_take` rows by (class, side, world), with the same prior. Today these rows are excluded from every bot record, and they stay excluded there.
- `signal_backing_advisory` (`:1204`) is unchanged.

**Where it sits.** Inside the Size fieldset (`base.html:2464-2491`), above Units, Cash committed and Notional, never in `warnHtml` among the warning cards. The size comes last because it "follows from all three" (`base.html:2146-2150`); the block follows it.

**What the operator sees** (English, in the popup's own style; Example 1b at 30×):

```
THE BETTOR  (shadow: today's size is still the default)
Bigger than today: 2,765 units against 833, on a measured edge; held to half
your ceiling by a 3% EURUSD tail move.
- Edge: golden_cross on forex, long, real money: 120 closes (90 by weight),
  average +0.35R after eToro's overnight fees; +0.27R with the proving
  ground's prior; +0.21R at the cautious bound.
- Stake: a quarter Kelly is 2.49%; 82% Kelly, 18% exploration gives 2.06%;
  120 real closes allow up to 1.30%. So 1.30%.
- Drawdown 6% under the high-water mark since you armed the circuit: x0.96.
- Already riding: GBPUSD long (correlation 0.62) carries 0.19% of the same
  bet; AAPL 0.02%. So 1.04%.
- Tail: 3,473 units would lose 6.3% of the account on a 3% move. The Bettor
  plans inside half your 10% ceiling: 2,765 units.
At stake: 0.83% of the real account at your stop (14.93 USD).
Rails: cash OK (100 USD of margin at 30x; 412 free, read 2 min ago) ·
daily stop OPEN (-0.4% of 8%) · circuit armed (6% of 25%) · ceiling 10%:
0.83% at the stop, 5.0% on a tail move · book: open risk 1.3% of 15%,
tail 10.3% of 50%.
Units [ 833 ]   [RESET TO TODAY'S SIZE (833)]   [USE THE BETTOR'S (2,765)]
```

- **The headline leads with what set the size** (the stored `binding`) and how it compares with today's: "Smaller than today: GBPUSD long already rides 0.19% of the same bet"; "Bigger than today (1,000 against 833) because of eToro's minimum; the Bettor alone would bet 0.14%"; "Exploring: thin record (4 closes)".
- **Two risks, said apart.** "At stake" is `f × B`; "at your stop" is `qty × d_stop`. When `d_eff > d_stop` both are shown, with a line built from `d_eff_why`: "Your stop is 0.03% away; the Bettor sizes as if it were 0.50% (half an hour's range)" or "... as if it were the weekend gap (p90 1.2%)". The ticket's R AT STAKE (`base.html:2680`) and the fill message's "Risk if the stop is hit" (`notifications.py:1203`) keep meaning the stop.
- **No suggestion on a suspect quote.** The block reads "No suggestion: the quote is suspect (crossed / far from the platform's quote). The Bettor does not size off it."
- **Declined.** The block reads "The Bettor would not bet: ..." with the numbers.
- **No suggestion is not a decline.** A key with no continuation record (Part B), or a hand lane with no record at all, gets "No suggestion" and demands no reason.

**The buttons: one restore button per size.** The first draft's extra Size field is dropped; the Units field is the only size field.
- **Shadow:** Units defaults to today's size. Buttons "RESET TO TODAY'S SIZE (833)" and "USE THE BETTOR'S (2,765)". A declined Bettor leaves today's size in Units.
- **Binding:** Units defaults to the Bettor's size. Buttons "RESET TO THE BETTOR'S SIZE (2,765)" and "TODAY WOULD SEND 833". A declined Bettor leaves Units empty, with its sentence; either button or a typed size fills it, and the typed reason is then required.

**The client-side verdict follows the rails while binding.** The ticket's script today blocks sizes on the old caps (`judgeSize`, `base.html:2120-2144`: the 7% `max_risk_dollars`, the class `max_notional`, `poolFree()`), and `okBtn.disabled` follows it (`base.html:2739`), so the Bettor's own size could be greyed out by a cap that no longer applies. The client's checks are the server's in the server's order (`base.html:2040-2045`), so in a binding world:
- the preview ships the rails' bounds: the ceiling at the stop and on the tail half, the book's room, the margin against eToro's free cash, and the venue minimum;
- `judgeSize` mirrors `rails.judge` in its order;
- the old caps move into `warnHtml` as warnings;
- the meter and the POOL line read eToro's free cash instead of the pool.
- Pinned in `tests/test_bettor_ticket.py` (binding half): the Bettor's suggested size is always pressable unless a rail refuses it.

**When the operator moves the stop.** Today the size "follows the stop" by holding a money budget (`autoQty`, `base.html:2034-2038, 2691-2694`), so a tighter stop buys more units, and `_execute` sizes `risk_dollars / dist` on a stop override (`manual_trade.py:2327-2329`). The Bettor sizes on `d_eff` precisely so that tightness does not buy size.
- The preview ships `terms` (`f`, `B`, `d_noise`, `d_gap`, `tail_c`, the tail cap and the minimum), so the browser shows `f × B / d_eff`, tail-fitted, at once, marked "checking".
- A stop edit then re-asks the server for the Bettor block, debounced like the leverage select (`base.html:2493-2497`). TAKE stays disabled until the server's answer matches the stop shown.
- When the edited stop sits inside `d_eff`, the block says so: "your stop is inside half an hour's range: sized as if it were 0.50% away".
- Pinned: the qty shown after a stop edit equals the qty `_execute` sends.

**Shadow on the ticket, refusals included.** When today's preview refuses for size (`'Sized to zero ...'`, `manual_trade.py:1481-1483`; the venue minimum past 7% of the pool, `:1502-1509`), it returns no ticket, so the Bettor would be hidden exactly where it disagrees most. While `bettor` is ON:
- the refusal is returned together with the Bettor block: "Today refuses: ... The Bettor would bet 1,000 units (0.30%): it takes effect when the Bettor binds your tickets on real money";
- a BetSizing row is recorded with `today_outcome = refused`, at most one per (user, symbol, side, stop) per 10 minutes, so the overrides section and the readiness counts include these cases.

**The override.**
- While shadow, Units defaults to today's size, and today's caps still judge it (`validate_qty_override`, `:851-886`). "USE THE BETTOR'S" only fills the field.
- While binding in that world (`bettor_ticket_<world>` ON):
  - Units defaults to the Bettor's size;
  - `validate_qty_override` calls `bettor.rails.judge`, so only the six rails judge the typed size;
  - the old caps turn into the warnings of A5.
- **A typed reason is required** when the typed size is more than twice the Bettor's, or when the Bettor declined. The reason is recorded.
- **Recorded:** the BetSizing row stores `override_qty` and `override_reason`.
- **Graded:** /bettor/ has a section "Your overrides against the Bettor": the money, the growth and the hit rate of the overrides.
- **Executed:** `_execute` re-sizes against the same book (the PIN is still required), re-judges the rails at the fresh price, records the row, and attaches the trade.

## A7. The rails card

One card, "Survival rails", at the top of /setup/'s Risk Limits. It is posted to `dashboard.views.setup_rails`.

| Field | Stored | Bounds | Notes |
|---|---|---|---|
| eToro free cash | read-only | — | the cells, their age and their world; "re-read after every order and close" once F1 lands |
| Daily loss stop % | `Portfolio.max_daily_loss_pct` (moves here from the open form) | 0.1-100 (`dashboard/views.py:3595-3620`) | |
| Drawdown circuit % | `Portfolio.max_drawdown_pct` (new) | 5-60, default 25 | per world: the state, the anchored mark and since when, the trip and re-arm history, and "Re-arm now (restarts the mark at today's equity)" (PIN) |
| Venue minimum | read-only | — | eToro's per class, with when it was measured |
| Sanity ceiling per bet % | `Portfolio.max_bet_loss_pct` (new) | 0.5-50, default 10 | "The most one bet, or one banner, may lose at its stop or on a tail move. A bet past it is refused, never shrunk; the Bettor plans its own bets inside half of it. To bet smaller across the board, lower Boldness." |
| Book: open risk % | `Portfolio.max_open_risk_pct` (moves here from the open form) | 1-100, stored 15 | "the most every open bet together may lose from the marks to the stops, locked winners included" |
| Book: tail move % | `Portfolio.max_book_tail_pct` (new) | 10-100, default 50 | "the most the whole book may lose if every position takes its class's tail move (forex 3%, stocks 15%, crypto 20% ...)" |
| Boldness | `Portfolio.bettor_boldness` (new) | 0.25 / 0.5 / 1 / 1.5, default 1 | "multiplies every stake the Bettor computes, after its own judgment. 1 is the Bettor as designed." Graded on /bettor/ as a temperament arm |
| Apply to my tickets | `Portfolio.rails_on_tickets` (new, default False) | toggle | the daily stop and the book's open-risk half bind the operator's own tickets (OFF: warnings, as today) |

**The PIN.**
- **Loosening any field takes the trading PIN.** That means raising a percentage or Boldness, turning the ticket toggle OFF, or re-arming the circuit. The check is `core.trading_pin.check(request, pin, door=ACT, act="Rails")`, the counted door `switch_pin.check_trading_pin` uses (`core/switch_pin.py`).
- **Tightening never asks.**
- Every change writes an audit row (`bot_program.audit.record_event("rails_changed", ...)`) with who, the field, before and after, the direction ("loosens" or "tightens") and the door. Never the PIN.
- The old /setup/ inputs for MAX DAILY LOSS and MAX OPEN RISK become read-only, with a pointer to the card.

## A8. Data model and migrations

**`bot_program/bettor_models.py`**, imported from `bot_program/models.py` like `desk_models` (`models.py:787`). Status and kind values are tuples in `bot_program/bettor/constants.py`, never `choices=`, the Orcs' convention (`orcs/models.py:11-13`).

`BetSizing` holds one row per sized bet:

| Group | Fields |
|---|---|
| Identity | `created_at` (index), `version` (char 12, e.g. "b2"), `user` FK, `world` (char 5), `lane` (char 8: bot / manual / horde), `mode` (char 8: shadow / binding), `book` (char 8: real / shadow), `config` FK null, `trade` FK AssetBotTrade null (SET_NULL), `desk_decision` FK null, `horde_action` FK null (added by the Part B migration), `orc` FK null |
| Bet | `symbol`, `side`, `asset_class` (the instrument's), `rule_name`, `evidence_key` (char 160, index), `regime` (char 16), `score` |
| Money | `bankroll` (Decimal 14,4), `bankroll_ccy`, `bankroll_source` (char 40), `bankroll_age_s`; `price`, `stop`, `vpu`, `d_stop`, `d_eff`, `d_eff_why` (char 60), `c`, `tail_c`, `tail_loss` |
| Today | `today_qty` (Decimal 18,8), `today_risk_money`, `today_outcome` (char 16: sent / refused / not_proposed), `today_refusal` (char 40) |
| Bettor | `bettor_qty`, `bettor_stake_money`, `f`, `f_kelly`, `f_explore`, `f_explore_basis` (char 12: f_x / fee_floor), `ramp`, `omega`, `mu_hat`, `sigma_mu`, `z`, `mu_c`, `n_own`, `w_own`, `w_cross`, `drag` (JSON), `prior_source` (char 20), `prior_mu`, `prior_n`, `k`, `conviction` (JSON {voice: {g, v}}), `d_factor`, `boldness`, `corr_sub`, `fees_money` (expected round trip at this size), `binding` (char 24: kelly / explore / declined / no_suggestion / unmeasured / riding / costs_exceed / tail_fit / venue_min_up / rail_cash / rail_ceiling / rail_book / rail_daily / rail_circuit / rail_venue_min / rail_unreadable), `rails` (JSON), `words` (JSON list of sentences), `inputs` (JSON: everything a temperament re-run needs) |
| Act | `sent_qty` null, `last_look` (JSON: fresh price, re-fitted qty, re-judged rails), `override_qty` null, `override_reason` (char 300) |
| Grade | `realized_r` null, `pnl_today` null, `pnl_bettor` null, `growth_today` null, `growth_bettor` null, `grade_source` (char 12: fill / simulated), `table` (char 8: both / bettor / today), `feasible` (bool null), `graded_at` null, `ungradeable` (char 80) |

- Indexes: (user, world, created_at), (trade), (graded_at), (evidence_key).

`TradeCost` holds one row per closed trade the Bettor has netted: `trade` OneToOne AssetBotTrade (CASCADE), `fixed_money`, `proportional_money`, `financing_money`, `prop_r` (the proportional costs in R), `source` (char 12: venue / schedule), `computed_at`. It is written at grading and by a nightly backfill, and read by the evidence readers. It touches no existing row.

`DrawdownCircuit` holds one row per (user, world), unique on that pair:
- `state` (armed / tripped / would_trip);
- `hwm` (the anchored mark, net of flows), `hwm_since` (when the operator last armed it, or when the row began), `hwm_pending` (a reading awaiting its confirmation);
- `tripped_at`, `tripped_dd`, `trip_kind` (depth / slow_bleed);
- `rearmed_at`, `rearmed_by`, `rearm_via` (auto / pin).

**Migrations.**
- `bot_program/migrations/00NN_bettor.py`: the three tables. Take the next free number at build time. Main is at `0045_orcs_dossier_drums`, and threefix, Live/paper apart, Orders at a price and Orcs O2 may each add one first, so rebase before merging.
- `portfolio/migrations/0018_portfolio_survival_rails.py` adds:
  - `max_drawdown_pct` (Float, default 25);
  - `max_bet_loss_pct` (Float, default 10);
  - `max_book_tail_pct` (Float, default 50);
  - `bettor_boldness` (Float, default 1.0);
  - `rails_on_tickets` (Bool, default False).
- Both migrations are schema only, reversible, and carry no data migration. `max_open_risk_pct` and `max_daily_loss_pct` already exist and only move on the page.

**Trade metadata.** `metadata["bettor"]` holds `{bet_id, mode, f, stake_money, d_eff, c, binding}` on every row sent while the `bettor` switch is ON. It is the only new key, and a test pins it.

## A9. States

| Thing | States |
|---|---|
| The Bettor in one world | **OFF** (`bettor` OFF: nothing is read or recorded). **SHADOW** (`bettor` ON: computed against the shadow book and recorded; today's size is sent). **BINDING** (`bettor_sizes_<world>` ON as well, which needs `drawdown_circuit` ON: the Bettor's size is sent). While binding, today's chain is still computed as the counterfactual, so the comparison never stops |
| One bet | computed → recorded → sent / declined (Bettor) / refused (rail) / refused (gate, today's arm only) → closed → graded / ungradeable |
| Drawdown circuit | ARMED ⇄ TRIPPED (auto re-arm only on a genuine recovery within X/2 of the anchored mark, or the PIN, which restarts the mark). WOULD_TRIP while the switch is OFF. The state survives the switch |
| Daily stop | OPEN / ELITE ONLY / SHUT (unchanged) |
| Readiness, per world | NOT YET → SAFE → BETTER (shown, never applied) |

## A10. Shadow, grading and the comparison page

**What is recorded in shadow.**
- **Bots:** a BetSizing row at the proposal. The candidate carries `cand.bettor`, a new field on `EntryCandidate` (`candidates.py:38-99`). The row is updated at the send with `sent_qty`, the last look and the trade.
- **Size refusals:** for every bet today refuses **for size**, the Bettor's verdict is recorded with `today_outcome = refused`. The refusals that count:
  - `SIZED_TO_ZERO`;
  - the 7% ceiling;
  - MAX SINGLE POSITION, MAX OPEN RISK, MAX NOTIONAL MULTIPLE and theme legs;
  - `VENUE_MIN_SIZE`;
  - cash and pledge;
  - `DESK_DISPLACED`;
  - the stop floor's skip.

  `_skip` gains a `size_refusal=` tag at those sites (`base.py:1541`, `:5319-5541`, `:5853-5910`), so the hook needs no guessing.
- **Gate refusals** (cost, stage, FAILED, timing, quote) refuse in both arms and are not recorded.
- **Ticket:** a row at `_execute`, and a row for each preview today refuses for size (A6).
- **Fencing:** any exception inside the Bettor is logged and costs nothing. The entry continues exactly as today (pinned by a test).

**The shadow book** (`bettor/shadow_book.py`). The Bettor in shadow must not take sequences of trades that binding could not fund, on an account with about 1.7k of 1.8k already used (`scratchpad/issues/pace.md`, issue 2). One shadow book per (user, world):
- **Equity:** the world's real equity at the first shadow row, plus the Bettor arm's graded P&L since, net of fees.
- **Open bets:** the Bettor arm's own open bets at the Bettor's quantities, marked at the venue marks. Those are what its correlation, heat and book rail read.
- **Free cash:** eToro's free cash, plus the margin today's arm holds in use, minus the margin the Bettor arm would hold.
- **Its own daily stop and circuit,** computed on the shadow equity.
- A shadow bet the shadow book could not fund is fitted or refused exactly as binding would, recorded with `feasible = False` when refused, and graded as 0 for the Bettor arm.

**The grading,** `bettor.grading.grade_bets`, runs nightly at **03:55 UTC**, after the desk at 03:45 (`config/celery.py:664`). Three tables, never mixed:

| Table | Which bets | How each arm is graded |
|---|---|---|
| **Both took** (paired, clean) | today sent it and the Bettor would have bet | the same fill and exit: `pnl_arm = gross_per_unit × qty_arm − fees(qty_arm)`, each arm's own fixed fees, proportional fees and financing. The first draft's `(pnl + fixed_fees) × ratio − fixed_fees` added back fees `pnl` never contained |
| **Only the Bettor took** (modelled) | today refused or did not propose it | the **proving simulator's own policy** (`backtester/proving/simulate.simulate`, `simulate.py:173`): gaps fill at the open, care's break-even and locks (`simulate.py:144-171`), the no-progress clock, the class cost plus eToro's fees. Never `capital_desk.walk_bracket`, whose stop is "-1.0 by construction" with no cost, gap or care (`capital_desk.py:1358-1393`) and which marks at a 168 h horizon (`:1443-1480`) |
| **Only today took** | the Bettor declined or refused | today's real P&L; the Bettor arm 0 |

- **Growth:** `log(1 + pnl_arm / equity_arm_at_entry)`, each arm on **its own** book's equity.
- **Never summed:** worlds and currencies.

**Readiness: a paired sequential test, read nightly.** At 60 bets, point criteria cannot tell a better Bettor from a worse one (`scratchpad/bettor/tools/power.py`: with true edges N(+0.05, 0.08)R and an R s.d. of 1.40, a Bettor that knows every edge passes an 80% calibration bound 34% of the time and a skill-less one 21%; "growth ≥ today's" passes 67% against 54%, because below Kelly a bigger size grows faster whenever the sample's mean happened to be positive). Instead:
- **Paired only.** READY reads the "both took" table alone.
- **Allocation skill, apart from size level.** For each paired bet `i` with net result per unit of stake `x_i`, `d_i = log(1 + a_i x_i) − log(1 + k b_i x_i)`, where `a_i` is the Bettor's stake, `b_i` today's, and `k` rescales today's sizes to the Bettor's mean risk. The size level (the ratio of mean risks) is reported separately, never as skill.
- **The bound:** a one-sided 95% lower bound on the mean of `d_i`, by bootstrap in day blocks (bets of one day move together), with the alpha spent over the nightly looks (O'Brien-Fleming), so reading it every night cannot manufacture a pass.
- **The verdicts, per world (shown, never applied):**
  - **NOT YET:** fewer than 60 paired bets or 30 days, or a condition below fails.
  - **SAFE (no worse, rails held):** the bound on `d_i` is above `−NONINF_MARGIN`; the Bettor arm's maximum drawdown on its shadow book is at most 1.25 × today's and under half the circuit; no unexplained ceiling refusal; at most 5% of its bets infeasible.
  - **BETTER (proven):** SAFE, and the bound on `d_i` is above 0.
- **Real money also needs** SAFE after at least 30 days binding on demo (eToro's real mechanics), or, if demo cannot run, 30 days binding on paper with SAFE.
- **Time to an answer, printed on the page.** /bettor/ prints, per world, the paired bets graded, the measured bet rate (check E1), the bets needed for BETTER at 80% power given the measured effect and spread, and the projected date. At about 2 graded bets a day, SAFE needs about 30 days; BETTER with perfect skill needs about 600 to 1,500 bets, which is 10 months to 2 years. The page says so in one sentence: "Real money will rest on SAFE (no worse, rails held) and on demo, not on proof that the Bettor is better: that proof needs about N more bets, about M months at today's pace."

**The page /bettor/** (`dashboard/views_bettor.py`).
- **Layout:** world tabs, REAL, DEMO and PAPER, never summed.
- **Head:** graded bets n per table, and for each arm:
  - money P&L;
  - summed log growth;
  - max drawdown of its own book;
  - a Sharpe-like mean / s.d. of return on its own equity.
- **Readiness:** the verdict, the paired bound, the size level, what is missing, the bets still needed and the projected date.
- **Sizing skill:** the rank correlation between `log(bettor_qty / today_qty)` and the realised R, on the paired table.
- **Calibration:** `mu_c` buckets against the realised mean R, with intervals. The Bettor is judged on its own predictions.
- **Temperament arms:** the same stored inputs re-run at λ in {0.125, 0.25, 0.5}, z in {0.5, 1}, the ramp's slope in {5, 10, 20}, `TAIL_SHARE` in {0.25, 0.5, 1}, the half-life in {90, 180} days, and the operator's Boldness values. Each is labelled with its real multiple at the stop (`λ × c`). A constant changes only by a commit, shadow first.
- **Round-ups:** the venue-minimum round-ups as their own arm.
- **Voice validities `v_i`,** the council's and the Mind's shadow arms included: what K would have been, and what it would have earned.
- **Heat:** the Bettor's book heat, from the marks to the stops, beside today's open-risk figure and the 15% rail.
- **The rails:** state and headroom, and every ceiling refusal with its driver.
- **Overrides:** the operator's sizes against the Bettor's (A6).
- **The ledger:** filterable; each row shows today's size, the Bettor's, the ratio, R, both P&Ls, its table and the binding words.

## A11. Switches and defaults

| Key | Group | On arrival | PIN to turn ON | Needs ON | Meaning |
|---|---|---|---|---|---|
| `bettor` | System | OFF | no (moves nothing) | — | shadow: computes against the shadow book and records; today's size is sent |
| `drawdown_circuit` | System | OFF | no (it only stops) | — | OFF: WOULD TRIP is recorded and said, and nothing binds. ON: the circuit halts new entries and legs |
| `bettor_sizes_paper` | System | OFF | **yes** (`PIN_SWITCHES`) | `bettor`, `drawdown_circuit` | the Bettor sizes paper bot bets |
| `bettor_sizes_demo` | System | OFF | **yes** (`LIVE_MONEY_SWITCHES`: live-mode configs reach eToro demo) | same | the Bettor sizes eToro demo bot bets |
| `bettor_sizes_live` | System | OFF | **yes** (`LIVE_MONEY_SWITCHES`) | same | the Bettor sizes real-money bot bets; A5 applies |
| `bettor_ticket_paper`, `_demo`, `_live` | System | OFF | **yes** (paper in `PIN_SWITCHES`, the others in `LIVE_MONEY_SWITCHES`) | `bettor_sizes_<world>` | the ticket defaults to the Bettor's size and is judged by the rails only, in that world |

Part B adds `horde_reinforce`, `horde_legs_<world>` and `horde_ticket_legs_<world>` (B12).

**How the PIN and the dependencies work.**
- `core/platform_control.py` gains `PIN_SWITCHES = LIVE_MONEY_SWITCHES + ("bettor_sizes_paper", "bettor_ticket_paper", "horde_legs_paper", "horde_ticket_legs_paper")`.
- `switch_pin.needs_pin` (`core/switch_pin.py:120-122`) reads `PIN_SWITCHES`, so the Wall's live-money count (`core/wall_facts.py:433-440`) does not move for the paper keys.
- **Every key of this design joins `BULK_ENABLE_EXEMPT`** (`platform_control.py:126`), `bettor` included. The System group's "all on" turns every key outside that list ON (`switch_pin.set_category`, `:267-279`), and the list exists because "one tap of the System group's all on on a phone armed all seven at once, with no PIN" (`platform_control.py:88-96`).
- **Each dependent switch reads OFF unless every key it needs is ON.**
- **A gating key that turns OFF takes its dependents OFF:** they are written OFF and recorded `SWITCH_DISARMED` (via `"cascade:<key>"`), so any resume goes through their own PIN. The gating keys are `bettor`, `drawdown_circuit`, `bettor_sizes_<world>`, `horde_reinforce`, `orcs` and `horde_legs_<world>`.
- So **the Bettor never binds without its circuit:** turning `drawdown_circuit` OFF stops all binding at once, and a tripped circuit has exactly one way back for the Bettor's power, the PIN'd re-arm (its state survives OFF and ON).
- Descriptions stay under 300 characters (the registry test).
- Tested: "all on" after a pause never brings binding back; turning `bettor` or `drawdown_circuit` OFF disarms every binding switch.

**The code constants** live in `bot_program/bettor/constants.py`. Each is pinned by a test, and any change is a commit graded in shadow.

| Group | Constants |
|---|---|
| Version | `BETTOR_VERSION = "b2"` |
| Temperament | `KELLY_FRACTION = 0.25`, `EDGE_Z = 0.5`, `EDGE_Z_THIN = 1.0`, `EDGE_Z_THIN_N = 50`, `RAMP_N = 10`, `TAIL_SHARE = 0.5`, `BOLDNESS_CHOICES = (0.25, 0.5, 1.0, 1.5)` |
| Estimator | `R_WIN_EXCLUDE = 20`, `R_WIN_CLIP = 5`, `R_LOSS_CAP = -20`, `UNPRICED_R = -1.0` (or the worse class gap), `UNPRICED_MAX_SHARE = 0.05`, `HALF_LIFE_DAYS = 90`, `WINDOW_DAYS = 365`, `SIGMA0_R = 1.45`, `NU0 = 10` |
| Prior | `PRIOR_SCEPTIC = (0.0, 30)`, `SIM_DRAG_DEFAULT = (-0.15, 0.15)`, `SIM_MAX_N = 30`, `PARENT_MIN_MASS = 10`, `PARENT_MAX_N = 15` |
| Worlds | the world weights (A2.3), `DRAG_DEFAULT` (paper→live −0.10, demo→live −0.05, paper→demo −0.05, each ± 0.10), `DRAG_N0 = 20`, `DRAG_MIN_N = 10` |
| Exploration | `EXPLORE_HALF_N = 20`, `EXPLORE_SHARE = {"live": 0.4, "demo": 1.0, "paper": 1.0}`, `EXPLORE_MAX_FRACTION = 0.005`, `FEE_MAX_R = 0.25` |
| Decline | `DECLINE_MIN_N = 20` |
| Score and regime | `TERCILE_MIN_MASS = 30`, `TERCILE_N0 = 100`, `REGIME_MIN_N = 100` |
| Conviction | `K_CLIP = (0.5, 1.5)`, `VOICE_MIN_N = 100`, `VOICE_ALPHA = 0.05` |
| Correlation | `RHO_FLOOR` (A2.8), `RHO_UNMEASURED = {"same_symbol": 1.0, "theme": 0.8, "same_class": 0.6, "cross_class": 0.3}`, `RHO_MIN_BARS = 60`, `RHO_DAYS = 45` |
| Effective stop | `NOISE_ATR = 0.5` |
| Tail move | `TAIL_MOVE_FLOOR = {"forex": 0.03, "index": 0.06, "commodity": 0.08, "etf": 0.08, "stock": 0.15, "crypto": 0.20}`, `TAIL_YEARS = 2` |
| Bankroll | `BANKROLL_MAX_AGE_S = 7200`, `BANKROLL_JUMP = 0.20` |
| Venue minimum | `VENUE_MIN_ROUNDUP = 2.0` |
| Circuit | `SLOW_BLEED_DAYS = 30` (trip at half the circuit), `HWM_CONFIRM_READS = 2` |
| Readiness | `READY_MIN_N = 60`, `READY_MIN_DAYS = 30`, `READY_ALPHA = 0.05`, `NONINF_MARGIN` (log growth per bet, 0.0002), `INFEASIBLE_MAX = 0.05`, `DEMO_BINDING_DAYS = 30` |

## A12. Files and functions

| File | What |
|---|---|
| `bot_program/bettor/__init__.py` | the switch keys, `is_on()`, `is_binding(world, lane)` (reads the dependencies) |
| `bot_program/bettor/constants.py` | A11 |
| `bot_program/bettor/math.py` (pure, no Django import) | `guard(rs)` (one-sided), `posterior(values, weights, own_mask, *, prior_mu, prior_n, var_drag)`, `cautious_edge(post, n_own)`, `kelly_fraction(mu_c, post)`, `explore_weight(w_own)`, `fee_floor(...)`, `ramp(f_x0, n_own)`, `declines(post, n_own)`, `conviction(voices)`, `drawdown_factor(dd)` (calls `share_allocator.governor_for`), `rho_eff(...)`, `correlation_sub(open_bets, rho)`, `effective_risk(d_stop, d_noise, d_gap)`, `tail_fit(...)`, `venue_min_roundup(...)`, `worth(...)`, `paired_bound(d, days, look)` |
| `bot_program/bettor/costs.py` | `fees_for(trade)` (venue payload, else the schedule and the financing model), `net_r(trade)`, `fees_at(qty, ctx)`; the nightly `TradeCost` backfill |
| `bot_program/bettor/evidence.py` | `graded_rs(rule, inst_class, side, world, now)` (netted, guarded, unpriced counted), `hand_rs(user, inst_class, side, world)`, `proving_prior(rule, inst_class, side)` (holdout recomputed net), `sim_drag(inst_class)`, `world_drag(rule, inst_class, src, dst)`, `other_side_posterior(...)`, `score_tercile(...)` (out of sample), `regime_edge(...)`, `edge_for(key, *, score, regime, now) -> Edge`; for Part B, `continuation(...)` and `outcome_rho(...)` |
| `bot_program/bettor/correlation.py` | one source per series, venue first; rank correlation; suspect windows unmeasured; class defaults |
| `bot_program/bettor/rails.py` | `settings(user)`, `judge(ctx, qty, *, book, banner=None) -> RailVerdict` (fails closed while binding), `circuit(user, world)`, `step_circuit(user, world, now)` (called from the sync task after each equity reading), `rearm(user, world, by)` |
| `bot_program/bettor/shadow_book.py` | `Book` (real or shadow), `shadow_book(user, world)` |
| `bot_program/bettor/brain.py` | `BetContext`, `BetVerdict`, `context_for_candidate`, `context_for_ticket`, `context_for_leg`, `size(ctx, *, book)`, `size_tick(ranked, user, world)`, `last_look(ctx, verdict, fresh_price)` |
| `bot_program/bettor/ledger.py` | `record(ctx, verdict, *, today_qty, today_outcome, today_refusal, ...)` (fenced, never raises), `attach_trade(bet_id, trade, sent_qty, last_look)` |
| `bot_program/bettor/grading.py` | `grade_bets(now)`, `arm_pnl(trade, qty)`, `simulated(bet)` (the proving simulator), `summary(user, world, days)`, `readiness(user, world)`, `temperaments(bet)`, `voice_validity(voice)` |
| `bot_program/bettor_models.py` | A8 |
| `bot_program/asset_engine/base.py` | `propose_entry`: the shadow hook before `_judge_final_size` (`:4709`); binding branch: the Bettor's qty replaces the chain from `_size_for_entry` to the taper (`:4623-4673`), and `_judge_final_size` becomes `bettor.rails.judge`. `_size_for_entry` (`:8095`): binding skips `apply_stop_floor`. `execute_entry(cand, size_mult, bettor_qty=None)`: binding applies `bettor_qty`; the debate cut and admin "reduced" stay after it; the last look's re-fit and re-judge immediately before `market_order` (`:6214`). `_skip(..., size_refusal=)` |
| `bot_program/asset_engine/candidates.py` | `bettor: dict = field(default_factory=dict)` |
| `bot_program/asset_engine/runner.py` (`:600-719`), `bot_program/capital_desk.py`, `bot_program/tasks.py` | binding: `choose` calls `brain.size_tick` in rank order, inside the fleet pass under `TICK_LOCK_KEY` |
| `bot_program/manual_trade.py` | `_preview`: the `bettor` block with `terms` and the rails' bounds; size refusals return the block and record; `validate_qty_override`: binding calls `rails.judge`; `_execute`: re-judges at the fresh price and records; `_risk_appetite`: the binding words |
| `templates/base.html` and the ticket's script | the block inside the Size fieldset, the two restore buttons, `judgeSize` mirroring the rails while binding, the debounced re-ask on a stop edit, the meter and POOL line on eToro's free cash |
| `bot_program/notifications.py` (`fill_open_message`, `:1194`), `base._fill_words` (`:8384`) | one line keyed on `binding`: "Sized by the Bettor: 0.83% of the account at stake (a quarter Kelly on +0.21R, 120 closes; held to half the ceiling by a 3% tail)"; explore: "exploring: thin record (4 closes)"; venue_min_up: "raised to eToro's minimum (the Bettor alone would bet 0.14%)". "At stake" and "at the stop" are both printed when they differ. In shadow: "Bettor (shadow): would have put 0.83% at stake (sent: 0.25%)" |
| `bot_program/telegram_eye.py` (`SKIP_WORDS`, `:229-270`) | words for `bettor_declined`, `costs_exceed`, `riding`, `tail_fit`, `rail_*` (`rail_circuit` in the A4 words), `rail_unreadable` |
| `bot_program/tasks.py`, `config/celery.py` | `grade_bets` at 03:55 UTC; the `TradeCost` backfill; `step_circuit` after the eToro sync; the circuit's Telegram messages |
| `dashboard/views_bettor.py`, `templates/dashboard/bettor.html`, `dashboard/urls.py` | `/bettor/` and `/api/bettor/` |
| `dashboard/views.py`, `templates/dashboard/_rails_card.html`, `templates/dashboard/setup.html`, `bot_program/personas.py` | `setup_rails` (POST, PIN); the per-world words on the replaced fields |
| `bot_program/management/commands/bettor.py` | `bettor show [--world]`, `bettor explain <trade_id or symbol rule side>`, `bettor grade [--save]` (dry by default), `bettor rails`, `bettor costs [--save]` (dry by default) |
| `bot_program/morgul.py` | G11: a bet, banner or book past its ceiling (critical) |
| `core/platform_control.py`, `core/switch_pin.py` | A11: `PIN_SWITCHES`, `BULK_ENABLE_EXEMPT`, the dependencies and the cascade |
| `portfolio/models.py` | A8 |

## A13. Tests to write first

| File | Pins |
|---|---|
| `tests/test_bettor_math.py` | The posterior equals the prior at no evidence and tends to the weighted mean as the mass grows. Weights halve at 90 days. **Precision is the weight mass:** halving every weight halves the certainty. A +40R win is excluded, a +9R win counts +5, **a −28R loss counts −20 and lowers `mu_hat` and raises `m2`, a −8R loss counts −8**. The drag's variance widens `sigma_mu` for cross-world evidence. z is 1.0 under 50 own closes. The cautious edge sits below the mean. Kelly is 0 at `mu_c ≤ 0`. `omega` reads own-world mass only. The ramp. The fee floor and `COSTS_EXCEED`. Decline on a confident loser. K = 1 with no graded voice. `drawdown_factor` equals `governor_for` (pinned). rho: same symbol 1.0, theme 0.8, same class 0.6, cross class 0.3 when unmeasured; floors by posture; negative counted as 0. The heat series is bounded by `ceiling / rho_floor`. `d_eff` takes the max and has no cost term. The tail fit. The round-up only at `mu_c > 0` and within 2 × `f × B`. Worth with `c` and fixed fees. Never NaN, never negative |
| `tests/test_bettor_evidence.py` | Per side and per world (demo is never live). **Each cell of the world table** (demo→live 0.7, paper→live 0.5, live→live 1.0). **200 paper closes at weight 0.5 leave real-money `omega` at 0 and the live stake at `f_x`.** The instrument's class, not the filed class. Closes netted of fees (crypto, stocks, financing); paper netted at eToro's schedule. **An unpriced close counts as a loss and names itself; over 5% unpriced makes the key unmeasured.** The proving prior per tier, net of eToro's fees; LIVE_PROVEN read as UNPROVEN; the measured simulated drag. **The other side's record leaves this key's closes out.** Terciles only after an out-of-sample monotone effect. The world drag on `_world_filter`, "unmeasured" under 10 a side. The hand lane is read for tickets only. The query count is bounded and cached per tick |
| `tests/test_bettor_correlation.py` | One source per series (a mixed eToro/Yahoo window is never read as one series). Rank correlation is unmoved by one spiked close. A window with a suspect bar is unmeasured and takes its class default |
| `tests/test_bettor_rails.py` | The 0.03% forex stop at 66 × is refused (with a fresh ATR) or shrunk by `d_eff` (with a stale one). A spike-driven size cannot pass the ceiling. The tail half uses the tail move, not `JUMP_PCT`. **The book ceiling counts break-even legs and fits down; 20 × `B` of forex is refused on the book's tail.** Cash fits down, then refuses under the venue minimum. Daily stop SHUT gives 0; ELITE gives × 0.5 and at most 2. **The circuit's mark is anchored, never rolling: a −2% a week bleed trips it (slow bleed); a 30% loss held for 90 days never re-arms by itself; a spiked equity reading cannot lift the mark; the PIN re-arm restarts the mark; the state survives OFF and ON.** Demo and paper never count in real rails. The ceiling counts a banner. **While binding, an exception or an unreadable input refuses with `rail_unreadable`; a price that ran at the last look re-fits and re-judges** |
| `tests/test_bettor_shadow.py` | `bettor` OFF: no rows and no extra queries. ON: one row per candidate, per sent ticket and per refused preview (deduplicated). **The order sent is byte-identical to OFF** (qty, stop, target, leverage, venue, metadata apart from `bettor`). Every size refusal records a row; no gate refusal does. An exception inside the Bettor costs nothing. **The shadow book: its open bets, cash, daily stop and circuit are its own; an unfundable bet is infeasible** |
| `tests/test_bettor_grading.py` | **Each arm is `gross × qty − fees(qty)` with its own fees.** Declined is 0. **Today-refused goes through the proving simulator (a gap fills at the open; care's locks apply; eToro's fees are charged), never `walk_bracket`.** The three tables are never mixed. Log growth on each arm's own equity. Curve drawdown. Worlds and currencies are never summed. **The paired bound with day blocks and alpha spending; a no-skill Bettor that only bets bigger is not BETTER.** Temperament arms |
| `tests/test_bettor_binding.py` | With `bettor_sizes_paper` ON (and `drawdown_circuit` ON), paper's qty is the Bettor's. **Without `drawdown_circuit` ON, nothing binds.** The caps of A5 marked replaced are not consulted on paper, and the rails are. Real money is unchanged until `bettor_sizes_live`. The debate cut and admin "reduced" still apply after the Bettor. The desk's `size_mult` may exceed 1 only in binding. `size_tick` runs under `TICK_LOCK_KEY` |
| `tests/test_bettor_ticket.py` | The block inside the Size fieldset and its words: the headline keyed on `binding`; "at stake" and "at your stop" both when they differ; the `d_eff` line. No suggestion on a suspect quote. Shadow keeps today's default and caps; **a size refusal still shows the block and records a row**. **Binding (`bettor_ticket_<world>`): `judgeSize` mirrors the rails; the Bettor's size is always pressable unless a rail refuses it; the old caps are warnings; the qty shown after a stop edit equals the qty `_execute` sends.** The two restore buttons per mode. The override reason is required above 2 × or when declined, never for "no suggestion". Overrides are recorded and graded |
| `tests/test_rails_card.py` | Loosening needs the PIN and counts on the session counter; tightening does not. Bounds. Boldness. Audit rows without the PIN. The /setup/ daily-loss and open-risk fields are read-only. **Each replaced /setup/ field shows its state per world; the appetite warning's binding words** |
| `tests/test_bettor_switches.py` | Registry rows. `PIN_SWITCHES`. **Every key in `BULK_ENABLE_EXEMPT`, `bettor` included; "all on" after a pause never brings binding back.** The `_live` suffix is in `LIVE_MONEY_SWITCHES` (`tests/test_ops_cockpit.py`). Each dependent reads OFF without what it needs. **A gating key going OFF writes its dependents OFF with `SWITCH_DISARMED`** |

---

# PART B: THE HORDE'S REINFORCEMENTS

## B1. The invariant: one banner per asset

- A **banner** is one (user, money world, symbol, side). Each world stands alone.
- **A second (or further) position under a banner exists only as a named Horde action.** Each action is decided by one component, **the Marshal**, with a written reason. It is recorded as a `HordeAction` row and stamped on the leg's trade (`metadata["horde"]`).
- Every path that can open a row on a held banner checks for that stamp: a bot, the ticket, Telegram's "Prepare ticket", the NL trader, a re-entry. A row without the stamp is refused with "`EURUSD` long is held under its banner; the Horde decides further legs (Reinforce...)".
- **The banner holds legs, and the legs belong to ideas (Orcs).**
  - A REINFORCE leg is an add of the **same** idea: the same thesis and the same invalidation.
  - A SECOND FRONT is a **new** idea, an Orc of its own with its own thesis and stop, under the same banner.
- **The Bettor sizes the banner as one budget** (B4). The sanity ceiling, the book ceiling and the daily stop count the banner.
- **No Orc, no leg.**
  - A banner whose first row has no Orc (`orcs` OFF) never gains a leg.
  - While `orcs` is OFF there is no Horde action at all.
- **Rows opened at the broker outside the platform** stay in the "broker rows no seat claims" band (`horde.py:1686-1697`): shown, never adopted (the operator's decision of 2026-10-31). The Horde cannot decide what it did not open.

## B2. The actions

| Action | What | When |
|---|---|---|
| **REINFORCE** (spec id A-CONFIRM) | a new leg of the same idea, at the confirmation, its stop at the idea's invalidation, never wider than the root's current stop | the idea has **proven itself**: the newest leg reached +1R on a FINAL bar close of its decision frame (1h or 4h); every open leg's stop (the worse of sent and held) is at its entry or better; every open leg is in profit at the mark; a confirmation fact newer than the last leg exists (a structure break on a final bar from the Orc's menu, a reclaimed sweep, or a CALL TO ARMS). A further add needs the previous add to have proven itself the same way. There is no fixed count: the proof chain and the budget, which now counts every leg from its mark to its stop, limit the pyramid |
| **SECOND FRONT** | a new Orc under the same banner (`Orc.front_of`), with its own thesis, plan and stop | a CALL TO ARMS from a **different rule**, or the same rule on another timeframe or persona, on the held (world, symbol, side). The rule's proof is not FAILED for (class, side). Its own record gives a positive standalone stake. The outcome correlation of the two rules on this asset is measured below 0.9 (unmeasured counts as 0.8). The banner's combined mark P&L is ≥ 0 |
| **REGROUP: close** | closes the **weakest leg** by its eToro position id | the leg's thesis broke (the thesis check reads broken, X-THESIS, or the structure stop broke on a final bar); or the banner's current risk exceeds **1.25 ×** the Bettor's re-evaluated banner budget (after correlation, drawdown or edge changed). Weakest means the lowest `mu_c` per unit of current risk; on a tie, the newest leg. Adds close before their root. A root is closed by REGROUP only when its own thesis broke |
| **REGROUP: unify** | two legs of **one idea** whose stops sit within 0.25R get one stop (the tighter, tighten only), one trail and one crowd level | after a REINFORCE, or whenever the stops drift |
| **CALL TO ARMS** (routing, not an order) | a second bot firing on a held banner never opens. Its candidate goes to the Marshal as a journal fact, and the source rule is credited for grading. The Marshal either uses it as a REINFORCE confirmation (same thesis) or weighs it as a SECOND FRONT (independent thesis, own stake) | from the `already_open` and `duplicate_state` sites (B8) |

**What "merge" means.** eToro closes a position whole and never nets (`etoro_client.py:2738-2752`; `venue_close.py:10-14`), so two eToro positions can never become one. A merge is therefore the unify above: one plan over two position ids.

**Later actions on the same table.** These are out of this build and each gets its own shadow:
- RETAKE, the one re-entry after a stop-hunt (R-RECLAIM, `REENTRY_WINDOW_MARKET_H` 24);
- SPLIT, two legs at entry (a banker and a runner), which is how "half at +1R" becomes possible with real money (`position_care.py:64-76`).

**Never Horde actions** (refused, with a test each):
- a bot averaging down;
- a hedge: a long and a short leg on one asset in one world. **This tightens:** today two configs may hold opposite sides, because `duplicate_state` checks the same side only (`risk_gate.py:1633-1641`);
- a widened stop;
- a leg without a venue position id;
- a leg on a forming bar, a suspect or frozen mark, under integrity F5, within `ADD_PRE_SHUT_H` of a shut (6 h; 12 h for Corsairs), in a print window, or with an unmeasured gap;
- a leg by Mercenaries;
- a leg past the daily stop (the elite exception does not extend to legs) or with the circuit tripped;
- a leg combined across worlds, or whose world differs from its banner's.

## B3. Who decides: the Marshal

**The Marshal.**
- **The file:** `bot_program/orcs/marshal.py`. It is deterministic: no model and no order of its own.
- **Its name:** the Marshal decides for every banner, whatever its Orc's rank. It is not a rank: "Standard-bearer" stays the L3 rank every Orc slot prints beside its badge (`orcs/ranks.py:11-18`), which the first draft had borrowed.
- **When it runs:** in the first fleet pass after each 1h and 4h final-bar close, and on each CALL TO ARMS, for every banner with an Orc, while `horde_reinforce` is ON. The binding step runs inside the fleet pass, under `TICK_LOCK_KEY` (`tasks.py:44-64`), after that tick's bot candidates, so a leg and a bot entry never "each pass the duplicate and open-risk gates and send the same order twice". In shadow it may run on its own beat.
- **How a binding leg is sent:** through `propose_entry`'s gate chain with a stamped candidate. The stamp passes `already_open` and `duplicate_state`; every other gate runs, including `can_open_new` (`base.py:3964-4144`: the per-config breakers of 4 losses or 10%, `max_concurrent`, the per-config 24 h loss fallback that rail 2 relies on), the stage computation that decides paper or real (`base.py:4558-4665`), the cost filter and the FAILED proof gate. A leg whose world differs from its banner's is refused. Then `execute_entry` with the Bettor's quantity and the last look (A4). The first draft built the candidate by hand and skipped all of these.
- **What it writes:** one `HordeAction` per decision, with a **written reason** that cites fact ids. Example:

  > REINFORCE Orc #12 EURUSD long: leg 1 at +1.2R (MFE +1.4R) on the 4h close of 14:00 UTC; stop at break-even (eToro holds 1.08190); confirmation F41 (4h close above 1.0850); Bettor 0.29% (a quarter Kelly on a +0.06R cautious continuation edge, less the 0.36% leg 1 still carries to its stop); banner risk after 0.65% of the account.

**The roles around it:**

| Role | Who | Power |
|---|---|---|
| Decides | the Marshal | the only code path that opens or closes a leg under a held banner |
| Sizes | the Bettor (`context_for_leg`) | the leg's stake against the banner as one budget (B4); it may say zero |
| Gates | the bots' own gate chain | breakers, max concurrent, stage and venue, cost, FAILED proof, as for any entry |
| Survive | the six rails, counted on the banner and the book | refuse or fit down only |
| Cuts, live | the trade debate's Executioner, after its 30 graded trades | ≤ 1, or a veto |
| Opinion | the council (Gambler, Emperor, Hand) | shadow; graded; feeds K only after the operator's yes (A2.6) |
| His own idea | the operator | a ticket idea's Orc has commission `advise`: the Marshal *proposes* on the Horde and on Telegram, and the operator presses "Reinforce..." on the ticket with his PIN |
| Arms a seat | the operator | real-money legs only on a seat he armed with his PIN (B12) |
| Shows | the Horde band | decides nothing |

**Refusal codes** (`orcs/constants.HORDE_REFUSALS`):
- `not_proven_yet`, `previous_add_unproven`, `stop_not_safe`, `under_water`;
- `no_new_fact`, `same_idea`, `not_independent`;
- `forming_bar`, `suspect_mark`, `integrity_f5`, `pre_shut`, `print_window`, `gap_unmeasured`;
- `mercenaries`, `corsair_shut`;
- `breaker`, `max_concurrent`, `stage_venue`, `cost_filter`, `proof_failed`, `world_mismatch`;
- `bettor_zero`, `no_suggestion`, `rail_cash`, `rail_ceiling`, `rail_book`, `rail_daily`, `rail_circuit`, `rail_venue_min`, `rail_unreadable`;
- `no_position_id`, `hedge`, `switch_off`, `seat_not_armed`.

Every refusal is recorded with its numbers, and the shadow ledger keeps them.

**Every code has words** (`orcs/words.HORDE_REFUSAL_WORDS`, in `dashboard/plain_words.py`'s style: "a stored reason is said in fixed words keyed on its cause", `plain_words.py:9-11`; a test pins that none is missing). For example:
- `not_proven_yet`: "leg 1 at +0.6R; an add needs +1R on a final 4h close";
- `stop_not_safe`: "leg 1's stop is still under its entry (eToro holds 1.07918)";
- `bettor_zero`: "the continuation edge pays nothing once leg 1's 0.36% to its stop is counted";
- `seat_not_armed`: "real-money adds on this seat wait for your PIN (ready: 41 of 60 graded on demo)";
- `routed_to_banner` (a skip code of the bots, B8): "EURUSD long is held; this signal went to the Marshal as a call to arms".

`telegram_eye.SKIP_WORDS` (`:229-270`) gains `routed_to_banner`, `bettor_declined` and the rail codes, so `/why` never falls back to `code.replace('_', ' ')` (`:436-438`).

## B4. Sizing the banner as one budget

**Notation.**
- `f_mts` is a leg's (or any open bet's) risk **from the mark to its stop**, as a fraction of `B`, at the worse of its sent and held stops, plus its gap shock when a shut falls inside the hold (A2.8). A leg at break-even in profit still counts what it can give back.
- `others` means every other open bet in the world, through A2.8's correlation term.

**REINFORCE** (the same thesis, so rho = 1 with its own idea):

```
mu_cont  = posterior of the add's own R over the closes where the add's trigger fired
f_cont   = 0.25 * max(mu_cont_c, 0) / m2_cont * K * D * Boldness
f_add    = max(0, f_cont - Σ_{legs of the idea} f_mts - Σ_others rho_eff * f_mts)
```

- **The population is the trigger itself:** the closes whose decision frame produced a final bar close at or above +1R. The first final close at or above +1R is found by walking each trade's decision-frame final bars (`orcs/bars.py` for live and demo, the proving bars for proving trades), memoised per trade. The first draft used closes whose intrabar MFE reached +1R (`simulate.py:269`), which REINFORCE never acts on.
- **The unit is the add's own risk:** the add enters at the trigger close `r_entry` (in the root's R) with its stop at the root's break-even, so its R is `(r_final − r_entry) / r_entry`.
- **The evidence and its weights:**
  - legs with real fills, by the world table of A2.3 (live 1.0; demo 0.7 for live);
  - proving trades at weight 0.5, capped at a pseudo-count of 20, shifted by the simulated drag;
  - the add arm's ghost outcomes, priced by `orcs/pricing.py` and never filled, at weight 0.5 and shifted by the simulated drag: a simulation, never weighted like a real close.
- **The cautious edge** is as in A2.3: z = 1 until 50 legs with real fills in the target world.
- **No exploration on real money:** an add with no measured continuation gets "no suggestion" (`no_suggestion`), never exploration. Paper may explore adds at `f_x`.
- **The ramp for legs:** `f_cont ≤ f_x × (1 + n_real_legs / 10)`, where `n_real_legs` counts the seat's legs with real fills on demo and on real money (the seat was armed on that evidence, B12).
- **Example 5 (A2.12):** the root carries 0.36% from its mark to its stop at break-even; a continuation stake of 0.65% leaves an add of 0.29%. Pinned: a root at +1R with its stop at entry gives `f_add` = the continuation stake minus the root's mark-to-stop risk.

**SECOND FRONT** (a different thesis; rho is the measured outcome correlation of the two rules on this asset and side):

```
rho_12  = corr(R_rule1, R_rule2) over overlapping pairs on this symbol and side
          (n >= 15; else 0.8)
f_front = max(0, f_standalone(rule2 key) * K * D * Boldness
                  - rho_12 * Σ_{banner legs} f_mts
                  - Σ_others rho_eff * f_mts)
```

The unmeasured value moves from 0.7 to 0.8, to match the cautious class defaults of A2.8: two rules on the same symbol and side are at least as alike as two symbols of one sector.

**The banner budget** used by REGROUP:

```
F_banner_now = max over the banner's ideas of their standalone stakes now
             + the independence credits (1 - rho_12) of the other ideas
```

- REGROUP closes the weakest leg when `Σ f_mts > 1.25 * F_banner_now`. The heat line and REGROUP read the same `f_mts`.

**The rails on the banner.**
- The sanity ceiling: `max(Σ legs money at their stops from the marks, Σ legs notional * tail_c)` ≤ X% of `B` **after the action**.
- The book ceiling counts every leg, break-even legs included.
- Splitting one bet into legs can never walk past a ceiling the bet itself would hit. A test pins it.

**One record.** The Bettor records a `BetSizing` row with `lane = horde` and the `horde_action` link.

## B5. The Horde band: one banner per asset

**One seat per leg stays.** Each leg is one eToro position, with its own stop, mark and P&L, and the truth contract is per row (`horde.py:20-25`). What changes:

**The banner strip.** In `horde._groups` (`:1610-1660`), seats of one (world, symbol, side) sit under a strip. A banner with one seat gets the strip too once `horde_reinforce` is ON, because the first REINFORCE is always decided on a one-seat banner. Example:

```
EURUSD LONG · REAL MONEY · 2 legs · Orc #12 (root + reinforce)
Risk if every stop is hit 11.78 USD from the marks (0.65% of the account;
the Bettor allows 0.65%)
P&L +6.48 USD (leg 1 at +1.2R; leg 2 just filled) · average entry 1.08334
Marshal: reinforced at 14:05 UTC on F41 (4h close above 1.0850).
```

A second-front banner names both ideas: "XAUUSD LONG · DEMO · 2 ideas: Orc #40 (golden_cross 4h) and Orc #44 (bollinger_squeeze_breakout 1d, second front)". The head adds "· N banners" beside the seat count.

**Each leg card names its leg:**
- "leg 1 of 2 · root";
- "leg 2 of 2 · REINFORCE by the Marshal on F41";
- "leg 2 of 2 · SECOND FRONT · Orc #44";
- "leg 2 of 2 · ADD by you" (or "ADD by you · under water", B8);
- the mission names who decided: the Marshal, the operator, or a CALL TO ARMS from rule X.

**Every seat with an Orc has one Horde line:** the Marshal's latest decision or refusal for it, in the words of B3, with its time. Example: "Marshal, 14:00 UTC: no add yet. Leg 1 at +0.6R; an add needs +1R on a final 4h close." In shadow it reads "Shadow: the Marshal would REINFORCE 0.29% at 1.08512 (F41); today: no add. Record: 14 graded, add delta +0.08R (lower bound −0.03R)." This answers the question the operator will ask most: why the Horde did not reinforce his winner.

**Seat readiness** is shown on the band head for the world tab and on the /orcs/ seat page: "Adds on golden_cross · forex · DEMO: 41 of 60 graded with real fills, delta +0.07R net of fees, corrected lower bound −0.02R. Not ready." A ready seat shows "Ready: arm for real money (PIN)".

**The Orc slot's authority line.** Once a leg binds on a banner, the slot never prints "watches and writes: shadow only" (`ranks.py`, HOLDS[0]) for its Orc; it shows the seat's add state instead: "adds: armed on this seat (60 graded on demo, +0.08R)".

**Rows that are not legs.** Two rows on one asset with **no** Horde stamp (today's hand-opened sibling) still group under the strip, marked "2 positions, not linked by the Horde", with their combined risk. This is display only and helps today.

**"Same bet"** (`_same_bets`, `:1520-1543`) extends to the same symbol and side in every class: "Long AAPL through 2 legs of one banner".

**The dossier's peer table** (`_peers`, `:2471-2611`) lists the sibling leg first. It stops keeping only the first seat per symbol (`:2491`) and stops pre-marking its own symbol as seen (`:2508`).

**The Orc slot** (`notes.for_rows`, `notes.py:680-717`) gains:
- `leg: {seq, kind, of}`;
- `idea_risk`, in the idea's R, as `risk_r` already is (`notes.py:312-316`; the O5 seam at `notes.py:689`);
- `banner_risk`, as a percentage of the account. The slot carries no money (`notes.py:24-26`); the money figures stay on the `horde.py` strip, which already prints money.

**The laws on Orc words, amended, not dodged.** Every sentence that names an Orc must be reserved (`orcs/notes.py:22-31, 781-796`, `RESERVED_SENTENCES` / `RESERVED_PATTERNS`; `dashboard/horde.py:269-296`), and the slot law says "no Orc verb is printed: in O1 no Orc has acted" (`tests/test_the_horde.py:963-1005`). Both would reject the strip's and the leg cards' sentences, and a builder meeting those tests might drop "Orc #12" from the strip.
- The new sentences are registered as `RESERVED_PATTERNS`: the strip's head and idea lines, the leg labels, the Horde line and the seat line above.
- The slot law becomes: "an act is printed only for a HordeAction in state sent or filled under `horde_legs_<world>`; shadow proposals say Shadow".
- `test_every_orc_word_in_a_payload_is_reserved` and `test_no_orc_verb_anywhere` are extended in commits 4 and 16, never loosened.

**The commands:**
- "Close this leg...";
- "Close the banner (2 legs)...": the dialog names what stays open;
- "Regroup...": the operator's own close-weakest or unify, with the PIN as for any close.

**Elsewhere.** /positions/, Telegram /positions and /why print the leg after the symbol: "EURUSD long · leg 2/2 REINFORCE (Orc #12)".

## B6. How the care and the Orcs treat each leg

**Stops.**
- Each leg keeps its own eToro stop (the disaster stop), mirrored tighten-only as today (`position_care.py`).
- An idea owns one plan and one invalidation.
- A REINFORCE leg's stop sits at the idea's invalidation or tighter, never wider than the root's current stop. No stop is ever loosened to make room.

**R and the clocks.**
- Break-even and the trail run per leg, **in the idea's R** (the root's `r_money`), so the legs never run two unrelated clocks.
- A second front is its own idea, with its own R and its own care.
- The **no-progress clock and the time stop are the root's.** An add never resets them; a second front has its own.

**Judged on the banner:**
- the weekend and event cuts, on the combined leverage and loss;
- the posture floors, as for any leg.

**Anti-hunt.**
- The legs of one idea put their stops beyond the **same** crowd level (`smart_money.stop_beyond_the_crowd`, `smart_money.py:221-246`). They are never staggered inside a hunt zone.
- The crowd read treats the banner's own stops as a known cluster.

**Mark sanity.** No leg action is taken on a suspect or frozen mark. Every trigger is a FINAL bar close, so a one-tick spike, like the ones the operator just saw, can never open a leg.

**The close.**
- Each leg closes by its own position id (`venue_close.position_id_for`, `:60-75`).
- An idea dies with its last leg; a banner dissolves with its last idea.
- The kill switch ends everything.

**The Orcs.**
- **The journal.** Each action writes "intent", "action" or "refusal" entries (`JOURNAL_KINDS`), and a CALL TO ARMS is a "fact".
- **Birth.**
  - `birth.ensure()` attaches a stamped leg as an `OrcLeg(kind="add")` of its idea (`adds_used + 1`), and a second front as a new Orc with `front_of` set (`birth.py:286-310`).
  - The census never adopts a stamped leg as a new idea (`census.py:39-45`).
- **The ghost** (`orcs/ghost.py`) gains two arms:
  - `add`: the leg that would have been, priced by `orcs/pricing.py` at the proposal's tick;
  - `front`.
  - Both are graded against **the root alone** (the care ghost, which is what the platform does today): `delta_add` and `delta_front` on `OrcGrade`, net of the leg's eToro fees. They feed the continuation estimate at simulation weight (B4), and never seat readiness (B12).
- **Morgul G8** (`morgul.py:1085-1121`):
  - the legs of one idea are already one position;
  - two ideas under one banner joined by a `second_front` action are not a duplicate either;
  - an unstamped second idea still is;
  - a stamped leg whose idea is dead, or belongs to another banner, becomes a finding.

## B7. What the operator sees on Telegram

Nothing acts from Telegram. The buttons open the platform, as the "Prepare ticket" and "Close position" links already do (commit `63ad93e`). Every link carries a row's id and nothing else (`alerts/links.py`).

**A real-money leg fills** (through `fill_open_message`, `notifications.py:1194`, which gains a Horde header):

```
🟢 Reinforced EURUSD long: leg 2 of 2 (Orc #12)
Real money · eToro
1,636 units at 1.08512, about 1,775 USD.
Why: 4h close above 1.0850 (F41); leg 1 at +1.2R, its stop at break-even.
Banner after: 2 legs · risk if both stops are hit, from the marks, 0.65% of
the account · average entry 1.08334
Sized by the Bettor: a quarter Kelly on a +0.06R cautious continuation edge,
less the 0.36% leg 1 still carries to its stop
▸ Trade: #212 · Banner: EURUSD long · Marshal
[Open position] [Close this leg]
```

**A second front:** "🟢 Second front on XAUUSD long: leg 2 of 2 (Orc #44, bollinger_squeeze_breakout 1d) · Why: an independent breakout (F12), outcome correlation with Orc #40 0.31 over 22 pairs ...".

**A regroup** is a header on the close's own message, never a second message. `notify_bot_fill_close` already sends `fill_close_message` for every close (`notifications.py:1747-1764`); for a row carrying `metadata["horde"]` that message opens with:

```
🔻 Regrouped EURUSD long: closed leg 2 (second front, Orc #31).
Why: its thesis broke (F57: 4h close back under 1.0830).
Leg 1 stays open, stop 1.08320.
```

and its button reads [Open banner], which opens the root's `/forensics/<id>/` page (`dashboard/urls.py:355`). The Horde is a band with a JSON feed (`api/horde/`, `dashboard/urls.py:157`), not a page, so there is no banner page to link to.

**The operator's own idea** (commission `advise`):

```
The Horde proposes: reinforce your EURUSD long. Leg 1 at +1.1R, stop at
break-even, 4h close above 1.0850 (F41).
The Bettor suggests 1,636 units (0.29% of the account).
Holds until the 18:00 UTC 4h close.
[Prepare ticket]
```

- [Prepare ticket] opens a new route, `/horde/actions/<id>/ticket/` (the HordeAction id only, under the links law). The only prepare-ticket route today is keyed on a Signal id (`dashboard/urls.py:201`, `signals/<int:signal_id>/ticket/`), and a Horde proposal is not a signal.
- The ticket opens as "Reinforce Orc #12" with the proposal's Bettor size and facts. When the proposal has lapsed (one bar of its frame, B11), it states "expired at 18:00 UTC; this is a fresh ticket" and re-asks the Bettor.

**The drawdown circuit** trips and re-arms with the words of A4, in percent only.

**Shadow and refusals.**
- In shadow: no message per proposal. One digest line a day: "Horde, shadow: 3 reinforcements, 1 second front and 0 regroups proposed; graded so far, add delta +0.08R (14)."
- A REGROUP close that fails at the venue goes to the alarm bot, as any stuck close does.
- No money appears in any alarm text (the council's law).

## B8. Rules that change

| Rule | Today | Proposed |
|---|---|---|
| `already_open` (`base.py:4228-4239`) | any open row of the config on the symbol refuses | still refuses a new idea. When the row has an Orc and the candidate is on the same side, the candidate becomes a CALL TO ARMS fact for the Marshal (skip code `routed_to_banner`, with its words). The opposite side is still refused |
| `duplicate_state` (`risk_gate.py:1606-1664`) | refuses another config holding the same symbol and side; exempts the asker's config | keyed on the **banner**: a row stamped with the banner's HordeAction passes; anything else is refused, the asker's own config included. Its sentence offers "the Horde can reinforce it" instead of "close that leg first". **Opposite sides on one banner world are refused** (new, commit 24) |
| Max concurrent (`base.py:4073-4078`) | counts rows | counts banners |
| Cooldown (`base.py:4271-4280`) | 60 min per config and symbol | unchanged (RETAKE comes later) |
| Manual exemption (`manual_trade.py:1586-1601`) | adds to his own ticket freely ("adding to your own expression is sizing", `:1592-1594`); refused beside a bot | while `horde_ticket_legs_<world>` is ON: a second ticket on his own banner opens as a leg labelled **"ADD by you"**, graded apart from the Marshal's REINFORCE, and says so: the combined risk after, the average entry, and the Bettor's leg size, or "no suggestion" when there is no continuation record (no reason demanded for that). On a leg under water the label is "ADD by you · under water", with "averaging down a loser", a typed reason, and the combined risk shown before the PIN. Beside a bot's banner: "Reinforce Orc #12" (a leg of that banner) instead of a flat refusal. The ticket never opens a second idea on a held banner (map_horde §7.10 q4: we recommend against it) |
| Which Horde refusals bind his ticket leg | — | **the six rails and the hedge refusal only.** Pre-shut, print window, unmeasured gap and the other timing refusals are warnings, as the ticket's timing is today ("a warning, not a block", `base.html:2345-2366`). No position id stays a refusal, because the plumbing cannot close a leg without one |
| `concentration_state` (`risk_gate.py:1480-1550`) | 2 clips, a warning | the banner budget (B4); the ceiling counts the banner |
| `theme_state` | 3 legs | A2.8's rho 0.8 (Part A) |
| Birth, census, G8 | always a root | B6 |

## B9. Plumbing before any leg

This step adds no power. It fixes bugs that bite as soon as two rows share a symbol, as the operator's hand-opened siblings already do.

| Piece | Fix |
|---|---|
| Close-retry drain (`pending_closes.py:696-717, 867`) | judges a CLOSE_PENDING row by its position id when the row carries one and the venue lists ids, instead of answering UNKNOWN because "another live row claims the symbol" |
| "Still holds" (`base.py:2379-2386`) | the same, id-first |
| Reconcile (`reconcile_asset.py:357-368`) | id-first; a row with no id beside a sibling raises a Morgul finding instead of staying OPEN forever |
| Position ids | no leg is opened unless the root row and the venue answer carry a position id (`base.py:2190-2205, 6418-6431, 6790-6810`) |
| Cash freshness | pace fix F1 (re-read after every booking) lands first |
| Legacy NL trader (`nl_trader.py:169, 193`) | refuses close and set_sl when two open Positions share the symbol, and names them |

## B10. Data model and migrations

`bot_program/orcs/models.py` (the app is bot_program):

**`HordeAction`** (new):
- **The banner:** `created_at`, `user` FK, `world` (char 5), `symbol`, `side`, `banner_key` (char 64, index: `"<world>:<symbol>:<side>"`).
- **What was decided:** `action` (char 16: reinforce / second_front / regroup_close / regroup_unify / routed / operator_add), `state` (char 12), `mode` (char 8: shadow / binding), `decided_by` (char 16: marshal / operator).
- **The Orcs and the leg:** `orc` FK (holding), `new_orc` FK null (the front), `leg_trade` FK AssetBotTrade null (the leg opened or closed).
- **The reason:** `source` (JSON: rule, signal id, conviction, config of a CALL TO ARMS), `facts` (JSON list of {id, headline}), `reason` (char 400), `refusal` (char 32), `expires_at` (the proposal's bar close).
- **The money:** `bet` FK BetSizing null, `banner_risk_before`, `banner_risk_after` (Decimal 14,4, from the marks), `bankroll`.
- **The grade:** `delta_r` null (banner with the action minus without, net of fees), `delta_money` null, `graded_at` null.
- Indexes: (banner_key, created_at), (state), (orc).

**`Orc`** gains:
- `front_of` FK self, null, SET_NULL;
- `banner_key` (char 64, index).

**`OrcGrade`** gains `delta_add` and `delta_front`, both Float null, net of fees.

**`OrcSeat`** (`orcs/models.py:21-41`) gains `legs_live_armed_at` (DateTime null) and `legs_live_armed_by` (FK user null): the operator's PIN'd arming of that seat for real-money legs.

**Constants** (`orcs/constants.py`): `HORDE_ACTIONS`, `HORDE_STATES`, `HORDE_REFUSALS`, `REINFORCE_AT_R = 1.0`, `REGROUP_OVER = 1.25`, `UNIFY_WITHIN_R = 0.25`, `FRONT_RHO_UNMEASURED = 0.8`, `FRONT_SAME_IDEA_RHO = 0.9`, `FRONT_MIN_PAIRS = 15`, `GHOST_WEIGHT = 0.5`, `SEAT_READY_N = 60`, `SEAT_READY_ALPHA = 0.05`. `LEG_KINDS` is unchanged: a front is the root of its own Orc.

**Trade metadata:** `metadata["horde"] = {"action", "action_id", "banner", "leg": n, "by"}`, beside the existing `metadata["orc"]` stamp.

**Migration:** `bot_program/migrations/00NN+1_horde_actions.py`:
- the HordeAction table;
- the Orc, OrcGrade and OrcSeat fields;
- the `BetSizing.horde_action` FK.

It is schema only and reversible. It must not collide with Orcs O2's own migration (OrcIntent, OrcActionGrade, Captain): rebase onto whichever lands first.

## B11. States

| Thing | States |
|---|---|
| HordeAction | **shadow**: proposed → refused(code) or recorded → graded. **binding**: proposed → refused(code), or sent → filled / failed → graded. A proposal not acted on within one bar of its frame becomes `expired` at `expires_at` |
| Banner | single → reinforced (the root plus adds of one idea) and/or fronted (two ideas or more) → regrouping (a close in flight) → dissolved |
| Seat, for real-money legs | not ready → ready → armed (the operator's PIN) → disarmed (free, any time) |
| Orc (unchanged) | born / active / care_owned / reentry_window / dead |

## B12. Switches, shadow and rollout

| Stage | Switch (OFF on arrival) | PIN | Needs ON | What happens |
|---|---|---|---|---|
| S0 plumbing | none | — | — | B9; the band display of B5 for rows that exist today |
| S1 shadow | `horde_reinforce` (System) | no | `orcs`, `bettor` | the Marshal decides in shadow; CALL TO ARMS facts; the add and front ghost arms; graded against the root alone; the Horde shows it all as shadow, with a line per seat and seat readiness; the daily digest line |
| S2 paper | `horde_legs_paper` | **yes** (`PIN_SWITCHES`) | `horde_reinforce`, `bettor_sizes_paper`, `drawdown_circuit` | legs open on paper; paper may explore adds at `f_x` |
| S3 demo | `horde_legs_demo` | **yes** (`LIVE_MONEY_SWITCHES`) | same, demo | legs open on eToro demo: two real positions, each above its minimum, against eToro's real mechanics. This is where seats earn readiness |
| S4 real money | `horde_legs_live` | **yes** (`LIVE_MONEY_SWITCHES`) | same, live | real-money legs, **only on seats the operator armed** |
| Ticket legs | `horde_ticket_legs_paper`, `_demo`, `_live` | **yes** | `horde_legs_<world>` | his second ticket opens as "ADD by you" (B8) in that world |

All of these join `BULK_ENABLE_EXEMPT`, and each turns OFF with whatever it needs (A11).

**A seat is ready** when its (world, class, rule) seat (`OrcSeat`, `orcs/models.py:21-41`) holds:
- at least 60 graded actions of that kind **with real fills** on eToro demo or real money (ghost and shadow outcomes count toward the continuation estimate, never toward readiness);
- deltas net of eToro's fees;
- a positive lower bound on the mean delta at 95%, Holm-corrected across the seat set and spent over the nightly looks (O'Brien-Fleming). With a delta s.d. near 1R, an 80% bound over 20 actions passes a zero-effect seat 20% of the time on each look, and there are many seats.

**A ready seat is shown, never armed by itself.** The operator arms it for real money with the PIN on the /orcs/ seat page ("Arm this seat for real-money adds"), and disarms it with one tap, no PIN. Readiness stands in for the L3 rank until the rank ladder of O2 and later is built; when it is, the seat's level joins the condition.

**REGROUP binds with the legs switch,** and only on legs the Horde opened. On the operator's hand rows it only advises. A wrong regroup costs an opportunity, never risk.

**Grading.**
- Per action: `delta_r`, net of fees.
- Per seat: the hit rate and mean delta of REINFORCE, SECOND FRONT and "ADD by you", each apart.
- For the Bettor: the leg's size against its alternatives (A10).

## B13. Files and functions

| File | What |
|---|---|
| `bot_program/orcs/banner.py` | `banner_key(world, symbol, side)`, `banners_of(user, world=None)`, `Banner` (legs, ideas, combined risk from the marks to the worse stops, tail loss, average entry, P&L) |
| `bot_program/orcs/marshal.py` | `step(user, now)`, `consider_reinforce(banner, orc, facts)`, `consider_front(banner, call)`, `consider_regroup(banner)`, `route_call_to_arms(cand, banner)`, `decide(...) -> HordeAction`. The binding `execute(action)` builds a stamped `EntryCandidate` and runs it through `propose_entry`'s gate chain, then `execute_entry(cand, bettor_qty=...)`, inside the fleet pass under `TICK_LOCK_KEY`; regroup closes go through `manual_close` and `venue_close` by position id |
| `bot_program/orcs/words.py`, `dashboard/plain_words.py` | `HORDE_REFUSAL_WORDS`, the seat line, the Horde line |
| `bot_program/orcs/models.py`, `constants.py` | B10 |
| `bot_program/orcs/ghost.py`, `grading.py` | the `add` and `front` arms; `delta_add`, `delta_front`, net of fees; seat readiness |
| `bot_program/orcs/birth.py`, `census.py` | attach stamped legs and fronts; never adopt a stamped leg |
| `bot_program/orcs/notes.py` | `leg`, `idea_risk` (R), `banner_risk` (% of the account); the new `RESERVED_PATTERNS`; the authority line on a binding banner |
| `bot_program/orcs/tasks.py`, `bot_program/tasks.py`, `config/celery.py` | the Marshal's shadow step after the 1h and 4h closes; its binding step inside the fleet pass |
| `bot_program/bettor/evidence.py` | `continuation(...)` (the trigger population, the add's own R, ghost at simulation weight), `outcome_rho(...)` |
| `bot_program/bettor/brain.py` | `context_for_leg` |
| `bot_program/asset_engine/base.py` | `already_open` → `routed_to_banner` (`:4228-4239`); `propose_entry` and `execute_entry` accept a stamped candidate; the `_broker_still_holds` id-first fix (`:2379-2386`) |
| `bot_program/pending_closes.py`, `bot_program/reconcile_asset.py`, `bot_program/nl_trader.py` | B9 |
| `portfolio/risk_gate.py` | `duplicate_state` keyed on the banner; opposite sides refused (commit 24) |
| `bot_program/position_care.py` | the idea's R for legs; the root's clock; banner-level weekend and event cuts |
| `bot_program/manual_trade.py` | a second ticket as "ADD by you"; "Reinforce Orc #12"; averaging-down words; which refusals bind |
| `dashboard/horde.py`, `templates/_partials/the_horde.html`, `static/js/sv-horde.js`, `static/css/sv-horde.css` | B5 |
| `dashboard/views_orcs.py` (the /orcs/ seat page), its template | seat readiness; "Arm this seat for real-money adds" (PIN) |
| `alerts/links.py`, `dashboard/views_links.py`, `dashboard/urls.py` | `horde_ticket_path(action_id)`; `/horde/actions/<id>/ticket/` |
| `bot_program/notifications.py`, `bot_program/telegram_eye.py` | B7: the fill header, the regroup header on `fill_close_message`, the proposal, the circuit's words; `SKIP_WORDS` additions |
| `bot_program/morgul.py` | G8 additions; G11 counts banners and the book |
| `core/platform_control.py` | `horde_reinforce`, `horde_legs_<world>`, `horde_ticket_legs_<world>`, their dependencies |

## B14. Tests to write first

| File | Pins |
|---|---|
| `tests/test_horde_sibling_plumbing.py` | Two legs on one symbol and side: the drain books the right one by id; "still holds" answers by id; the reconcile closes the right leg; a row with no id beside a sibling raises a finding; no leg opens without position ids |
| `tests/test_horde_banner_view.py` | The strip and its words, one-seat banners included once `horde_reinforce` is ON; leg labels ("ADD by you" included); unlinked rows marked "not linked"; the peer table lists the sibling (the `:2491` and `:2508` cases); same-symbol "same bet"; the world tabs are never summed; the Horde line per seat; the seat-readiness line; the slot's authority line never "shadow only" on a binding banner; `idea_risk` in R and `banner_risk` in percent, no money in the slot; the `horde_dom_harness.js` cases |
| `tests/test_the_horde.py` (extended) | the new sentences are reserved (`test_every_orc_word_in_a_payload_is_reserved`); an Orc verb only for a sent or filled HordeAction under `horde_legs_<world>`; shadow proposals say Shadow (`test_no_orc_verb_anywhere`) |
| `tests/orcs/test_marshal.py` | Each REINFORCE precondition refuses with its code (`not_proven_yet`, `stop_not_safe`, `under_water`, `no_new_fact`, `forming_bar`, `suspect_mark`, `integrity_f5`, `pre_shut`, `print_window`, `gap_unmeasured`, `mercenaries`, `corsair_shut`, `previous_add_unproven`). **A binding leg meets `can_open_new` (breaker, max concurrent), the stage and venue, the cost filter and the FAILED gate; a leg in another world than its banner is refused.** SECOND FRONT refuses the same rule again (`same_idea`) and a correlated rule (`not_independent`). REGROUP picks the weakest leg, closes adds before the root, and unifies within 0.25R, tighten only. No hedge. The written reason cites the fact ids. **Every refusal code has words. The binding step holds `TICK_LOCK_KEY`** |
| `tests/orcs/test_horde_budget.py` | **A root at +1R with its stop at entry gives `f_add` = the continuation stake minus the root's mark-to-stop risk.** The continuation population is the final-close trigger and its unit the add's own R. Ghost outcomes weigh 0.5 with the simulated drag. No exploration on real money ("no suggestion"). `rho_12` is 0.8 when unmeasured. REGROUP and the heat line read the same mark-to-stop risk. Splitting cannot pass the ceiling. The banner counts in the daily stop, the circuit and the book ceiling |
| `tests/orcs/test_horde_switch_off.py` | With `horde_reinforce` OFF: nothing is read or written. With it ON and no `horde_legs_<world>`: no order path is ever reached (patch the client and assert no call). Without `orcs`: no action. **`horde_legs_live` without an armed seat: no order. Turning `horde_reinforce`, `orcs`, `drawdown_circuit` or `bettor_sizes_<world>` OFF disarms the legs switches** |
| `tests/orcs/test_orc_add_arm.py` | The add and front arms seed at the proposal tick, price through `pricing.py`, and grade against the root alone, net of fees |
| `tests/orcs/test_seat_readiness.py` | 60 actions with real fills; ghost outcomes never count; Holm across seats; alpha spent over looks; a ready seat is shown, never armed without the PIN; disarming is free |
| `tests/test_horde_gates_rekey.py` | `already_open` gives `routed_to_banner` and a journal fact. `duplicate_state` lets a stamped leg pass and refuses an unstamped one, the asker's config included. Opposite sides are refused (commit 24). Max concurrent counts banners |
| `tests/test_horde_manual_leg.py` | A second ticket becomes "ADD by you" with words; under water says so and needs a typed reason; "no suggestion" demands no reason; only the rails and the hedge refusal bind it, timing refusals warn; "Reinforce Orc #12" beside a bot banner; never a second idea |
| `tests/test_horde_telegram.py` | The words of the messages; the regroup is a header on `fill_close_message` (one close, one message); [Prepare ticket] opens `/horde/actions/<id>/ticket/` with the id only; "Holds until ..."; an expired proposal opens a fresh ticket that says so; [Open banner] opens the root's forensics page; the circuit's trip and re-arm words in percent only; links only, no action; the shadow digest line; no money in the alarm path |

---

# C. The commits, in order (smallest and safest first)

Each commit lands with its tests written first. "Neutral" means no order, size, stop or limit changes. Every switch arrives OFF.

| # | Commit | Main files | Tests first | Money direction | Switch |
|---|---|---|---|---|---|
| 1 | Bettor arithmetic, pure: the one-sided guard, the mass posterior with the drag's variance, z, the ramp, the fee floor, the tail fit, the round-up, worth with `c`, the paired bound | `bettor/math.py`, `bettor/constants.py` | `test_bettor_math.py` | neutral (nothing reads it) | none |
| 2 | Bettor evidence and costs readers: per side and per world, the world drag, netting of fees (computed, not stored), unpriced closes, the net proving prior and simulated drag, the other side, the Bettor's own correlation matrix, continuation and outcome rho | `bettor/evidence.py`, `bettor/costs.py`, `bettor/correlation.py` | `test_bettor_evidence.py`, `test_bettor_correlation.py` | neutral | none |
| 3 | Sibling legs by position id: drain, still-holds, reconcile, the NL trader guard | `pending_closes.py`, `base.py`, `reconcile_asset.py`, `nl_trader.py` | `test_horde_sibling_plumbing.py` | neutral (books what happened; unsticks closes) | none |
| 4 | Horde banner display for rows that exist today: the strip, the unlinked mark, the peer sibling, same-symbol same bet, combined risk per asset; the new sentences reserved | `horde.py`, `notes.py`, the partial, the JS and CSS | `test_horde_banner_view.py`, `test_the_horde.py` extended | display only | none |
| 5 | Rails readers and the Portfolio fields (ceiling 10, circuit 25, book tail 50, Boldness 1, ticket toggle OFF): verdicts only, failing closed | `bettor/rails.py`, `portfolio/models.py`, migration 0018 | `test_bettor_rails.py` (verdict half) | neutral | none |
| 6 | BetSizing, TradeCost and DrawdownCircuit; the `bettor` switch; the shadow book; shadow hooks in `propose_entry`, `execute_entry` (the last look recorded), the `_skip` size tags, the ticket's `_preview` refusals and `_execute` | `bettor_models.py`, `bettor/brain.py`, `bettor/ledger.py`, `bettor/shadow_book.py`, `base.py`, `candidates.py`, `manual_trade.py`, `platform_control.py`, migration 00NN | `test_bettor_shadow.py` | neutral (byte-identical orders pinned) | `bettor` OFF |
| 7 | Nightly grading (three tables, the proving simulator for one-arm bets, each arm net of its fees), the TradeCost backfill, `manage.py bettor` | `bettor/grading.py`, `bettor/costs.py`, `tasks.py`, `celery.py`, the command | `test_bettor_grading.py` | neutral | — |
| 8 | /bettor/ page with readiness (paired, sequential, time to an answer), the ticket's Bettor block in the Size fieldset (shadow), the fill line (shadow), the skip words | `views_bettor.py`, templates, `base.html`, `manual_trade.py`, `notifications.py`, `telegram_eye.py` | `test_bettor_ticket.py` (shadow half), page tests | display only | — |
| 9 | Survival rails card behind the PIN: the daily stop and open risk move to it; circuit, ceiling, book tail, Boldness, the ticket toggle; the per-world words on /setup/ and the personas page | `views.py`, `_rails_card.html`, `setup.html`, `personas.py` | `test_rails_card.py` | neutral (values unchanged; loosening now needs the PIN) | — |
| 10 | Drawdown circuit: the anchored mark, confirmed readings, the slow bleed, WOULD TRIP in shadow; ON halts; the Telegram trip and re-arm words; Morgul G11 | `bettor/rails.py`, `tasks.py` (after the sync), `notifications.py`, `morgul.py` | `test_bettor_rails.py` (circuit half) | **tightens** when ON | `drawdown_circuit` OFF |
| 11 | `PIN_SWITCHES`; register `bettor_sizes_*` and `bettor_ticket_*` (inert); the dependencies, the cascade and `BULK_ENABLE_EXEMPT` | `platform_control.py`, `switch_pin.py` | `test_bettor_switches.py` | neutral (stopping cascades) | all OFF |
| 12 | Binding on paper: the Bettor's qty, rails-only judging with the last look's re-judge, the desk's `size_tick` under the lock, no stop widening | `base.py`, `runner.py`, `capital_desk.py`, `sizing.py` call sites | `test_bettor_binding.py` (paper) | both directions, **paper only** | `bettor_sizes_paper` (PIN; needs `drawdown_circuit` ON) |
| 13 | Horde data: HordeAction, `Orc.front_of` and `banner_key`, `OrcGrade` deltas, `OrcSeat` arming fields; birth attaches stamped legs; the census skips them | `orcs/models.py`, `constants.py`, `birth.py`, `census.py`, migration 00NN+1 | `test_orc_birth` and census additions | neutral (nothing stamps yet) | — |
| 14 | Gates re-keyed in shadow: `already_open` and `duplicate_state` record CALL TO ARMS facts; refusals unchanged | `base.py`, `risk_gate.py`, `marshal.route_call_to_arms` | `test_horde_gates_rekey.py` (shadow half) | neutral | — |
| 15 | The Marshal in shadow, the Bettor's leg lane, the add and front ghost arms, the refusal words, seat readiness | `orcs/marshal.py`, `banner.py`, `ghost.py`, `grading.py`, `words.py`, `bettor/brain.py` | `test_marshal.py`, `test_horde_budget.py`, `test_orc_add_arm.py`, `test_seat_readiness.py`, `test_horde_switch_off.py` | neutral | `horde_reinforce` OFF |
| 16 | Horde shadow proposals on the band: the line per seat, the seat-readiness line, the slot law amended; the Telegram digest line | `horde.py`, `notes.py`, `notifications.py` | the view and Telegram tests (shadow), `test_the_horde.py` extended | display only | — |
| 17 | Binding on eToro demo | as 12 | `test_bettor_binding.py` (demo) | both directions, **demo only** | `bettor_sizes_demo` (PIN) |
| 18 | Care per banner: the idea's R, the root's clock, banner-level weekend and event cuts (stamped legs only) | `position_care.py` | care tests on stamped legs | neutral until legs exist | — |
| 19 | Paper legs: REINFORCE, SECOND FRONT, REGROUP, through the bots' gates inside the fleet pass | `marshal.execute`, `base.py`, `tasks.py` | binding halves of the B14 files | **loosens on paper** (adds paper exposure) | `horde_legs_paper` (PIN) |
| 20 | Demo legs | as 19 | as 19 | demo only | `horde_legs_demo` (PIN) |
| 21 | Binding on real money | as 12 | `test_bettor_binding.py` (live) | **both directions on real money**: larger than today on a measured edge with real closes behind it, smaller on a thin, costly or correlated one | `bettor_sizes_live` (PIN) |
| 22 | The ticket binds: the Bettor's default, rails-only judging in the browser and on the server, the stop edit's re-ask, the restore buttons, override reasons | `manual_trade.py`, `base.html` and the ticket's script | `test_bettor_ticket.py` (binding half) | **loosens or tightens** per ticket (the 7% and class notional caps give way to the rails) | `bettor_ticket_<world>` (PIN, its own switch; needs `bettor_sizes_<world>`) |
| 23 | The operator's second ticket as a leg: "ADD by you"; "Reinforce Orc #12"; which refusals bind | `manual_trade.py`, `risk_gate.py` | `test_horde_manual_leg.py`, the gate tests' binding half | **loosens** (beside a bot: refused today, offered as a leg) | `horde_ticket_legs_<world>` (PIN, its own switch; needs `horde_legs_<world>`) |
| 24 | Hedges refused: a long and a short on one asset in one world | `risk_gate.py` | the gate tests' hedge half | **tightens** | none (needs the operator's yes, D4) |
| 25 | Real-money legs, per armed seat; the seat's arming on /orcs/ | `marshal.py`, `views_orcs.py` | the seat-readiness and switch-off tests | **loosens** | `horde_legs_live` (PIN) and a PIN per seat |
| 26 | (Decision) the council's Gambler into K | `bettor/brain.py`, `council.py` law text and tests | `test_council_*` amended | **both** | needs the operator's yes |

The first draft's commit 26 (retire MAX OPEN RISK) is withdrawn: MAX OPEN RISK stays as rail 6(a).

**Dependencies.**

| Commits | Depend on |
|---|---|
| 12 and later | pace fixes F1 (re-read after every booking) and F2 (cash in the preview), on the threefix branch; commit 10 (the circuit) and its switch ON |
| 21 and later | Live/paper apart C1-C3 (real-only daily stop and drawdown; a demo equity of its own) |
| 19 and later | the eToro demo measurements of the Orders-at-a-price work, for two positions on one symbol |
| Part B overall | Orcs O1 only. O2's intents (A-CONFIRM from `orcs/mandate.py`) can become a Marshal input when they land, never a second decider |

The shorts work is not a dependency: the per-side keys already size shorts on their own record, net of their overnight fees.

---

# D. Decisions for the operator

1. **The council in the Bettor.** It changes the council's law ("nothing in an order path or sizing reads them"). We recommend a shadow arm now, and binding only on his yes after its record shows a lift (commit 26).
2. **MAX OPEN RISK stays.** It is the book ceiling's open-risk half (his own 15%), measured from the marks to the stops, locked winners included, on the rails card with the PIN to loosen. The first draft's recommendation to retire it is withdrawn: with nothing else capping a single stake below the ceiling, the correlation floors alone allow 100% of the account at risk in calm. Loosening it later is his call, once /bettor/ shows the Bettor's realised heat.
3. **The daily stop and open risk on his own tickets.** Keep them warnings (the default, toggle OFF), or make them hard? The book's tail half and the per-bet ceiling are hard on tickets either way.
4. **Hedges.** We recommend refusing a long and a short on one asset in one world. This tightens: today two configs may do it (commit 24).
5. **Defaults.** Confirm: the sanity ceiling at 10% of the account per bet or banner; the book at 15% open risk and 50% on a tail move; the drawdown circuit at 25% under the mark since he last armed it, with a slow-bleed trip at 12.5% in 30 days and an automatic re-arm only on a recovery to within 12.5%; Boldness at 1; the daily stop at the value stored today (the comments record his 8%).
6. **What real money will rest on.** Proving that the Bettor sizes better than today needs about 600 to 1,500 paired bets, 10 months to 2 years at about 2 a day. We recommend he accepts binding real money on SAFE (no worse than today, rails held, 30 days binding on demo), with BETTER shown when it comes. The /bettor/ page prints the date it projects.
7. **Follow-up, not in this build.** Charge eToro's fees in the proving simulator and in paper fills, and include instruments deactivated during the history span in the proving universe. Both tighten today's verdicts and paper records, so they change today's arm; we recommend yes, as their own commits after this build, each with its own check of which verdicts move.

# E. Read-only checks before building (VPS)

None of these sends an order or writes anything.

1. **Real closes per (rule, class, side), and the bet rate:** the sample the Bettor will read, and the graded bets a day that set the projected dates. This is map_sizing §9 command 1. Run it again with `'demo'` and `'paper'`, and divide each count by the days it spans.
2. **Score coverage:**

   ```
   cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py shell -c "from bot_program.models import AssetBotTrade as T; qs=T.objects.filter(status='CLOSED', realized_r__isnull=False); print(qs.count(), qs.exclude(composite_score=0).count())"
   ```

3. **Proving trades with a regime and an MFE:**

   ```
   cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py shell -c "from backtester.models_proving import ProvingTrade as P; print(P.objects.count(), P.objects.exclude(regime='').count(), P.objects.filter(mfe__gte=1).count())"
   ```

4. **Equity readings per env** (bankroll and drawdown):

   ```
   cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py shell -c "from django.db.models import Count; from bot_program.models import BrokerEquityReading as R; print(list(R.objects.values('broker','env').annotate(n=Count('id'))))"
   ```

5. **Open rows sharing a symbol and side today** (the plumbing of commit 3):

   ```
   cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py shell -c "from django.db.models import Count; from bot_program.models import AssetBotTrade as T; print(list(T.objects.filter(status__in=('OPEN','CLOSE_PENDING')).values('config__user','symbol','side','paper').annotate(n=Count('id')).filter(n__gt=1)))"
   ```

6. **Unpriced and inferred closes per key** (the share that makes a key unmeasured):

   ```
   cd ~/Sauron_Vision && ./deploy/dc exec -T web python manage.py shell -c "from django.db.models import Count, Q; from bot_program.models import AssetBotTrade as T; print(list(T.objects.filter(status='CLOSED').values('rule_name','config__asset_class','side','paper').annotate(n=Count('id'), unpriced=Count('id', filter=Q(pnl__isnull=True)), inferred=Count('id', filter=Q(metadata__exit_price_inferred=True))).filter(Q(unpriced__gt=0)|Q(inferred__gt=0))))"
   ```

---

# R. The review: every finding and what became of it

**Applied** (B = blocking, S = should-fix, N = nit):

| Part | Sev. | Where it landed |
|---|---|---|
| A2.3 bad-data defence threw away the losses that ruin an account (two findings) | B | A2.3 one-sided guard; Example 3; A13 tests |
| A4/A5 no book-level notional or shock bound | B | rail 6 (book ceiling, tail half); the tail move replaces `JUMP_PCT` in the ceiling; A5's sentence about `d_eff` corrected |
| A11 `drawdown_circuit` switch versus binding | B | A11: binding needs the circuit ON; turning it OFF disarms binding; its state survives OFF and ON |
| A4 rolling 90-day mark; slow bleed; self re-arm | B | A4 anchored mark, confirmed readings, slow-bleed trip, recovery re-arm, PIN re-arm restarts the mark; A2.7 `D` reads the same measure |
| A2.2/A2.3/A10 costs inside R | B | A2.3 costs inside R and `TradeCost`; `d_cost` removed; the worth rule on fixed fees; A10 each arm net of its own fees; Example 4 |
| Kish `n_eff`, `sigma_mu`, `omega` (two findings) | B, S | A2.3 weight mass as precision; the drag's variance; `omega` from own-world mass; A13 test |
| A10 readiness power and time to an answer | B | A10 paired sequential test, SAFE / BETTER, size level apart, the projected date; D6 |
| A10 one-arm bets graded kindly; path dependence | B | A10 three tables, the proving simulator, the shadow book, growth on each arm's own equity |
| A2.8/B4 locked winners counted as zero | B | A2.8 and B4 mark-to-stop risk; Example 5; tests |
| A6 the ticket's client-side verdict | B | A6 `judgeSize` mirrors the rails while binding; old caps become warnings; meter on free cash |
| A6 moving the stop on the ticket | B | A6 shipped `terms`, the debounced re-ask, the inside-`d_eff` sentence, the pinned qty |
| A2.8 heat bound; D2 | S | A2.8 bound restated as ceiling / floor; rail 6(a) keeps MAX OPEN RISK; D2 rewritten; commit 26 withdrawn |
| A2.8 correlation fails open | S | A2.8 the Bettor's own matrix, class defaults, suspect windows unmeasured; `test_bettor_correlation.py` |
| A2.3-A2.5 small samples and many keys | S | sceptical prior (30); z = 1 until 50 own closes; terciles only at 30 by weight; the earned-stake ramp, graded as temperament |
| A2.3 unpriced exits | S | A2.3 population; E6 |
| A12 rails at the send; failure mode | S | A4 the last look's re-fit and re-judge; rails fail closed while binding |
| B13 legs skipped the gates and the lock | S | B3 legs through `propose_entry`'s gates, inside the fleet pass under `TICK_LOCK_KEY`; new refusal codes |
| A11 resuming without the PIN | S | A11 the cascade; every key in `BULK_ENABLE_EXEMPT`, `bettor` included |
| C commits 22 and 23 arrived ON | S | their own switches, OFF on arrival, PIN-gated: `bettor_ticket_<world>`, `horde_ticket_legs_<world>` |
| B4/B12 real-money adds on simulated evidence | S | ghost outcomes at weight 0.5 with the drag; never toward readiness; the seat armed by the PIN |
| A2.3 world table labels | S | relabelled; each cell pinned |
| A2.3 the drag function | S | `evidence.world_drag` on `_world_filter`, per pair, shrunk, its error in `sigma_mu` |
| A2.3 the prior: SIM_DRAG, survivorship | S | the measured simulated drag sets `mu0` and `n0`; LIVE_PROVEN read as UNPROVEN; survivorship stated in the words |
| A2.3/A2.4 pooling counted the key twice; terciles | S | the other side only, the key left out; tercile prior without its rows, `n0` 100, out-of-sample monotone effect first |
| A2.9 venue-minimum round-up | S | only at `mu_c > 0` within 2 × `f × B`; no absolute term; graded as its own arm |
| A2.6 voice validity | S | out-of-sample coefficient; 100 bets; 95% with alpha spending |
| A2.4 the Mind's regime weight | S | one bar-derived taxonomy; `tau` graded out of sample; the Mind's label a shadow voice |
| A2.2/A2.5 R unit (`d_stop` against `d_eff`) | S | `c` stored; the real multiple `λ × c` said and graded; the worth rule × `c` (see Rejected 1) |
| B12 seat readiness | S | 60 actions with real fills, net of fees, Holm across seats, sequential |
| A6/A12/B7 two different risks | S | A6 "at stake" and "at your stop" both, the `d_eff` line; the fill line |
| A6/A12 what drove the size | S | the headline and the fill line keyed on `binding`, against today's |
| A6 buttons and size fields | S | block inside the Size fieldset; one restore button per size; what a decline leaves |
| A5/A7 old controls keep their words | S | A5 per-world words on /setup/ and personas; the appetite warning rewritten; the AGGRESSIVE row corrected |
| A7/A11 no dial for the bots | S | Boldness on the rails card; the ceiling's copy says "refused, never shrunk" |
| A10 shadow hidden on refused tickets | S | A6 refusals return the block and record `today_outcome = refused` |
| B7 Telegram buttons with no page | S | `/horde/actions/<id>/ticket/`; "Holds until ..."; expired tickets say so; [Open banner] to the root's forensics |
| B3 the name "Standard-bearer" | S | renamed the Marshal; the authority line on binding banners |
| B3/B5/B12 Horde decisions invisible | S | refusal words; a Horde line per seat; one-seat strips; the seat-readiness line; `SKIP_WORDS` |
| B5 the reserved-sentence and "no Orc acted" laws | S | patterns registered; the slot law amended; tests extended in commits 4 and 16 |
| B8 the operator's own add | S | "ADD by you", graded apart; only the rails and the hedge bind; "no suggestion" demands no reason |
| A4 what the operator is told when the circuit trips | S | A4 words in percent; main chat once per event; the band head line |
| B4 `mu_cont` population and units | N | the final-close trigger and the add's own R |
| B7 two messages for one regroup | N | a header on `fill_close_message` |
| B5 slot key units | N | `idea_risk` in R, `banner_risk` in percent, money on the strip only |

**Rejected, or done another way, with reasons:**
1. **R unit: "estimate on `x_i = r_i × c_i`".** Not taken; we took the finding's own alternative. Every row measures R at the stop sent. Folding each row's `c` into its outcome would pool bets whose stop sat inside the noise with bets whose stop did not, and the estimate would then depend on how the Bettor sized in the past. So `f` stays Kelly's fraction in R, `d_eff` only caps the quantity, and `c` is stored and carried into the words, the worth rule and the temperament labels.
2. **Costs: "charge the eToro fee schedule in the proving simulator and in paper fills".** Not in this build. Both change today's arm: the verdicts that gate trades today, and the paper P&L the pages show. That is outside shadow before power. The Bettor nets the fees in its own readers (`TradeCost`; the holdout recomputed net), so its numbers are right without touching today's. The change is recommended as its own follow-up (D7).
3. **The prior: "include instruments deactivated during the history span".** Deferred for the same reason (it moves today's verdicts), and recommended in D7. The survivorship is stated on every prior now.
4. **Small samples: "scale z with the number of live keys".** Not taken. z is 1 until 50 own closes, plus the earned-stake ramp. A per-key count is stable and can be read on the ticket; the number of live keys changes every night and would move every stake with it.
5. **Book bound: "alternatively keep MAX NOTIONAL MULTIPLE as that rail".** Not taken; rail 6(b) uses each class's tail move instead. A 4× notional multiple treats a forex book and a crypto book alike; the loss on a tail move is the number the operator can feel, and it is comparable across classes.
6. **One finding asked for no more than a sanity ceiling's shock half at the tail move.** We added the brain's tail fit inside half the ceiling as well. Without it, an ordinary tight-stop forex Kelly bet would be refused whole by the ceiling, which would make a refusal a routine event instead of a symptom.
