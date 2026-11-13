# Redoing every old-design element: the pull requests, in order

Written 2026-11-13 for the operator's request "refaites aussi tous les éléments du vieux design svp, tout, pour s'imbriquer dans le nouveau svp". Base: main 349b1ca (#106, S1a and the magic). The inventory these batches empty is `inventory.md` (104 rows, numbered there and cited here as #n). Read-only planning: nothing was written in the repository.

## The rules every batch keeps

- **Display only, shippable alone.** One PR per batch. Every commit says "Money direction: none. Display only." The engine, the bots, the Orcs, the gates, the ticket's execute path and every switch see what they see today.
- **§10, the money controls' look contract, binds.** Words, forms, PIN steps, confirm steps and focus order never change; only the look does, and the look never misleads. `tests/test_money_controls_look.py` stays green; where a row says "until S2.x", that batch updates the pin to the §10 look on purpose and says why.
- **§11, the live hooks contract, binds.** No batch renames or drops a hook. B0 first adds the hooks merged since S1a (#105's one-price hooks, the marquee's), so `test_live_hooks_inventory` sees them.
- **The magic stays** (operator, 2026-11-07, merged in #106): Orbitron titles without digits, Rajdhani 600 nav rows, the Eye-lit palette, the light sources of `magic_spec.md` §3.2 (wordmark, Eye mark, active nav row, live dots, selected tab, a live hero card's edge, a side's inset light), embers on pages that opt in, Ambience Magic/Calm/Off. Nothing else glows.
- **The marquee stays** (operator, 2026-11-13): both strips scroll continuously and stop on hover. It is built on `claude/marquee`; no batch plans against it. B1 rebases on it and keeps `SVMarquee`, `data-sv-marquee-speed` and `data-sv-marquee-pop`.
- **Tests first, measured.** Each batch opens with a commit that puts its pages and states on the guard's strict list ("no element on these pages outside the tokens": B0's census at zero for them) and its own measured checks. That commit is red on main; the display commits make it green.
- **Never weaken a test.** A test that pins a look is updated to the new look with the reason in the commit; a test that pins a meaning (REAL is the only solid red fill, unknown is an em-dash, a stale price stops printing, the PIN is asked) stays.
- **Synthetic data only** (the repository is public): fixtures, screenshots and tests never use his account. Before/after pictures go to him as files, never into git.
- **UI yields to money work.** When a money branch touches the same template, the UI batch rebases after it.
- **The cross-cutting rows** of the inventory (#17–#22, #24, #46, #78–#80, #86, #87: the Eye's green as an accent, text under 11 px, words in the number face, inline styles and page blocks, chip and card families, scripts that paint colours, gains painted in the Eye's green, gold warnings, states drawn as gain/loss chips, dialog families, loops, old faces) shrink in every batch that touches their pages; B24's guard holds them at zero.

## Why this order

1. **B0 first, before S1b.** It is tests only, takes a day, conflicts with nothing, and it is what makes every later batch measurable: without it a batch cannot prove "nothing on these pages is outside the tokens", and other work (money branches keep adding templates) could add old looks while the redo runs.
2. **The shell next (B1–B4), as the plan says (S1b).** It is on every page: the frame, the floating buttons, the menu, the cards and menus that open from the bands, the bar and the rail, the panels.
3. **The shared pieces (B5).** The KPI strip, the labels, the card recipe, checkboxes, messages and motion sit on about fifty pages: one CSS-first PR changes them all at once, the largest visible gain after the frame, and it makes every page batch after it smaller.
4. **His pages, most used first (B6–B10).** The plan's default order, which he was shown and did not change: the ticket and the instrument page (he trades from it, and TAKE TRADE opens from the rail on every page), positions (he watches it), home, signals and portfolio, then the chart (S4) that sits on the instrument page.
5. **The pages he sees sometimes (B11–B15)**: cockpits, the Oculus, the money settings, the bots, login and lock.
6. **The long tail (B16–B21)**, one PR per nav section, the section he opens most first (The markets: /instruments/).
7. **Every width (B22, S3)**, once the pages are on the kit; then **the public pages, report and emails (B23)**, then **cleanup and the final guard (B24)**.

## The batches at a glance

| # | Batch | Plan stage | What he will see | Hours | Waits for |
|---|---|---|---|---|---|
| B0 | The measuring stick | (new) | Nothing (tests only) | 6–8 | — |
| B1 | The frame | S1b | Content 92 px from the top instead of 184; one band, a thin bottom bar; Gollum, the Eye and the Horde in the bar; nothing floating on his tables; the rail a real column | 30–38 | `claude/marquee` merged |
| B2 | The menu and one icon family | S1b | One family of thin icons, no colour emoji; a compact menu with sections that fold | 12–16 | B0 (can go before B1) |
| B3 | The shell's cards and menus | S1b | Quote, news, rail and bar cards, bell, user and sessions menus in the kit's look; a moving price gets a brief tint instead of glowing | 18–24 | B1 |
| B4 | The shell's panels | S1b (unstaged there) | The Horde, Council, Activity, Ask Sauron, Gollum's window, the tour and the "?" sheet in the kit's look | 16–22 | B1, B3 |
| B5 | The shared pieces | S2 (shared) | On ~50 pages at once: readable labels, calm key-figure tiles, cards that stop lifting and glowing, one look for messages, quiet checkboxes, no sliding | 14–18 | B0 |
| B6 | Ticket, TAKE TRADE, instrument page | S2.1 | A summary of the warnings at the top of TAKE TRADE, warnings in orange, a confirm in the trade's colour; a compact instrument header | 18–24 | B5; the steppers PR (before or after, never with) |
| B7 | Positions | S2.2 | The table fits at 1440, normal quantities, white symbols, CLOSE ALL with ■, a clear close window, the position page's REAL chip in solid red | 24–30 | B5, B6; U3 |
| B8 | Home /command/ | OC1 (replaces S2.3) | His eToro money first, his positions high, one page, the loop folded at the foot | 28–36 | OC0 merged |
| B9 | Signals, portfolio, small charts | S2.4 | Kit tiles and tables; small charts with jade gains and a five-colour donut | 14–18 | B5 |
| B10 | The instrument chart | S4 | Full-height chart, one row of tools, jade/coral candles, OHLC in the chart, tags that no longer pile up | 30–40 | B6 (can run beside B7–B9) |
| B11 | Cockpits | S2.5 | /ops/ as a dense filterable list; OFF in grey, a REAL chip by every real-money switch, PIN and TURN ON aligned | 16–22 | B5 |
| B12 | The Oculus | O1 (Oculus plan) | The Oculus plan's approved look | 14–18 | B5 |
| B13 | Money settings | S2.6 | Readable forms with units; the broker's world choice explained with its chips; warnings in orange | 16–20 | B5; U3 for /treasury/ |
| B14 | Bots and pools | S2.6 | REAL never drawn as a loss; ON/OFF in words; PAUSE with ■; no sonar ring | 14–18 | B11 |
| B15 | Login, PIN, lock, pop-out | S2.7 | The same moments in the new faces and colours, the Eye kept, no invented prices, PIN boxes that say what they unlock | 14–18 | B5 |
| B16 | Long tail: The markets | S2.8 | /instruments/, calendar, news, Big Money, liquidations on the kit | 14–18 | B5 |
| B17 | Long tail: What can act | S2.8 | Strategies, setups, rules, ladder, personalities, events | 8–10 | B5 |
| B18 | Long tail: What is measured | S2.8 | Evidence, performance, forensics list, backtests, calibration, council | 10–14 | B5 |
| B19 | Long tail: What is invented | S2.8 | Evolution, research, briefing, mind, lore and the rest | 14–18 | B5 |
| B20 | Long tail: The machine | S2.8 | Admin panel (ARM LIVE with its REAL chip), system map, health, tasks, audit, the Eye pages | 18–24 | B5 |
| B21 | Long tail: You, off-nav, the book's tail | S2.8 | Profile (PIN and password windows), notifications, letters, getting started, hand-over, bot sub-pages, tax lots, bot charts | 12–16 | B5 |
| B22 | Every width | S3 | Every page right at 1280–2560; tablet usable; phone: sheets, stacked tables, money buttons big enough for a finger | 24–32 | B6–B9 (after B21 is best) |
| B23 | Public pages, report, emails | outside the plan | The Wall, the Book, the investor page, the report and the emails in the new look | 16–24 | his yes (default yes) |
| B24 | Cleanup and the zero-old-design guard | (new) | Nothing visible; nothing old can come back | 8–12 | all above |
| | **Total** | | | **410–540 h** (about 470) | |

Hours are working hours for one agent session per PR: the build, the tests, one review round and its fixes. CI (about 46 minutes a run on the 2-vCPU runner), his deploy and the French sheet for each deploy come on top. OC0's own review and merge (needed by B8, not old-design work) is 4–6 h more.

---

## B0. The measuring stick (tests only)

**Scope.**
1. `tests/test_live_hooks_inventory.py` takes in the hooks merged since S1a, counted on main: #105's `data-q`, `data-q-f`, `data-q-side`, `data-q-spark`, `data-q-title`, `data-q-dot`, `data-q-state`, `data-q-bars`, `data-q-target`, `data-q-stop`, `data-q-ref`, `data-q-o`, `data-q-max`, `data-q-fam`, `data-q-below`, `data-sv-quotes`, `data-sv-now`, and `svCharts[id].setNow/.caption/.series/.bars`. The marquee's `data-sv-marquee-speed`, `data-sv-marquee-pop` and `window.SVMarquee` join here if `claude/marquee` merged first, else in B1. (Plan §11: "the inventory takes them in when it merges".)
2. `tests/test_zero_old_design.py`, **source half** (no browser, always runs): a census of old markers per file over every template (`templates/**/*.html` and `bot_program/templates/**/*.html`), `static/css/*.css`, `static/js/*.js`, `core/templatetags/*.py` and the Python that emits colours (`dashboard/views_bot_charts.py`, `dashboard/reports.py`). Budgets in `tests/old_design_budget.json` start at today's counts; a count may only go down; a file absent from the budget must be at zero; a failure prints `file:line` and the marker. The markers are listed under "The final guard" below.
3. Same file, **measured half** (`_Chrome` over the CDP pipe, as `tests/test_close_advice.py` and `tests/test_magic_layer.py` do; pages rendered through the test client on a synthetic fixture, opened as files; skipped where no Chromium): `tests/old_design_census.js` (beside `tests/horde_dom_harness.js`), a port of this run's `olddesign/runtime/tools/collect.js` (the token set of `sv-tokens.css`, the magic's light sources, the role rules), runs on every routed page and on the states. Per-page budgets in the same JSON; the STRICT list is empty at B0.

**Pages.** All 105 routes (94 that extend `base.html`, 11 standalone), with their parameters filled from the fixture, and about 25 states (listed under the final guard).

**What he will see.** Nothing.

**Money and hooks.** Adds the hooks to the inventory; changes no display.

**Tests.** These are the tests. Green on main by construction (budgets = today).

**Risks.**
- CI time: the measured half must stay under about 5 minutes (one Chrome, pages as files, no server, 1440 only; other widths in B22). It can be its own CI job, in parallel with the suite. GitHub's ubuntu runner ships Google Chrome, which `_chrome()` finds on the PATH; confirm on the first run.
- False positives: the census reuses the runtime sweep's rules, already run over 93 scenes; any rule that flags a kit component is a bug in the rule, fixed here.
- Fonts: served locally, as `test_magic_layer` does, so the font census is stable.

**Size.** 6–8 h. **Waits for.** Nothing.

## B1. The frame (S1b, part 1)

**Scope.**
- `base.html` topbar (615-816) to 44 px: title on the left on one line (the longest, /oculus/'s, fits), then the UTC clock, sessions N/14 (no inline colour), the feed pill, a reserved slot for F7's "live prices paused" chip, the armed pill, bell, lock and user.
- The two strips (819-855; restore tabs 846-855) become one 32 px market band holding the two scrolling lanes of `claude/marquee` (prices, then news), same driver, speeds and pause on hover; the hide/restore tabs on the kit (no gradient, no glow). Below 1440 the news lane folds into a "News N" chip (plan §6.2). Alternative if he prefers: two strips of 28 px.
- Content start: first content line at y ≤ 100 (about 92), gap 16.
- Bottom strip (879-1494) to a 32 px status bar: PORTFOLIO, OPEN P&L, POSITIONS, SIGNALS, BOT, ALERTS, DRAWDOWN and HORDE always show, the rest behind "+N" below 1920; dropdowns open upward (railfilters' click-to-open kept); minimise tab, restore pill and ▶ arrows go.
- Gollum (6590-6650) becomes a 24 px avatar at the bar's left end (his bubble above the bar for 6 s, then a count dot); Ask Sauron's Eye (6652-6720) a 28 px Eye at its right end; the Horde tab (`_partials/the_horde.html:33-66`) a bar cell.
- COUNCIL and ACTIVITY tabs (`council_band.html:26-41`, `activity_drawer.html:23-33`, `sauron.css:3549-3565`) become icons with badges in a 40 px right dock; their panels open over the rail column, never over the page. The '<' edge toggles go.
- The rail (1512, 1532-1697) becomes a grid column, 300/340/380 px by tier; collapsed, the 40 px dock with counts and direction dots in up/down (`signal_rail_items.html:104`'s inline Eye dot goes).
- Sidebar 232/240/256 by tier, 56 collapsed (the nav's rows are B2's).
- §6.3: `container-type: inline-size` on `.page-content` and cards, the 12-column grid with the tier's gutter, `.sv-p1/.sv-p2/.sv-p3`, KPI strips capped at 8, prose at 72 ch.
- The shell's own inline styles (490 per page) move to classes; `sauron.css:2550`'s `filter: brightness(1.1)` on REAL ARMED goes.
- Files: `base.html` (shell regions), `sauron.css` shell sections (57-58, 1138-1260, 1591-1609, 1869-1930, 1939-2006, 2231-2404, 2550, 3549-3565, 7195-7253), `sv-rail.css` (frame only), `sv-horde.css/.js`, `sv-council-band.css/.js`, `sv-activity.css/.js` (launch points only), `sv-tour.js` (anchors), the three partials.

**Inventory rows.** #1–#7 (#7's layout), #10, #11, #12 (shell part), #23, #41.

**What he will see.** About 120 px more to read at every desktop size; one band at the top where prices and news keep scrolling; a thin bar at the bottom where the important cells always fit; Gollum, the Eye and the Horde in that bar instead of on his tables; Council and Activity from the right edge; the rail narrows the page instead of covering it; titles on one line.

**Money controls to keep (§10).**
- World markers: the REAL ARMED pill moves into the 44 px row and stays the only solid red (#CC3A40, white at 4.94:1), its beat kept, no filter.
- Every price and P&L cell in the band and the bar: no count-up, no colour flash, stale stays stale; `sv-venue.js` (the feed's painter, F7) untouched.
- The bar's POSITIONS dropdown CLOSE keeps `data-sv-close-trade` (its look is B3's); the rail cards' TAKE TRADE and PASS keep S1a's look.

**Live hooks to keep (§11 and #105), counted in B1's files at 349b1ca.** `data-sv-live` ×38, `data-sv-live-key` ×15, `data-sv-live-status` ×4, `data-decimals` ×7, `data-flash` ×4, `data-sv-count` ×2, `data-sv-at` ×8, `data-sv-close-trade` ×5, the `data-sv-overlay` family, `data-nav-page-id`, `data-sv-fhost` ×4, `data-sv-list` ×4, `data-sv-rail-n` ×7, `data-sv-gone`, `data-market` ×2, `data-sv-shut`; `data-q` ×34, `data-q-f` ×15, `data-q-side` ×7, `data-q-title` ×8, `data-q-spark`, `data-q-bars`, `data-q-fam` ×3 each, `data-q-target`, `-stop`, `-o`, `-max`; ids `signalsRail`, `railSignals`, `railSignalsBody`, `hbSignalRows`, `clock`, `svBannerStack`; classes `.sv-unknown` ×60, `.sv-age`, `.sv-row--live`, `.sv-sel-bar`, `.sv-pinned` ×13, `.sv-world--*`; globals `svTakeTrade`, `svTakeTradeAsset`, `svCloseTrade`, `svRenderSparks`, `svWheelMarquee`, `svLiveRefresh`; the marquee's hooks. The JS phone boundary (768/769) does not move.

**Tests to write first.**
- Guard: the shell regions of every page strict (topbar, band, status bar, dock, rail dock, sidebar frame).
- New `tests/test_shell_geometry_measured.py` at 1280, 1440, 1920 and 2560, rail open and closed: first content y ≤ 100 (today 184); no fixed shell element intersects `.page-content`'s inner box (today 5 controls); status-bar hidden width 0 (today 424 at 1440); content right ≤ rail left; the topbar title on one line; at 390 the phone tier unchanged.
- REAL ARMED: computed `filter: none` under `:hover`; background `--sv-real`.
- Updated deliberately (looks): `test_the_horde`, `test_gollum`, `test_council_band`, `test_activity_drawer`, `test_tour`, the seven `test_headband_*`, `test_ticker_and_banners`, `test_expand_does_not_vanish`, `test_popup_persistence`, `test_overlay_scrolls`, `test_marquee`, `test_magic_layer` (the brand block in the 44 px row). Kept: `test_money_world`, `test_money_controls_look`, `test_one_quote_screens`, `test_live_hooks_inventory`.

**Risks.**
- `base.html` (8,511 lines) is edited by the marquee on the same lines (the strips, `svWheelMarquee`, the drag), and later by F7 (the painter): B1 starts after the marquee merges and keeps the painter untouched.
- The "+N" overflow must not move a cell under the pointer when a value ticks (rule 7): fixed cell widths.
- Things move that he knows by heart (Gollum, the Eye, the Horde, Council, Activity): the French note says so before the deploy.
- The rail as a column narrows pages not yet redone: the guard measures every page at 1440 with the rail open, and new truncation fails B1.
- The magic's light in the brand block (now the 44 px row) must look the same under Magic, Calm and Off.

**Size.** 30–38 h. **Waits for.** `claude/marquee` merged; B0.

## B2. The menu and one icon family (S1b, part 2)

**Scope.**
- New `static/icons/sv-icons.svg`: about 45 symbols on a 24-unit grid, 1.5 px stroke, `currentColor`, drawn after Lucide (ISC notice in the file), including the tower E1 (Barad-dûr) expects. New `{% icon %}` tag in `core/templatetags/sauron_tags.py`.
- Replaced: the 62 nav marks (`base.html:484-598`), the footer's ⬢ and ⏻, the phone nav's ◎ ✦ ☰ (1524-1528), the topbar's ☀/☾, 🔒/🔓, ▼ and bell, the user menu's ◉ ⚿ ⌗ ★ (749-809), the glyphs inside page titles (⚖ ⚠ ✉ ⌘ ⇩), the shell's glyph buttons (⚙, ✕, ⇔, ▸); the 21 inline SVGs at five stroke widths.
- The nav: 32 px rows, Rajdhani 600 15 px kept (the magic), Orbitron section heads kept and made collapsible (state per browser; storage read in try/catch); the collapsed tooltip `#navMiniTip` on bg-2 with a line-2 border, no gradient, no glow.

**Inventory rows.** #7 (icons), #8, #9.

**What he will see.** One family of thin line icons in the menu and the top bar, never a colour emoji on Windows or a Mac; a slightly narrower menu whose sections he can fold.

**Money controls to keep.** None is a money control. The lock-now button keeps its title and action; REAL ARMED is untouched.

**Live hooks to keep.** `data-nav-page-id` (nav activity), `#clock`, the tour's nav anchors.

**Tests to write first.**
- Guard: the sidebar and the topbar cluster strict, including a CDP glyph census: every glyph in the nav and topbar is drawn by the sprite or one of the four faces (today DejaVu Sans, IPAGothic, Noto Color Emoji).
- `test_nav_grouping`'s glyph rules become "every nav row names an icon that exists in the sprite" (updated deliberately, as plan §9 says).
- New: every sprite symbol has `stroke-width` 1.5 and `currentColor`; nav rows measure 32 px; a folded section stays folded after a reload.

**Risks.** 62 pages need 62 symbols he can tell apart (the PR lists the mapping); E1 waits on the tower; the active row's Eye edge and spill (the magic) must stay.

**Size.** 12–16 h. **Waits for.** B0. It touches `base.html` 460-607 only, so it can go before B1 if the marquee is late.

## B3. The shell's cards and menus (S1b, part 3)

**Scope.**
- Popovers on the kit's anatomy (§7: bg-2, line-2, radius 6, header with title and ×, scrolling body, sticky footer); railfilters' placement, click-to-open, pinning and scrolling are not redone:
  - the quote card `.dh-pop`: the inline Eye colours (`dh_item.html:45, 64, 72-75`, `base.html:1650`) become `.up`/`.down`; values in JetBrains Mono; volume grouped; the source through `src_name`;
  - the news, ticker and dwell cards (`.tnp-*`, `.tp-*`, `.nf-pop`): Eye calls to action become ghost or secondary buttons; sentiment and urgency become `.sv-side`/`.sv-state` with words;
  - the bar's dropdowns (`.ip-dropdown`): "▸ View …" become ghost buttons, "◉ LIVE" a `.sv-state`, quantities through `qty`, ages "12 s, 3 min" (plan §4.4), and **CLOSE stays neutral on hover** (no coral);
  - the rail card (`.sr-popup`): the actions row's Eye border and the urgency chip's inline margin go; ages in the §4.4 form;
  - `.pos-pop`; the instrument preview (`base.html:4340-4380`, inline styles to classes, a gain's price in jade); the live-status list (5420, 5444).
- The topbar menus (bell, user, sessions) on the kit's menu: bg-2, 32 px items, no glow, no text glow, no 8 px slide; the logout in ink.
- The price flash (`sv-venue.css` only, `sv-venue.js` untouched): the cell's background takes the up/down wash for ≤ 600 ms, the number never glows (§8, binding); a stale age in amber (§3.7).
- The open rail (`sv-rail.css`, tokens only): score dot without glow; urgency as `.sv-state` warn with whole words; the watchlist chips on the kit's washes; ⚙ from the sprite.
- The trading-event banners (`#svBannerStack`, behaviour kept) and the hand-over card become the kit's Notice.

**Inventory rows.** #13, #35–#40, #75, #76, and #24's shell scripts.

**What he will see.** Every card that opens from the price band, the bottom bar and the rail, and the bell, user and sessions menus, in the kit's calm look; a gain in jade, never in the Eye's green; a price that moves gets a brief tinted background instead of glowing; urgency words no longer cut ("HIG").

**Money controls to keep (§10).**
- Quote card LONG/SHORT: as the deal ticket's sides (already the kit's).
- Signal card TAKE TRADE / ADD TO POSITION in the signal's side, PASS ghost (already the kit's): only the leftovers around them change.
- The bar's CLOSE: neutral outline at rest and on hover, never red. This deliberately changes `test_headband_position_row`'s hover pin. The earlier review wanted the button to warn "once reached for"; the warning stays in words (its title and the close dialog), not in a loss colour.
- Every price cell: background wash only, at most once a second per cell (the feed's own limit), stale shown stale.
- World chips inside the cards: REAL solid red only.

**Live hooks to keep.** The `data-q` family (`sv-venue.js` reads the cells; only its sheet changes), `data-sv-close-trade`, `svTakeTrade`, `svTakeTradeAsset`, `.sv-pinned`, `data-sv-fhost`, `data-sv-list`, `data-sv-rail-n`, `data-sv-gone`, `data-f-toggle`, `data-f-gone`, `data-market`, `data-f-shutoff`, `data-f-shut`, `data-sv-shut`, `SV.popup`, `SV.dwell`, `SV.ages`, `#svBannerStack`.

**Tests to write first.**
- Guard strict on these states: quote card, news card, ticker card, dwell card, the bar's dropdowns (PORTFOLIO, POSITIONS, SIGNALS), rail card bullish and bearish, bell, user menu, sessions menu, live-status list, instrument preview, a fill banner.
- Measured: a moved `[data-q]` cell has `text-shadow: none` and a washed background; the bar's CLOSE under `:hover` has no coral in border, text or background; no popover text under 11 px; ages printed as "N s", "N min", "N h", "N d".
- Updated deliberately: `test_headband_position_row`, `test_headband_hover_lives`, `test_popup_persistence`, `test_overlay_scrolls`, `test_live_notification_banners`, `test_passation`, the rail tests that read `sv-rail.css`. Kept: `test_one_quote_screens`.

**Risks.** Money buttons live inside these cards (side colours and the ghost PASS must not move); the age format change touches tests that read `timesince` text; `sv-venue.js` belongs to the feed (F7): only its sheet changes here.

**Size.** 18–24 h. **Waits for.** B1.

## B4. The shell's panels (the plan said "unchanged"; "tout" includes them)

**Scope.**
- The Horde's sheet (`sv-horde.css:235-580`): links in ink-2, meters on the kit's score meter, lens pills as `.sv-seg`, the demo stripes become the DEMO outline chip with its word, risk lines in the number face only for the numbers, notes in Inter, buttons on the kit; the "levels" command neutral, not ringed in coral.
- The Council band (`sv-council-band.css:200-440`): FOR and AGAINST as words with a mark in ink, never the Eye's green; jade and coral only where a seat argues a long or a short.
- The Activity drawer (`sv-activity.css:140-252`): 360 px (§7), chips and dots on the kit, details in Inter, an error row as the danger Notice.
- Ask Sauron's panel (`sauron.css:4051-4370, 6694-6978`; `base.html:6757-6800, 7836-7848`): opaque bg-2 bubbles (no blur), header and buttons on the kit, the input on the kit, answers' headings and links in ink, table heads 11 px, the greeting in classes. Its "working" light stays only while it answers (kept by S1a).
- Gollum's dialog, the tour cards (`sv-tour.css`), the "?" sheet and the shortcut toast (`sauron.css:817-873`) on the kit's dialog and Notice.

**Inventory rows.** #54, #71–#74, #88, #89 (and #80's shell dialogs).

**What he will see.** The Horde, the Council, the Activity, Ask Sauron, Gollum's window, the tour and the "?" sheet in the kit's look: opaque, readable, no green glows.

**Money controls to keep (§10).** The Horde sheet's CLOSE (neutral, never red), its ADD (the side's colours), its levels editor launch (the editor itself is B7's); the Council never colours a verdict as a gain or a loss. Nothing changes in what the panels do.

**Live hooks to keep.** `SV.council`, `SV.tour`, `SV.overlay` and the `data-sv-overlay` family, `svTakeTrade`, `svCloseTrade`, `svLevels` (`sv-horde.js:1794-1886`); the JS phone boundary in `sv-horde.js:64`, `sv-council-band.js:51`, `sv-activity.js:53`.

**Tests to write first.**
- Guard strict on: the Horde open (both lenses), the Council open, the Activity open, Ask Sauron open with a canned answer rendered by its own renderer (no model call), Gollum's dialog, a tour step, the "?" sheet.
- Measured: no `backdrop-filter` anywhere; no panel text under 11 px; the Horde's CLOSE computes to the kit's neutral outline.
- Updated deliberately: `test_the_horde`, `test_gollum`, `test_council_band`, `test_activity_drawer`, `test_tour`, the Ask Sauron panel's look pins.

**Risks.** The Horde carries money commands; Ask Sauron's tests must never call a model; the Council's FOR/AGAINST must stay readable without colour.

**Size.** 16–22 h. **Waits for.** B1, B3.

## B5. The shared pieces

**Scope (shared rules, CSS first).**
- The KPI strip (`.oc-strip-*`, `sauron.css:3389-3520, 4403-4445, 5019-5040`): label Inter 11 uppercase ink-3, value a mono figure, sub-line 11 ink-3 that wraps instead of being cut, the lead cell without the Eye gradient, opaque bg-1 cells (which also takes the figures of /evidence/, /asset-bots/, /evolution/, /big-money/ and /treasury/ off the void).
- The shared labels (`.stat-label`, `.section-label`, `.metric-label`, `.metric-sub`, `.form-label`, `.input-label`, `.form-hint`, `.input-hint`, form `p label`, `.helptext`): Inter 11–12 px at .06em.
- The legacy card recipe (`.card`, `.stat-box`, `.metric`, `.signal-item`): radius 6, line-2 border, no resting shadow or inset, no lift, no glow, no accent bars; a clickable card gets a line-3 border on hover.
- `.empty-state`: the faint Eye mark at 6 %, one sentence, one action.
- The old badge washes (`.badge-high`, `.badge-low`, `.badge-critical`) on the kit's `.sv-state` looks (amber, hollow, coral with words); gold no longer marks a priority.
- `<code>` and `.sv-ident` in JetBrains Mono 12 px on bg-3.
- The checkbox, radio, range and file skin (`sauron.css:3095-3372`): 16 px, checked = the Eye's check on bg-0, no gradient, no glow; the kit page's own "Demo account" sample is fixed by the same rule.
- Motion (`sv-motion.css`, `sauron.css:636-680`): entry ≤ 4 px over 140 ms, no cascade past 200 ms, data cards not revealed, an htmx swap keeps the last render (70 % if slow), no slide on leave, menus drop ≤ 4 px. Count-up stays on counts only.
- Django messages: one partial `_partials/messages.html` on the kit's Notice (info, warn, danger; icon and title), included by the 19 templates that render their own.

**Inventory rows.** #14, #15, #44, #45, #77, #81, #82, #83, #84 (and #19's shared part).

**What he will see.** On about fifty pages at once: labels he can read (11 px instead of 9), calm and opaque key-figure tiles, cards that no longer lift and glow under the pointer, one clear message look after a save, checkboxes that no longer glow, pages that appear without sliding.

**Money controls to keep (§10).** The /brokers/ world checkboxes (Demo, Switch world, Replace keys) become plain 16 px checkboxes with their words, nothing that invites a click (their "World" fieldset is B13's). No button changes in this batch; the card hover no longer lights any figure.

**Live hooks to keep.** `.up`/`.down` on strip values, `.sv-unknown`, `data-sv-live-key` on strip values, `data-sv-count` (count-up on counts), `SV.flash`.

**Tests to write first.**
- Guard: the shared selectors strict on every page: no `.oc-strip-label`, `.stat-label`, `.metric-label`, `.form-label` under 11 px or in JetBrains Mono; no `.card` with a transform or box-shadow on hover; no checkbox with a gradient or a glow; `.empty-state` text ≥ 4.5:1; no animation translating more than 4 px.
- Measured on `/design/kit/`: the checkbox sample matches §7. On the five pages above: no figure on a see-through ground.
- Updated deliberately: `test_motion`, `test_card_responsiveness`, `test_design_kit_page`, the tests that read a page's message markup.

**Risks.** A page block that re-declares a shared class still wins until its own batch: the guard's per-page budgets show what remains. The messages partial touches 19 templates (merged one at a time, low conflict).

**Size.** 14–18 h. **Waits for.** B0. Its files (`sauron.css` shared sections, `sv-motion.css`) do not overlap B1's, so it can move earlier if B1 waits on the marquee.

## B6. The ticket, TAKE TRADE and the instrument page (S2.1)

**Scope.**
- The deal ticket (`deal_ticket.html` classes only; `sauron.css:7555-7652` into the kit): labels ≥ 11 px in Inter, prices JetBrains Mono 15/500, the REAL chip, the stale dash and the fixed width kept.
- The TAKE TRADE / ADD dialog (`base.html` sizeDialog: markup and class hooks only):
  - a warning summary pinned under the header, "⚠ N warnings: TITLE · TITLE", that expands on click;
  - the warnings as the kit's warn Notice (amber with ⚠ and a title in Inter 12), not DEMO's gold, not mono prose;
  - field labels ≥ 11 px; the meter on the kit's score meter;
  - the confirm in the side's colours (BUY up outline, SELL down outline, the side's inset light of the magic);
  - the world chip in the header; #94's outcome states in the same look.
- The instrument page (`instrument_detail.html`, style 94-191 and 30 inline styles, onto the kit): a 56 px hero row (`.sv-panel--hero`, lit only while live): symbol, star, price as a JetBrains Mono hero, the change signed with ▲/▼, the freshness badge (§3.7), the market state as `.sv-state`; his position on the symbol on `.sv-table` with P&L in up/down and the target in up; the grid below. Its four Eye rules go. Embers only after the no-figure-on-the-void proof.

**Inventory rows.** #25, #26, #27 (and #46's and #16's parts on this page).

**What he will see.** The ticket's words readable and its prices crisp; in TAKE TRADE, a line at the top that says how many warnings there are and which, the warnings in orange, the confirm in jade for a buy and coral for a sell, REAL/DEMO/PAPER in the title; a compact instrument header with the price large in the number face and its age.

**Money controls to keep (§10).** Deal ticket SELL/BUY (down/up outlines; never moves as prices tick; stale stops printing a price); TAKE TRADE/ADD (header with side, symbol and world chip; the REAL top edge when live or funding; the summary pinned; Cancel neutral; words, focus, PIN and execute unchanged); leverage in words and mono; the ticket's PIN step; `tk-venue`; every price and P&L cell.

**Live hooks to keep.** `data-ticket`, `data-dq` ×3, `data-decimals` ×4, `data-mark-source`, `data-instrument-live` ×2, `data-q` ×12, `data-q-f` ×10, `data-q-title`, `.tk-stale`, `.sv-unknown` ×5, `svTakeTradeAsset` ×5 and `base.html`'s `svTakeTrade`; the chart's `json_script` ids (printed by the page; the chart's inside is B10's); `sv-instrument-live.js` untouched (F7).

**Tests to write first.**
- Guard strict on /instruments/EURUSD/ (live), /instruments/BTCUSD/ (paper), the TAKE TRADE dialog on paper (the existing preview path) and on a live world (a synthetic preview payload, never posted).
- Measured: no ticket or dialog text under 11 px; the ticket does not move when `.tk-px` changes length (kept); the confirm's computed border is `--sv-up` on a BUY and `--sv-down` on a SELL; with one warning or more, the summary lies inside the dialog's first viewport and its count equals the number of warnings; no warning painted in `--sv-demo`; the REAL chip in the header of a live order.
- Updated deliberately: `test_deal_ticket`, `test_money_controls_look` (DealTicketLookTests and the dialog's row: S1a pinned the confirm "neutral until S2.1"), `test_pretrade_controls`, `test_venue_split`. Kept: `test_money_world`, `test_one_quote_screens`, the PIN tests.

**Risks.** The steppers PR (`scratchpad/fleet/steppers_spec.md`) edits the same dialog: one goes first, never both at once (if the steppers merge first, B6 restyles them as a kit component). The number and order of warnings are words: unchanged. C1–C3 (REAL | DEMO on the ticket) will be built on this look.

**Size.** 18–24 h. **Waits for.** B5; the steppers PR ordered.

## B7. Positions (S2.2)

**Scope.**
- `positions_list.html` (style 685-1053 and 54 inline styles onto the kit): KPI tiles in one row at ≥ 1440; the table on `.sv-table` with column priorities and a row detail (›) for the Orc line and secondary facts; symbols in ink-1, never broken; `qty` and `px` (no 8-decimal values); the P&L cell as `.sv-pnl` + `.sv-fresh` + `.sv-est`; the sticky CLOSE column kept; CLOSE ALL as the stop variant ■ with "(whole book)"; the hover and focus marker as a background, never the left edge; the broker table's BUY and P&L in side and polarity colours; the capital card, the analytics (3 columns at ≥ 1680) and the filter on the kit.
- `_positions_metrics.html`, `_position_summary.html`, `capital_card.html`, `position_filter.html`, `close_selection_bar.html`, `sv-close-advice.css` (skin only): the checkbox is the Eye (selection), the bar on bg-2; CLOSE SELECTED neutral-strong, not coral; the advice as words with a mark, never coral or the Eye's green.
- The close dialog's content (`base.html` closeFlow): P&L in up/down with its source line, Mark with its freshness badge, the REAL chip for a live row, the PIN label saying what it unlocks ("PIN · closes a live position (real money)"), the PIN field `.sv-pin-field`.
- The level editor (`.lvl-dlg`, `sauron.css:7520-7553`, `sv-level-edit.js` behaviour untouched) on `.sv-dialog`: labels 11 px, inputs mono with units, Save primary, warnings amber.
- The position page `/forensics/<id>/` (style 17-202 onto the kit): its close confirm neutral-strong (no solid coral), **the REAL chip the solid REAL chip** (`{% money_world %}`), OPEN/WORKING as `.sv-state`, the P&L hero in mono up/down, "Should I close?" a secondary button, "Close this position" readable.

**Inventory rows.** #28–#34 (and #46's and #80's parts here).

**What he will see.** The positions table fitting at 1440 without sideways scrolling, rows of 32–44 px instead of 165, quantities in normal digits, white symbols, his P&L with its source and age, CLOSE ALL with the square; a calm close window that gives the P&L in its colour, the price's age and REAL in red; the position page with its REAL chip in solid red, not gold.

**Money controls to keep (§10).** CLOSE and RETRY CLOSE (neutral, sticky right column, RETRY with the amber "closing" chip); the close dialog (P&L up/down with its source; Mark with its freshness; world chip; confirm neutral-strong "CLOSE …"; the PIN for real rows unchanged); CLOSE ALL (stop variant in the table head; preview with world chips; "(whole book)" when filtered); the close PIN; world markers (the REAL edge never covered on hover or focus); the level editor's words and steps; every P&L cell.

**Live hooks to keep.** `#svCloseAll` ×2, `data-sv-close-trade`, `data-sv-close` ×2, `data-sv-overlay`, `data-sv-live` ×6, `data-sv-live-key` ×29, `data-sv-live-status` ×2, `data-decimals` ×2, `data-mark-source` ×2, `data-sv-at`, `data-q` ×5, `data-q-f` ×3, `data-q-side` ×5, `data-q-title` ×2, `data-q-ref`, `.sv-unknown` ×19, `.sv-age`, `.sv-row--live` ×2, `.sv-sel-bar`, `svLiveRefresh` ×4, `svCloseTrade`; `sv-close-advice.js` behaviour.

**Tests to write first.**
- Guard strict on /positions/ (rail open and closed, 1280/1440/1920), the close dialog (live and paper, synthetic previews), the level editor, /forensics/<id>/ (live and paper), the selection bar and the advice cards.
- Measured: the table's scrollWidth ≤ clientWidth at ≥ 1440 (today 1,815 in 1,034); CLOSE inside the viewport; row height ≤ 44 with the detail closed (today 165); no mid-word break in a symbol cell; no `\d+\.\d{8}` in the table's HTML; a REAL row's first cell keeps the 3 px `--sv-real` inset under `:hover` and `:focus-within`; CLOSE ALL carries ■ and `.btn-stop`; on /forensics/<id>/ no solid red fill except the REAL family, and the REAL chip's background is `--sv-real`.
- Updated deliberately: `test_position_page`, `test_position_card_ux`, `test_gain_shows_percent`, `test_close_advice` (skin pins, its measured selection-bar test), `test_close_liveness`, `test_money_controls_look` (the close dialog and CLOSE ALL rows, which S1a left "for S2.2"). Kept: `test_money_world`, `test_one_quote_screens`, the PIN tests.

**Risks.** U3 (`claude/wip-usedfix-u3`, stale since 2026-11-02) edits 5 lines of `positions_list.html`: B7 goes first and U3 rebases; if U3 is revived first, B7 rebases (UI yields). Feed F4 later patches the P&L cells through the kept `data-sv-live-key`. Every fact moved into the row detail stays reachable by click (rule 9).

**Size.** 24–30 h. **Waits for.** B5, B6; U3 coordination.

## B8. Home, /command/ (OC1 of the Operations Center plan; replaces S2.3)

**Scope.** As `plans/opscenter/opscenter_spec.md` §OC1 (his six OKs of 2026-11-07): `command.html` rewritten on the kit (its 12.3 KB style block leaves), `_command/` partials, `sv-command.css`, `sv-stage.css`; the hero leading with eToro's own figures; one page (the LIVE tab retired, its facts re-homed); the positions table (R3) with CLOSE sticky; the Day of Sauron ring folded at the foot with its text ≥ 11 px (`sv-day-scheme.css`); counts that stop wearing up/down (§8); `qty` instead of `floatformat:4`; the LIVE (real money) pill replaced by the REAL chip.

**Inventory rows.** #42, #43 (and #28's and #46's parts on /command/).

**What he will see.** What the OC plan promised: his eToro money first, his positions high on the page, one page instead of four tabs, the loop folded at the foot.

**Money controls to keep (§10).** CLOSE in the table (neutral, sticky); the three world cards (REAL solid, DEMO gold outline, PAPER grey); P&L cells; no count-up on money.

**Live hooks to keep.** `data-sv-count` ×6 (counts), `data-sv-close-trade` ×2, `data-q`, the day scheme's payload (`sv-day-live.js` gains only `data-day-collapsed-default`), the eye-event map (OC spec §6.2).

**Tests to write first.** OC1's acceptance (positions table top ≤ 460 before S1b, ≤ 380 after; page ≤ 3,200 px; 0 text under 11 px; 0 ellipses at 1280 with the rail open) and the guard strict on /command/ and its Review tabs.

**Risks.** OC0 (`claude/opscenter0`, 75 commits behind main) must be reviewed, rebased and merged first; E1 makes "/" lead to Barad-dûr, so /command/ is reached from the nav and the Eye.

**Size.** 28–36 h (OC1, L), plus OC0's review and merge (4–6 h, not old-design work). **Waits for.** OC0 merged; B7 (OC1 can reuse the positions table partial). If OC0 is not ready, B9 goes first.

## B9. Signals, portfolio and the small charts (S2.4)

**Scope.**
- `signals_list.html` (47 inline), `_signals_metrics.html`: tiles on `.sv-kpi`; "◬ ask" as ghost buttons; filter labels on the kit; symbol names never cut; score bars on the meter; CRITICAL and the state chips as `.sv-state`.
- `portfolio_overview.html` (25 inline; `:245` `floatformat:4` to `qty`), `_portfolio_metrics.html`: the P&L source line in ink-3 (not jade); the allocation donut in the categorical slots.
- The small charts' language on all seven pages that draw them: `SAURON_CHART_COLORS` values (the name is a §11 global and stays), `_chart_assets.html` (Chart.js defaults; `.sv-metric-card` to the kit tile), `sauron.css:6566-6693` (bars, donut segments, axis 11 px), `chart_line/bars/donut.html`, `views_bot_charts.py` SVG colours, the liquidations and bot-home canvases (JetBrains Mono, tokens). The eToro "now" line colour in `sv-venue.js:731-733` (the feed's file) changes in one line, agreed with F7, or reads a token.

**Inventory rows.** #47, #48, #49 (and #46's parts here).

**What he will see.** /signals/ and /portfolio/ with the kit's tiles, tables and buttons; symbols never cut; small charts where a gain is jade and a loss coral, and a donut in five distinct colours instead of the Eye's green and gold.

**Money controls to keep (§10).** P&L cells and their source lines; /portfolio/'s CLOSE copy (`portfolio_overview.html:263`, neutral); world markers.

**Live hooks to keep.** `data-sv-live` ×4, `data-sv-live-key` ×29, `data-sv-live-status`, `data-mark-source` ×2, `data-sv-close-trade`, `data-q`, `svRenderDonuts` ×4, `svRenderLines` ×4, `svRenderSparks`, `SAURON_CHART_COLORS` ×7 (name kept), `.sv-unknown` ×9, `.sv-age`.

**Tests to write first.** Guard strict on /signals/, /portfolio/ and the small charts of /positions/, /news/, /ai/, /ai/tasks/ and /strategies/. Measured: chart pixels only in the categorical slots (nominal series) or up-fill/down-fill (polarity), as this run's `canvas.js` census reads them; no canvas wider than its column; no symbol cut; no table scrolling sideways at ≥ 1440. Updated deliberately: the look pins in `test_signal_acted_and_sizing`, `test_signal_backing_warning`, `test_portfolio_live`, `test_portfolio_value_truth`, and any test reading `SAURON_CHART_COLORS` values.

**Risks.** pnltruth's lines on /portfolio/; F4 patches P&L cells through the kept hooks; `sv-venue.js` belongs to F7.

**Size.** 14–18 h. **Waits for.** B5.

## B10. The instrument chart (S4)

**Scope.** As plan S4 (`chart_widget.html`; `instrument_detail.html`'s height line only):
- Layout: full height (viewport minus chrome, minimum 480, ≥ 60 % of the viewport); one 36 px toolbar row (symbol; interval favourites 5m 15m 1H 4H D W, the rest in a menu; type, indicators and overlays menus; LOG, fit, tall, fullscreen); date ranges and the bar countdown in a bottom row.
- Colours from the tokens (`getThemeColors` read once): up-fill/down-fill candles, entry ink-1 solid, target up dashed, stop down dashed, crosshair ink-3 dashed, volume at 35 %; no Eye, no old gold.
- In the pane: the legend top-left without plates (`textContent` updates); stop and target labels as chips in the pane that avoid each other; only the last price and his entry on the axis; the last-price tag outlined (coral on bg-2, 6.40:1) instead of a solid red box; the pinned card scrollable, placed on the emptier side; captions and credit in Inter 11.
- Feel: `svCharts[id].tick` coalesced to one paint per frame (same signature), `computeGeom` cached, the SRI hash on lightweight-charts 4.1.0.

**Inventory rows.** #50–#53 and the owed "chart feel".

**What he will see.** A chart that takes the height of the screen, one row of tools with menus, candles in jade and coral, O H L C inside the chart, stop and target labels that no longer pile up on the latest candles, a pinned signal card he can scroll.

**Money controls to keep.** The PIN veil (`chart_widget.html` ≈423), the levels and position lines' meaning and editing behaviour, the tick weld rules; no red fill outside REAL (the last-price box).

**Live hooks to keep.** `svCharts` ×6 (`refresh`, `tick`, and #105's `setNow`, `caption`, `series`, `bars`), `svLevels` ×24, `svSignalDots` ×7, `svHoverCards` ×3, the `json_script` ids `<chart_id>-positions` / `-signals`, F7's `tick(price, quote)` signature.

**Tests to write first.** Guard strict on the chart region (canvas pixel census: no Eye family #00E0x0, no old gold #D0B020). Measured: 1 toolbar row at ≥ 1280 (today 2); chart height ≥ 60 % of the viewport (today 328 px of 900); the legend inside the pane; no axis tag over the last 20 bars; the pinned card scrolls. Node: 10 ticks in one frame give one `update`; the same inputs give no geometry recompute; a 60 s refresh with unchanged indicators re-creates no series. Updated deliberately: the colour, face and toolbar pins in `test_chart_surfaces`, `test_chart_signal_markers`, `test_chart_levels_widget`, `test_chart_divisions`; the other chart tests (the plan counted 475 methods in the 14 `test_chart_*.py` files) re-run unchanged.

**Risks.** The size of the chart suite; TPO and volume profile (to be redone) paint in the level layer's order; **F7 must not raise the chart's tick rate before B10 merges**; lightweight-charts stays 4.1.x.

**Size.** 30–40 h. **Waits for.** B6 (the page around it). It touches `chart_widget.html` only, so a second session can build it beside B7–B9.

## B11. The cockpits: /ops/, /orcs/, /ai-models/ (S2.5)

**Scope.**
- `ops.html` (62 inline in the template, 455 in the page): each switch row is key (JetBrains Mono), name, `.sv-state` (ON the Eye dot, OFF a hollow ink-3 ring, ERROR coral with words), last run, runs, errors, then a 180 px action column: "PIN ____ TURN ON" neutral on a PIN switch, with the REAL chip by the name of every real-money switch (`actuator_mode_live`, #102's `bots_venue_floor_live`; the Orc mind switches say what they unlock); "turn off" neutral; "all on" neutral; "all off" the stop variant ■. A dense list with sticky group heads and counts, a filter by name or state, groups that fold (a group with something ON or in error opens by default). Links in ink; keys and commands in JetBrains Mono.
- `orcs_list.html`, `orcs_seats.html`, `orc_detail.html` (the STATE sentence becomes a header note and a short state chip), `ai_models.html` (one 48 px row per tier with an inline Save; the long paragraph a lead and "more").

**Inventory rows.** #56, #57, #58 (and #79's chips here).

**What he will see.** /ops/ as a dense list he can filter, under 6,000 px with the groups folded (today 19,848); OFF in hollow grey, not red; a REAL chip by every real-money switch with "PIN ____ TURN ON" in one aligned column.

**Money controls to keep (§10).** The platform switches row entire; the bots and brakes on /ops/; the switch PIN (its label says what it turns on). Form diff: the same keys, hidden inputs (`key`, `next`, `want`) and PIN fields before and after.

**Live hooks to keep.** None of §11's sits in these files; the guard confirms none is lost. The form fields are this page's contract.

**Tests to write first.** Guard strict on /ops/, /orcs/, /orcs/seats/, /orcs/<id>/, /ai-models/. Measured: every TURN ON and turn off at the same x; page height < 6,000 px with the groups closed; no OFF chip computing to coral or red; a REAL chip in every row whose switch takes a PIN; the form diff empty. Updated deliberately: `test_ops_cockpit`, the look parts of `test_switch_texts_truth`, the switch rows of `test_money_controls_look`. Kept: `test_switch_pin`, `test_ai_models_truth`, `tests/orcs/test_orc_pages.py`.

**Risks.** A PIN switch's TURN ON must never look safe or be hidden by a folded group; O2c/O2d add Orc pages, written on the kit.

**Size.** 16–22 h. **Waits for.** B5.

## B12. /oculus/ (O1 of the Oculus plan)

**Scope.** As `plans/oculus/oculus_spec.md` §O1 (approved block order, 2026-11-12): `oculus.html` on the kit, `_oculus/` partials, `sv-oculus.css` (tokens only), gate chips in words, amber only past a threshold with ⚠, "REAL MONEY" never as coral text.

**Inventory rows.** #59. **What he will see.** The Oculus plan's look. **Money.** None (a read-only page). **Hooks.** None of §11's.

**Tests to write first.** O1's own `test_oculus_look` and the guard strict on /oculus/.

**Size.** 14–18 h. **Waits for.** B5 (O0 is merged, #97).

## B13. Money settings: /setup/, /brokers/, /withdrawals/, /treasury/ (S2.6, part 1)

**Scope.**
- `setup.html` (95 inline): labels Inter 12 px; inputs JetBrains Mono with their units outside; "blank = no cap" kept in words; Save primary; HIGH/LOW as `.sv-state`; the ⚠ in a card title from the sprite.
- `brokers.html` (62 inline): a "World" fieldset that explains REAL and DEMO with their chips; Demo, Switch world and Replace keys as plain checkboxes with their words; capability badges as `.sv-chip`; "connected" as `.sv-state`; the LIVE env as the REAL chip (not a tall red block); FORGET ETORO KEYS on one line; the intro in Inter.
- `withdrawals.html` (49 inline): Reserve and Mark withdrawn primary; Cancel and Correct neutral; the explanation in Inter; warnings as amber Notices.
- `treasury.html` (93 inline): the 13 gold warnings and states as amber Notices or `.sv-state` words; the title in the page head; cells through classes; figures on opaque grounds.

**Inventory rows.** #60–#63 (and #78's gold warnings here).

**What he will see.** Forms he can read: labels at 12 px, inputs in the number face with their units, the broker's world choice explained with REAL and DEMO chips, warnings in orange with ⚠.

**Money controls to keep (§10).** /setup/'s risk limits (MAX ACCOUNT PLEDGED, MAX BOT LEVERAGE, MAX BOT FLOOR RISK, "blank = no cap", Save); /brokers/'s Demo, Switch world, Replace keys and Trading PIN (plain checkboxes, never toggles, nothing that invites a click: his house rule is never to tick Demo); /withdrawals/'s buttons; the /brokers/ PIN. Words, forms, PIN fields, hidden inputs and confirm steps byte for byte.

**Live hooks to keep.** `data-sv-live`, `data-sv-live-status`, `.sv-row--live` ×3.

**Tests to write first.** Guard strict on the four pages; the form diff (every `<form>`'s action, method, field names, types, values, hidden inputs and PIN fields equal to main's); measured: no text under 11 px; no warning in `--sv-demo`; plain checkboxes; the REAL chip on a live broker row. Updated deliberately: the look pins in `test_setup_form_submittable`, `test_brokers_page`, `test_broker_form_clarity`, `test_withdrawals`, `test_treasury`. Kept: `test_setup_memory`, the PIN tests.

**Risks.** U3 edits 53 lines of `treasury.html`: wait for U3 or let it rebase (UI yields); the look of the Demo box must never invite a tick.

**Size.** 16–20 h. **Waits for.** B5; U3 for /treasury/ (the three other pages can go without it).

## B14. Bots and pools: /asset-bots/, /bot/, /bot/console/, /shares/, /desk/, /allocator/, /risk/ (S2.6, part 2)

**Scope.**
- `asset_bots.html`: bot on/off as B11's switch rows; the lead strip opaque.
- `desk.html` (117 inline): a live venue and mode as the REAL chip, never the loss chip; ON as `.sv-state`.
- `shares.html`, `allocator.html`, `risk_depth.html` onto the kit.
- bot `home.html` (53 inline): ARMED keeps only the armed pill's beat (the sonar ring goes); FUTURES and TESTNET as neutral chips with words (gold is DEMO only); the PIN field per §7.
- `bot_console.html`: RUNNING and PAUSED as `.sv-state`; PAUSE BOT the stop variant ■; the dead red-slab rule and the page's `.up` rule go.

**Inventory rows.** #64, #65, #66 (and #78, #79, #86's /bot/ loop).

**What he will see.** The bot pages and the capital pools in the kit's look: real money marked by the red chip, never as a loss; ON and OFF in words with a dot; PAUSE with the square; no pulsing ring.

**Money controls to keep (§10).** Bots on/off, the Morgul brake, the bot brake, /bot/'s PIN toggle, PAUSE/RESUME, the pools' world markers. Form diff.

**Live hooks to keep.** None of §11's beyond B13's set; the forms are the contract.

**Tests to write first.** Guard strict on the seven pages; the form diff; measured: no live venue computing to coral (the REAL chip instead); no infinite animation on /bot/ but the armed beat. Updated deliberately: `test_asset_bots`, `test_shares_page`, the bot program's look pins, `test_motion` (the sonar).

**Risks.** ARMED is a real-money state: the armed pill's beat and its words must stay unmistakable.

**Size.** 14–18 h. **Waits for.** B11 (the switch row).

## B15. Login, PIN, lock, idle lock, pop-out (S2.7)

**Scope.** `registration/login.html`, `login_pin.html` (and `/login/pin/forgot/`), `_key_eye.html`, `dashboard/locked.html` (now linking `sv-tokens.css`), the idle lock (`base.html:8012-8063`; `sauron.css:5571-6011, 7346-7489`), `_popout.html`:
- the new faces (Inter, JetBrains Mono, the digit-free Orbitron for titles); Share Tech Mono and the full Orbitron leave;
- the atmosphere kept as brand moments (the Eye and its embers), **without invented prices**;
- the PIN field per §7 (password, mono, .3em, `autocomplete="off"`, `inputmode="numeric"`, a label that says what it unlocks);
- Unlock, Verify and Initialize Session as the kit's primary (no green slab, no glow), contrast ≥ 4.5:1 (today 2.07–2.21);
- keypad digits in JetBrains Mono.

**Inventory rows.** #67, #68, #69, #96 (and #87's old faces here). **/intro/ is excluded** (kept exactly by his decision; `claude/introlabels` drops its invented prices on its own).

**What he will see.** The same moments, login, PIN and lock, in the new faces and colours, the Eye still there, no invented prices behind the login, PIN boxes that say what they unlock.

**Money controls to keep (§10).** PIN entries: never look optional, never autofilled, always say what they unlock; steps unchanged.

**Live hooks to keep.** `svIdleLock` (engage, release); the lock's form fields.

**Tests to write first.** Guard strict on /login/, /login/pin/, /login/pin/forgot/, /locked/, the idle lock state, /popout/. Measured: every text and button ≥ 4.5:1; no Share Tech Mono loaded; the ember canvas draws no digit; keypad digits in JetBrains Mono. Updated deliberately: `test_login_eye`, `test_lock_polish`, `test_idle_lock` (looks). Kept: `test_login_pin_gate`, `test_lock_screen`.

**Risks.** The login page is public: never an account figure. The intro is out of this batch.

**Size.** 14–18 h. **Waits for.** B5.

## B16–B21. The long tail (S2.8): one PR per nav section

Each one: neon literals become tokens, sizes go onto the scale (≥ 11 px), words leave the number face, inline styles and page blocks move onto the kit, states become `.sv-state` (never gain/loss chips), Django messages use B5's partial, the section's own modal looks become `.sv-dialog`, endless loops stop at rest (a running job may show the heartbeat dot only). **Tests first:** the guard strict on the section's pages (and the plan's sweep test: no `rgba(0,232,104` and no `font-size` under 11 px in the section's templates); the section's page tests re-run. Each checks `git log` for open branches on its templates and waits for them.

| # | Section | Pages | What changes most | Money controls (§10) | Hooks to keep | Hours |
|---|---|---|---|---|---|---|
| B16 | The markets | /instruments/, /calendar/, /news/, /news/<pk>/, /big-money/, /liquidations/ | /instruments/: 4,337 elements, 2,023 inline styles to classes, market dots as `.sv-fresh`/`.sv-state`, cards on the kit, the LOSERS filter on `.sv-seg` (no red slab); calendar day numbers in JetBrains Mono, its JS rows through classes; the news item's 137-line block; /big-money/ off the void; the liquidations canvas in JetBrains Mono | none (price cells keep their freshness) | `data-q` ×12, `data-q-f` ×9, `data-q-title` ×2, `.sv-unknown` ×16 | 14–18 |
| B17 | What can act | /strategies/ (+ detail, the wizard), /setups/, /opportunities/, /rule-control/, /promotions/, /personas/, /events/ | Ladder cards (`.sc-*`) at 11–12 px in ink; armed, verdict and stage chips as `.sv-state`; ~135 inline styles | none today (Path A's future PIN on a live promotion is built on the kit) | — | 8–10 |
| B18 | What is measured | /evidence/, /performance/, /bot-performance/, /forensics/, /backtest/, /bot-backtest/ (+ detail), /calibration/, /council/ | /backtest/'s modal on `.sv-dialog`, its pills static (no endless pulse), its JS rows through classes; /evidence/ off the void; ~260 inline styles | none | — | 10–14 |
| B19 | What is invented | /evolution/, /discoveries/, /generated/, /hypotheses/, /brain/, /knowledge/ (+ history), /lore/ (+ entry), /consolidation/, /horizon/, /intelligence/, /briefing/, /earnings-reviews/, /research/, /ai-journal/, /ai/ | /evolution/'s 448-line block (opaque registry rows, ink counts, 101 sub-11 px); /research/'s 147-line block (no endless dot at rest); briefing chips; the brain overlay on `.sv-dialog`; ~250 inline styles | none | — | 14–18 |
| B20 | The machine | /admin-dashboard/ (+ system-map, eye, books, newsletters), /eye/ (+ gate-events, fills, exposure), /health/, /ai/tasks/, /audit/ | /admin-dashboard/'s 342 inline styles; PAUSE AUTOMATION as the stop variant ■; **ARM LIVE with the REAL chip** (steps unchanged); a lane's LIVE as the REAL chip; its modal on `.sv-dialog`; the system map's edges still at rest; the Eye pages' BUY/SELL as `.sv-side` and CLOSE neutral; /health/'s gold states in amber words | ARM LIVE (real money), PAUSE AUTOMATION (protective), the Eye pages' CLOSE | the `data-sv-overlay` family, `data-sv-at`, `.sv-unknown` ×5, `.sv-age` | 18–24 |
| B21 | You, off-nav, the book's tail | /profile/, /notifications/ (+ settings), /newsletters/ (+ detail), /getting-started/, /passation/, /short-proofs/, /bot/link/, /bot/configure/, /bot/scenarios/ (+ new, detail), /tax-lots/, /bot-charts/ | /profile/'s PIN and password windows on `.sv-dialog` with §7's PIN field; the notification settings' script styles through classes; /getting-started/ and /passation/ off the Eye's green | the PIN change on /profile/ | — | 12–16 |

**Inventory rows.** B16 #85, #93; B17 #90; B18 #91; B19 #92; B20 #94; B21 #95 (and their parts of #46, #78, #79, #80, #86).

**Risks for the six.** /admin-dashboard/ is the largest inline page (907 visual styles measured); ARM LIVE arms real money and must keep every step; U3 edits 3 lines of `short_proofs.html` (B21 rebases after it if it lands first).

## B22. Every width (S3)

**Scope.** As plan S3:
- **Desktop tiers** 1280/1680/2200: multi-column layouts at D3 and D4, KPI strips capped at 8, prose at 72 ch, no dead space at 2560; the orphan tiles and cut lines of #55.
- **Tablet** 769–1279: the sidebar as an icon rail, the rail as a drawer, the status bar's overflow, tables on their priorities.
- **Phone** ≤ 768: popovers as bottom sheets (railfilters' placement reused), the ticket as a full-width sheet with 44 px BUY/SELL, positions and signals as stacked cards, the Horde and the Eye moved into the phone nav, every money control ≥ 44 px.
- **Breakpoints:** 84 template media queries at about 25 widths and 92 in the sheets fold onto the tier boundaries; the JS boundaries (768/769/900) do not move.

**Inventory rows.** #55, #102.

**What he will see.** Every page right on his laptop, his desktop screen and a large screen; usable on a tablet; on the phone, cards that open from the bottom, tables as cards, LONG and SHORT big enough for a finger.

**Money controls to keep (§10).** Touch targets ≥ 44 px for every money control at ≤ 768 (48 for CLOSE, as S1a set); the phone ticket sheet keeps the ticket's PIN step and words.

**Tests to write first.** The measured matrix at 390, 768, 1024, 1280, 1440, 1920 and 2560: no sideways scroll, no fixed-chrome overlap, popovers inside the viewport, money targets ≥ 44 px at ≤ 768, 0 ellipsised titles; the guard strict at 390 and 2560 as well. Updated deliberately: `test_phone_layout`, `test_phase29_mobile`, `test_card_responsiveness`.

**Risks.** The phone's JS boundary; the ticket sheet after ticketnet's states.

**Size.** 24–32 h. **Waits for.** B6–B9 (the plan's "after S2.1–S2.4"); best after B21, so every page is on the kit.

## B23. The public pages, the report and the emails (outside the plan; on his yes, default yes)

**Scope.** /wall/, /book/, /withheld/, /investor/ (and /investor/live/): on the tokens and faces, their brand atmosphere kept as brand moments, **never an account figure** (`test_wall_public_safety`); the report (`report.html` on the tokens' light print values; `reports.py`'s PDF palette, today another project's #C0392B/#E74C3C/#2C3E50, on the tokens); the emails (newsletter, briefing: the token values inlined as hex, since email clients ignore CSS variables; Inter with web-safe fallbacks; ≥ 11 px) and the unsubscribe page.

**Inventory rows.** #97, #98, #99.

**What he will see.** The Wall, the Book, the investor page, the report and the emails in the same family as the platform.

**Tests to write first.** Guard strict on /wall/, /book/, /investor/; the source census on the email templates (no old greens, no sub-11 px). Kept: `test_the_wall`, `test_the_book`, `test_wall_day`, `test_wall_facts`, `test_wall_public_safety`, `test_wall_book_link`, `test_investor_window`, `test_newsletter`, `test_phase45_briefing_html_email`.

**Risks.** The Wall's 1,892-line style block is the bulk; these are public identity pages; the eyehall spec asks the Wall to follow the hall's ring rotation (E1).

**Size.** 16–24 h. **Waits for.** His answer (he said "tout"; default yes, last).

## B24. Cleanup and the zero-old-design guard

**Scope.**
- Delete, do not restyle: `dashboard/dashboard.html` and its unrouted `legacy_dashboard` view, `market_quotes.html`, `_signal_cards.html` and `_signal_performance.html` with their unrequested htmx routes, `_modal.html`, `.sv-switch`, `.btn-login`; the hidden ambient layers' markup and keyframes (`base.html:135-415`, `sauron.css:107-198, 3956-4021`); `frontend/` (dead React) in its own commit (plan §15). `test_live_hooks_inventory`'s two hooks in `dashboard.html` are moved deliberately.
- Fold the old `.btn` definitions into the kit (`sauron.css:413, 1006-1030, 2038-2070`) with a computed-style snapshot of every button variant before and after (no money control may change); drop the old token names nothing reads any more (`--accent-dim`, `--accent-bright`, `--accent-glow`, and the re-pointed aliases once no template uses them; the light-mode block stays if light mode stays).
- The guard made strict: budgets removed, STRICT = every page and state, exceptions reduced to the recorded ones.

**Inventory rows.** #103, #104 (and #16's rules).

**What he will see.** Nothing. Nothing old can come back.

**Size.** 8–12 h. **Waits for.** Every batch above.

---

## The final guard: "zero old design"

`tests/test_zero_old_design.py`, built in B0 as a ratchet and made strict in B24. Two halves, one test file, one budget file.

**1. The source half (no browser; always runs in CI).** It scans every template (`templates/**`, `bot_program/templates/**`), `static/css/*.css`, `static/js/*.js`, `core/templatetags/*.py`, `dashboard/views_bot_charts.py`, `dashboard/reports.py` and the email templates, and fails on:
- the Eye's literal green (`rgba(0, 232, 104, …)`, `#00e868`) or the old companions (`#40ff90`, `#0a5028`, `#030806`, `#3a6850`, `#e83030`, `#d8b020`, `#ffb000`, `#ff5e5e`) outside `sv-tokens.css` and the named light-source rules of `sv-kit.css`;
- `var(--accent-dim)`, `var(--accent-bright)`, `var(--accent-glow)`, and `var(--accent)` as a text or border colour outside the allowed roles;
- a `font-size` under 11 px; "Share Tech Mono"; the generic `monospace` as a first face;
- `badge-bullish` / `badge-bearish` on anything that is not a side word (LONG, SHORT, BUY, SELL, BULL, BEAR);
- a `style=` attribute carrying a visual property (colour, background, border, font, shadow, filter); geometry (width, height, offsets, transform, custom properties for data-driven bars) stays allowed;
- `animation: … infinite` outside the allowed list; `backdrop-filter`; a gradient outside the void, the hero edge and the active row's spill;
- an emoji or a Unicode glyph used as an icon in the nav, the topbar or a button (`{% icon %}` only).

**2. The measured half (Chrome over CDP; runs in CI on the ubuntu runner's Chrome, skipped only where no Chromium exists).** Every routed page (105 routes, parameters from the synthetic fixture) and these states: the rail open with a bullish and a bearish card, the quote card, the news, ticker and dwell cards, the bar's three dropdowns, the bell, the user menu, the sessions menu, the live-status list, the instrument preview, a fill banner, the Horde, the Council, the Activity, Ask Sauron with a canned answer, Gollum's dialog, a tour step, the "?" sheet, TAKE TRADE on paper and on a live world (synthetic preview), the close dialog live and paper (synthetic preview), the level editor, the idle lock. At 1440 × 900, dark, under Magic (and Off for the light checks). For every visible element and every `::before`/`::after` that paints:
- each computed colour (text, background, border, outline, SVG fill and stroke) is a token of `sv-tokens.css`, or one of the kit's named mixes (the up/down washes at 14 %, the chips at 12 %);
- the face fits the role: Inter for words, JetBrains Mono for numbers and code, Orbitron only in the frame's titles (never a digit), Rajdhani only in the nav rows; a sentence of 4 words or more is never in JetBrains Mono outside code, keys and identifiers;
- `font-size` ≥ 11 px; text contrast ≥ 4.5:1 against its computed ground;
- radius ∈ {0, 2, 4, 6, 999};
- shadows and glows only the popover and dialog shadows and the magic's light sources (wordmark, Eye mark, active nav row, live dots, the selected tab or segment, a live hero card's edge, a side's inset light); no gradient outside the void, the hero edge and the active spill; no `backdrop-filter`;
- the Eye's green as text only on the brand, the active nav icon and the empty-state mark; as a fill only on live dots, the ON state and a checked box; as a border only on the selection and focus;
- a solid red fill only on the REAL family (the chip, the armed pill, the row edge);
- running infinite animations only the live heartbeat, the armed beat, the Eye's breath under Magic and the embers' canvas (plus the marquee's frame loop, which is not a CSS animation);
- every rendered glyph drawn by one of the four faces or the sprite (CDP `getPlatformFontsForNode`);
- no fixed chrome over the content; the first content line at y ≤ 100.

A failure names the page, the state, the selector, the property and the value.

**3. Recorded exceptions** (each with its reason and date, each asserted to still exist so a removed exception is noticed, and each contained to its own file):
- `/intro/`: kept exactly, his decision of 2026-11-07;
- light mode, if he keeps it frozen (plan §15 decision 3);
- the Django admin (`/admin/`): Django's own look;
- the report's print palette (plan S2.7), if B23 does not take it;
- `/wall/`, `/book/`, `/investor/` and the emails, if he declines B23.

**4. The ratchet until B24.** `tests/old_design_budget.json` holds, per file and per page, today's count of each marker. A count may only go down; each batch sets its files and pages to zero and moves them to STRICT; a new template starts strict. B24 deletes the budgets: from then on every page and every state is strict, so nothing old can come back.

**Cost.** About 4–5 minutes of CI for the measured half (one browser, pages as files, 1440 only; 390 and 2560 from B22); it can run as its own job beside the suite.

---

## A realistic timeline

The pace of the last two weeks: about two to three display PRs a week beside the money work, each through review and CI, one at a time ("UI yields to money work"). On that pace:

| When | Batches | What he has by then |
|---|---|---|
| Week 1–2 | B0, B1, B2 | The new frame on every page: 120 px more to read, nothing floating on his tables, one icon family |
| Week 3 | B3, B4, B5 | Every card, menu and panel of the frame, and the shared pieces of ~50 pages, in the new look |
| Weeks 4–6 | B6, B7, B8, B9, B10 | His main pages: ticket and TAKE TRADE, positions, home, signals, portfolio, the chart |
| Weeks 7–9 | B11–B15 | Cockpits, the Oculus, the money settings, the bots, login and lock |
| Weeks 10–12 | B16–B24 | The long tail, every width, the public pages, the final guard: nothing old left |

About **three months** in all; sooner if a second session builds B10 (chart) and the long-tail sections beside the main line. The first visible change (the frame) lands within one to two weeks, after the marquee merges.

## Sequencing with the work in flight

| Work in flight | Touches | Rule |
|---|---|---|
| `claude/marquee` (continuous strips) | `base.html` strips and wheel/drag code, `sv-kit.css` §8, new `sv-marquee.js` | Merges first; B1 rebases on it and keeps `SVMarquee` and its two data hooks. If it is late, B2 and B5 go before B1 |
| OC0 (`claude/opscenter0`, 75 behind) | `command.html`, `_command_*.html`, `_eye_body.html`, 2 lines of `base.html` | Reviewed and merged before B8; until then B9 takes B8's place |
| U3 (`claude/wip-usedfix-u3`, stale WIP) | `positions_list.html` (5 lines), `treasury.html` (53), `short_proofs.html` (3) | B7 goes first and U3 rebases; /treasury/ (B13) waits for U3 or U3 rebases; money work lands first if it is revived |
| The steppers (`scratchpad/fleet/steppers_spec.md`) | The TAKE TRADE dialog | Before or after B6, never at the same time |
| Feed F7 | The WS painter (`sv-venue.js`), the paused chip, `sv-instrument-live.js`, the chart's tick rate | B1 keeps the painter untouched and reserves the topbar slot; only `sv-venue.css` changes (B3); B10 lands before F7 raises the chart's tick rate |
| Feed F4 | P&L cells on positions, portfolio, command | Through the kept `data-sv-live-key` hooks; prints with `.sv-pnl`/`.sv-fresh`/`.sv-est` |
| E1 Barad-dûr | "/", a new page on the kit | Uses B2's tower icon; "/" no longer lands on /command/ |
| `claude/introlabels` | `intro.html` | The intro is out of every batch (kept exactly); only its invented prices go there |
| O2c/O2d, C1–C3, P1–P5, A1 Anduin | New pages and the ticket's world choice | Written on the kit; never old design |

**Not in this redo:** S5 (the drawings) is a new feature, not old design, and stays last as the plan says; the steppers, C1–C3 and P1–P5 are features built on the kit.

---

## Added by the critic (2026-11-13)

Read against `inventory.md` rows #105–#116 (same date, same section name), §10 and the final guard. Evidence and measurements are in those rows and in `olddesign/critic/out/check.json` (scratch server 127.0.0.1:19883, synthetic fixture, stopped afterwards).

### 1. Scope the batches did not carry

| Batch | Adds | Rows | Hours added |
|---|---|---|---|
| B0 | The five guard fixes of §2 below | — | +4–6 |
| B1 | The page scrollbar (`sauron.css:681-683`) | #113 | +0.5 |
| B2 | The unseen-section dot (DEMO gold → the kit's count dot), the lock button (no Eye wash, no gold padlock) | #113 | +0.5 |
| B3 | `.sv-live-chip` everywhere (its rule leaves `live_region.html` for the kit: bar heads, /positions/, /portfolio/, /risk/, /investor/); the Telegram deep-link note on the kit's Notice; the bell's offline mark in amber (§3.7) and its hover | #111, #112, #113 | +2–3 |
| B5 | The shared table's body: words in Inter, `.num` mono and right-aligned (80 templates) | #114 | +1–2 |
| B6 | TAKE TRADE's "Close first" list (neutral ticks, B7's selection look; 11 px; words in Inter) and the LIVE ticket's Council block; both become guard states | #109 | +2–3 |
| B8 | The Bots tab's live Toggle + PIN, kept wherever OC1 re-homes it | #108 | +0.5–1 |
| B9 | The broker's own reading card (`broker_account.html`, `.bk-card`), reused as is by B8 and B13 | #110 | +1–2 |
| B14 | /shares/ Apply and ↶ Rollback (PIN, re-size live pools), /asset-bots/ Follow | #108 | +1–2 |
| B15 | The Wall's sign-in, PIN pad and forgot-PIN windows (`the_wall.html` overlay CSS and markup only; its AJAX login and PIN flow untouched), on the same look as /login/ and /login/pin/, whatever he answers about B23 | #105 | +4–6 |
| B17 | /personas/ Apply + PIN; /promotions/ ↑ and ↓ | #108 | +1–2 |
| B19 | /knowledge/ Clear + trading PIN | #108 | +0.5–1 |
| B20 | /admin-dashboard/'s money controls on B11's switch row, and the bot control panel (`_admin_bots.html`) | #106, #107 | +5–7 |
| B21 | /short-proofs/ Clear and Revoke + trading PIN | #108 | +0.5–1 |
| B23 | Loses the Wall's sign-in (to B15) and `report.html` (dead: to B24) | — | −2 |
| B24 | `404.html`, `500.html` (self-contained: no context processor runs for it), `403.html`, `403_csrf.html` on the kit; `report.html` deleted with the other dead templates | #115 | +3–5 |
| B24a (new, only if he keeps light mode) | §10's meanings in light mode: `--sv-real` distinct from `--sv-down` (today both #E83030), down marks off REAL's red, CLOSE and turn-off neutral; its palette may otherwise stay frozen | #116 | +6–10 (retiring it instead: +2–3, in B24) |
| **Total** | | | **+31–50 h: 441–590 h, about 510.** At the measured pace about one more week: "about three months" stands. |

### 2. The guard (B0, strict in B24): five holes

1. **Pages opened as files load nothing after the HTML.** B0 opens rendered pages as files, the way `tests/test_close_advice.py:1656-1665` does, with no server behind them. Every region htmx or `fetch` fills then stays empty and passes unseen: the KPI strips of /positions/, /portfolio/, /signals/, /news/, /backtest/, /strategies/ (`hx-get="/htmx/metrics/…"`, B5's main target), the bot control panel (`/htmx/admin/bots/`), /eye/'s body (`/eye/partial/`), /command/'s four tabs (`/command/tab/*`), the chart's candles (`/api/chart-data/`: B10's pixel census would read an empty canvas), the instrument preview, the rail's and the bell's refreshes. Fix: serve the fixture from a live server on 127.0.0.1 (`StaticLiveServerTestCase`), or answer Chrome's requests through CDP `Fetch.requestPaused` from the test client; and measure the partial routes as pages of their own.
2. **Rest state only.** The measured half reads computed styles at rest, yet #29 (a REAL row's edge turns green under the pointer), #38 (CLOSE turns coral on hover), #107 (the bot panel's Eye hover) and #113 are hover-only; only B3 and B7 test their own. Add a forced-state pass (CDP `CSS.forcePseudoState` with `:hover`, `:focus-visible`, `:active`) over every button, link, table row and checkbox of the shell and of the §10 controls, with the same colour, glow and red-fill rules.
3. **1440 only until B22.** A second keeper runs Sauron on a phone (`sv-responsive.css:1-30`); B1–B21 restyle what it shows with no check below 1440 except B1's "phone tier unchanged". Measure 390 × 844 from B0 for the shell and the §10 controls (targets ≥ 44 px, no sideways scroll, no red fill outside REAL).
4. **Properties, states and markers the lists miss.** Colours: add `accent-color` (#109's coral ticks; `sv-close-advice.css:37`), `caret-color`, `::placeholder`, `::marker`; scrollbars are invisible to computed styles, so the source half holds `::-webkit-scrollbar*` rules to tokens. States: the sidebar collapsed with `#navMiniTip`, the bands hidden (restore tabs), the bar minimised, the rail's collapsed dock, the Wall's sign-in and PIN pad (#105), a deep link (#112), Django messages (success, error), the bell offline, TAKE TRADE short of capital and LIVE with the Council asked (#109), the CLOSE ALL and close-selected previews, an empty page, 404/403/500 (#115), light mode (§10 checks only, #116). Source markers: the email palette (`sauron_tags.py:314-318`, #00753A …) and the PDF's (#C0392B, #E74C3C, #2C3E50 in `reports.py`) are on no list, so a strict B24 would pass both.
5. **No owner for a third of `sauron.css`.** 2,845 of its 7,716 lines fall in no range a row or a batch cites by line (some are named by component instead). Stretches with old markers among them: 7653-7717 (#110), 7050-7107 and 681-683 (#113), 3831-3955 (Ask Sauron's send orb: B4 should name it), 5346-5570 (light-mode overrides of the shell, the Palantír orb, laptop shims: B1, B4 or B24a), 2202-2286 (the watchlist rows: B3). B0 should print a `file:line → batch` map from its census, so B24 (8–12 h) is not left the orphans.

### 3. §10 controls no batch listed

The rule B11, B13 and B14 already follow becomes common to B8, B17, B19, B20 and B21: a form diff (every `<form>`: action, method, field names and types, hidden inputs, PIN fields equal to main's), and a PIN field whose visible label says what it unlocks (today 38 measured PIN fields on /admin-dashboard/ and /personas/ show only "PIN").

| Control | Where | Batch | Look to reach (§10) | Must never |
|---|---|---|---|---|
| FLATTEN ALL (PIN; closes every position; irreversible) | `admin_dashboard.html:240-258` | B20 | Stop variant ■, the §7 PIN field ("PIN · closes every open position"), its open-count line kept | Be a red fill; lose the count line |
| PROMOTE TO LIVE ×3 and DISABLE LIVE ×3 (actuator, meta-allocator, share-allocator live modes) | `admin_dashboard.html:835-842, 1198-1205, 1278-1293` | B20 | B11's PIN switch row: REAL chip by the name, "PIN ____ TURN ON" neutral, off neutral | Stay the light primary |
| The component table (81 START, 17 PIN switches, STOP) | `admin_dashboard.html:1300-1320` | B20 | B11's switch row | Keep "PIN" as the only visible word |
| SAVE KNOBS + PIN (sizes of a hand-taken ticket) | `admin_dashboard.html:84-120` | B20 | Inputs mono with units, labels ≥ 11 px, Save primary, §7 PIN | 10 px labels |
| Live asset-bot creation ("Live (your real funds)" + PIN) | `admin_dashboard.html:915-930` | B20 | The REAL chip by the Live choice, §7 PIN | — |
| Bot control panel: Toggle (arms a LIVE bot, PIN), Reset circuit (re-arms), Shadow 24h, Reconcile | `_admin_bots.html` | B20 | §10 "Bots on/off"; the mode as a world chip | Light up the Eye on hover; show a live bot without the REAL chip |
| /command/ Bots tab: Toggle a LIVE bot + PIN | `_command_bots.html:92-99` | B8 | As /asset-bots/ | Disappear when OC1 retires the tab |
| /shares/ Apply and ↶ Rollback (PIN), Reject; /asset-bots/ Follow | `shares.html:128-166`; `asset_bots.html:62-66` | B14 | §7 PIN with its words; glyphs from the sprite | — |
| /personas/ Apply on a live config (PIN; re-sizes real risk) | `personas.html:158-207` | B17 | §7 PIN | 54–60 px "PIN" with no label |
| /promotions/ ↑ into live_small/live_full (real money, no PIN today) and ↓ | `promotions.html:51, 70-71` | B17 | ↑ into a live stage names it with the REAL chip; ↓ neutral; stages as `.sv-state`; Path A's future PIN built on this | ↑ as the light primary; a live stage as a gain chip |
| /knowledge/ Clear; /short-proofs/ Clear and Revoke (trading PIN) | `knowledge.html:74-80`; `short_proofs.html:69-76` | B19, B21 | §7 PIN | — |
| TAKE TRADE "Close first" ticks (a paper ticket short of capital) | `base.html:3033-3054`; `sauron.css:6493-6496` | B6 | Neutral ticks, the pre-ticked proposal and the shortfall check kept | Coral ticks (today) |
| The Wall's PIN pad (his sign-in) | `the_wall.html:4628-4660` | B15 | §7 PIN boxes in mono, Verify primary | Orbitron Eye digits, a green slab (today) |
| The broker's own reading (equity, age, environment) | `_partials/broker_account.html` | B9 | A money cell with its age (§4.4); LIVE as the REAL chip | Coral LIVE text (today) |
| Light mode's world markers | `sv-tokens.css:265-268` | B24a (or retired) | REAL's red distinct from losses | Share #E83030 with every loss (today) |

### 4. Corrections

- **The final guard's exceptions:** "/wall/ … if he declines B23" excludes the Wall's sign-in and PIN states (#105, B15 in every case); "the report's print palette" goes (`report.html` is rendered by nothing; B24 deletes it; the PDF keeps its route, linked from no live page once `dashboard.html` goes); "light mode" keeps only its palette, never the §10 checks (#116).
- **B15's scope** names /login/, /login/pin/ and /login/pin/forgot/ but not the door he actually uses: since `LOGIN_URL` is `the_wall`, every expired session and every logout ends on the Wall's own sign-in (measured).
- **B17 and B19 "none" and B21 "the PIN change on /profile/"** are wrong for money: see §3.
- **B20's money list** names three controls out of the page's set: see §3.
- **"Nothing old left"** holds only once §2's five holes are closed: a page can be strict and still carry an old region the guard never loaded, an old hover it never forced, or an old phone layout it never measured.
