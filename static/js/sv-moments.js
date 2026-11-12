/* Sauron's moments (the magic kept, 2026-11-12): light only when
   something real happened, once.

   THE EYE'S FLARE. The sidebar's mark flares for a fill, and at 60 % for
   a close. The trigger is the platform's own announcement, sv:eye-event
   (base.html re-dispatches every /ws/eye/ message), kind fill_open or
   fill_close. Never sv:position-changed: that one also fires when an
   order MAY have reached the broker, when its answer was lost, when the
   lookup stayed unanswered and when a close's answer was lost.

   A fill_close must be a booked close: it carries its own trade and no
   source. The kill switch's sweep (a held order it withdrew traded
   nothing; the portfolio rows it only marks closed have no trade) and
   nl_trader's close written in the database alone say their source, and
   flare nothing.

   A fill_open must be a fill. It is also pushed for an order the broker
   holds unfilled (a WORKING entry), so it flares only when one of these
   proves the fill:
     - its payload says "working": false;
     - or this tab's own answer for that trade says so: the confirmed
       answer ({ok: true, trade_id}) or the lookup's ({state: "booked",
       trade_id}), each without "working". The socket's event waits up to
       4 s for that answer; an answer that came first is remembered for a
       minute.
   Without either proof there is no flare. One flare per trade, ever, and
   at most one per 1.5 s.

   THE FILL'S ROW. A proven fill arms a watch on its trade id for 60 s. The
   next live swap (sv:live-swapped) that brings the row holding that
   trade's own CLOSE button lights that row and no other: one overlay on
   the row's bottom hairline, from the row's left edge to the action
   cell's left edge, so CLOSE never takes it.

   A NEW SIGNAL. When the rail's body is replaced, a card is new only if it
   was not on the rail before AND its data-created is later than the
   rail's high-water mark (the newest data-created seen at load and after
   each swap): only the server's clock is compared, never the browser's.
   So BRING BACK, a filter change and a re-order light nothing. At most
   three cards a swap, and the rail's signal icon once.

   THE GAZE. Under Ambience Magic the mark's iris looks toward the pointer,
   up to 2.4 units across and 1 down of its 24: one write per frame, and
   only while the pointer moves.

   Calm: the lights fade in place, the Eye glows once without its ring, no
   gaze. Off, reduced motion and light mode: none of it. The words and the
   approved washes still say what happened.

   Display only. It listens; it dispatches nothing, asks no server, and
   never touches a button or a figure. tests/test_magic_layer.py runs it
   with a stubbed page. */
(function (w, d) {
    'use strict';
    var body = d.body;
    if (!body) return;
    var reduced = w.matchMedia ? w.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
    var WAIT_MS = 4000, WATCH_MS = 60000, GAP_MS = 1500, MAX_CARDS = 3, MOMENT_MS = 1600;

    function ambience() { return body.getAttribute('data-sv-ambience') || 'magic'; }
    /* 'magic', 'calm', or null where nothing may light. */
    function mode() {
        if (reduced.matches || body.classList.contains('light-mode')) return null;
        var a = ambience();
        return a === 'magic' || a === 'calm' ? a : null;
    }
    function now() { return w.performance.now(); }
    /* A class that plays once: off when its own animation ends, or after a
       moment's length where no animation runs. One listener and one timer
       per element, however often it plays. */
    function once(el, classes, pattern) {
        function off() { for (var i = 0; i < classes.length; i++) el.classList.remove(classes[i]); }
        if (!el.svMomentHeard) {
            el.svMomentHeard = true;
            el.addEventListener('animationend', function (e) {
                if (!e || !e.animationName || pattern.test(e.animationName)) off();
            });
        }
        if (el.svMomentTimer) w.clearTimeout(el.svMomentTimer);
        el.svMomentTimer = w.setTimeout(function () { el.svMomentTimer = 0; off(); }, MOMENT_MS);
    }

    /* ── the Eye's flare ──────────────────────────────────────────────── */
    var wrap = d.querySelector('.brand-eye-wrap');
    var lastFlare = -1e9;
    function flare(soft) {
        if (!wrap || !mode()) return false;
        var t = now();
        if (t - lastFlare < GAP_MS) return false;
        lastFlare = t;
        wrap.classList.remove('sv-flare', 'sv-flare--soft');
        void wrap.offsetWidth;                          /* a second flare starts from its first frame */
        if (soft) wrap.classList.add('sv-flare', 'sv-flare--soft');
        else wrap.classList.add('sv-flare');
        once(wrap, ['sv-flare', 'sv-flare--soft'], /^sv-eye-(flare|glow)/);
        return true;
    }

    /* ── a fill, proven ───────────────────────────────────────────────── */
    var seen = {};          /* 'open:<id>' / 'close:<id>': played, ever */
    var answers = {};       /* this tab's own answers: id -> {filled, at} */
    var waiting = {};       /* socket events waiting for the answer: id -> timer */
    var watch = {};         /* proven fills waiting for their row: id -> deadline */

    function proven(id) {
        if (waiting[id]) { w.clearTimeout(waiting[id]); delete waiting[id]; }
        if (seen['open:' + id]) return;
        seen['open:' + id] = 1;
        flare(false);
        watch[id] = now() + WATCH_MS;
    }
    function forget() {
        var t = now();
        for (var id in answers) if (t - answers[id].at > WATCH_MS) delete answers[id];
    }
    d.addEventListener('sv:eye-event', function (e) {
        var msg = (e && e.detail) || {}, data = msg.data || {};
        if (msg.kind === 'fill_close') {
            if (data.trade_id == null || data.source) return;     /* no booked close behind it */
            var key = 'close:' + data.trade_id;
            if (seen[key]) return;
            seen[key] = 1;
            flare(true);
            return;
        }
        if (msg.kind !== 'fill_open' || data.trade_id == null) return;
        var id = String(data.trade_id);
        if (data.working === false) { proven(id); return; }
        if (data.working) return;                       /* the broker holds it: no fill yet */
        forget();
        if (answers[id]) { if (answers[id].filled) proven(id); return; }
        if (seen['open:' + id] || waiting[id]) return;
        waiting[id] = w.setTimeout(function () { delete waiting[id]; }, WAIT_MS);
    });
    /* This tab's own answer: the confirmed open, or the lookup's "booked".
       Every other shape of this event proves nothing. */
    d.addEventListener('sv:position-changed', function (e) {
        var a = (e && e.detail) || {};
        if (a.trade_id == null || !(a.ok === true || a.state === 'booked')) return;
        var id = String(a.trade_id), filled = !a.working;
        answers[id] = { filled: filled, at: now() };
        if (waiting[id]) {
            w.clearTimeout(waiting[id]); delete waiting[id];
            if (filled) proven(id);
        }
    });

    /* ── the light along a row ────────────────────────────────────────── */
    function lightRow(row) {
        var m = mode();
        if (!m || !row) return null;
        var table = row.closest('table');
        if (!table) return null;
        var host = table.parentElement;
        while (host && host !== body && w.getComputedStyle(host).position === 'static') host = host.parentElement;
        host = host || body;
        var act = row.querySelector('[data-sv-close-trade]') || row.querySelector('td:last-child button, td:last-child .btn');
        var cell = act && act.closest('td, th');
        var r = row.getBoundingClientRect(), h = host.getBoundingClientRect();
        var right = cell ? cell.getBoundingClientRect().left : r.right;
        var el = d.createElement('div');
        el.className = m === 'calm' ? 'sv-row-light sv-row-light--still' : 'sv-row-light';
        el.setAttribute('aria-hidden', 'true');
        if (host === body) {
            el.style.left = (r.left + (w.scrollX || 0)) + 'px';
            el.style.top = (r.bottom - 2 + (w.scrollY || 0)) + 'px';
        } else {
            el.style.left = (r.left - h.left - (host.clientLeft || 0) + (host.scrollLeft || 0)) + 'px';
            el.style.top = (r.bottom - 2 - h.top - (host.clientTop || 0) + (host.scrollTop || 0)) + 'px';
        }
        el.style.width = Math.max(0, right - r.left) + 'px';
        function gone() { if (el.parentNode) el.parentNode.removeChild(el); }
        el.addEventListener('animationend', gone);
        w.setTimeout(gone, MOMENT_MS);
        host.appendChild(el);
        return el;
    }
    function quote(id) { return String(id).replace(/["\\]/g, '\\$&'); }
    d.addEventListener('sv:live-swapped', function (e) {
        var t = now(), scope = (e && e.detail && e.detail.node) || d;
        for (var id in watch) {
            if (t > watch[id]) { delete watch[id]; continue; }
            var btn = scope.querySelector('tr[data-sv-position-row] [data-sv-close-trade="' + quote(id) + '"]');
            var row = btn && btn.closest('tr[data-sv-position-row]');
            if (!row) continue;
            delete watch[id];
            lightRow(row);
        }
        var node = e && e.detail && e.detail.node;
        if (node && node.id === 'railSignalsBody') railSwapped();
    });

    /* ── a new signal ─────────────────────────────────────────────────── */
    var onRail = null, high = 0;
    function created(card) {
        var t = w.Date.parse(card.getAttribute('data-created') || '');
        return isNaN(t) ? 0 : t;
    }
    /* Reads the rail; returns the cards that are new by the server's clock. */
    function readRail() {
        var cards = d.querySelectorAll('#railSignalsBody .sr-signal-wrap[data-signal-id]');
        var ids = {}, fresh = [], top = high;
        for (var i = 0; i < cards.length; i++) {
            var id = cards[i].getAttribute('data-signal-id'), t = created(cards[i]);
            ids[id] = 1;
            if (onRail && !onRail[id] && t > high) fresh.push(cards[i]);
            if (t > top) top = t;
        }
        onRail = ids; high = top;
        return fresh;
    }
    function arrive(card) {
        var m = mode();
        if (!m || !card) return false;
        var classes = m === 'calm' ? ['sv-moment-arrive', 'sv-moment--still'] : ['sv-moment-arrive'];
        for (var i = 0; i < classes.length; i++) card.classList.add(classes[i]);
        once(card, ['sv-moment-arrive', 'sv-moment--still'], /^sv-light-/);
        return true;
    }
    function icon(el) {
        el = el || d.querySelector('#railSignals .rail-head .rh-icon');
        if (!el || !mode()) return false;
        el.classList.add('sv-moment-icon');
        once(el, ['sv-moment-icon'], /^sv-moment-icon/);
        return true;
    }
    function railSwapped() {
        var fresh = readRail(), lit = 0;
        for (var i = 0; i < fresh.length && lit < MAX_CARDS; i++) {
            if (fresh[i].offsetWidth > 0 && arrive(fresh[i])) lit++;    /* a card the filters hide lights nothing */
        }
        if (lit) icon();
    }
    readRail();
    /* The rail announces its swap as htmx:afterSwap, naming its body. */
    d.addEventListener('htmx:afterSwap', function (e) {
        var node = e && e.detail && e.detail.svRegion;
        if (node && node.id === 'railSignalsBody') railSwapped();
    });

    /* ── the gaze ─────────────────────────────────────────────────────── */
    var iris = d.querySelector('.sv-brand-iris'), gx = 0, gy = 0, queued = 0, centre = null, looking = false;
    function gazing() {
        return !!iris && !!wrap && ambience() === 'magic' && !reduced.matches && !body.classList.contains('light-mode');
    }
    function look() {
        queued = 0;
        if (!gazing()) return;
        iris.style.transform = 'translate(' + gx.toFixed(2) + 'px, ' + gy.toFixed(2) + 'px)';
        looking = true;
    }
    function clamp(v) { return v < -1 ? -1 : (v > 1 ? 1 : v); }
    d.addEventListener('pointermove', function (e) {
        if (!gazing()) return;
        if (!centre) {
            var r = wrap.getBoundingClientRect();
            centre = [r.left + r.width / 2, r.top + r.height / 2];
        }
        gx = clamp((e.clientX - centre[0]) / (w.innerWidth / 2 || 1)) * 2.4;
        gy = clamp((e.clientY - centre[1]) / (w.innerHeight / 2 || 1)) * 1;
        if (!queued) queued = w.requestAnimationFrame(look);
    }, { passive: true });
    function moved() { centre = null; }
    w.addEventListener('resize', moved);
    w.addEventListener('scroll', moved, { passive: true, capture: true });
    /* The Ambience left Magic: the iris looks ahead again. */
    if (w.MutationObserver) {
        new w.MutationObserver(function () {
            if (looking && !gazing()) { iris.style.transform = ''; looking = false; }
        }).observe(body, { attributes: true, attributeFilter: ['class', 'data-sv-ambience'] });
    }

    /* ── by hand: /design/kit/'s play buttons, and the tests ──────────────
       The same lights, asked for directly. Never an event: nothing else on
       the page hears it, and no trade is named. */
    w.SV = w.SV || {};
    w.SV.moments = {
        play: function (kind, el, other) {
            if (kind === 'fill') { lastFlare = -1e9; flare(false); return lightRow(el); }
            if (kind === 'close') { lastFlare = -1e9; return flare(true); }
            if (kind === 'signal') { icon(other); return arrive(el); }
            if (kind === 'stop' && el) {                /* the approved neutral wash, as sv-flash.js sets it */
                el.classList.remove('sv-flash', 'sv-flash--same');
                void el.offsetWidth;
                el.classList.add('sv-flash', 'sv-flash--same');
                once(el, ['sv-flash', 'sv-flash--same'], /^sv-flash/);
                return true;
            }
            return false;
        }
    };
})(window, document);
