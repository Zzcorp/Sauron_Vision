# Anduin: critique of the design (2026-11-12)

Critique only: nothing in the design was edited. Scripts, frames and crops are in `critique_work/` beside this file.

Severity: **HIGH** = wrong or misleading on a rule he set, fix before he sees it. **MEDIUM** = fix before the note goes or before the spec is called final. **LOW** = polish.

Counts: **3 high, 12 medium, 15 low** (30 findings).

---

## 0. Verdict

- **The craft is good.** The look is the house look, the colour rules are kept almost everywhere, the motion is restrained, and the data contract is unusually exact: I opened about 75 of its file:line references and every one lands on the thing it names (four inexact claims, A9 and A19).
- **The five-second read, as drawn:** the weather, yes (one word, top left). The REAL positions, yes (red edges). What is flowing, yes with the legend, but only at the mock's invented cadence (B4). **Where the money is, no:** the sizes do not say volume (B1), the baskets add the three worlds in their shape (A1), and two thirds of the reserve's "used" is nowhere on the page (A8).
- **Against his words:** blocks in baskets, yes. Baskets larger with volume, no: they are larger with the number of blocks. Flows passing through, yes, as a hairline. The weather shaping the scene, weakly (B2).
- **Truth:** two rules of the spec would make the real page say false things at A1: the definition of a refusal (A2) and the age reset by the animation (A4). The mock also shows a datum the code does not store (A7).
- **Cost:** the measured figures hold, with two exceptions: the idle river is not free (A5), and the canvas board runs uncapped and ignores reduced motion (A10).
- **The note** is short, plain and in the right voice. Six of its sentences promise more than A1 can give, and OK 6 hides its consequence (A11, §5).

---

## 1. What I ran

- Looked at every still in `shots/` (1440, 1920, 390, the three moments, the board), at the popover crop, and at one frame per second of `shots/anduin.webm` (13 frames, `critique_work/sheet_1.png`, `sheet_2.png`), with crops at full resolution.
- `critique_work/probe.js audit`: every visible text node at rest (1440, 1920, 390) and at four instants of the story: size, contrast on its own ground, the ground under every text that holds a digit (void, gradient, opacity), digits in the display face, every red fill, every text in the Eye's green, jade and coral figures, block and basket geometry against the values.
- `probe.js stress`: 0 positions, 40 positions, one position of $500,000, the World, Lane and Theme groupings, By risk.
- `probe.js motion`: drawn frames and rAF per second, the pauses, reduced motion, and CPU cores of Chrome's whole process tree (same method as the designer: headless, 4 Xeon cores, no graphics card, 1440x900, DPR 1, shared box at load 1.3-2.1).
- `travel.js` (mote travel times), `board_rm.js` and `board_cpu.js` (the board under reduced motion, its cost).
- The code at main `15dd487` (read-only checkout), `magic_spec.md` §1-4, the S1a tokens, M1 §3-5 and §10, M4's outline, the Operations Center spec's event rules.

## 2. What holds (checked, no finding)

| Check | Measured |
|---|---|
| Text under 11 px | none: 416 nodes at 1440, 419 at 1920, 370 on the phone, and at 4 instants of the story |
| Contrast | lowest is 4.94:1 (white on the REAL red); nothing under 4.5:1 |
| Figures on the void, on a gradient or on a glow, at rest | none |
| Digits in the display face | none: Orbitron is loaded without digits; the Lane titles ("FOREX #3") draw their digit in JetBrains Mono (measured) |
| Text in the Eye's green | the wordmark only; no figure |
| Solid red #CC3A40 | the REAL chip, the REAL block edge, the armed pill; nothing else (one other red fill: A15) |
| Per-world sums | basket feet (the four groupings, and By risk), reserve and Downstream print one figure per world; no figure adds two worlds |
| Drawn frames | 30.0 a second at rest and in the story (rAF 59.9) |
| Pauses | hidden: 0 draws, 0 rAF in 2 s; locked: 0, 0; back: 60-61 |
| Reduced motion | 0 rAF, 0 running animations, 0.002-0.005 core |
| CPU, my runs | river stopped 0.065-0.067 core; at rest 0.297-0.301; the story looping 0.371-0.385 (designer: 0.05-0.06, 0.24-0.26, 0.32-0.34: same order, mine 15-20 % higher on a shared box) |
| Weather sources | `market_stress.py:464 current()`, levels `:48-49`, thresholds `:51-56`, `:59-60`, words `:455`, `recovery_days :494`, `components["raw"]["realized_vol"]` (`:149`, `:420`), `aragorn_models.py:69-83`, `tasks.py:1837-1845` behind `crisis_mode`, `celery.py:573` (900 s), `posture.py:56`, `:87-97`, `regime.py:13`, `exchange_status.py:724`, `:743-800`, `entry_timing.py:139 SHUT_CLASSES` (index left out, as the spec says), `position_care.py:177-178`, `:187`, `:312`, `:358`, `market_data/models.py:63`: all correct |
| Other references opened | positions, seat fields, venue mark, reserve, quotes, rail, skips, the events and their senders, models: all land on the named symbol |
| Empty book | five dashed slots, the river crosses them, no clipping |

---

## 3. Lens A: truth, discipline and cost

### A1 [HIGH] The three worlds are added in the basket's shape, one scale lets DEMO and PAPER crush REAL, and OK 6 does not say so

- **Evidence.** `build()` takes one `vmax` over every world, and a basket's size is the sum of its blocks' heights. In the mock's Forex basket, 423 of 615 px of block height (69 %) is DEMO and PAPER. Spec §4.2 admits it: "the basket's own size is the only place where worlds meet". At the end of the video (frame 13), Forex holds no REAL row and is still the widest basket on the page: two columns of DEMO and PAPER. Stress run: with NAS100 (DEMO) at $500,000, the three REAL blocks fall to 126-129 px, the floor: simulated money decides how his real money is drawn. The note's OK 6 says only "un bloc PAPER peut être aussi haut qu'un REAL".
- **Why high.** "Never added" is his first rule, and the basket's size is the thing he asked to read volume from.
- **Fix.**
  1. `vmax` = the largest REAL value (the largest value shown only when no REAL row exists).
  2. Inside a basket, one band per world in the order REAL, DEMO, PAPER, no venue, with a hairline and the world chip between bands, and the per-world sum at the band's right.
  3. The basket's solid outline wraps the REAL band; the other bands sit in a dashed annex. A DEMO or PAPER block above the scale is capped and marked `›` beside its figure; it never raises the scale.
  4. Reword OK 6 (§5).
  5. A1's test: "no shape sums two worlds" joins "no figure sums two worlds".

### A2 [HIGH] The spec's definition of a refusal will draw false refusals on the real page

- **Evidence.** Spec §1.4: a refusal is "every skip code except `no_signals` and `stale_signals`", and one evaporation is drawn "when a symbol's last skip changes its code".
  - `already_open` is a skip, written by `propose_entry` whenever the vote says enter and the config already holds the symbol (`base.py:4909-4920`, again `:5309`). `skips.clear()` wipes the symbol's skip at the fill (`base.py:7615`, `skips.py:186-195`). So one bot pass after a fill, the last skip goes from nothing to `already_open`: the page draws "BTCUSD refused · already_open" seconds after the block formed, for a REAL order that was taken.
  - `hold` is the bot waiting (M1 §5.2), `cooldown` clears by itself, and `no_price` and `suspect_mark` are also written for open positions (M1 §5.4). All count as refusals under the spec's rule.
  - A code that flips with no new signal (a vote that meets `market_shut` at the close, then `hold`) draws an evaporation each time.
- **Fix.** Replace the rule in §1.4 and §3:
  - **Refusal** (token evaporates): `gate_blocked`, `cost_filter`, `bad_timing`, `market_shut`, `leverage_refused`, `proving_failed`, `sized_to_zero`, `venue_min_size`, `wide_spread`, `eligibility_refused`, `stage_blocked`, `brain_paused`, `paper_fallback`, `desk_displaced`, `venue_sick`, `shadow`, `order_rejected`, `order_error`, `error`, and `order_in_doubt` (coral, stays).
  - **Waiting** (its own count "the vote said no / already held", no token): `hold`, `already_open`, `cooldown`.
  - `no_price` and `suspect_mark`: a refusal when the config holds no row on the symbol; left out when it does (they are about the open position).
  - One evaporation only when the refusal's `at` is newer than the `created_at` of the symbol's newest signal, and that (config, symbol, code) was not already drawn for it.
  - Tests first: a fill followed by `already_open` draws nothing; `hold` a hundred times draws nothing; a held symbol's `no_price` draws nothing.

### A3 [MEDIUM] One signal meets several bots in several worlds; the page draws one fate, names no bot, and its counts add up as the code's cannot

- **Evidence.** A skip belongs to one config (`extras["skips"]`, `skips.py:161-183`), so the same signal can be taken by the paper bot and refused by the real one. The mock's refusal label names no bot and no world ("XAGUSD refused · cost_filter · ..."), while the taken label does ("taken · REAL · Crypto #5"). UPSTREAM prints "13 arrived · 3 taken · 5 refused · 5 on the rail": 3 + 5 + 5 = 13, a partition that four readers (Signal rows, trade rows, last skips, the rail) will never produce. Spec §1.4 reads "taken" by world, but the mock shows no split, and "5 refused" lacks the spec's own words "N symbols, by their last reason" (they are only in a `title`).
- **Fix.**
  1. The refusal label: `XAGUSD refused by Commodities #4 [REAL] · cost_filter · <detail>`.
  2. A token may leave several outcome chips at its gate, one per bot that judged it.
  3. Counts: `3 taken · 2 real · 1 paper` and `refused: 5 symbols by their last reason · 3 by real bots`.
  4. Change the mock's numbers so they do not add up, and print under them "four readers, they do not add up".

### A4 [MEDIUM] The animation resets the price's age, and it lands late

- **Evidence.** Mock: `priceMote.end()` sets `q.age = 0`; spec §3: "the price line's age returns to 0". Measured travel at the calm speed (96 px/s): 0.8 s for EURUSD, 8.7 s for AAPL, 10.8 s for NAS100 at 1440; up to 15.0 s at 1920. At A1 add the poll (up to 10 s) and the "random instant inside the poll interval". A price can be printed "0 s" more than 30 s after its stamp, and the right-hand baskets always look later than Forex.
- **Fix.**
  1. The printed age is `now − mark.at` from the payload, always; the canvas never writes it. Test: an age never decreases without a new `at`.
  2. A mote's travel is bounded: it enters at its own basket's gate, or its speed is distance / 1.2 s times the weather factor.
  3. Drop "released at a random instant"; stagger by each stamp's own offset, 1 s at most.

### A5 [MEDIUM] The idle river is not free; the spec says it is

- **Evidence.** Spec §5.3: "a frame with nothing to move is skipped (a shut book at night costs what the still page costs)". Measured with every feed quiet: rAF 59.9/s, 0 draws, 52 ms/s of main thread, 0.107 core. The still page: 0 rAF, 1 ms/s, 0.066 core. `frame()` re-arms itself for ever and `step()` runs 30 times a second. On the real page, idle is the usual state (B4).
- **Fix.** Stop asking for frames when no actor is alive and the bed is clean. Wake on the next event, poll or queued instant (`setTimeout` to it). Tick the ages with one 1 s timer. Add the budget line: idle = the still page within 0.01 core, 0 rAF. Correct the sentence in §5.3.

### A6 [MEDIUM] A gain is drawn as glowing green dots that read as the Eye's motes, while the gain's figure is ink

- **Evidence.** `SPR.up` (white-green core, jade halo, 10 px) against `SPR.price` (white-green core, Eye halo, 9 px): in `critique_work/c_m3_forex.png` the returning stream and the price mote cannot be told apart. The computed colour of the close label's "+$65.00 ▲" (`#fl3 .up`) and of Downstream's "+1.69R" (`#clbody .up`) is rgb(230,241,234), ink: the `.up` class is overridden. The house rule is the reverse: a gain is jade text, never a light (`magic_spec.md` §3.2); spec §1.8 says jade for REAL closes booked at eToro's price.
- **Fix.**
  1. Money motes are never glows: a 3 px square, ink, for every stream, whatever the result.
  2. The result's colour goes on the figure: jade or coral text with its sign and ▲ or ▼, in the riding label and in Downstream, for REAL closes booked at eToro's price only.
  3. CSS: `.fl .m.up, .ln .m.up { color: #24B582 }`, and the same for `.down`.

### A7 [MEDIUM] The mock prints a signal number on bot rows; the code does not store one

- **Evidence.** The popover reads "Comes from: bot Forex #3 · rule trend_break_4h · signal #4012" (`work/sw_popover_crop.png`); the `from:` strings of the six bot rows and the table view carry the same. Spec §1.1 and N8 say the id is not stored, and N8 is an engine write outside A1-A3.
- **Fix.** Remove "· signal #..." from the bot rows in the mock, the table and the board; keep it on ticket rows only (`manual_trade.py:3245`). The note says what he gets (§5).

### A8 [MEDIUM] Two thirds of the reserve's "used" is nowhere on the page

- **Evidence.** RESERVE prints "used $4,402.10". The REAL blocks' capital at work is $433.68 + $198.61 + $908.24 = $1,540.53. The other $2,861.57 has no block and no line. Spec §1.3 has a "Held outside Sauron" row and §1.1 a "+N at eToro, not on Sauron ›" footer; the mock draws neither. A basket's foot prints exposure, while the money streams stand for capital at work, which is only in the hover.
- **Fix.** Draw both lines in the mock (`outside Sauron $2,861.57 · 2 positions ›` in the REAL pool, `+2 at eToro, not on Sauron ›` in a basket's foot), or make the invented numbers reconcile. Add capital at work per world to the foot (`REAL $21,749.00 exposure · $433.68 at work`), so the reserve and the baskets can be checked against each other.

### A9 [MEDIUM] `board()` is not cached: the book's age and the query budget rest on a cache that does not exist

- **Evidence.** `dashboard/horde.py:2167-2169`: "Not cached: marks move inside the fingerprint's blind spot". What is kept 20 s is the head (`_head_raw`, `:817-838`) and the tab (`:2180`, `:2197-2208`). Spec §1.1 gives the book's age as "the board's own cache, 20 s" and §5.3 budgets the reader "behind the Horde's 20 s cache". The Horde itself ticks every 20 s (`TICK_S`, `:85`); Anduin plans a 10 s poll.
- **Fix.** §1.1: the age is the payload's own `as_of`, and the broker read's is `head.as_of`. §5.3: Anduin's reader keeps its own payload 10 s per user, keyed on the Horde's fingerprint; the 10 s poll asks for marks only; the 30 s poll for the rest. Measure both after `cache.clear()` before fixing the budget.

### A10 [MEDIUM] The canvas board runs at the display's rate, costs as much as the river, and ignores reduced motion

- **Evidence.** `Anduin.dc.html` holds 9 `animateMotion` and 9 `animate`, all `repeatCount="indefinite"`. Measured: 60 layouts a second, 0.32 core. With `prefers-reduced-motion: reduce`: successive frames still differ, 60 layouts a second, 0.24 core. Its reduced-motion rule stops three CSS animations and no SMIL.
- **Fix.** Draw the motes as CSS `offset-path` animations with `steps()` at 30 a second; one rule under reduced motion hides them and leaves the still bed; three motes and the one refused signal are enough for a board.

### A11 [MEDIUM] The French note: six sentences promise more than A1 gives, and OK 6 hides its consequence

Detail and replacement sentences in §5.

### Low

- **A12** The ribbon's second hatched band (`#fr2`, the first print plus 90 minutes) has no name anywhere: `aria-hidden`, absent from the table. Fix: name every band in its `title` and in the table, or draw the nearest print only until A3.
- **A13** Ages the spec promises and the mock does not print: the calendar's (`calendar read 2 h ago`, spec §1.7), the volatility's bar date (only in a `title`, which touch never shows), the per-basket 24 h counts. Fix: print them.
- **A14** "touches 6 open" against the Operations Center board's "touches 7 of 8" on the same book: MSFT, a stock, is touched by a USD print under `event_for`. And the ⚠ count (the care's record, written at its next pass, on bot-managed rows) can differ from the touch count (the rule, every row). Fix: `evt` on MSFT; print `touches 7 · 6 lit by the care`.
- **A15** The track's loss fill is `rgba(229,72,77,.8)`, a red fill, for any world. `magic_spec.md` §3.4 already asks for such fills to be outlined. Fix: a coral outline or hatch for a loss; the jade fill stays.
- **A16** The Eye's green beside REAL: the feeder of a lower block runs 0.5 px from the REAL block's red edge for its whole height, and the top-edge light (`.pe`) starts at full strength on the REAL corner. Fix: feeders descend in the right-hand gutter; on a REAL block `.pe` starts 12 px in.
- **A17** Figures fade: a forming block's content is at opacity under 1 for 0.6 s (0.88 measured mid-way), a leaving block's down to 0.03, a label's for 0.35 s. Fix: animate the frame; the text appears and leaves at opacity 1.
- **A18** Words. The mock's crisis sentence lacks "; open risk-on longs tightened." (`market_stress.py:455-461`; the spec says verbatim). The refusal sentences are M1's table, not the command's: `why_no_trade` prints the code and the stored `detail`, and `skips.diagnose()` has its own advice. Fix: print the code and the stored detail, verbatim; a table of plain sentences belongs in `skips.py`, used by both.
- **A19** Contract nits. `fill_close` from `base.py:4488-4492` sends `"0"`, not `""`, when the result is unmeasured (`pending_closes.py:1459-1465` sends `""`). `vol_percentile` needs 120 values of 20-day volatility, about 140 daily closes, not 120 bars. `mark_age_t` (`horde.py:1347`) is in the light's facts, not on the seat (N3 covers it). "No event carries the amount" against `fill_close`'s `pnl`. Skips keep 200 symbols per config (`skips.py:158`).
- **A20** Pauses and caps. Under the lock the mock's three shell loops still run (breath, beat, armedbeat: measured). The loop's threshold is 31 ms, which allows 32 drawn frames a second on some displays: use 33.3. The phone's switches measure 42 px, not 44. The note's "un quart de cœur": my runs give 0.30.
- **A21** Two cases with no rule. A signal born while its market is shut (M4) arriving at a frozen gate: say that the token waits in the ice with "born while shut", with no evaporation. The return after a long hidden spell at A1: treat it as a fresh load (no flows, the counts tell), or an hour of fills replays at once.

---

## 4. Lens B: feel and clarity

### B1 [HIGH] Blocks and baskets are not sized by volume: 24 to 1 is drawn 1.5 to 1, and baskets rank by count

- **Evidence** (measured at 1440x900, By exposure).
  - Blocks: EURUSD $21,749 is 192 px, AAPL $908 is 129 px. Floor 126, cap 192.
  - Baskets, area: Stocks ($2,154 in all) 81,144 px²; Indices ($20,872) 63,296; Commodities ($3,972) 53,912; **Crypto, empty, 51,704**.
  - With Indices at $500,000: Indices is 347 px tall, Stocks ($2,154) 434 px.
  - At 1920 a tall block is taller by blank space (EURUSD: about 80 px of nothing).
  - The phone already has the honest mark: a bar whose width is value / largest.
  - The note says "Un panier est aussi grand que ce qu'il contient".
- **Fix.**
  1. A compact tier: floor about 48 px (line 1 symbol, world, glyph; line 2 side, R, price dot and age). Cap = the column's free height (346 px at 1440x900). Height linear between them; lines appear by tier, as `mid` and `tall` do today.
  2. Every block carries the phone's proportion bar, so size still reads under the floor.
  3. An empty family is a narrow dashed slot (about 96 px), not a full basket.
  4. Each basket's head carries one small bar per world on one page-wide scale, side by side, never stacked.
  5. Tests: above the floor, two blocks' heights are in the ratio of their values within 2 %; on the mock's book and on the $500,000 case, the baskets' REAL bars rank as their REAL sums.

### B2 [MEDIUM] The weather barely shapes the scene

- **Evidence.** The wave's height measures 0.2-1.7 px at rest (5 px at most by the code) in a 16 px strip of a 498 px stage. From calm to stressed the scene gains a chip, a sentence, 1.1 px of wave and faster motes. In every still the weather is a word. His words were "plein d'autres animations et caractéristiques selon la météo de marché". The Great River is a hairline.
- **Fix** (still shapes that hold no figure, so they cost nothing at rest).
  1. The river becomes a band of 28 px with three current lines; their spacing and wave carry the level and the family's volatility (1 to 7 px).
  2. The baskets' outline takes the level's tone (ink, amber, coral hairline); a shut basket's frost covers its whole outline and head rule.
  3. Inside the care's window the front is a hatched amber band in the air above the baskets it touches, the same datum as the ribbon.
  4. Keep OK 5, and show him calm, stressed and crisis side by side in one still.

### B3 [MEDIUM] Forty positions: not designed, and the page holds about twelve

- **Evidence.** A column holds two floor-size blocks at 1440x900 (346 px free, 126 + 8 each), and the stage six columns at the mock's 164 px: about 12 blocks (14 at the 132 px minimum, where lines clip; about 24 at 1920x1080). I injected 40 rows: Forex runs 514 px past its region and under the banks, Stocks and Indices leave the screen (content 1802 px wide in 1144), 52 lines clip (`critique_work/s_forty.png`). The fold of spec §2.4 is words only. His book runs many bot configs, paper above all.
- **Fix.** B1's compact tier gives 30 blocks or more at 1440x900 (five or six per column). Beyond it, draw the fold in the mock (`+N more · in the table`, REAL last to fold) and keep one test still at 40 rows in `shots/`. Say the capacity in the note.

### B4 [MEDIUM] The video shows a river that A1 cannot have

- **Evidence.** The mock releases a mote every 2.7-3.4 s per live instrument. The code: eToro quotes every 30 s for open REAL rows (`etoro_quotes.py:97`), a tick stamp rewritten every 240 s (`venue_mark.py:107`), one mote per instrument per poll at most. With three REAL rows that is about six motes a minute. The note gives it one sentence; spec §9 lists it as unsure.
- **Fix.** A `?cadence=real` switch in the mock and a second 13 s clip at that cadence, sent beside the first. The still river must carry the meaning alone (B2's current lines; each block's price line). In the note's A1 row: "flux relevés toutes les 10 à 30 secondes".

### Low

- **B5** The phone and reduced motion lose the flows: only the 24 h counts remain. Fix: a "Last events" list of five lines (the same lines as the planned `aria-live` region) on the phone and under reduced motion.
- **B6** The origin line is cut in four of eight blocks at 1440 ("Recorded by hand · no ve…", "trend_break_4h · Commo…"): the bot is half of "where it comes from". Fix: two lines from the `mid` tier; a short bot tag below it.
- **B7** ▲ and ▼ mean two things: a signal's side ("XAGUSD ▼ Short", "last refusal: AAPL ▲ bad_timing") and a result ("+$65.00 ▲"). Fix: LONG and SHORT chips for a side; ▲ and ▼ for results only.
- **B8** The stage's lower third is empty at both sizes while blocks are 164 px wide; "1 signals", "1 markets open". Fix with B1; plural rules.
- **B9** The story's small untruths: PORTFOLIO stays $10,453.61 after the close while the reserve's cells total $10,518.61; the booked result equals the estimate to the cent; the level turns stressed at the instant the front arrives, as if the calendar drove it. Fix: update the bar; book +$63.80; separate the two events by a second.

---

## 5. The French note, sentence by sentence

Voice, length and the six OKs are right. These need changing before it goes:

| # | The note says | Verdict | Replace with |
|---|---|---|---|
| 1 | "Où regarder : ... `shots/anduin.webm` ... `anduin_mock.html` ... `Anduin.dc.html`" | Scratchpad paths mean nothing to him | Name what he receives: the video, the still, board 7 of the preview |
| 2 | "Adresse /anduin/, ouverte depuis Barad-dûr et la barre latérale" | Barad-dûr (E1) is not built and is not in A1's prerequisites | "ouverte depuis la barre latérale, et depuis Barad-dûr dès qu'elle existe" |
| 3 | "Un panier est aussi grand que ce qu'il contient" | Today it grows with the number of blocks (B1) | After B1: "Un panier grossit avec le volume REAL qu'il porte ; vide, il n'est qu'un trait" |
| 4 | "son origine (ton ticket, ou telle règle de tel bot)" | True; the mock adds a signal number bots do not have (A7) | "(ton ticket et son signal, ou telle règle de tel bot ; le numéro du signal d'un bot n'est pas enregistré aujourd'hui)" |
| 5 | "RESERVE (le disponible et l'utilisé d'eToro, avec leur âge)" | eToro is read in one world at a time | "... pour le monde où ton compte est branché ; l'autre affiche un tiret" |
| 6 | "UPSTREAM · 24 H (signaux arrivés, pris, refusés, et pourquoi)" | No dated count of refusals exists (N7) | "signaux arrivés et pris sur 24 h ; pour les refus, le dernier motif connu de chaque symbole, bot par bot" |
| 7 | "jade pour un gain, corail pour une perte" | Only REAL closes booked at eToro's price | "... pour l'argent réel soldé au prix d'eToro ; DEMO, PAPER et estimations restent en blanc" |
| 8 | "Le niveau de stress que les bots suivent déjà" | Only with `crisis_mode` on | Add: "si l'interrupteur crisis_mode est éteint, la page écrit « not measured » et le fleuve reste plat" |
| 9 | "Un marché fermé gèle son panier" | Not indices, not crypto | "(forex, actions, matières premières). Les indices ne gèlent pas : leur CFD se négocie presque sans arrêt" |
| 10 | "Coût au repos : un quart de cœur" | 0.24 to 0.30 over three runs, no graphics card | "entre un quart et un tiers de cœur, sur une machine sans carte graphique" |
| 11 | A1: "La vraie page sur tes données, en lecture seule" | True; silent on the delay | Add: "les flux sont relevés toutes les 10 à 30 secondes" |
| 12 | OK 6: "Une seule échelle pour les trois mondes : un bloc PAPER peut être aussi haut qu'un REAL" | Hides that a large DEMO or PAPER row shrinks his REAL blocks and swells the basket (A1) | "**L'échelle.** Proposé : l'argent réel fixe l'échelle et la taille des paniers ; DEMO et PAPER sont rangés à part dans chaque panier. Sinon : une seule échelle, où un gros bloc DEMO ou PAPER écrase tes blocs REAL" |

Add one line under "Ce que tu verras": how many positions fit before the rest folds into the table (B3).

---

## 6. Order of work for the fixer

1. B1 with A1 (one change of layout: compact tier, REAL scale, world bands, empty slot). It also settles B3 and B8.
2. A2, A3, A4 in the spec (three rules rewritten, tests named).
3. A6, A7, A8 in the mock (colours, the signal number, the reserve's lines).
4. A5 and A10 (the idle loop, the board).
5. B2, then B4's second clip.
6. A9 in the spec; the note's twelve lines; the lows.
