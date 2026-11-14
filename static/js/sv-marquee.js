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
   px, owned here: the wheel (svWheelMarquee) and the drag in base.html
   move it through SVMarquee.offset() / .to() (so would the arrow crawl,
   but no template renders arrow buttons today), and the scroll goes on
   from wherever the hand left it.

     * A constant speed, independent of the content: each frame moves a
       strip its speed times the display's frame interval, times the
       whole frames since the last one (the interval measured while
       running, snapped to the display's own rate; the frames a busy
       machine drops do not lengthen it). The same distance
       every frame, so the device-pixel steps keep one even rhythm: news
       at 30 px/s on a 60 Hz screen is half a pixel a frame, and the
       frame clock's jitter (coarsened to 0.1 ms) decided each rounding
       (the review, 2026-11-13: it stood two frames and stepped two). A
       frame late by more than DT_MAX catches up DT_MAX only: after a long
       task the strip goes on from where it froze instead of leaping.
     * A seamless loop: the track holds the same items twice; the period is
       measured (the left of the first item of the second half minus the
       left of the first item) and the position wraps on it, so the picture
       at pos and at pos - period is the same one. The period is made a
       whole number of device pixels (the gap between the halves padded by
       the fraction, the track's width kept): otherwise the copy sits at
       another sub-pixel phase and every glyph shifts once a loop. A strip
       whose one pass fits in its frame (two headlines; no news yet:
       "Quiet") has nothing to reveal: it stands at its start, its copy
       hidden, and the wheel goes to the page.
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
       is on the page (data-sv-marquee-pop, anchored in this strip: hovered,
       crossing or pinned), while focus is in it (a focused item is shown,
       clear of the collapse tab: the item itself, never wrapped to its
       twin), while a finger is down and three seconds after it lifts,
       while the hand drags it, while the tab is hidden or the PIN lock is
       up, while the strip is collapsed or not displayed, and under reduced
       motion (the wheel and the drag still move it there). While no strip
       runs no frame is asked for; a strip resumes from the same spot (its
       first frame moves 0).
     * Content, not the magic layer: it reads no mood setting and runs the
       same in both themes.

   Display only: it reads boxes and writes one transform per strip. No
   request, no storage. tests/test_marquee.py measures it in Chromium. */
(function (w, d) {
    'use strict';
    if (w.SVMarquee || !d) return;

    var DT_MAX = 0.05;          /* s: a late frame catches up this much at most (2 px at 40 px/s) */
    var TOUCH_MS = 3000;        /* a finger lifted: still this long after */
    var SHOW_PX = 24;           /* a focused item is shown this far inside */
    var TRACK = '.ticker-track, .dh-track';
    /* The displays' own rates (Hz): a measured interval this close to one
       of them (1%) is that one exactly, so a frame's distance is the
       speed's own fraction of a pixel (30 px/s at 60 Hz: exactly 0.5). */
    var RATES = [30, 48, 50, 60, 72, 75, 90, 100, 120, 144, 165, 240];
    var reduced = w.matchMedia ? w.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
    var hovers = w.matchMedia ? w.matchMedia('(hover: hover)').matches : true;
    var strips = [], raf = 0, locked = false;
    var frameMs = 0, gaps = [], lastNow = 0;   /* the display's frame interval, measured */
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
        this.span = 0;          /* the items' extent, px of track */
        this.origin = 0;        /* the track's own left, from the clip's */
        this.loop = false;
        this.items = [];        /* {key, copy, left, w}, px of track, as last measured */
        this.padded = [];       /* the two items carrying the period's padding */
        this.hid = [];          /* the copy, hidden while there is no loop */
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

    /* The period's padding off, so the items are measured as they are. */
    function unpad(s) {
        s.padded.forEach(function (el) { el.style.marginRight = ''; });
        s.padded = [];
    }

    function measure(s) {
        unpad(s);
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
        s.width = s.clip.clientWidth;
        /* the transform written and the clip's scroll are in the rect: the
           track's own left in the clip */
        s.origin = tr.left - (s.x || 0) - cr.left + s.clip.scrollLeft;
        s.period = halves ? items[n / 2].left - items[0].left : 0;
        s.loop = s.period > 0 && s.width > 0 && s.period >= s.width;
        /* One loop a whole number of device pixels (the review, 2026-11-13):
           a period of 6638.39 px put the copy at another sub-pixel phase than
           the first half, and at each wrap every glyph in view shifted by the
           fraction (backwards on the news strip). The gap between the halves
           takes the fraction (a margin on the first half's last item), and
           the second half's last item gives it back: the track's width is
           unchanged, so no ResizeObserver hears of it. */
        if (s.loop) {
            var dpr = w.devicePixelRatio || 1;
            var pad = Math.ceil(s.period * dpr - 1e-3) / dpr - s.period;
            if (pad > 1e-3) {
                els[n / 2 - 1].style.marginRight = pad + 'px';
                els[n - 1].style.marginRight = -pad + 'px';
                s.padded = [els[n / 2 - 1], els[n - 1]];
                for (i = n / 2; i < n; i++) items[i].left += pad;
                s.period += pad;
            }
        }
        /* With nothing to reveal the copy would stand beside the first half
           (two headlines, twice): hidden while there is no loop. */
        s.hid.forEach(function (el) { el.style.visibility = ''; });
        s.hid = [];
        for (i = n / 2; halves && !s.loop && i < n; i++) {
            els[i].style.visibility = 'hidden';
            s.hid.push(els[i]);
        }
        s.items = items;
        s.span = n ? items[n - 1].left + items[n - 1].w : 0;
        stats.measures++;
    }

    function wrap(s, p) {
        if (!s.loop) return 0;
        p = p % s.period;
        return p < 0 ? p + s.period : p;
    }

    /* Not wrapped: kept where the track still covers the whole clip. A
       focused item is shown this way, itself and not its twin a loop away
       (the next frame wraps the position: the same picture). */
    function within(s, p) {
        return Math.max(s.origin, Math.min(s.origin + s.span - s.width, p));
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

    /* The display's frame interval (ms), from the gaps between frames while
       running: the mean of the last ones near their median, snapped to the
       display's own rate when that close, and kept until it moves by more
       than 3% (another screen).
       Unless the median is two, three or four times a gap that still
       recurs (five of the last ones near it): then it is frames the machine
       dropped, and that shorter gap is the screen's (2026-11-14). A busy
       machine draws every other frame for a second: the median became
       33.3 ms on a 60 Hz screen, the frames that came at 16.7 ms were no
       longer whole frames and moved by their own time, and the news stood
       two frames and stepped two, as before whole frames. */
    function interval(gap) {
        if (gap > 3 && gap < 60) {
            gaps.push(gap);
            if (gaps.length > 40) gaps.shift();
        }
        if (gaps.length < 20) return frameMs;
        var med = gaps.slice().sort(function (a, b) { return a - b; })[gaps.length >> 1];
        var sum, k, i, d;
        for (d = 4; d > 1; d--) {
            for (i = 0, k = 0; i < gaps.length; i++) {
                if (Math.abs(gaps[i] - med / d) < med / d * 0.25) k++;
            }
            if (k >= 5) { med = med / d; break; }
        }
        for (i = 0, sum = 0, k = 0; i < gaps.length; i++) {
            if (Math.abs(gaps[i] - med) < med * 0.25) { sum += gaps[i]; k++; }
        }
        var mean = sum / k;
        for (i = 0; i < RATES.length; i++) {
            if (Math.abs(mean * RATES[i] / 1000 - 1) < 0.01) { mean = 1000 / RATES[i]; break; }
        }
        if (!frameMs || Math.abs(mean - frameMs) > frameMs * 0.03) frameMs = mean;
        return frameMs;
    }

    function tick(now) {
        raf = 0;
        var any = false, f = lastNow ? interval(now - lastNow) : frameMs;
        lastNow = now;
        for (var i = 0; i < strips.length; i++) {
            var s = strips[i];
            if (!running(s)) { s.last = 0; continue; }
            any = true;
            if (s.last) {
                /* Whole frames at the speed: the same distance every frame,
                   one rhythm of device pixels (a busy machine's frames at
                   16.7 and 33.3 ms in turn are one and two frames). A gap
                   that is not whole frames (the interval still being
                   learnt, another screen not yet taken) moves by its own
                   time. A late frame catches up DT_MAX at most. */
                var due = now - s.last, n = f ? Math.round(due / f) : 0;
                if (n && Math.abs(due - n * f) > f / 4) n = 0;
                var ms = Math.min(n ? n * f : due, DT_MAX * 1000);
                if (ms > 0) s.pos = wrap(s, s.pos + s.speed * ms / 1000);
            }
            s.last = now;
            paint(s);
        }
        stats.frames++;
        if (any) raf = w.requestAnimationFrame(tick);
        else lastNow = 0;
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
        if (!any) lastNow = 0;
    }

    /* A card this strip opened, on <body> and displayed (the popup engine
       in base.html portals it there while it is open, its anchor in
       _origParent). A card anchored elsewhere that wears the same class
       (the rail's watchlist cards are .dh-pop too) is not this strip's. */
    function popOpen(s) {
        if (!s.pop || !d.body) return false;
        var kids = d.body.children;
        for (var i = 0; i < kids.length; i++) {
            var n = kids[i];
            if (!(n.matches && n.matches(s.pop))) continue;
            if (n._origParent && !s.frame.contains(n._origParent)) continue;
            if (w.getComputedStyle(n).display !== 'none') return true;
        }
        return false;
    }

    /* A focused item the strip does not show wholly is brought in, clear of
       the collapse tab, by the strip's own position (the browser cannot
       scroll an item that sits left of the clip into view). That element
       itself, not its twin in the other half: within(), never wrapped. */
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
        s.pos = within(s, to);
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
           that move becomes the strip's own position, NEVER wrapped on the
           loop (the review, 2026-11-13): a wrap traded the focused item for
           its twin a loop away and left the focus off screen, the strip
           jumping at each Shift+Tab. Then the focused item is shown from
           its own box: the browser's scroll and show() may both have moved
           the strip for it. */
        s.clip.addEventListener('scroll', function () {
            var by = s.clip.scrollLeft;
            if (!by) return;
            s.clip.scrollLeft = 0;
            if (!s.loop) return;
            s.pos = within(s, s.pos + by);
            paint(s);
            var a = d.activeElement;
            if (a && s.track.contains(a)) show(s, a);
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

    /* Another device-pixel ratio (a zoom, another screen): the rounding and
       the period's padding are per device pixel, so measure again. */
    function watchDpr() {
        if (!w.matchMedia) return;
        var mq = w.matchMedia('(resolution: ' + (w.devicePixelRatio || 1) + 'dppx)');
        function on() {
            if (mq.removeEventListener) mq.removeEventListener('change', on);
            else if (mq.removeListener) mq.removeListener(on);
            strips.forEach(refresh);
            watchDpr();
        }
        if (mq.addEventListener) mq.addEventListener('change', on);
        else if (mq.addListener) mq.addListener(on);
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
        watchDpr();
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
                     loop: s.loop, running: running(s), holds: Object.keys(s.holds),
                     frameMs: frameMs };
        },
        stats: stats
    };

    if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', init);
    else init();
})(window, document);
