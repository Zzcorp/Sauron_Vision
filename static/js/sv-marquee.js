/* sv-marquee.js: the price headband and the news ticker scroll again
   (2026-11-13).

   The operator's decision, 2026-11-13: the two strips across the top of
   every work page scroll on their own again, continuously, right to left,
   not too fast, and stop on hover. S1a had stopped them (sv-kit.css §8,
   where the decision is recorded), and what was left was three hand
   drivers with three offsets: the wheel's (svWheelMarquee), a second wheel
   listener on the ticker, the drag's; leaving a strip threw the hand's
   position away. Before S1a the keyframe marquee ran at half the track's
   width over a fixed duration, so its speed was the content's, and a
   refetch or a painter update that changed the width moved the strip.

   ONE DRIVER for every frame that declares data-sv-marquee-speed (px per
   second: base.html, prices 40, news 30). Each strip has ONE position, in
   px, owned here: the wheel (svWheelMarquee), the drag and the arrow crawl
   in base.html move it through SVMarquee.offset() / .to(), and the scroll
   goes on from wherever the hand left it.

     * A constant speed, independent of the content: pos += speed * dt.
     * A seamless loop: the track holds the same items twice; the period is
       measured (the left of the first item of the second half minus the
       left of the first item) and the position wraps on it, so the picture
       at pos and at pos - period is the same one. A strip whose one pass
       fits in its frame (no news yet: "Quiet") has nothing to reveal: it
       stands at its start and the wheel goes to the page.
     * Never a jump on a refresh: a ResizeObserver (widths: the one-price
       painter, a region sweep, the fonts) and a MutationObserver (items
       added, removed, swapped by a news refetch) measure again, and the
       item at the frame's left edge (or the first one after it still
       there, by its news id or symbol and its half) is put back where it
       was on the screen. Never a restart at 0.
     * Transform only (the tracks are on their own layer, sv-kit.css §8),
       written only when its device pixel changes, rounded to device
       pixels so the figures stay crisp. No layout per frame.
     * Still while the pointer is on the strip, while a card opened from it
       is on the page (data-sv-marquee-pop: hovered, crossing or pinned),
       while focus is in it (a focused item is shown), while a finger is
       down and three seconds after it lifts, while the hand drags it,
       while the tab is hidden or the PIN lock is up, while the strip is
       collapsed or not displayed, and under reduced motion (the wheel and
       the drag still move it there). While no strip runs no frame is asked
       for; a strip resumes from the same spot (its first frame moves 0).
     * Content, not the magic layer: every Ambience, both themes.

   Display only: it reads boxes and writes one transform per strip. No
   request, no storage. tests/test_marquee.py measures it in Chromium. */
(function (w, d) {
    'use strict';
    if (w.SVMarquee || !d) return;

    var DT_MAX = 0.25;          /* s: a late frame catches up this much at most */
    var TOUCH_MS = 3000;        /* a finger lifted: still this long after */
    var SHOW_PX = 24;           /* a focused item is shown this far inside */
    var TRACK = '.ticker-track, .dh-track';
    var reduced = w.matchMedia ? w.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
    var hovers = w.matchMedia ? w.matchMedia('(hover: hover)').matches : true;
    var strips = [], raf = 0, locked = false;
    var stats = { frames: 0, writes: 0, measures: 0 };

    function Strip(frame, track) {
        this.frame = frame;
        this.track = track;
        this.clip = track.parentElement;
        this.speed = Math.max(0, parseFloat(frame.getAttribute('data-sv-marquee-speed')) || 0);
        this.pop = frame.getAttribute('data-sv-marquee-pop') || '';
        this.pos = 0;           /* px of track at the clip's left edge, in [0, period) */
        this.period = 0;
        this.width = 0;         /* the clip's */
        this.origin = 0;        /* the track's own left, from the clip's */
        this.loop = false;
        this.items = [];        /* {key, copy, left, w}, px of track, as last measured */
        this.x = null;          /* the transform written, px */
        this.css = '';
        this.last = 0;          /* the last frame's time, 0: none yet */
        this.holds = {};
        this.touchT = 0;
    }

    // ── what the strip holds ─────────────────────────────────────────────

    function keyOf(el) {
        return el.getAttribute('data-news-id') || el.getAttribute('data-symbol')
            || el.getAttribute('href') || (el.textContent || '').trim().slice(0, 80);
    }

    function measure(s) {
        var els = s.track.children, n = els.length;
        var tr = s.track.getBoundingClientRect(), cr = s.clip.getBoundingClientRect();
        var seen = {}, items = [];
        for (var i = 0; i < n; i++) {
            var r = els[i].getBoundingClientRect(), k = keyOf(els[i]);
            seen[k] = (seen[k] || 0) + 1;
            items.push({ key: k, copy: seen[k] - 1, left: r.left - tr.left, w: r.width });
        }
        var halves = n >= 2 && n % 2 === 0;
        for (i = 0; halves && i < n / 2; i++) {
            if (items[i].key !== items[i + n / 2].key) halves = false;
        }
        s.items = items;
        s.width = s.clip.clientWidth;
        /* the transform written is in the rect: the untransformed left */
        s.origin = tr.left - (s.x || 0) - cr.left;
        s.period = halves ? items[n / 2].left - items[0].left : 0;
        s.loop = s.period > 0 && s.width > 0 && s.period >= s.width;
        stats.measures++;
    }

    function wrap(s, p) {
        if (!s.loop) return 0;
        p = p % s.period;
        return p < 0 ? p + s.period : p;
    }

    /* The item at the clip's left edge and the ones after it in view, each
       with how far the edge is into it. */
    function anchors(s) {
        var u = s.pos - s.origin, out = [];
        for (var i = 0; i < s.items.length && out.length < 12; i++) {
            var it = s.items[i];
            if (it.left + it.w <= u) continue;
            if (it.left >= u + s.width) break;
            out.push({ key: it.key, copy: it.copy, off: u - it.left });
        }
        return out;
    }

    function reanchor(s, list) {
        for (var j = 0; j < list.length; j++) {
            for (var i = 0; i < s.items.length; i++) {
                var it = s.items[i];
                if (it.key === list[j].key && it.copy === list[j].copy) {
                    s.pos = wrap(s, it.left + list[j].off + s.origin);
                    return true;
                }
            }
        }
        return false;
    }

    /* Measure again and keep what the eye sees where it was. */
    function refresh(s) {
        var list = s.items.length ? anchors(s) : [];
        measure(s);
        if (!s.loop) s.pos = 0;
        else if (!reanchor(s, list)) s.pos = wrap(s, s.pos);
        paint(s);
        wake();
    }

    function paint(s) {
        var dpr = w.devicePixelRatio || 1;
        var x = -Math.round(s.pos * dpr) / dpr;
        if (x === 0) x = 0;     /* never -0 */
        if (x === s.x && s.track.style.transform === s.css) return;
        s.track.style.transform = 'translate3d(' + x + 'px, 0px, 0px)';
        s.x = x;
        s.css = s.track.style.transform;
        stats.writes++;
    }

    // ── running or still ─────────────────────────────────────────────────

    function held(s) {
        for (var k in s.holds) if (s.holds[k]) return true;
        return false;
    }

    function running(s) {
        return s.loop && s.speed > 0 && !held(s) && !reduced.matches && !d.hidden && !locked;
    }

    function hold(s, why, on) {
        if (!!s.holds[why] === !!on) return;
        if (on) s.holds[why] = true;
        else delete s.holds[why];
        wake();
    }

    function tick(now) {
        raf = 0;
        var any = false;
        for (var i = 0; i < strips.length; i++) {
            var s = strips[i];
            if (!running(s)) { s.last = 0; continue; }
            any = true;
            if (s.last) {
                var dt = Math.min((now - s.last) / 1000, DT_MAX);
                if (dt > 0) s.pos = wrap(s, s.pos + s.speed * dt);
            }
            s.last = now;
            paint(s);
        }
        stats.frames++;
        if (any) raf = w.requestAnimationFrame(tick);
    }

    /* Whatever changed: run, or ask for no frame at all. A strip that stops
       forgets its clock, so it starts again from where it stands. */
    function wake() {
        var any = false;
        for (var i = 0; i < strips.length; i++) {
            if (running(strips[i])) any = true;
            else strips[i].last = 0;
        }
        if (any && !raf) raf = w.requestAnimationFrame(tick);
        else if (!any && raf) { w.cancelAnimationFrame(raf); raf = 0; }
    }

    /* A card this strip opened, on <body> and displayed (the popup engine
       in base.html portals it there while it is open). */
    function popOpen(s) {
        if (!s.pop || !d.body) return false;
        var kids = d.body.children;
        for (var i = 0; i < kids.length; i++) {
            var n = kids[i];
            if (n.matches && n.matches(s.pop) && w.getComputedStyle(n).display !== 'none') return true;
        }
        return false;
    }

    /* A focused item the strip does not show is brought in, by the strip's
       own position (the browser cannot scroll an item that sits left of
       the clip into view). That element itself, not its twin in the other
       half: the position is not wrapped here but kept where the track still
       covers the whole clip (the next frame wraps it, the same picture). */
    function show(s, el) {
        if (!s.loop || !el || el === s.track || !s.track.contains(el)) return;
        while (el.parentElement !== s.track) el = el.parentElement;
        var c = s.clip.getBoundingClientRect(), r = el.getBoundingClientRect();
        var right = c.right, tab = s.frame.querySelector('.hb-collapse-btn');
        if (tab && tab.offsetWidth) right = Math.min(right, tab.getBoundingClientRect().left);
        var to;
        if (r.left < c.left) to = s.pos - (c.left - r.left) - SHOW_PX;
        else if (r.right > right) to = s.pos + (r.right - right) + SHOW_PX;
        else return;
        var lo = s.origin, hi = s.origin + 2 * s.period - s.width;
        s.pos = Math.max(lo, Math.min(hi, to));
        paint(s);
    }

    function bind(s) {
        var f = s.frame;
        f.addEventListener('pointerenter', function (e) {
            if (e.pointerType !== 'touch') hold(s, 'hover', true);
        });
        f.addEventListener('pointerleave', function (e) {
            if (e.pointerType !== 'touch') hold(s, 'hover', false);
        });
        f.addEventListener('pointerdown', function (e) {
            if (e.pointerType !== 'touch') return;
            if (s.touchT) { w.clearTimeout(s.touchT); s.touchT = 0; }
            hold(s, 'touch', true);
        });
        f.addEventListener('focusin', function (e) {
            hold(s, 'focus', true);
            show(s, e.target);
        });
        f.addEventListener('focusout', function (e) {
            var to = e.relatedTarget;
            hold(s, 'focus', !!(to && f.contains(to)));
        });
        /* The browser scrolls the clip to show a focused item to the right;
           that move becomes the strip's own position. */
        s.clip.addEventListener('scroll', function () {
            var by = s.clip.scrollLeft;
            if (!by) return;
            s.clip.scrollLeft = 0;
            s.pos = wrap(s, s.pos + by);
            paint(s);
        }, { passive: true });
        if (w.MutationObserver) {
            new w.MutationObserver(function () { refresh(s); })
                .observe(s.track, { childList: true });
            new w.MutationObserver(function () {
                var shut = f.classList.contains('collapsed');
                if (shut) hold(s, 'hover', false);
                hold(s, 'collapsed', shut);
            }).observe(f, { attributes: true, attributeFilter: ['class'] });
        }
        hold(s, 'collapsed', f.classList.contains('collapsed'));
        if (hovers && f.matches(':hover')) hold(s, 'hover', true);
    }

    /* A finger lifted anywhere: the strips it held run again a few seconds
       later. */
    function lift(e) {
        if (e.pointerType !== 'touch') return;
        strips.forEach(function (s) {
            if (!s.holds.touch) return;
            if (s.touchT) w.clearTimeout(s.touchT);
            s.touchT = w.setTimeout(function () { s.touchT = 0; hold(s, 'touch', false); }, TOUCH_MS);
        });
    }

    function find(track) {
        for (var i = 0; i < strips.length; i++) if (strips[i].track === track) return strips[i];
        return null;
    }

    function init() {
        var frames = d.querySelectorAll('[data-sv-marquee-speed]');
        for (var i = 0; i < frames.length; i++) {
            var f = frames[i], t = f.querySelector(TRACK);
            if (!t || f._svMarqueeStrip) continue;
            f._svMarqueeStrip = true;
            var s = new Strip(f, t);
            strips.push(s);
            bind(s);
            refresh(s);
        }
        if (!strips.length) return;
        if (w.ResizeObserver) {
            var ro = new w.ResizeObserver(function (entries) {
                var seen = [];
                entries.forEach(function (en) {
                    strips.forEach(function (s) {
                        if ((en.target === s.track || en.target === s.clip) && seen.indexOf(s) < 0) seen.push(s);
                    });
                });
                seen.forEach(refresh);
            });
            strips.forEach(function (s) { ro.observe(s.track); ro.observe(s.clip); });
        }
        if (w.MutationObserver && d.body) {
            var pops = strips.map(function (s) { return s.pop; }).filter(Boolean).join(', ');
            new w.MutationObserver(function (records) {
                if (!pops) return;
                var hit = false;
                records.forEach(function (r) {
                    [r.addedNodes, r.removedNodes].forEach(function (list) {
                        for (var i = 0; i < list.length; i++) {
                            if (list[i].nodeType === 1 && list[i].matches(pops)) hit = true;
                        }
                    });
                });
                if (hit) strips.forEach(function (s) { hold(s, 'popup', popOpen(s)); });
            }).observe(d.body, { childList: true });
        }
        if (d.fonts && d.fonts.ready) d.fonts.ready.then(function () { strips.forEach(refresh); });
        w.addEventListener('resize', function () { strips.forEach(paint); });
        w.addEventListener('pointerup', lift, true);
        w.addEventListener('pointercancel', lift, true);
        w.addEventListener('pageshow', function () { strips.forEach(function (s) { s.last = 0; }); wake(); });
        d.addEventListener('visibilitychange', wake);
        d.addEventListener('sv:pin-locked', function () { locked = true; wake(); });
        d.addEventListener('sv:pin-unlocked', function () { locked = false; wake(); });
        if (reduced.addEventListener) reduced.addEventListener('change', wake);
        else if (reduced.addListener) reduced.addListener(wake);
        wake();
    }

    w.SVMarquee = {
        /* True when this driver keeps the track's position. */
        owns: function (track) { return !!find(track); },
        /* The track's offset, px (the transform's x before rounding, <= 0). */
        offset: function (track) {
            var s = find(track);
            return s ? -s.pos : 0;
        },
        /* Put the track at offset x (wrapped on its loop) and show it now;
           the offset it took. A strip with nothing to reveal keeps 0. */
        to: function (track, x) {
            var s = find(track);
            if (!s) return x;
            if (!s.loop) return -s.pos;
            s.pos = wrap(s, -x);
            paint(s);
            return -s.pos;
        },
        /* Hold the strip still for a reason of the caller's (the drag). */
        hold: function (track, why, on) {
            var s = find(track);
            if (s) hold(s, 'by:' + why, on);
        },
        state: function (track) {
            var s = find(track);
            if (!s) return null;
            return { pos: s.pos, period: s.period, width: s.width, speed: s.speed,
                     loop: s.loop, running: running(s), holds: Object.keys(s.holds) };
        },
        stats: stats
    };

    if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', init);
    else init();
})(window, document);
