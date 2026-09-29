/* sv-motion.js — the motion layer's nerves (2026-09-29).
 *
 * The sheet (static/css/sv-motion.css) holds every keyframe and
 * transition; this file only decides WHEN a class goes on and, just as
 * carefully, when it comes off. Four jobs:
 *
 *   a. SCROLL REVEAL. Cards and panels whose top is below the viewport
 *      at scan time get .sv-rv (hidden, 14px low) and an observer; on
 *      intersect they get .in and rise. Siblings are staggered through
 *      --sv-i. A safety timer reveals everything still hidden 2.5s after
 *      the scan, whatever the observer did — an element inside a
 *      collapsed disclosure never intersects, and a page must never keep
 *      a card the operator cannot see. Both classes are removed once the
 *      transition has ended, so the card returns to its own styles (the
 *      hover lift is a transform transition of its own).
 *      Only with IntersectionObserver, only without prefers-reduced-
 *      motion, and only for what is genuinely off-screen: nothing that
 *      is on the screen at rest is ever touched.
 *   b. HTMX. A swap target is scanned again on its first settle, and
 *      then only for a swap the operator caused (a tab click carries a
 *      triggeringEvent; the live refresh through htmx.ajax, the `every`
 *      poll and the initial `load` trigger do not). The Operations
 *      Center's tab body re-renders on every fill, and a reveal that
 *      replayed on each would blink the lower cards for nobody.
 *      A live region (_partials/live_region.html) that re-swapped gets
 *      .sv-swapped for one beat.
 *   c. PAGE LEAVE. A plain same-origin link click adds body.sv-leaving
 *      and LETS THE BROWSER GO: no preventDefault, no location
 *      assignment. pageshow with `persisted` takes the class off, or a
 *      bfcache return would show a blank page; a timer takes it off too,
 *      for a click that turned out to be a download or a cancelled
 *      navigation. Not on a phone, whose browser has its own transition.
 *   d. COUNT-UP. [data-sv-count="<number>"] counts from 0 to the number
 *      on reveal, thousands-separated, never NaN: an attribute that does
 *      not parse leaves the server's own text exactly as rendered.
 *
 * Reduced motion is read once through matchMedia and gates all four.
 */
(function (w, d) {
  "use strict";

  var SAFETY_MS = 2500;      /* everything still hidden is revealed here */
  var LEAVE_RESET_MS = 2500; /* a leave that never left comes back here */
  var STEP_CAP = 8;          /* --sv-i beyond this is one long wait, not a cascade */
  var RV_MS = 550;           /* the sheet's --sv-rv-dur */
  var RV_STEP_MS = 60;       /* the sheet's --sv-rv-step */
  var COUNT_MS = 900;
  var FOLD_MARGIN = 20;      /* an element this close to the fold is on screen */

  var reduce = !!(w.matchMedia &&
                  w.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var hasIO = typeof w.IntersectionObserver === 'function';

  function phone() {
    return !!(w.matchMedia && w.matchMedia('(max-width: 768px)').matches);
  }

  function each(list, fn) {
    Array.prototype.forEach.call(list || [], fn);
  }

  /* ── a. scroll reveal ─────────────────────────────────────────────── */

  /* What may rise. [data-sv-reveal] marks a container whose direct
     children are the cards (the Operations Center's grids); the rest are
     the shapes every page is built from. The stacked table rows are
     candidates only on a phone, where the stack block turns each row into
     a grid card; a real table row is left alone. */
  var CANDIDATES = '[data-sv-reveal] > *, .page-content .grid > *, ' +
                   '.page-content .card, .page-content .stat-box, ' +
                   '.page-content .metric, .page-content .oc-strip > *, ' +
                   '.page-content .pillar';
  var PHONE_CANDIDATES = '.page-content table.sv-stack tbody tr';

  /* Never a candidate: the fixed chrome, the overlays, the passation
     card, and anything INSIDE a live region — the region swaps its
     innerHTML from under whatever class sat there. */
  var OUTSIDE = '.info-panel-wrap, .data-headband, .ticker-bar, ' +
                '.signals-rail, .sidebar, .topbar, .sv-passation-card, ' +
                '[data-sv-live], [data-sv-overlay], .modal, .modal-overlay, ' +
                '.sv-dialog, .il-overlay, .se-chat-panel, .gollum-dialog';

  /* Never a candidate when it CONTAINS one of these: a chart (its
     renderer measures the box, and the expand pin is position:fixed), a
     portalled popup, a dialog host, or a sticky bar. A table's sticky
     header row is not in this list on purpose: it sticks to the
     .table-wrapper scroller INSIDE the card, which a transform on the
     card does not move, and the transition ends at transform: none. */
  var INSIDE = '.oc-donut, .oc-sparkline, .sv-bars-svg, .sv-candle-container, ' +
               'canvas, .tv-lightweight-charts, [data-sv-overlay], .sr-popup, ' +
               '.ip-dropdown, .sv-card, .dh-pop, .nf-pop, .ticker-popup, ' +
               '.sv-sel-bar, .sv-edit-toolbar, .ask-side, .chat-compose, ' +
               '[class*="sticky"], [style*="sticky"], [style*="fixed"]';

  var io = null;

  function observer() {
    if (io) return io;
    io = new w.IntersectionObserver(function (entries) {
      each(entries, function (en) {
        if (en.isIntersecting) show(en.target);
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0 });
    return io;
  }

  function stepOf(el) {
    var i = parseInt(el.style.getPropertyValue('--sv-i'), 10);
    return isNaN(i) ? 0 : i;
  }

  /* Reveal one element and, once its transition has ended, hand it back
     to its own styles. transitionend can be swallowed (a tab in the
     background, a transition cut short by display:none), so a timer sized
     to the sheet's duration backs it up. */
  function show(el) {
    if (io) io.unobserve(el);
    if (!el.classList.contains('sv-rv')) return;
    el.classList.add('in');
    runPendingCounts(el);
    var settled = false;
    function done() {
      if (settled) return;
      settled = true;
      el.removeEventListener('transitionend', onEnd);
      el.classList.remove('sv-rv');
      el.classList.remove('in');
      el.style.removeProperty('--sv-i');
    }
    function onEnd(e) {
      if (e.target === el && e.propertyName === 'opacity') done();
    }
    el.addEventListener('transitionend', onEnd);
    setTimeout(done, RV_MS + stepOf(el) * RV_STEP_MS + 150);
  }

  /* Whatever is still hidden, now. Called by the safety timer, on a
     bfcache return, and if the scan itself throws. */
  function revealAll() {
    each(d.querySelectorAll('.sv-rv'), function (el) {
      if (!el.classList.contains('in')) show(el);
    });
  }

  function isCandidate(el) {
    if (el.classList.contains('sv-rv')) return false;
    if (el.closest(OUTSIDE)) return false;
    /* Not inside another candidate: one cascade, not a cascade within
       a cascade. Ancestors come first in document order, so the parent
       already wears the class by the time its children are looked at. */
    if (el.parentElement && el.parentElement.closest('.sv-rv')) return false;
    if (el.querySelector(INSIDE)) return false;
    var cs = w.getComputedStyle(el);
    if (cs.position === 'fixed' || cs.position === 'sticky') return false;
    if (cs.display === 'none') return false;
    var r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return false;
    /* Only what is genuinely below the fold. The entry cascade may be
       holding the page 18px low at scan time; the margin covers that so
       an element at the fold's edge is left on screen. */
    return r.top > w.innerHeight + FOLD_MARGIN;
  }

  function scanReveal(root) {
    if (!hasIO || reduce) return;
    /* This scan's batch, and its own timer: the timer is armed BEFORE
       anything is hidden, so if the loop below throws halfway what it
       hid still comes back — and it reveals this batch only, so the
       load's timer does not cut short a tab switch two seconds later. */
    var batch = [];
    setTimeout(function () {
      each(batch, function (el) {
        if (!el.classList.contains('in')) show(el);
      });
    }, SAFETY_MS);
    try {
      var sel = CANDIDATES + (phone() ? ', ' + PHONE_CANDIDATES : '');
      var parents = [], counts = [];
      var obs = observer();
      each(root.querySelectorAll(sel), function (el) {
        if (!isCandidate(el)) return;
        var p = el.parentNode, k = parents.indexOf(p);
        if (k < 0) { k = parents.length; parents.push(p); counts.push(0); }
        el.style.setProperty('--sv-i', String(Math.min(counts[k], STEP_CAP)));
        counts[k] += 1;
        /* A node htmx just inserted may be mid fade-in; a card about to
           wait below the fold has nothing to fade in for. */
        el.classList.remove('sv-in');
        el.classList.add('sv-rv');
        batch.push(el);
        obs.observe(el);
      });
    } catch (e) {
      revealAll();
    }
  }

  /* ── d. count-up ──────────────────────────────────────────────────── */

  function fmt(n, dec) {
    try {
      return n.toLocaleString('en-US', {
        minimumFractionDigits: dec, maximumFractionDigits: dec });
    } catch (e) {
      return n.toFixed(dec);
    }
  }

  function countUp(el) {
    if (el.__svCounted) return;
    el.__svCounted = true;
    var raw = String(el.getAttribute('data-sv-count') || '').replace(/[,\s]/g, '');
    var target = parseFloat(raw);
    /* Not a number: the server's text stays exactly as rendered. */
    if (!isFinite(target)) return;
    var dec = (raw.split('.')[1] || '').length;
    if (dec > 6) dec = 6;
    if (reduce || typeof w.requestAnimationFrame !== 'function') {
      el.textContent = fmt(target, dec);
      return;
    }
    var t0 = null;
    function frame(ts) {
      if (t0 === null) t0 = ts;
      var p = Math.min(1, (ts - t0) / COUNT_MS);
      var eased = 1 - Math.pow(1 - p, 3);
      if (p < 1) {
        el.textContent = fmt(target * eased, dec);
        w.requestAnimationFrame(frame);
      } else {
        el.textContent = fmt(target, dec);
      }
    }
    el.textContent = fmt(0, dec);
    w.requestAnimationFrame(frame);
  }

  var countIO = null;

  /* A counter inside a card that is still hidden waits for the card:
     numbers rolling behind an opacity of 0 are numbers rolled for
     nobody. show() runs the ones it was holding. */
  function runPendingCounts(el) {
    each(el.querySelectorAll('[data-sv-count]'), function (c) {
      if (c.__svPending) { c.__svPending = false; countUp(c); }
    });
  }

  function scanCounts(root) {
    var els = root.querySelectorAll('[data-sv-count]');
    if (!els.length) return;
    if (!hasIO) { each(els, countUp); return; }
    if (!countIO) {
      countIO = new w.IntersectionObserver(function (entries) {
        each(entries, function (en) {
          if (!en.isIntersecting) return;
          countIO.unobserve(en.target);
          var card = en.target.closest('.sv-rv');
          if (card && !card.classList.contains('in')) {
            en.target.__svPending = true;
            return;
          }
          countUp(en.target);
        });
      }, { threshold: 0 });
    }
    each(els, function (el) { countIO.observe(el); });
  }

  function scan(root) {
    scanReveal(root);
    scanCounts(root);
  }

  /* ── b. htmx and the live regions ─────────────────────────────────── */

  /* One beat of a class, restartable, taken off again so the node goes
     back to its own styles (and a later insertion can play it again). */
  function beat(el, cls, ms) {
    el.classList.remove(cls);
    void el.offsetWidth;                        /* restart the keyframe */
    el.classList.add(cls);
    setTimeout(function () { el.classList.remove(cls); }, ms);
  }

  /* Every node htmx just inserted fades in from the first frame. The
     sheet's .htmx-added rule holds it at 0 until then; the animation
     then owns the opacity across the settle tick that removes that
     class. Not a transition on the node: a .card declares its own list
     without opacity and would appear in one step beside a strip that
     fades. */
  d.addEventListener('htmx:afterSwap', function (e) {
    if (reduce) return;
    var t = e.detail && e.detail.target;
    if (!t || t !== e.target || !t.children) return;
    each(t.children, function (kid) {
      if (kid.classList && kid.classList.contains('htmx-added')) beat(kid, 'sv-in', 400);
    });
  });

  d.addEventListener('htmx:afterSettle', function (e) {
    var t = e.detail && e.detail.target;
    /* afterSettle fires on the target and on every id-matched element
       of the new content; one scan per swap, on the target. */
    if (!t || t !== e.target || !t.querySelectorAll) return;
    var first = !t.hasAttribute('data-sv-motion-seen');
    var byHand = !!(e.detail.requestConfig && e.detail.requestConfig.triggeringEvent);
    t.setAttribute('data-sv-motion-seen', '1');
    if (first || byHand) scan(t);
  });

  d.addEventListener('sv:live-swapped', function (e) {
    if (reduce) return;
    var node = e.detail && e.detail.node;
    if (!node || !node.classList) return;
    beat(node, 'sv-swapped', 400);
  });

  /* ── c. page leave ────────────────────────────────────────────────── */

  var leaveTimer = null;

  function sameOrigin(a) {
    var origin = a.protocol + '//' + a.host;
    return origin === (w.location.protocol + '//' + w.location.host);
  }

  function hasHxAttribute(a) {
    for (var i = 0; i < a.attributes.length; i++) {
      if (a.attributes[i].name.indexOf('hx-') === 0) return true;
    }
    return false;
  }

  function onLinkClick(e) {
    if (reduce || phone()) return;
    if (e.defaultPrevented || e.button !== 0) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (!a) return;
    if (a.target && a.target !== '_self') return;
    if (a.hasAttribute('download')) return;
    var href = a.getAttribute('href') || '';
    if (!href || href.charAt(0) === '#') return;
    if (/^(javascript|mailto|tel):/i.test(href)) return;
    if (!sameOrigin(a)) return;
    /* A hash on the current page scrolls, it does not navigate. */
    if (a.hash && a.pathname === w.location.pathname && a.search === w.location.search) return;
    /* Opted out, part of a form (the logout, PIN and kill-switch
       surfaces), an htmx link, a tab, an overlay control, the theme
       switch (its own transition class overrides ours). */
    if (a.closest('[data-no-fade], form, [hx-boost], [data-sv-overlay], [role="tab"], .theme-toggle-btn')) return;
    if (a.hasAttribute('data-sv-open') || a.hasAttribute('data-sv-close')) return;
    if (hasHxAttribute(a)) return;
    d.body.classList.add('sv-leaving');
    if (leaveTimer) clearTimeout(leaveTimer);
    leaveTimer = setTimeout(function () {
      d.body.classList.remove('sv-leaving');
    }, LEAVE_RESET_MS);
  }

  d.addEventListener('click', onLinkClick);

  w.addEventListener('pageshow', function (e) {
    if (e.persisted) {
      d.body.classList.remove('sv-leaving');
      if (leaveTimer) { clearTimeout(leaveTimer); leaveTimer = null; }
    }
    revealAll();
  });

  /* ── go ───────────────────────────────────────────────────────────── */

  /* Deferred: the DOM is parsed and nothing is painted yet, so what
     the scan hides was never shown. */
  scan(d);
})(window, document);
