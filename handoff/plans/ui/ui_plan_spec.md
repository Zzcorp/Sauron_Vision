# Sauron Vision UI plan: Bloomberg × TradingView, in Sauron's identity

Spec, 2026-11-06. Based on mainread `d81a035` (after PR #88), the three maps of this workflow (visual system, charts, screenshots) and the 49 + 45 screenshots under `scratchpad/uiplan/`. This is a plan; nothing is built here and nothing in any worktree was written.

Every stage below is one pull request that ships alone and changes display only. The trading engine, the bots, the Orcs, the gates, the ticket's execute path and every money switch see exactly what they see today. Every commit message states "Money direction: none. Display only."

---

## 0. In one page

**The direction.** Sauron stays dark, green-eyed and itself, but it stops decorating the space behind the numbers.
- **From Bloomberg:** terminal discipline. Dense rows, every number in a tabular mono face, small-caps labels, a status bar of live cells, nothing moving unless a value moved.
- **From TradingView:** clean neutral greys, a calm sans for words, the chart as a full-height canvas with a one-row toolbar, an in-pane legend and a drawing rail, and popovers that never hide what you are looking at.
- **From Sauron itself:**
  - the hexagon Eye and the Orbitron wordmark;
  - the void with a whisper of green;
  - the lore (the Horde, the Orcs, the Council, Gollum);
  - the house's honesty rules (unknown is a dash; whose price, how old; REAL money is the only solid red mark).
- **The Eye's green has one job.** It marks what is live and what you have selected. It is no longer the colour of profit, buttons and links all at once.

**The stages.**

| Stage | One PR | What he will see | Starts when |
|---|---|---|---|
| S0 | Six display defects | The rail no longer hides /positions/; ticket prices in the right face; the signals chart draws; TradingView credited; dark scrollbars; readable Orc links | Now; needs no approval |
| V | Preview page (no PR) | The palette, the faces and ten components on synthetic data, to approve | Now |
| S1a | Foundation: tokens, faces, kit | Every page at once: calm background, opaque panels, Inter for words and JetBrains Mono for numbers, nothing under 11 px in the shell, gains and losses in their own colours, one look for buttons, tables, chips, menus and dialogs | V approved |
| S1b | Shell layout | About 120 px more height for content; one market band; a 32 px status bar; Gollum, the Eye and the Horde docked; the rail a real column; compact nav with one icon family | `claude/railfilters` and `claude/pnltruth` merged |
| S2.1–S2.8 | Page by page, one PR per page group | The pages he uses most, rebuilt on the kit: ticket and instrument, positions, home, signals and portfolio, cockpits, money settings, login and lock, then the long tail | S1b; each page after the branch that touches it |
| S3 | Responsive, complete | Every page right at 1280, 1440, 1920 and 2560; tablet usable; phone usable (bottom sheets, stacked tables, touch-size money buttons) | S2.1–S2.4 |
| S4 | Charts, TradingView-grade | A full-height chart, one-row toolbar, legend in the pane, clean axis tags, scrollable pinned cards, smooth under fast ticks; small charts restyled | S1a and `claude/pnltruth` merged |
| S5a | Drawing tools (last) | Rectangles, trend/horizontal/vertical lines, rays, channels, Fibonacci, text, long/short box; select, drag, style, delete, undo; Sauron style | S4 |
| S5b | Drawings kept on the server | His drawings follow him to every browser, on every timeframe | S5a |

**What we need from him.**
1. Approve the palette, the faces and the calm background on the preview page.
2. Confirm the page order of S2.
3. Keep or retire light mode.

---

## 1. Inputs and constraints

**His words (2026-11-06, verbatim):**
- (1) "ameliore le design peu etre, plus haut de gamme, elegant". Reference: "un smart melange de bloomberg et trading view sous sauron".
- (2) "quand on click sur un signal faire que le dessous de popup soit mieux placer pour voir le contenu dessous, faire que scroll possible sur click de ce dernier par en hover etc". Being built in `claude/railfilters`.
- (3) "ameliorer responsive complet etc".
- (4) "Ajouter rectangle, lignes et design de ces derniers etc... comme trading view in sauron style". Last.
- (5) "sombre, surtout sur ordinateur, dessins en dernier".

**What the maps measured (the problems this plan fixes):**

| Finding | Evidence | Fixed in |
|---|---|---|
| No design system: 7,621-line `sauron.css` of appended layers, 82 template `<style>` blocks, 3,059 inline styles, no type/space/shadow scale | map 1 §0.1 | S1a, S2 |
| The brand colour is the profit colour: `--accent` #00e868 drives brand, `.btn-primary`, links, focus and `.up` | `sauron.css:17`, 1962, 3394 | S1a |
| 409 hard-coded `rgba(0,232,104,…)`, five reds, six golds | map 1 §0.3 | S1a (shell), S2 (pages) |
| Ambient noise behind data: grid drift, globe-eye, circuit SVG, 240 embers and 50 ash flakes carrying **fake tickers and fake prices**, caustics, two fake log paragraphs, 51 infinite animations, cards 8–12 % transparent | `base.html:119-401`, 3468-3756, 5678-5679; `sauron.css:2811`, 3928-3991 | S1a |
| Type too small and in the wrong faces: 39–56 % of text under 11 px at 1280; Orbitron's wide digits on money; the deal ticket's bid/ask in Arial | map 1 §0.5 | S0 (Arial), S1a |
| Labels at `--text-muted` #3a6850: 3.1:1 contrast | measured | S1a |
| The right rail covers /positions/ (44/280 px) and /portfolio/ (159 px) | `sv-close-advice.css:66` | S0 |
| Nothing scales above 1440 px; paragraphs 1,918 px wide at 2560 | map 1 §0.7 | S1b, S3 |
| First content line at y=184 at every desktop width; reading height 555 px of 800 at 1280 | map 1 §0.8 | S1b |
| Floating controls sit on content at every width: Gollum, the Eye, the Horde, COUNCIL/ACTIVITY tabs, edge toggles | map 1 §0.9, shots 01–13 | S1b |
| Numbers in no single format: 8-decimal quantities and prices, `floatformat:4` next to `{% px %}`, raw feed tags ("yfinance_public") as labels | shots 03, 07, 08, 09 | S1a (tags), S2 |
| /signals/ throws "Chart is not defined" | map 1 §9 | S0 |
| Chart: two-row toolbar at 1440, stacked axis tags, 9–10 px legends, fixed 420 px height, pinned card not scrollable | map 2 §3, §12 | S4 |
| lightweight-charts licence: no TradingView attribution link anywhere | map 2 §1 | S0 |

**Work in flight (what each branch touches in the display layer):**

| Branch | State | Display files it touches |
|---|---|---|
| `claude/railfilters` (b5a62a9) | 2 commits; point 2 built | `base.html` head (adds `sv-rail.css` at 113), bottom-band SIGNALS cell (1157-1185), rail markup (1474-1510), popup positioner and dismiss JS (1661-2090), portals (4316-5250); new `static/css/sv-rail.css`; `signal_rail_items.html`, new `signal_rows_compact.html`, `live_region.html` |
| `claude/pnltruth` (62a2d20) | built, reviewed | `base.html` 852-1050 (PORTFOLIO and OPEN P&L cells); `chart_widget.html` (svHoverCards, ~1348); `_command_portfolio.html`, `_position_summary.html`, `instrument_detail.html:267`, `portfolio_overview.html`, `positions_list.html`, `investor/_panel_body.html`; `sv-close-advice.js`, `sv-horde.js` |
| `claude/ticketnet` (d823b82) | building | `base.html` 1857-3580 (the TAKE TRADE script) |
| `claude/etbudget` | rebasing | no display file |
| `claude/orcs2b` (007f7e6) | building | `ai_models.html`, `orc_detail.html` |
| `claude/usedfix` + WIP U3 | U3 unfinished | `treasury.html`, `short_proofs.html`, `positions_list.html` (U3), `sv-horde.js` |
| eToro-grade feed (spec only) | F1 next | F4: positions/portfolio/command templates, eye `add()`; F7: `base.html` `onmessage`/`applyTick`/rail match/paused chip, new `sv-venue.js`, `sv-instrument-live.js`, `deal_ticket.html`, `core/context_ui.py` |
| Designed, not started | — | Worlds C1–C3 (REAL and DEMO side by side on the ticket, second PIN), Orders at a price P1–P5, TPO and volume profile (chart), Orcs O2c/O2d pages |

**House rules that bind every stage:**
- Display only. Each commit says "Money direction: none".
- Never weaken a test or drop an assertion.
  - A test that pins a *look* is updated to pin the new look, with the reason in the commit.
  - A test that pins a *meaning* (REAL is the only solid red fill, unknown is an em-dash, a stale ticket stops printing a price, the PIN is asked) stays as it is.
- The repository is public. Screenshots, fixtures and tests use synthetic data only. Never his account, positions or figures.
- Faces come from Google Fonts only. No broker call, no model call, no API key anywhere in this work.
- The platform keeps every feature: the Horde, Gollum, the Council, Activity, Ask Sauron, the tour, the lock, light mode (frozen, §3.10). They move; they do not disappear.

---

## 2. The direction, concretely

### 2.1 What we take from each

| Source | We take | We leave |
|---|---|---|
| Bloomberg | Density (32 px rows, 13 px base); every number in a tabular mono face; small-caps labels; brightness, not colour, for hierarchy; a bottom status bar of live cells; keyboard first; black void | Amber everywhere; the retro look; function-key jargon |
| TradingView | Neutral layered greys; a calm sans for words; the chart as a full-height canvas; one-row toolbar with menus; legend inside the pane; axis tags; a drawing rail on the left; popovers that stay out of the way; crosshair culture; consistent up/down colours | Blue as the brand; ads-style density in the margins |
| Sauron | The hexagon Eye and Orbitron wordmark; the near-black void with a green whisper; the eye-green as the colour of "live" and "selected"; the lore; the honesty markers (whose price, how old, REAL red, em-dash for unknown); the atmosphere on the lock, login and intro screens | Neon glow on every edge; fake tickers and logs behind real data; sci-fi faces on numbers |

### 2.2 Ten rules

1. **Nothing moves on a work page unless a value moved or he acted.** Two exceptions: the live heartbeat dot, and the armed pill's beat (real money armed). Atmosphere lives on the brand moments: lock, login, intro, empty states.
2. **Panels are opaque.** No translucency, gradient or glow behind a number.
3. **One colour, one meaning** (§3.9). Colour marks state, polarity and whose money. Buttons carry words; only the actions that buy or sell (LONG/SHORT, BUY/SELL, and TAKE TRADE in its signal's side) carry a market colour.
4. **Colour never works alone.**
   - A gain carries its sign and a ▲.
   - A world chip carries its word.
   - A warning carries ⚠ and a title.
   - A freshness dot carries its age.
5. **Numbers are mono, words are sans.** A number that is data (cell, chip, tile, axis, ticker, button) uses the number face. A number inside a sentence stays in the sentence's face.
6. **Nothing under 11 px, anywhere.** Text roles meet 4.5:1 contrast on the surface they sit on.
7. **Truth over decoration.** No count-up on money, no flash that changes a number's colour meaning, no price shown as fresh when it is not. A button never moves under the pointer when a price ticks.
8. **The left edge of a row belongs to its money world** (the REAL edge). Selection uses the background, never that edge.
9. **Hover enhances, never gates.** Every fact in a popover is reachable by click or tap (railfilters' rule, kept everywhere).
10. **Desktop first, phone usable.** Pages are designed at 1440, checked at 1280, 1920 and 2560, and must not break at 390.

---

## 3. Palette (dark)

Values were checked with the dataviz validator (`validate_palette.js`, OKLab ΔE×100, Machado CVD simulation). Contrast ratios are WCAG 2; APCA Lc is in brackets. Scripts: `scratchpad/uiplan/spec_tools/contrast.mjs`, `de.mjs`.

### 3.1 Surfaces and lines (all opaque)

| Token | Hex | Use |
|---|---|---|
| `--sv-bg-0` | #070A09 | The void: page background, chart canvas, input wells |
| `--sv-bg-1` | #0C1110 | Cards, panels, sidebar, rail, table body |
| `--sv-bg-2` | #121918 | Raised: popovers, dialogs, sticky table heads, toolbars, status bar |
| `--sv-bg-3` | #182120 | Controls, row hover |
| `--sv-bg-4` | #1F2A28 | Selected row, pressed control |
| `--sv-line-1` | #1B2422 | Hairlines between rows |
| `--sv-line-2` | #26322F | Card and input borders |
| `--sv-line-3` | #36443F | Strong borders, hover borders |

### 3.2 Ink

| Token | Hex | On bg-0 / bg-1 / bg-4 | Use |
|---|---|---|---|
| `--sv-ink-1` | #E9EFED | 17.1 / 16.4 / 12.7 (Lc 96) | Values, primary text |
| `--sv-ink-2` | #B4C0BC | 10.6 / 10.2 / 7.9 (Lc 67) | Secondary text |
| `--sv-ink-3` | #8A9894 | 6.6 / 6.3 / 4.9 (Lc 45) | Labels, captions, axis text (today's `--text-muted` #3a6850 is 3.1:1) |
| `--sv-ink-4` | #59655F | 3.3 / 3.1 / 2.4 | Disabled and placeholder only; never information |

### 3.3 Identity: the Eye

| Token | Hex | Use, and only this |
|---|---|---|
| `--sv-eye` | #00E868 (today's accent, kept) | The logo and wordmark; the Eye (Ask Sauron); the live dot (feed alive, price LIVE, component healthy); the focus ring (2 px, offset 2 px); the selection marker (active nav bar, active tab underline, checked box) |

Never on a number, never as a button fill, never as body or link text. Its contrast is 11.6:1 on bg-1.

### 3.4 Market polarity

| Token | Hex | Contrast on bg-1 | Use |
|---|---|---|---|
| `--sv-up` | #24B582 (jade) | 7.26 (Lc 51) | Gains, LONG/BUY text and outlines, up arrows |
| `--sv-down` | #FF6B6E (coral red) | 6.87 (Lc 49) | Losses, SHORT/SELL text and outlines |
| `--sv-up-fill` | #1FA374 | 6.2 on bg-0 | Up candles, up bars, up volume (at 35 %) |
| `--sv-down-fill` | #E5484D | 5.1 on bg-0 | Down candles, down bars, down volume (at 35 %) |
| `--sv-up-wash`, `--sv-down-wash` | 14 % mix of up/down | — | Price flash background, BUY/SELL hover |

- **Zero and unchanged** use ink-2. **Unknown** is the em-dash in ink-3.
- **Up is not the Eye.** #24B582 against #00E868 measures ΔE 15.9 under normal vision and 14.8 deutan, so they stay apart. #2DBD87 failed at 13.9.
- **Up and down are balanced** (Lc 51 against 49), so neither shouts.
- **Red/green under deutan** is ΔE 6.3. That is the floor band, legal only with the sign and arrow (rule 4).

### 3.5 Whose money (the approved convention of 2026-09-30, kept)

| Token | Look | Meaning |
|---|---|---|
| `--sv-real` #CC3A40 with `--sv-real-ink` #FFFFFF | **The only solid red fill on the platform**: the REAL chip, the armed pill, plus a 3 px inset edge on a real-money row | Real money |
| `--sv-demo` #D6BC5E | Gold outline chip | A broker's demo account |
| `--sv-paper` = ink-3 | Grey outline chip | Sauron's simulator |

White on #CC3A40 is 4.94:1. Today's #E83030 gives 4.29, under 4.5 for an 11 px chip. A test enforces that no other selector paints a solid fill in `--sv-real` or in any red.

### 3.6 Status

| Token | Hex | Form it always comes in |
|---|---|---|
| `--sv-warn` | #F29B38 | A box with a left bar, ⚠ and a title, or a dot with words. Never a bare amber number |
| `--sv-danger` | = `--sv-down` | ERROR/FAILED: a dot with words; an error box with ⨯ and a title |
| `--sv-ai` | #A48BFF | Text a model wrote, AI spend, the Orcs' minds |
| "OK / running" | the Eye dot | "Sauron sees it alive" |

Blue is no longer a status. Neutral information uses ink-2 with an ⓘ.

### 3.7 Price source and age badges (aligned with the feed spec §5.4 grades)

Anatomy: a 6 px dot, then the source in human words (Inter 11 px, ink-2), then `·`, then the age (mono 11 px, ink-3). The title gives the full sentence. Example: `● eToro · 12 s`.

| Grade (feed spec) | Dot | Words | The value itself |
|---|---|---|---|
| LIVE | Eye, filled | `eToro · live` | Normal |
| RECENT | ink-2, filled | `eToro · 12 s` | Normal |
| STALE | warn, filled | `eToro · 3 min` | ink-3 (shown as stale) |
| CLOSED | ink-3 ring, hollow | `eToro · closed` | Normal (it is the close) |
| NONE | — | `no price` | em-dash |
| Reference (an outside quote, F5/F7) | ink-3 square, hollow | `Binance · 18 min · reference` | Its own slot, never the main cell |
| Paused (his socket to Sauron) | — | global warn chip `live prices paused` in the topbar | Every dot turns hollow |
| Estimate (pnltruth's `pnl_words`) | — | `≈` before the value, plus an `estimate` chip (ink-3 outline); the line under it names the price and its age | Normal |

- Sources print as names (eToro, Binance, OANDA, Yahoo, Finnhub, paper), never as tags. "yfinance_public" becomes "Yahoo". The mapping lives in one template filter and one JS map.
- Freshness never recolours a number. Only STALE dims it.
- The feed spec's own rules decide when a badge degrades (degrade at once, hold 5 s, recover on the second confirmation). The kit only draws them.

### 3.8 Chart colours

**Categorical** (asset classes, strategies, any nominal series), in this fixed order:

| Slot | Hue | Hex |
|---|---|---|
| 1 | blue | #3987E5 |
| 2 | orange | #D95926 |
| 3 | violet | #9085E9 |
| 4 | yellow | #C98500 |
| 5 | magenta | #D55181 |

- **Validated.** On bg-1 and bg-0 every check passes. The worst adjacent pair is magenta↔yellow: CVD ΔE 13.2, normal 19.3. The donut's wrap-around pair (magenta↔blue) gives ΔE 15.9 / 26.5.
- **Excluded on purpose.** Green and red belong to polarity. A sixth series folds into "Other".
- **No mixing.** A categorical chart never also carries up/down meaning (dataviz rule). Legends are always present for 2 or more series.

**Polarity charts** (P&L by symbol, R histogram, direction donut) use up-fill and down-fill, with a neutral ink-3 midpoint.

**Chart chrome:**

| Element | Value |
|---|---|
| Canvas | bg-0 |
| Grid | ink-1 at 5 % |
| Axis text | ink-3 in the number face, 11 px. Today it is `--text-muted` at 3.15:1, in generic `monospace` |
| Crosshair | ink-3, dashed |
| Last-price tag | up-fill or down-fill box, ink-1 text |

- **Position lines:**
  - entry: ink-1, 1 px solid, with its LONG/SHORT + qty label;
  - stop: down, 1 px dashed;
  - target: up, 1 px dashed;
  - soft stop: ink-3, dotted.
- **Signal dots** use up/down.
- **Levels.** The `--lvl-*` tokens are re-stepped from the categorical slots in S4.

### 3.9 One colour, one meaning

| Colour | Means | Never means |
|---|---|---|
| Eye green #00E868 | Live, alive, selected, focused, Sauron's mark | Profit, "go", a button |
| Jade #24B582 | Up, gain, long, buy | Healthy, on, brand |
| Coral #FF6B6E | Down, loss, short, sell; errors (with icon and words) | Real money, "off" |
| Solid red #CC3A40 | REAL money | Loss, danger, delete |
| Gold outline #D6BC5E | DEMO money | Warning |
| Amber #F29B38 | Warning, stale | Demo money, a gain |
| Violet #A48BFF | A model wrote or spends it | A series in a gain chart |
| ink-1 to ink-4 | Hierarchy, neutral state (OFF, PAPER, CLOSED) | — |

**Known collisions and their mitigation (computed):**
- **Amber against gold** (ΔE 8.3 normal, 4.0 deutan). The forms differ: a warning is a box with ⚠, DEMO is an outline chip with its word.
- **Coral against amber** (13.4). A loss is a signed number; a warning is a box.
- **Coral against solid red** (8.8). A loss is text; REAL is a filled chip with white text.

Red/green under deutan rests on rule 4 (signs and arrows).

### 3.10 Old tokens re-pointed in S1a; light mode frozen

S1a re-points the old names in `sauron.css:6-45` so every page changes at once. The old values are restated under `body.light-mode`, so light mode computes the same colours as today (§15, decision 3).

| Old token | Old value | Becomes |
|---|---|---|
| `--bg-void`, `--bg-primary` | #030806, #060e0a | bg-0 |
| `--bg-secondary`, `--bg-card` | #081410, #0a1a14 (with an 8–12 % transparent card recipe at 2806-2857) | bg-1, opaque |
| `--bg-card-hover` | #0e2218 | bg-3 |
| `--border`, `--border-glow` | #133020, #1a4030 | line-2, line-3 |
| `--text-primary`, `--text-secondary`, `--text-muted` | #daf0e6, #7aaa8a, #3a6850 | ink-1, ink-2, ink-3 |
| `--accent`, `--accent-bright` | #00e868, #40ff90 | stays the Eye; S1a moves `.up`, `.sign-*`, `.bullish`, `.tk-long`, `.btn-primary` and links off it |
| `--accent-red`, `--danger` | #e83030, #d03030 | `--sv-down`; the REAL family moves to `--sv-real` explicitly |
| `--success` | #00e868 | `--sv-up` |
| `--warning` | #d89020 | `--sv-warn` |
| `--accent-gold` | #d8b020 | `--sv-demo` |
| `--accent-purple`, `--accent-blue` | #8840d0, #30a0e8 | `--sv-ai`, categorical slot 1 |
| `--font-display` | Orbitron | Inter 600, uppercase, tracking .06em; Orbitron moves to `--sv-font-brand` (wordmark only) |
| `--font-heading`, `--font-body` | Rajdhani | Inter |
| `--font-mono` | Share Tech Mono | JetBrains Mono |

The 409 literal `rgba(0,232,104,…)` keep today's green until their stage: the shell in S1a/S1b, each page in S2, the long tail in S2.8.

---

## 4. Typography

### 4.1 Faces, loaded from Google Fonts only

| Role | Face | Why |
|---|---|---|
| Words (UI) | **Inter**, variable `opsz 14..32`, `wght 400..700` | Built for screens, legible at 11–13 px. The served file carries `tnum` and `pnum` (checked with fontTools). It does not carry `zero`, `ss*` or `case`, so this plan uses none |
| Numbers | **JetBrains Mono**, variable `wght 400..700` | Tabular by construction (every digit 600 units). Its zero has an inner mark, so 0 and O never mix in tickers. U+2212 and the hyphen share one width, so columns align whichever sign is used |
| Wordmark | **Orbitron 700**, subset with `text=` | Identity continuity; the subset file measured 1.1 KB (the Latin files: Inter 73 KB, JetBrains Mono 31 KB) |

**Links (checked live):**
- `https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400..700&family=JetBrains+Mono:wght@400..700&display=swap`
- `https://fonts.googleapis.com/css2?family=Orbitron:wght@700&text=SAURON%20VISION&display=swap`

**What leaves the shell (`base.html:61`):** Rajdhani, Share Tech Mono and full Orbitron. The standalone screens keep their own links until S2.7.

**Fallbacks:**
- words: `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;
- numbers: `ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace`.

### 4.2 Roles

| Role | Face, weight | Case and tracking |
|---|---|---|
| Body, cells, controls | Inter 400 (500 for emphasis) | Sentence |
| Labels, table heads, card titles | Inter 600 | UPPERCASE, .06em |
| Buttons | Inter 600 | UPPERCASE, .04em |
| Data numbers | JetBrains Mono 400 (500 for emphasis) | — |
| Hero figures | JetBrains Mono 500–600 | −.01em |
| Brand | Orbitron 700 | As today |

### 4.3 Scale and desktop tiers

| Token | Use | 1280–1679 | 1680–2199 | ≥2200 | Phone ≤768 |
|---|---|---|---|---|---|
| `--sv-fs-micro` | Uppercase labels, axis, ages | 11 | 11 | 12 | 11 |
| `--sv-fs-small` | Secondary, chips, table heads | 12 | 12 | 13 | 12 |
| `--sv-fs-base` | Body, cells, controls | 13 | 14 | 15 | 14 (inputs stay 16, as today at `sauron.css:2991`) |
| `--sv-fs-lead` | Card values, dialog text | 15 | 16 | 17 | 15 |
| `--sv-fs-title` | Page and section titles | 18 | 19 | 20 | 17 |
| `--sv-fs-figure` | KPI tile values | 20 | 22 | 24 | 20 |
| `--sv-fs-hero` | Portfolio value, instrument price | 28 | 32 | 36 | 26 |

- **Line heights:** text 1.45; single-line cells 1.25; titles 1.2; figures 1.1.
- **Floor and measure:** 11 px is the floor. Prose is capped at a 72 ch measure (`--sv-measure`).
- **Tiers are tokens.** They are redefined on `:root` by media queries, so every component scales with no per-page work.

### 4.4 Numbers

| Kind | Rule | Today |
|---|---|---|
| Prices | The instrument's own decimals through `{% px %}` (sauron_tags 510-534) and `svDecimals`; no grouping; eToro's digits once the feed knows them (feed F7) | `floatformat:4` in the watchlist (`base.html:1543`, 1559); 8 decimals in the bottom-band dropdown |
| Quantities | New `qty` filter: trimmed, grouped (`20,000`, `0.05`, `1.5`), at most 8 significant digits for crypto | `12.00000000`, `20000.00000000` |
| Money | Grouped, 2 decimals, sign on P&L. Account currency as a symbol prefix (`€10,453.61`); other currencies as a code suffix | Mixed |
| Percent | 2 decimals, sign on changes, no space before % | — |
| R | 2 decimals plus R (`+1.25R`) | — |
| Ages | `12 s`, `3 min`, `2 h`, `3 d` | `timesince\|truncatechars:8` gives "2 minut…" (`signal_rail_items.html:30`) |
| Unknown | em-dash (`measured`, `.sv-unknown`, unchanged) | — |

**Minus sign: we keep the ASCII hyphen.** Two reasons:
1. `sv-flash.js` `numberOf` parses `[+-]` to decide the flash direction, so U+2212 would flash a fall as a rise.
2. Spreadsheets do not read U+2212 as negative, and he may copy figures.

JetBrains Mono aligns the hyphen anyway.

**Ticket inputs.** The float tails in the ticket's stop and target inputs (`0.65030685`) are not touched by this plan. Rounding an input's initial value changes what is sent. It belongs to the ticket's own work (ticketnet, C1–C3), with a test that the level lands on eToro's price grid.

---

## 5. Density, spacing, shape

- **Spacing scale (px):** 2, 4, 6, 8, 12, 16, 20, 24, 32, 40, 48 (`--sv-sp-0` to `--sv-sp-10`).
- **Rows:**
  - compact 28 (tables of 20+ rows, the rail);
  - default 32;
  - with a secondary line 44;
  - touch 44.
- **Controls:** sm 28, md 32 (default), lg 40, touch 44.
- **Card padding:** 16 (12 when compact). Card header 40 px tall.
- **Grid gutters:** 12 (1280–1679), 16 (1680–2199), 20 (≥2200).
- **Radius:** 2 (chips), 4 (controls), 6 (cards, popovers, dialogs), 999 (dots and count bubbles only). This replaces the 3/4/6/8/10/12/20/50 % mix.
- **Borders:** 1 px. Markers are 2 px (focus, selection). The world edge is 3 px.
- **Elevation:**
  - cards have none (a line-2 border on the void);
  - popover: `0 8px 24px rgba(0,0,0,.45)`;
  - dialog: `0 24px 64px rgba(0,0,0,.6)`.
  - There are no glows. The only glow-like effect is the focus ring, which is solid.
- **Z-index:** the existing `sv-overlay.css` ladder (34-50) is kept as is.

---

## 6. Grid and shell

### 6.1 Desktop tiers

| Tier | Width | Sidebar | Rail open | Gutter | Type step |
|---|---|---|---|---|---|
| D1 | 1280–1439 | 232, collapsible to 56 | 300 | 16 | 0 |
| D2 | 1440–1679 | 232 | 300 | 16 | 0 |
| D3 | 1680–2199 | 240 | 340 | 20 | +1 |
| D4 | ≥2200 | 256 | 380 | 24 | +2 |
| Tablet | 769–1279 | 56 (icons) | drawer over the page, 320 | 16 | 0 |
| Phone | ≤768 | off-canvas (today's phone tier) | hidden, phone nav | 12 | phone |

The JS phone boundary (768/769 in `sv-horde.js:64`, `sv-motion.js:55`, `sv-council-band.js:51`, `sv-activity.js:53`, `base.html:5264`, 5611) does not move. The tiers are CSS only.

### 6.2 Shell geometry, before and after

| Part | Today | After S1b |
|---|---|---|
| Topbar | 56 | 44: page title on the left. On the right: UTC clock, sessions N/14, feed pill (where F7's "live prices paused" lands), armed pill, bell, lock, user |
| Data headband + news ticker | 48 + 38, two bands | One 32 px market band. Quotes on the left (railfilters' behaviour kept; arrows in their own gutters, never over a price). The latest headline as one line on the right at ≥1440; a "News N" chip below that width |
| Gap to content | 42 | 16 |
| First content line | y=184 | y≈92 |
| Bottom strip | 60–61, 14 cells, 491/727 px hidden behind arrows at 1280 | 32 px status bar. PORTFOLIO, OPEN P&L, POSITIONS, SIGNALS, BOT, ALERTS, DRAWDOWN and HORDE always show; the rest sit behind "+N" below 1920. Its dropdowns open upward (railfilters made them click-to-open) |
| Gollum | 56 px button over content, bottom left | A 24 px avatar at the status bar's left end. His bubble pops up above the bar for 6 s, then becomes a count dot |
| The Eye (Ask Sauron) | 57 px button over content, bottom right | A 28 px Eye at the status bar's right end; the panel is unchanged |
| The Horde strip | 224–298 × 28 over content | A status bar cell; its panel is unchanged |
| COUNCIL and ACTIVITY tabs, edge toggles | 28 × 112 tabs and 28 × 56 toggles on the content's edges | Icons with badges in a 40 px right dock. Panels open over the rail column, never over the page |
| Signal rail | Collapsed 44 / open 280, covering /positions/ | A grid column: opening it narrows the page. Collapsed, it is the 40 px dock (counts and direction dots) |
| Reading height at 1280×800 / 1440×900 / 1920×1080 / 2560×1440 | 555 / 655 / 835 / 1195 | ≈676 / 776 / 956 / 1316 (+121 px each) |

Wireframe, 1440 × 900, rail closed:

```
+-------------+------------------------------------------------------------+----+
| [eye] SAURON| POSITIONS          11:26 UTC  6/14  [feed]  [bell][lock] OP |    |  44
|             +------------------------------------------------------------+ D  |
| nav, 32 px  | DJ30 43,120.00 -0.12% | FTSE100 ... | ...  || headline ... | O  |  32
| rows,       +------------------------------------------------------------+ C  |
| collapsible |  content: 16 px gutters, 12-column grid, cards             | K  |
| sections    |                                                            |    |
+-------------+------------------------------------------------------------+----+
| (Gollum) PORTFOLIO | OPEN P&L | POS | SIG | BOT | ALERTS | DD | +6 | HORDE (Eye)|  32
+--------------------------------------------------------------------------------+
```

### 6.3 Content grid

- A 12-column fluid grid inside `.page-content`, with the tier's gutter.
- **Data surfaces use the full width; prose does not.** Tables, charts and grids span the page. Prose blocks stop at 72 ch.
- **The extra width at D3/D4 goes into more columns, not wider cards.** Positions analytics and the home sections become 3 columns at ≥1680; KPI strips stop at 8 per row.
- **Components respond to their container** (`container-type: inline-size` on the main column and on cards), so opening the rail reflows them by itself:
  - KPI strip: `repeat(auto-fit, minmax(150px, 1fr))`, capped at 8 per row.
  - Day-of-Sauron tiles: 7 columns at a container ≥1100 px, 4 from 760, 2 below. No title is ever truncated (today 21 ellipses, 31 with the rail open, at 1280).
  - Tables: columns carry a priority (`.sv-p1` always; `.sv-p2` hidden in a container under 1000 px; `.sv-p3` under 1300 px). Hidden columns move into the row's detail line, never off-screen.

---

## 7. Components (the kit)

All of these live in `static/css/sv-kit.css`. They are documented with live samples on a staff-only page, `/design/kit/` (S1a), which the screenshot harness renders at every width.

**Shell**
- **Sidebar:**
  - brand block 44 px (hexagon Eye and Orbitron wordmark);
  - rows 32 px with a 16 px icon and Inter 13;
  - section headers 11 px uppercase ink-3, collapsible, state kept per browser;
  - active row: bg-3, ink-1 text, 2 px Eye bar on the left;
  - unseen dot (nav-activity) in amber.
- **Topbar, market band, status bar, right dock:** as in §6.2.
  - Quote cell: symbol in Inter 12/600 ink-2, price in mono 13 ink-1, change in mono 12 up/down with its sign, freshness dot.
  - Status cell: label 11 px ink-3, value mono 13, sub-text 11 ink-3, all on one line.

**Surfaces**
- **Card:** bg-1, 1 px line-2, radius 6.
  - Header 40 px: title 12 px uppercase ink-2 on the left, meta 11 px ink-3 on the right.
  - Body padding 16. Optional footer.
  - Data cards do not lift on hover; only clickable cards get a line-3 border on hover.
- **Notice:** one component for info (ink-2, ⓘ), warn (amber bar, ⚠) and danger (coral bar, ⨯), with title, words and optional action. It replaces the 8+ page-specific renderings of Django messages and the banner skin (`#svBannerStack` keeps its behaviour).
- **Empty state:** the faint Eye mark (6 %), one sentence, one action. This is where the atmosphere lives on work pages.

**Data**
- **Table:**
  - head: 28 px, sticky, bg-2, 11 px uppercase ink-3;
  - rows: 32 px, hairline line-1, hover bg-3, selected bg-4 with the checkbox;
  - numbers right-aligned in mono, text left-aligned;
  - symbol cell: mono 13/500 ink-1, never broken mid-word (`white-space: nowrap`), with a secondary line at 11 px ink-3;
  - the left edge is reserved for the REAL edge;
  - wide tables: a sticky first column, a sticky action column on the right, and a scroll shadow.
  - Long secondary text (the Orc line) goes into a row detail expander (▸), never into a 12-line column (shot 08).
- **KPI tile:** label 11 uppercase ink-3; value at figure size in mono; sub-line 11 ink-3; optional freshness or source line. No count-up on money.
- **Key–value grid** (`dl`): 2 or 3 columns; keys 11 ink-3; values mono 13 ink-1.
- **P&L cell:** value (up/down by sign, ink-2 at zero) and the source line under it (`eToro's own · 8 s`, or `≈ estimate: Binance quote, 18 min`). This styles what pnltruth and F4/F7 already print (`pnl_words`, `pnl_title`), without inline styles.
- **Score meter:** 4 px bar on bg-3, fill ink-2; the dots of signal strength stay.
- **Sparkline:** 1.5 px line in up/down by the period's sign, no glow (today `drop-shadow` at 2668).

**Controls**
- **Buttons:**

  | Variant | Look | Use |
  |---|---|---|
  | Primary | ink-1 fill, bg-0 text | Save, Apply, Preview: non-money confirms |
  | Secondary | bg-3, line-2 border, ink-1 | Default |
  | Ghost | Transparent, ink-2; hover bg-3 | Toolbars, tertiary |
  | BUY | Up outline, up text, up wash on hover | Only on actions that open or add to a long |
  | SELL | Down outline, down text, down wash on hover | Only on actions that open or add to a short |
  | Stop | ink-1 1.5 px outline with a ■ glyph | CLOSE ALL, all off, brake: protective actions |
  | Icon | 28 × 28 | — |

  - No variant is a solid red fill, and no button glows.
  - Disabled: bg-2, ink-4 text, line-1 border, with the reason in words next to it or in the title.
  - Focus: 2 px Eye outline at 2 px offset.
  - Sizes: 28 / 32 / 40.
- **Inputs:** 32 px, bg-0 well, line-2 border, Eye ring on focus. Numbers in mono, right-aligned, with their unit outside the field.
  - **PIN field:** password type, mono, .3em tracking. Its label says what it unlocks. `autocomplete="off"` and `inputmode="numeric"` are kept.
- **Checkbox / radio:** 16 px; checked uses the Eye. A money choice (Demo, Switch world on /brokers/) stays a plain checkbox with its words, never a toggle.
- **Display toggle:** only for display preferences, never for a money or platform switch.
- **Tabs:** 32 px; active: ink-1 with a 2 px Eye underline.
- **Segmented control:** timeframes; later the REAL | DEMO world choice that C1–C3 will build, designed here: segments carry their world chip, the REAL segment shows the solid red chip.
- **Select and menu:** bg-2 menu, 32 px items, check mark for the current item.
- **Chips (ten styles become five):**

  | Chip | Look |
  |---|---|
  | `.sv-chip` | Neutral outline (asset class, rule, tag). The class chips stop using red, gold and blue: COMMODITY is no longer red |
  | `.sv-world` | REAL / DEMO / PAPER, §3.5 |
  | `.sv-side` | LONG / SHORT / BUY / SELL / BULL / BEAR: up/down text on a 12 % wash, never filled |
  | `.sv-state` | Dot plus word: ON (Eye), OFF (hollow ink-3; OFF is not an error), ERROR (coral), STALE (amber), PENDING (amber, "closing") |
  | `.sv-count` | bg-3 bubble, mono 11 |

  - Plus `.sv-fresh` (§3.7) and `.sv-ai` (violet dot plus "model").

**Overlays (one family)**
- **Popover:** for rail cards, quote cards, status-bar dropdowns, nav menus and chart cards.
  - bg-2, line-2 border, radius 6, popover shadow; widths 320 / 360 / 420.
  - Header 40 px with title and ×; a body that scrolls; a sticky footer for actions.
  - Placement (anchoring, flipping, viewport fit, pinned state) is railfilters' and is not redone.
- **Dialog:** sizes 420 / 520 / 720. The header carries the subject.
  - `.sv-dialog--danger` (set today when the ticket is live or funding, `base.html:2677`) gets a 3 px `--sv-real` top edge and the REAL chip in the header.
  - The five modal systems share this look; their behaviour is unchanged.
- **Drawer:** Activity, 360 px, unchanged behaviour.
- **Tooltip:** `title` stays the tooltip for now. A styled tooltip is not in this plan.

**Money components:** the deal ticket, the TAKE TRADE dialog, the switch row and the close dialog are specified in §10.

---

## 8. Motion

- **Durations:** 80 ms (press), 140 ms (hover, popover in), 200 ms (drawer). Easing `cubic-bezier(.2,0,0,1)`. No bounce, no slide over 4 px.
- **Price flash:** the background takes the up/down wash and fades over 600 ms. At most once a second per cell (the feed spec's own limit). The number's colour never flashes.
- **No count-up on money or prices.** `sv-motion.js` count-up stays on counts only (`_command_bots.html`, `_command_history.html`), and those counts stop wearing `up`/`down`: a count of enabled bots is not a gain.
- **Infinite animations on work pages: two at most, both meaningful.**
  - The live heartbeat dot (opacity .55 to 1, 2.4 s).
  - The armed pill's beat (`sv-armed-beat`, `sauron.css:2431-2436`), which says real money is armed.
  - Both are off under `prefers-reduced-motion`, as the armed beat already is. The other infinite animations in `sauron.css` stop on work pages.
- **Ambient layers on work pages:**
  - grid, globe-eye, circuits, particles, caustics and code-stream are not displayed;
  - their `requestAnimationFrame` loops (`base.html:3468-3756`) do not start when hidden or when reduced motion is asked;
  - the particles stop carrying ticker labels and prices everywhere (`base.html:3476-3490`, 3565-3570): fake prices have no place on a trading screen, even behind glass.
  - Lock, login and intro keep their atmosphere (S2.7).
- **Refresh keeps the frame.** A region being refreshed keeps its last render, at 70 % opacity if slow. No skeleton, no layout jump.

---

## 9. Icons

- **One family.** A self-hosted SVG sprite, `static/icons/sv-icons.svg`: about 40 symbols on a 24-unit grid, 1.5 px stroke, `currentColor`, shown at 16 px (nav, buttons) and 20 px (topbar).
- **Source.** Drawn after Lucide (ISC licence; notice in the file). No CDN and no icon font, so no flash of a missing glyph.
- **What it replaces:**
  - the 62 Unicode nav glyphs (`base.html:461-577`), some of which render as colour emoji depending on the OS (⚠ ⚖ ⛁);
  - 🔒/🔓, ☀/☾ and ⏻ in the topbar;
  - the 21 inline SVGs drawn at five different stroke widths.
- **The logo** stays the inline hexagon Eye (`base.html:407-438`), drawn in `currentColor`.
- `tests/test_nav_grouping.py`'s glyph-block rules become: "every nav row names an icon that exists in the sprite".

---

## 10. Money-relevant controls: the look contract

The words, forms, PIN steps, confirm steps and focus order of every control below are unchanged by every stage. Only the look changes, and the look must never mislead.

The new test file `tests/test_money_controls_look.py` (S1a) pins each row: the selector exists, it uses the stated tokens, and no rule paints it in a forbidden way.

| Control | Where | Look | Must never |
|---|---|---|---|
| Deal ticket SELL (bid) / BUY (ask) | `_partials/deal_ticket.html:23-55`; CSS `sauron.css:7474-7557` | SELL: down outline and text; BUY: up outline and text; the price in mono 15/500; the world chip in the middle (`tk-venue`): REAL solid red, paper grey outline; a fixed min-width so a ticking price never moves a button; stale ticket dashed with a muted price (today's rule) | Render in Arial (S0); use a solid red fill; print a price when stale; shift under the pointer as prices tick |
| TAKE TRADE / ADD dialog | `base.html:1849-3295` (host 2677, label 2880); CSS `sz-` 6308-6484 | Header: side, symbol and world chip; REAL or funding: `--danger` with the red top edge. A warning summary pinned under the header ("⚠ 2 warnings: BOOK LIMIT REACHED · NO SAURON SIGNAL", click to expand), because the dialog opens scrolled to the units field (shot 10). Confirm button in the side's colours (BUY up, SELL down); Cancel neutral | Show a green confirm on a SELL; let a warning sit above the fold with no visible trace; change words, focus, PIN or execute |
| Signal card TAKE TRADE / ADD TO POSITION / PASS | `.sr-pop-btn-act` 1715, `.sr-pop-btn-pass` 1731; railfilters' `.sr-pop-foot` | TAKE TRADE / ADD in the signal's side (a bearish signal is a SELL); PASS is ghost-neutral (it dismisses, it does not lose) | Paint TAKE TRADE green on a bearish signal (today's `-act` is green for every side); paint PASS red |
| Quote card LONG / SHORT (headband and watchlist) | `base.html:1561-1565`; `.sr-pop-btn-act`, `.sr-pop-btn-short` 2674 | As the deal ticket's sides | Use today's saturated green and red gradient slabs (shot 04) |
| CLOSE / RETRY CLOSE per row | `positions_list.html:414` (`btn-danger`, `data-sv-close-trade`) | Neutral outline "CLOSE", in a sticky right column (never scrolled off); RETRY CLOSE with the amber "closing" state chip | Be a red fill. Today `.btn.btn-danger` (`sauron.css:1967`) paints a dark-to-red gradient with white text, the REAL chip's family, and it also reads as a loss. Be hidden behind a horizontal scroll (today at 1440, shot 08) |
| Close dialog | `sv-close-advice.js/.css` | P&L in up/down with its source line; "Mark now" with its freshness badge; world chip; confirm neutral-strong "CLOSE …"; the PIN for real rows unchanged | Show an estimate without saying so; show a stale mark as live |
| CLOSE ALL | `positions_list.html:225` (`#svCloseAll`), preview 1135, execute 1193 with PIN | Stop variant (■, ink-1 outline) in the table head; the preview lists rows with their world chips | Be a red fill; lose its "(whole book)" words when filtered |
| PIN entries | Lock (`sauron.css:5492-5934`, `base.html:7258`, `locked.html`), `login_pin.html`, ticket PIN step, /ops/ (`ops.html:129`), /brokers/ (`brokers.html:91`), CLOSE ALL | PIN field (§7) with "PIN · turns on actuator_mode_live (real money)"-style words | Look optional; be autofilled; hide what it unlocks |
| Platform switches | `ops.html:101-129`; `admin_toggle_component` | Row: key (mono), name, state chip, last run, runs, errors, then a 180 px action column so the buttons align. A money (PIN) switch shows the REAL chip by its name and "PIN ____ TURN ON" in neutral; "turn off" neutral; "all on" neutral; "all off" in the stop variant | Make TURN ON a cheerful green fill (today's `.btn.btn-primary`, `sauron.css:1962`, a green gradient slab); make turn off or OFF red (today's `btn-danger` and red OFF chips): turning off is the safe direction |
| Bots on/off, Morgul brake, bot brake | `asset_bots.html`, /ops/ | Same as switches | Same |
| World markers | `.sv-world` (`sauron.css:2395-2421`), `{% money_world %}`, `.sv-row--live`, `.tk-venue--live`, `.sv-venue--live`, `.sv-armed-pill` (2422-2437) | §3.5 | Lose the "only solid red fill" property; drop below 4.5:1 |
| /brokers/ Demo, Switch world, Replace keys | `brokers.html:89-92` | Plain checkboxes with their words, in a "World" fieldset that explains REAL and DEMO with their chips | Become toggles; gain emphasis that invites a click |
| /setup/ risk limits | `setup.html:175-271` (MAX ACCOUNT PLEDGED, MAX BOT LEVERAGE, Save Risk Limits) | Mono inputs with units; "blank = no cap" stays in words; Save primary | Lose the explanation of blank |
| /withdrawals/ | `withdrawals.html:143-232` (Reserve, Mark withdrawn, Cancel, Correct) | Primary for Reserve and Mark withdrawn; neutral Cancel and Correct | Paint Cancel red (it cancels a reservation, it moves nothing) |
| Leverage on the ticket (PR #85/#86) | TAKE TRADE body | The chosen multiplier in words and mono | Look "safe" when it is the maximum |
| Every price and P&L cell | Everywhere | §3.4, §3.7, §4.4, §8 | Count up; flash its text colour; look live when stale; hide that it is an estimate |
| Future: pending orders (P1–P5), REAL \| DEMO on the ticket (C1–C3) | Not built | Built on these rules | — |

---

## 11. The live hooks contract

Display stages never rename or drop these, because live updates, the ticket and the tests depend on them.

New test `tests/test_live_hooks_inventory.py` (S1a): it records today's inventory and fails if a template loses one.

- **Data attributes:**
  - `data-sv-live`, `data-sv-live-key`, `data-sv-live-status`;
  - `data-dq`, `data-ticket`, `data-decimals`;
  - `data-flash`, `data-sv-noflash`, `data-sv-count`;
  - `data-mark-source`, `data-sv-at`, `data-sv-close-trade`;
  - `data-sv-overlay`, `data-sv-open`, `data-sv-close`, `data-sv-persist`, `data-sv-backdrop`, `data-sv-focus`, `data-sv-lock`;
  - `data-sv-fhost`, `data-sv-list`, `data-sv-rail-n`, `data-sv-gone-toggle` (added by railfilters; the inventory takes them in when it merges);
  - `data-nav-page-id`, `data-instrument-live`.
- **Ids:**
  - `#signalsRail`, `#railSignals`, `#railSignalsBody`, and railfilters' `#hbSignalRows`;
  - `#svCloseAll`, `#clock`, `#svBannerStack`;
  - the chart's `json_script` ids `<chart_id>-positions` and `-signals`.
- **Classes JS reads:** `.sv-unknown`, `.sv-age`, `.up`, `.down`, `.sv-flash--*`, `.tk-stale`, `.sv-row--live`, `.sv-world--*`, `.sv-sel-bar`, and railfilters' `.sv-pinned`.
- **Window globals:**
  - `svTakeTrade`, `svTakeTradeAsset`, `svCloseTrade`;
  - `svCharts` (`{refresh, tick}`), `svLevels`, `svSignalDots`, `svHoverCards`;
  - `svRenderSparks`, `svWheelMarquee`, `svLiveRefresh`, `svRenderDonuts`, `svRenderLines`;
  - `SAURON_CHART_COLORS`, and `SV.*` (`overlay`, `ages`, `flash`, `dwell`, `popup`, `tour`, `council`).

---

## 12. The stages

Each stage gives:
- **Goal**
- **He will see**
- **Files**
- **Conflicts and order**
- **Tests**
- **Acceptance**
- **Size**

Screenshots before and after come from the harness (§14), on the synthetic fixture.

### S0. Six display defects (ships first; fixes, no redesign; no approval needed)

**Goal.** Remove defects measured today.
1. **The rail covers /positions/ and /portfolio/.** `body:has(.sv-sel-bar) .main-content { overflow-x: clip; }` (`sv-close-advice.css:66`) lets the column ignore the rail's margin. Give `.main-content` `min-width: 0`, or move the clip to the selection bar's own container.
2. **The deal ticket's bid/ask render in Arial.** Add `.sv-ticket button { font: inherit; }`. The global reset waits for S1a.
3. **The signals setup chart never draws.** `_signals_metrics.html:1` brings Chart.js through an htmx swap and the inline chart code at :91 runs first; `request.chart_assets_loaded` is never set. Run the chart code on the library's load event, and set the guard.
4. **The lightweight-charts licence.** Add "Charts by TradingView" (a link to tradingview.com) with the NOTICE text in the chart's caption row (`chart_widget.html:840-892`).
5. **Native controls paint light on the dark theme.** Set `:root { color-scheme: dark }`, and `:root:has(> body.light-mode) { color-scheme: light }`. The light-mode class sits on `<body>` (`base.html:117`), and the page's scrollbars follow the root.
6. **Links without a class render in the browser's blue** (/orcs/ "Orc #13", footnotes). Add a base `a` rule with today's tokens: `--text-primary`, underline at 40 %, full underline on hover.

**He will see:**
- the positions table no longer hidden behind the open rail;
- the ticket's prices in the page's face;
- the signals chart drawn;
- a small TradingView credit under the chart;
- dark scrollbars and dropdown lists;
- readable Orc links.

**Files:**
- `static/css/sv-close-advice.css`;
- `static/css/sauron.css` (three or four rules);
- `templates/_partials/chart_widget.html` (caption row only);
- `templates/dashboard/_signals_metrics.html`, `templates/_chart_assets.html`;
- new `tests/test_ui_s0_fixes.py`.

**Conflicts.** None:
- railfilters edits `base.html` and the rail partials;
- pnltruth edits `chart_widget.html` near 1348 (the hover cards), not the captions;
- no branch touches `sv-close-advice.css`, the metrics fragment or the ticket CSS.

**Tests:**
- Measured (the `tests/test_close_advice.py` `_chrome()` pattern, skipped where no Chromium is found; GitHub's ubuntu runner ships Chrome, so they should run in CI too — confirm on the first PR):
  - at 1280/1440/1920, rail open and closed, `.page-content`'s right edge ≤ the rail's left edge on /positions/ and /portfolio/;
  - `.tk-px` computed font is the mono token;
  - /signals/ logs no error.
- String: the attribution link exists once.
- Re-run: `test_close_advice`, `test_deal_ticket`, `test_chart_surfaces`, `test_card_responsiveness`.

**Acceptance:**
- **Metrics:** rail overlap 0 px (today 44/280/33/159 px); console errors 0 on /signals/ (today "Chart is not defined").
- **Screenshot pairs:**
  - `positions_1280_railopen` and `positions_1440_railopen`;
  - a crop of the instrument ticket at 1440;
  - `signals_1440_default`;
  - `12_orcs` at 1920.

**Size:** S.

### V. The preview page (before S1a; no pull request)

**Goal.** He approves the look before any page changes.

A private page (claude.ai artifact) is built from the S1a draft of `sv-tokens.css` and `sv-kit.css`, with synthetic content only. It shows:
- **Palette and type:** the palette with its roles (§3.9); the type specimen at the four tiers.
- **Shell:** a shell mock at 1440 (topbar, market band, status bar, dock).
- **Money components:**
  - a positions table with REAL, DEMO and PAPER rows, gains, losses, an estimate and a stale price;
  - the deal ticket (REAL and paper, live and stale);
  - the TAKE TRADE header with its warning summary;
  - a switch row (money and display).
- **Popovers and tiles:** a signal popover; a KPI strip.
- **Chart:** a chart sample with synthetic bars.
- **Before/after:** one strip with today's screenshot of the same area.

He answers: OK, or what to change. Nothing in the repository changes here.

### S1a. Foundation: tokens, faces, kit (one PR)

**Goal.** Every page changes at once through shared tokens and the kit. Pages' own blocks are cleaned later in S2.

**He will see, on every page:**
- a calm, opaque dark background: no circuits, particles, fake prices or log lines behind data;
- Inter for words and JetBrains Mono for numbers;
- labels readable (ink-3 at 6.3:1 instead of 3.1:1);
- nothing under 11 px in the shell;
- gains and losses in jade and coral, not in the brand green;
- REAL still the only solid red;
- calm, consistent buttons (no green or red slabs);
- tables aligned in mono;
- one look for chips, menus, popovers and dialogs;
- readable links.

**Files:**
- New:
  - `static/css/sv-tokens.css` (all `--sv-*` tokens and the tier media queries);
  - `static/css/sv-kit.css` (components; loaded just before `sv-responsive.css`, so after railfilters' `sv-rail.css` whichever lands first);
  - `templates/dashboard/design_kit.html`, a view and a URL (`/design/kit/`, staff only).
- `templates/base.html`:
  - line 61 (the font link, §4.1);
  - two `<link>` lines in the head;
  - the ambient-loop guards and the particles' fake labels (3468-3756; no in-flight hunk touches this range).
- `static/css/sauron.css`:
  - `:root` 6-45 re-pointed (§3.10) and the old values restated under `body.light-mode` (624-651);
  - the reset at 46 gains `button, input, select, textarea { font: inherit; color: inherit; }`;
  - body at 47-51 becomes Inter 13/1.45/400;
  - the ambient blocks are hidden on work pages;
  - `.up`, `.down`, `.sign-*`, `.bullish`, `.bearish` and big-number classes (`.stat-value`, `.metric-value`, `.ip-count`, `.dh-pop-price`, `.pos-pop-r-val`, `.oc-strip-value`, `.oc-hero-amount`) re-pointed;
  - the `.btn` family (342, 909, 1944-1975), so that no button anywhere is a green or red slab from S1a on:
    - `.btn-primary` becomes the light primary;
    - `.btn-danger` becomes the neutral outline (it carries CLOSE, CLOSE ALL, turn off, all off and Cancel today);
    - the per-page variants (the stop variant on CLOSE ALL and all off, neutral TURN ON) arrive with their pages in S2.
- `core/templatetags/sauron_tags.py`: new `qty` and `src_name` filters, unused until S2.
- `templates/_chart_assets.html`: Chart.js defaults take the number face; colours already come from the tokens.

**Conflicts:**
- railfilters adds one head line at 113: a trivial rebase.
- No branch touches `sauron.css` `:root`, the reset, the ambient code or the template tags.
- The kit restyles railfilters' popups by class only, in a later sheet. Their markup and JS are untouched.

**Tests:**
- New `tests/test_design_tokens.py`:
  - every text role pair in §3.2–§3.6 meets ≥4.5:1, computed in Python;
  - the font link is exactly §4.1's, and no other font host appears in the shell;
  - the input reset exists;
  - no `font-size` under 11 px in `sv-tokens.css`, `sv-kit.css` or the shell rules S1a owns;
  - `--sv-real` and any red are used as a solid background only by the world-marker family;
  - light mode restates every re-pointed token.
- New `tests/test_design_kit_page.py`: staff sees every component; others get 404.
- New `tests/test_live_hooks_inventory.py` (§11).
- New `tests/test_money_controls_look.py` (§10).
- Node: the ambient guard returns early when hidden or under reduced motion.
- Updated deliberately, each with its reason:
  - `test_money_world` (REAL hex);
  - `test_motion` (infinite animations off on work pages);
  - `test_nav_grouping` (its docstring names Rajdhani);
  - `test_headband_*`, `test_phone_layout`, `test_measured_rendering`, `test_card_responsiveness`, `test_brand_assets` (the logo colour is unchanged; checked);
  - `test_chart_divisions` (its toolbar measurement already uses a 0.6 em fallback: JetBrains Mono is 0.6 em, so expected unchanged).

**Acceptance:**
- **Metrics:**
  - text under 11 px in the shell: 0 (today 39–56 % of all text at 1280);
  - every shell text ≥4.5:1 against its computed background (harness check);
  - running infinite animations on a work page: ≤2 (heartbeat, armed beat);
  - ambient canvases neither rendered nor scheduled;
  - 0 console errors;
  - no page scrolls sideways at any width (today's good state, kept).
- **Screenshot pairs:** 01 home, 04 quote card, 05 rail open, 06 signal popover, 08 positions, 09 instrument, 10 ticket, 11 ops, at 1440 and 1920, plus `/design/kit/` at the four desktop widths.

**Size:** L (mostly CSS).

### S1b. Shell layout (one PR; after railfilters and pnltruth merge)

**Goal.** Give the content its space and stop the chrome from sitting on it (§6.2).

**He will see:**
- the first content line at about 92 px instead of 184, about 120 px more to read at every desktop size;
- one 32 px market band, with the latest headline on its right;
- a 32 px status bar where the important cells always fit and the rest wait behind "+N";
- Gollum, the Eye and the Horde in that bar, no longer over tables;
- Council and Activity opened from the right dock;
- the rail as a real column that narrows the page when open;
- a compact nav with collapsible sections and one icon family;
- popovers in the kit's look, with railfilters' click-to-open behaviour.

**Files:**
- `templates/base.html`:
  - topbar 594-782;
  - news ticker 785-794 and data headband 797-809 merged into one band;
  - restore tabs 812-821;
  - bottom strip 845-1443 (single-line cells, overflow, docked Horde, Gollum and Eye);
  - rail toggle 1456, rail 1476-1590 (column and dock);
  - nav 439-578 (icons, compact rows, collapsible sections);
  - Gollum 5689; Ask Sauron button 5740.
- `static/css/sauron.css` shell sections: 1062-1343, 1497-1787, 1850-1920, 2126-2223, 3399-3457 (`--se-*` edges), 7114-7264.
- Horde, Council and Activity: `sv-horde.css/.js`, `sv-council-band.css/.js`, `sv-activity.css/.js` (launch points only).
- Overlays and tour: `sv-overlay.css` (skin moves to the kit), `sv-tour.js` (anchors).
- `sv-rail.css` (tokens only).
- New: `static/icons/sv-icons.svg` and a `{% icon %}` tag.

**Conflicts:**
- Starts only after railfilters (rail, popups, bottom-band SIGNALS) and pnltruth (bottom-band PORTFOLIO and OPEN P&L) merge.
- ticketnet is untouched.
- Feed F7 later edits the WS painter and the paused chip. S1b keeps the painter untouched and reserves the topbar slot where "live prices paused" goes.

**Tests:**
- Updated deliberately:
  - `test_the_horde`, `test_gollum`, `test_council_band`, `test_activity_drawer`, `test_tour`;
  - `test_headband_*`, `test_ticker_and_banners`;
  - `test_nav_grouping` (glyph blocks become sprite icons);
  - `test_expand_does_not_vanish`, `test_popup_persistence`, `test_overlay_scrolls`.
- New measured `tests/test_shell_geometry_measured.py`, at 1280/1440/1920/2560, rail open and closed:
  - first content y ≤ 100;
  - no fixed shell element intersects `.page-content`'s inner box;
  - status-bar hidden width 0;
  - content right ≤ rail left;
  - topbar fits;
  - at 390 the phone tier is unchanged.

**Acceptance:**
- **Metrics:**
  - first content y ≤100 (today 184);
  - reading height ≥676/776/956/1316 (today 555/655/835/1195);
  - fixed-chrome overlaps 0 (today 5 controls at every width);
  - status bar hidden 0 px (today 491/727 at 1280; 331/567 at 1440).
- **Screenshot pairs:** 01, 02, 03, 05, 06, 08, 11 at 1440 and 1920, and 01 at 390.

**Size:** L.

### S2. Page by page (one PR per group)

**Order.** Our estimate of his use, which he confirms or changes. `/` lands on /command/, he trades from the instrument page's ticket and the rail, and he watches /positions/.

**Every S2 PR:**
- moves the page's own `<style>` block and inline styles onto the kit;
- replaces its neon literals with tokens and its sub-11 px sizes with the scale;
- applies the number rules (`px`, `qty`, `src_name`) and the look contract;
- leaves every hook of §11 intact;
- rebases on whichever branch touching the same template merged first. UI yields to money work.

**S2.1 The ticket and the instrument page (after ticketnet and pnltruth).**
- He will see:
  - a compact hero row (56 px): symbol, star, price in mono hero, change, freshness badge, market badge, the deal ticket on the right;
  - the chart directly under it (its inside is S4);
  - below: his position(s) on the symbol, latest quote, signals, technicals and news in a 2- or 3-column grid;
  - the TAKE TRADE dialog per §10, with the warning summary pinned, side-coloured confirm and world chip.
- Files:
  - `instrument_detail.html` (not the chart card's inside);
  - `deal_ticket.html` (classes only);
  - `sauron.css` 7474-7557 and 6308-6484 (into the kit);
  - `base.html` TAKE TRADE: the summary bar's markup and class hooks only.
- Not touched: `sv-instrument-live.js` (F7 owns it).
- Tests: `test_deal_ticket`, `test_pretrade_controls`, `test_venue_split`, `test_money_world`; measured: the ticket never moves when `.tk-px` text changes length.
- Acceptance pairs: 09, 09b and 10 at 1440 and 1920. Metric: no ticket text under 11 px.

**S2.2 Positions (after pnltruth; rebase over usedfix U3 if it lands first).**
- He will see:
  - KPI tiles in one row at ≥1440 (4 × 2 at 1280);
  - the open-positions table fitting at ≥1440 with no sideways scroll, through column priorities and a row detail for the Orc line and secondary facts;
  - symbols never broken ("EURU / SD");
  - CLOSE always visible in a sticky right column;
  - quantities and prices in their own digits (no `12.00000000`);
  - the P&L source line styled;
  - the close and CLOSE ALL dialogs per §10;
  - analytics in 3 columns at ≥1680.
- Files: `positions_list.html` (style 681-1049 into the kit; table markup), `_positions_metrics.html`, `_position_summary.html`, `sv-close-advice.css/.js` (skin only).
- Tests: `test_position_page`, `test_position_card_ux`, `test_gain_shows_percent`, `test_close_advice`, `test_close_liveness`, `test_money_world`.
- Measured, at each desktop width:
  - main table scrollWidth ≤ clientWidth at ≥1440;
  - CLOSE inside the viewport;
  - row height ≤44;
  - zero mid-word breaks in symbol cells;
  - no 8-decimal value in the HTML.
- Acceptance pairs: 08 at 1280/1440/1920/2560, rail open and closed. Today: a 1,409 px table in a 1,078 px card at 1440, and 240 px rows.

**S2.3 Home, /command/ (after pnltruth).**
- He will see:
  - a hero row (portfolio in mono hero, 24h change with source, the REAL / PAPER / DEMO split);
  - the seven Day-of-Sauron tiles never truncated (container query);
  - the loop diagram calmer and collapsible;
  - THE BEAT beside it;
  - tabs and tiles on the kit;
  - the open-positions table on the number rules (today 8-decimal quantities and a cut table).
- Files: `command.html` (style 482-785), `_command_*.html`, `sv-day-scheme.css`. `sv-day-live.js` is untouched.
- Acceptance:
  - ellipsised tiles 0 at 1280 with the rail open (today 31);
  - no table scrolls sideways at ≥1440;
  - pairs 01/01b at 1440 and 1920.

**S2.4 Signals and portfolio (after pnltruth).**
- He will see:
  - **/signals/:** the KPI strip, score distribution and direction mix in the chart language (§3.8), and the signals table with symbols no longer cut (`sig-sym-name` ellipses today);
  - **/portfolio/:** the hero, the positions table with its source lines, and the allocation donut in the categorical palette.
- Files: `signals_list.html`, `_signals_metrics.html`, `portfolio_overview.html`, `_portfolio_metrics.html`.
- Conflicts:
  - pnltruth edits `portfolio_overview.html` (250-255) and merges first;
  - railfilters' rows live in its own partials, not in `signals_list.html`;
  - feed F4 later patches the same P&L cells, through the kept `data-sv-live-key` hooks.
- Tests: `test_portfolio_live`, `test_portfolio_value_truth`, `test_signal_acted_and_sizing`, `test_signal_backing_warning`, `test_measured_rendering`; measured: no canvas wider than its column, no table scrolling sideways at ≥1440.
- Acceptance:
  - the setup chart draws (S0) in the kit's chart look;
  - no canvas spills its column (today 71 px at 1280 with the rail open);
  - pairs `signals_*` and `portfolio_*` at 1440 and 1920, rail open and closed.

**S2.5 Cockpits: /ops/, /orcs/, /ai-models/ (after orcs2b).**
- He will see:
  - **/ops/:**
    - switches as a dense list with sticky group headers and counts;
    - money switches marked REAL with an aligned PIN and TURN ON column;
    - a filter by name or state;
    - groups collapsible (a group with something ON or ERRORING opens by default);
    - the page from 19,016 px at 1440 to under 6,000 with groups closed.
  - **/orcs/:** the repeated STATE sentence becomes a header note plus a short state chip; the LINE column readable.
  - **/ai-models/:** one 48 px row per tier (model, effort, Save inline); the long paragraph becomes a lead plus "more".
- Files: `ops.html`, `orcs_list.html`, `orc_detail.html`, `orcs_seats.html`, `ai_models.html`.
- Conflicts:
  - orcs2b edits `ai_models.html` and `orc_detail.html`, and merges first;
  - O2c/O2d's new Orc pages are written on the kit;
  - no feed phase touches these pages.
- Tests:
  - `test_ops_cockpit`, `test_switch_pin`, `test_switch_texts_truth`, `test_ai_models_truth`, `tests/orcs/test_orc_pages.py`;
  - the `test_money_controls_look` rows for switches;
  - a form diff: the same keys, hidden inputs, `want` values and PIN fields before and after.
- Acceptance: pairs 11, 12 and 13 at 1440 and 1920; page heights; TURN ON buttons in one column (measured x of every action column equal).

**S2.6 Money settings.**
- Pages: /setup/, /brokers/, /withdrawals/, /treasury/, /asset-bots/, /shares/, the capital desk, the allocator, risk.
- He will see:
  - forms with readable labels (11 px uppercase becomes 12 px), mono inputs with their units, one Save per form;
  - the /brokers/ world boxes grouped and explained with their chips;
  - the withdrawal and bot buttons per §10.
- Files: `setup.html` (90 inline styles), `brokers.html`, `withdrawals.html`, `treasury.html` (81 inline styles; after U3), `asset_bots.html`, `shares.html`, the desk template (113 inline styles), the allocator and risk templates.
- Conflicts: U3 edits `treasury.html` (it waits for U3); C1–C3 will add the world choice on the ticket, not here.
- Rule: words, forms, PIN fields, hidden inputs and confirm steps are byte-for-byte unchanged. The test diffs every `<form>`'s fields before and after.
- Tests: `test_setup_form_submittable`, `test_setup_memory`, `test_brokers_page`, `test_broker_form_clarity`, `test_withdrawals`, `test_treasury`, `test_asset_bots`, `test_shares_page`, plus the form diff.
- Acceptance: pairs of each page at 1440 and 1920; no text under 11 px; the form diff empty.

**S2.7 Login, PIN, lock, intro (brand moments).**
- He will see the same moments with the new faces and palette: the Eye and its embers, without fake prices, and the PIN field per §7.
- Files: `registration/login.html`, `login_pin.html`, `dashboard/locked.html`, `intro.html`, `_popout.html`.
- These point at `sv-tokens.css` and §4.1's fonts. They keep their atmosphere: globe-eye and embers, without fake prices.
- `report.html` keeps its light print palette. The Wall, the Book and the investor panel are out of scope (public identity, their own tests).
- Conflicts: none in flight.
- Tests: `test_login_eye`, `test_login_pin_gate`, `test_lock_screen`, `test_lock_polish`, `test_idle_lock`.
- Acceptance: pairs of login, PIN and lock at 1440 and 390.

**S2.8 The long tail.** One PR per nav section, without a layout redesign:
- neon literals become tokens;
- sizes move onto the scale;
- Django messages use the notice component;
- the five modal looks become the dialog;
- old `.btn` definitions (342, 909, 1944) are folded into the kit.

Conflicts: each section PR checks `git log` for open branches on its templates and waits for them.

Tests:
- a sweep test: no `rgba(0,232,104` and no `font-size` under 11 px left in the section's templates;
- the page tests of that section, re-run.

Acceptance: one harness pass of the section's pages at 1440, each page's numbers in the PR.

**Size:** S2.1, S2.2, S2.5 M; the others S–M.

### S3. Responsive, complete (one PR; after S2.1–S2.4)

**Goal.** Every page right at every width. Desktop first, then tablet, then phone.

**Desktop sweep (the harness at 1280, 1440, 1920, 2560 for the 12 most-used pages and `/design/kit/`):**
- the type tiers;
- multi-column layouts at D3/D4;
- KPI strips capped at 8;
- the 72 ch measure;
- no dead space (today the bottom strip's right half is empty at 2560 and ends in a dead gap at 1920; cards and tables stretch to 2,200 px at 2560).

**Tablet (769–1279):**
- sidebar as an icon rail;
- the signal rail as a drawer over the page;
- the status bar's overflow;
- tables on their priorities.

**Phone (≤768), on top of today's phone tier:**
- every popover opens as a bottom sheet (railfilters' tap-to-open, `sv-overlay.css:785-813` today removes hover cards on touch);
- the ticket as a full-width bottom sheet with 44 px BUY/SELL;
- positions and signals as stacked cards (`.sv-stack`, `sauron.css:6058-6180`);
- the Horde pill and the Eye moved into the phone nav's menu (today over the WATCH and TELL tiles);
- touch targets ≥44 px on every money control.

**Breakpoints.** The ~70 template media queries at 30 different widths fold onto the tier boundaries.

**Files:** `sv-responsive.css`, `sv-kit.css` tiers, page media queries. The chart's own phone layout is S4's.

**Conflicts:**
- The JS breakpoints (768/769/900) do not move, so `sv-horde.js`, `sv-council-band.js`, `sv-activity.js` and `sv-day-live.js` are untouched.
- Railfilters' popover placement is reused for the bottom sheets, not rewritten.
- The phone ticket sheet waits for ticketnet's merge, like S2.1.

**Tests:**
- `test_phone_layout`, `test_phase29_mobile`, `test_card_responsiveness`;
- new measured matrix at 390, 768, 1024, 1280, 1440, 1920, 2560:
  - no sideways scroll;
  - no fixed-chrome overlap;
  - popovers inside the viewport;
  - money-control targets ≥44 px at ≤768.

**Acceptance:**
- The matrix is green.
- Screenshot pairs at 390: home, positions, instrument, ticket. Pairs at 2560: home, positions.

**Size:** M.

### S4. Charts, TradingView-grade (one PR; after S1a and pnltruth; can run alongside S2)

**Goal.** The chart becomes the best surface of the product. All existing behaviour stays: the tick weld rules (`tickRefusal` 6620-6653), signal dots, levels, positions, memory and the PIN veil (423).

**He will see.**

*Layout and toolbar:*
- A chart that fills the page's height on a computer (instead of a fixed 420 px). Viewport minus chrome minus hero, minimum 480. Tall and fullscreen kept.
- A one-row toolbar of 36 px:
  - on the left: symbol;
  - interval favourites (5m 15m 1H 4H D W), with the rest in a menu;
  - chart type menu;
  - indicators menu (SMA20, SMA50, EMA20, BB, VWAP, RSI, MACD, VOL);
  - overlays menu (Positions, Levels, Signals, Sessions);
  - on the right: LOG, fit, tall, fullscreen.
- Date ranges (1W 1M 3M 1Y) on a bottom row, as on TradingView, with the UTC time and the bar countdown.

*In the pane:*
- The legend inside the pane, top-left, with no bordered plates: symbol · interval · source, O H L C and the change in mono 12, and the indicators listed with show/hide.
- **Axis tags:**
  - only the last price and his entry sit on the price axis;
  - stop and target labels move into the pane's right edge as small chips that avoid each other (the level layer's keep-outs), so tags no longer stack over the newest candles (shot 09).
- The pinned signal or level card:
  - scrolls (pointer events on when pinned; today `pointer-events: none` at 485-523);
  - sits in the emptier side of the pane, not centred on the dot over the newest candles (`place()` 1214-1224).
- A faint symbol and interval watermark (4 %).
- Colours, faces and lines per §3.8.

*Feel and the small charts:*
- No hitch when prices arrive quickly.
- Small Chart.js and SVG charts in the same language: categorical palette, polarity colours, thin marks, mono ticks, tooltips value-first, legends for 2+ series.

**Files:**
- `templates/_partials/chart_widget.html`:
  - CSS 24-657, toolbar 661-768, captions 840-892;
  - `getThemeColors` 2947-3024 (read once per page: the theme is server-rendered);
  - `baseOptions` 3589-3613 (font = number face, colours = tokens);
  - `applyPositions` 4310-4383 (line styles; labels for SL/TP off the axis);
  - LevelLayer painters 4959-5255 (cache `computeGeom` by visible range, price range and hover);
  - `onCrosshair` 5760-5840 (`textContent` updates, no `getComputedStyle` per move);
  - card placement 1214-1224 and pinning 5638-5668;
  - refresh 6039-6193 (update series in place; re-create price lines and indicator series only when they changed);
  - `svCharts[...].tick` coalesced to one paint per animation frame, same signature;
  - keyboard 6446-6499 (Esc order: tool, then selection, then popover, then tall);
  - the library loader 895-906 (add the SRI hash for 4.1.0).
- `instrument_detail.html` (the chart card's height line at 211 only).
- `_chart_assets.html`; `_partials/chart_line.html`, `chart_bars.html`, `chart_donut.html`.
- `dashboard/views_bot_charts.py` (SVG colours).

**Library.** Stay on lightweight-charts 4.1.x (no v5 migration here; map 2 §8 gives its cost: 13 call sites, the test fakes, the logo decision).

**Conflicts:**
- pnltruth's chart hunk (~1348) merges first.
- Feed F7 calls `svCharts[id].tick(price, quote)`. S4 keeps that contract and adds the frame coalescing and the `computeGeom` cache that map 2 §6 says F7 needs before raising the tick rate.
- TPO and volume profile (to be redone) will paint in the level layer's order, which S4 documents: bottom = profiles, normal = levels and drawings, top = chips.
- S2.1 owns the rest of `instrument_detail.html`.

**Tests:**
- The 14 `tests/test_chart_*.py` files (475 methods) re-run. Updates where they pin colours, faces or toolbar shape: `test_chart_surfaces`, `test_chart_signal_markers`, `test_chart_levels_widget`, `test_chart_divisions` (its measured toolbar becomes the new single row).
- New tests:
  - node test of the geometry cache (same inputs → no recompute);
  - node test of tick coalescing (10 ticks in one frame → one `update`);
  - node test with the LWC fakes: a 60 s refresh with unchanged indicators re-creates no series and no price line;
  - measured: one toolbar row at ≥1280, the legend inside the pane, the pinned card scrollable, no axis tag over the last 20 bars;
  - attribution present (S0).

**Acceptance:**
- **Metrics:**
  - toolbar rows 1 at ≥1280 (today 2 at 1440);
  - chart height ≥60 % of the viewport on desktop (today 420 px, 47 % at 900);
  - crosshair move with no style recalculation and the legend update under 1 ms (performance trace);
  - 0 console errors.
- **Screenshot pairs:** 09/09b at 1440, 1920 and 2560, plus 390; the signal card pinned; a stacked-tag case (BTCUSD with TP, entry and SL near the last price).

**Size:** L.

### S5. Drawing tools: last

**Library option chosen: B.** A Sauron drawing layer as a series primitive on lightweight-charts 4.1.x, the pattern `LevelLayer` already proves.
- It is written behind a thin attach adapter, so a later move to v5 pane primitives (option C) stays a contained step.
- **Why not C now:** v5 is a migration (13 call sites, the test fakes, +36 KB, the logo).
- **Why not D:** TradingView Advanced Charts means a licence, a datafeed adapter and rebuilding every Sauron layer; most of the 475 tests would become obsolete.
- **Why not E:** forks and plugins replace the core or need a bundler the project does not have.

**S5a. The tools (one PR; after S4).**

**He will see** a 36 px drawing rail on the chart's left, with these tools:
- cursor;
- trend line, ray, extended line;
- horizontal line, horizontal ray, vertical line;
- rectangle;
- parallel channel;
- Fibonacci retracement;
- text note;
- long/short position box (risk and reward washes, reusing the painter at 4988-5004);
- measure (today's, kept);
- magnet, lock all, hide all, delete all (with confirm).

**Interaction:**
- Click to select. Drag the body or a handle. Shift constrains to 0/45/90°.
- The magnet snaps to OHLC.
- Delete/Backspace deletes. Esc cancels the tool, then the selection, then the popover. Ctrl+Z / Ctrl+Shift+Z undo and redo.
- Double-click edits a text.
- On touch, press and drag to place.

**Style popover:** tone (six swatches), width 1/2/3, solid/dashed/dotted, fill opacity, extend left/right, label, and visibility (all timeframes, this one, or a list).

**Sauron style:**
- 1.5 px lines;
- 7 px square handles, outlined in the Eye when selected (the selection rule);
- labels in mono 11 on bg-2 plates;
- fills at 10 %;
- when a drawing is selected, its price and time tags show on the axes.
- The default tone is a pale ice (#9FC3FF), distinct from every system line. Position and level lines stay labelled and are never selectable.

**Storage.** The existing chart memory in localStorage (`sv-chart:` key at 3057), extended:
- one schema, `{t: UTC seconds, p: price}` anchors per symbol, shown on every timeframe through a bar ruler that extrapolates past the last bar, so a drawing can sit in the future;
- today's H-lines and trend lines are migrated;
- the cap rises from 40 to 200 per symbol.

**Files:**
- New `static/js/sv-chart-draw.js`: pure geometry, hit test, ruler and serialisation; node-tested and parse-checked.
- `chart_widget.html` wiring:
  - tool routing through `activeTool`, `setActiveTool` and `onChartClick`;
  - capture-phase pointer listeners for drags, with scroll and scale off during a drag;
  - re-attach after a series swap (`addSeries` detaches at 3928-3933);
  - the drawings' rows and labels fed into `computeGeom`'s keep-outs (4751-4796);
  - hits answered as `zOrder: 'normal'` with `isBackground: true`, so signal dots keep their priority.

**Conflicts:**
- S5a touches the same file as S4, so it starts after S4 merges.
- If TPO and the volume profile are rebuilt meanwhile, they paint in the bottom layer and the drawings in the normal layer (S4's documented order).
- Feed F7's ticks do not touch drawings.

**Tests:**
- Node: geometry, hit test, ruler (exact bars, fractional, beyond the last bar), serialisation and migration.
- Rewritten deliberately: `tests/test_chart_memory_and_live_positions.py:98-183` (it pins `out.hlines.push(d.price)`, `out.trendlines[d.tf]`, `slice(-40)`).
- Measured: place, move and delete each tool at 1440; reload and switch the timeframe, and the drawing is still there; a signal dot over a rectangle still opens its card; level chips never land on a drawing.

**Acceptance:**
- **Screenshots:** each tool selected and unselected; the rail; the style popover; before/after of the instrument chart at 1440 and 1920.
- **Performance:** 200 drawings, pan at 60 fps (trace).

**S5b. Drawings kept on the server (one PR; after S5a).**

**He will see** his drawings on every browser and device, per instrument, on every timeframe he chose.

**Files:**
- A `ChartDrawing` model in `dashboard`: user, symbol, kind, anchors, style, visible timeframes, the timeframe drawn on, z-order, locked, hidden, client id, timestamps, soft delete. Indexed on (user, symbol), capped at 200 per symbol. Migration `dashboard/0003`.
- API `/api/chart-drawings/?symbol=` (GET, POST) and `/<id>/` (PATCH, DELETE): login, CSRF, 423 when PIN-locked (the widget already handles 423 at 6064-6067).
- First paint through a `json_script` block `<chart_id>-drawings`, as positions and signals arrive today.
- An optimistic local mirror, and a one-time import of the localStorage set.

**Conflicts:**
- The migration is `dashboard/0003`. If another branch adds a `dashboard` migration first, this one is renumbered before merge.
- No branch in flight touches the chart memory.

**Acceptance:**
- A drawing made in one browser appears in another after a reload.
- Deleting one and pressing undo restores it.
- The PIN lock answers 423, and the chart says so without losing the local copy.

**Tests:**
- API: auth, CSRF, 423, owner isolation, cap, soft delete, import.
- A decision-module scan (pnltruth's pattern) proves no engine, bot, Orc, alert or gate module imports `ChartDrawing`. The house rule that drawings never reach the trading model's maps (`views.py:4688-4691`, `bot_program/positioning.py:402`) stays enforced.

**Money:** none. No order or alert attaches to a drawing in this plan.

**Size:** S5a L, S5b M.

---

## 13. Sequencing with the work in flight

| Order | Stage | Can start | Must wait for | Yields to |
|---|---|---|---|---|
| 1 | S0 | Now | Nothing | — |
| 2 | V | Now (built from the S1a draft) | — | — |
| 3 | S1a | After V | — | railfilters' head line (rebase) |
| 4 | S4 | After S1a | pnltruth merged | F7 (keeps `tick`), TPO/profile (layer order) |
| 5 | S1b | After S1a | railfilters and pnltruth merged | F7 (painter untouched) |
| 6 | S2.1 | After S1b | ticketnet and pnltruth merged | C1–C3 (built on its look) |
| 7 | S2.2 | After S1b | pnltruth merged; U3 if it lands first | F4/F7 (hooks kept) |
| 8 | S2.3, S2.4 | After S1b | pnltruth merged | F4/F7 |
| 9 | S2.5 | After S1b | orcs2b merged | O2c/O2d (new pages use the kit) |
| 10 | S2.6, S2.7, S2.8 | After S1b | U3 for `treasury.html` | — |
| 11 | S3 | After S2.1–S2.4 | — | — |
| 12 | S5a, then S5b | After S4 | — | — |

**An ask to the feed work.** F4 and F7 should print their badges with the kit's `.sv-fresh`, `.sv-src` and `.sv-est` (§3.7) rather than inline styles. If F4 lands before S1a, S2.2 and S2.3 migrate its inline styles.

---

## 14. Screenshots and measurements

- **The harness exists in scratch.** It is the mapping run's tools in `scratchpad/uiplan/`:
  - `visual/measure.js`, `shots_tools/capture.js`, `common.js`, `sheet.js`;
  - `shots_tools/fixture.py`, `orcs_fixture.py`, `visual/seed.py`.
- **How it runs.** Playwright Chromium against `runserver 127.0.0.1` on a throwaway SQLite fixture:
  - every non-local request is served from local copies or aborted;
  - every state-changing POST is aborted except the login, a ticket preview and the nav visit stamp.
- **Where it lives.** It is copied to branch `claude/handoff` under `handoff/tools/visual/` (never merged; the fixture password is read from the environment, not written in a file). Any session can then reproduce a before/after.
- **Before and after.** Before shots come from `main` at the PR's base, after shots from the PR branch: same fixture, same widths (390, 1280, 1440, 1920, 2560), same states (rail closed and open, each popover, the ticket preview). `sheet.js` lays the pairs side by side for the operator.
- **Measured per shot:**
  - first content y and reading height;
  - horizontal offenders and inner scrollers;
  - ellipsised count and the text-size histogram (share under 11 px);
  - computed contrast failures;
  - fixed-chrome overlaps and rail overlap;
  - status-bar hidden width;
  - console errors;
  - running infinite animations.
- **What goes into each PR.** The numbers and the list of screenshot pairs go into the PR body. The images go to the operator as files, never into git.
- **In CI.** The geometry checks that matter also exist as measured Django tests (the `_chrome()` pattern). They run on every PR where the runner has Chrome, and are skipped, not failed, where it has none.

---

## 15. Decisions, risks, and what is not in this plan

**Decisions for the operator (in the French note):**
1. **Palette, faces and calm background**, approved on the preview page (V).
2. **S2's page order.** Default: ticket and instrument, positions, home, signals and portfolio, cockpits, money settings, login and lock, the rest.
3. **Light mode.** Default: kept working and frozen at today's colours (only the faces change). Option: retire it.

**Decisions taken here (and why):**

| Decision | Why |
|---|---|
| The Eye's green is for live and selection, and gains move to jade | Finding 2 |
| REAL stays the only solid red, at #CC3A40 | Approved convention; 4.94:1 |
| DEMO stays gold | Approved; its collision with warnings is mitigated by form |
| ASCII minus kept | Flash direction; spreadsheets |
| Buttons carry words; only the buy/sell actions carry market colours; protective actions use the stop variant, not red | §10 |
| Ticket inputs' float tails left to the ticket work | Rounding changes what is sent |
| LWC stays 4.1.x; drawings on option B | Map 2 §9 |
| Drawings stored per user and instrument, timeframe as visibility | Map 2 §10 |

**Risks:**
- **Wider faces.** Inter and JetBrains Mono are wider than Rajdhani and Share Tech Mono, so S1a can create truncation in tight places until S1b and S2. The S1a PR measures the shell and fixes its own overflow; page leftovers are listed for S2.
- **Test churn.** About 50 test files read CSS or templates: the map counted 48, and a grep for stylesheet names finds 51. Every update states whether it pins a look (updated) or a meaning (kept).
- **Rebase churn on `base.html`.** It has 7,752 lines and three branches edit it. S1a stays CSS-first; S1b waits for railfilters and pnltruth; S2.1 waits for ticketnet.
- **Light mode.** Untested beyond "computes the same colours". If he uses it, a later light kit is a separate stage.
- **The feed raises the tick rate.** S4's coalescing and cache must land before F7 goes live on the chart. If F7 comes first, it must not raise the chart's tick rate until S4 ships.

**Not in this plan:**
- No new trading feature, order type or alert (on drawings or elsewhere).
- No change to what the engine, the bots, the Orcs or the gates read.
- No lightweight-charts v5 migration and no TradingView Advanced Charts.
- No redesign of the Wall, the Book or the investor panel.
- No light-theme polish; no styled tooltips.
- No command palette (a Bloomberg-style "go to" bar would fit later).
- Deleting the dead `frontend/` React folder is a separate cleanup task.
