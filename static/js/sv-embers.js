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
       numbers, never among them).

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
    function running() { return shown() && embers.length > 0 && !held() && !reduced.matches; }

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
        stats.maps++; stats.mapMs = j.ms; stats.mapSlices = j.slices; stats.voidArea = Math.round(voidArea);
        stats.rows = rows.slice(); stats.ROW = ROW;
        readWords();
        fit();
        first = false;
        drawn = false;
        wake();
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
        var na = Math.min(NAMAX, Math.round(voidArea / ASH_DENSITY));
        while (embers.length > n) embers.pop();
        while (embers.length < n) { var e = {}; seed(e, true); embers.push(e); }
        while (ashes.length > na) ashes.pop();
        while (ashes.length < na) { var a = {}; seedAsh(a, true); ashes.push(a); }
        for (var i = 0; i < embers.length; i++) {      /* a covered row: move, faded in */
            if (rowAt(embers[i].y) < 0.05) seed(embers[i], true);
        }
        stats.embers = embers.length; stats.ash = ashes.length;
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
            if (!drawn && embers.length) { for (var k = 0; k < embers.length; k++) embers[k].f = 1; draw(); }
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
