/* Sauron's embers, calm (the magic kept, 2026-11-12).

   main's ember field (base.html "Embers & Ash"), kept on work pages in a
   calm form:
     - where they can be seen: embers are born in the page's visible void
       (the rows of the screen no card covers), one per 6,000 px² of it, at
       most 56, and 12 flakes of ash at most (main: 240 and 50, everywhere,
       most of them behind its 8-12 % transparent cards);
     - about two thirds of the light of main's embers once its fake labels
       and trails are gone: alpha .18 to .55, one soft sprite each, no
       trails;
     - slower: 7 to 23 px a second, left to right (main: 15 to 75);
     - behind opaque cards (the canvas sits under the layout), and only on a
       page that declares it holds no figure on the void (<body
       data-sv-embers>; sauron.css hides the canvas everywhere else);
     - at most 30 frames a second, on a backing store a quarter of the
       screen's pixels (half per side: an ember is a soft light);
     - one drawImage per ember from three glow sprites drawn once;
     - never a label, a symbol or a number: this file draws no text;
     - an ember dims to alpha .18 as it passes within 18 px of words on the
       void (.sv-on-void, .sv-page-head), so their dark halo keeps them at
       4.5:1 or better;
     - an ember fades out as it nears what covers the void (the cards,
       panels and bars the map found): gone within 12 px of an edge, whole
       again at 24 px, so none is ever cut flat by a card or seen in a
       gutter under 24 px between figures (the magic lives around the
       numbers, never among them);
     - and in the gutters themselves, as the desk v2 board draws them
       (approved 2026-11-13, "amazing work, bravo, I need it fast!!";
       Twist2 "Les braises"): a gutter of 6 to 40 px between two panels,
       found where the map's panels face each other and walked point by
       point (void, and no word within 24 px), is a channel; a few embers
       of at most 11 px drift along it, at most one per 280 px of it
       (about one per 7 cm), each drawn CLIPPED to its channel, so none can
       ever cross a panel or sit on one. A channel is let go the moment the
       page scrolls or changes shape, and found again with the map;
     - and never on a figure a page prints straight on the void (a text
       with a digit and nothing painted under it up to <body>, as
       /positions/' eToro split line is until its page grounds it): the map
       counts it as covering the void, as a card does, so no ember or ash is
       drawn within 12 px of it, and no channel runs within 24 px of it
       (the review of the desk v2 build, 2026-11-13; Twist2: "aucune lueur
       ni reflet derrière un montant").

   It runs under Ambience Magic, in the dark theme, on a page that opted
   in, and nowhere else: there it maps nothing and asks for no frame. Where
   it runs, it asks for no frame while the tab is hidden, while the PIN
   lock is up (sv:pin-locked / sv:pin-unlocked), while a dialog holds the
   page (body.sv-scroll-locked) or the "?" shortcut sheet is open
   (#kbdModalOverlay.open, base.html's own modal outside SV.overlay), or
   when the page shows no void; under reduced motion it draws one still
   frame and stops.

   The void map: on load, on resize, after a scroll and after a live swap
   that moved the page's shape (sv:live-swapped), the screen is sampled on a
   24 px x 24-column grid with elementFromPoint, in idle slices of about
   4 ms (a hit test that must first refresh can take longer); a point is
   void when nothing from the hit element up to <body> paints a background,
   and the points a row above and below it are void too (the 10-16 px
   gutters between stacked cards are not the void). A panel scrolling
   inside itself (the nav, the rail) moves no void and costs no map. No map
   runs while the page is held: through a dialog's scrim or the lock's veil
   it would find no void; one that falls due waits for the hold to end.
   Rows are weighted by their void share and embers are born in them.
   Embers whose row became covered move, faded in, to a void row. The first
   map waits for the page's own entrance (its cards rise 18 px and fade in
   over 0.6 s): the field then fades in behind cards that have landed.

   Display only: it reads the page's boxes and one attribute of <body>, and
   draws light. tests/test_design_tokens.py runs it with a stubbed page. */
(function (w, d) {
    'use strict';
    var canvas = d.getElementById('particles-canvas');
    if (!canvas || !canvas.getContext) return;
    var ctx = canvas.getContext('2d');
    var CFG = w.SV_EMBERS || {};
    var NMAX = CFG.embers || 56, NAMAX = CFG.ash || 12, FPS = CFG.fps || 30, S = CFG.scale || 0.5;
    var A0 = CFG.a0 || 0.18, A1 = CFG.a1 || 0.55, DENSITY = CFG.density || 6000, ASH_DENSITY = 30000;
    var ROW = 24, COLS = 24, RING = 240, START_MS = 900;
    var reduced = w.matchMedia ? w.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
    var body = d.body, root = d.documentElement, locked = false, raf = 0, last = 0, W = 0, H = 0;
    var embers = [], ashes = [], rows = [], cum = [], voidArea = 0, mapTimer = 0, drawn = false, started = false;
    var WORDS = '.sv-on-void, .sv-page-head', NEAR = 18, CAP = 0.18, words = [], wordsDirty = true;
    /* What covers the void as the last map found it: an ember fades out
       as it nears one, gone within HUG px of its edge, whole at FAR px. */
    var HUG = 12, FAR = 24, ground = [], grounds = [];
    /* The figures printed straight on the void, as the last map found them
       (their text nodes), and their boxes now: they cover the void too. */
    var FIG_CAP = 200, FIG_SCAN = 20000, figs = [], figBoxes = [];
    /* The gutters' channels and their embers (the desk v2 board). */
    var CH_MIN = 6, CH_MAX = 40, CH_LEN = 96, CH_GAP = 280, CH_STEP = 20, CH_CAP = 20, CH_SAMPLES = 1600;
    var chans = [], cembers = [], chanOff = false;
    /* base.html's "?" sheet: a modal that is not SV.overlay's (no scroll lock) */
    var kbd = d.getElementById('kbdModalOverlay'), stale = false;
    /* What the tests read: frames drawn, the last RING draw times (a ring,
       so a late read still sees the latest), the void and the counts. */
    var stats = w.__svEmberStats = {
        frames: 0, ring: new Float32Array(RING), n: 0, maps: 0, mapMs: 0, sliceMax: 0,
        voidArea: 0, embers: 0, ash: 0, words: 0, grounds: 0,
        recent: function () {
            var k = Math.min(this.n, RING), out = [];
            for (var i = 0; i < k; i++) out.push(this.ring[(this.n - k + i) % RING]);
            return out;
        },
        /* the alpha an ember of alpha `a` is drawn at when it is at (x, y) */
        alphaAt: function (x, y, a) { if (wordsDirty) readWords(); return capNear(x, y, a); },
        /* the same near what covers the void (a card, a panel, a bar) */
        groundAt: function (x, y, a) { if (wordsDirty) readWords(); return fade(x, y, a); },
        /* where each ember is, and its own alpha */
        field: function () { return embers.map(function (e) { return [e.x, e.y, e.a]; }); },
        /* the gutters' channels [left, top, right, bottom, horizontal] and
           where each of their embers is drawn [left, top, right, bottom,
           channel] after its clip, as the last frame drew it */
        channels: function () { return chanOff ? [] : chans.map(function (c) { return [c.l, c.t, c.r, c.b, c.h]; }); },
        chanField: function () { return cembers.map(function (e) { return e.box ? e.box.concat([e.c]) : null; }).filter(Boolean); },
        /* the brightest ember the field would draw at (x, y): its largest
           sprite, at the alpha its own cap gives there */
        stamp: function (x, y) {
            if (wordsDirty) readWords();
            var a = capNear(x, y, A1), dd = 2.4 * 9;
            ctx.setTransform(S, 0, 0, S, 0, 0);
            ctx.globalAlpha = a;
            ctx.drawImage(SPR[2], x - dd / 2, y - dd / 2, dd, dd);
            ctx.globalAlpha = 1;
            return a;
        }
    };

    /* Words on the void: their boxes, read after a map, a scroll or a swap. */
    function readWords() {
        words = []; wordsDirty = false;
        var ns = d.querySelectorAll(WORDS);
        for (var i = 0; i < ns.length; i++) {
            var r = ns[i].getBoundingClientRect();
            if (r.width && r.height && r.bottom > -NEAR && r.top < H + NEAR) words.push([r.left, r.top, r.right, r.bottom]);
        }
        stats.words = words.length;
        grounds = [];
        for (var k = 0; k < ground.length; k++) {
            var g = ground[k];
            if (g.el.isConnected !== false) {           /* a swap that kept the page's shape keeps its box */
                var b = g.el.getBoundingClientRect();
                g.box = b.width && b.height ? [b.left, b.top, b.right, b.bottom] : null;
            }
            var q = g.box;
            if (q && q[3] > -FAR && q[1] < H + FAR && q[2] > -FAR && q[0] < W + FAR) grounds.push(q);
        }
        /* A figure on the void covers it as a card does (never on a figure). */
        figBoxes = [];
        for (var f = 0; f < figs.length; f++) {
            var fg = figs[f];
            if (fg.n.isConnected !== false) {           /* a swap that kept the page's shape keeps its box */
                var rg = d.createRange(); rg.selectNodeContents(fg.n);
                var fr = rg.getBoundingClientRect();
                fg.box = fr.width && fr.height ? [fr.left, fr.top, fr.right, fr.bottom] : null;
            }
            var fq = fg.box;
            if (fq && fq[3] > -FAR && fq[1] < H + FAR && fq[2] > -FAR && fq[0] < W + FAR) { figBoxes.push(fq); grounds.push(fq); }
        }
        stats.figures = figBoxes.length;
        stats.grounds = grounds.length;
    }
    /* An ember near what covers the void fades out: 0 within HUG px of
       its edge, rising to its own alpha at FAR px. */
    function fade(x, y, a) {
        var dd = FAR * FAR;
        for (var i = 0; i < grounds.length; i++) {
            var q = grounds[i];
            var dx = x < q[0] ? q[0] - x : (x > q[2] ? x - q[2] : 0);
            if (dx >= FAR) continue;
            var dy = y < q[1] ? q[1] - y : (y > q[3] ? y - q[3] : 0);
            if (dy >= FAR) continue;
            if (dx * dx + dy * dy < dd) { dd = dx * dx + dy * dy; if (dd <= HUG * HUG) return 0; }
        }
        return dd >= FAR * FAR ? a : a * (Math.sqrt(dd) - HUG) / (FAR - HUG);
    }
    /* An ember within NEAR px of a word on the void is capped at CAP, rising
       back to its own alpha at NEAR. */
    function capNear(x, y, a) {
        for (var i = 0; i < words.length; i++) {
            var q = words[i];
            var dx = x < q[0] ? q[0] - x : (x > q[2] ? x - q[2] : 0);
            var dy = y < q[1] ? q[1] - y : (y > q[3] ? y - q[3] : 0);
            var dist = Math.sqrt(dx * dx + dy * dy);
            if (dist < NEAR) { var c = CAP + (a - CAP) * dist / NEAR; if (c < a) a = c; }
        }
        return a;
    }

    /* Wanted here at all: Ambience Magic, a page that opted in, the dark
       theme, and a canvas the sheet displays. */
    function ambience() { return body.getAttribute('data-sv-ambience') || 'magic'; }
    function shown() {
        return ambience() === 'magic' && body.hasAttribute('data-sv-embers')
            && !body.classList.contains('light-mode')
            && w.getComputedStyle(canvas).display !== 'none';
    }
    /* Held: the tab is hidden, the lock is up, or a dialog holds the page. */
    function held() {
        return !!d.hidden || locked || body.classList.contains('sv-scroll-locked')
            || !!(kbd && kbd.classList.contains('open'));
    }
    function running() { return shown() && (embers.length + cembers.length) > 0 && !held() && !reduced.matches; }

    /* Three glow sprites, drawn once: a pale core, the Eye's green, a halo
       as wide as main's mid glow (its 2.5x disc), so an ember reads as main's
       did at the same alpha. */
    function sprite(px) {
        var c = d.createElement('canvas'); c.width = c.height = px;
        var g = c.getContext('2d'), r = px / 2;
        var grd = g.createRadialGradient(r, r, 0, r, r, r);
        grd.addColorStop(0, 'rgba(214,255,230,1)');
        grd.addColorStop(0.14, 'rgba(0,232,104,.9)');
        grd.addColorStop(0.40, 'rgba(0,232,104,.34)');
        grd.addColorStop(0.70, 'rgba(0,232,104,.10)');
        grd.addColorStop(1, 'rgba(0,232,104,0)');
        g.fillStyle = grd; g.fillRect(0, 0, px, px);
        return c;
    }
    var SPR = [sprite(12), sprite(20), sprite(32)];
    var ASH = (function () {
        var c = d.createElement('canvas'); c.width = 8; c.height = 4;
        var g = c.getContext('2d');
        g.fillStyle = 'rgba(96,150,116,.9)'; g.fillRect(1, 1, 6, 2);
        return c;
    })();

    /* ── the void map ─────────────────────────────────────────────────── */
    function paints(n) {
        var cs = w.getComputedStyle(n);
        if (cs.backgroundImage && cs.backgroundImage !== 'none') return true;
        var m = /rgba?\(([^)]+)\)/.exec(cs.backgroundColor || '');
        if (!m) return false;
        var p = m[1].split(/[ ,\/]+/).filter(Boolean);
        return p.length < 4 || parseFloat(p[3]) > 0;
    }
    /* What covers a point: the nearest element up to <body> that paints. */
    function painter(n, memo) {
        if (!n || n === body || n === root) return null;
        if (memo.has(n)) return memo.get(n);
        var p = paints(n) ? n : painter(n.parentElement, memo);
        memo.set(n, p);
        return p;
    }
    /* The map is built in slices of at most ~4 ms (an idle callback each),
       so it never holds the main thread; embers keep the old map meanwhile. */
    var job = null, first = true;
    function mapVoid() {
        if (!shown()) { job = null; return; }
        if (held()) { job = null; stale = true; return; }   /* through a scrim the page shows no void */
        stale = false;
        if (first) shape = shapeNow();
        job = { r: 0, nr: Math.ceil(H / ROW), bits: [], cover: new Set(), ms: 0, slices: 0, memo: new Map() };
        schedule();
    }
    function schedule() {
        if (w.requestIdleCallback) w.requestIdleCallback(slice, { timeout: 300 });
        else w.setTimeout(slice, 16);
    }
    function slice() {
        var j = job;
        if (!j) return;
        if (!shown()) { job = null; return; }              /* the Ambience changed meanwhile */
        if (held()) { job = null; stale = true; return; }  /* a dialog opened meanwhile: map once it closes */
        var t0 = w.performance.now();
        while (j.r < j.nr) {
            var y = Math.min(H - 1, j.r * ROW + ROW / 2), bits = [];
            for (var c = 0; c < COLS; c++) {
                var el = d.elementFromPoint((c + 0.5) * W / COLS, y), p = el ? painter(el, j.memo) : null;
                if (p) j.cover.add(p);
                bits.push(!p);
            }
            j.bits.push(bits); j.r++;
            if (w.performance.now() - t0 > 4) break;
        }
        var dt = w.performance.now() - t0;
        j.ms += dt; j.slices++;
        if (dt > stats.sliceMax) stats.sliceMax = dt;
        if (j.r < j.nr) { schedule(); return; }
        job = null;
        /* a point counts where the void also runs a row above and below
           it: a gutter between stacked cards is no place to be born */
        rows = []; voidArea = 0; cum = [];
        for (var r = 0, acc = 0; r < j.bits.length; r++) {
            var up = j.bits[r - 1], dn = j.bits[r + 1], hit = 0;
            for (var k = 0; k < COLS; k++) if (j.bits[r][k] && (!up || up[k]) && (!dn || dn[k])) hit++;
            rows.push(hit / COLS); voidArea += hit / COLS * W * ROW; acc += hit / COLS; cum.push(acc);
        }
        ground = [];
        j.cover.forEach(function (el) { ground.push({ el: el, box: null }); });
        figs = voidFigures(j.memo);
        stats.maps++; stats.mapMs = j.ms; stats.mapSlices = j.slices; stats.voidArea = Math.round(voidArea);
        stats.rows = rows.slice(); stats.ROW = ROW;
        readWords();
        findChannels(j.memo);
        fit();
        first = false;
        drawn = false;
        wake();
    }
    /* ── the gutters' channels ─────────────────────────────────────────── */
    /* A point of a gutter is void when nothing up to <body> paints there
       and no word of the void sits within FAR px of it. */
    function quiet(x, y, memo) {
        var el = d.elementFromPoint(x, y);
        if (!el || painter(el, memo)) return false;
        for (var n = el.firstChild; n; n = n.nextSibling) {
            if (n.nodeType !== 3 || !n.nodeValue.trim()) continue;
            var rg = d.createRange(); rg.selectNodeContents(n);
            var rs = rg.getClientRects();
            for (var k = 0; k < rs.length; k++) {
                var q = rs[k];
                if (x > q.left - FAR && x < q.right + FAR && y > q.top - FAR && y < q.bottom + FAR) return false;
            }
        }
        return true;
    }
    /* The figures a page prints straight on the void, in the window: a text
       with a digit whose element, up to <body>, paints nothing (the magic
       layer's own measure of a figure on the void). Read once per map. */
    function voidFigures(memo) {
        var out = [];
        if (!d.createTreeWalker || !d.createRange) return out;
        var top = (d.querySelector && d.querySelector('.page-content')) || body;
        var tw = d.createTreeWalker(top, 4 /* NodeFilter.SHOW_TEXT */, null), n, seen = 0;
        while ((n = tw.nextNode()) && out.length < FIG_CAP && ++seen < FIG_SCAN) {
            if (!/\d/.test(n.nodeValue)) continue;
            var el = n.parentElement;
            if (!el || el.closest('script, style, noscript, template, textarea') || !el.getClientRects().length) continue;
            var b = el.getBoundingClientRect();
            if (b.bottom < -FAR || b.top > H + FAR || b.right < -FAR || b.left > W + FAR) continue;
            if (painter(el, memo)) continue;            /* on a card: the card covers it already */
            out.push({ n: n, box: null });
        }
        return out;
    }
    /* A gutter's cross-section within FAR px of a figure on the void. */
    function byFigure(x0, y0, x1, y1) {
        for (var i = 0; i < figBoxes.length; i++) {
            var q = figBoxes[i];
            if (x1 > q[0] - FAR && x0 < q[2] + FAR && y1 > q[1] - FAR && y0 < q[3] + FAR) return true;
        }
        return false;
    }
    /* Where two of the map's panels face each other across 6 to 40 px, the
       gap between them is walked every CH_STEP px; each run of void long
       enough, never by a figure on the void, is a channel. */
    function findChannels(memo) {
        chans = []; chanOff = false;
        var boxes = [];
        for (var i = 0; i < ground.length; i++) {
            var b = ground[i].el.getBoundingClientRect();
            if (b.width < 40 || b.height < 12 || b.bottom <= 0 || b.top >= H || b.right <= 0 || b.left >= W) continue;
            boxes.push([b.left, b.top, b.right, b.bottom]);
        }
        var cand = [];
        for (var a = 0; a < boxes.length; a++) {
            var A = boxes[a], hz = null, vt = null;
            for (var c = 0; c < boxes.length; c++) {
                if (c === a) continue;
                var C = boxes[c];
                var ox = Math.min(A[2], C[2]) - Math.max(A[0], C[0]), gy = C[1] - A[3];
                if (ox >= CH_LEN && gy >= CH_MIN && gy <= CH_MAX && (!hz || gy < hz.g)) {
                    hz = { g: gy, r: [Math.max(A[0], C[0]), A[3], Math.min(A[2], C[2]), C[1]] };
                }
                var oy = Math.min(A[3], C[3]) - Math.max(A[1], C[1]), gx = C[0] - A[2];
                if (oy >= CH_LEN && gx >= CH_MIN && gx <= CH_MAX && (!vt || gx < vt.g)) {
                    vt = { g: gx, r: [A[2], Math.max(A[1], C[1]), C[0], Math.min(A[3], C[3])] };
                }
            }
            if (hz) cand.push({ h: true, r: hz.r });
            if (vt) cand.push({ h: false, r: vt.r });
        }
        /* the longest first, each gap once */
        cand.sort(function (p, q) { return (q.r[2] - q.r[0]) + (q.r[3] - q.r[1]) - (p.r[2] - p.r[0]) - (p.r[3] - p.r[1]); });
        var taken = [], samples = 0;
        for (var k = 0; k < cand.length && samples < CH_SAMPLES; k++) {
            var cd = cand[k], r = [Math.max(0, cd.r[0]), Math.max(0, cd.r[1]), Math.min(W, cd.r[2]), Math.min(H, cd.r[3])];
            if (r[2] - r[0] < 1 || r[3] - r[1] < 1) continue;
            var dup = false;
            for (var t = 0; t < taken.length && !dup; t++) {
                var o = taken[t];
                var ix = Math.min(o[2], r[2]) - Math.max(o[0], r[0]), iy = Math.min(o[3], r[3]) - Math.max(o[1], r[1]);
                if (ix > 0 && iy > 0 && ix * iy > 0.5 * (r[2] - r[0]) * (r[3] - r[1])) dup = true;
            }
            if (dup) continue;
            taken.push(r);
            var len = cd.h ? r[2] - r[0] : r[3] - r[1], mid = cd.h ? (r[1] + r[3]) / 2 : (r[0] + r[2]) / 2;
            var start = null, last = null;
            for (var u = CH_STEP / 2; u <= len; u += CH_STEP) {
                samples++;
                var px = cd.h ? r[0] + u : mid, py = cd.h ? mid : r[1] + u;
                var clear = !(cd.h ? byFigure(px, r[1], px, r[3]) : byFigure(r[0], py, r[2], py));
                if (clear && quiet(px, py, memo)) { if (start === null) start = u; last = u; }
                else { run(cd.h, r, start, last); start = null; }
            }
            run(cd.h, r, start, last);
        }
        stats.chanCount = chans.length;
    }
    function run(h, r, start, last) {
        if (start === null || last - start + CH_STEP < CH_LEN) return;
        var a = Math.max(0, start - CH_STEP / 2), b = last + CH_STEP / 2;
        chans.push(h ? { h: true, l: r[0] + a, t: r[1], r: Math.min(r[2], r[0] + b), b: r[3] }
                     : { h: false, l: r[0], t: r[1] + a, r: r[2], b: Math.min(r[3], r[1] + b) });
    }
    /* At most one ember per CH_GAP px of a channel, CH_CAP in all. */
    function chanFit(room) {
        var want = [];
        for (var i = 0; i < chans.length; i++) {
            var c = chans[i], len = c.h ? c.r - c.l : c.b - c.t;
            for (var k = 0; k < Math.min(4, Math.max(1, Math.floor(len / CH_GAP))); k++) want.push(i);
        }
        want = want.slice(0, Math.max(0, Math.min(CH_CAP, room)));
        cembers = want.map(function (ci) {
            var c = chans[ci], len = c.h ? c.r - c.l : c.b - c.t, th = c.h ? c.b - c.t : c.r - c.l;
            return { c: ci, t: Math.random() * len, v: 7 + Math.random() * 11, a: 0.3 + Math.random() * 0.22,
                     dd: Math.max(5, Math.min(11, th - 2)), off: (Math.random() - 0.5) * Math.max(0, Math.min(3, th - 12)),
                     ph: Math.random() * 6.283, pv: 0.5 + Math.random(), s: Math.random() < 0.5 ? 0 : 1, f: 0, box: null };
        });
    }
    function stepChan(dt) {
        for (var i = 0; i < cembers.length; i++) {
            var e = cembers[i], c = chans[e.c];
            if (!c) continue;
            var len = c.h ? c.r - c.l : c.b - c.t;
            e.t += e.v * dt; e.ph += e.pv * dt;
            if (e.f < 1) e.f = Math.min(1, e.f + dt);
            if (e.t > len + e.dd) e.t = -e.dd;
        }
    }
    /* One drawImage each, its source cut so the sprite ends at the
       channel's edges: an ember in a gutter is never drawn past it. */
    function drawChan() {
        for (var i = 0; i < cembers.length; i++) {
            var e = cembers[i], c = chans[e.c];
            e.box = null;
            if (!c || chanOff) continue;
            var x = c.h ? c.l + e.t : (c.l + c.r) / 2 + e.off, y = c.h ? (c.t + c.b) / 2 + e.off : c.b - e.t;
            var x0 = x - e.dd / 2, y0 = y - e.dd / 2;
            var cx0 = Math.max(x0, c.l), cy0 = Math.max(y0, c.t), cx1 = Math.min(x0 + e.dd, c.r), cy1 = Math.min(y0 + e.dd, c.b);
            if (cx1 - cx0 < 0.5 || cy1 - cy0 < 0.5) continue;
            var img = SPR[e.s], k = img.width / e.dd;
            ctx.globalAlpha = (words.length ? capNear(x, y, e.a) : e.a) * e.f * (0.65 + 0.35 * Math.sin(e.ph * 1.7));
            ctx.drawImage(img, (cx0 - x0) * k, (cy0 - y0) * k, (cx1 - cx0) * k, (cy1 - cy0) * k, cx0, cy0, cx1 - cx0, cy1 - cy0);
            e.box = [cx0, cy0, cx1, cy1];
        }
    }

    function rowAt(y) { var r = Math.floor(y / ROW); return r >= 0 && r < rows.length ? rows[r] : 0; }
    function voidY() {
        var total = cum.length ? cum[cum.length - 1] : 0;
        if (!total) return Math.random() * H;
        var t = Math.random() * total, lo = 0, hi = cum.length - 1;
        while (lo < hi) { var mid = (lo + hi) >> 1; if (cum[mid] < t) lo = mid + 1; else hi = mid; }
        return Math.min(H - 1, lo * ROW + Math.random() * ROW);
    }
    /* the counts follow the void: one ember per DENSITY px² of it */
    function fit() {
        var n = Math.min(NMAX, Math.round(voidArea / DENSITY));
        chanFit(NMAX - n);
        var na = Math.min(NAMAX, Math.round(voidArea / ASH_DENSITY));
        while (embers.length > n) embers.pop();
        while (embers.length < n) { var e = {}; seed(e, true); embers.push(e); }
        while (ashes.length > na) ashes.pop();
        while (ashes.length < na) { var a = {}; seedAsh(a, true); ashes.push(a); }
        for (var i = 0; i < embers.length; i++) {      /* a covered row: move, faded in */
            if (rowAt(embers[i].y) < 0.05) seed(embers[i], true);
        }
        stats.embers = embers.length + cembers.length; stats.ash = ashes.length;
        stats.chanEmbers = cembers.length;
    }
    /* A live swap usually repaints values, not the layout: the map is redone
       only when the page's shape moved (its height, the scroll, the window). */
    var shape = '';
    function shapeNow() { return [root.scrollHeight, w.scrollY, W, H].join(':'); }
    function remap(ev) {
        wordsDirty = true;
        if (!started || !shown()) return;
        if (held()) { stale = true; return; }           /* never map through a scrim, the veil or a hidden tab */
        /* a swap that kept the page's shape, or a panel (the nav, the
           rail) scrolling inside itself, moved no void */
        if (ev && (ev.type === 'sv:live-swapped' || (ev.type === 'scroll' && ev.target !== d))
            && shapeNow() === shape) return;
        chanOff = true;                                 /* the gutters moved: found again with the map */
        if (mapTimer) w.clearTimeout(mapTimer);
        mapTimer = w.setTimeout(function () { mapTimer = 0; shape = shapeNow(); mapVoid(); }, 220);
    }

    function seed(e, anywhere) {
        e.x = anywhere ? Math.random() * W : -20 - Math.random() * 160;
        e.y = voidY();
        e.r = 0.5 + Math.random() * 1.9;             /* core radius, CSS px */
        e.v = 6 + Math.random() * 12 + e.r * 2;       /* px per second */
        e.dy = (Math.random() - 0.5) * 0.6;           /* a slow rise or fall, ±0.3 px/s */
        e.ph = Math.random() * 6.283; e.pv = 0.5 + Math.random();
        e.amp = 3 + Math.random() * 6;
        e.a = A0 + Math.random() * (A1 - A0);
        e.s = e.r > 1.6 ? 2 : (e.r > 1 ? 1 : 0);
        e.f = anywhere ? 0 : 1;                       /* fade-in, 0..1 over 1 s */
    }
    function seedAsh(a, anywhere) {
        a.x = anywhere ? Math.random() * W : -20 - Math.random() * 200;
        a.y = voidY();
        a.w = 3 + Math.random() * 3; a.h = 1 + Math.random();
        a.v = 4 + Math.random() * 8; a.rot = Math.random() * 6.283; a.rv = (Math.random() - 0.5) * 0.5;
        a.a = 0.08 + Math.random() * 0.14;
    }
    function size() {
        W = w.innerWidth; H = w.innerHeight;
        canvas.width = Math.ceil(W * S); canvas.height = Math.ceil(H * S);
    }
    function step(dt) {
        stepChan(dt);
        for (var i = 0; i < embers.length; i++) {
            var e = embers[i];
            e.x += e.v * dt; e.y += e.dy * dt; e.ph += e.pv * dt;
            if (e.f < 1) e.f = Math.min(1, e.f + dt);
            if (e.x > W + 30) seed(e, false);
        }
        for (var j = 0; j < ashes.length; j++) {
            var a = ashes[j];
            a.x += a.v * dt; a.rot += a.rv * dt;
            if (a.x > W + 30) seedAsh(a, false);
        }
    }
    function draw() {
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        for (var j = 0; j < ashes.length; j++) {
            var a = ashes[j], c = Math.cos(a.rot) * S, s = Math.sin(a.rot) * S;
            var aa = grounds.length ? fade(a.x, a.y, a.a) : a.a;
            if (!aa) continue;                          /* against a card: nothing to draw */
            ctx.setTransform(c, s, -s, c, a.x * S, a.y * S);
            ctx.globalAlpha = aa;
            ctx.drawImage(ASH, -a.w / 2, -a.h / 2, a.w, a.h);
        }
        if (wordsDirty) readWords();
        ctx.setTransform(S, 0, 0, S, 0, 0);
        for (var i = 0; i < embers.length; i++) {
            var e = embers[i], dd = e.r * 9, y = e.y + Math.sin(e.ph) * e.amp;
            var ea = grounds.length ? fade(e.x, y, e.a) : e.a;
            if (!ea) continue;                          /* against a card: nothing to draw */
            ctx.globalAlpha = (words.length ? capNear(e.x, y, ea) : ea) * e.f * (0.6 + 0.4 * Math.sin(e.ph * 1.7));
            ctx.drawImage(SPR[e.s], e.x - dd / 2, y - dd / 2, dd, dd);
        }
        drawChan();
        ctx.globalAlpha = 1;
        drawn = true;
    }
    function tick(now) {
        raf = 0;
        if (!running()) return;                         /* paused: nothing scheduled */
        raf = w.requestAnimationFrame(tick);
        if (now - last < 1000 / FPS - 4) return;        /* the 30 fps cap */
        var dt = Math.min((now - last) / 1000, 0.1);
        last = now;
        var t0 = w.performance.now();
        step(dt); draw();
        stats.frames++;
        stats.ring[stats.n % RING] = w.performance.now() - t0; stats.n++;
    }
    function resume() {
        if (!raf && running()) { last = w.performance.now(); raf = w.requestAnimationFrame(tick); }
    }
    /* No frame stays asked for while the field is paused. */
    function halt() {
        if (raf) { if (w.cancelAnimationFrame) w.cancelAnimationFrame(raf); raf = 0; }
    }
    function clear() {
        ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, canvas.width, canvas.height);
        drawn = false;
    }
    /* Whatever changed (the Ambience, the opt-in, a dialog, the lock, the
       tab): run, hold still, or leave the canvas empty. */
    function wake() {
        if (!started) return;                           /* the page is still entering */
        if (!shown()) { halt(); if (drawn) clear(); return; }
        if (!stats.maps && !job) { size(); mapVoid(); return; }    /* shown for the first time: map, then come back */
        if (held()) { halt(); return; }
        if (stale) { stale = false; remap(); }          /* the hold is over: map the page as it is now */
        if (reduced.matches) {                          /* one still frame: the field is simply there */
            halt();
            if (!drawn && (embers.length || cembers.length)) {
                for (var k = 0; k < embers.length; k++) embers[k].f = 1;
                for (var q = 0; q < cembers.length; q++) cembers[q].f = 1;
                draw();
            }
            return;
        }
        resume();
    }

    size();
    w.setTimeout(function () { started = true; mapVoid(); }, START_MS);

    d.addEventListener('visibilitychange', wake);
    d.addEventListener('sv:pin-locked', function () { locked = true; halt(); });
    d.addEventListener('sv:pin-unlocked', function () { locked = false; wake(); });
    d.addEventListener('sv:live-swapped', remap);
    w.addEventListener('scroll', remap, { passive: true, capture: true });
    w.addEventListener('resize', function () {
        var was = drawn;
        size(); drawn = false;
        remap();
        if (was && shown() && reduced.matches) draw();
    });
    if (d.fonts && d.fonts.ready) d.fonts.ready.then(remap);
    /* a dialog opening or closing (its scroll lock), the Ambience changing,
       or the page's opt-in */
    if (w.MutationObserver) {
        new w.MutationObserver(wake).observe(body, { attributes: true, attributeFilter: ['class', 'data-sv-ambience', 'data-sv-embers'] });
        if (kbd) new w.MutationObserver(wake).observe(kbd, { attributes: true, attributeFilter: ['class'] });
    }
    if (reduced.addEventListener) reduced.addEventListener('change', wake);
})(window, document);
