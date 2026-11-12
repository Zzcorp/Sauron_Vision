# Anduin: what was done with the critique (2026-11-12)

Each of the 30 findings of `critique.md` was checked again, by the code at main `15dd487` (read-only checkout) or by a measure on the mock, before anything was changed. Nothing in the repository was edited.

**Result: 30 confirmed and applied. Four parts of their proposed fixes were rejected, with reasons (R1 to R4 below). Three things are specified and not drawn (L1 to L3).**

## 1. Rejected parts, and why

| # | In the critique | Rejected because | Done instead |
|---|---|---|---|
| R1 | B3: "B1's compact tier gives 30 blocks or more at 1440x900" | Measured, it does not, once A1's own fix is in: each world's band has a head, the annex has its own box, the river is 12 px taller and a card's foot holds three lines | The capacity is measured and said: the forty-row book draws 21 of 40 at 1440 x 900 (the 7 real rows as full blocks, 3 other blocks, 11 one-line rows; 19 fold) and all 40 at 1920 x 1080. A row tier was added to get there |
| R2 | B1 fix 1: "Height linear between [the floor and the cap]" | It contradicts B1's own test (fix 5: above the floor, heights in the ratio of the values within 2 %). Linear from a 48 px floor keeps a 48 px offset: 24 to 1 would be drawn 6 to 1 | Height = cap x value / scale, never under the floor. Measured: EURUSD 255 px, GBPUSD 151 px, ratio 1.689 against 1.685 for the values |
| R3 | B1 fix 3: an empty family as a slot of "about 96 px" | "COMMODITIES" in the title face needs 104 px and "STOCKS & ETFS" two lines | The slot is 124 px |
| R4 | A20: "use 33.3" as the loop's threshold | A plain threshold of 33.3 ms draws 20 frames a second whenever a 60 Hz callback arrives 0.1 ms early | One draw per slot of a thirtieth of a second: 30 a second is a ceiling whatever the display's rate |

Also placed elsewhere than proposed: B1 fix 4's per-world bars sit in each band's head (with its chip and its sum), not in the basket's head. A8's "exposure · at work" is the band's sum plus an `at work` line in the card's foot.

## 2. The 30 findings

| # | Sev. | Checked by | Applied in | What changed |
|---|---|---|---|---|
| A1 | HIGH | the mock's `build()` (one `vmax` over every world) | mock, board, spec §0, §1.2, §4.2, §5.1, §7, note | Real money sets the one scale; the solid card holds REAL only; DEMO, PAPER and no-venue rows sit in a dashed annex, one band per world with its own sum and bar; a block above the scale is capped and marked `›`. Probe: a DEMO row of $500,000 changes no REAL block; the card holds no other world. OK 6 reworded |
| A2 | HIGH | `base.py:4909-4920`, `:5309`, `:7615`; `skips.py:29-195`; M1 §5.2, §5.4 | spec §1.4, §3, §8 (tests); mock (a `waiting` count) | A closed list of refusal codes; `hold`, `already_open`, `cooldown` counted apart; `no_price` and `suspect_mark` only for a symbol the bot does not hold; one evaporation per (config, symbol, code) and per signal |
| A3 | MED | `skips.py:161-183`; the mock's labels and counts | mock, board, spec §1.4, §3 | The chip names the bot and its world; counts split by world; the mock's numbers no longer form a sum; "four readers · they do not add up" in the card |
| A4 | MED | the mock's `priceMote.end()`; arithmetic on the paths | mock, spec §1.5, §3, §5.1, §8 | The age is printed from the stamp at the release; a mote enters at its basket's gate and takes 1.2 s at most. Probe: 1.2 s on every block at 1440 and 1920; the landing follows the age by 1.20-1.23 s |
| A5 | MED | the mock's `frame()` | mock, spec §5.3, §8 | The loop stops when nothing moves; one timer wakes it. Measured: idle 0.056-0.059 of a core against 0.053 for the still page, 0 frames asked |
| A6 | MED | CSS specificity (`.fl .m`, `.ln .m` over `.up`); the sprites | mock, spec §3, §5.1 | Money is ink squares, 3 px; jade or coral on the figure, for REAL closes booked at eToro's price only. Probe: the close chip and Downstream's REAL figures compute to jade, PAPER's to ink |
| A7 | MED | `base.py:7507-7520`, `:6732`; `manual_trade.py:3245` | mock, board, spec §1.1, note | No signal number on a bot row, anywhere; a ticket keeps its own |
| A8 | MED | arithmetic on the mock's book | mock, board, spec §1.1, §1.3, §5.1 | REAL pool: `on Sauron $1,540.53`, `outside $2,861.57 · 2 positions ›`; `at work` in each card's foot; `+1 at eToro, not on Sauron ›` in two feet. Probe: used = on Sauron + outside before and after the story |
| A9 | MED | `horde.py:2167-2169` | spec §1.1, §1.9, §5.3 | `board()` is not cached: the age is the payload's `as_of`; Anduin's reader keeps its own 10 s; a marks-only poll |
| A10 | MED | `tools/build_board.js` (SMIL, a rule that stops CSS only) | board, tool, spec §5.3, §6 | Three motes and one token on CSS `offset-path` in steps; one rule hides them under reduced motion. Measured: 0.13 of a core and 0 layouts (was 0.32 and 60); under reduced motion 0.001-0.004 and the frames no longer differ |
| A11 | MED | the note, line by line | note | All twelve lines replaced; the capacity line added |
| A12 | LOW | the mock's ribbon | mock, spec §1.7, §5.5 | Each band carries its print's name in its title; the table lists the prints |
| A13 | LOW | the mock | mock, spec §1.7, §5.1 | `calendar read 2 h ago`; `vol p41 · 3 inst · 11 Nov`; one pill `book read N s ago` for the payload |
| A14 | LOW | `position_care.py:358-420`, `:184` | mock, spec §1.7 | MSFT is touched: `touches 7 open`; inside the window `· 6 lit by the care` |
| A15 | LOW | the mock's CSS; `magic_spec.md` §3.4 | mock, spec §5.1 | A loss on the track is a coral hatch with an outline |
| A16 | LOW | the mock's geometry | mock, spec §2.1, §5.1 | Feeders drop in the gutter at the block's right; on a REAL block the top-edge light stops 12 px short of the red edge |
| A17 | LOW | the mock's CSS | mock, spec §3, §5.1 | A forming block opens its frame, then its lines stand at once; a closing block's lines leave at once; chips appear and leave at full strength |
| A18 | LOW | `market_stress.py:455-461`; `why_no_trade.py:193-194`; `risk_levels.py:593-594` | mock, spec §1.4, §1.7 | The crisis sentence whole, on two lines; a refusal prints its code and its stored detail, in the engine's own wording |
| A19 | LOW | `base.py:4488-4492`, `pending_closes.py:1459-1465`, `regime.py:13-21`, `horde.py:1347`, `skips.py:158` | spec §1.4, §1.5, §1.6, §1.7 | The five nits corrected |
| A20 | LOW | the mock; the measure | mock, spec §3.2, §5.4, note | Under the lock the shell's three loops stop (0 running animations); the phone's switches are 44 px; the frame cap by slots (R4); the note's cost sentence |
| A21 | LOW | the spec | spec §3, §5.2, §8 | A signal born while its market is shut waits in the ice; a return after a hidden spell is a fresh load |
| B1 | HIGH | the mock's `F` and `C` | mock, board, spec §2.1, §4.2, note | A 48 px floor, lines by tier, a bar at every block's foot, the slot, per-world bars (R2, R3) |
| B2 | MED | the mock's `ampAt()` | mock, board, spec §3.1, new still | A 28 px band with three lines; outlines toned by the level; frost over the whole basket; the front's band in the air. Measured height of the middle line: 2.2, 4.2, 5.7 px |
| B3 | MED | forty rows injected | mock, spec §2.4, §9, note, new still | The row tier, the fold, the order (smallest first, real money last), the capacity (R1) |
| B4 | MED | `etoro_quotes.py:97`, `venue_mark.py:107` | mock, second clip, spec §5.1, §6, note | `?cadence=real` and `shots/anduin_real_cadence.webm` |
| B5 | LOW | the phone and reduced-motion renders | mock, spec §2.5, §5.5, note | "Last events": five lines on the phone, a still chip under reduced motion, an `aria-live` region, a table |
| B6 | LOW | the stills | mock, spec §2.1 | The origin on two lines: the rule, then the bot |
| B7 | LOW | the mock's labels | mock, spec §3, §5.5 | LONG and SHORT chips for a side; ▲ and ▼ for results only |
| B8 | LOW | the stills | mock | "1 signal", "1 market open"; the empty part of the stage now means "little engaged" |
| B9 | LOW | arithmetic on the story | mock, spec §6 | PORTFOLIO follows the reserve's reading; the close is booked at +$63.80, not the estimate's +$65.00; the front arrives at 21:00, the level turns at 21:15 |

## 3. Added beyond the critique (to be read by the reviewer of the next round)

- **The scale never shrinks by itself.** With a scale tied to "the largest REAL value now", closing the largest position would resize every block. The scale is set at the layout, printed with its time in a pill, grows at once for a larger real position, and is refitted by a click. Probe: after EURUSD closes, the scale and every other height are unchanged.
- **Outside the real card, a block is cut down before any is hidden**: to the floor, then to a one-line row; only then does the smallest fold. Real money is never cut down. This is what took the forty-row still from 11 drawn to 21.
- **A re-lay** (a fill in an empty family, a close) keeps the scale and the block width and eases in 0.4 s; the block width is found as if every empty family already held a column.
- A new block class named `over` met the sky's "overline" class and set a capped block in capitals; the clipped-line check caught it; the class is `capd`.

## 4. Specified, not drawn in the mock

- L1. Several outcome chips for one signal judged by several bots (A3 fix 2): the story has one bot per signal.
- L2. A21's two cases.
- L3. `order_in_doubt`'s coral chip.

## 5. Measures on the final mock

Headless Chrome, 4 Xeon cores at 2.1 GHz, no graphics card, 1440 x 900, DPR 1. CPU is Chrome's whole process tree. Two runs (load 0.6-0.9, then 1.0-1.8).

| Page | Run 1, cores | Run 2, cores | Frames asked /s | Drawn /s | Work per drawn frame |
|---|---|---|---|---|---|
| A flat page | 0.001 | 0.003 | n/a | n/a | n/a |
| The river stopped (`?motion=0`) | 0.053 | 0.053 | 0 | 0 | n/a |
| Idle, every feed quiet | 0.056 | 0.059 | 0 | 0 | n/a |
| At rest, today's real price pace | 0.105 | 0.112 | 13 | 6.7-6.8 | 0.17-0.20 ms |
| At rest, the mock's pace | 0.193 | 0.222 | 43-44 | 22 | 0.11 ms |
| The story, looping | 0.324 | 0.357 | 51 | 25 | 0.39-0.42 ms |
| At rest, 1920 x 1080 | 0.273 | 0.296 | 43 | 22 | 0.11-0.12 ms |
| CPU slowed 4x, the story | n/a | n/a | 49-50 | 25 | 1.41-1.55 ms |

First edition, same harness: 0.24-0.30 at rest, 0.32-0.385 in the story, 0.107 idle (the critique's run).

Pauses, frames drawn in 2 s: hidden 0; locked 0, with 0 running animations; table open 0; reduced motion 0 frames asked and 0 running animations; the phone 0.

Board: 0.13 of a core, 0 layouts a second (style recalculated 60 times a second by the CSS animations); under reduced motion 0.001-0.004, still.

Checks on every render (no page error, no request but the fonts, no text under 11 px, none under 4.5:1, no clipped line, no box past its region, no overlap): all empty for the page at rest at 1440 x 900 and 1920 x 1080, the phone, the three moments, the end of the story, the forty-row book, the three weather levels, the four groupings, both sizings, a sixteen-row book and an empty book. `work/probe_final.json` holds the probes named above.

## 6. Limits that remain

- The machine has no graphics card: the order of the costs carries over, not the figures.
- The 1280 px tier is not measured.
- The board was rendered with scripts disabled in the Signature board's frame; it was not opened in the canvas itself, and it now relies on CSS `offset-path`.
- At 1440 x 900 a paper-heavy book folds: 19 of 40 on the stress book, and a basket whose real block fills its column shows its other rows as a count only.

## 7. Files

- `anduin_spec.md`, `anduin_mock.html`, `Anduin.dc.html`, `canvas_entry.json`, `anduin_fr.md`, `critique.md`, this log.
- `shots/`: `anduin_1440x900.png`, `anduin_1920x1080.png`, `anduin_390.png`, `moment_1_signal_refused.png`, `moment_2_taken_money_block_forming.png`, `moment_3_stressed_frost_dry_close.png`, `weather_calm_stressed_crisis.png`, `anduin_40_positions_1440x900.png`, `anduin.webm`, `anduin_real_cadence.webm`, `board_anduin_1440x900.png`.
- `tools/` (render, measure, board, switches), `final_work/` (the first edition's copies as `*.before.*`, the patch scripts, `stress.js`, `probe.js`).
