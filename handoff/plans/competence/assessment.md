# Will Sauron Vision be competent on the markets? An honest assessment

**Date:** 2026-11-07. **Revised:** 2026-11-11, after a refutation pass (see "Revision" below).

**Scope.** This reads the code at main `ede54d0`. Every `file:line` below was checked again on 2026-11-11 in a fresh `git archive ede54d0` at `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/competence/r3/src`. No production data, broker or model was touched.

**Current main is `15dd487`**, two merges later. Between the two, only the Oculus page, its template, tests, `deploy/RUNBOOK.md` and one test counter (`core/wall_facts.py`) changed. No cited code file moved, except where §3.7 says so.

**Sources.**
- The synthetic measurements come from the scripts listed in §7. Each one was run again on the fresh copy, and the key ones were repeated with a different seed.
- The outside evidence is in §8. It rests on search summaries: direct fetches of the regulators' and publishers' pages failed in this session (hosts not allowed).

**What "competent" means here.** A rule is competent when all of these hold:
- its expectancy per trade is positive after **all** costs: the spread both ways, eToro's fees, overnight financing, slippage and gaps, and currency conversion;
- that expectancy is measured out of sample, on real money;
- it holds at a size that survives the drawdowns that expectancy implies.

A business test sits on top: the profit must also pay the platform's running costs (AI and servers).

**Revision (2026-11-11).** The refutation found no promise of returns and no wrong citation, but it found statements that overstated safety. All were checked again and the confirmed ones are applied here:
- sizing: the 0.25% default holds for bots only, on a pool that is a stored number (§2.1, §3.1);
- each bot has its own breakers, though the account has none (§2.9, §3.1);
- the AI is not all in shadow: the Mind's pause already blocks bot entries (§2.7, §3.9);
- the proving ground's false-positive rates were restated, with a zero-net-edge test (§2.3, §3.2);
- sample sizes now state their power (§3.5, §4);
- financing is charged in one narrow case since 2026-10-31 (§3.3);
- several protections act only when a switch is ON (§2.6, §2.9, §3.1);
- the command loop now writes outside the repository and no longer depends on the shell (§6);
- three outside claims were corrected (§1, §8), and the unverified account size was removed.

---

## 1. Verdict

### Today: unproven, and the honest default is "not yet"

Nothing in the repository can show an edge. Only his real-money record can. The code's own dated comments describe an early record that did not pay. The operator lines below are the code's English renderings of his messages, not his exact words:

- **2026-10-02.** "our Sauron is unfortunately not winning over the long run". The week's diagnosis ends "Never paid." (`bot_program/scorecard.py:3-10`). That week's rows mix paper and live ("two paper stops").
- **2026-10-02.** "we are getting plundered" (`bot_program/aragorn.py:4-5`)
- **2026-10-05.** The code paraphrases him, without quote marks: the account has paid in and nothing has come back (`signals/management/commands/bar_losers.py:3-4`).
- **2026-10-06.** `bollinger_squeeze_breakout` is "the one rule with a measured edge": 43 graded signals, a 33% hit rate, +0.26R (`signals/promotion_pipeline.py:129-134`).
  - These are graded signals, not trades taken. The record is gross of costs and measured on the signal card's own levels.
  - With σ ≈ 1.4R, its standard error is 0.21R, so the 95% interval runs from about −0.16R to +0.68R.
  - So even this rule cannot yet be told apart from luck on its own record. Its PROVEN from the proving ground is stronger evidence, but that verdict assumed the cost table, not eToro's real costs, and a PROVEN can itself be luck (§3.2).

### Can it become competent? Plausibly, but only narrowly

The realistic best case is a handful of (rule, asset class, side) cells that keep a positive expectancy after eToro's real costs. Those would trade small, and everything else would stay on paper. Bollinger squeeze is the only candidate the code names. As a whole fleet — 36 rules were put on real money by hand on 2026-10-01 — it is unlikely to be competent.

### What it has going for it

No data compares this platform with other retail setups, so no such comparison is made here. Retail CFD accounts usually fail through leverage, costs, missing stops, overtrading and overriding their own rules. Sauron has real answers to several of these:

- By default a bot sizes each trade from its risk, 0.25% of its pool, and its stop is held at eToro.
- By default each bot stops opening after 4 straight losses or a 10% drawdown of its own pool.
- A strict backtest judge refuses real money to rules it marks FAILED.
- The entry filter charges eToro's measured per-order fees.
- The books count in R and never count an unmeasured result as zero.
- The AI's powers only block or cut; none raises a size.
- A kill switch protected by a PIN disables every bot.

These raise the odds of **surviving** and of **learning the truth quickly**. They do not create an edge by themselves. Several act only when their switch is ON (§2.9, §3.1), and no drawdown stop covers the account as a whole.

### Why it is fragile

1. **The trade ideas are public.**
   - They are textbook patterns on 4h bars: RSI divergence, MACD crosses, moving-average crosses, the Bollinger squeeze, ICT/SMC.
   - No proprietary data and no execution advantage appear anywhere in the code.
   - The research is mixed before costs. The strictest studies find the gains vanish after costs and cannot be picked in advance (§8).
2. **The costs most likely to decide the result are mostly not counted.**
   - Overnight financing is charged only in the entry filter, and only for an eToro short of a class measured on demo (since 2026-10-31).
   - eToro's fees are never subtracted from booked results, and eToro exits are booked at a level or a mark, not a fill.
   - So every closed result and every promotion gate reads too optimistic.
3. **Real money reaches rules by routes weaker than the proving ground.**
   - A hand promotion has no evidence gate and no PIN.
   - Aragorn, when ON, can promote on 20 paper closes.
   - A full-size override rests on a gross signal record.
   - Every verdict except FAILED still trades at 0.25×.
   - On the hand-taken lane, the daily stop, total exposure and the proving verdict only warn.
4. **The settings allow losses to outrun the evidence.**
   - The risk ceiling is 7% per trade.
   - The comments record a daily stop he set at 8% (the default is 3%), extending to 12% for "elite" entries.
   - Open risk may reach 15%, and the comments record 100% of the account allowed as margin (the default is 50%).
   - Hand tickets default to the highest leverage.
   - The Bettor plan's recorded ceilings go further: 20% per bet and 80% open risk.
   - Which values are set today is unknown.
5. **The samples are far too small.** Every promotion step rests on 10 to 50 trades or signals. An 80% chance of seeing a +0.1R edge takes about 1,240.
6. **The AI bill is certain; the edge is not.**
   - The code measured about 4 USD a day, under a default ceiling of 15 USD a day. That measurement predates the Council and the Orc minds.
   - On a small account, this bill can exceed what any plausible edge earns.

### What we cannot see from here

The answer depends on data we do not have:
- the live record per rule, class, side and world (real money, eToro demo, paper);
- which switches are ON: `aragorn`, `crisis_mode`, `morgul_guards`, `morgul_brake`, `proving_ground`, `pipeline_promotion`, `trade_debate`, and others;
- today's proving-ground verdicts;
- the risk per trade of each config, each pool's size, MAX BOT LEVERAGE, the daily stop, the margin limit and the manual-lane knobs actually set;
- the account size;
- the financing eToro actually charged;
- today's AI spend.

§6 lists read-only commands that answer the first three without printing any money figure.

### Outside base rates (§8)

- **ESMA (2018):** 74–89% of retail CFD accounts lose money.
- **AMF (France, 2014):** 89% of 14,799 clients lost money over 2009–2012, and the most active traders lost the most.
- **FCA (2016):** 82% of clients in its sample lost money.
- **Leverage caps:** the 2010 US cap cut high-leverage traders' losses by 40% (Heimer & Simsek).
- **Backtests shrink live.**
  - Across 215 bank products, the median Sharpe ratio fell from 1.20 in backtest to 0.31 live.
  - Across 888 Quantopian algorithms, the backtest Sharpe ratio barely predicted live results (R² < 0.025).
- **Day traders:** under 1% are predictably profitable net of fees (Taiwan).
- **AI agents:** we know of no robust published evidence that LLM agents produce a durable net trading edge. One 2025 benchmark finds their reported advantages shrink on longer periods and wider universes.

### Competence, leg by leg

| Leg | Status from the code |
|---|---|
| Positive expectancy | Unproven. The code's own history is negative (early October). One candidate rule, not significant on its own record. |
| After all costs | Not measurable today. eToro's fees, financing (but for measured eToro shorts at entry), exit fills and gaps are missing from every booked R. |
| Out of sample | The proving ground does this properly, at table costs (2–10 bps). It still calls a zero-edge rule PROVEN in about 1–5% of runs. The real-money samples are far too small. |
| At a survivable size | For a bot at its defaults, yes: 0.25% per trade and its own breakers. Not at the recorded ceilings, not on the hand-taken lane, and no drawdown stop covers the account as a whole. |
| Pays its running costs | Unknown. The code itself warns that the AI bill can become the dominant expense. |

---

## 2. Real strengths

1. **Bots size each trade from its risk.**
   - The size is `qty = f × pool / |entry − stop|`, with f = 0.25% by default. That value was chosen so a system with zero edge survives the several hundred trades it takes to find out (`bot_program/asset_engine/sizing.py:27-36, 49-50`).
   - The final size is checked again, and refused rather than shrunk, past the 7% cap (`bot_program/asset_engine/base.py:6150-6196`).
   - This makes 1R mean the same thing on every trade, so expectancies can be compared.
   - Limits: f is a fraction of the config's pool, `cfg.capital`, a stored number that can be larger than what the broker holds (`sizing.py:286`; `base.py:4826-4830`). Each config can carry its own `risk_per_trade_pct` up to 7% (`sizing.py:140-161`). §3.1 covers the hand lane.
2. **Stops are held at the broker.**
   - Every live bot order carries its stop and target to eToro (`base.py:7058-7073`).
   - A leveraged order without a stop is never sent (`bot_program/engine/etoro_client.py:3501-3577`).
   - Stops only tighten, and R is always measured against the opening stop (`bot_program/engine/trailing.py:1-14`).
   - After a fill worse than planned, the stop moves so the risk held equals the risk sized (`base.py:6000-6020`).
3. **A validator built to say no, and money that obeys it.**
   - The proving ground replays each rule as the bot trades it (`backtester/proving/__init__.py:17-49`; `backtester/proving/judge.py:1-55`):
     - entry at the next bar's open, with ATR levels and position care;
     - a gap through the stop filled at the open;
     - a 30% holdout never used to choose;
     - a Šidák-corrected bootstrap bound;
     - a test at double costs;
     - at least 3 of 5 time folds positive.
   - On synthetic noise that loses 0.06–0.09R a trade after table costs, its own engine labels a rule PROVEN in 0.0–1.0% of runs and PROMISING in 5.0–13.0% (200 runs per case).
   - §3.2 gives its error rates on a rule with exactly zero net edge, which are higher.
   - Since 2026-10-07, a FAILED verdict refuses the bot's real-money entry, and anything unproven enters at a quarter of its size (`backtester/proving/proof.py:11-35, 77-82, 416-430`).
   - The nightly judge runs only while `proving_ground` is ON (`backtester/tasks.py:489-491`).
4. **An entry filter that knows eToro's fees.**
   - A trade must clear twice its round trip and keep a net reward:risk of at least 1.5 after costs (`bot_program/asset_engine/risk_levels.py:553-608`).
   - eToro's measured per-order fees are added at the final size: crypto 1% a side, stocks 1 USD a side (`risk_levels.py:374-390`; `base.py:7685`).
   - It refuses the trades those fees would eat, which includes most live crypto.
5. **Measurement discipline.**
   - Results are in R.
   - An unmeasured exit is "counted and left out — never read as zero" (`bot_program/scorecard.py:27-30`).
   - A signal without a stop stays ungraded rather than being scored (`signals/performance.py:84-99`).
   - The three money worlds are named (`bot_program/bot_grading.py:64-77`).
   - Inferred exit prices are counted and labelled (`bot_program/scorecard.py:32-40`).
6. **A ladder that can also demote, when switched on.**
   - The floor: a live rule with at least 20 graded signals at 0R or worse, or a thin edge under a low hit rate, goes back to paper (`signals/promotion_pipeline.py:116-138`).
   - It acts only through `bar_losers --apply`, or through the nightly sweep once `pipeline_promotion` is ON (`signals/management/commands/bar_losers.py:18-21, 115-117`).
   - Aragorn benches pairs that lose on real closes (`bot_program/aragorn.py:19-32, 76-87`). Its moves need `aragorn` ON.
7. **The AI's powers only block or cut.**
   - **In shadow.** Council weights are "computed and shown … no sizing, no gate" (`ai_agents/council_grading.py:20-31`). The Orcs and their minds act on their own simulated position, never on the real one (`bot_program/orcs/__init__.py:1-11`; `bot_program/orcs/mind.py:1-5`; `bot_program/orcs/intents.py:1-7`).
   - **Already binding.** The Mind's pause blocks a rule's bot entries, paper and live (`base.py:4977-5014`; `brain/context.py:231-242, 382-421`). It also squeezes theme caps (`context.py:424-451`).
     - A report's pause is softened to "watch" only when the Mind's trust is low. An ungraded Mind ("unknown") keeps full power (`context.py:366-379, 445-449`).
   - **Binding later.** The trade debate is OFF by default. Once ON, it stays in shadow for its first 30 graded live trades and then binds, whatever its score. It can only cut a trade or veto it (`ai_agents/agents/trade_debate.py:12-23, 37-41, 375`).
   - Trust stays neutral until 10 calls are graded (`ai_agents/calibration.py:49`).
   - The capital desk is deterministic, not AI, and in shadow by default (`bot_program/capital_desk.py:8-10, 49-53`).
8. **A spending ceiling on AI:** 15 USD a day by default, computed from recorded spend (`ai_agents/spend.py:1-14, 51-60`).
9. **Operational guards.**
   - **Per-bot breakers.** By default a bot halts new entries after 4 straight losses or a 10% drawdown of its own realised curve (`bot_program/asset_engine/safety.py:27-28, 242-325`; `base.py:4685-4692`). They never close a position, each config can change them, and the hand lane has none.
   - **Kill switch.** Behind the PIN, it disables every config, then tries to close every position. A close that fails is recorded and left to close by hand (`bot_program/engine/kill_switch.py:3-8`; `dashboard/views.py:7066-7098`).
   - **Entry timing.** No bot entry at rollover, at the market open, in the last hour before a weekend, or around a high-impact release (`bot_program/entry_timing.py:1-57`). No switch is needed.
   - **Morgul.** Read-only guards for a position without a stop at eToro, margin, daily loss, stop overshoot and drift, with an optional brake. Both are OFF on arrival (`bot_program/morgul.py:1-131, 142-143`).
   - **Position care.** Break-even, trailing stop, weekend lock and a no-progress exit (`bot_program/position_care.py:133-180`). It runs only while `aragorn` is ON (`position_care.py:679-682`).
   - **Dead man's switch.** OFF unless its URL is set in `.env` (`core/management/commands/dead_man_switch.py:22-26`).
10. **Code that tells the truth about itself.**
    - It records its failures in dated comments (§1).
    - It states its own limits: "Composite strategy is a starting point, not alpha … necessary but not sufficient" (`NOTES.md:85-92`), and "six backtest paths and not one that could be believed" (`backtester/proving/__init__.py:1-15`).
    - That culture is the precondition for finding a real edge rather than imagining one.

---

## 3. Real risks and gaps, ranked by how much money they could cost

### 1. Leverage, sizing and the hand-taken lane let losses outrun the evidence

**At stake:** the whole account, in the tail.

- **Risk per trade.**
  - The ceiling is 7% per trade, "room the operator chose" (`bot_program/asset_engine/sizing.py:52-80`).
  - The code's own arithmetic: ten losses in a row at 7% cost 52%. One bot at its default breakers cannot get there, since it halts after 4 losses (25% at 7%). The hand lane has no such breaker.
  - The default stays at 0.25%. His real risk per trade is unknown: it depends on each config's `risk_per_trade_pct` and on each pool's stored size.
  - A live hand ticket whose risk budget is under eToro's minimum size is raised to that minimum, as long as it risks no more than 7% of the pool. He sees the raise and confirms with the PIN (`bot_program/manual_trade.py:879-931, 1892-1990`).
- **Daily and book limits.**
  - The default daily stop is 3% (`portfolio/models.py:34`). Comments record that he set 8% on 2026-10-01, with "elite" entries allowed until 12% (`portfolio/risk_gate.py:229-248`; `base.py:4790-4793`).
  - Open risk at the stops may reach 15% (`portfolio/models.py:56-63`).
  - The default margin limit is 50% of the account. Comments record that he chose 100% on 2026-10-05: "one gap can take the whole account, and he was told so" (`portfolio/models.py:44-55`).
  - At the recorded values, a single day can cost more than 20% without breaking any rule. Today's values are unknown.
- **Hand tickets.**
  - They default to the highest leverage, shorts included. The multiplier changes the cash eToro locks, not the units (`bot_program/manual_trade.py:204-232`).
  - MAX BOT LEVERAGE never caps them, and a blank value caps nothing for the bots either (`portfolio/models.py:76-88`).
  - Hard on a ticket: the 7% risk cap, the class's notional cap and the pool's free cash (`manual_trade.py:972-1035`).
  - Warnings only: the daily stop, total exposure, the book's notional cap, entry timing and the proving verdict (`manual_trade.py:1248-1262, 1747-1765, 2083-2095`; `bot_program/entry_timing.py:54-57`).
- **Gaps.** A gap through the stops "is bounded by nothing here", and eToro's close-out rule is "a BELIEF" (`base.py:374-391`).
- **Protections that are OFF unless switched ON.** A missing switch reads OFF (`core/platform_control.py:25, 72-77`). This covers:
  - position care (`bot_program/position_care.py:679-682`);
  - crisis sizing, with the drawdown and losing-streak scales (`bot_program/posture.py:27-33, 81-90`);
  - the desk's budget (`bot_program/capital_desk.py:49-53`);
  - Morgul's guards and brake (`bot_program/morgul.py:142-143`).
- **No drawdown stop at account level.** Each bot has its own breakers (§2.9), but nothing halts the account as a whole after a drawdown.
  - The book's daily stop is the only account-wide limit. It reads realised losses over a trailing 24 hours (`portfolio/risk_gate.py:216-227`), so a slow bleed never trips it. It is hard for the bots and only a warning on hand tickets.
- **The Bettor plan would widen this further.** It is not built. Its recorded choices are a 20% loss ceiling per bet, 80% book open risk, a 25% circuit breaker and warnings only on manual tickets (`/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/bettor/operator_choices.md:4-6`). Two losses at the ceiling cost 36%, more than that plan's own breaker.
- **Zero-edge Monte Carlo, 200 trades.** Median maximum drawdown is 5.4% at 0.25% risk per trade, 20% at 1%, and 86% at 7%.

### 2. Real money on rules with no proven net edge

**At stake:** a steady loss on every trade.

- **Bulk promotion.** On 2026-10-01, 36 rules were put at live_full by hand, "most with 0 graded signals" (`backtester/proving/proof.py:4-9`; `signals/promotion_pipeline.py:539-540`).
- **Everything except FAILED still trades.**
  - PROMISING, INSUFFICIENT, no verdict, and rules no family replays all trade at 0.25×.
  - The judge itself calls PROMISING "never on money" (`proof.py:15-29`).
- **The judge's own error rates** (its own code on synthetic trades, §7).
  - A rule with exactly zero net edge comes out PROVEN in about 1–5% of runs: 1.2–1.5% at 60 trades, 3–5% from 120 trades up. It comes out PROMISING in 7.5–31%.
  - Each live rule is judged as a single candidate, on up to 84 cells a night (§3.5). So a few PROVEN verdicts can be luck.
  - PROVEN keeps full size and never expires: the newest saved verdict is read whatever its age (`proof.py:141-153`).
  - A real edge of +0.10R gross, at a 0.05R cost, comes out PROVEN in only 2–24% of runs (60 to 1,000 trades). The judge refuses most small real edges too.
- **The full-size override.**
  - A rule gets full size back when its own record shows at least 20 graded signals at +0.10R or better (`proof.py:382-409`; `signals/promotion_pipeline.py:446-492`).
  - That record is all-time, pools both sides and every class, is gross of costs, and is measured on the card's levels.
  - A rule with zero edge passes this test 34% of the time at n = 20 (exact binomial), and 15% at n = 200.
- **Weak routes to real money.**
  - A hand promotion has no evidence gate and no PIN (`dashboard/views_admin_hq.py:1598-1614`; `signals/promotion_pipeline.py:1207-1221`).
  - A rule without an evaluator passes a hand promotion with "no backtest evidence available". The automatic sweep refuses it (`signals/promotion_evidence.py:15-17, 171-179`).
  - Aragorn, when ON, moves a paper rule to live_full on its paper closes (`bot_program/aragorn.py:33-55, 90-94, 206-220`).
    - The test: 20 closes, expectancy ≥ +0.15R, an 80% one-sided bound above zero, profit factor ≥ 1.3, and a non-negative last 10.
    - The proven pair enters at 0.25×, the rule's other classes are benched (`aragorn.py:33-39, 84, 236-260`), and the proof's cut multiplies on top (`proof.py:30-34`).
    - Zero-edge trades pass one look about 7–8.5% of the time. With a look after every close from 20 to 60, 25% pass at least once, or 16% with a 0.07R paper cost. It evaluates every 4 hours.
- **Public ideas, mostly unjudged.**
  - The signals are textbook patterns (`signals/rules/technical_rules.py:130-162, 367-394`).
  - The proving ground replays only 14 live rule names, as 15 rule-side pairs.
  - So most live rules, including every opportunity setup, have no verdict at all.
- **Timeline.**
  - The plan of 2026-09-15 was "two to three months" of paper trading first (`bot_program/management/commands/paper_readiness.py:1-7`).
  - A real BTC round trip was measured on 2026-09-26 (`risk_levels.py:377-378`; `base.py:821-824`).
  - The bulk promotion followed on 2026-10-01.
- **Size of the loss (estimate).**
  - With no edge, the expectancy is roughly minus the costs. The noise runs gave −0.06R to −0.09R a trade at table costs.
  - At real costs, −0.1R to −0.3R a trade is plausible.
  - 200 trades at −0.2R is −40R: 10% of the pool at 0.25% risk per trade, 40% at 1%.

### 3. Most costs are counted nowhere a decision is made

**At stake:** this is systematic. It turns a gross edge into a net loss and makes every gate optimistic.

- **Overnight financing.**
  - The code says financing "is charged by NOTHING here — the cost filter is spread only" (`bot_program/management/commands/preflight_live.py:441-444`). That line is now partly stale.
  - Since 2026-10-31, an eToro short of a class whose short was measured on the demo account pays its measured overnight fee in the entry filter (`base.py:7711-7742`; `risk_levels.py:393-473`).
  - It is still charged nowhere for longs, in the booked results, on paper or in signal grades.
  - Cost per night ≈ (annual rate ÷ 365) ÷ stop fraction. The 6% rate is an illustration, not eToro's:
    - at a 0.30% forex stop: 0.055R a night, about 0.22R over the 96-hour no-progress window;
    - at a 1% stop: 0.016R a night.
  - Two nights at a tight forex stop erase the +0.10R "thin edge".
- **eToro's fees are never booked.**
  - They are used only to refuse an entry. Booked P&L is the price difference times the quantity (`base.py:3757-3764`).
  - Crypto costs about 200 bps per round trip at eToro, against the 10 bps that paper and the proving ground charge (`risk_levels.py:64-70, 377-380`; `backtester/proving/simulate.py:115`). Paper and proving-ground crypto results therefore cannot be carried over to eToro.
  - Stocks pay 1 USD a side. At 0.25% risk that costs 800 ÷ pool in R: 0.4R on 2,000 USD.
- **Exit prices.**
  - A position eToro closes itself is booked at its stop or target level, ignoring any gap (`bot_program/venue_exit.py:19-25`).
  - A close the platform sends to eToro is booked at a mark, since eToro publishes no closing fill (`bot_program/scorecard.py:453-460` calls these "inferred").
  - The exit half-spread, about 0.01–0.03R on major pairs, never reaches the books.
- **Gaps.** The proving ground does fill a gap through the stop at the next open (`backtester/proving/__init__.py:33-36`; `judge.py:27-32`). The books and the signal grades do not.
- **Signal grading.** Signals feed the ladder, the loser floor, the override and the rule weights. They are graded gross, with a stop counted at exactly −1R (`signals/performance.py:144-160`).
- **Effect.** These read too high:
  - the realized P&L and `realized_r` of closed trades;
  - the scorecard;
  - the daily stop;
  - the "elite" and attack-tier records;
  - every promotion gate.
- **One exception, display only.** Since 2026-11-06 an open eToro row shows eToro's own profit figure. Nothing that decides money reads it (`portfolio/services.py:1010-1026`).

The operator's own plan put real fees under "Later" (`.../scratchpad/bettor/operator_choices.md:8`).

### 4. Running costs can exceed any plausible edge on a small account

**At stake:** certain money, every day.

- **The code's own warning.** AI is "the largest recurring variable cost … and the least validated component — it can quietly become the dominant expense of running a system whose trading edge is not yet measured" (`ai_agents/spend.py:3-7`).
- **Measured burn.** About 4 USD a day, under a default ceiling of 15 USD a day (`spend.py:51-60`). That line dates from 2026-10-03 or earlier. The Council arrived on 2026-10-16 and the Orc minds on 2026-11-05. Today's spend is unknown.
- **Arithmetic.**
  - At 0.25% risk per trade and +0.10R a trade, each trade earns 0.025% of the pool.
  - Paying 120 USD a month then takes 240 trades a month on 2,000 USD, 48 on 10,000, and 10 on 50,000.
  - At the ceiling of about 450 USD a month, the AI costs 22.5% of a 2,000 USD account every month.
- **Account size** is unknown here.

### 5. Samples are too small, and many tries go uncounted

**At stake:** this is how luck gets money and how real edges get refused.

- **Sample sizes.**
  - The ladder's steps use 30, 20 and 10 (`signals/promotion_pipeline.py:95-108`); Aragorn uses 20, 10 and 8 (`aragorn.py:76-94`).
  - With σ ≈ 1.41R, 20 trades can only tell an edge of +0.52R from zero, and 50 trades +0.33R.
  - A true +0.1R edge shows up half the time with about 540 trades (one-sided 5%) or 770 (two-sided). An 80% chance takes about 1,240.
- **Uncounted tries.**
  - Each live rule is judged as a single candidate (`backtester/proving/run.py:321`). The nightly run writes at most 84 verdicts at 4h (14 cases × 6 classes) plus the 1h po3 rows, and fewer in practice, since three families name their markets (`backtester/proving/families.py:851-877`). Only the generator corrects for its tries (`run.py:351-353`).
  - Evolution, the pattern miner and the AI strategy generator add more tries that no gate counts.
  - The code admits it: a rule "can look good for three weeks by luck, get promoted to live, and hand the losses back" (`signals/promotion_evidence.py:4-6`).

### 6. Execution gaps

**At stake:** rare but large.

- **Weekend and event gaps.**
  - The code's own example: "a 0.09% forex stop through a 2.5% Monday gap is -28R" (`backtester/proving/judge.py:24-31`).
  - Before a weekend, only winners at +0.5R or more are locked, and only losers at 5x leverage or more are closed (`bot_program/position_care.py:148-149`). This needs `aragorn` ON.
- **Stops moved by eToro.** eToro rewrote a real BTC stop from 5% to about 10% below the entry (`base.py:812-826`).
- **Fail-open limits.** The book limits stop applying if the database cannot be read (`portfolio/risk_gate.py:2060-2075`).
- **No partial close.** eToro cannot close part of a position (`bot_program/engine/etoro_client.py:4034-4047`). Paper can still scale out when `aragorn_scale_out` is ON (`position_care.py:166-169`), so paper can show an exit that live cannot take.

### 7. Readings that can mislead a decision to scale up

- **"Live" includes the eToro demo.** "Live" means `paper=False`, which includes the demo account. This holds in the scorecard, the ladder, Aragorn, the evidence ledger and the side scorecard (`bot_program/bot_grading.py:64-77`; `bot_program/scorecard.py:261-276`).
  - On our synthetic rows, a real-money record of −0.20R over 14 closes printed as +0.13R once 6 demo closes were pooled in.
  - At `ede54d0` the /oculus/ book panel pooled them too. On `15dd487` its open book is split into real, demo and paper; the desk's live venue and the paper-against-live gap still pool.
- **"Paid" on thin samples.** The scorecard prints "Paid" for any positive average, even on one trade (`scorecard.py:418-423`). No real-money result carries a confidence interval.
- **A wrong label in the command's own help.** Its header calls `--venue live` "real money only" (`bot_program/management/commands/scorecard.py:8`), while the rows it reads include the demo account.
- **A mislabelled profit factor.**
  - The /command/ "PROFIT FACTOR" is the average win divided by the average loss, which is the payoff ratio (`dashboard/views_command.py:828-837`).
  - Example: a book winning 30% of trades at a payoff of 1.5 shows 1.50, while its true profit factor is 0.64.

### 8. The rule that trades is not exactly the rule that was validated

- **Forming bars.**
  - The original long rules and bollinger squeeze — the one candidate edge — read the newest stored bar, which may still be forming (`signals/rules/technical_rules.py:20-26, 134-162, 371-394`).
  - The short mirrors and the proving ground use closed bars only (`:47-74`).
- **Different levels.**
  - Signal cards use fixed-percent levels; bollinger uses ±2% and ±4% (`:391-392`).
  - The bot trades ATR levels (`bot_program/asset_engine/risk_levels.py:26-28`).
  - So the graded record that can grant full size measures a different trade from the one sized.
- **One signal is enough.** A single signal from a single rule can open a trade (`bot_program/asset_models.py:145-147`).

### 9. The AI layers are unproven as decision makers

- The Council and the Orcs are in shadow. The Mind's pause already binds, and the debate binds after 30 graded live trades once ON (§2.7). Both can only block or cut, so their direct risk is a missed trade, not a larger one.
- Neither needs a good record to bind: an ungraded Mind has full power, and the debate binds whatever its score.
- Published tests are not encouraging. A 2025 benchmark finds LLM strategies' reported advantages shrink on longer periods and wider universes (§8).
- Their money risk today is their bill (item 4), and the temptation to let them decide more before they are graded.

### 10. A latent default

- A rule-control row created without a stage defaults to live_full (`signals/models_control.py:72-74`). Aragorn's own header calls this "a hazard" (`aragorn.py:35-37`).
- Low probability, high consequence.

---

## 4. What "competent" should mean, measurably

Judge each (rule, asset class, side) separately, in each world. **Real money decides.** Demo and paper only screen.

| Criterion | Threshold | Shown today | Missing |
|---|---|---|---|
| Unit | R net of the spread both ways, eToro's fees, financing and conversion, with exits at broker fills | gross R (`scorecard`, `side_scorecard`) | net-of-cost R; broker exit prices |
| Sample | at least 100 real closes for a first read; about 1,240 for an 80% chance of confirming +0.1R, using n ≈ ((1.645 + 0.84) × 1.41 / E)² | the count, and "THIN SAMPLE" under 20 | the count needed for the observed E |
| Expectancy | above zero, with a 95% one-sided lower bound above zero (block bootstrap by day), corrected for the number of rules and variants tried | point averages; the proving ground's bound at table costs | an interval on real money; correction across live rules |
| Validation | PROVEN by the proving ground for that class and side, at real costs | `prove show`, `side_scorecard` | verdicts at real costs |
| Stability | positive in at least 60% of months and 3 of 5 time folds; still positive without the best 3 trades; not carried by one symbol | the proving ground's folds | a monthly real-money table; a concentration check |
| Paper-to-real gap | real expectancy at least about 50–70% of the paper or proving-ground figure, with the gap explained by costs | the /oculus/ gap rows (where "live" still includes demo) | a real-only gap |
| Drawdown | maximum drawdown in R within what the sizing assumes (for example ≤ 40R at 0.25%, i.e. 10%); account drawdown kept below a hard stop set in advance | per-bot breakers; a snapshot drawdown that mixes worlds and cash flows | equity drawdown net of deposits; a hard stop for the account |
| Truth check | booked realized P&L within a few percent of eToro's statement for the same period | nothing | a monthly reconciliation |
| Business | net trading profit above the AI and server costs over at least 6 months | AI spend per day (/ai-models/) | the comparison |
| Hand lane | the same table, judged separately (`manual_take`) | `scorecard --by lane` | as for the bots |

**Sample guide** (σ ≈ 1.41R, one-sided 5%):

| Trades | Smallest edge they can tell from zero |
|---|---|
| 10 | +0.73R |
| 20 | +0.52R |
| 50 | +0.33R |
| 100 | +0.23R |

| Edge | Trades for a 50% chance of seeing it | Trades for an 80% chance |
|---|---|---|
| +0.3R | about 60 | about 140 |
| +0.2R | about 135 | about 310 |
| +0.1R | about 540 | about 1,240 |

---

## 5. Next steps, ranked by how much they raise the chance of real competence

**Sizes:** S = settings, or under a day of work. M = one PR of a few days. L = a week or more.

1. **Size down until a lower bound clears zero.** (S for settings, M for code)
   - Risk per trade at 0.25–0.5%, on every config.
   - MAX BOT LEVERAGE set.
   - Daily stop back near 2–3%, with no elite override.
   - Margin at 50% of the account or less.
   - Hand tickets default to a low multiplier and obey the same hard limits as the bots, with a PIN to override that is recorded.
   - A hard stop on the account's drawdown, above the per-bot breakers.
   - Revisit the Bettor ceilings (20% a bet, 80% open risk) before building them.

   Competence includes surviving, and this is the cheapest step with the largest protective effect.
2. **Count real costs in every R.** (L)
   - Book exits at eToro's fill, or at eToro's own netProfit.
   - Subtract eToro's per-order fees.
   - Read the overnight fees from eToro (statement or API) and charge them per row, longs included.
   - Carry the measured fees and a financing model into paper and the proving ground, then re-run every verdict.

   This is the operator's "real fees later" item: make it now. Until it is done, treat every verdict as an upper bound.
3. **One gate for every route to real money.** (M)
   - Real money only for (rule, class, side) cells that are PROVEN at real costs, or whose net lower bound on real money is above zero.
   - Hand promotions, Aragorn and the full-size override all pass through the same gate.
   - PROMISING, INSUFFICIENT and no verdict go to paper, not to 0.25×.
   - Count every live rule and variant in the multiple-testing correction, and give a PROVEN verdict an expiry.
4. **Fewer, better rules.** (S–M)
   - Keep the 1–3 cells with evidence, bollinger squeeze first, and retire the rest to paper.
   - Make the long rules and bollinger read closed bars only (S).
   - Grade signals on the ATR trade the bot actually takes (M).
   - Require at least 2 independent sources, or a higher score, to enter (S).
   - Let the exits work. In the one week the code analysed, paper and live rows together, 12 of 15 winners were closed by hand at +0.28R on average (`bot_program/scorecard.py:3-10`), while the bots' plan targets +2R (`bot_program/asset_engine/risk_levels.py:26-28`).
     - Our illustration: with winners at +0.28R and losers at −1R, a book needs a 78% win rate just to break even.
     - The code's own figure for that week: +0.42R paid against the +0.43R a 68% win rate needs.
5. **A competence report.** (S now, M done properly)
   - **Now:** the stopgap `edge_summary.py` separates real, demo and paper, with 95% bootstrap intervals. It is tested read-only and R-only, but it sits in our scratchpad, not on his server.
   - **Then:** a `manage.py edge_report` command with a block bootstrap, net-of-cost R, a `--world` option, the trade count needed, and a verdict per cell.
   - **Fixes (S):** add `--world` to `scorecard`, correct the PROFIT FACTOR label, and change "Paid" to "positive, not significant" unless the interval clears zero.
6. **Make the running cost visible, and make it earn its keep.** (S)
   - Track the monthly AI and server cost against net trading profit.
   - Keep AI layers that are not graded positive off, or on a low budget.
   - Lower `AI_DAILY_BUDGET_USD` on a small account.

---

## 6. Read-only commands he can run now

Run these on the VPS. One paste writes everything to a single file in his home folder.

```
cd ~/Sauron_Vision
sh -c 'for c in "component list" \
  "scorecard --days 3650 --venue live --by lane" \
  "scorecard --days 3650 --venue live --by rule" \
  "scorecard --days 3650 --venue live --by exit" \
  "scorecard --days 3650 --venue paper --by rule" \
  "side_scorecard" "prove show" "bar_losers"
do echo "=== $c"; ./deploy/dc exec -T web python manage.py $c; done' > ~/competence.txt 2>&1
```

Then, as a separate step: `cat ~/competence.txt`.

**Why this form.**
- The file goes to `~/competence.txt`, not into the repository. A file left in the repository folder is not covered by `.dockerignore`, so the next build would copy it into the image (`Dockerfile.prod:56`), and git would show it untracked.
- `sh -c '…'` hands the loop to `sh`, so it no longer depends on the shell he types in. Without it, zsh passes `"component list"` as one word and six of the eight commands fail.

**How these were checked (2026-11-11, on the fresh copy).**
- **Flags.** `--help` confirms each one: `component list`; `scorecard --days --venue {live,paper} --by {lane,rule,class,venue,signal,exit,orc}`; `side_scorecard`; `prove show`; `bar_losers`; `aragorn status`; `council show --days`; `mind_contract trust`. `scorecard` has no `--world`.
- **Read-only.** Each of the 11 commands (the 8 above plus the 3 optional ones) ran on a seeded throwaway SQLite database, in an empty network namespace, with every SQL statement logged. Each exited 0 with zero SQL writes, zero cache writes and zero network connects, and the hash of the full database dump was unchanged.
- **No money.** The seed carried planted money values. None appears in the output of the 8 loop commands. The output holds only counts, R, percentages, rule, class and symbol names, trade ids and dates.
- **The loop.** With a stand-in for `deploy/dc`, the form above gives 8 headers and the right argument counts when typed in bash, in sh (dash) and in zsh, and with `sh` being dash or bash.
- **Not checked.** Real data, PostgreSQL, the real `docker compose`, and his server's shell.

| Command | What it prints | What we read from it |
|---|---|---|
| `component list` | ON or OFF for every switch | which protections are really active |
| `scorecard --days 3650 --venue live --by lane` | closed trades on real money plus demo: count, win rate, average win and loss, payoff, expectancy, total R, THIN SAMPLE, trades closed by hand, overshoots; bots and the hand lane apart | the overall record, with the hand lane separate |
| `… --by rule` | the same, per rule | which rules carry the book and which lose |
| `… --by exit` | which exit closed each trade, and how many exit prices are inferred | how much of the R is an estimate |
| `scorecard --days 3650 --venue paper --by rule` | the paper record per rule | the paper-to-real gap |
| `side_scorecard` | per rule × class × side: graded signals, paper, live (demo included), the newest verdict, the stage | which cells could ever qualify |
| `prove show` | the newest proving run: verdict, trades, holdout, lower bound, double costs, folds; "no saved verdict yet" if it never saved one | what the strict judge says. Run it Monday to Saturday: the generator runs on Sunday at 03:50 UTC, after the 03:40 judge, so on Sunday the newest run is the generator's (`config/celery.py:590-599`). |
| `bar_losers` | every live rule's all-time graded record, how it got there ("by hand, unproven"), and the floor's verdict; nothing is written without `--apply` | which rules are on real money without proof |

**Optional, not in the loop.**
- `edge_summary.py`. It separates real, demo and paper, with intervals, and prints R only. It has to be copied to the server first: `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/competence/evscripts/edge_summary.py`, run with `./deploy/dc exec -T web python manage.py shell < edge_summary.py > ~/edge_summary.txt`.
- `aragorn status`: which pairs are live, on probation or on the bench. It prints the free text of reasons and actions. In our test a planted money note in that text did print, so it is not guaranteed free of money.
- `council show --days 180` and `mind_contract trust`: how well the AI is calibrated.

**His own check.** On his eToro account statement for the last 90 days, compare the total of overnight fees and other fees with Sauron's booked total. The gap is what Sauron does not count. He can send us the ratio rather than the amounts.

**How to read it.**
- "live" here means real plus demo. Only the edge_summary script separates the two, so the loop alone cannot give a real-money verdict per rule.
- "Paid" appears for any positive average, even on one trade.
- Every R is gross of financing and fees.

**Never use these for this:**
- anything with `--apply`, `--save` or `--yes`: they write;
- `preflight_live`, `open_trades`, `treasury`: they print money.

---

## 7. Unknowns, and the files behind this

**Unknown from here:**
- the production switch states;
- the /setup/ values: risk per trade per config, each pool's size, MAX BOT LEVERAGE, daily stop, margin limit;
- the manual-lane knobs;
- the account size and currency;
- eToro's actual financing;
- today's AI spend;
- the record per rule and per world;
- the record of the hand-taken lane;
- whether bollinger squeeze still holds its edge.

**Scratch files** (all under `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/competence/`):
- `r3/src/`: `git archive ede54d0`, the copy every citation and command was re-checked against on 2026-11-11.
- `r3/out/engine_noise.txt`, `r3/out/zero_edge.txt`: the saved noise tests, run again (`sigscripts/engine_noise_mc.py`, `sigscripts/zero_edge_mc.py`).
- `r3/scripts/indep.py`, `r3/scripts/zero_big.py`, `r3/scripts/aragorn_seq3.py` and their outputs in `r3/out/`: the same questions with other seeds, the sample sizes, the losing streaks, the financing drag, the AI hurdle and the drawdowns.
- `r3/scripts/fam2.py`: the count of rules the proving ground replays.
- `r3/scripts/run3.sh`, `r3/scripts/probe3.py`, `r3/scripts/seed3.py`, `r3/out/cmd/`: the write, cache and network probe of the §6 commands.
- `r3/looptest/`: the loop under bash, sh and zsh.
- `evscripts/edge_summary.py`: the stopgap report.
- `r2/`, `refute/`, `verify/`, `asrc/`: the earlier passes.

---

## 8. Outside sources

These rest on search summaries. Direct fetches of the publishers' pages failed in this session.

**Retail CFD results**
- ESMA, CFD product intervention, 2018 (74–89%): https://www.esma.europa.eu/press-news/esma-news/esma-agrees-prohibit-binary-options-and-restrict-cfds-protect-retail-investors
- AMF, retail CFD and forex results in France, 2014 (89% of 14,799 clients, 2009–2012; the most active lose most; no learning effect): https://www.amf-france.org/sites/institutionnel/files/contenu_simple/rapport_etude_analyse/epargne_prestataire/Etude%20des%20resultats%20des%20investisseurs%20particuliers%20sur%20le%20trading%20de%20CFD%20et%20de%20Forex%20en%20France.pdf
- FCA CP16/40, 2016 (82% of sampled clients lost): https://www.fca.org.uk/publication/consultation/cp16-40.pdf
- Heimer & Simsek, the leverage cap and retail forex (losses of high-leverage traders down 40%): https://www.nber.org/papers/w24176

**Technical rules, data snooping, backtests that shrink live**
- Park & Irwin 2007. Of 95 modern studies, 56 find positive results, 20 negative and 19 mixed; the authors warn that data snooping and after-the-fact rule selection weaken the positive ones: https://ideas.repec.org/a/bla/jecsur/v21y2007i4p786-826.html
- Bajgrowicz & Scaillet 2012. Even in sample, the rules' performance is offset by low transaction costs, and the best rules could not be chosen in advance: https://econpapers.repec.org/RePEc:eee:jfinec:v:106:y:2012:i:3:p:473-491
- Sullivan, Timmermann & White 1999: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=65140
- McLean & Pontiff 2016: https://afajof.org/issue/volume-71-issue-1/
- Suhonen, Lennkh & Perez 2017 (summary; 215 products, 1.20 to 0.31): https://www.cxoadvisory.com/big-ideas/live-performance-of-alternative-beta-products/
- Wiecki et al. 2016 (888 algorithms, R² < 0.025): https://joi.iijournals.com/content/25/3/69
- Bailey, Borwein, López de Prado & Zhu 2014: https://www.ams.org/notices/201405/rnoti-p458.pdf

**Who survives**
- Barber, Lee, Liu & Odean 2014 (under 1%): https://faculty.haas.berkeley.edu/odean/papers/day%20traders/The%20Cross-Section%20of%20Speculator%20Skill.pdf
- Chague, De-Losso & Giovannetti: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101
- Barber & Odean 2000: https://faculty.haas.berkeley.edu/odean/papers/returns/Returns.html

**LLM trading**
- FINSABER, 2025. Reported LLM advantages shrink on longer periods and wider universes: https://arxiv.org/abs/2505.07078
- Glasserman & Lin 2023. In sample, a "distraction effect" outweighs look-ahead bias; out of sample, look-ahead bias is not a concern: https://arxiv.org/abs/2309.17322

**CFD financing**
- IG, how overnight funding is calculated: https://www.ig.com/en/help-and-support/cfds/fees-and-charges/why-is-overnight-funding-charged-and-how-is-it-calculated-

**Removed in this revision.** The claim that the FCA paper says leverage magnifies costs (unconfirmed), and an unverified account size.
