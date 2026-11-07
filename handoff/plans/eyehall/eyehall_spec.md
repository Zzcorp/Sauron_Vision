# Barad-dûr: the page after the login animation (spec, revision 2)

Spec, 2026-11-07, revised the same day after two critiques (truth, performance and safety; delight, usability and consistency). The change log is `changes.md`. It reads `main` at `ede54d0` through the read-only worktree `mainread`, and the offline scratch copy `scratchpad/eyehall/app` (SQLite, synthetic fixture). It uses:
- the Eye Hall map (`scratchpad/eyehall/`: the shots, `tools/*.json`, `logs/beat.txt`);
- the approved UI plan (`scratchpad/uiplan/ui_plan_spec.md`: palette §3, type §4, motion §8, the kit §7, money controls §10);
- the preview boards (`scratchpad/preview/project/*.dc.html`);
- the Oculus spec (`scratchpad/oculus/oculus_spec.md`), whose truth rules this page reuses;
- the Operations Center spec and mock (`scratchpad/opscenter/opscenter_spec.md`, `opscenter_mock.html`, revised 10:03). This page reuses four of its blocks in short form (§11).

This is a plan. Nothing is built, and nothing in any worktree was written. Every figure in the mock and the board is synthetic: EURUSD, XAUUSD, USDJPY, NAS100, GBPUSD and amounts invented for the purpose. The synthetic book is the Operations Center mock's, so the three boards agree when he sees them side by side. Nothing came from the operator's account.

**Deliverables (all in `scratchpad/eyehall/`):**

| File | What it is |
|---|---|
| `eyehall_spec.md` | This spec |
| `eyehall_fr.md` | The French proposal for the operator |
| `eyehall_mock.html` | Standalone animated mock |
| `shots/mock_1440x900.png` | A frame of the mock, 1440 × 900 |
| `shots/mock_390.png` | The phone page, full length |
| `shots/mock_1440.webm` | 8.4 s of video: the intro's last frame, the hand-off, then live events |
| `Eye.dc.html` | The same design as preview-canvas board 5. It moves with SMIL and CSS only |
| `canvas_entry.json` | The entry to add to `scratchpad/preview/project/canvas.json` |
| `changes.md` | What changed after the critiques, and what was not taken |
| `mock_tools/` | The scripts that rendered and measured all of the above, with their reports |

The mock takes these parameters:
- `?from=intro&t=<ms>&px=<-1..1>&py=<-1..1>` plays the hand-off from the intro's own state;
- `?demo=0` stops the synthetic events;
- `?perf=1` counts frame cost; `?idle=<s>` shortens the drift's quiet minute (review only).

---

## 0. In one page

**His words (2026-11-07, verbatim).** "Je voudrai aussi que l'on creer une page qui s'affiche apres que l'utilisateur se connecte un sorte dde page avec seulement l'oeil aucentre et des particules ou de element anmer qui soit les eleme,t de chaque page ainsi que leur interconnection entre eux marquer etc... vous comprennez? Ainsi avec en grafique sur chaque coté et en chiffre les element detaillé et donnant vue au perf du potfolio etc?...."

**Then the correction:** "Garder l'animation action actuel de chargement svp cependant vous comprenez?"

**What we build.** A page shown right after login and right after today's loading animation, which stays exactly as it is. It has:
- the Eye alone at the centre;
- around it, the platform's pages as living elements, with their interconnections drawn and named;
- charts and detailed figures on each side: the portfolio's performance on the left, the day's activity on the right.

**The name: Barad-dûr.** The tower whose summit holds the Eye.
- URL `/barad-dur/`, URL name `barad_dur`; data at `/api/barad-dur/`, URL name `barad_dur_data`.
- The first row of the sidebar's AMON HEN group.

**The flow.**

```
Wall login (+ PIN) --> /intro/  (kept: same look, timing, Skip, once per session)
                          |  end of the sequence: /barad-dur/?from=intro&t=..&px=..&py=..  (hand-off from its own state)
                          |  Skip:                /barad-dur/                               (short fade)
                          v
                     /barad-dur/  <-- second login in the same session (the intro view redirects here)
                          |           <-- sidebar row "Barad-dûr" (first in AMON HEN)
                          |
             click the Eye, Enter, or "Enter the Operations Center"  --> /command/
             click any page on the ring, its stage's list, or All pages (/)  --> that page
```

**The concept in five lines.**
1. The kept intro hands its Eye over. Its one changed line passes its own animation clock and pointer, so Barad-dûr's first frame is the intro's last frame to within half a pixel; then the Eye descends into its hall and wakes.
2. Around the Eye turns the day of Sauron: seven stations (SEE, THINK, DECIDE, ACT, WATCH, TELL, LEARN) in the words of `day_live`, ACT at the bottom, and the top left open: the night that carries LEARN back to THINK.
3. Twenty pages sit by stage around the ring, each with its name and one real figure. Twenty named roads join them, in the platform's words. The other 36 sidebar pages are under their stage, 7 more in the top line's menu and the bottom line, and all 62 in All pages.
4. A particle travels a road only when a real push event happens on it, in the colour of whose money it is. Between events a faint green drift moves on the roads that carry pushes; it sleeps after a quiet minute and stops when the live feed does. No particle ever carries a number or a label.
5. On the left, the book's performance: REAL equity from eToro (net of paid withdrawals), open now, 24 h and from the high-water mark, P&L by world, PAPER's realized curve. On the right, the day: what needs him, signals to act on, the last 24 h by world, win rate and expectancy, and the machine. REAL, DEMO and PAPER are never added, and the page is display only.

**The stages.**

| Stage | What he will see | Starts when |
|---|---|---|
| E0 | This design, the animated mock, the video, board 5 on the preview canvas | Now. No repository change |
| E1 | The real page on real data: the hand-off, static roads, both side panels, NEED YOU, All pages, the lock, the sidebar row; white particles on the push events; the intro's three targets point at it; tests first | S1a merged |
| E2 | Particles in the colour of their world on every fill and close, the Orc's birth, the entry's path (bot, ticket, words), and "since you last looked" replayed | E1 merged |
| E3 | eToro's own P&L per position and the held instruments' prices about every 10 s | Feed F4 and F7 merged |

**What we need from him** (the French note asks it):
1. OK on the name Barad-dûr.
2. OK that the intro keeps everything and only its destination changes (its last line also passes where its Eye is, so nothing jumps).
3. Should `/` stay the Operations Center (default), or lead to Barad-dûr too?
4. OK on the twenty pages shown around the Eye (§4.3). The rest stay one click away.
5. OK on world-coloured particles, with solid red meaning real money.
6. The pages are fixed points and only events move (default). Or should the pages themselves drift slowly around the Eye?

---

## 1. Inputs and constraints

**What the map measured that shapes this design:**
- **The intro is self-contained.** It sends no request during its sequence, which ends at a random time between 4.9 and 8.0 s (`intro.html:318-335`: 2.2 s, then ten steps of 150–400 ms and four of 100–250 ms, then 0.8 s). It hard-codes `/command/` in exactly three places. Changing those three targets is the whole switch.
- **The intro draws the Eye in a fixed place that floats.** At 1440 × 900 the drawn Eye is 220 × 139 at x 610; its float runs between 0 and −14 px over 6 s (`intro.html:45-50`), so its top lies between y 248 and 262 at the last frame. Its glow breathes (scale 1 → 1.18, opacity .7 → 1, 4 s, `intro.html:37-40`); the background glow follows the pointer by up to ±110 px and the globe by ±60 px (`intro.html:280-293`); an 80 px grid drifts over 40 s (`intro.html:125-137`).
- **"Eye" is taken.** It already names /eye/, the /ws/eye/ socket, the Telegram Eye voice, the background globe-eye and the green token. The Oculus (Latin for eye) is the "every cycle" page. The new page needs another name.
- **The shell is heavy.** It costs about 80 queries and 856 KiB of HTML on every render, and S1a hides its ambient layers on work pages. The new page is therefore **standalone**, like the intro and /locked/: its own top and bottom lines, its own canvas, rendered with an explicit context (no context processors), its own sockets.
- **eToro reads one world at a time.** Each user has one eToro row; its `demo` flag (default True) is the switch between the two worlds, and the sync reads only that world (`bot_program/models.py:376-382`, `tasks.py:1049`). `account_equity(user)` returns that one world's reading; `broker_env(acct)` names it (`capital_truth.py:426-440`).
- **The equity's currency is eToro's.** `account_equity()["currency"]` is eToro's `accountCurrency` (`etoro_client.py:2684-2693`). Trade P&L is in USD (`portfolio/services.py:1261, 1298, 1313`). PR #89 refuses eToro's own figure when the account is not in USD (`services.py:1207-1209`).
- **eToro's own P&L per position is probably empty until F4.** PR #89's tier 1 reads `netProfit` from the portfolio list, which the client calls unmeasured (`etoro_client.py:2939-2958`; the feed spec, P-b 1). Until F4, an open P&L is an estimate that says which price it used.
- **The push events exist, with three gaps.** `fill_open`, `fill_close`, `close_pending`, `scale_out`, `gate_reject`, `notification`, `new_signal`, `run_complete`, `council_sitting` and `sauron_answer` arrive on /ws/eye/; `quote`, `signal` and `news` on /ws/dashboard/. No payload says its world; a bot fill and a ticket fill send the same `fill_open` (`asset_engine/base.py:7595-7599`, `manual_trade.py:3821-3825`); and nothing announces an Orc's birth, which happens after the commit and only while the Orcs are on (`orcs/birth.py:49-77`). E2 adds `world`, `via` and an `orc_born` push (§4.6).
- **There is no shadow bot mode.** A bot is `live` or `paper`; DEMO is a live-mode config on an eToro account whose `demo` flag is on. Bots are shown by world (REAL, DEMO, PAPER) and off. "Shadow" stays the word for the Orcs' minds, the desk and the allocator.
- **The idle lock is a server flag with JSON and HTML answers.** A request counts as machinery only if it sends a JSON header or sits under `/api/`, `/htmx/` or `/partials/` (`core/idle_lock.py:89-104`); anything else re-stamps the session as human (`:132-133`) and gets a 302 to /locked/ instead of 423 when locked (`:138-146`). The overlay opens only through `SV.overlay` (`static/js/idle-lock.js:192`), and the /ws/eye/ consumer closes the socket on `session_locked` instead of forwarding it (`dashboard/consumers.py:258-267`).
- **The Operations Center's design exists and is approved** (`scratchpad/opscenter/`, six OKs given on 2026-11-07, including P2 "since you last looked"). Its words, its NEED YOU cell and its R6 and R7 blocks are reused here (§11).

**House rules that bind every stage:**
- Display only, and each commit says "Money direction: none. Display only."
- No broker call and no model call to draw the page.
- Synthetic data only in mocks, fixtures, screenshots and tests. Never weaken a test.
- The UI plan's palette, faces and floor apply: Inter and JetBrains Mono, Orbitron for the wordmark only, nothing under 11 px. One declared exception: the intro's own words in its own faces for the 340 ms of the hand-off (§2.5).
- REAL, DEMO and PAPER are never summed, in money. A count may stand beside its split, never alone ("3 real · 2 demo · 2 paper").

---

## 2. The name and the place in the flow

### 2.1 Barad-dûr

**Why this name:**
- **It is the right image.** In the lore the Eye sits at the summit of Barad-dûr and sees every land. That is the page: the Eye at the centre, every page of the realm around it, the roads between them.
- **It collides with nothing.** It is not "Eye" (/eye/, the socket, the voice, the token), not Oculus, and not Amon Hen (the sidebar group it heads).
- **It reads the same in French and English,** and the operator already uses the lore's words: the Horde, the Orcs, Morgul, Aragorn, Gollum.
- **Mechanics:** URL `/barad-dur/` (ASCII); URL name `barad_dur`; template `dashboard/barad_dur.html`; page title "Barad-dûr · Sauron Vision"; in the sidebar, mark ♖ (U+2656, beside the Council's ♔), replaced by a tower icon from the S1b sprite.

**Considered and set aside:** "The Eye", "Eye Hall" (collisions); "Amon Hen" (the group's name); "The Palantír" (another seeing-stone, and it would read as the Oculus); "Lugbúrz" (the same tower in Black Speech; too obscure).

### 2.2 The intro: kept; only its target changes

The intro is not touched: its look, its timing, its Skip, its particles and its 14 lines all stay. `LOGIN_REDIRECT_URL = "intro"` stays (`config/settings.py:516`). Three lines change, and in each one only the target changes:

| File:line | Today | E1 |
|---|---|---|
| `templates/dashboard/intro.html:198` (Skip) | `<a href="/command/" id="introSkip"` | `<a href="{% url 'barad_dur' %}" id="introSkip"` |
| `templates/dashboard/intro.html:324` (end of the sequence) | `window.location.href = '/command/';` | `window.location.href = '{% url "barad_dur" %}?from=intro&t=' + Math.round((function () { try { return document.querySelector('.intro-eye').getAnimations()[0].currentTime \|\| performance.now(); } catch (e) { return performance.now(); } })()) + '&px=' + pCX.toFixed(3) + '&py=' + pCY.toFixed(3);` |
| `dashboard/views.py:6496` (repeat visit in the same session) | `return redirect("command_center")` | `return redirect("barad_dur")` |

- **Line 324 passes the intro's own state** so the hall's first frame can be its last frame:
  - `t`, the float's own animation clock (`.intro-eye` has one animation, the 6 s float, `intro.html:41-50`). The glow, the globe's turn and the grid started in the same first style pass, so they share it. If the browser has no `getAnimations`, the line passes the page clock instead.
  - `pCX`, `pCY`, the pointer's smoothed parallax, which live in the same closure (`intro.html:280-293`).
  - The expression is ES5 syntax and its one DOM call sits in a `try`, so it cannot throw: the line still does only one thing, it leaves for its destination.
- **Why the float's clock and not the page clock.** The page clock (`performance.now()`) counts from navigation, the float from the intro's first paint. The gap is the time to that first paint, which grows on a busy machine or a slow font: the intro's Google Fonts link blocks rendering (`intro.html:13`). Measured here (`mock_tools/handoff.js`), the page clock ran 205–851 ms ahead of the float, which put the Eye 1.3–6.3 px off; holding the intro's font stylesheet for 500 ms alone gave 6.26 px.
- **Measured** on the real intro (`intro_copy.html`: main's file with the navigation replaced by the proposed expression's values and the boxes read in the same instant; its random delays pinned so the sequence ends at 4.9, about 6.45 and 8.0 s, plus the 6.45 s case with its font stylesheet held 500 ms; the pointer moved up and right):
  - with the float's clock, the Eye's drawn box in the hall's first frame lands within 0.05 px of the intro's last frame in all four cases, and within 0.36 px after the hall takes over;
  - the globe and the glow land on the intro's offsets, about (+30, −24) and (+55, −44) px, within 0.1 px.
- **The docstring** at `views.py:6491-6494` changes its words "hands off to the Operations Center" to "hands off to Barad-dûr". Nothing else changes.
- **Skip lands without the hand-off** (a 320 ms fade): the frame at a skip is not the intro's last frame.
- **A test pins that nothing else in intro.html moved.** It compares the file, with lines 198 and 324 masked, against the hash of today's file.

**"Once per browser session", as it really is.** The flag `sauron_intro_seen` lives in the database session, whose cookie lasts two weeks and survives a browser restart. So the intro plays once per login, not once per browser session. This design keeps that behaviour exactly, and the French note says it in plain words.

### 2.3 Who lands where

| Arrival | Today | With Barad-dûr |
|---|---|---|
| Wall login, no PIN (AJAX → `/intro/`) | intro → /command/ | intro → **/barad-dur/?from=intro&…** (hand-off) |
| Wall login with PIN (/login/pin/ → `/intro/`) | intro → /command/ | intro → **/barad-dur/?from=intro&…** |
| Plain /login/ and /login/pin/ pages (302 → /intro/) | intro → /command/ | intro → **/barad-dur/?from=intro&…** |
| Skip during the intro | /command/ | **/barad-dur/** (short fade) |
| Second login in the same session (same user, no logout) | /intro/ answers 302 → /command/ | 302 → **/barad-dur/** |
| Logout then login, or another user | intro replays | intro replays → /barad-dur/ |
| Telegram deep link (`next`, `safe_next`) | straight to the link | unchanged |
| Forgot PIN | /profile/?modal=pin | unchanged |
| Signed-in visitor on /wall/ | 302 → / → /command/ | unchanged (decision 3: `/` stays the Operations Center) |
| Idle lock, then unlock | back to the same page | /locked/?next=/barad-dur/ → back to Barad-dûr (§6.4) |
| Investor login | /investor/ only (`investor_gate.py:34-35`) | unchanged: /barad-dur/ and /api/barad-dur/ are outside `ALLOWED_PREFIXES` |

### 2.4 Reopening it, and leaving it

**To come back:** the sidebar row "♖ Barad-dûr", first in AMON HEN, above the Oculus, for every login (each viewer sees their own book and the platform figures they are allowed). `tests/test_nothing_unseen.py` gains the route; nothing is removed.

**To leave, by mouse:**
- click the Eye, or "Enter the Operations Center" (bottom right) → /command/;
- click any page on the ring → that page;
- click a station → its list: "Open THINK on the Oculus ›", the job sentence, its pages on the ring with their figures, then its other pages;
- the bottom line's links: Operations Center, Oculus, Positions, Signals, All pages;
- the top line: NEED YOU → /command/ (its lit rows); the bell → Notifications; the user menu (Profile, Setup, Getting Started; for staff The Lore, Model Selection, Admin Panel; then Log out, through the idle lock's own logout form).

**To leave, by keyboard:** Enter with nothing focused → /command/; `O` Oculus, `P` Positions, `S` Signals; `/` All pages (filter focused); `1`–`7` open a station's list with focus on its first link; `Esc` closes.

**One page to every page.** The ring shows 20 pages (14 below 1366 px wide). The stations' lists hold 36 more sidebar pages under their nearest stage; 7 have no stage (Oculus, Operations Center, Profile, Setup, Getting Started, The Lore, Model Selection) and sit in the bottom line and the user menu. **All pages** opens the sidebar's eight groups, built from the same navigation source and permission checks as the sidebar, with a filter field: the UI plan's go-to bar (`ui_plan_spec.md:1259`), first here.

### 2.5 The entrance: the intro's motion, continued

**The first frame is the intro's last frame, painted before any script runs.**
- A few inline lines in `<head>` read `t`, `px` and `py` and set CSS variables before the first paint: the Eye at the intro's place and float, the background glow at the pointer's offset (×110 px), the globe at its offset (×60 px), and the glow's breathing, the globe's turn and the 80 px grid at the intro's clock (a negative `animation-delay` of `t`).
- The hall's `<head>` loads the intro's own font link byte for byte, so its faces come from the browser's cache: the title in Orbitron, and "Systems online. Launching…", the greeting, the subtitle and Skip in Share Tech Mono, drawn in the first frame at the intro's size, colour and spacing. This is a declared exception to the type rule, for the 340 ms these words take to leave.
- Two things are not redrawn: the intro's 70 particles (they carry fake prices; the rule) and its 10 px "100%" (under the floor). They are the only things that vanish at frame 0.
- The Eye is the hall's own SVG, traced on `logo_SV.png` (§4.1). Asleep it wears the PNG's colour (#3C9A6C), so the first frame cannot be told from the intro's PNG. When the script runs, the Eye moves from the CSS-placed frame into the hall's layout in the same frame (FLIP), a 0.41 px adjustment.
- No blank frame: the `<head>` paints `#030806`, the intro's void; Chromium keeps the intro painted until the hall's first paint (paint holding on same-origin navigations); the first payload is inlined, so that paint needs no request. Another browser shows at most one frame of the void colour, never white. The pages, stations and roads are hidden by CSS until the entrance reveals them, so nothing flashes.

**The choreography, from the first paint (`?from=intro`):**

| Time | What moves | How |
|---|---|---|
| 0–340 ms | "VISION", the subtitle, the bar, its line, the greeting and Skip leave | Opacity to 0, 4 px up |
| 0–950 ms | The Eye descends from the intro's place to the hall's centre (720, 450 at 1440 × 900), 220 → 180 px | Transform only, cubic-bezier(.3,0,.2,1) |
| 0–950 ms | The glow and the globe return from the pointer's offsets to the centre; the grid fades | Transform, opacity |
| 0–900 ms | "SAURON" flies to the top line's wordmark | Translate and scale (FLIP), then cross-fades into it at 1,000–1,220 ms |
| 200–1,100 ms | The void warms from #030806 to #070A09; the glow settles to 55 %, the globe to .035 | Background and opacity |
| 450–1,150 ms | The ring of the day draws; the stations appear in the day's order, 70 ms apart | Stroke-dashoffset; opacity |
| 520–1,420 ms | The Eye wakes: the iris turns Eye green and its three meridians appear | Colour, opacity |
| 760 ms | The top line arrives (the wordmark lands in it) | Opacity, 4 px |
| 800–1,690 ms | The pages arrive stage by stage (SEE first, LEARN last) | Opacity |
| 1,000–1,600 ms | The roads draw in; their names follow at 1,450 ms | Stroke-dashoffset; opacity |
| 1,150–1,570 ms | The side panels and the bottom line | Opacity, 4 px |
| 1,600 ms | The drift starts | Canvas, 10 frames a second |

- Everything is clickable from the first frame. The longest single motion is 950 ms, and nothing bounces or slides more than 4 px (UI plan §8).
- **Without `?from=intro`** (sidebar, second login, Skip, phone): everything fades in over 320 ms, then the drift starts at 400 ms.
- **Under `prefers-reduced-motion`:** no entrance; the page is simply there.

Verified frame by frame in `shots/mock_1440.webm` (it starts at the first complete intro frame) and in `mock_tools/vf6/sheet_entrance.png`.

---

## 3. The page at 1440 × 900

Standalone: no sidebar, no market band, no status bar. Gutters 16 px. Side columns 300 px (360 at ≥ 1680, 288 below 1366). The centre takes the rest (776 px at 1440).

```
+------------------------------------------------------------------------------------------------------+
| (hex) SAURON | BARAD-DÛR  the pages and their roads  [NEED YOU ⨯ 2 alarms · 6 watch ›]               |
|        KILL SWITCH ready 7 d quiet  ● eToro · live 6 s  [REAL ARMED · 2 BOTS] 12:53:20 UTC (bell 2) (lock) OPERATOR ▾ |
+---------------------+--------------------------------------------------------+-----------------------+
| PERFORMANCE 1D 7D 30D 90D     Strategy Evolution o      o Economic Calendar      | SIGNALS TO ACT ON  13·3 |
| [REAL] eToro equity $10,453.61  Promotion Ladder o (open top: the night) o News  | XAUUSD SHORT .72 4 min |
| +217.40 · +2.12% ▲ · 30 d  eToro · 40 s   Bot Perf. o  (●LEARN)  (▲SEE stale) o Instruments | you hold it: REAL short |
| [OPEN NOW ≈+76.26 ▲][24 H +12.40 ▲][FROM HIGH -3.12%]  Ask Sauron o            o Sauron's Mind | USDJPY · EURUSD ...  |
| used 42.1% · available $5,955.11    Strategist B. o (●TELL)  ( EYE ) (▲THINK stale) o Signals | +10 more · Signals ›  |
| [REAL curve, net of withdrawals]   Notifications o                       o Opportunities | LAST 24 H (3 lanes)   |
| [DEMO] — not read: one world at a time   System Health o (●WATCH) (●DECIDE) o Asset Bots | REAL | ||●● ⨯⨯        |
| [PAPER] realized, cumulative +73.03       The Orcs o     (●ACT)        o Capital Desk | DEMO  nothing in 24 h  |
| P&L  REAL DEMO PAPER (USD)                Portfolio o                o Share Allocator| PAPER ●|●|●|| ...    |
| open ≈+76.26 ≈+66.90 +6.60                    Brokers o    o Positions (⨯ 2 alarms) | WIN RATE · EXPECTANCY |
| 24 h / 7 d / 30 d                          roads on 5 lanes, 20 named                  | THE MACHINE           |
+---------------------+--------------------------------------------------------+-----------------------+
| ↵ Operations Center  O Oculus  P Positions  S Signals  / All pages  1–7 a stage  Esc   display only · read 12 s ago |
|                                                              [ENTER THE OPERATIONS CENTER →]   44 px |
+------------------------------------------------------------------------------------------------------+
```

The real rendering is `shots/mock_1440x900.png`. That frame catches a REAL bot fill on "the book" just after the order reached Positions, with a quote leaving Instruments & Quotes.

---

## 4. The centre

### 4.1 The Eye

**The geometry is the logo, traced** (`static/logo/logo_SV.png`, 285 × 180, measured in Chromium):

| Part | Geometry |
|---|---|
| Lid | Two arcs of radius 139.5 from (26, 90) to (258, 90), stroke 10.5 (a vesica, like the mark) |
| Iris ring | Centre (141.5, 90), r 39.75, stroke 20.5 (outer 50, inner 29.5) |
| Pupil | r 29.5, #030806 |
| Catchlight | r 14.3 at (157.8, 71.2), #F8F8F8 |

**Its colours.** Asleep it is the PNG's #3C9A6C. Awake the iris is the Eye green #00E868, with the mark's three meridians knocked through in #061109 at 42 % (`sauron_eye.svg`'s globe), and the lid #3FB57A. In the centre, the Eye green means only live or selected: the Eye, the live station dots, the focus ring, the drift.

**It is alive, in three ways:**
- **Breathes.** The intro's own glow keyframes (scale 1 → 1.18, opacity .7 → 1, 4 s), continuing the intro's phase after the hand-off. The glow is sized at the intro's ratio (1.36 × the Eye's width). This is the page's one decorative infinite animation, compositor-only.
- **Looks.** The iris moves toward the page under the pointer or in focus: up to 16 px across and 9 px down, scaled by distance, in 260 ms. With no target it returns home. Under reduced motion it does not move.
- **Glows on money events.** A thin Eye-green ring expands from the iris and the glow swells once (1.1 s), on `fill_open`, `fill_close` and `scale_out` in any world, never on quotes or signals. At most once every 2 s: a kill switch or a batch of closes glows once. The glow sits on a wrapper (`.eye-hit`) so it never interrupts the breathing.

**Clicking it enters the Operations Center.** Hover or focus shows "Enter the Operations Center · 2 need you ↵" under it (11 px, ink-2, the count in coral when an alarm is lit); its accessible name says the same.

**Size.** 200 × 126 × es, es = clamp(0.8, 0.9 × s, 1.05) (0.7 in the tight tiers). At 1440 × 900 the box is 180 × 113.

### 4.2 The ring of the day: seven stations

**The words and states come from the platform.**
- The stations, their order and their one-sentence jobs come from `core/day_of_sauron.py` (`STAGES`, :31).
- The state comes from `day_live_payload` (`dashboard/views_day.py:349`) in the five words of `STAGE_STATES` (:47), each a glyph and a word, as on the Oculus and the Operations Center: `● live` (Eye green), `▲ stale` (amber), `✕ broken` (coral), `○ off` (hollow ink-3), `· quiet` (ink-3). A live pill reads "● DECIDE"; a non-live pill reads "▲ SEE stale".
- ⚠ is kept for a Horde watch light and a guard finding, never for a stage.
- For a viewer (non-staff), the pills show hollow dots and the list says "states are staff's". `day_live` is staff-only today (`views_day.py:665`), and this page does not widen that.

**The geometry.**
- Clockwise, ACT at the bottom: SEE 30°, THINK 72°, DECIDE 126°, ACT 180°, WATCH 234°, TELL 288°, LEARN 330°. THINK and TELL sit 18° above the Eye's widest line, where the lid is narrow.
- The ring is drawn as an open arc: the top, between LEARN and SEE, is left open on purpose. It is the night: the road "the night" (Promotion Ladder → Signals) arcs across it, NEXT_OF's "LEARN feeds THINK the next morning" made visible. A small chevron mid-way between neighbouring stations gives the direction of the day; none crosses the night.
- **No pill touches the lid.** The ring's radius starts at 124 × s and grows until every pill keeps 8 px from the lid's outer edge (stroke included), computed from the traced lid. When the full pills ("▲ THINK stale") do not fit with the roads around them, the tighter tiers show the glyph and the title only ("▲ THINK"); the word stays in the pill's accessible name, its title and its list.
- **A station is a button.** Its list (a 290 px popover): the header "THINK · ▲ stale · ran 4 min · 1 of 19 late · 8 more", then "Open THINK on the Oculus ›" (`/oculus/#stage-think` after O2a), the job sentence, the pages on the ring with their figures, then the stage's other pages as links. The count "+N" is not on the pill: it would read as N new signals.

**One geometry for the platform.** The Wall's ring and the Operations Center's folded loop (`static/js/sv-day-scheme.js:25`) put SEE at 9 o'clock, DECIDE at 12 and TELL at 6; this ring puts the night at the top and ACT at the bottom. Same order and direction, different rotation. This spec keeps the hall's (night at the top) and proposes that the Wall follow in S2.7 (the brand moments), so the platform draws one ring.

### 4.3 The pages on the ring

Twenty pages, chosen because they carry the platform's flows and its money (the map's §3 with its nearest stage). Each element is:
- an 8 px dot (ink-2; amber when its data is late; coral when the Horde has an alarm on it; Eye green when selected);
- its name in Inter 12/600 ink-1;
- one figure in JetBrains Mono 11 ink-2;
- for a late or lit page, a third line in its tone with glyph and words ("▲ checked 2 h ago", "⨯ 2 alarms");
- one link to its page.

The hover card adds the figure's source and age, and its roads in and out ("in · quotes · from Instruments & Quotes"; "out · signals · to Asset Bots · read at its next tick"; a quiet road says "no push: drawn, never animated").

| Angle | Page (URL name) | Stage | Figure (mock) | Source | p2 |
|---|---|---|---|---|---|
| 12° | Economic Calendar (`economic_calendar`) | SEE | US CPI in 37 min / ▲ checked 2 h ago | The next high-impact row (`EconomicEvent`, 1 query); late against the beat entry `check-economic-calendar`'s 30 min | ✓ |
| 36° | News & Sentiment (`news_feed`) | SEE | 24 items today | day_live SEE: "news items scraped today" (`views_day.py:205, 214`); `news` push | |
| 52° | Instruments & Quotes (`instruments_list`) | SEE | 41 priced · 6 s | day_live SEE (priced < 15 min, newest age); `quote` push for the age | |
| 68° | Sauron's Mind (`brain_dashboard`) | THINK | trending · 2 h ago | Newest `BrainReport` with no error: regime and age; confidence in the card | |
| 84° | Signals (`signals_list`) | THINK | 13 on the rail | The rail's own `active_n` (`rail_snapshot`, `signal_rail.py:818`); held count in the card; `signal`, `new_signal` | |
| 100° | Opportunities (`opportunities_dashboard`) | THINK | 5 matches today | `OpportunityFlag` scanned since 00:00 UTC | ✓ |
| 116° | Asset Bots (`asset_bots_dashboard`) | DECIDE | 4 of 6 on · 3 min | day_live DECIDE (bots on, freshest tick) | |
| 132° | Capital Desk (`desk_dashboard`) | DECIDE | shadow · 2 sized | The newest desk plan; its mode in words (shadow: chooses and records, every candidate runs at full size) | |
| 148° | Share Allocator (`shares_dashboard`) | DECIDE | governor 1.00 | `share_allocator.governor_for(drawdown_pct)` on the drawdown already read (0 queries): 1.00 until 5 % under the high-water mark (`share_allocator.py:74-76, 329-336`) | ✓ |
| 168° | Positions (`positions_list`) | ACT | 3 real · 2 demo · 2 paper / ⨯ 2 alarms | `open_by_world` counts (`_panel_detail`), never a total; the light from the Horde's tab (§5.3) | |
| 192° | Brokers (`brokers_page`) | ACT | eToro REAL · 40 s | The account row's world (`broker_env`) and the sync's age (60 s cadence) | |
| 212° | Portfolio (`portfolio_overview`) | WATCH | REAL margin 42.1% | eToro's own cells: used over equity (`panel_etoro.used`, `.total`), with the chip of the world the sync read. The platform book (all worlds, mixed currencies) stays on the page with its explanation | |
| 228° | The Orcs (`orcs_list`) | WATCH | 7 on watch | Orcs alive (`orcs/models.py:47`, 1 query) | ✓ |
| 244° | System Health (`system_health`) | WATCH | 4 feeds live · 1 off | `market_data.feeds.feed_states()` (4 queries), the pill's own verdict | |
| 260° | Notifications (`notifications_inbox`) | TELL | 2 unread · 6 today | Per user (`views_day.py:316-319`); `notification` push | |
| 276° | Strategist Briefing (`briefing_dashboard`) | TELL | today 06:04 UTC | The newest briefing's time (daily, 06:00 UTC) | |
| 292° | Ask Sauron (`research_view`) | TELL | answers live | State only; `sauron_answer` push | ✓ |
| 308° | Bot Performance (`bot_performance_dashboard`) | LEARN | 3 graded today | Trades graded since 00:00 UTC (`grade_bot_trade` at the close) | |
| 324° | Promotion Ladder (`promotions_dashboard`) | LEARN | 2 promoted · night | The night's promotions | |
| 348° | Strategy Evolution (`evolution_dashboard`) | LEARN | 4 mutations · night | The night's mutations | ✓ |

- **Labels anchor outward:** within 12° of the top above the dot; between 150° and 210° below it; otherwise beside it, away from the centre. Economic Calendar (12°) and Strategy Evolution (348°) sit above their dots, which keeps them clear of News and the Ladder at 1366 and 1536 px.
- **p2 pages** leave the ring in the compact tier (below 1366 px wide in practice). They stay first in their station's list. Their roads hide with them.
- **The Orcs is not in the sidebar** (the Horde opens it). It is on the ring because "born at the fill" is one of the platform's most visible flows.
- **Every missing figure is a named dash** ("— staff only", "— the scan has not run today", "— not read: eToro reads one world at a time"). **Every stored reading prints its age** (the Oculus rule).

**The station lists (36, by nearest stage, map §3):**
- **SEE:** Big Money.
- **THINK:** Strategies, Setups, Event Engine, Hypothesis Market, Intelligence Hub, Earnings Reviews, AI Insights, The Council (staff).
- **DECIDE:** Bot Program, Personalities, Withdrawals, Treasury.
- **ACT:** Ops (switches; superuser), Admin Panel (kill switch; superuser).
- **WATCH:** Risk Depth, Evidence Ledger, Audit Log (staff).
- **TELL:** Weekly Letter, Newsletters (superuser).
- **LEARN:** Tax Lots, Risk Allocator, Bot Equity Curve, Rule Controls, Signal Performance, Trade Forensics, Backtesting, Bot Backtest, Agent Calibration, Discoveries, Generated Strategies, Knowledge Graph, Consolidation, Horizon, AI Journal, Agent Tasks.
- **No stage (7):** Oculus, Operations Center (bottom line), The Lore (staff), Model Selection (staff), Profile, Setup, Getting Started (user menu).

The lists and All pages are built from the same permission checks as the sidebar, so a staff-only page never shows to a viewer.

### 4.4 The roads

Twenty roads, each named in the platform's words (the map's flows F1–F18, NEXT_OF's sentences, and three the code shows). A road with a push moves; a road with no push is drawn dotted, never animated, and carries no drift.

| Road | From → to | Flow | Moves on (E1 white, E2 in its world's colour) |
|---|---|---|---|
| quotes | Instruments & Quotes → Signals | F1 (SEE → THINK) | `quote` (≤ 1 per 4 s); Signals reads it at its next scan |
| matches | Opportunities → Signals | the scanner creates a signal per flag (`signals/opportunity_scanner.py:1829`) | — (dotted) |
| news | News & Sentiment → Sauron's Mind | F2 | `news`; the mind reads it at its next synthesis |
| signals | Signals → Asset Bots | F3 ("the bots count its vote") | `signal`, `new_signal`; the bots read it at their next tick |
| entries | Asset Bots → Capital Desk | F5 (the gates) | `fill_open` via bot; `gate_reject` stops just after Asset Bots |
| pools | Share Allocator → Capital Desk | F6 | — (dotted) |
| orders | Capital Desk → Positions | F5 (DECIDE → ACT) | `fill_open` via bot |
| take trade | Signals → Positions | F4 (the ticket, by hand) | `fill_open` via manual or words |
| the book | Positions → Portfolio | F8 | `fill_open`, `fill_close`, `scale_out` |
| eToro sync | Brokers → Portfolio | F7 (60 s) | — (dotted) |
| born at the fill | Positions → The Orcs | F13 | `orc_born` (E2), only when an Orc is really born |
| fills told | Positions → Notifications | F14 (WATCH → TELL) | `notification` of a fill type |
| findings | System Health → Notifications | F10 | `notification` of a guard or alarm type |
| closes, graded | Positions → Bot Performance | F9 + F15 | `fill_close` |
| grades | Bot Performance → Promotion Ladder | F15 (the night) | — (dotted) |
| decay | Bot Performance → Strategy Evolution | F15 | — (dotted) |
| the night | Promotion Ladder → Signals | F15 (LEARN → THINK) | — (dotted) |
| events ahead | Economic Calendar → Positions | the care's rule (`position_care.event_for`, `bot_program/position_care.py:358`) | — (dotted) |
| the briefing | Sauron's Mind → Strategist Briefing | the briefing reads the newest report (`brain/strategist.py:39`) | — (dotted) |
| answers | Sauron's Mind → Ask Sauron | `sauron_answer` (`brain/tasks.py:217, 246`) | `sauron_answer` |

The briefing and the answers leave the mind together over the top: one bundle on one lane that forks near TELL. No page on the ring is an island.

**Drawing.**
- A road leaves its page radially, turns on a 10 × s corner, follows an arc on its lane, turns and reaches its page radially. Roads leaving or reaching one page fan out 2.2° apart, sorted by direction, so the roads arriving from one side and those leaving to the other can share lanes.
- **The lanes start outside the station pills** (ring radius + the pills' radial extent + 10 px) and are 12 × s apart (10 × s in the closer tiers).
- **The lane plan keeps every road inside its pages.** A lane fits a road only if the road and its corner stay 6 px inside both of its pages and 10 px inside every page its arc passes. Long roads take the inner lanes; short ones (under 40°) the outer lanes where they fit; two roads never share a lane over the same angles (a 1° margin beyond the fans), except the bundle.
- Stroke 1 px line-3; a quiet road is dotted (2 3); a lit road 1.5 px ink-3.
- **Names** sit on the road, 11 px ink-3 with a bg-0 halo, at the first of nine positions along and beside the arc that overlaps no page, no station, no other name and not the Eye. A name with no free place shows when its road lights. At 1440 × 900 that is 2 of 20 ("matches", "eToro sync"); at 1920 none.
- Particles never travel a road that is not drawn.

**The tiers** (the layout tries them in order and keeps the first that passes every check):

| Tier | Pages | Pills | Lane spacing | Eye scale floor | Measured at |
|---|---|---|---|---|---|
| full | 20 | glyph + title + word | 12 × s | 0.8 | 1920 × 1080, 2560 × 1440 |
| full-close | 20 | glyph + title + word | 10 × s | 0.8 | 1440 × 900, 1536 × 864 |
| full-tight | 20 | glyph + title | 10 × s | 0.7 | 1366 × 768 |
| compact, compact-tight, compact-snug | 14 | words, then glyph + title | 12, 10, 8 × s | 0.8, 0.7 | (fail at 1280) |
| compact-min (last resort) | 14 | glyph + title | 8 × s | 0.7 | 1280 × 720, 1280 × 800 |

**At 1280 px wide the last resort is cramped.** No label overlaps and no pill touches the lid, but the side hubs (Signals, Notifications) need more lanes than the 170 px half-width leaves: the quotes road passes 5.5–5.8 px from Sauron's Mind's dot and its corner reaches 12–13 px beyond Signals' radius. E1 decides between two cures, measured: draw only the push roads below 1366 px (the quiet ones on hover), or narrow the side columns to 264 px there.

### 4.5 Particles and the drift

**Event particles.**

| Kind | Look |
|---|---|
| Money event on REAL (`world` live) | Solid #CC3A40 core: the platform's only solid red, REAL money |
| Money event on DEMO (`demo`) | Gold #D6BC5E |
| Money event on PAPER (`paper`) | Grey #B4C0BC |
| A row that states no venue (`""`), and everything else (quote, signal, news, notification of a fill) | Ink-1 white |
| A guard finding | Amber #F29B38, with its words in Notifications |

- A 2.3 px core with a soft glow sprite (drawn once, then blitted) and a short fading trail; it travels its road in 0.9–2.3 s, eased in and out.
- **Rings only where something happens.** The source page rings as a particle leaves (quote, signal, news). The destination rings on arrival only where it reacts at once: Positions on a fill (red for REAL), the Orcs on a birth, Notifications on a message, Bot Performance on a graded close, Ask Sauron on an answer. Signals, Asset Bots and Sauron's Mind read on their own cadence (15 min, 5 min, hourly) and do not ring; their hover card says "read at its next tick".
- **A refusal by the exposure caps** (`gate_reject`, `orchestrator.py:478-506`) stops just after Asset Bots and rings Asset Bots amber. The desk's figure comes only from its own plan and never moves on a refusal.
- **No particle ever carries a number or a label.** A figure that changes washes for 900 ms; its text colour never flashes and nothing counts up.

**The drift.**
- One mote per road that carries a push (12 of 20 at 1440): 1.4 px, the Eye green at 30 %, 16 px/s. It shows the roads' direction at rest. Quiet roads carry none, so nothing suggests the night's work at midday.
- **Ten frames a second, by a timer.** Frames are requested only while a particle travels or the pointer moved in the last second (then 60 per second).
- **It sleeps after a quiet minute:** 60 s with no pointer movement, no key and no event. Any of them wakes it.
- **It stops when the feed stops:** a closed socket or a failed feed stops it, and the top line says "live updates paused". Closed markets do not stop it: the feed line says "markets closed · reopens Mon 00:00 UTC" and the drift goes on.

**Limits.** At most one particle per road per 400 ms and 12 in flight. Quotes start at most one particle every 4 s.

### 4.6 Events → roads

| Push (socket) | Kind | Roads, in order | Colour (E2) | Also |
|---|---|---|---|---|
| /ws/eye/ | `fill_open`, `via` bot | entries → orders → the book | world | Eye glow (≤ 1 per 2 s); Positions rings; re-fetch |
| /ws/eye/ | `fill_open`, `via` manual or nl | take trade → the book | world | same |
| /ws/eye/ | `orc_born` (new, E2) | born at the fill | world | the Orcs ring; their count |
| /ws/eye/ | `fill_close` | closes, graded ∥ the book | world | Eye glow; Bot Performance rings; re-fetch |
| /ws/eye/ | `fill_close`, source `kill_switch` | the book; Positions rings amber | world | the kill switch cell reads "fired" from the re-fetch; one glow for the burst |
| /ws/eye/ | `close_pending` | — (Positions rings amber) | — | re-fetch |
| /ws/eye/ | `scale_out` | the book | world | re-fetch |
| /ws/eye/ | `gate_reject` | entries, stopping just after Asset Bots | white | Asset Bots rings amber; the desk is untouched |
| /ws/eye/ | `notification` | fills told (fill types), findings (guard or alarm types); otherwise Notifications rings | white / amber | an alarm type puts its words in NEED YOU; re-fetch |
| /ws/eye/ | `new_signal` (staff) | signals | white | the Signals source rings |
| /ws/dashboard/ | `signal` | signals | white | the Signals source rings |
| /ws/dashboard/ | `quote` | quotes (≤ 1 per 4 s) | white | the Instruments age only; no re-fetch |
| /ws/dashboard/ | `news` | news | white | the News figure |
| /ws/eye/ | `sauron_answer` | answers | white | Ask Sauron rings |
| /ws/eye/ | `run_complete`, `council_sitting` | — (the page's dot rings, when it is on the ring) | — | — |
| /ws/eye/ | (socket closed by the consumer on `session_locked`) | — | — | the lock path (§6.4) |

**What E2 adds to the pushes (display fields only):**
- `"world": world_of(trade)` (`dashboard/position_summary.py:253-270`: `"live"`, `"demo"`, `"paper"`, or `""` for a row that states no venue) on every trade push: 11 call sites (`asset_engine/base.py:3863, 4356, 4488, 4525, 7597`; `manual_trade.py:3823`; `reconcile_asset.py:1023`; `pending_closes.py:1459, 1518`; `nl_trader.py:184`; `engine/kill_switch.py:39`, the helper that sends the kill switch's four).
- `"via": "bot" | "manual" | "nl"` on `fill_open`, so a bot fill and a ticket fill take their own roads.
- `orc_born`, sent from `orcs/birth.py`'s `_ensure_quietly` after `ensure()` creates an Orc (after the commit, only while the Orcs are on, never for options or working entries, within the paper and demo cap). One call site.
- A test asserts each trade push carries one of the four world values; `""` stays white.

**Notification types.** The map from `notification_type` to road is a fixed table in `sv-hall.js`. A test pins it against alerts' type choices, so a new type falls back to "Notifications rings" rather than to a wrong road.

### 4.7 Hover, focus, keyboard, accessibility

**Hover or focus on a page:** the Eye looks at it; its roads light and their names show; unrelated pages fade to 42 %; a card (bg-2 popover, 300 px) gives the purpose, the figure, its source and age, and the roads in and out. Hover enhances, never gates: the same facts are in the element's accessible name and on the page it opens.

**Keyboard and assistive technology:**
- **Tab order:** the top line, then the pages in the day's order, the Eye, the side panels, the bottom line.
- **Keys:** Enter (nothing focused) the Operations Center; `O`, `P`, `S`; `/` All pages; `1`–`7` a station's list with focus on its first link; `Esc` closes. The bottom line's keys are real links with the same targets, so every key has a mouse path.
- **Structure for readers:** the elements are real links grouped in one `<section>` per stage, named by the stage's job sentence. The canvas and the road SVG are `aria-hidden`; the roads are written into each page's description.
- **Focus** is a 2 px Eye ring with a 2 px offset (UI plan §7). Key letters are set in Inter 600, so `O` never reads as a zero.
- **Contrast:** names ink-1, figures ink-2 and road names ink-3 all meet 4.5:1 on bg-0 (ink-3 is 6.6:1).

### 4.8 Layout rules

| Element | Rule |
|---|---|
| Positions | One table of angles (§4.3), scaled to the centre column. No force simulation: the same page is always in the same place |
| Scale | s = clamp(0.8, min(W / 776, H / 816), 1.3) |
| Page ellipse | rx = min(246 s, W/2 − 150), ry = min(290 s, H/2 − 62) |
| Station ring | From 124 s, grown until every pill keeps 8 px from the lid |
| Lanes | From the ring + the pills' radial extent + 10; spacing per tier; the lane plan of §4.4 |
| Tiers | §4.4; the compact tiers start when the centre is narrower than 700 px |
| Checks | Measured on the mock at 390, 1280 × 720, 1280 × 800, 1366 × 768, 1440 × 900, 1536 × 864, 1920 × 1080 and 2560 × 1440 (§12) |

---

## 5. The two sides and the two lines

All cards are the kit's `.sv-panel`: bg-1, 1 px line-2, radius 6, a 40 px head with the title in 12 px uppercase ink-2 and the meta in 11 px ink-3. They are opaque, and no glow sits behind a number. At ≥ 880 px of height the side columns fit without scrolling (measured: 816 of 816 px at 1440 × 900). Below that they scroll inside their column, never the page.

### 5.1 Left: the book's performance

**PERFORMANCE.** One window switch (1D, 7D, 30D, 90D) governs the charts. One block per world, never on a shared axis.

| World | What it shows | Source |
|---|---|---|
| REAL | eToro equity, its change over the window, three cells (OPEN NOW, 24 H, FROM HIGH), eToro's used and available, the curve | §5.1 below |
| DEMO | The same when the account is on DEMO, or the last stored DEMO reading with its true age; otherwise "— not read: eToro reads one world at a time; the account is on REAL" | `broker_env(acct)`; `BrokerEquityReading` with `env="paper"` |
| PAPER | Realized P&L, cumulative (step line), "77 closes · 30 d" in ink-3; "no equity series is kept" | The world's closes; the simulator keeps no equity series |

**One world at a time.** The live reading goes on the card that `broker_env(acct)` names (`live` → REAL, `paper` → DEMO). The other world's card shows its last stored `BrokerEquityReading` for that environment with its true age, or the dash above. Open P&L says "eToro's own" only for the account's world (after F4); the other world says "≈ estimate". A test: with `acct.demo=True`, `equity.real.last` is null and the REAL card prints the dash.

**REAL, in detail.**
- **Equity:** `account_equity(user)` when `broker_env` is `live`: value, currency, age ("eToro · 40 s").
- **The change over the window:** "+217.40 · +2.12% ▲ · 30 d", net of paid withdrawals, on the drawdown's own basis: each reading compared as it would read had every later paid withdrawal already left (`withdrawals.flow_adjusted_value`, `paid_flows_for(user, currency)`, `capital_truth.py:851-918`), with its filters (`account_pk`, the reading's currency, `env` empty or the account's). Its title says "net of paid withdrawals · deposits are not known to Sauron". The arrow comes after the figure, as everywhere.
- **The three cells:** OPEN NOW "≈ +76.26 ▲" (ink-1: an estimate until E3, the words in its title: "estimate: eToro quote, 12 s · 3 of 3 rows"); 24 H "+12.40 ▲" (booked closes, jade); FROM HIGH "−3.12%" (`equity_drawdown`, coral text, REAL only, null when the account is on DEMO).
- **eToro's cells:** "used 42.1% · available $5,955.11" (`panel_etoro.used`, `.available`; with eToro's P&L on all positions they add up to the equity; the title says so).
- **The curve:** `BrokerEquityReading` (broker etoro, env live), at most 180 points (1D: 96 × 15 min; 7D: 168 hourly; 30D: 180 × 4 h; 90D: 180 × 12 h), plotted net of paid withdrawals. Each paid withdrawal inside the window is marked on the time axis with its amount. The dashed high-water line ("high-water $10,790.20 · 24 Oct · net") is drawn on the same basis, only when it falls inside the window's range.

**How the charts are drawn.** 2 px line coloured by the window's sign (jade up, coral down: these are eToro's own readings and booked closes); a 10 % wash under it; an 8 px end dot with a 2 px surface ring; hairline grid; axis text in mono 11 ink-3. A crosshair finds the time across the charts; one tooltip lists the worlds at that time, keyed by the world chips (REAL equity, net; DEMO "— not read"; PAPER realized). The tooltip enhances, never gates.

**P&L.** A table with columns REAL · USD, DEMO · USD, PAPER · USD (the currency codes come from the payload; a world mixing currencies prints a code per cell). No total column, no total row.

| Row | Rule |
|---|---|
| open | `_panel_detail`'s `panel_open_pnl_live/_demo/_paper`, the band's cached figures, so the two screens print the same digits. REAL and DEMO show "≈" and stay ink-1 while they are estimates; PAPER is the simulator's mark (ink-1) |
| 24 h, 7 d, 30 d | Realized, rolling windows: one read of the user's closed trades (`values("paper", "metadata", "pnl", "closed_at")`) split by `world_of` in Python, the Operations Center's R2 read. A world with no close prints "—" with "nothing closed in this world in 24 h" |

The note under the table words the source per PR #89's tiers: `etoro` → "eToro's own · 8 s" (after F4); `etoro_quote` → "estimate: eToro quote, 12 s"; `estimate` → "estimate: eToro tick price, 3 min" or "estimate: <feed> quote, <age>" (the feed's name through `_feed_label`). PAPER: "the simulator's mark, Yahoo quote, 3 min" (`venue_pnl` returns None for paper rows; the mark's feed and age).

**Colour.** Jade and coral mark polarity on booked closes and on eToro's own figures; an estimate (≈) and the simulator's open mark stay ink-1 with their arrow. A count is never coloured as a gain.

### 5.2 Right: the day's activity

**SIGNALS TO ACT ON** — the Operations Center's R6, short.
- The rail's own list and order (`rail_snapshot(request)`, `signal_rail.py:818`): on what you hold first, then voting now, then new since you looked. The first three, each with symbol, side chip, score meter, score and age, and under it the held words ("you hold it: REAL short 1.5 · adds to it"; "against it").
- Meta: "13 on the rail · 3 held" (`active_n`, `held_n`). Foot: "+10 more · Signals ›" (`active_n` − 3) and "the rail's list and order".
- No TAKE TRADE here: a row opens its signal; the card's TAKE TRADE stays behind the ticket's PIN.

**LAST 24 H** — the chart on the right.
- One 14 px lane per world (REAL, DEMO, PAPER), never on one axis, over the rolling 24 h before the payload's time; axis "−24 h · 18:00 · 00:00 · 06:00 · now".
- A tick for each open; a dot for each close, jade or coral by its sign; a coral ⨯ for an alarm on that world (a close refused, a close given up).
- Each lane's head: the world chip, "4 opened · 2 closed", and "⨯ 2 alarms" when lit; a world with nothing reads "nothing opened or closed in 24 h".
- Hover a mark: the trade ("XAUUSD: eToro refused the close; retried since 12:11 UTC").
- Source: one read of the viewer's trades opened or closed in 24 h, split by `world_of`; the alarms from the Horde's tab.

**WIN RATE · EXPECTANCY** — closed bot trades of his book, 30 d.
- `performance_by_venue(user=viewer, days=30)` (its defaults are `user=None, days=180`, `bot_grading.py:347-369`), totals per world weighted by trade count.
- One line per world: "46% won · +0.12R a trade · n 24".
- Under 10 trades: "— not judged · n 3", no colour (the Oculus rule, `oculus_spec.md:1086`).

**THE MACHINE** — staff for guards and the beat.

| Row | Mock | Source |
|---|---|---|
| Bots | REAL 2 · DEMO 0 · PAPER 2 · off 2; "ticked 3 min ago · every 5 min" | Configs by world, read from each config's account (live mode on an eToro account with `demo` on → DEMO), as the Operations Center's R7 note |
| The Orcs | 7 on watch · 3 intents today; "minds in shadow · nothing placed" | Orcs alive, `OrcIntent` today, the switches' words; the title: "one per open position while the Orcs are on (paper and demo capped at 10; none for options)" |
| Guards | ⚠ 1 finding · 12 ran 2 min ago; "XAUUSD (REAL) closing for 42 min" | The Morgul summary from the cache (`morgul:summary`); staff only |
| The beat | 64 tasks · 62 on time · ▲ 2 late | `day_live_payload`'s counts; staff only |

Amber appears only with a glyph and words.

### 5.3 The two lines

**Top line (40 px)**, in the shell's words (the Oculus and Operations Center mocks):
- the hexagon mark and the Orbitron wordmark SAURON;
- the title "BARAD-DÛR" (14 px, 600, .06em, uppercase) and the tagline "the pages and their roads" in ink-3, shown at 1440 px and wider;
- **NEED YOU**, the first cell: "⨯ 2 alarms" in coral with "· 6 watch ›" beside it; "⚠ 1 watch" in amber when only watch lights are lit; "● all clear" in ink-2 when none. It reads the Horde's tab (`dashboard/horde.py:2196 tab()`, cached on the book's fingerprint; `_tab_of` :2085 counts the seats' alarm lights plus the closes given up), the Operations Center's POSITIONS · NEED YOU in short. It links to /command/; its title lists the alarms in the Horde's words. An alarm-type `notification` puts its words in this cell, because the hall has no toast. The Positions dot takes the same light;
- KILL SWITCH "ready · 7 d quiet", or "✕ fired 14:02 · manual" in coral words: `panel_bot.kill_at` and `kill_reason` from `_bot_truth` (`core/context_processors.py:779-792`: the "KILL SWITCH ACTIVATED" notification of the last 7 days), already in `_panel_detail` (0 extra queries). For superusers it links to `admin_dashboard#flattenForm`;
- the feed: "● eToro · live · 6 s", the shell pill's own verdict;
- the armed pill "REAL ARMED · 2 BOTS" (the shell's), which opens Positions;
- the UTC clock, anchored to the payload's time;
- the bell with the unread count (→ Notifications);
- the lock button: `id="lockNowBtn"` with `data-has-pin` (`idle-lock.js:136-141`);
- the user menu "OPERATOR ▾" (§2.4).

**Bottom line (44 px):**
- the shortcuts as real links with keycaps: ↵ Operations Center, O Oculus, P Positions, S Signals, / All pages; then "1–7 a stage" and "Esc clear";
- "display only · read 12 s ago";
- "ENTER THE OPERATIONS CENTER →" in the kit's secondary look. The Eye stays the brightest thing on the page.

### 5.4 Numbers and words (UI plan §4.4, the Oculus and the Operations Center)

- **Money:** grouped, two decimals; P&L carries its sign, then ▲ or ▼ after it ("+217.40 · +2.12% ▲ · 30 d"); the ASCII hyphen as the minus.
- **Currency:** from the readers only. Equity and the drawdown: `account_equity()["currency"]` as a symbol prefix ($ for USD; a code suffix for any other). Trade P&L: USD. A world mixing currencies: a code per cell. There is no fixed € anywhere; the synthetic account is in USD, like the Operations Center's.
- **Percent:** two decimals with sign. **R:** two decimals with R.
- **Counts:** in mono, never coloured as gains; a count may stand beside its split, never alone.
- **Ages:** "6 s", "3 min", "2 h", "3 d". Every stored reading prints its age; one without an age is a dash.
- **Windows:** every count names its window: "today" (00:00 UTC, the stations' metrics), "24 h" (rolling: realized P&L and trades, as the Operations Center), "7 d", "30 d", "night".

---

## 6. The data contract

### 6.1 One payload

**How it is served.**
- `GET /api/barad-dur/` answers one JSON document, built by `dashboard/hall.py: hall_payload(user, now=None)`. It sits under `/api/` and the page sends `Accept: application/json`, so the idle lock treats it as machinery: it never re-stamps the session as human, and a locked session gets 423, not a redirect (`core/idle_lock.py:89-104, 138-146, 161-164`).
- `GET /api/barad-dur/?probe=1` answers 204 with no work (423 when locked): the page's 10 s lock probe.
- The same builder fills the page's first render through `json_script`, so the first paint needs no request.
- Version field `v`. Every money figure carries `world`, `ccy`, `source`, `at` and `age_s`. Every missing figure carries `dash`: the words to print instead.

```json
{
  "v": 2,
  "at": "2026-11-07T12:53:08Z",
  "viewer": {"staff": true, "superuser": true},
  "feed": {"state": "live", "source": "eToro", "age_s": 6, "words": "eToro · live", "markets": "open"},
  "kill": {"state": "ready", "quiet_days": 7, "fired_at": null, "reason": null},
  "needs": {"alarms": 2, "watch": 6, "top": [{"symbol": "XAUUSD", "world": "live", "words": "Closing: eToro refused the close; it is still open there · 42 min, 8 retries"}]},
  "account": {"env": "live", "ccy": "USD", "equity": 10453.61, "used": 4402.10, "available": 5955.11, "pnl": 96.40, "age_s": 40},
  "worlds": {
    "live":  {"open": 3, "closing": 1, "bots_armed": 2},
    "demo":  {"open": 2, "closing": 0},
    "paper": {"open": 2, "closing": 0},
    "":      {"open": 1}
  },
  "equity": {
    "window": "30D", "basis": "net of paid withdrawals",
    "live":  {"ccy": "USD", "series": [["2026-10-08T12:00Z", 10236.21], "... at most 180 points"],
              "last": {"value": 10453.61, "age_s": 40, "source": "eToro's sync"},
              "withdrawals": [], "hwm": {"value": 10790.20, "at": "2026-10-24T..."}},
    "demo":  {"dash": "not read: eToro reads one world at a time; the account is on REAL", "stored": null},
    "paper": {"series": null, "dash": "the simulator keeps no equity series", "realized_cum": [["...", 0.0], "..."], "closes": 77}
  },
  "realized": {
    "live":  {"ccy": "USD", "h24": 12.40, "d7": -41.20, "d30": 141.14, "closes_24h": 2},
    "demo":  {"ccy": "USD", "h24": null, "dash_h24": "nothing closed in this world in 24 h", "d7": -201.33, "d30": -834.47},
    "paper": {"ccy": "USD", "h24": -40.81, "d7": 31.90, "d30": 73.03, "closes_24h": 5}
  },
  "open_pnl": {
    "live":  {"value": 76.26, "source": "etoro_quote", "words": "estimate: eToro quote, 12 s", "rows": 3, "of": 3},
    "demo":  {"value": 66.90, "source": "estimate", "words": "estimate: eToro tick price, 3 min", "rows": 2, "of": 2},
    "paper": {"value": 6.60, "source": "mark", "words": "the simulator's mark, Yahoo quote, 3 min", "rows": 1, "of": 2}
  },
  "drawdown": {"live": {"pct": 0.0312, "hwm": 10790.20, "hwm_at": "...", "age_s": 40, "window_days": 90, "net_of_withdrawals": true}},
  "day24": {"live": {"opens": ["..."], "closes": ["..."], "alarms": ["..."]}, "demo": {"...": "..."}, "paper": {"...": "..."}},
  "perf_30d": {
    "live":  {"n": 24, "won": 0.46, "exp_r": 0.12},
    "demo":  {"n": 3, "dash": "not judged · n < 10"},
    "paper": {"n": 77, "won": 0.55, "exp_r": 0.21}
  },
  "signals": {"active_n": 13, "held_n": 3, "top": [{"id": 0, "symbol": "XAUUSD", "side": "short", "score": 0.72, "age_s": 240, "held_words": "you hold it: REAL short 1.5 · adds to it"}]},
  "bots": {"live": 2, "demo": 0, "paper": 2, "off": 2, "tick_age_s": 180, "cadence_s": 300},
  "orcs": {"alive": 7, "intents_today": 3, "words": "minds in shadow · nothing placed"},
  "guards": {"ran_age_s": 120, "n": 12, "findings": [{"key": "stuck_close", "words": "XAUUSD (REAL) closing for 42 min"}]},
  "beat": {"tasks": 64, "on_time": 62, "late": 2, "broken": 0},
  "stages": {"see": {"state": "stale", "words": "ran 6 s · 1 of 21 late"}, "think": {"...": "..."}},
  "pages": {"signals_list": {"fig": "13 on the rail", "state": "live", "age_s": 60}, "...": "..."},
  "more": {"think": [{"name": "Strategies", "url": "/strategies/"}, "..."]},
  "nav": [{"group": "Amon Hen", "rows": [{"name": "Barad-dûr", "url": "/barad-dur/"}, "..."]}, "..."]
}
```

**For a viewer** (non-staff), the staff-only keys (`stages[*].state`, `guards`, `beat`, and the platform figures of Asset Bots, Capital Desk and System Health) are replaced by `{"dash": "staff only"}`, never dropped in silence. The viewer's own book is always theirs.

### 6.2 Readers, queries and the caches

Measured on the synthetic fixture with every broker client and every outbound connection made to raise (`mock_tools/budget.py`, `budget.json`):

| Block | Reader (existing) | Queries | Cache |
|---|---|---|---|
| Open P&L and positions per world, eToro's cells, kill switch | `_panel_detail` (`core/context_processors.py:1002`) | 48 cold, 4 warm (70 ms / 3 ms) | The band's 20 s cache on the book fingerprint |
| NEED YOU | `horde.tab(user)` (`dashboard/horde.py:2196`) | 52 cold, 4 warm (72 ms / 4 ms) | Its own, on the fingerprint |
| Stations, SEE–TELL page figures | `day_live_payload` (`views_day.py:349`) | 17 (14 ms) | 5 s shared micro-cache |
| Signals to act on | `rail_snapshot(request)` | 10 (11–25 ms) | 5 s micro-cache |
| Drawdown (and the governor) | `equity_drawdown` + `governor_for` | 2 + 0 | none |
| Equity series | `BrokerEquityReading`, one read, split and downsampled in Python | 1 | 300 s (one sync cadence) per user and window |
| Win rate, expectancy | `performance_by_venue(user, days=30)` | 3 (6 ms) | On the fingerprint |
| Realized 24 h, 7 d, 30 d | One read of closes, split by `world_of` | 1 | On the fingerprint |
| Last 24 h | One read of trades opened or closed | 1 | On the fingerprint |
| System Health | `feed_states(now)` | 4 | 5 s micro-cache |
| Notifications | Unread and today | 1 | 5 s micro-cache |
| Calendar, mind, opportunities, briefing, graded, promotions, mutations | One small read each (2 measured at 1; 5 counted at 1) | ≈ 7 | 60 s |
| Orcs | Alive, intents today | 2 | On the fingerprint |
| Bots by world, the desk's plan | Configs with their accounts; the newest plan | ≈ 3 | Bots on the fingerprint; the desk 5 s |
| Guards | `morgul:summary` | 0 | Morgul's |

**The caches.** The book's blocks (everything that changes only when trades, positions or configs change) are cached on the book's fingerprint (`core/context_processors.py:202-225`). Everything else is built per request behind a 5 s micro-cache shared by the viewer's tabs, which an event-triggered re-fetch bypasses, so a signal, a message or a refusal shows in its figure on the first re-fetch. Slow figures (hourly and nightly) are cached 60 s; the equity series 300 s.

**Budgets asserted in E1 (`assertNumQueries` on the fixture):**
- payload, warm: ≤ 50 (counted: 4 + 4 + 17 + 10 + 2 + 4 + 1 + 1 + 1 = 44);
- payload after a fill (the fingerprint changed, the book's blocks cold): ≤ 160 (counted ≈ 150, ≈ 200 ms on the fixture);
- GET /barad-dur/: the payload plus the session, the user and the lock's profile read: ≤ 55 warm;
- no context processor runs on the GET.

### 6.3 Refresh and push

- **Poll:** `/api/barad-dur/` every 60 s while visible and unlocked; never while hidden or locked.
- **Lock probe:** `/api/barad-dur/?probe=1` every 10 s while visible and unlocked (no work; 423 when the session was locked from another tab).
- **Push:** the hall opens its own sockets, because it does not extend base.html: /ws/eye/ (per user; the consumer accepts any signed-in, unlocked, non-investor session, `consumers.py:230-252`) and /ws/dashboard/ (broadcast: quote, signal, news). It closes both on `sv:pin-locked` and when hidden for more than 60 s, and reconnects with base.html's backoff.
- **On a push:** animate at once (§4.6), then one re-fetch 800 ms later (debounced, at most one in flight, at most one every 5 s, bypassing the micro-cache). Quotes never cause a re-fetch.
- **Between fetches the page invents nothing.** A particle says "something happened here"; the numbers change only when the payload says so.
- **Ages and the clock never trust the viewer's clock:** an age is the server's `age_s` plus the time since the payload arrived, measured with `performance.now()`; the clock starts from `payload.at`; a cell that sums several rows shows its oldest row's age.
- **Nothing is polled per frame.** The clock and the ages are a text update once a second.

### 6.4 The standalone page's plumbing

**The idle lock.**
- The overlay markup moves out of base.html (8450-8505) into `templates/_partials/idle_lock.html`, byte for byte, and base.html includes it. The hall includes the same partial (`idle-lock.js` needs `#idleLockOverlay` to engage, `idle-lock.js:164-165`) and `static/js/idle-lock.js`.
- The explicit context carries what the context processors would: `idle_lock.enabled`, `idle_lock.minutes`, `idle_lock.has_pin`, `pin_locked`, and `csrf_token` from `get_token(request)` (without it `{% csrf_token %}` in `ilLogoutForm` renders empty, and Log out and "PIN forgotten?" fail with 403).
- **On `sv:pin-locked`** (Lock now, the idle timeout), **on any 423**, and **on an unexpected /ws/eye/ close followed by a probe that answers 423** (the consumer closes the socket on `session_locked`): the page paints an opaque veil in the same frame (no figure stays visible), stops every animation, closes its sockets and its polls, then `location.replace('/locked/?next=/barad-dur/')` once the probe answers 423 (it asks every 250 ms, at most 2 s; /locked/ sends an unlocked session straight back). /locked/ is the existing standalone gate (`dashboard/lock_views.py:33-48`): the PIN brings him back here.
- The hall does not load `sv-overlay.js`, `sv-gate.js` or the shell's gate CSS: /locked/ draws the gate.
- One run state: paused while hidden, locked or offline; nothing restarts the motion while locked (a tab hidden and shown again under the lock stays still); the sockets reopen only on `sv:pin-unlocked` (or a fresh page after /locked/).
- The middleware already covers /barad-dur/ and /api/barad-dur/: neither is in `EXEMPT_PREFIXES` (`idle_lock.py:55`), so a locked GET of the page goes to /locked/?next=/barad-dur/ and the data endpoint answers 423.

**The investor gate** keeps investors out (§2.3). **CSRF:** the page posts nothing but idle-lock.js's lock and the logout form.

---

## 7. Motion and performance

### 7.1 One animated layer

- **Per frame,** only the particle canvas is drawn: one `<canvas>` over the centre column (backing store × devicePixelRatio, capped at 2); sprites drawn once and blitted; each road pre-sampled every 2 px at layout; only the rectangles drawn in the previous frame are cleared.
- **Static,** drawn on layout or data change only: the ring, the roads and their names (one SVG); the page labels (DOM links).
- **On the compositor:** the Eye's breathing, gaze and glow (CSS transforms and opacity).
- **Infinite CSS animations** (a declared §8 exception, like S2.7's brand moments): the Eye's breathing, the faint globe's 90 s turn (the intro's own), the live dot's heartbeat. All three stop under reduced motion.

### 7.2 The run state and its cost, measured on the mock

**The rules:**
- 60 frames a second while a particle travels or the pointer moved in the last second (requestAnimationFrame);
- otherwise the drift alone, 10 frames a second, by a timer (no requestAnimationFrame);
- nothing after a quiet minute, while hidden, while locked, under reduced motion, or with the feed stopped.

**Measured** in headless Chromium at 1440 × 900 (`mock_tools/perf2.js`, `perf2.json`; 4 cores, load average 4–9 during the runs; medians of 3 interleaved runs, 10 s windows):

| State | Main thread (task time) | Script | Frames requested | Draws per second | Style recalcs / 10 s |
|---|---|---|---|---|---|
| The drift alone (10 Hz timer) | 2.6–3.7 % (two sessions) | 0.2–0.3 % | 0 | 9.9 | 108 (the three CSS animations) |
| After the quiet minute (shortened to 3 s for the test) | 0.6–0.7 % | 0 % | 0 | 0 | 10 |
| Before this revision (critique's measure): every frame requested | 10.1 % | — | 58/s | — | 296 / 5 s |

| Check | Result |
|---|---|
| `sv:pin-locked`, then 1.5 s | 0 frames, 0 draws, the veil on |
| Locked, then the tab hidden and shown, then 1.5 s with the pointer moving | 0 frames, 0 draws, no timer |
| Unlocked, then 1.5 s | the drift again (14 draws) |
| Reduced motion, with the event story running | 0 frames, 0 running animations; the static highlight shown on every changed figure ("14 on the rail", "8 on watch", …) |
| The draw alone, busiest fixed scene (`__benchDraw(400)`, 5 runs) | median 0.1 ms, p95 0.2 ms unthrottled; p95 0.9–1.3 ms with the CPU slowed 4× |
| The live story with the CPU slowed 4× (entrance included) | draw mean 0.9 ms, p95 2.8 ms, one 30 ms outlier on the loaded box |
| DOM nodes | 930 (the phone: 868) |

**E1 re-measures on a quiet runner** and asserts: the draw-alone p95 ≤ 2 ms at CPU 4×; main thread ≤ 4 % while the drift runs and ≤ 2 % once it sleeps, over 10 s at 1440 × 900; ≤ 3 running infinite animations.

### 7.3 Pauses and reduced motion

**Paused** (no frame, no timer, sockets closed, polls stopped): `visibilitychange` hidden; `sv:pin-locked`, a 423, or the socket closed by the lock. The run state is one object; `start` refuses while locked.

**Under `prefers-reduced-motion`,** a still rendition: no entrance, no drift, no particles, no breathing, no gaze. An event lights its road for 1.5 s and gives the figure that changed a static highlight for 1.5 s (a background, no animation), so the information still arrives.

---

## 8. Truth and money safety (the display-only contract)

- **No money control on the page.** No CLOSE, TAKE TRADE, ADD, PASS, switch, brake or kill-switch form; no `data-sv-close-trade`, `svTakeTrade(` or `svCloseTrade(`; no `hx-post`. The only forms are idle-lock.js's lock request and the logout form. A test renders the page as a superuser with every block populated and greps the HTML.
- **Every action is a link to the page that holds it, behind its own PIN:** positions and CLOSE → `positions_list`; the kill switch → `admin_dashboard#flattenForm` (superuser); switches → `ops_dashboard`; keys → `brokers_page`; signals → their page or the rail. A test reverses every URL on the page.
- **No broker or model call.** A source scan proves `dashboard/hall.py` and `views_hall.py` import no broker adapter, no `client_for_symbol` and no model gateway; the page and the payload render with `EtoroTrader`, `client_for_symbol`, `http.client.HTTPConnection.connect`, urllib3's pool `urlopen` and the model gateway patched to raise. The readers named here ran that way on the fixture (`budget.py`); the two functions in `capital_truth.py` that do build broker clients (`broker_equity`, `pool_oversubscription`) are not on this page's path.
- **The worlds are never summed.** The payload has no `total` key (a test); the P&L table has no total row (a test); DEMO is never in REAL; Positions prints "3 real · 2 demo · 2 paper". The Portfolio figure is REAL-only (eToro's margin used over equity), not the band's `panel_exposure`, which divides both books' notional by the book's value (118 % on the fixture).
- **One world at a time.** The equity, the drawdown and eToro's cells belong to the world `broker_env(acct)` names; the other world's card shows its stored reading or the dash. A test with `acct.demo=True`.
- **Stale says its age; missing is a named dash.** An eToro cell past `BROKER_STALE_S` greys, with its age. A Morgul summary older than 900 s greys every guard line. A figure whose reader failed shows "—" with its reason in the title, and the failure is logged at WARNING once per process.
- **Solid red stays REAL's.** The REAL chip, the armed pill and the REAL particle's core are the world-marker family (UI plan §3.5). The S1a test that forbids other solid reds gains the hall's canvas constant as a declared world marker. A drawdown or a loss is coral text with its sign, never a red fill.
- **Nothing counts up, and colour never works alone.** Gains carry + and ▲, warnings carry a glyph and words, world chips carry their word.
- **Figures that the rules cannot produce are gone from the mock:** the governor reads 1.00 under the 5 % knee; News counts "today"; the calendar's next event is ahead of the clock; DEMO's 3 trades are "not judged"; PAPER's open P&L names the simulator's mark.

---

## 9. The phone (390)

`shots/mock_390.png` shows the full page (3,375 px; the bar is drawn at the end there so it can be seen).

- **Order:** the top line (three rows: the brand and title; the kill switch and the feed; the armed pill, the bell, the lock and the user menu), NEED YOU across the width, the Eye (128 × 81, breathing), **the REAL line** (equity, then OPEN NOW, 24 H and FROM HIGH as three cells, with eToro's age), then the pages, then the side panels in their desktop order.
- **The pages:** a two-column grid of 44 px tiles grouped by stage. Each group's head is its station's button (44 px): glyph or dot, title, state words, and "8 more ›", which opens the stage's other pages in place as 44 px links. All 20 pages are shown.
- **No ring, roads or particles:** the canvas is not drawn. An event washes the tile that changed and makes the Eye glow.
- **"Enter the Operations Center"** is a full-width 44 px bar fixed at the bottom.
- **Measured:** no text under 11 px; no sideways scroll (scrollWidth 390); every tile, stage head and list link ≥ 44 px; the REAL line starts at y 244 (the money used to start at about 1,070 px).

---

## 10. The stages

### E0. Design and preview (now; no repository change)

- **Goal.** He sees the page and answers the six questions.
- **Delivered:** this spec; the French note; the animated mock, its frame, its phone shot and its video; `Eye.dc.html` for the preview canvas as board 5, with its entry in `canvas_entry.json`:
  `"Eye.dc.html": {"x": 0, "y": 2240, "w": 1440, "h": 900, "title": "5 · Barad-dûr, après l'animation de chargement"}`, appended to `order`.
- **Send with the note:** the 8.4 s video, because the hand-off he asked about is only there.
- **Acceptance:** done when he answers.

### E1. The page, real data, static roads, both panels, the lock; the intro's targets (after S1a merges)

**Goal.** The page exists, on real data, as the kept intro's hand-off target.

**He will see:** the hand-off from the intro; the Eye awake; the ring with live station states; the twenty pages with real figures; the roads drawn and named; both side panels; NEED YOU; All pages and the user menu; the sidebar row; the drift while the socket is open; white particles on the push events (the world's colours come with E2).

**Files:**

| File | Change |
|---|---|
| `dashboard/hall.py` | New: `hall_payload(user, now=None)` and its small readers, each fenced and named in `dash` on failure; the caches of §6.2 |
| `dashboard/views_hall.py` | New: `barad_dur` (login_required; explicit-context render with the payload inlined, the idle lock's context and `csrf_token`) and `barad_dur_data` (JSON at `/api/barad-dur/`, with `?probe=1`) |
| `dashboard/urls.py` | Two paths: `barad-dur/` and `api/barad-dur/` |
| `templates/dashboard/barad_dur.html` | New, standalone: the `<head>` lines of the hand-off, the intro's font link under `?from=intro`, S1a's `sv-tokens.css`, `sv-hall.css` and `sv-hall.js`, the idle-lock partial |
| `templates/_partials/idle_lock.html` | New: extracted byte for byte from base.html 8450-8505 |
| `templates/base.html` | The include in place of the block; one nav row (♖ Barad-dûr) first in AMON HEN |
| `static/css/sv-hall.css` | New: the page, from the mock's CSS on S1a's tokens |
| `static/js/sv-hall.js` | New: layout and tiers, roads, entrance, drift, hover, keys, All pages, the run state, the lock path, the sockets (white particles) |
| `templates/dashboard/intro.html` | Lines 198 and 324: the targets only |
| `dashboard/views.py` | Line 6496 (target) and the docstring's words |

**Tests, written first** (`tests/test_barad_dur.py`, plus measured tests on the `_chrome()` pattern):
1. **The intro is kept.** intro.html with lines 198 and 324 masked hashes to today's file; the two lines carry the hall's URL (Skip without parameters, the end of the sequence with `from`, `t`, `px`, `py`, in ES5); `LOGIN_REDIRECT_URL == "intro"`.
2. **Landing.** First GET /intro/ → 200 and sets the flag; second GET → 302 to /barad-dur/; after logout and login → 200 again; `test_telegram_links`' login paths unchanged.
3. **Access and the lock's plumbing.** Anonymous → the Wall; investor → /investor/ (page and API); locked GET /barad-dur/ → /locked/?next=/barad-dur/; locked GET /api/barad-dur/ with no headers → 423; unlocked GET /api/barad-dur/ with no headers leaves `sv_last_seen` unchanged; the probe answers 204 and stamps nothing; the page's context carries `idle_lock`, `pin_locked` and a non-empty CSRF token; the lock button has `id="lockNowBtn"` and `data-has-pin`.
4. **Display only.** No form but the idle lock's and the logout; none of the money hooks; every link reverses; the source scan and the patched-network render (§8).
5. **Worlds and truth.** The payload has no total; REAL excludes DEMO (fixture with one DEMO row, the C1–C3 case); with `acct.demo=True`, `equity.live.last` and `drawdown.live` are null and the REAL card prints the dash; a fixture account in EUR prints EUR on the equity and USD on the P&L; "eToro's own" appears only for the account's world; the Portfolio figure is REAL-only; each money figure has `source` and `age_s`; missing ones have `dash`; the viewer variant withholds the staff keys in words; DEMO with n < 10 has no `won` and no colour.
6. **Cost.** `assertNumQueries`: payload warm ≤ 50; after a fill ≤ 160; GET ≤ 55; no context processor on the GET; a re-fetch after a `signal` push returns the new count (the micro-cache is bypassed).
7. **Nav.** The row exists for all logins; `test_nothing_unseen` lists the route; staff-only pages stay out of a viewer's station lists, user menu and All pages; All pages lists every sidebar row.
8. **Measured layout (Chrome)** at 390, 1280 × 720, 1280 × 800, 1366 × 768, 1440 × 900, 1536 × 864, 1920 × 1080 and 2560 × 1440: no text under 11 px; no sideways scroll; no two ring labels overlap; every ring label inside the centre column; no station pill within 6 px of the lid; every road inside its pages at ≥ 1366 px (and the 1280 cure of §4.4 measured); the side columns fit at ≥ 880 px of height; 0 console errors.
9. **Measured motion.** No frame while hidden, locked, or locked then hidden then shown; reduced motion: 0 frames, 0 running animations, the static highlight on a changed figure; the draw-alone p95 ≤ 2 ms at CPU 4×; main thread ≤ 4 % drifting, ≤ 2 % asleep; ≤ 3 infinite animations; at most 12 particles in flight under a burst of 50 events; one Eye glow per 2 s.
10. **Measured lock.** After Lock now, after the idle timeout, and after a lock from another tab, no figure is visible within 1 s (10 s for the other tab when its socket is closed), and the page lands on /locked/?next=/barad-dur/; the PIN brings it back.
11. **Measured hand-off.** On the real intro and the real clock, sequences ending at 4.9, 6.45 and 8.0 s, with the pointer moved, and once with the intro's first paint delayed by 500 ms (a held font): the Eye's drawn box in the hall's first frame matches the intro's last frame within 1 px; the globe and the glow sit at the intro's offsets within 1 px; the first frame draws the intro's words in Share Tech Mono; only the intro's particles and its 10 px percentage are missing from it.

**Acceptance:** the tests green; screenshot pairs (the intro's last frame against the hall's first frame at 1440) and the hall at every size of test 8; the query and frame numbers in the PR body.

**Conflicts:** S1a owns the tokens (E1 starts after it). base.html: two places (the include and the nav row); no branch in flight touches 8450-8505 or AMON HEN's rows; rebase if S1b lands first. The intro: no branch touches it (the S1a branch does not).

**Size:** M.

### E2. The world on every particle (after E1)

- **Goal.** Particles in the colour of their world; each entry on its own road; the Orc's birth; "since you last looked" replayed.
- **Files:**
  - the 11 push sites gain `"world"`, the `fill_open` sites gain `"via"`, and `orcs/birth.py` sends `orc_born` (§4.6);
  - `sv-hall.js` gains the colours, the `via` roads and the birth road;
  - `dashboard/hall.py` gains the events since his last visit (the Operations Center's R8 stamp, P2, which he approved on 2026-11-07), replayed in at most 6 s with a caption ("since 11:48 · 2 fills · 3 closes · replayed"); nothing is replayed without a stamp.
- **Tests:** each trade push carries one of `live`, `demo`, `paper`, `""`; each `fill_open` carries `via`; `orc_born` only when an Orc is created (Orcs off, options, a working entry and the cap send nothing); the notification-type table covers every type or falls back; a Node test of the event table; measured: at most 12 particles in flight under a burst of 50 events, draw p95 ≤ 2 ms at CPU 4×.
- **Acceptance:** the mock's story reproduced on the fixture by firing the same events through the channel layer, recorded.
- **Size:** S–M.

### E3. Feed-grade live (after the eToro feed's F4 and F7)

- **Goal.** The figures move with eToro's own feed, about every 10 s.
- **He will see:** eToro's own P&L per position on the account's world ("eToro's own · 8 s" replaces "≈ estimate"), the held instruments' prices refreshing with their grade badges, the Instruments figure's age live, quote particles from the venue push instead of the 60 s pollers.
- **Files:** `sv-hall.js` listens to F7's venue push (`sv-venue.js`'s events); the payload carries F6's `feed_status`; no new poll.
- **Tests:** F7's own, plus a measured check that the hall adds no request per tick.
- **Size:** S.

---

## 11. Decisions, risks, and where it meets the other pages

**Decisions taken here, and why:**

| Decision | Why |
|---|---|
| Standalone page, not base.html | "Only the Eye at the centre"; the shell costs ≈ 80 queries and 856 KiB per render; S1a hides the ambient layers on work pages. Costs taken: its own sockets, the idle-lock partial, /locked/ for the gate |
| The intro passes its state on its one changed line | The only way the first frame can be its last frame on a real login (the float alone varies by 14 px). It passes the float's own clock, because the page clock runs ahead of it by the time to the intro's first paint (up to 6.3 px measured); ES5, cannot throw |
| Stages, not sidebar groups, around the Eye | The day's cycle gives every road a direction; the operator reads it on /command/ and the Wall |
| The top of the ring left open | The night is the only flow that skips a stage (LEARN → THINK); an open arc says so without a word |
| Twenty pages, not sixty-two | 62 names around one Eye is a list, not a picture; the rest are one click away, and All pages lists them all |
| Roads on concentric lanes, kept inside the pages | Readable at 1 px, labels on the road, no spaghetti |
| Particles only on real events; a drift that sleeps | "Nothing moves unless a value moved" (UI plan rule 1), adapted to a brand page: the drift is the heartbeat, and it rests when nobody looks |
| World colour on particles; REAL = solid red | The platform's one meaning for solid red; whose money moved matters most |
| One eToro world at a time, said in words | The account row holds one world; the page never shows a demo balance under the REAL chip |
| The Eye enters the Operations Center; `/` stays /command/ | The intro used to land there; his habits and bookmarks keep working (decision 3 asks him) |

**Risks:**
- **The hall becomes the place he lingers, and its numbers must be as true as the Operations Center's.** Every figure reuses the reader that page, the band or the Horde already uses, so they cannot disagree.
- **The idle-lock extraction touches base.html.** It is byte for byte, and a test diffs the rendered overlay before and after.
- **1280 px screens.** The compact tier is cramped there (§4.4); E1 measures the two cures.
- **The board uses SMIL.** If the canvas ever sanitizes SVG animation elements, the board still renders, but still.

**Where it meets the Operations Center and the Oculus.**
- Barad-dûr is the entrance; /command/ is the work home; the Oculus is "is every cycle turning".
- It reuses four Operations Center blocks in short form, with their readers and words: R1's POSITIONS · NEED YOU (top line), R2's worlds (the P&L table's open row and the realized read), R6's signals to act on (the first three, in its order), R7's bots and Orcs (the machine). It shows none of R3's rows, CLOSE, R5's market or R9's review: those stay there.
- The stage vocabulary is the one `sv-stage.css` will carry (created by OC1, loaded by the Oculus's O2a); E1 loads it too, so the three pages never draw the stages two ways.
- **Synthetic data across the boards:** the hall's book is the Operations Center mock's (REAL 3 open, DEMO 2, PAPER 2, one hand row; $10,453.61 at eToro; NEED YOU ⨯ 2 alarms · 6 watch; US CPI 13:30 at 12:53 UTC). The Oculus mock still prints €, PAPER 1 open and a 14:53 clock; aligning it belongs to the Oculus's own corrections (the Operations Center spec §9 lists them).

**Not in this plan:** no change to the intro's look, timing, Skip or flag; no new trading feature and no money control; no change to what the engine, bots, Orcs, gates or desk read; no animation of money values; no 3D, WebGL or video background; no sound.

---

## 12. Appendix: what was measured on the mock

The scripts are in `scratchpad/eyehall/mock_tools/`:
- `render2.js`: the sizes, the frame, the phone, the video, the checks (`render2_report.json`);
- `perf2.js`: the run state's cost and pauses (`perf2.json`);
- `handoff.js`: the hand-off against the real intro (`handoff.json`);
- `budget.py`: the payload's reads on the fixture (`budget.json`);
- `build_board2.js`, `board_shot.js`: the board, rendered with JavaScript off;
- `dbg4.js`: road clearances at the tight sizes.

Everything ran offline. Google Fonts were answered from local copies of Inter, JetBrains Mono, Orbitron and Share Tech Mono inside the harness, and every other page request was aborted (`blocked: []`).

| Check | 390 | 1280 × 720 | 1280 × 800 | 1366 × 768 | 1440 × 900 | 1536 × 864 | 1920 × 1080 | 2560 × 1440 |
|---|---|---|---|---|---|---|---|---|
| Tier | phone | compact-min | compact-min | full-tight | full-close | full-close | full | full |
| Pages · roads · lanes | 20 tiles | 14 · 14 · 4 | 14 · 14 · 4 | 20 · 20 · 5 | 20 · 20 · 5 | 20 · 20 · 5 | 20 · 20 · 5 | 20 · 20 · 5 |
| Text under 11 px | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Ring labels overlapping, outside the column | — | 0, 0 | 0, 0 | 0, 0 | 0, 0 | 0, 0 | 0, 0 | 0, 0 |
| Closest pill to the lid | — | 8.8 px | 8.4 px | 11.0 px | 9.1 px | 8.6 px | 23.7 px | 32.5 px |
| Roads inside their pages | — | cramped (§4.4) | cramped | ✓ (10.5 px) | ✓ (8.5 px) | ✓ | ✓ | ✓ |
| Road names on hover only | — | 2 | 1 | 2 | 2 | 2 | 0 | 0 |
| Side columns | stacked | scroll inside | scroll inside | scroll inside | fit (816 / 816) | right scrolls inside | fit | fit |
| Sideways scroll | none | none | none | none | none | none | none | none |
| Console errors | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

- **The hand-off** (`handoff.json`; load average 8–10 on 4 cores): the intro's sequence ending at 4.9, 6.45 and 8.0 s, and 6.45 s with its font stylesheet held 500 ms, the pointer moved up and right (px 0.49–0.50, py −0.40):
  - with the float's clock (the proposed line): the hall's first frame matches the intro's drawn Eye within 0.05 px in all four cases; after the script takes over, 0.36 px (the takeover itself moves it 0.41 px);
  - with the page clock: 1.31–6.26 px, because the page clock ran 205–851 ms ahead of the float (and 9.1 s in one starved run);
  - the globe's and the glow's centres: about (+30, −24) and (+55, −44) px in both pages, within 0.1 px;
  - the intro's four lines of words are drawn in Share Tech Mono in the hall's first frame.
- **The video.** `shots/mock_1440.webm`, 1440 × 900, VP9, 8.4 s. It starts at the intro's first complete last frame (title, words, bar, greeting, Skip), then plays the hand-off; a quote; a new signal while Signals is hovered (the Eye looks at it); a REAL bot fill through entries, orders and the book with the Eye's glow, its Orc born; the fill told; a PAPER close graded; Positions hovered with its roads lit.
- **The board.** `Eye.dc.html`, rendered with JavaScript disabled: 282 text nodes, none under 11 px; 101 SMIL animation elements; a 1440 × 900 root; no custom properties, no `@media` but reduced motion, nothing fixed, no `100vh`; the format of `Signal.dc.html` (support.js, `<x-dc>`, `<helmet>`, the `data-dc-script` DCLogic block). Its Eye breathes (sampled: scale 1.00 → 1.18 → 1.00, opacity .70 → 1.00 over 4 s) with the glow on its own wrapper; particles move along the same road paths on a 12 s loop.
