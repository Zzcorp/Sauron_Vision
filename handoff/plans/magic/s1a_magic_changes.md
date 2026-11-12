# S1a, the magic kept: the change list (v2, 2026-11-07)

**Where it goes.** Against `/home/user/Sauron_Vision/.claude/worktrees/uis1a` (claude/uis1a). It was read at b37cde1. The S1a workflow has since finished at c6f1822, and every anchor used here is still present there. Main has since moved to 15dd487 (Oculus O0), which touches none of the files this list edits, and no branch has a `portfolio` migration 0020 yet. It is built on top of the S1a branch:
- **after** the S1a workflow in flight finishes (merge of main, three reviews, fixes, full suite);
- **before** the S1a pull request opens.

Nothing here was written to that worktree: this is the plan for it.

**Three commits, one PR:**

| Commit | Changes | What it is |
|---|---|---|
| 1. "UI plan S1a: the magic kept" | C1–C7, C9 | Display only. `{% get_ambience %}` answers "magic" until commit 2 adds the field |
| 2. "UI plan S1a: Ambience Magic, Calm or Off" | C8 | A profile field, its migration `portfolio/0020`, a view, the menu control. The deploy sheet says **migrate before restart**: the profile is read on every request (`get_theme`, the idle lock) |
| 3. "The fill event says whether it filled" (optional; may become its own PR) | C10 | A UI event's payload, in two money modules. Without it, a bot's fill does not flare |

The look can be reverted without reverting a migration, and the reverse.

**Commit messages:**

> 1. UI plan S1a: the magic kept. The Eye-lit palette, Orbitron titles (without digits) and Rajdhani nav, light on what lives, opaque cards, calm embers on the pages that opt in, the Eye's breath and gaze, and moments for proven events only. Money direction: none. Display only.
>
> 2. UI plan S1a: Ambience Magic, Calm or Off, saved on the profile. Money direction: none. Display only. Deploy: migrate before restart.
>
> 3. fill_open says whether the order filled, and a held order's fill is announced. Money direction: none: a UI event's payload.

**Rules kept:**
- The words, forms, PIN steps, confirm steps, focus order and live hooks (UI plan §10, §11) are unchanged.
- REAL stays the only solid red, and never a light.
- No figure is ever lit, and none sits on the void.
- No control that moves money takes the Eye's green.
- No text is under 11 px.
- No network, no broker, no model.

**Reference.** The design, the measurements and the board are `magic_spec.md`, `Signature.dc.html` and `shots/`.
- `A:` is claude/uis1a. Line numbers are b37cde1's: `A:base.html` is `templates/base.html`, and `A:sauron.css`, `A:sv-kit.css`, `A:sv-tokens.css` are under `static/css/`.
- **The line numbers are b37cde1's.** c6f1822 committed the S1a workflow's last edits (its worktree is clean) and moved lines in `sauron.css`, `sv-kit.css` and `base.html`. Anchor each change by the selectors and comment markers quoted here, not by line number.

**Size.** M: about 300 lines of CSS, 2 new JS files (`sv-embers.js` about 12 KB, `sv-moments.js` about 5 KB), 1 field and its migration, 1 view, 1 tag, 1 control, 3 template lines (`orc_detail.html`, two opt-ins) and the tests.

**Order of work.** Tests first, red; then C1 to C10; then the harness pass (Acceptance, at the end).

---

## C1. Tokens: the Eye-lit ladder, light, faces (`A:sv-tokens.css`)

**Change:**
- **The ladder** (`:root`, the §3.1–§3.2 block): twelve values, each at S1a's OKLab lightness, hue 160:

  | Token | S1a | Eye-lit |
  |---|---|---|
  | `--sv-bg-0` | #070A09 | #040B07 |
  | `--sv-bg-1` | #0C1110 | #07130C |
  | `--sv-bg-2` | #121918 | #0D1B14 |
  | `--sv-bg-3` | #182120 | #14231B |
  | `--sv-bg-4` | #1F2A28 | #1B2C23 |
  | `--sv-line-1` | #1B2422 | #14261D |
  | `--sv-line-2` | #26322F | #1D3528 |
  | `--sv-line-3` | #36443F | #2C4739 |
  | `--sv-ink-1` | #E9EFED | #E6F1EA |
  | `--sv-ink-2` | #B4C0BC | #ACC4B6 |
  | `--sv-ink-3` | #8A9894 | #839B8D |
  | `--sv-ink-4` | #59655F | #55665D |

- **The faces** (after the font tokens):
  - `--sv-font-display: "Orbitron", "JetBrains Mono", "Inter", sans-serif;`. Frame titles only, in capitals. Its digits fall back to JetBrains Mono, because Orbitron is loaded without them (C2).
  - `--sv-font-frame: "Rajdhani", "Inter", sans-serif;` for the nav rows and the brand subtitle.
  - `--sv-track-display: .16em; --sv-track-overline: .18em; --sv-track-brand: .24em;`
  - `--sv-fs-nav: calc(var(--sv-fs-base) + 2px);`, so 15, 16 and 17 px across the tiers.
  - `--sv-font-brand` stays and reads `var(--sv-font-display)`.
- **Light:**
  - `--sv-glow-brand-text: 0 0 12px rgba(0,232,104,.45), 0 0 2px rgba(0,232,104,.3);`
  - `--sv-glow-edge: 0 0 8px rgba(0,232,104,.75), 0 0 2px rgba(0,232,104,.9);`
  - `--sv-glow-dot: 0 0 6px rgba(0,232,104,.7);`
  - `--sv-glow-up-in: inset 0 0 0 1px rgba(36,181,130,.55), inset 0 0 12px rgba(36,181,130,.22);` and `--sv-glow-down-in` with 255,107,110: **inset only**.
  - `--sv-spill-active: linear-gradient(90deg, rgba(0,232,104,.13), rgba(0,232,104,.03) 55%, rgba(0,232,104,0) 80%);`
  - `--sv-edge-hero: linear-gradient(90deg, rgba(0,232,104,0), rgba(0,232,104,.85) 28%, rgba(120,255,180,.95) 50%, rgba(0,232,104,.85) 72%, rgba(0,232,104,0));`
  - **v1's `--sv-glow-primary` and `--sv-glow-focus` are not added** (C3).
- **The void:**
  - `--sv-void-light: radial-gradient(900px 360px at 46% -110px, rgba(0,232,104,.10), rgba(0,232,104,.025) 50%, rgba(0,232,104,0) 74%);`
  - `--sv-void-vignette: radial-gradient(140% 120% at 50% 28%, rgba(0,0,0,0) 55%, rgba(0,0,0,.42) 100%);`
  - `--sv-void-grain`: the board's `feTurbulence` data URI; `--sv-grain-opacity: .07;`
- **Motion:** `--sv-dur-breath: 6s; --sv-dur-moment: 1200ms; --sv-dur-sweep: 900ms;`
- The light-mode block is untouched. It is frozen and carries no glow.

**Tests first** (in `tests/test_design_tokens.py`, updated deliberately, and the new `tests/test_magic_layer.py`):
- **`PALETTE` takes the twelve new values.** This is a look, so it is updated with its reason. Every computed contrast test runs unchanged. The minimum stays ink-3 on bg-4 at 4.92:1 (S1a 4.93).
- **New `test_the_eye_lit_ladder_keeps_s1a_lightness`.** For every token, the OKLab L is within 0.003 of S1a's value, so no contrast can drift. Hue is 150–170 and chroma at most 0.045.
- **New `test_light_is_the_eye_or_a_side_only`.** Every `--sv-glow-*`, `--sv-edge-*` and `--sv-spill-*` value uses only rgba(0,232,104), rgba(120,255,180), rgba(36,181,130) or rgba(255,107,110). None uses `--sv-real` or another red. The side tokens are `inset` only.
- **New `test_no_text_glow_token_but_the_brand`.**
- **New `test_no_primary_or_focus_glow_token`.**

**Acceptance.** The contrast table of `magic_spec.md` §3.1, recomputed in the test. Every text role is at 4.5:1 or better on every surface.

---

## C2. Faces: three links, Orbitron without digits, a whitelist, Rajdhani on the nav

**Change:**
- **`A:base.html`, the font links** (after `<link rel="preconnect" href="https://fonts.googleapis.com">`). S1a's second link (`Orbitron:wght@700&text=SAURON%20VISION`) becomes two:
  - `https://fonts.googleapis.com/css2?family=Orbitron:wght@400..900&amp;text=ABCDEFGHIJKLMNOPQRSTUVWXYZ%C3%80%C3%81%C3%82%C3%84%C3%87%C3%88%C3%89%C3%8A%C3%8B%C3%8E%C3%8F%C3%94%C3%96%C3%99%C3%9B%C3%9C%20%C2%B7%E2%80%94%E2%80%93-%26%27%E2%80%99()%2F%3A.%2C!%3F%23%2B%25&amp;display=swap`. The capitals, the Latin-1 capitals and the title punctuation, **no digit**. Checked live: one 4.9 KB variable subset, weights 400–900, whose `unicode-range` holds no 0–9.
  - `https://fonts.googleapis.com/css2?family=Rajdhani:wght@600&amp;display=swap` (15.7 KB latin).
  - Their comment says why: `text=` applies to the whole request, and a digit must never be drawn in Orbitron.
- **`A:sauron.css`'s `--font-display` stays Inter.** S1a's 35 rules on it keep Inter: symbols, figures, buttons, PIN keys, the user's initials.
- **`A:sv-kit.css`, new block "§4 The display face, on the frame only":**
  - **Rule:** `font-family: var(--sv-font-display); font-weight: 600; text-transform: uppercase; letter-spacing: var(--sv-track-display)`.
  - **Selectors:**
    - `.sidebar-brand h1` (the brand);
    - `.topbar-title` (15 px);
    - `.card-title` (both definitions; 12 px, ink-2);
    - `.sv-panel-title`;
    - `.sc-heading-title` (the day diagram);
    - `.modal-title`, `.kbd-modal-title`, `.gollum-dialog .gl-title`;
    - `.nav-section` (11 px, `--sv-track-overline`, ink-3);
    - `.il-title`, at weight **900**, as main;
    - the new `.sv-overline` (11 px, .2em, ink-3: page-head overlines in S2).
  - **The wordmark:** `.brand-text` letter-spacing `var(--sv-track-brand)`, 16 px.
  - **`.sv-plain`** (`font-family: var(--sv-font-sans)`, letter-spacing as a label) for a money word inside a title. **`A:templates/dashboard/orc_detail.html:3`** wraps its `LONG` / `SHORT` in it. This is the only page title with a money word today.
- **The lock** (`A:sauron.css`, the idle lock block):
  - `.il-clock` takes `var(--sv-font-mono)` at weight 400: a clock is a figure.
  - `.il-sub` (9 px) and `.il-standby` (10 px) rise to 11 px.
- **Nav rows:** `.nav-link { font-family: var(--sv-font-frame); font-weight: 600; font-size: var(--sv-fs-nav); letter-spacing: .02em; }`. This replaces S1a's `.nav-link` size in its nav block; the 2 px edge is kept.
- **The subtitle:** `.sidebar-brand .subtitle { font-family: var(--sv-font-frame); font-size: 12px; letter-spacing: .3em; }`.
- **Faces named literally under `base.html`.**
  - `A:templates/_partials/passation_card.html` (included on every page while a hand-over is due) names `'Orbitron'` and `'Rajdhani'` for its kicker and its sentences. They point to `var(--sv-font-display)` and `var(--sv-font-sans)`, and `'Share Tech Mono'` points to `var(--sv-font-mono)`.
  - The same goes for `dashboard/passation.html` if it still names them when the commit is built (the S1a workflow in flight edits it).

**Tests first:**
- **`FaceTests.FONT_LINKS`** takes the three links. This is a look, updated with its reason.
- **`test_the_font_links_are_exactly_section_4_1`** is updated deliberately:
  - "Rajdhani" is now allowed in `base.html`, as the 600 link only (the assertion at `tests/test_design_tokens.py:337`);
  - it still forbids `Share+Tech+Mono` and the full `Orbitron:wght@400;500;600;700;800;900`.
- **New `test_orbitron_is_loaded_without_digits`:** the Orbitron link carries `text=`, and its decoded value holds no 0–9.
- **New `test_the_display_face_is_on_the_frame_only`:**
  - it parses `sauron.css`, `sv-kit.css`, **and every `<style>` block and `style=""` attribute of the templates rendered under `base.html`, partials included**;
  - Orbitron and Rajdhani appear only through the tokens, and only on whitelisted selectors;
  - no whitelisted selector matches a figure class (`.sv-num`, `.mono`, `td.num`, `.sv-kpi-value`, `.stat-value`, `.metric-value`, `.dv`, `.ip-pnl`, `.dh-val`, `.dh-chg`, `.wl-sym`, `.sr-sym`, `.pos-pop-sym`, `.gate-key`, `.tk-px`), a button (`.btn`, `.sr-pop-btn`, `.sv-dialog-btn`) or a chip (`.sv-chip`, `.sv-world`, `.sv-side`).
- **New `test_no_money_word_in_orbitron`:**
  - static: in every `{% block page_title %}` and every `.card-title` / `.sv-panel-title` element of the templates, no literal BUY, SELL, REAL, LONG or SHORT outside `.sv-plain`;
  - measured: on the harness pages, no element computing Orbitron has one in its text.
- **New `test_rajdhani_is_on_the_nav_rows_and_the_subtitle_only`.** The same parse, with `.nav-link` and `.sidebar-brand .subtitle` as the whitelist.
- **Measured** (new class in `test_magic_layer.py`, the `_measure` pattern of S1a's shell tests; skipped without Chrome), on /command/, /positions/ and /instruments/NAS100/ at 1280, 1440 and 1920:
  - `.topbar-title` and `.card-title` compute Orbitron, and `.nav-link` computes Rajdhani;
  - **every text node holding a digit inside an element computing Orbitron:** CDP `CSS.getPlatformFontsForNode` gives Orbitron no more glyphs than the node has characters other than digits. On the board, the probe "NAS100 · 30D WINDOW #12" gives Orbitron 15 glyphs and JetBrains Mono 8;
  - every element whose own text is a figure computes JetBrains Mono or Inter;
  - no text under 11 px.

**Acceptance:**
- The shell's text under 11 px stays 0.
- Nav-label widths stay within ±2 px of S1a's (measured in scratch: −1.5 to +1.1 px on the seven longest).
- First-visit fonts: +19.5 KB over S1a.
- Screenshot pairs 01, 08 and 09 at 1440 show the titles in Orbitron, and the digits of the instrument page's title in JetBrains Mono.

---

## C3. Light on the frame (`A:sv-kit.css`)

Every rule here sits under `body:not(.light-mode)` and under `:is([data-sv-ambience="magic"], [data-sv-ambience="calm"])`. **Off is S1a exactly.**

**Change:**
- **The wordmark.** S1a's `body:not(.light-mode) .sidebar-brand h1 { text-shadow: none; }` (the nav block) stays for Off; Magic and Calm take `text-shadow: var(--sv-glow-brand-text)`.
- **The active nav row.** S1a's `.nav-link.active` keeps the ink-1 text and adds:
  - `background: var(--sv-spill-active), var(--sv-bg-3)`;
  - `.nav-link.active::after { content: ""; position: absolute; left: -2px; top: 4px; bottom: 4px; width: 2px; background: var(--sv-eye); box-shadow: var(--sv-glow-edge); }` (`.nav-link` is already relative);
  - the icon in `var(--sv-eye)` with `filter: drop-shadow(0 0 4px rgba(0,232,104,.55))`.
- **Live dots.** `.sv-fresh--live::before`, `.sv-live-dot`, `.status-dot.online` and the band's live `.dh-dot` take `box-shadow: var(--sv-glow-dot)`. They are static: `.sv-live-dot` alone beats, as in S1a.
- **Selected tab and segment.** Their inset underline takes `0 4px 10px -6px rgba(0,232,104,.6)` as well.
- **The focus ring** stays S1a's 2 px Eye outline. No halo.
- **No glow on `.btn-primary`.** It is also the PIN-guarded TURN ON that arms real money (`A:templates/dashboard/ops.html:129`), and Reserve this amount, Mark withdrawn and Correct (`withdrawals.html:143, 178, 232`), and the Save buttons (`setup.html`, `brokers.html`).
- **Money buttons: their side's light, on hover and focus only, inside their own box, never on a disabled one** (each rule carries `:not([disabled], .disabled)`, as c6f1822's disabled look does). S1a's rest (`box-shadow: none`) stays, and S1a's hover washes stay.
  - Jade (`var(--sv-glow-up-in)`):
    - `.sr-pop-btn.sr-pop-btn-act` (a bullish card);
    - `.sr-gone-row[data-side="long"] .sr-gone-btn.sr-gone-btn-ticket`;
    - `.tk-long`;
    - the kit's `.btn.btn-buy`.
  - Coral (`var(--sv-glow-down-in)`):
    - `.sr-pop-btn.sr-pop-btn-short`;
    - `.sr-popup:has(.sr-pop-dir-bearish) .sr-pop-btn.sr-pop-btn-act`;
    - `.sr-gone-row[data-side="short"] .sr-gone-btn.sr-gone-btn-ticket`;
    - `.tk-short`;
    - the kit's `.btn.btn-sell`.
  - **No light, named:**
    - `.sv-dialog-btn--go`, the TAKE TRADE dialog's confirm, neutral until S2.1 gives it its side;
    - `.btn-primary`;
    - `.btn-danger` (CLOSE, RETRY CLOSE, CLOSE ALL, turn off, all off);
    - the REAL family.
- **The hero card, new `.sv-panel--hero`.** The kit shows it; pages adopt it in S2, O1, OC1 and E1.
  - `border-color: var(--sv-line-3)`.
  - `::before` is the edge: `left: 14px; right: 14px; top: -1px; height: 1px; background: var(--sv-edge-hero)`.
  - `::after` is the glow **above** the card: `top: -14px; height: 13px; left: 12%; right: 12%; background: radial-gradient(60% 100% at 50% 100%, rgba(0,232,104,.30), transparent)`.
  - No corner marks.
  - **Dark when its figure is not live:** `.sv-panel--hero:has(.sv-fresh--stale, .sv-fresh--closed, .sv-fresh--ref, .sv-est)::before, ::after { content: none }`.
  - **Dark around a world marker:** the same for `:has(.sv-world--live, .sv-venue--live, .tk-venue--live, .sv-armed-pill, .sv-adv-world.is-live, .pos-pop-venue.is-live, .hq-tag--live, .hq-brk--live, .ib-env--live, .bk-env--live)`. The last six are the labels c6f1822 made REAL chips.
- **Light mode:** none of this applies.

**Tests first:**
- **New `test_no_figure_is_ever_lit`:**
  - Static: no rule whose selector matches a figure class (C2's list) sets a `text-shadow` other than `none` or the bg-0 halo, a `filter`, a `box-shadow` carrying 0,232,104 or a side colour, or a gradient or translucent `background`.
  - Measured on /command/ and /positions/ under Magic, **at rest and at each moment's peak** (the kit's play buttons): **every text node that holds a digit** has:
    - `text-shadow: none`, or one whose every colour is bg-0;
    - `filter: none`;
    - no Eye or side box-shadow on itself or on an ancestor up to its cell or card.
  - S1a's 600 ms neutral wash is the one allowed translucency, named by its class.
  - The board's checker is the reference: `magic/tools/check_board.js` (97 figures, 0 lit, at rest and at the three peaks).
- **New `test_real_never_glows`.** The world family (`.sv-world--live`, `.sv-armed-pill`, `.tk-venue--live`, `.sv-venue--live`, `tr.sv-row--live > td:first-child`, and c6f1822's REAL chips `.sv-adv-world.is-live`, `.pos-pop-venue.is-live`, `.hq-tag--live`, `.hq-brk--live`, `.ib-env--live`, `.bk-env--live` with `.hq-acct--live`'s edge) has no `0 0 Npx` shadow and no text-shadow. The one named exception is S1a's focus outline: `.sv-armed-pill` is a link. This extends S1a's `test_the_world_family_reads_sv_real`.
- **`tests/test_money_controls_look.py` (updated):**
  - **forced states:** with `:hover` and `:focus-visible` forced on every §10 control (CDP `CSS.forcePseudoState`), no computed `box-shadow`, `text-shadow` or `filter` carries 0,232,104;
  - every side glow is `inset` only;
  - **neighbours:** with each money control forced into hover or focus, every other element's box within 24 px stays pixel-identical to rest;
  - at rest every money button's computed `box-shadow` is `none`;
  - a bearish card's act button lights coral, never jade;
  - `test_btn_primary_is_the_light_primary_not_a_green_slab` and `test_turn_on_is_no_green_slab` gain the forced hover and focus states.
- **New `test_off_is_s1a`.** Under Off, with hover and focus forced, the shell's computed `box-shadow`, `text-shadow` and `filter` equal S1a's.
- **New hero tests** (kit page):
  - a hero holding `.sv-fresh--stale` computes `content: none` on `::before` and `::after`;
  - the same around a world marker;
  - static: no template puts `sv-panel--hero` on an element that holds a world marker;
  - the 14 px band above every hero touches no text holding a digit.
- **New `test_light_only_on_light_sources`.** Every rule using a `--sv-glow-*` token belongs to the whitelist above.

**Acceptance:**
- Measured: 0 figures lit; 0 text under 4.5:1 on its ground (S1a's shell check, unchanged).
- A crop of the active nav, a live dot and the kit's hero card at 1440, DPR 2.

---

## C4. The void and opaque cards (`A:sauron.css`, `A:sv-kit.css`)

**Change:**
- **The void, on two composited fixed layers, never `background-attachment: fixed`.**
  - Measured in scratch (`magic/cost/cost_layers.json`): v1's `background-attachment: fixed` on `<body>` made the main thread repaint it. On a CPU slowed 4× it cost 413 ms/s at rest against 157 ms/s for the layered void, and the embers fell to 50.6 fps against 60.1.
  - Under `body:not(.light-mode):is([data-sv-ambience="magic"], [data-sv-ambience="calm"])`:
    - `body::before { content: ""; position: fixed; inset: 0; z-index: -2; pointer-events: none; will-change: transform; background: var(--sv-void-light), var(--sv-void-vignette); }`;
    - **the grain:** `body::after { content: ""; position: fixed; inset: 0; z-index: -1; pointer-events: none; will-change: transform; background-image: var(--sv-void-grain); opacity: var(--sv-grain-opacity); }`.
  - `<body>` keeps its flat bg-0. The canvas (z-index 0) and `.app-layout` (`position: relative`, above it) stack over both, so the order is: the light, the grain, the embers, the layout.
- **Opaque cards.** `body:not(.light-mode) :is(.card, .stat-box, .metric, .signal-item) { background: var(--sv-bg-1); }`.
  - S1a keeps main's gradient on them (the "UNIFIED PREMIUM CARD SYSTEM" block): `rgba(8,20,16,.92)` at 60 % and `rgba(6,14,10,.88)` at 100 %, so the lower 40 % is 8–12 % see-through.
  - That gradient covers 496 elements in 92 templates (counted at b37cde1); 10 `.sv-panel` are opaque.
  - Over the void its stops read within about 6 levels (of 255) of bg-1, so the look barely moves: the lower edge of a card lightens slightly.
- **Words on the void**, the new `.sv-on-void` (the kit's `.sv-page-head`, for S2, wears it):
  - `text-shadow: 0 0 3px var(--sv-bg-0), 0 0 8px var(--sv-bg-0), 0 0 14px var(--sv-bg-0);`. This is a dark halo, not a glow.
  - The embers dim near these words (C5): the halo alone is not enough at the embers' brightness.
  - A page head's age or source line sits on `.sv-pill--solid` (bg-1, line-2) and wears no halo.

**Tests first:**
- Measured:
  - `body::before` computes the two gradients under Magic and Calm, and `display: none` (or no content) under Off and in light mode;
  - no element computes `background-attachment: fixed`.
- Measured: `.card`, `.stat-box`, `.metric` and `.signal-item` compute an opaque background in dark mode.
- **New `test_no_figure_on_the_void_or_glass`**, measured on every harness page (01, 08, 09, `/ops/`, `/design/kit/`). For each text node that holds a digit, walk up its ancestors:
  - none may be translucent (a `background-color` alpha between 0 and 1, or a gradient with a stop under alpha 1) before the first opaque one;
  - that first opaque one is not `html` or `body`;
  - S1a's 600 ms wash is excepted by its class.
- `.sv-on-void` words on the kit page meet 4.5:1 against the brightest pixel within 2 px of their glyphs, with the brightest ember the script would draw there (its own `alphaAt`) passed behind them. The scratch measure is `magic/tools/void_contrast.js`.

**Acceptance.** **v1's line "S1a's ground check still finds every card opaque" is withdrawn: no such check existed.** It is replaced by `test_no_figure_on_the_void_or_glass` passing on the five pages, and on every page that opts into the embers (C5).

---

## C5. Calm embers, on the pages that opt in

**Change:**
- **`A:sauron.css`, the ambient hide list** (the rule that ends `#particles-canvas, #caustics-canvas, .se-cs-paragraph { display: none !important; }`):
  - `#particles-canvas` leaves the list;
  - add `body:not([data-sv-embers]) #particles-canvas, body:not([data-sv-ambience="magic"]) #particles-canvas, body.light-mode #particles-canvas { display: none !important; }`.
- **The opt-in.**
  - `A:base.html`'s `<body>` gains `{% block sv_embers %}{% endblock %}`.
  - `dashboard/positions_list.html` and `dashboard/command.html` fill it with `data-sv-embers`, once `test_no_figure_on_the_void_or_glass` passes on them.
  - Any later page opts in under the same test. The instrument page waits until its `.detail-header` (the live price and the symbol on the void) sits on a panel.
- **`A:base.html`, the ambient scripts:**
  - "Cursor-tracking pupil for the background Sauron Eye", "Embers & Ash particle system" and "Mouse parallax on globe-eye + eye-glow-shadow" are replaced by `<script src="{% static 'js/sv-embers.js' %}" defer></script>`.
  - It is the measured candidate `magic/cost/sv-embers.js` v2:
    - embers born in the void map, one per 6,000 px² of void, at most 56, and ash one per 30,000, at most 12;
    - 7–23 px/s, alpha .18–.55, three sprites drawn once, one `drawImage` per ember;
    - 30 fps at most, a store at a quarter of the screen's pixels, the map built in idle slices of about 4 ms;
    - **no text**;
    - **dimmed near words on the void:** an ember within 18 px of `.sv-on-void` or `.sv-page-head` is held to alpha .18, rising back to its own at 18 px. Their boxes are read after each map, scroll and swap;
    - stats in a 240-frame ring, and `alphaAt(x, y, a)` for the tests.
  - It schedules nothing while the tab is hidden, during `sv:pin-locked`, while `body.sv-scroll-locked` is set, under Calm and Off, on a page that has not opted in, or when the page shows no void. Under reduced motion it draws one still frame.
  - The clock stays as its own small inline script, unchanged.
- **The caustics** (the script on `#caustics-canvas`) are removed with the canvas and its rule. Its layer never shows on a work page, and it was the heaviest: 2.8 fps alone in the theme map's measure.
- **The fake log lines** go with their CSS (`.se-cs-paragraph`, "Background code-stream"), if they are still in `base.html` when the commit is built:
  - "Ambient code-stream — fake "Sauron's current activity" feed", the typing loop in the Ask Sauron script, which still writes invented log lines into hidden boxes at b37cde1;
  - "Phase 64: 2 background code-stream paragraphs", its two boxes.
  
  c6f1822 guards the loop: it no longer starts while its boxes are hidden, and `sauron.css` hides them on every page under `base.html`. So the code is dead there, and it goes. Fabricated activity never ships.
- **The hidden globe, grid and circuits markup** stays hidden, as S1a has it. Removing it is S1b's cleanup.

**Tests first:**
- **`AmbientSourceTests` (updated):**
  - the hide rule no longer names `#particles-canvas`; a rule hides it outside Magic, off the opted-in pages and in light mode;
  - `test_the_particles_carry_no_tickers_and_no_prices` now reads `static/js/sv-embers.js`. It **extends** to: no `fillText`, `strokeText` or `.font =` anywhere in it, so no text ever, and the caps are at most 56 and 12;
  - new: no `se-cs-paragraph`, `TEMPLATES` or `caustics-canvas` in `base.html`.
- **`AmbientGuardNodeTests` (rewritten for `sv-embers.js`)**, run under node with the stubbed page of S1a's harness. The stub gains `document.hidden`, `body.classList`, `body.getAttribute`, a MutationObserver, `matchMedia`, `requestIdleCallback` and `elementFromPoint`:
  - opted in, under Magic, with a void: frames scheduled;
  - 0 `requestAnimationFrame` when hidden, during `sv:pin-locked` until `sv:pin-unlocked`, with `sv-scroll-locked` until removed, under Calm and Off (the canvas cleared), when not opted in, and with no void;
  - reduced motion: exactly one draw and 0 `requestAnimationFrame`;
  - the cap: ten rAF ticks 16.7 ms apart give five draws;
  - **the void map:** with `elementFromPoint` answering a card over the top half, no ember is born there; a page with no void has 0 embers;
  - **the slices:** with a stubbed clock, no slice works for more than 4 ms plus one row;
  - **near words:** `alphaAt` returns at most .18 inside a `.sv-on-void` box, and the ember's own alpha at 18 px and beyond;
  - **the stats ring** holds the last 240 frames, so a late read still sees the latest;
  - `test_the_clock_still_ticks` is kept.
- **Measured** (Chrome; skipped without it), on /positions/ and /command/ at 1440. **Counts are asserted; times are reported:**
  - under Magic: at most 31 drawn frames per second, at most 100 canvas calls and 0 text calls per drawn frame;
  - under Calm and Off, and on a page that has not opted in: the canvas computes `display: none`, and 0 frames are drawn in 2 s.
- **`ShellMeasuredTests.test_no_ambient_layer_is_displayed` (updated).** On an opted-in page under Magic, `#particles-canvas` is displayed and every other ambient layer is not. Elsewhere, none is.

**Acceptance, measured on the branch** (not the scratch pages) and pasted into the PR body as reported numbers:
- /positions/ and /command/ at 1440: Magic against Off, two 6 s windows each, process-tree CPU and main-thread ms/s;
- a 3 s scroll of /positions/ with the void on, and the remaps and the longest map slice;
- for reference, the scratch v2 harness (§4.4 of the spec; Magic 0.37 cores and 189 ms/s against 0.87 and 691 for main's embers on the same page; 49 sprites a frame at 28.7 frames/s; a CPU slowed 4×: 59.5 fps against 19.5; a 3 s scroll: 0.45 cores, the longest map slice 12 ms).

---

## C6. The Eye mark, alive (the brand block in `A:base.html`, `A:sv-kit.css` "The sidebar's mark")

**Change:**
- **The breath.** S1a's `.brand-eye-wrap::before { animation: none; opacity: 0; }` stays for Off.
  - Under `body[data-sv-ambience="magic"]`, **inside `@media (prefers-reduced-motion: no-preference)`**: `opacity: 1; filter: none; background: radial-gradient(circle, rgba(0,232,104,.34) 0%, rgba(0,232,104,.12) 36%, rgba(0,232,104,0) 68%); animation: sv-eye-breath var(--sv-dur-breath) ease-in-out infinite;`.
  - `@keyframes sv-eye-breath { 0%,100% { opacity: .5; transform: translate(-50%,-50%) scale(.88) } 50% { opacity: .95; transform: translate(-50%,-50%) scale(1.06) } }`.
  - Under Calm, and under Magic with reduced motion: the same halo, still, at opacity .7.
  - Transform and opacity only, so the compositor runs it. The gradient replaces main's blur filter.
- **The gaze.**
  - The mark's iris circles get one wrapper, `<g class="sv-brand-iris">`, inside a `clipPath` of the lid's own almond path.
  - The new `static/js/sv-moments.js` moves the wrapper up to **2.4 units across and 1 down** toward the pointer (about 2.8 px and 1.2 px at 28 px).
  - One rAF-coalesced write per pointer move, nothing while the pointer is still.
  - Off under reduced motion, outside Magic and in light mode.
- **The flare.**
  - `.brand-eye-wrap::after` (a burst and a 1 px ring in one circle) plays `sv-eye-flare` (1.2 s, `cubic-bezier(.2,0,0,1)`) when `.brand-eye-wrap.sv-flare` is set. `.sv-flare--soft` (60 %) is for `fill_close`.
  - **The trigger is `sv:eye-event` with `detail.kind` `fill_open` or `fill_close`, never `sv:position-changed`.** That event also fires for "MAY have reached the broker" (`A:base.html:3590`), a lost answer (`:3880`), the lookup's outcome even "unanswered" (`:3940`) and a close whose answer was lost (`:3998`).
  - **A `fill_open` flares only when one of these proves the fill:**
    - its payload says `"working": false` (C10);
    - or this tab's own answer for that `trade_id` says so. That is the confirmed answer (`sv:position-changed` whose detail is `{ok: true, trade_id}`, the dispatch at `:3627`) without `working`, or the lookup's `{state: "booked", trade_id}` without `working`. The socket event waits up to 4 s for that answer.
    
    A `fill_open` for a trade id whose answer said `working: true` never flares. Without either proof there is no flare: until C10, a bot's fill does not flare.
  - One flare per trade id, ever (`detail.data.trade_id`). At most one per 1.5 s. The class is removed on `animationend`.
  - Calm: one soft glow, no ring. Off and reduced motion: none.
- `.sidebar-brand .brand-eye` stays still: the mark itself never floats.

**Tests first:**
- **Node** (`sv-moments.js` with a stubbed page):
  - `fill_open` with `working: false` flares; with `working: true` it does not;
  - `fill_open` without `working`:
    - followed within 4 s by this tab's `{ok: true, trade_id}` without `working` for the same id: one flare;
    - followed by the same answer with `working: true`, or by nothing: no flare;
  - **the detail shapes of the dispatches at `:3590`, `:3880`, `:3940` and `:3998`, on their own, give no flare**;
  - one HTTP answer plus one socket event for the same trade give exactly one flare, in either order;
  - `fill_close` flares soft; `quote`, `notification` and `run_complete` do not;
  - nothing under reduced motion or Off;
  - the gaze writes nothing without a pointer move.
- **`test_at_most_two_infinite_animations_and_only_the_meaningful_ones` (updated):**
  - Magic allows exactly `sv-heartbeat`, `sv-armed-beat` and `sv-eye-breath`; Calm and Off allow the first two;
  - **under reduced motion, 0**;
  - measured on /command/ and /positions/ at the four widths.

**Acceptance.** Measured infinite animations: 3 under Magic, 2 under Calm and Off, 0 under reduced motion. A 6 s capture of the kit page shows the breath and one flare, from the kit's "play a fill" button.

---

## C7. Moments (`static/js/sv-moments.js`, `A:sv-kit.css`)

**Change:**
- **The fill's light, `.sv-row-light`.**
  - It is one overlay element that `sv-moments.js` places in the table's container, on the row's **bottom hairline**: 2 px, the hairline itself and one faint pixel above it, where no text reaches.
  - It runs from the row's left edge **to the action cell's left edge**, so CLOSE never takes it.
  - No `box-shadow`. One 900 ms sweep of `background-position`. Removed on `animationend`.
  - Placing the light as a background of the row was tried: Chrome sizes a row's background per cell, and the light showed at rest.
- **`.sv-moment-arrive`:** the same light along a card's top edge, 900 ms.
- **`.sv-moment-icon`:** the dock's signal icon lights once, 1.2 s. It is a radial light behind the icon; the count's bubble stays opaque above it. v1 put the ring on the count's bubble, which lit a figure.
- **The keyframes** animate only the opacity and `background-position` of these moment elements. They never animate a content element's colour, transform or size, and never a button.
- **What counts as new:**
  - **A fill:** a proven `fill_open` (C6) arms a watch for its `trade_id`, which expires after 60 s. The positions region's next `sv:live-swapped` lights the `tr[data-sv-position-row]` that holds `[data-sv-close-trade="<trade_id>"]`, and only that row.
  - **A new signal:**
    - a card on the rail's swap (`.sr-signal-wrap[data-signal-id]`) is new only if it was not on the rail before **and** its `data-created` is later than the rail's high-water mark (the newest `data-created` seen at load and after each swap);
    - only the server's clock is compared, never the browser's;
    - at most 3 per swap, plus the dock's icon;
    - ↺ BRING BACK and a filter change bring older cards, so they mark nothing.
  - **A stop moved** keeps S1a's own flash: the approved neutral wash, 600 ms. Nothing new here; the chart's level line is S4's.
- **Calm:** the lights fade in place; they do not travel. **Off and reduced motion:** none. The information still arrives through S1a's washes and the words.
- Each moment plays once per event id. A refresh without a proven event plays nothing.

**Tests first:**
- Node:
  - the event to class mapping;
  - once per id;
  - none under reduced motion or Off;
  - a swap without a proven fill marks nothing;
  - **a fill for trade A never lights row B**;
  - **↺ BRING BACK marks nothing**, and neither does a filter change;
  - a swap that only re-orders the same ids marks nothing.
- Static: the moment keyframes never animate `color`, `transform`, `width` or `height`, and never target `.btn`, `button` or a figure class.
- Measured (kit page, its play buttons):
  - **at the moment's peak, at row heights 28, 32 and 44 px, no pixel inside any button's box changes by more than 2 levels**;
  - the computed `color` of the row's P&L cell is sampled every 50 ms and is constant.
  
  The board's checker does the same: at the fill's peak, every button box is unchanged.

**Acceptance.** The board's three moments, re-shot on the kit page at 1440, DPR 2.

---

## C8. His choice: Ambience Magic, Calm or Off (commit 2)

**Change:**
- **`portfolio/trader_profile.py`:** `ambience = models.CharField(max_length=8, default="magic", choices=[("magic", "Magic"), ("calm", "Calm"), ("off", "Off")], help_text="Display only: embers, light and moments.")`.
- **Migration:** `portfolio/migrations/0020_traderprofile_ambience.py`, after `0019_traderprofile_rail_prefs`. No branch has a portfolio 0020 today. Renumber before merge if another branch adds one first.
- **`core/templatetags/sauron_tags.py`:** `get_ambience`, like `get_theme`. It returns `"magic"` for anonymous users and on any error. In commit 1 it returns `"magic"` without reading the profile.
- **`A:base.html`, the `<body>` tag:** `data-sv-ambience="{% get_ambience %}"`. This lands in commit 1, with the tag's constant answer.
- **`dashboard/views.py`:** `set_ambience`:
  - POST only, `login_required`, CSRF;
  - the value checked against the choices, then `save(update_fields=["ambience"])`;
  - it answers JSON `{"ambience": …}`, 405 to GET and 400 to a bad value.
- **`dashboard/urls.py`:** `path("ambience/", views.set_ambience, name="set_ambience")`.
- **The control.** In the user menu beside the theme link: "Ambience" with three buttons (Magic, Calm, Off) and `aria-pressed`. No explanation in the menu.
  - Clicking POSTs. **Only a 200 answer that echoes the value sets `body.dataset.svAmbience`** and moves `aria-pressed`. The embers, the breath, the void and the light then react at once, through CSS and the scripts' observer, with no reload.
  - On a failure the old value stays, and the menu says "Not saved".
  - Other open tabs follow on their next page load.

**What each mode shows:** `magic_spec.md` §4.6.

**Tests first** (new `tests/test_ambience_pref.py`):
- the default is `magic`;
- POST sets the value; GET gives 405; a bad value gives 400; an anonymous user is redirected; CSRF is enforced;
- the body carries the attribute for each value;
- **decision-module scan** (pnltruth's pattern): no engine, bot, Orc, alert, gate or ticket module reads `ambience`;
- node: a 500 or a network failure leaves `data-sv-ambience` unchanged and shows "Not saved";
- measured: switching to Calm stops the canvas within one frame and sets `display: none`, with no reload.

**Acceptance.** The cost per mode from the harness (scratch: Magic 0.37 cores, Calm 0.09, Off 0.10), pasted into the PR body. The deploy sheet says "migrate before restart".

---

## C9. The kit page and S1a's own tests, updated deliberately (commit 1)

- **`templates/dashboard/design_kit.html` (`/design/kit/`)** gains:
  - the face specimen: an Orbitron title with a figure in it, a Rajdhani nav row, an Inter label, JetBrains Mono figures;
  - the Eye-lit swatches;
  - the light sources, each under Magic, Calm and Off;
  - a hero card, live and stale, and one beside a REAL chip, which stays dark;
  - a `.sv-page-head` with its solid age pill;
  - the three moments with a "play" button each (staff page, synthetic rows at 28, 32 and 44 px);
  - the Ambience control.
  
  `tests/test_design_kit_page.py` checks each one is present.
- **`tests/test_design_tokens.py`:**
  - `PALETTE` (C1), `FONT_LINKS` and the Rajdhani assertion at line 337 (C2), `AMBIENT` and its node harness (C5);
  - the infinite-animation allowance per mode and under reduced motion (C6);
  - the faces' parse, now including the templates' own styles (C2).
  
  Each is "a look, updated". The meaning tests stay as they are: 4.5:1, REAL the only solid red, nothing under 11 px, light mode frozen.
- **`tests/test_money_controls_look.py`:** C3's forced states, inset-only side glows, neighbours unchanged; REAL never glows.
- **`tests/test_live_hooks_inventory.py`:** unchanged. The magic adds no hook and removes none. The brand iris's class, the `sv_embers` block and `data-sv-embers` are new and are not hooks.

---

## C10. The fill event says whether it filled (commit 3, optional)

**Why.** `fill_open` is pushed for an order the broker holds unfilled, a WORKING entry: `A:bot_program/manual_trade.py:3823` (the same function says at `:3868-3869`: "Saying 'opened' here would be a claim about the future") and `A:bot_program/asset_engine/base.py:7597`. When such an order fills later (`_finish_working_entry`), nothing is pushed. So the Eye cannot tell a fill from a held order, and a held order's fill goes unannounced.

**Change:**
- Both pushes add `"working": bool((trade.metadata or {}).get("entry_working"))` to the payload.
- `_finish_working_entry` pushes `fill_open` with `"working": false` once the fill is booked, inside the same `try/except` pattern as the other pushes.

**Tests first:**
- the two payloads carry `working`, true for a held entry;
- the held order's fill pushes one `fill_open` with `working: false`;
- `tests/test_phase23_websocket.py` is unchanged.

**What it is.** Money direction: none. It changes a UI event's payload and adds one announcement. It touches two money modules, so the reviewers may prefer it as its own PR. C6 is safe without it: until then, only this tab's own proven fills flare.

---

## Acceptance of the PR, in one pass of the harness

**Screenshot pairs**, S1a against S1a plus the magic:
- 01 home, 08 positions and 09 instrument at 1440 and 1920;
- `/design/kit/` at the four desk widths;
- a 6 s capture of the kit page (breath, one fill, one new signal).

**Measured:**

| Check | Target |
|---|---|
| Text under 11 px in the shell (the idle lock included) | 0 |
| Shell text under 4.5:1 | 0 |
| Figures lit, at rest and at each moment's peak | 0 |
| Text holding a digit on the void or on a translucent ground (five pages, and every opted-in page) | 0 |
| Digits drawn in Orbitron | 0 |
| Orbitron text holding BUY, SELL, REAL, LONG or SHORT | 0 |
| §10 controls with the Eye's green, hover and focus forced | 0 |
| Button pixels changed by a moment (more than 2 levels) | 0 |
| Solid red fills that are not REAL | 0 |
| Infinite animations, Magic / Calm / Off / reduced motion | 3 / 2 / 2 / 0 |
| Drawn ember frames | ≤ 31/s |
| Ember canvas calls per frame, text calls | ≤ 100, 0 |
| Frames drawn when paused (hidden, lock, dialog, Calm, Off, not opted in, reduced motion) | 0 |
| Pages that scroll sideways | none |
| Console errors | 0 |

**Reported, not asserted** (machine-dependent): CPU cores per mode, main-thread ms/s, the ember draw time, fps under 4× throttling, the scroll run, the map's slices.
