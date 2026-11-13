/* sv-frame.js: the frame (UI redo B1 + B2, the desk v2 board, 2026-11-13).
 *
 * The operator approved the desk v2 boards ("amazing work, bravo, I need it
 * fast!!"). This is the frame's own behaviour, and only the frame's:
 *
 *   - the keys: "/" goes to the top bar's "Symbol or command" field from
 *     anywhere outside a field, Esc leaves it; "?" opens the keys sheet,
 *     as the status bar's "? Keys" does;
 *   - the field: Enter goes to a symbol the page knows, else to a page of
 *     the menu by its name, else to the instruments list searched for the
 *     words (its own ?q=); it sends nothing, it only navigates;
 *   - the menu: a section head folds its rows, his choice kept per browser
 *     (storage read in try/catch; the page's own section is always open);
 *     a folded section with something unseen shows the dot;
 *   - the dock: Signals opens and shuts the rail (as the rail's toggle did),
 *     Council, Activity and Ask Sauron open their own panels through their
 *     own doors; each button says whether its panel is open, and the
 *     Council's and Activity's counts are mirrored from their own badges;
 *   - the status bar: the Horde's cell opens the Horde (as h does), "N
 *     more" opens the cells that wait behind it, upward, closed by Esc or a
 *     click outside;
 *   - the fit (review of the desk v2 build, 2026-11-13): the top bar keeps
 *     the page's name whole and the status bar keeps every cell on its line
 *     by letting words go one step at a time, only as far as each needs;
 *     a wide bar takes back cells from "N more" while they fit;
 *   - the band's dots: each price's freshness, read from the one price
 *     (sv-venue.js's own state, never a second painter);
 *   - the Eye: the feed's state, the market shut, the lock.
 *
 * "/" and "?" do nothing while a dialog or the lock holds the page: a
 * money dialog keeps its focus.
 *
 * Display only: no fetch, no socket, no order, no broker, no model.
 */
(function (w, d) {
  'use strict';

  var FOLD_KEY = 'sv_nav_folds';
  var RAIL_KEY = 'sauron_signals_rail';

  function load(key) { try { return w.localStorage.getItem(key); } catch (e) { return null; } }
  function store(key, val) { try { w.localStorage.setItem(key, val); } catch (e) { /* the page keeps it */ } }
  function typing(t) {
    return !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
  }

  /* ── the command field ───────────────────────────────────────────── */
  var form = d.querySelector('form.sv-cmd');
  var field = d.getElementById('svCmd');

  function knownSymbols() {
    var seen = {};
    Array.prototype.forEach.call(d.querySelectorAll('[data-symbol], [data-q]'), function (el) {
      var s = (el.getAttribute('data-symbol') || el.getAttribute('data-q') || '').trim().toUpperCase();
      if (/^[A-Z0-9][A-Z0-9._\-]{0,23}$/.test(s)) seen[s] = 1;
    });
    return seen;
  }

  function pageFor(words) {
    var want = words.toLowerCase().replace(/\s+/g, ' ').trim();
    if (!want) return null;
    var rows = d.querySelectorAll('#mainSidebar .sidebar-nav a.nav-link');
    var exact = null, prefix = null;
    Array.prototype.forEach.call(rows, function (a) {
      var label = a.querySelector('.label-text');
      var name = (label ? label.textContent : a.textContent).toLowerCase().replace(/\s+/g, ' ').trim();
      if (!exact && name === want) exact = a;
      if (!prefix && name.indexOf(want) === 0) prefix = a;
    });
    var hit = exact || prefix;
    return hit ? hit.getAttribute('href') : null;
  }

  /* Where Enter goes for these words: a symbol the page knows, a page of
     the menu, else the instruments list searched for them. */
  function target(value) {
    var v = String(value || '').trim();
    if (!v) return null;
    var sym = v.toUpperCase().replace(/\s+/g, '');
    if (knownSymbols()[sym] && form) {
      var url = form.getAttribute('data-sv-sym-url') || '/instruments/SVSYM/';
      return url.replace('SVSYM', encodeURIComponent(sym));
    }
    var page = pageFor(v);
    if (page) return page;
    var action = (form && form.getAttribute('action')) || '/instruments/';
    return action + '?q=' + encodeURIComponent(v);
  }

  if (form && field) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var to = target(field.value);
      if (to) w.location.assign(to);
    });
    field.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); field.value = ''; field.blur(); }
    });
    /* Folded to its "/" key, the field opens where it is pressed. */
    form.addEventListener('mousedown', function (e) {
      if (e.target !== field) { e.preventDefault(); field.focus(); }
    });
  }

  /* ── the keys sheet ──────────────────────────────────────────────── */
  function openKeys() {
    var sheet = d.getElementById('kbdModalOverlay');
    if (sheet) sheet.classList.add('open');
  }

  /* A dialog, a money dialog above all, or the lock holds the page: the
     frame's keys wait, so the focus never leaves it. */
  var pinLocked = false;
  function held() {
    return pinLocked || !!d.querySelector('.sv-dialog.is-open') || d.body.classList.contains('sv-scroll-locked');
  }

  d.addEventListener('keydown', function (e) {
    if (e.defaultPrevented || typing(e.target)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (held()) return;
    if (e.key === '/' && field) {
      e.preventDefault();
      field.focus();
      try { field.select(); } catch (err) { /* nothing to select */ }
      return;
    }
    if (e.key === '?') { e.preventDefault(); openKeys(); }
  });

  /* ── the menu: sections fold ─────────────────────────────────────── */
  function rowsOf(head) {
    var out = [], n = head.nextElementSibling;
    while (n && !n.classList.contains('nav-section')) {
      if (n.classList.contains('nav-link')) out.push(n);
      n = n.nextElementSibling;
    }
    return out;
  }
  function folds() {
    try { return JSON.parse(load(FOLD_KEY) || '{}') || {}; } catch (e) { return {}; }
  }
  function setFold(head, folded) {
    head.classList.toggle('is-folded', folded);
    var b = head.querySelector('.nav-fold');
    if (b) b.setAttribute('aria-expanded', folded ? 'false' : 'true');
    rowsOf(head).forEach(function (r) { r.classList.toggle('nav-folded', folded); });
    markUnseen(head);
  }
  function markUnseen(head) {
    var any = rowsOf(head).some(function (r) { return !!r.querySelector('.nav-dot'); });
    head.classList.toggle('has-unseen', any && head.classList.contains('is-folded'));
  }
  var heads = Array.prototype.slice.call(d.querySelectorAll('#mainSidebar .nav-section[data-nav-sec]'));
  (function applyFolds() {
    var saved = folds();
    heads.forEach(function (head) {
      var key = head.getAttribute('data-nav-sec');
      var folded = Object.prototype.hasOwnProperty.call(saved, key) ? !!saved[key] : !head.hasAttribute('data-nav-open');
      if (rowsOf(head).some(function (r) { return r.classList.contains('active'); })) folded = false;
      setFold(head, folded);
    });
  })();
  heads.forEach(function (head) {
    var b = head.querySelector('.nav-fold');
    if (!b) return;
    b.addEventListener('click', function () {
      var folded = !head.classList.contains('is-folded');
      setFold(head, folded);
      var saved = folds();
      saved[head.getAttribute('data-nav-sec')] = folded;
      store(FOLD_KEY, JSON.stringify(saved));
    });
  });
  /* The nav's dots (sv-nav-activity.js) land on rows: a folded section says
     it holds one. */
  d.addEventListener('sv:nav-activity', function () {
    setTimeout(function () { heads.forEach(markUnseen); }, 0);
  });

  /* ── the dock ────────────────────────────────────────────────────── */
  var rail = d.getElementById('signalsRail');
  function dockBtn(name) { return d.querySelector('.sv-dock [data-sv-dock="' + name + '"]'); }
  function setOpen(btn, open) {
    if (!btn) return;
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    btn.classList.toggle('is-open', !!open);
  }
  function railOpen() { return !!(rail && rail.classList.contains('open')); }
  function syncRail() { setOpen(dockBtn('signals'), railOpen()); }
  if (rail && w.MutationObserver) {
    new MutationObserver(syncRail).observe(rail, { attributes: true, attributeFilter: ['class'] });
  }
  syncRail();

  /* A panel's own door, its own open state, its own badge: mirrored. */
  var DOORS = {
    council: { tab: 'svCouncilBandTab', badge: 'svCouncilBandBadge' },
    activity: { tab: 'svActivityTab', badge: 'svActivityBadge' }
  };
  Object.keys(DOORS).forEach(function (name) {
    var door = DOORS[name], tab = d.getElementById(door.tab), btn = dockBtn(name);
    if (!tab || !btn) return;
    var n = btn.querySelector('.sv-dock-n');
    function sync() {
      setOpen(btn, tab.getAttribute('aria-expanded') === 'true');
      var badge = d.getElementById(door.badge);
      if (n && badge) {
        var shown = !badge.hidden && badge.textContent.trim() && badge.textContent.trim() !== '0';
        n.textContent = shown ? badge.textContent.trim() : '';
        n.hidden = !shown;
      }
    }
    if (w.MutationObserver) {
      var mo = new MutationObserver(sync);
      mo.observe(tab, { attributes: true, attributeFilter: ['aria-expanded'] });
      var badge = d.getElementById(door.badge);
      if (badge) mo.observe(badge, { attributes: true, childList: true, characterData: true, subtree: true });
    }
    sync();
  });

  var chat = d.getElementById('seChatPanel');
  function syncAsk() { setOpen(dockBtn('ask'), !!(chat && chat.classList.contains('open'))); }
  if (chat && w.MutationObserver) {
    new MutationObserver(syncAsk).observe(chat, { attributes: true, attributeFilter: ['class'] });
  }
  syncAsk();

  d.addEventListener('click', function (e) {
    var btn = e.target && e.target.closest ? e.target.closest('.sv-dock [data-sv-dock]') : null;
    if (!btn) return;
    var name = btn.getAttribute('data-sv-dock');
    if (name === 'signals') {
      if (!rail) return;
      var open = rail.classList.toggle('open');
      store(RAIL_KEY, open ? 'open' : 'closed');
      return;
    }
    if (DOORS[name]) {
      var tab = d.getElementById(DOORS[name].tab);
      if (tab) tab.click();
      return;
    }
    if (name === 'ask') {
      if (chat && chat.classList.contains('open')) {
        var close = chat.querySelector('.se-chat-close, [data-se-close], #seChatClose');
        if (close) { close.click(); return; }
      }
      if (w.openEyeWithQuery) w.openEyeWithQuery('');
      else { var fab = d.getElementById('seEyeFab'); if (fab) fab.click(); }
    }
  });

  /* ── the status bar ──────────────────────────────────────────────── */
  var hordeCell = d.getElementById('svHordeCell');
  var hordePanel = d.getElementById('svHordePanel');
  var hordeTab = d.getElementById('svHordeTab');
  if (hordeCell) {
    hordeCell.addEventListener('click', function () {
      if (w.SVHorde && w.SVHorde.toggle) w.SVHorde.toggle('click');
      else if (hordeTab) hordeTab.click();
    });
    var syncHorde = function () {
      var open = hordeTab ? hordeTab.getAttribute('aria-expanded') === 'true'
                          : !!(hordePanel && !hordePanel.hasAttribute('inert'));
      hordeCell.setAttribute('aria-expanded', open ? 'true' : 'false');
    };
    if (w.MutationObserver) {
      if (hordeTab) new MutationObserver(syncHorde).observe(hordeTab, { attributes: true, attributeFilter: ['aria-expanded'] });
      if (hordePanel) new MutationObserver(syncHorde).observe(hordePanel, { attributes: true, attributeFilter: ['inert'] });
    }
  }

  var moreBtn = d.getElementById('svMoreBtn');
  var morePop = d.getElementById('svMorePop');
  function setMore(open) {
    if (!moreBtn || !morePop) return;
    morePop.hidden = !open;
    moreBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  if (moreBtn && morePop) {
    moreBtn.addEventListener('click', function (e) {
      e.preventDefault();
      setMore(morePop.hidden);
    });
    d.addEventListener('click', function (e) {
      if (morePop.hidden) return;
      var t = e.target;
      if (moreBtn.contains(t) || morePop.contains(t)) return;
      if (t && t.closest && t.closest('.ip-dropdown')) return;
      setMore(false);
    });
    d.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !morePop.hidden) setMore(false);
    });
  }

  /* The bar keeps every cell on one line, whatever it holds (a state word,
     an alarm, a six-figure book, a stale mark): where its content would
     pass the Eye, the words go one step at a time and only as far as
     needed (.sv-bar-t1 to .sv-bar-t6, sv-frame.css). Where it has room to
     spare (a wide screen), it takes back the cells "N more" holds, in
     order, while they fit, each at the width it took (POSITIONS stays
     there: the Horde stands in its place). Measured on load, on a resize,
     once the faces are in and when the sweep rewrites a cell; never while
     the pointer is on the bar, so a cell never moves under the hand. */
  var wrap = d.getElementById('infoPanelWrap');
  var barRow = wrap && wrap.querySelector('.info-panel-bar');
  var moreBox = barRow && barRow.querySelector('.sv-more');
  var STEPS = 6, fitTimer = null, onBar = false, fitting = false, barMo = null;
  var waiting = [];
  if (morePop) {
    Array.prototype.forEach.call(morePop.children, function (c) {
      if (c.classList.contains('ip-cat')) waiting.push(c);
    });
  }
  function cellName(c) {
    var l = c.querySelector('.ip-label');
    return l ? l.textContent.replace(/\s+/g, ' ').trim() : '';
  }
  function title(word) { return word.charAt(0) + word.slice(1).toLowerCase(); }
  function sayMore() {
    var pop = morePop, btn = moreBtn;
    if (!pop || !btn) return;
    var left = waiting.filter(function (c) { return c.parentNode === pop; });
    var n = left.length, label = btn.querySelector('.sv-more-n');
    if (label) label.textContent = n + ' more';
    btn.setAttribute('aria-label', n + ' more cell' + (n === 1 ? '' : 's') + ': '
      + left.map(function (c) { return title(cellName(c)); }).join(', '));
    if (moreBox) moreBox.hidden = !n;
  }
  function overflowing() {
    var last = barRow.lastElementChild;
    var room = wrap.getBoundingClientRect().right - 44;
    return !!last && last.getBoundingClientRect().right > room + 0.5;
  }
  function fitBar() {
    if (!wrap || !barRow || onBar || fitting) return;
    fitting = true;
    try {
      var pop = morePop;
      /* Start whole: every cell back where it waits, every word shown. */
      waiting.forEach(function (c) {
        if (pop && c.parentNode !== pop) { c.style.minWidth = ''; pop.appendChild(c); }
      });
      for (var i = 1; i <= STEPS; i++) wrap.classList.remove('sv-bar-t' + i);
      wrap.classList.remove('sv-bar-tight');
      var step = 0;
      while (step < STEPS && overflowing()) { step++; wrap.classList.add('sv-bar-t' + step); }
      if (step) wrap.classList.add('sv-bar-tight');
      wrap.setAttribute('data-sv-bar-step', String(step));
      /* Room to spare: the cells come back from "N more" while they fit. */
      if (!step && pop && moreBox && w.innerWidth >= 1680) {
        for (var k = 0; k < waiting.length; k++) {
          var c = waiting[k];
          if (c.querySelector('#ipPositionsCount')) continue;
          barRow.insertBefore(c, moreBox);
          if (overflowing()) { pop.appendChild(c); break; }
          c.style.minWidth = Math.ceil(c.getBoundingClientRect().width) + 'px';
        }
      }
      /* The cells keep the order they wait in. */
      if (pop) {
        var inPop = waiting.filter(function (c) { return c.parentNode === pop; });
        var now = Array.prototype.filter.call(pop.children, function (c) { return inPop.indexOf(c) !== -1; });
        if (now.some(function (c, i) { return c !== inPop[i]; })) inPop.forEach(function (c) { pop.appendChild(c); });
      }
      sayMore();
    } finally {
      fitting = false;
      /* Its own moves are not news: only the sweep's are. */
      if (barMo) barMo.takeRecords();
    }
  }
  function fitSoon() { clearTimeout(fitTimer); fitTimer = setTimeout(fitBar, 120); }
  if (wrap) {
    wrap.addEventListener('mouseenter', function () { onBar = true; });
    wrap.addEventListener('mouseleave', function () { onBar = false; fitSoon(); });
    w.addEventListener('resize', fitSoon);
    if (w.MutationObserver && barRow) {
      barMo = new MutationObserver(function () { if (!fitting) fitSoon(); });
      barMo.observe(barRow, { childList: true, subtree: true, characterData: true });
    }
    fitBar();
  }

  /* ── the top bar: the page's name, whole ──────────────────────────── */
  /* The title never shrinks; the field gives way to its 150 px by itself.
     Past that, one step at a time and only as far as needed (sv-frame.css
     .sv-fit-2 to .sv-fit-7): the title's words after its " · ", the field
     folds to its "/" key, the word "sessions", the operator's name, two
     points of the title's size; the last step, which no page should need,
     lets the title end in an ellipsis. Whatever is let go is still the
     title's tooltip and the controls' names. */
  var top = d.querySelector('.topbar');
  var ttl = top && top.querySelector('.topbar-title');
  var topRight = top && top.querySelector('.topbar-right');
  var TOP_STEPS = 7, topTimer = null, topFitting = false;
  function topOver() {
    var r = top.getBoundingClientRect();
    if (ttl.scrollWidth > ttl.clientWidth + 0.5) return true;
    return !!topRight && topRight.getBoundingClientRect().right > r.right - 16 + 0.5;
  }
  function fitTop() {
    if (!top || !ttl || topFitting) return;
    if (form && form.contains(d.activeElement)) return;   /* never under his typing */
    topFitting = true;
    try {
      for (var i = 2; i <= TOP_STEPS; i++) top.classList.remove('sv-fit-' + i);
      var step = 1;
      while (step < TOP_STEPS && topOver()) { step++; top.classList.add('sv-fit-' + step); }
      top.setAttribute('data-sv-fit', String(step));
      var whole = ttl.textContent.replace(/\s+/g, ' ').trim();
      if (step >= 2 && ttl.querySelector('.sv-ttl-sub')) ttl.title = whole;
      else if (ttl.scrollWidth > ttl.clientWidth + 0.5) ttl.title = whole;
      else ttl.removeAttribute('title');
    } finally {
      topFitting = false;
    }
  }
  function topSoon() { clearTimeout(topTimer); topTimer = setTimeout(fitTop, 120); }
  if (top && ttl) {
    w.addEventListener('resize', topSoon);
    if (field) field.addEventListener('blur', topSoon);
    if (w.MutationObserver && topRight) {
      new MutationObserver(function (list) {
        if (topFitting) return;
        for (var i = 0; i < list.length; i++) {
          var t = list[i].target, el = t.nodeType === 1 ? t : t.parentNode;
          if (!el || !el.closest || !el.closest('#clock')) { topSoon(); return; }
        }
      }).observe(topRight, { childList: true, subtree: true, characterData: true });
    }
    fitTop();
  }
  /* The faces arrive after the first layout: measured again once they are in. */
  if (d.fonts && d.fonts.ready) d.fonts.ready.then(function () { fitTop(); fitBar(); });
  w.SVFrameFit = { top: fitTop, bar: fitBar };

  d.addEventListener('click', function (e) {
    var keys = e.target && e.target.closest ? e.target.closest('[data-sv-cell="keys"]') : null;
    if (keys) { e.preventDefault(); openKeys(); }
  });

  /* ── the band's dots: each price's freshness ─────────────────────── */
  /* The one price's own state (sv-venue.js, SVVenue.stateAt): live within
     its live bound; recent, delayed by less than a quarter of an hour;
     stale, delayed by more; closed, its market shut; no dot without a
     price. Read when the painter paints and every 15 s; never painted by
     a second hand. */
  var STALE_MS = 15 * 60 * 1000;
  function freshness() {
    var V = w.SVVenue;
    if (!V || !V.get || !V.stateAt) return;
    var now = V.now ? V.now() : Date.now();
    Array.prototype.forEach.call(d.querySelectorAll('.sv-band .dh-item[data-symbol]'), function (it) {
      var dot = it.querySelector('.dh-dot');
      if (!dot) return;
      var p = V.get(it.getAttribute('data-symbol'));
      var st = p ? V.stateAt(p, now) : 'none';
      var f = st === 'live' ? 'live' : st === 'shut' ? 'closed'
            : st === 'delayed' ? ((p && p.at && now - p.at > STALE_MS) ? 'stale' : 'recent') : '';
      if (f) dot.setAttribute('data-sv-fresh', f); else dot.removeAttribute('data-sv-fresh');
      var words = { live: 'live', recent: 'delayed', stale: 'stale', closed: 'market closed' }[f];
      if (words) dot.setAttribute('title', words); else dot.removeAttribute('title');
    });
  }
  if (w.SVVenue && w.SVVenue.onPaint) w.SVVenue.onPaint(function () { setTimeout(freshness, 0); });
  d.addEventListener('sv:live-swapped', function () { setTimeout(freshness, 0); });
  setInterval(freshness, 15000);
  freshness();

  /* ── the Eye, the system's heartbeat ─────────────────────────────── */
  /* The brand's Eye says what the feed says (the desk v2 board, Twist2 "Le
     battement du système"): alive, it breathes (the magic layer's breath)
     and beats once each time the feed answers alive; with no news it greys
     and stills; under the lock it shuts. It reads the top bar's own feed
     pill, which polls the live health; it asks nothing itself. */
  var eye = d.querySelector('.sidebar-brand');
  var eyeWrap = d.querySelector('.sidebar-brand .brand-eye-wrap');
  var feedDot = d.querySelector('#liveStatusPill .lsp-dot');
  var openCount = d.querySelector('[data-ex-open-count]');
  var beatTimer = null, EYE_KEY = 'sv_eye_last';
  /* Until the feed answers on this page, the Eye says what it last said
     in this session (no grey blink on every page); the session's first
     page, nothing heard yet, is quiet. */
  function lastSaid() { try { return w.sessionStorage.getItem(EYE_KEY); } catch (e) { return null; } }
  function say(st) { try { w.sessionStorage.setItem(EYE_KEY, st); } catch (e) { /* the page keeps it */ } }
  function eyeState() {
    if (!eye) return;
    if (eye.getAttribute('data-sv-eye') === 'locked') return;
    var cls = feedDot ? feedDot.className : '';
    var state = /\blsp-green\b/.test(cls) ? 'live' : /\blsp-flat\b/.test(cls) ? 'unknown' : 'quiet';
    /* The market shut (no session open): the lids lower. */
    if (state !== 'unknown' && openCount && openCount.textContent.trim() === '0') state = 'closed';
    if (state === 'unknown') {
      var was = lastSaid();
      if (was === 'live' || was === 'quiet' || was === 'closed') state = was;
    } else {
      say(state);
    }
    eye.setAttribute('data-sv-eye', state);
    if (state === 'live' && eyeWrap) {
      eyeWrap.classList.remove('sv-beat');
      void eyeWrap.offsetWidth;
      eyeWrap.classList.add('sv-beat');
      clearTimeout(beatTimer);
      beatTimer = setTimeout(function () { eyeWrap.classList.remove('sv-beat'); }, 900);
    }
  }
  if (feedDot && w.MutationObserver) {
    new MutationObserver(eyeState).observe(feedDot, { attributes: true, attributeFilter: ['class'] });
  }
  if (openCount && w.MutationObserver) {
    new MutationObserver(eyeState).observe(openCount, { childList: true, characterData: true, subtree: true });
  }
  d.addEventListener('sv:pin-locked', function () { pinLocked = true; if (eye) eye.setAttribute('data-sv-eye', 'locked'); });
  d.addEventListener('sv:pin-unlocked', function () { pinLocked = false; if (eye) { eye.removeAttribute('data-sv-eye'); eyeState(); } });
  eyeState();

  w.SVFrame = { target: target, openKeys: openKeys, more: setMore };
})(window, document);
