# The magic layer: Sauron's theme, kept inside the approved look (spec v2, 2026-11-07)

**His words** (on board 1 of the preview canvas, "Couleurs et polices"): "mais garder la thematique initiale pour le design et theme please, you understand that we still feel the magic or something alike, the prestige too..."

**What this answers.** The approved direction stays for the data: crisp figures in a mono face, no glow behind a number, nothing under 11 px, every text at 4.5:1 or better, no fake data. Sauron's identity comes back in the frame: the Eye, the green light, Orbitron, the embers, the moments and the brand screens.

**Version 2.** Two critiques (feel; discipline, performance and truth) reviewed v1. Every finding was checked against the code and the renders, and `changes.md` says what was applied or rejected, and why. The main changes:
- **The embers that would ship are now the embers the board shows.** On the same layout, v1's script lit about an eighth of what the board showed.
  - The v2 script is born in the page's empty space, at about two thirds of the light of main's embers once their fake labels are gone.
  - It dims near words on the void, so they keep 4.5:1.
  - The board's field is seeded from that script's own map of this layout. It lights 7 % (column) to 19 % (void band) more pixels than the script, and the summed light is within 8–10 % (§4.1).
- **Truth before light.** The Eye flares only for a proven fill. The real-money TURN ON never takes the Eye's light. Cards become opaque. Embers only show on pages that prove no figure sits on the void. Orbitron is loaded without digits, so a digit in a title is always drawn in JetBrains Mono. The void's layers are composited, after `background-attachment: fixed` was measured to cost the main thread 2.6× at rest on a slow CPU.
- **The board shows what the S1a commit builds.** It is the approved Positions page plus the magic. The page head and the hero card are a labelled proposal for later (stage S2), and the Ambience control sits in the user menu. Every annotation sits in an opaque dashed frame, so the void holds no word, as on the real page.

Everything here is design. Nothing in any repository or worktree was written. All data in the mock is synthetic.

**Sources read:**
- main (`mainread`, ede54d0);
- S1a (`uis1a`, claude/uis1a b37cde1, `git diff origin/main...HEAD`; line numbers below are b37cde1's). The S1a workflow has since finished at c6f1822; the anchors used here are still there;
- the UI plan spec and the four approved boards;
- the theme map of this workflow, the before and after shots, the Oculus mock, the Eye page spec (Barad-dûr, approved on 2026-11-07).

**Deliverables:**

| File | What |
|---|---|
| `magic/Signature.dc.html` | The board for the canvas, in board 4's format, 1440 × 900. Animated with CSS keyframes and SVG SMIL only |
| `magic/shots/signature_1440x900.png` | The board at rest, after every moment has played |
| `magic/shots/signature.webm` | 6.2 s of the board (VP9, 1440 × 900) |
| `magic/shots/moment_*.png` | The three moments at their peak, cropped, at DPR 2 |
| `magic/s1a_magic_changes.md` | The change list: two commits on claude/uis1a, and one small optional commit |
| `magic/magic_fr.md` | The French note for him |
| `magic/changes.md` | Each critique finding: applied or rejected, and why |
| `magic/cost/sv-embers.js` | The ember candidate, v2 |
| Canvas | `"Signature.dc.html":{"x":1520,"y":2240,"w":1440,"h":900,"title":"6 · La signature (la magie gardée)"}`. Slot 5, at (0, 2240), is Barad-dûr's now |

Measurements and tools are listed in §8.

---

## 1. The principle in five lines

1. **Two layers.** The data keeps the approved rules: opaque, mono, crisp, honest. The frame is Sauron's: the Eye, its green light, Orbitron and the embers.
2. **Green is light, not paint.** The Eye's green glows only on what is alive or chosen: the Eye, live dots, the active row, the selected tab, and a hero card's edge while its figure is live. It never sits behind a number, never marks a gain, never surrounds REAL and never lights a control that moves money.
3. **Calm ambience, earned moments.** Embers drift only in the page's empty space, behind opaque cards, at 30 frames a second at most. They are nearly as present as main's embers (about two thirds of their light, §4.1), but slower and without main's fake labels. Light flares once, and only for a proven fill, a close, a new signal or a moved stop.
4. **Prestige is craft.** Orbitron capitals for titles, with their digits in JetBrains Mono. A hexagon Eye that breathes and looks toward the pointer. Hairline edges that catch the light, a void lit from above, and greys tinted toward the Eye's green.
5. **Truth outranks atmosphere.** No invented figure anywhere, not even in the embers, and no figure on the void. Every effect gives way to money controls, stale prices, the lock, dialogs, reduced motion and his Ambience choice.

---

## 2. Faces

### 2.1 Roles

| Role | Face | Size, weight, tracking | Where |
|---|---|---|---|
| Wordmark | **Orbitron** 700 | 16 px, .24em, Eye green with its glow (§3.2) | The brand block |
| Page title | **Orbitron** 600 | 15 px, .16em, capitals, ink-1 | The top bar |
| Section and card titles | **Orbitron** 600 | 12 px, .16em, capitals, ink-2 | Card heads (`.card-title`, `.sv-panel-title`), the day diagram's heading, modal titles, Gollum's title |
| Overlines | **Orbitron** 600 | 11 px, .18–.22em, capitals, ink-3 | Nav section heads; page-head overlines (stage S2) |
| The lock | **Orbitron** 900 for the title, as main; **JetBrains Mono** 400 for the 46 px clock | The clock is a figure, so it takes the number face. Main drew it in Orbitron, and S1a in Inter | The idle lock (`/locked/` keeps its own link and has no clock) |
| Nav rows | **Rajdhani** 600 | 15 px (the base size + 2 at every tier), .02em | The sidebar's page names |
| Brand subtitle | **Rajdhani** 600 | 12 px, .3em, ink-3 | "TRADING INTELLIGENCE", where the brand block shows it |
| Words | **Inter** | As approved: body 13, labels 11 in capitals at .06em, buttons 12 in capitals at .04em | Sentences, labels, table heads, chips, buttons, controls, and money words inside a title |
| Numbers | **JetBrains Mono** | As approved: cells 13, figures 20, hero 28, at 400–500 | Every figure, including the digits of an Orbitron title |
| Share Tech Mono | *none in the shell* | — | Kept where it lives today: the intro (unchanged), and the login, PIN and `/locked/` screens until S2.7 |

**Orbitron rules:**
- Capitals only.
- **It is loaded without digits** (§2.3). A digit inside an Orbitron title is drawn by the next face in the stack, JetBrains Mono, with no template edit. Measured on the board: the probe title "NAS100 · 30D WINDOW #12" draws 15 glyphs in Orbitron and 8 in JetBrains Mono (its 7 digits and one space).
- Never a sentence, a button, a chip, a table head or a money word: BUY, SELL, REAL, LONG, SHORT. A money word inside a title wears the word face (`.sv-plain`). One page title has one today: the Orc page's "LONG"/"SHORT" (`orc_detail.html:3`).
- A symbol inside a title (for example "NAS100 — NASDAQ 100" on the instrument page) keeps Orbitron letters and JetBrains Mono digits. The confusable pairs (0/O, 8/B, 5/S) can then never meet inside one face.

### 2.2 Why JetBrains Mono carries the numbers, measured at 11–13 px

**Method:**
- Every face was drawn white on black by Chrome's own text rasteriser, at DPR 1 (the hard case) and DPR 2.
- The faces are the very Google Fonts files the shell loads.
- **Distinctness** of two glyphs is Σ|A−B| / (ΣA+ΣB) over their pixels, drawn on the same advance and baseline: 0 means the same picture, 1 means no shared ink. It is a pixel measure, not a reading test.
- The worst digit pair is the one a tired eye confuses first.

**Script:** `magic/tools/legibility.js`. **Data:** `magic/fonts/legibility.json`.

| At DPR 1 | JetBrains Mono 400 | Share Tech Mono 400 | Orbitron 500 | Rajdhani 600 | Inter 400 (reference) |
|---|---|---|---|---|---|
| Figure height, px (11 / 12 / 13 px) | **9 / 10 / 11** | 8 / 9 / 9 | 8 / 9 / 10 | 7 / 8 / 9 | 8 / 10 / 11 |
| Digit advance, px | **6.60 / 7.20 / 7.80** | 5.94 / 6.48 / 7.02 | 8.34 / 9.10 / 9.86 (not tabular) | 5.34 / 5.82 / 6.31 (not tabular) | 6.52 / 7.12 / 7.71 (tnum needed) |
| Worst digit pair | **0.162 / 0.201 / 0.181** (0/8) | 0.103 / 0.114 / 0.116 (0/8) | 0.060 / 0.056 / 0.065 (5/6, 6/8, 8/9) | 0.117 / 0.105 / 0.103 (0/8, 5/6) | 0.141 / 0.125 / 0.136 (3/8) |
| Mean digit distinctness | **0.453 / 0.468 / 0.467** | 0.382 / 0.401 / 0.417 | 0.380 / 0.384 / 0.414 | 0.385 / 0.362 / 0.390 | 0.422 / 0.441 / 0.447 |
| 8 vs B | **0.150 / 0.178 / 0.139** | 0.083 / 0.102 / 0.087 | 0.040 / 0.037 / 0.054 | 0.089 / 0.091 / 0.081 | 0.197 / 0.189 / 0.195 |
| 5 vs S | **0.219 / 0.220 / 0.230** | 0.119 / 0.132 / 0.128 | 0.080 / 0.040 / 0.067 | 0.205 / 0.189 / 0.184 | 0.240 / 0.243 / 0.265 |
| At DPR 2, worst digit pair | **0.201 / 0.210 / 0.207** | 0.138 / 0.137 / 0.135 | 0.088 / 0.077 / 0.060 | 0.116 / 0.123 / 0.118 | 0.140 / 0.152 / 0.152 |

**What the table shows:**
- **JetBrains Mono against Share Tech Mono.** At every size JetBrains Mono's figures are 1–2 px taller and 11 % wider. By this pixel measure its worst digit pair is 57 %, 76 % and 56 % more distinct at 11, 12 and 13 px, and its 8/B and 5/S pairs are 60–85 % more distinct.
- **The one pair that goes the other way: 0 against O.** Share Tech Mono's narrower zero wins there by pixels (0.22 against 0.10). JetBrains Mono tells them apart by the mark inside its zero, which this pixel measure undervalues, and a price never puts 0 beside O.
- **Orbitron is the least distinct face for figures.** It confuses 5/6 and 8/9 at a quarter of JetBrains Mono's distinctness, and 8/B at 0.04. That is why the shell loads it without digits.
- **Rajdhani's figures are the smallest** (7–9 px), so Rajdhani carries words only.

**Nav rows: Rajdhani as a drop-in.**
- Rajdhani 600 at 15 px takes Inter 13 px's width within ±1.5 px on the seven longest nav labels. For example, "Operations Center" measures 111.3 px against 112.4 px (`magic/fonts/navwidth.json`), so nothing reflows.
- Its x-height is higher: 7.65 px against 7.10 px. Its caps are 9.65 px against 9.46 px.

The specimen is `magic/fonts/specimen_dpr1.png`.

### 2.3 Loading

**The shell's three font links:**
1. `https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400..700&family=JetBrains+Mono:wght@400..700&display=swap` (unchanged).
2. `https://fonts.googleapis.com/css2?family=Orbitron:wght@400..900&text=<A–Z, the Latin-1 capitals, the title punctuation>&display=swap`. It replaces S1a's `Orbitron:wght@700&text=SAURON%20VISION` subset. The `text=` list holds no digit. The full value is in `s1a_magic_changes.md` C2.
3. `https://fonts.googleapis.com/css2?family=Rajdhani:wght@600&display=swap`.

`text=` applies to a whole request, so Orbitron and Rajdhani need separate links.

**Checked live today:**
- Google answers link 2 with one variable subset (weights 400–900) of **4.9 KB**. Its `unicode-range` holds no U+0030–0039, so the browser never draws a digit in it (`magic/fonts/orb_text.css`, `orb_text_subset.woff2`).
- Rajdhani 600 latin is **15.7 KB**.
- In total, **19.5 KB** more than S1a on a first visit, then cached.
- 400–900 keeps main's lock weights: main's clock asked for 200 and got 400, and its title is 900.
- Share Tech Mono is not loaded by the shell. The intro, `/locked/`, the login and the PIN screens keep their own links.

**Faces named literally.** `_partials/passation_card.html` (included on every page while a hand-over is due) and `dashboard/passation.html` name Orbitron and Rajdhani in their own `<style>`. Once the shell loads those faces, their sentences would render in Rajdhani. They point to the tokens instead, and C2's test reads every `<style>` block and `style=""` attribute of the templates rendered under `base.html`.

---

## 3. Colour and light

### 3.1 The Eye-lit ladder: main's tint at S1a's lightness

S1a's neutrals sit almost exactly on grey (OKLCH chroma 0.006–0.02, hue 164–188). The theme map ranked the green-lit palette fourth in what makes Sauron feel like Sauron. Here every neutral keeps S1a's OKLab lightness, so every contrast stays the same. Each takes the Eye's hue family (160°) at about main's chroma: main's card was chroma 0.025, its border 0.046.

Script: `magic/tools/palette_math.py`, `palette_variants.py`.

| Token | S1a (approved) | Eye-lit | ΔE×100 | Contrast of ink-1 / ink-2 / ink-3 on it (Eye-lit; S1a in brackets) |
|---|---|---|---|---|
| `--sv-bg-0` | #070A09 | **#040B07** | 1.1 | 17.17 / 10.72 / 6.66 (17.07 / 10.61 / 6.63) |
| `--sv-bg-1` | #0C1110 | **#07130C** | 1.6 | 16.37 / 10.23 / 6.36 (16.35 / 10.16 / 6.34) |
| `--sv-bg-2` | #121918 | **#0D1B14** | 1.5 | 15.32 / 9.57 / 5.94 (15.31 / 9.51 / 5.94) |
| `--sv-bg-3` | #182120 | **#14231B** | 1.6 | 14.10 / 8.81 / 5.47 (14.12 / 8.77 / 5.48) |
| `--sv-bg-4` | #1F2A28 | **#1B2C23** | 1.5 | 12.67 / 7.91 / **4.92** (12.70 / 7.89 / 4.93) |
| `--sv-line-1 / -2 / -3` | #1B2422 / #26322F / #36443F | **#14261D / #1D3528 / #2C4739** | 1.8 / 2.3 / 2.2 | (lines: hairlines, card and input borders) |
| `--sv-ink-1 / -2 / -3 / -4` | #E9EFED / #B4C0BC / #8A9894 / #59655F | **#E6F1EA / #ACC4B6 / #839B8D / #55665D** | 0.9 / 1.9 / 1.8 / 0.8 | — |

**What stays the same:**
- The minimum is still ink-3 on bg-4, at 4.92:1.
- The Eye (11.51:1), jade (7.23:1), coral (6.84:1), DEMO gold (10.13:1) and amber (8.60:1) on bg-1 move by 0.03 or less.
- White on REAL red stays 4.94:1.
- Neutral ink stays far from a gain: ink-2 against jade is ΔE 15.4 (S1a 16.6).
- Light mode is frozen, as S1a has it.

`magic/fonts/compare_palette.png` shows the three ladders side by side.

### 3.2 Light sources: the only places the Eye's green may glow

| Source | Light | Ambience | Token |
|---|---|---|---|
| The wordmark | Text glow | Magic, Calm | `--sv-glow-brand-text: 0 0 12px rgba(0,232,104,.45), 0 0 2px rgba(0,232,104,.3)` |
| The Eye mark (brand block) | A soft radial halo; it breathes under Magic (§5.1), stands still under Calm; a flare for a proven fill or a close | Magic (motion), Calm (still) | A radial gradient on `.brand-eye-wrap::before` (not a blur filter); `--sv-dur-breath` |
| The active nav row | A 2 px Eye edge with its glow, a light spill fading to the right (~13 % → 0 over 80 % of the row), the icon in Eye green | Magic, Calm | `--sv-glow-edge: 0 0 8px rgba(0,232,104,.75), 0 0 2px rgba(0,232,104,.9)`; `--sv-spill-active` |
| Live dots: a feed alive, a price LIVE, a component healthy | A static 6 px glow. One dot per page beats (S1a's heartbeat) | Magic, Calm | `--sv-glow-dot: 0 0 6px rgba(0,232,104,.7)` |
| The selected tab or segment | The 2 px Eye underline with a short downward glow | Magic, Calm | `0 4px 10px -6px rgba(0,232,104,.6)` |
| A hero card (stage S2; the kit shows the class) | A 1 px gradient edge on top and a glow **above** it, outside the card. **Lit only while its figure is live**; dark around a REAL marker | Magic, Calm | `--sv-edge-hero`, see §5.2 |
| BUY/LONG and SELL/SHORT controls, hovered or focused | Their side's colour, never the Eye's, **inside their own box** (an inset glow), so nothing next to them changes. Crisp at rest | Magic, Calm | `--sv-glow-up-in: inset 0 0 0 1px rgba(36,181,130,.55), inset 0 0 12px rgba(36,181,130,.22)`; `--sv-glow-down-in` in coral |

**Gone from v1:**
- **The primary-button glow.** `.btn-primary` is also the PIN-guarded TURN ON that arms real money on `/ops/` (`ops.html:129`), and Reserve, Mark withdrawn, Correct and the Save buttons. UI plan §10 says TURN ON is never a cheerful green.
- **The focus halo.** S1a's 2 px Eye outline at 2 px offset stays the focus light. A halo on a money control in focus would be the Eye's green on that control.

**Never lit:**
- a number, a cell, a tile, a chip or the band's quotes;
- a stale, estimated or closed value;
- the REAL family (the chip, the armed pill, the row edge): REAL is a fill, never a light, and the armed pill beats by its dot alone. S1a's focus outline is the one exception, since the armed pill is a link;
- a gain, which is jade text, never the Eye;
- a control that moves money, with the Eye's green: TURN ON, the TAKE TRADE dialog's confirm (`.sv-dialog-btn--go`, neutral until S2.1), CLOSE and CLOSE ALL.

**Off is S1a.** Under Ambience Off, every rule above is off: the shell's computed box-shadows, text-shadows and filters equal S1a's, hover and focus included. S1a's two meaningful beats stay under Off: the live heartbeat and the REAL ARMED dot.

### 3.3 The void: dark gradients behind opaque cards

The void is the page behind the cards.

**What it carries** (`body:not(.light-mode)`, Magic and Calm):
- the **Eye's light from above**: `radial-gradient(900px 360px at 46% -110px, rgba(0,232,104,.10), rgba(0,232,104,.025) 50%, transparent 74%)`;
- a **vignette**: `radial-gradient(140% 120% at 50% 28%, transparent 55%, rgba(0,0,0,.42) 100%)`;
- a static **grain**: an SVG `feTurbulence` tile at 7 %, under the embers.

The grain adds a printed, velvet depth. It is drawn once and never animates. At 7 % it is felt rather than seen. Off removes all three.

**How they are fixed to the viewport.** They sit on two fixed, composited layers: `body::before` (the light and the vignette, z-index −2) and `body::after` (the grain, z-index −1), each with `will-change: transform`. They are never a `background-attachment: fixed` on `<body>`. v1 used that, and the main thread repainted it: on a CPU slowed 4×, it cost 413 ms/s at rest against 157 ms/s for the layers, and the embers fell to 50.6 fps against 60.1 (`magic/cost/cost_layers.json`; the v1-style harness's run is `cost/cost_bodyfixed.json`).

**Cards become opaque.** S1a kept main's card gradient on `.card, .stat-box, .metric, .signal-item`: `linear-gradient(160deg, var(--bg-card) 0%, rgba(8,20,16,.92) 60%, rgba(6,14,10,.88) 100%)` (`sauron.css:2925-2926`). Its lower 40 % is 8–12 % see-through, on 496 elements in 92 templates, and only 10 `.sv-panel` are opaque (counted at b37cde1). C4 makes them bg-1 in dark mode. Over the void the gradient's stops read within about 6 levels (of 255) of bg-1, so the look barely moves: the lower edge of a card lightens slightly.

**No figure on the void.** A text that holds a digit never sits on the void or on a translucent ground. This is measured on every page that shows embers (§4.2).

**Words that do sit on the void** (`.sv-on-void`; the S2 page head, `.sv-page-head`, wears it):
- They wear the void's own **dark halo**: `text-shadow: 0 0 3px, 0 0 8px, 0 0 14px` in bg-0. This is the Eye page's rule for its road names. It is a shade, not a glow, and the figure tests accept a text-shadow whose every colour is bg-0.
- **And the embers dim near them.** An ember within 18 px of such words is held to alpha .18 (§4.1). The halo alone is not enough at v2's brightness: one ember at alpha .55 behind an 11 px ink-3 line still brought it down to about 2.4:1.
- An age or source line in a page head (stage S2) sits on an opaque bg-1 pill instead, since it holds a figure.

**Measured with the embers behind them** (`magic/tools/void_contrast.js`, `board/void_contrast.json`): see §4.1.

### 3.4 Whose money, unchanged

- REAL is the solid #CC3A40 with white at 4.94:1, the only solid red.
- DEMO is the gold outline #D6BC5E. PAPER is the grey outline.
- None of them glows.

**A finding for S4.** The approved §3.8 "last-price tag" (a down-fill box #E5484D with ink-1 text) measures 3.36:1 with S1a's ink-1 and 3.38:1 with the Eye-lit ink-1 (3.91:1 in white) at 11 px. It is also a solid red fill outside the REAL family. S4 should draw it outlined: coral on bg-2, 6.40:1. The v2 board has no chart, so it no longer shows this.

---

## 4. The ambience

### 4.1 The embers, kept on work pages in a calm form

| | main today | S1a | v1 candidate | **v2 (this layer)** |
|---|---|---|---|---|
| Embers and ash | 240 + 50 | not displayed | 56 + 12 | **one ember per 6,000 px² of visible void, at most 56; ash one per 30,000, at most 12**. On the board's layout: 35 + 7, for 211,680 px² of void |
| Where they are born | anywhere | — | anywhere (so ~7 visible at once) | **in the page's void**: the screen's rows weighted by how much of them no card covers (the void map) |
| Speed, left to right | 15–75 px/s | — | 6–22 px/s | **7–23 px/s** |
| Brightness | alpha .06–.38, a pulse, halos of 2.5× and 4.5× | — | alpha .05–.22 | **alpha .18–.55**, pulsing to 60 %, one glow sprite whose halo is as wide as main's 2.5× glow |
| Trails | 40 % of the larger embers, 8–17 points | — | none | **none** |
| Labels and prices | 24 invented tickers on 35 % of the larger embers, 8–9 px | removed | none | **none, ever**: the script draws no text |
| Near words on the void | over them | — | over them | **held to alpha .18 within 18 px** of `.sv-on-void` and `.sv-page-head`, rising back to its own alpha at 18 px |
| Where they show | over the whole page, cards 8–12 % transparent | — | behind cards | **behind opaque cards, on pages that opt in** (§4.2) |
| Frame rate | every frame (60) | — | 30 at most | **30 at most** |
| Backing store | full screen | — | a quarter of the screen's pixels | **a quarter of the screen's pixels** (half per side; 1/16 of the device pixels at DPR 2) |
| Drawing | ~1,400 arc fills + 100 rects + ~100 texts a frame | — | one `drawImage` per ember | **one `drawImage` per ember** from three sprites drawn once |

**The void map.** On load, on resize, after a scroll and after a live swap (`sv:live-swapped`), the script samples the screen on a 24 px × 24-column grid with `elementFromPoint`.
- A point is void when nothing from the hit element up to `<body>` paints a background.
- The rows are weighted by their void share, and embers are born in them. An ember whose row became covered moves, faded in, to a void row.
- **It never holds the main thread long.** On the board's layout a map is 912 hit tests and 15–33 ms of work, in 4–6 idle slices of about 4 ms. A hit test that must first rebuild its data can stretch one slice: up to 22 ms once at load, and 4.5–12 ms after a scroll (`tools/map_probe.js`).
- A live swap that leaves the page's shape alone (its height, the scroll, the window) costs no map at all: 0 hit tests, measured.
- A page with no void draws nothing and schedules no frame.

**Measured light** (`magic/tools/ember_lit.js`; `board/ember_lit_final.json` for the scripts, `board/ember_lit_board.json` for the board):
- The same layout was shot without and with embers, 8 instants per page load, and 4 loads for the random scripts (32 instants). The board's field is fixed, so it needs one load.
- "Lit px" counts the pixels whose luminance rose by more than 4 of 255. "Light" is the summed rise / 1000.
- "The void band" is the clear strip below the table (y 570–626).

| Source, on the board's layout | Main column: lit px (light) | The void band: lit px (light) |
|---|---|---|
| v1 candidate (alpha .05–.22, born anywhere) | 152 (1.8) | 62 (0.7) |
| **v2 (`cost/sv-embers.js`)** | **1,123 (17.0)** | **392 (5.9)** |
| main's embers without their fake labels and trails | 1,626 (28.9) | 599 (10.8) |
| main's embers today, labels and trails included | 2,336 (37.7) | 724 (11.9) |
| **the board's CSS field** | **1,197 (15.6)** | **466 (6.5)** |

**Reading:**
- **v2 puts about two thirds of the light of main's embers on the page**, once main's invented labels and trails are taken away: 1,123 against 1,626 lit px over the column, 392 against 599 in the void band. They are slower, and they are only where the page is empty.
- About a third of main's light today came from its fake tickers and trails, which do not come back.
- v1 was about one seventh of v2. That is the gap the first critique found between v1's board and v1's script.
- **The board shows what would ship.** Its field lights 7 % more pixels than the script over the column (8 % less light), and 19 % more in the void band (10 % more light). Its CSS sprites are drawn at full resolution, where the script uses a quarter-size store, so the board's alpha is lower to give the same light.
- The variation between loads is wide, since the script places its embers at random: 578–1,608 lit px over the column.

**Words on the void, with the brightest ember behind them** (`magic/tools/void_contrast.js`, `board/void_contrast.json`). The board's void holds no word, so three test lines were placed on the harness's void band, in the S2 page head's roles, with the halo. For each line, the script's largest sprite was drawn at points 56 px apart along it, with its centre on the line and 6, 12 and 18 px above and below. Each case was shot with and without the ink, and the brightest non-ink pixel within 2 px of the glyphs was read:

| Test line (with the dark halo) | The brightest ember undimmed (alpha .55) | **As the script draws it (held to .18 near words)** |
|---|---|---|
| Overline, Orbitron 11 px, ink-3 | 2.32:1 | **5.31:1** |
| Lead sentence, Inter 15 px, ink-1 | 6.08:1 | **13.84:1** |
| Source line, Inter 11 px, ink-3 | 2.20:1 | **5.25:1** |

So the halo alone does not hold an 11 px ink-3 line at v2's brightness. With the dimming, every line holds 4.5:1 or better. The script's own `alphaAt` gave .18 inside each line's box and .55 at 18 px from it.

### 4.2 Where they show: pages that opt in

S1a's cards were not opaque, and some pages put figures on the void. For example, the instrument page's live price `.dtl-last` and its symbol sit in `.detail-header`, which has no background (`instrument_detail.html:7, 28-29`; `sauron.css:682`). So the canvas does not show on every page that extends `base.html`:
- A page opts in with `{% block sv_embers %}data-sv-embers{% endblock %}` on `<body>`. The CSS hides the canvas everywhere else, and the script schedules nothing there.
- **First:** `/positions/` and `/command/`.
- **A page may opt in only when C4's measured test passes on it:** no text holding a digit sits on a translucent ground or on the void, and every word on the void carries `.sv-on-void` (the halo, and the embers dim near it).
- A page that has not opted in keeps the void's light, vignette and grain, without embers.

### 4.3 When they stop

Each pause was checked in Chrome on the v2 harness. The figure is the number of frames drawn in 2 s.

| State | How it is detected | Frames drawn in 2 s |
|---|---|---|
| Running (Magic, the page opted in) | — | 57 (the 30 fps cap) |
| Tab hidden | `document.hidden`, `visibilitychange` | **0**; 60 again within 2 s of showing |
| PIN lock up | `sv:pin-locked` / `sv:pin-unlocked` (idle-lock.js) | **0**; 60 after unlocking |
| A dialog holds the page (TAKE TRADE, a close, CLOSE ALL) | `body.sv-scroll-locked` (sv-overlay.js), watched by a MutationObserver | **0**; 60 after closing |
| Ambience Calm / Off | `body[data-sv-ambience]` | **0 / 0**, the canvas cleared; 60 back on Magic, no reload |
| The page has not opted in | no `data-sv-embers` on `<body>` (the CSS hides the canvas) | **0**; 60 once it opts in |
| Reduced motion | `prefers-reduced-motion: reduce` | **0**: one still frame drawn (1,243 lit px), no `requestAnimationFrame` asked |

Also checked: the script draws no text (no `fillText`, `strokeText` or `.font`), and its stats ring stays at 240 entries after 8,000 frames.

### 4.4 What it costs, measured

**Conditions:**
- The harness pages are built from the v2 board itself, with the demo moments stopped and the production structure:
  - the void's light and vignette are on a fixed, composited `body::before`, and the grain on a fixed, composited `body::after` (§3.3);
  - the layout sits above them;
  - the canvas is fixed full-screen under the layout, as `base.html` places `#particles-canvas`.
- Headless Chrome in this container: 4 Xeon cores at 2.1 GHz, **no graphics card** (software raster and compositing), 1440 × 900, DPR 1.
- Each page was measured over two 6 s windows with the pointer moving.
- **CPU** is Chrome's whole process tree (utime + stime from `/proc`), in cores.
- The absolute numbers are this machine's. Without a graphics card most of the cores go to software compositing, which a GPU removes, so **the order carries over, not the ratios**.

Script: `magic/cost/measure_cost.js`. Data: `magic/cost/cost.json` (v1's is `magic/v1/cost_v1.json`).

| Page (the v2 harness) | fps | Main thread, ms/s | CPU, cores | Ember work per drawn frame, mean / p95 | Canvas calls per drawn frame |
|---|---|---|---|---|---|
| A flat page (the floor) | 60.1 | 19 | 0.07 | — | — |
| S1a's shell at rest (one heartbeat, the armed dot) | 60.0 | 50 | 0.12 | — | — |
| Magic at rest, no embers (the breath, the light, the void's two layers) | 60.0 | 58 | 0.12 | — | — |
| **+ main's embers, verbatim** | 56.8 | **691** | **0.87** | **4.39 / 9.95 ms** | 1,450 arc + 1,450 fill + 100 fillRect + **113 fillText** + 50 save/restore |
| **+ the calm embers v2 (Magic)** | 56.5 | **189** | **0.37** | **0.18 / 0.30 ms** at 28.7 drawn frames/s | **49 drawImage** + 10 setTransform + 1 clearRect |
| The calm embers without the 30 fps cap | 58.7 | 318 | 0.57 | 0.26 / 0.35 ms at 58.7/s | the same |
| Ambience Calm | 59.8 | 48 | 0.09 | — | — |
| Ambience Off | 60.0 | 42 | 0.10 | — | — |
| The board's CSS ember field (41 embers, 8 ash, 98 CSS animations; the final board has 35 and 7) | 59.8 | 221 | 0.49 | — | — |
| A 3 s scroll, with the embers (2–3 remaps; the longest map slice 12 ms) | 58.2 | 177 | 0.45 | — | — |
| The same scroll under Off | 60.0 | 65 | 0.14 | — | — |
| CPU slowed 4×: Magic at rest, no embers | 60.1 | 229 | — | — | — |
| CPU slowed 4×: main's embers | **19.5** | 1,009 | — | 19.8 / 38.9 ms | — |
| CPU slowed 4×: the calm embers | **59.5** | 467 | — | 0.91 / 2.0 ms | — |

**Reading:**
- **On this machine the calm embers cost 0.25 of a core** over Magic at rest. Main's embers cost 0.75 over the same base: **three times as much**.
- **The main thread is 3.6× less busy** (189 against 691 ms/s). The time the embers add drops 4.8× (132 against 634 ms/s).
- **The work per drawn frame drops 25×** (0.18 against 4.39 ms). The calls per frame drop from about 3,200 to 60.
- **On a CPU four times slower,** main's embers drag the page to 19.5 fps. The calm ones keep it at 59.5.
- **The 30 fps cap saves a third of the CPU** (0.37 against 0.57).
- **Scrolling** with the embers costs 0.31 of a core more than under Off, with 2–3 remaps in 3 s.
- **CSS embers cost more than the canvas** (0.49 cores, 221 ms/s). The board uses them only because a board may not run a script.
- **Magic at rest costs what S1a at rest costs here** (0.12 cores; main thread 58 against 50 ms/s): the void's two layers, the breath and the static light are cheap once composited (§3.3).
- The page's own frame counter read 56–57 fps with either ember field in this run, against 60 at rest; the calm field read 59.5 in its 4× run and 59.8 in the final re-measure below. The branch's measurement on a machine with a graphics card is the one to trust (C5).

**Re-measured on the final board** (35 embers and 7 ash, the wider glow, the dimming near words; `cost/cost_calm_final.json`): Magic 0.36 cores and 193 ms/s, against 0.13 and 68 ms/s at rest; 0.17 / 0.30 ms of ember work per drawn frame at 30 frames/s, with 42 `drawImage`, 9 `setTransform` and 1 `clearRect`; on a CPU slowed 4×, 59.6 fps. The table above was measured with 41 embers and 8 ash, before the board's annotations moved into frames.

**Two costs found in v1, still true:**
- **SMIL in production is ruled out.** With the board's SMIL pupil and a heartbeat on all 11 live dots, the shell at rest cost 0.39–0.43 cores and 156–181 ms/s. SMIL alone added about 100 ms/s of main thread. Production moves the pupil on pointer events (§5.1), never with SMIL.
- **S1a's rule stays: one heartbeat per page.** Every other live dot is still.

### 4.5 Stronger where the page is the brand

| Screen | What it keeps | Notes |
|---|---|---|
| **The intro** (`intro.html`) | **Kept exactly**, his words: faces, background Eye, 70 linked particles, the logo's glow and float, the 14 loading steps, timing, Skip | Only its destination changes: it leads to Barad-dûr instead of the Operations Center (`/command/`), as the Eye page's spec has it, approved |
| **The lock** (idle lock and `/locked/`) | Its own atmosphere, as main has it: grid, Eye, the PIN iris choreography | No embers: the work page's field pauses under the lock (`sv:pin-locked`). The title returns to Orbitron 900; the clock takes JetBrains Mono (§2.1); `.il-sub` and `.il-standby` rise from 9 and 10 px to 11 px |
| **Barad-dûr**, the Eye page (approved) | The whole Eye, which breathes and looks toward the page under the pointer (up to 16 px across), its drift and its event particles, as its spec has them | **This is where the big Eye lives now.** It does not come back behind the work pages, where it sat behind the figures. The page takes this palette and these faces and obeys the Ambience choice |

**One question for him.** The intro's 14 flying tickers show invented prices (`Math.random()`, every 1.5 s). "Keep it exactly" says they stay. The French note asks once whether he wants the figures dropped from those labels and nothing else changed.

### 4.6 His choice: Ambience Magic, Calm or Off (default Magic)

**Where it lives:**
- **Stored per user** on his profile, beside `theme_mode`: `TraderProfile.ambience`, values `magic`, `calm` or `off`. It comes in its own commit (C8) with its migration.
- **Read** through `{% get_ambience %}` onto `<body data-sv-ambience>`.
- **Set** in the user menu, beside the theme switch, by a POST with CSRF.
  - The page changes only after the server answers 200 with the saved value. On a failure it keeps the old value and says "Not saved".
  - Other open tabs follow on their next page load.
- **Display only:** no engine, bot, Orc or gate module may read it, and a scan test keeps it so.

| | **Magic** (default) | **Calm** | **Off** |
|---|---|---|---|
| Embers and ash | The calm field, 30 fps, on pages that opt in | none | none |
| The Eye mark | Breathes (6 s), looks toward the pointer, flares for a proven fill or a close | Still halo; for a proven fill or a close, one soft glow, no ring | As S1a: no halo, no flare |
| Static light (wordmark, active row, live dots, tabs, a live hero's edge) | Lit | Lit (still light is not motion) | As S1a |
| The void | Light from above, vignette, grain | The same, still | Flat bg-0 |
| Moments | Edge lights that travel, the icon's light, S1a's washes | Edge lights fade in place, S1a's washes | S1a's 600 ms washes only |
| Faces and palette | Orbitron, Rajdhani, Inter, JetBrains Mono; Eye-lit | The same | The same: the theme is not an ambience |
| Infinite animations on a work page | Heartbeat, armed dot, the Eye's breath (3) | Heartbeat, armed dot (2) | The same (2) |
| Under reduced motion | 0 infinite animations (S1a's two beats stop too); the embers draw one still frame | 0 | 0 |
| CPU here, no graphics card (§4.4) | 0.37 cores | 0.09 | 0.10 |

---

## 5. Prestige details

### 5.1 The Eye mark, alive in the top bar

The brand block is the top bar's left end: the 44 px row above the sidebar (S1b). The mark is today's inline hexagon Eye.

**At rest (Magic, and only where motion is allowed):**
- A soft radial halo behind it breathes over 6 s: opacity .5 → .95, scale .88 → 1.06.
- The breath animates transform and opacity only, so the compositor runs it. Main's halo used `filter: blur(6px)`; a gradient replaces it.
- It sits inside `@media (prefers-reduced-motion: no-preference)`.

**It looks toward the pointer.** Main's background Eye followed the pointer, and the theme map ranks that first among Sauron's signatures:
- **The iris is clipped to the almond** (a `clipPath` of the lid's own path) and moves up to **2.4 units of 24 across and 1 down**: about 2.8 px and 1.2 px at 28 px. v1's 0.9 units was about 1 px, which nobody would see.
- The move is coalesced to one transform per frame, and only while the pointer moves, so a still pointer costs nothing.
- It is off under reduced motion, outside Magic and in light mode.
- In the board, a slow SMIL glance and a slow pupil dilation stand in for this, because a board may not run a script.

**The big Eye** that watches is Barad-dûr's (§4.5). The mark is its echo on every page.

**It flares for a proven fill or a close:**
- The halo goes to 1.6× at full strength and fades over 1.2 s, and a 1 px ring opens to 1.9× once.
- **The trigger is the platform's own announcement, `sv:eye-event` `fill_open` or `fill_close`, never `sv:position-changed`.** That event also fires when the order *may* have reached the broker (`base.html:3590`), when an answer was lost (`:3880`), when the lookup stayed unanswered (`:3940`) and when a close's answer was lost (`:3998`). Only the dispatch at `:3627` is a confirmed open.
- **`fill_open` must be a fill.** Today it is also pushed for an order the broker holds unfilled: a WORKING entry (`manual_trade.py:3823`, `asset_engine/base.py:7597`). So `fill_open` flares only when one of these proves the fill:
  - its payload says `"working": false` (C10 adds the field);
  - or this tab's own answer for that trade id says so: the confirmed answer `{ok: true, trade_id}` without `working`, or the lookup's `{state: "booked", trade_id}` without `working`. The socket event waits up to 4 s for that answer.
  
  Without either proof there is no flare: until C10, a bot's fill does not flare.
- One flare per trade id, ever, and at most one per 1.5 s.
- `fill_close` is pushed only once a close is booked (`asset_engine/base.py:4488`, `pending_closes.py:1459`, `reconcile_asset.py:1023`, `nl_trader.py:184`). It flares at 60 %.
- Never for a quote, a notification or a refresh.

### 5.2 Hero cards (stage S2; the kit shows the class)

- **What it is:** the page's one headline figure, such as the instrument's live price, the Operations Center's day, or the Oculus verdict.
- **Its card:** opaque bg-1 with a line-3 border.
- **Its edge:**
  - a 1 px gradient on the top edge (Eye at 85 %, a paler 95 % centre, fading to nothing at both ends);
  - a soft glow **above** the edge, outside the card. The 14 px above it never hold a figure, and a test checks that.
- **Lit only while its figure is live.** A stale, closed, reference or estimated value (`.sv-fresh--stale`, `--closed`, `--ref`, `.sv-est`) puts the light out: `:has()` drops the edge and the glow.
- **Never around a world marker.** REAL is a fill, never a light. A card that holds `.sv-world--live`, `.sv-venue--live`, `.tk-venue--live`, `.sv-armed-pill` or a REAL chip (c6f1822 made six more labels REAL chips; C3 names them) is never a hero. CSS drops the light, and a static test forbids the pairing in templates.
- **No corner marks.** v1's four were a HUD cliché and not Sauron's card style; main's cards use a top line.
- **In the board:** the labelled inset "A proposal for later · your OK", with the same XAUUSD price lit when live and dark when stale.

### 5.3 Headers

- **Page title:** Orbitron in capitals in the top bar. S1a adds no subtitle.
- **Page head on the void (stage S2, his OK):**
  - an Orbitron overline;
  - one lead sentence in Inter 15, with no figure in it;
  - on the right, the source and age on an opaque bg-1 pill, since they hold a figure.
  - It costs about two table rows at 1440 × 900: in v1's board the table header sat at y 329, against 232 on approved board 2.
- **Card titles:** Orbitron 12 px at .16em in ink-2. A count beside a title is a mono bubble.

### 5.4 Moments: light only when something real happened

| Moment | The real event, and its proof | What lights, once | How long |
|---|---|---|---|
| **A fill** | `sv:eye-event` `fill_open`, proven (§5.1) | The Eye flares. A light runs along the new row's bottom hairline, from its left edge to the action cell's left edge. The row is `tr[data-sv-position-row]` holding `[data-sv-close-trade="<trade_id>"]`, on the swap that brings it, within 60 s | 1.2 s; 0.9 s |
| **A close** | `sv:eye-event` `fill_close` | The Eye flares at 60 %. The row leaves on the next refresh, as today: no light runs on a row that is going | 1.2 s |
| **A new signal** | The rail's live swap (`sv:live-swapped`) brings a card that was not on the rail and whose `data-created` is later than the rail's high-water mark: the newest `data-created` seen at load and after each swap, so only the server's clock is compared. At most 3 per swap. BRING BACK and a filter change mark nothing | A light runs along the card's top edge. The dock's signal icon lights once, behind the icon; the count's bubble stays opaque above it | 0.9 s; 1.2 s |
| **A stop moved** | `sv:levels-saved` (`detail.trade`), fired after the server repainted the level | S1a's own neutral wash on the stop cell (S4 later steps the chart's level line) | 0.6 s |
| A close stuck at the broker | `close_pending` | Nothing magic: the amber state chip and its words | — |

**Forbidden.** A rule broken here is a defect, and each line has a test (`s1a_magic_changes.md`):
- a glow, gradient or translucency behind a figure. S1a's 600 ms neutral wash is the one allowed translucency;
- any text glow but the wordmark's. The dark halo of words on the void is allowed (§3.3);
- flashing: nothing repeats faster than once a second, and nothing blinks;
- an infinite animation beyond the heartbeat, the armed dot and the Eye's breath;
- a moment that changes a figure's colour, counts up, moves or resizes a control, paints inside a button's box, plays twice for one event, or plays on a refresh that brought no proven event;
- light on a stale, estimated or closed value (a stale price never gets a live dot);
- the REAL red as light, the Eye's green around REAL or on a control that moves money, the Eye's green on a gain, a side's glow at rest or outside its control's box;
- a particle above the content, or any label, symbol or figure in the ambience;
- embers while a dialog is open, the lock is up, the tab is hidden, on a page that has not opted in, or under reduced motion (one still frame).

---

## 6. What it means for S1a (summary; the full list is `s1a_magic_changes.md`)

Two commits on claude/uis1a, after the S1a workflow in flight finishes and before its PR opens, and one small optional third. Money direction: none. Size M. Each change has its test written first and a measured acceptance.

**Commit 1, display only: "the magic kept".**
1. **C1. Tokens:** the Eye-lit ladder; light, edge, spill, void and grain tokens; the faces (`--sv-font-display: "Orbitron", "JetBrains Mono", "Inter"`).
2. **C2. Faces:** three font links, with Orbitron loaded without digits; Orbitron on a whitelist of title selectors; Rajdhani on the nav rows; the lock's weights and its 11 px floor; literal faces in templates moved to the tokens.
3. **C3. Light on the frame**, under Magic and Calm: the wordmark, the active row, live dots, tabs, the hero class (lit only while live, never around REAL), and the side glows (hover and focus only, inset only).
4. **C4. The void and opaque cards:** light from above, vignette, grain; `.card`, `.stat-box`, `.metric` and `.signal-item` opaque; the dark halo; a measured test that no figure sits on the void or on glass.
5. **C5. Calm embers on pages that opt in:** `sv-embers.js` v2 replaces main's ember script; the caustics and the fake log lines go.
6. **C6. The Eye mark alive:** breath, gaze, and a flare for proven fills.
7. **C7. Moments** on existing events, each with its proof.
8. **C9. S1a's tests and the kit**, updated deliberately.

**Commit 2: "Ambience Magic, Calm or Off".** C8: the profile field and migration `portfolio/0020`, the view, the control. The deploy sheet says "migrate before restart".

**Commit 3, optional, may become its own PR: "the fill event says whether it filled".** C10 adds `working` to both `fill_open` pushes, and a `fill_open` when a held order fills.

---

## 7. What it means for the three designs in flight

- **Oculus (O1).**
  - **The hero is the VERDICT cell alone, lit only while it reads "● all clear".** It is never the whole status strip, which holds the REAL MONEY cell and its armed chip, and never "⚠ N need you", which keeps its amber.
  - The cycle's LIVE dots and active station carry the light. Station and card titles are in Orbitron, with their digits in JetBrains Mono.
  - The figures, tables and money blocks stay as O1 has them.
- **Operations Center (OC1).**
  - The Day of Sauron loop is the frame's centrepiece: Orbitron step names, and a light that runs along an arrow only when that step really ran (from `sv-day-live`'s own data, never a timer).
  - A hero only for a card without a world marker. The counts stay mono on opaque tiles.
  - `/command/` is one of the first two pages with embers, once C4's test passes there.
- **Barad-dûr (E1), approved, "/" leads to it.**
  - The strongest ambience after the intro: the whole Eye breathing and looking toward the page under the pointer, and its drift and event particles, which already follow these rules. It obeys Ambience: Calm stills the drift, Off stops it.
  - **It has no sidebar** (eyehall spec "Standalone: no sidebar"). Its frame faces are:
    - panel titles in Orbitron 12;
    - stage pills (SEE, THINK, DECIDE, ACT…) in Orbitron 11;
    - station names in Rajdhani 600, since they are that page's navigation;
    - figures in JetBrains Mono.
  - **Its spec's line "Orbitron for the wordmark only" (eyehall_spec.md §1, the rules) must be amended to this** when E1 is built. This workflow cannot edit that file.

---

## 8. Files, scripts and measurements

All files are under `/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad/magic/`.

**Board and renders:**
- `Signature.dc.html`, built by `tools/build_board.py`. It is seeded, so it is reproducible. Its ember field is seeded from `board/voidmap.json`, which `tools/voidmap.js` reads from the shipped script running on this very layout.
- `tools/check_board.js`, the board's own checks, at rest and at each moment's peak (the animations paused at the instant):
  - 226 texts, at rest and at each of the three peaks: 0 under 11 px, 0 under 4.5:1;
  - 97 texts that hold a digit, 0 lit, 0 on a translucent ground, 0 on the void;
  - 0 Orbitron texts with a money word; the probe title draws its digits in JetBrains Mono (Orbitron 15 glyphs, JetBrains Mono 8);
  - no text with a digit in the 14 px above the lit hero;
  - at the fill's and the stop's peaks no button box changes; at the signal's peak only the dock's signal button does, which is that moment's own light;
  - no sideways scroll; no script but the format's own `support.js` tag and DCLogic block; 0 console errors; no request left the box.
- `tools/void_contrast.js` (words on the void against the brightest pixel around their glyphs), `tools/ember_lit.js` (the light per ember source).
- The animations: CSS keyframes (the breath, the moments, one heartbeat, the armed dot, 42 drifts, 35 sways, 7 spins) and two SMIL animations (the iris's glance and the pupil's dilation).
- Renders: `tools/render_board.js` writes `shots/signature_1440x900.png`, `shots/signature.webm` (6.2 s, VP9, from the first painted frame) and the three moments at their peak (`shots/moment_1_new_signal.png`, `moment_2_fill.png`, `moment_3_stop_moved.png`).
- Fonts are served from local copies, offline (`tools/shot2.js`): Orbitron as the digit-free subset Google answered live, with Google's own `unicode-range`. No other request left the box.
- v1's files are kept in `v1/`.

**Faces:**
- `tools/legibility.js` → `fonts/legibility.json`, `fonts/specimen_dpr1.png`;
- `tools/font_metrics.py` → `fonts/font_metrics.json`;
- `tools/navwidth.js` → `fonts/navwidth.json`;
- `fonts/orb_text.css`, `fonts/orb_text_subset.woff2` (the digit-free Orbitron, fetched live), `fonts/raj600_latin.woff2`.

**Palette:**
- `tools/palette_math.py`, `tools/palette_variants.py` → `fonts/palette_math.json`, `fonts/palette_variants.json`, `fonts/compare_palette.png`.

**Cost:**
- `cost/sv-embers.js` (the v2 candidate);
- `cost/build_cost_pages.py` → `cost/pages/*.html`;
- `cost/measure_cost.js` → `cost/cost.json` (§4.3, §4.4, with the pause checks and the scroll test).
