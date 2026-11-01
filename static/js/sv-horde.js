/* The Horde — a seat for every open position (2026-10-08).
 *
 * templates/_partials/the_horde.html draws a tab on the cockpit strip's own
 * line and a sheet that opens upward from it (static/css/sv-horde.css);
 * this file opens it, sizes it and paints it from GET /api/horde/ (the
 * root's data-horde-url; dashboard/views_horde.py over dashboard/horde.py).
 *
 *   - THE TAB toggles the sheet; so do the `h` key (base.html's global
 *     handler calls window.SVHorde.toggle) and Escape from inside it. The
 *     choice and the height are remembered on a wide screen only.
 *   - SIZE: the top edge is a window splitter (pointer drag, arrow keys,
 *     Page keys, Home/End, Enter). PEEK, HALF and FULL are measured from
 *     the furniture actually on screen, never from constants. A phone
 *     snaps to a third, two thirds or the full room above the bottom nav.
 *   - CADENCE: collapsed, nothing polls. The tab copies the strip's own
 *     position count for free (#ipPositionsCount) and reads one cached
 *     answer after load, when that count moves, on a book event and when
 *     the page comes back after five minutes. Open and visible, the board
 *     is read on the strip's clock (every 20 s with the socket down, every
 *     60 s with it up) and 800 ms after a fill, a close or a refused close.
 *     A seat's dossier is never on the timer: it is read when it opens,
 *     when its seat's facts move (the board's `rev`), when its levels are
 *     saved, and on its own button.
 *   - RULE 1: nothing here sends an order. A money command is a button the
 *     platform's EXISTING flows already answer (the close dialog, the level
 *     editor, the TAKE TRADE ticket), each with its own confirmation; the
 *     level editor and the close advice are loaded once, lazily.
 *   - Everything is built with textContent. Every static sentence comes
 *     from the partial's word template (W), every data sentence from the
 *     server; an unmeasured figure is the em dash, never a zero.
 */
(function () {
  'use strict';
  var root = document.getElementById('svHorde');
  if (!root) return;

  var URL_ = root.getAttribute('data-horde-url') || '';
  var TICK_MS = 20000;
  var UP_EVERY = 3;
  var EVENT_DEBOUNCE_MS = 800;
  var TAB_MIN_GAP_MS = 10000;
  var TAB_STALE_MS = 300000;
  var SEAT_LOAD_TIMEOUT_MS = 5000;
  var SAY_GAP_MS = 10000;
  var SNAP_PULL_PX = 24;
  var FLING_PX_PER_MS = 0.5;
  var SHUT_MAX = 50;
  var DOSSIER_ROOM_PX = 440;
  var OPEN_KEY = 'sauron_horde_open';
  var H_KEY = 'sauron_horde_h';
  var LENS_KEY = 'sauron_horde_lens';
  var SHUT_KEY = 'sauron_horde_shut';
  var SNAP_KEY = 'sauron_horde_snap_phone';
  var LIMITS_KEY = 'sauron_horde_limits';
  /* The tab's tiers, widest first: what each one shows is the stylesheet's
     (sv-horde.css); which one is used is the widest whose content fits the
     tab's room, measured, never guessed (2026-10-16: every segment of the
     tab ended in an ellipsis at 1380). */
  var TAB_TIERS = ['hd-t-l', 'hd-t-m', 'hd-t-s'];
  var BOOK_KINDS = { fill_open: 1, fill_close: 1, close_pending: 1 };
  var GLYPHS = { alarm: '!', order: '◇', watch: '▲', unheld: '○', calm: '●' };
  var DASH = '—';
  var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var phoneMq = window.matchMedia ? window.matchMedia('(max-width: 768px)') : null;

  var tab = document.getElementById('svHordeTab');
  var panel = document.getElementById('svHordePanel');
  var grip = document.getElementById('svHordeGrip');
  var head = document.getElementById('svHordeHead');
  var title = document.getElementById('svHordeTitle');
  var seatsEl = document.getElementById('svHordeSeats');
  var sayEl = document.getElementById('svHordeSay');
  var tableEl = document.getElementById('svHordeTable');
  var sumEl = document.getElementById('svHordeSum');
  var notesEl = document.getElementById('svHordeNotes');
  var stateEl = document.getElementById('svHordeState');
  var bandsEl = document.getElementById('svHordeBands');
  var seatBox = document.getElementById('svHordeSeat');
  var stampEl = document.getElementById('svHordeStamp');
  var dotEl = document.getElementById('svHordeDot');
  var bookEl = document.getElementById('svHordeBook');
  var headCountEl = document.getElementById('svHordeCount');
  var closeBtn = document.getElementById('svHordeClose');
  if (!tab || !panel || !grip || !URL_) return;
  var lensBtns = root.querySelectorAll('.hd-lens-btn');
  var segs = {
    alarms: tab.querySelector('.hd-tab-alarms'), real: tab.querySelector('.hd-tab-real'),
    r: tab.querySelector('.hd-tab-r'), risk: tab.querySelector('.hd-tab-risk'),
    flag: tab.querySelector('.hd-tab-flag'), moves: tab.querySelector('.hd-tab-moves')
  };

  /* ── words ───────────────────────────────────────────────────────── */
  var WORDS = {};
  (function () {
    var tpl = document.getElementById('svHordeWords');
    var src = tpl && (tpl.content || tpl);
    if (!src || !src.querySelectorAll) return;
    var spans = src.querySelectorAll('[data-w]');
    for (var i = 0; i < spans.length; i++) {
      WORDS[spans[i].getAttribute('data-w')] = spans[i].textContent;
    }
  })();
  function W(key) { return WORDS[key] || ''; }
  function fill(text, map) {
    return String(text || '').replace(/\{(\w+)\}/g, function (m, k) {
      return (map && map[k] !== undefined && map[k] !== null) ? String(map[k]) : m;
    });
  }

  /* ── the DOM, by hand ────────────────────────────────────────────── */
  /* A middle dot never opens a line (2026-10-16: "· 25,840.55, the broker
     account", "· at the stops 27.60"): in running text the space before
     it is a no-break space, so a wrapped line ends with the dot; between
     the boxes of a wrapping row (joinDots) the dot ends the box before it. */
  function dots(t) {
    return String(t === undefined || t === null ? '' : t).replace(/ \u00b7/g, '\u00a0\u00b7');
  }
  function txt(t) { return document.createTextNode(dots(t)); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null && text !== '') n.textContent = dots(text);
    return n;
  }
  function joinDots(parent, nodes) {
    nodes = nodes.filter(Boolean);
    nodes.forEach(function (n, i) {
      if (i === nodes.length - 1) { add(parent, n); return; }
      var unit = add(parent, el('span', 'hd-unit'));
      add(unit, n);
      add(unit, el('span', 'hd-sep', '\u00a0\u00b7'));
    });
  }
  function add(parent, child) { if (parent && child) parent.appendChild(child); return child; }
  function clear(n) { while (n && n.firstChild) n.removeChild(n.firstChild); }
  function dash(v) { return (v === null || v === undefined || v === '') ? DASH : String(v); }
  function button(cls, text, onClick) {
    var b = el('button', cls, text);
    b.type = 'button';
    if (onClick) b.addEventListener('click', onClick);
    return b;
  }
  function link(cls, text, href) {
    var a = el('a', cls, text);
    a.setAttribute('href', safeHref(href));
    return a;
  }
  function safeHref(u) {
    u = String(u || '');
    return (u.charAt(0) === '/' && u.charAt(1) !== '/') ? u : '#';
  }
  /* Every clock is UTC, the platform's own (the topbar, the drawer, the
     server's sentences). */
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function clock(ms) {
    if (!ms) return DASH;
    var d = new Date(ms);
    return pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ':' + pad(d.getUTCSeconds());
  }
  function isoClock(iso) {
    var t = Date.parse(iso || '');
    return isNaN(t) ? DASH : clock(t);
  }
  function stamp(iso) {
    var t = Date.parse(iso || '');
    if (isNaN(t)) return '';
    var d = new Date(t), now = new Date();
    var hm = pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes());
    if (d.getUTCFullYear() === now.getUTCFullYear() && d.getUTCMonth() === now.getUTCMonth()
        && d.getUTCDate() === now.getUTCDate()) return hm;
    return pad(d.getUTCDate()) + ' ' + MONTHS[d.getUTCMonth()] + ' ' + hm;
  }
  function ageWords(ms) {
    var s = Math.max(0, Math.round(ms / 1000));
    if (s < 90) return s + ' s';
    if (s < 5400) return Math.round(s / 60) + ' min';
    return Math.round(s / 3600) + ' h';
  }
  function toneCls(t) { return t === 'up' ? 'hd-tone-up' : t === 'down' ? 'hd-tone-down' : ''; }

  /* ── state, and what a reader may keep (a private window may refuse) ── */
  var state = {
    open: false, phone: false, ctl: null, timer: null, ticks: 0,
    inflight: false, again: false, stopped: false,
    board: null, lastGoodAt: 0, lastTabAt: 0,
    h: 0, lastGoodH: 0, maxH: 0, minH: 0, frac: null, snapPhone: 2, dragH: null,
    lens: 'all', tone: '', shut: {}, tabAria: '',
    seatKey: null, seatRev: null, seatData: null, seatGone: false, seatFrom: null, seatFocus: false,
    lvlFailed: false, moves: 0, lastAlarms: null, lastSayAt: 0,
    evTimer: null, persistTimer: null, prev: {}, limitsOpen: load(LIMITS_KEY) === '1',
    grownFrom: null, grownTo: null,
    /* Per band: is its "What holds this class today" open (kept across
       the board's repaints, never stored). */
    today: {},
    seatN: (function () {
      var n = parseInt((seatsEl && seatsEl.textContent) || '', 10);
      return isFinite(n) ? n : null;
    })()
  };
  function load(key) { try { return window.localStorage.getItem(key); } catch (e) { return null; } }
  function store(key, val) { try { window.localStorage.setItem(key, String(val)); } catch (e) { /* lasts the page */ } }
  (function () {
    var lens = load(LENS_KEY);
    if (lens && /^(all|live|demo|paper|none)$/.test(lens)) state.lens = lens;
    var shut = [];
    try { shut = JSON.parse(load(SHUT_KEY) || '[]') || []; } catch (e) { shut = []; }
    if (Array.isArray(shut)) shut.slice(0, SHUT_MAX).forEach(function (k) { state.shut[String(k)] = 1; });
  })();

  /* ── measured, not calculated ────────────────────────────────────── */
  function rect(sel) {
    var n = document.querySelector(sel);
    if (!n) return null;
    var cs = window.getComputedStyle(n);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return null;
    var r = n.getBoundingClientRect();
    if (r.bottom <= 0 || r.top >= window.innerHeight || r.width <= 0 || r.height <= 0) return null;
    return r;
  }
  function px(v) { var n = parseFloat(v); return isFinite(n) ? n : 0; }
  function measure() {
    var vh = window.innerHeight;
    var top = 0;
    ['.topbar', '.ticker-bar', '.data-headband'].forEach(function (sel) {
      var r = rect(sel);
      if (r && r.top < vh * 0.5) top = Math.max(top, r.bottom);
    });
    if (state.phone) {
      /* The bottom nav's height is --sv-bottom-chrome, a calc() with the
         safe area in it: a custom property reads back unresolved, so the
         sheet's own resolved `bottom` (which IS that variable) is read. */
      var chrome = px(window.getComputedStyle(panel).bottom);
      state.maxH = Math.max(120, Math.round(vh - top - chrome - 8));
      state.minH = Math.round(state.maxH / 3);
      return;
    }
    var stripTop = vh;
    var strip = document.querySelector('.info-panel-wrap');
    if (strip && !strip.classList.contains('minimized')) {
      var sr = rect('.info-panel-wrap');
      if (sr) stripTop = sr.top;
    }
    /* FULL meets the header's bottom edge: no strip of the page shows
       between them, and the tab, which would sit under the header there,
       tucks away (applyHeight) while the head says what it said. */
    state.maxH = Math.max(120, Math.round(stripTop - top));
    state.minH = Math.min(196, state.maxH);
    state.stripTop = stripTop;
    state.headerBottom = top;
  }
  /* The page's side-panel toggles (sauron.css .sidebar-toggle-btn,
     .rail-toggle-btn: 28x56, centred on the viewport, one rung over the
     sheet) stood on the open sheet's head (round 2: at 1100 and with the
     activity drawer open). While the sheet is open they move up into the
     page above it when it has their room; else they stand in the body's
     side gutter, under the head, where nothing is written. Their own
     z-index is kept, so they stay reachable; closed, they go back. */
  var TOGGLE_HALF = 28, TOGGLE_GAP = 8;
  function placeToggles() {
    var b = document.body;
    if (!b) return;
    if (!state.open || state.phone || !state.stripTop) {
      b.style.removeProperty('--hd-toggle-y');
      return;
    }
    var vh = window.innerHeight;
    var sheetTop = state.stripTop - state.h;
    var y = vh / 2;
    if (y + TOGGLE_HALF + TOGGLE_GAP > sheetTop) {
      if (sheetTop - (state.headerBottom || 0) >= 2 * (TOGGLE_HALF + TOGGLE_GAP)) {
        y = sheetTop - TOGGLE_HALF - TOGGLE_GAP;
      } else {
        var head = document.getElementById('svHordeHead');
        var hb = head ? head.getBoundingClientRect().bottom : sheetTop;
        y = Math.max(y, hb + TOGGLE_HALF + TOGGLE_GAP);
      }
    }
    b.style.setProperty('--hd-toggle-y', Math.round(y) + 'px');
  }
  /* The tab tucks away while the sheet is open, at every height: the
     head's own count, alarms and REAL pill stand in for it (sv-horde.css
     .hd-tab-tucked), and the head's snaps and x close it. FULL tucked it
     first (it would sit under the header); round 2 found the open tab
     riding the sheet's top cut through the page's own lines (the account
     card's "LIVE 25,840.55 USD" with the activity drawer open, "PORTFOLIO
     VALUE" at 1100). */
  function tuckTab() {
    var tuck = state.open && !state.phone;
    if (tuck !== root.classList.contains('hd-tab-tucked')) root.classList.toggle('hd-tab-tucked', tuck);
    /* A hidden tab never keeps the focus: it goes to the head's title. */
    if (tuck && document.activeElement === tab) {
      try { title.focus({ preventScroll: true }); } catch (e) { /* an old engine */ }
    }
  }
  /* HALF shows at least the first row of seat cards whole (2026-10-16:
     at 1100x800 no card showed at HALF): the height that row needs is
     measured from the cards on screen, and HALF is the larger of half the
     room and that, below FULL. Nothing on screen yet: half the room. */
  function firstRowNeed() {
    if (!bodyEl || !state.open || !bandsEl) return 0;
    var cards = bandsEl.querySelectorAll('.hd-seat');
    var b = bodyEl.getBoundingClientRect();
    for (var i = 0; i < cards.length; i++) {
      var c = cards[i].getBoundingClientRect();
      if (!c.height) continue;
      return Math.ceil((state.h - bodyEl.clientHeight) + (c.bottom - b.top + bodyEl.scrollTop) + 8);
    }
    return 0;
  }
  function snaps() {
    if (state.phone) return [Math.round(state.maxH / 3), Math.round(state.maxH * 2 / 3), state.maxH];
    var half = Math.max(Math.round(state.maxH * 0.5),
                        Math.min(firstRowNeed(), Math.round(state.maxH * 0.8)));
    return [state.minH, Math.min(half, state.maxH), state.maxH];
  }
  function clampH(h) { return Math.max(state.minH, Math.min(state.maxH, Math.round(h))); }
  function applyHeight(h) {
    state.h = clampH(h || 0);
    root.style.setProperty('--horde-h', state.h + 'px');
    tuckTab();
    placeToggles();
    var p = state.maxH ? Math.round(100 * state.h / state.maxH) : 0;
    grip.setAttribute('aria-valuenow', String(state.open ? p : 0));
    grip.setAttribute('aria-valuetext', state.open ? fill(W('valuetext'), { p: p, px: state.h })
                                                   : W('collapsed'));
  }
  function initialHeight() {
    if (state.phone) {
      var n = parseInt(load(SNAP_KEY) || '2', 10);
      if (!(n >= 1 && n <= 3)) n = 2;
      state.snapPhone = n;
      return snaps()[n - 1];
    }
    if (state.frac === null) {
      var f = parseFloat(load(H_KEY));
      state.frac = (isFinite(f) && f > 0 && f <= 1) ? f : 0.5;
    }
    return state.frac * state.maxH;
  }
  function nearestSnap(h) {
    var s = snaps(), best = 0;
    for (var i = 1; i < s.length; i++) if (Math.abs(s[i] - h) < Math.abs(s[best] - h)) best = i;
    return best;
  }
  function persistHeight() {
    if (state.phone) {
      state.snapPhone = nearestSnap(state.h) + 1;
      store(SNAP_KEY, state.snapPhone);
      return;
    }
    state.frac = state.maxH ? Math.round(1000 * state.h / state.maxH) / 1000 : 0.5;
    if (!state.phone) store(H_KEY, state.frac.toFixed(3));
  }
  function chromeMoved() {
    var ev;
    try { ev = new CustomEvent('sv:chrome-moved'); } catch (e) {
      ev = document.createEvent('CustomEvent');
      ev.initCustomEvent('sv:chrome-moved', false, false, null);
    }
    document.dispatchEvent(ev);
  }
  function remeasure() {
    var before = state.maxH;
    measure();
    /* The strip minimized or restored moves the closed tab: its room too. */
    tier();
    if (state.open) {
      /* Grown for a dossier: kept, re-clamped, until the dossier closes. */
      if (state.phone) applyHeight(snaps()[state.grownFrom !== null ? 2 : state.snapPhone - 1]);
      else if (state.grownFrom !== null) applyHeight(state.h);
      else applyHeight(state.frac !== null ? state.frac * state.maxH : state.h);
    }
    if (before !== state.maxH) chromeMoved();
  }

  /* The wide dossier is its own scroller, stuck to the top of the body:
     its height is the body's visible height less the floating buttons'
     band, read from the body itself (the head grows with the war table). */
  var bodyEl = document.getElementById('svHordeBody');
  function fitDossier() {
    if (bodyEl) root.style.setProperty('--hd-body-h', bodyEl.clientHeight + 'px');
  }

  /* ── width tiers and the phone ───────────────────────────────────── */
  /* The tab's tier: the widest whose content fits the room the stylesheet
     gives the tab (its max-width on the strip's line, or beside the pill
     with the strip minimized). Every segment keeps its whole width (no
     ellipsis, sv-horde.css), so the tab's scrollWidth IS what the tier
     needs; its clientWidth is what it has. The alarms and the REAL pill
     are in every tier. */
  function setTabTier(cls) {
    TAB_TIERS.forEach(function (c) { root.classList.toggle(c, c === cls); });
    if (state.seatN !== null) seatsEl.textContent = seatWords(state.seatN);
  }
  function fitTab() {
    root.classList.remove('hd-tab-alt');
    if (state.phone) { setTabTier('hd-t-s'); return; }
    if (fitTier()) return;
    /* The strip minimized: the tab stands left of the pill; where not
       even the narrowest tier fits there, it takes the room right of the
       pill (sv-horde.css hd-tab-alt). */
    var strip = document.querySelector('.info-panel-wrap');
    if (strip && strip.classList.contains('minimized')) {
      root.classList.add('hd-tab-alt');
      if (!fitTier()) setTabTier('hd-t-s');
    }
  }
  function fitTier() {
    for (var i = 0; i < TAB_TIERS.length; i++) {
      setTabTier(TAB_TIERS[i]);
      if (tab.scrollWidth <= tab.clientWidth + 1) return true;
    }
    return false;
  }
  function tier() {
    var w = state.phone ? window.innerWidth : (root.clientWidth || panel.clientWidth || window.innerWidth);
    /* The sheet's tiers: the dossier column from 900px, the one-row war
       table from 560px. */
    root.classList.toggle('hd-w-l', !state.phone && w >= 900);
    root.classList.toggle('hd-w-m', !state.phone && w >= 560 && w < 900);
    root.classList.toggle('hd-w-s', state.phone || w < 560);
    fitTab();
  }
  function setPhone(on) {
    var was = state.phone;
    state.phone = !!on;
    root.classList.toggle('hd-phone', state.phone);
    measure();
    if (state.open) applyHeight(state.phone ? snaps()[state.snapPhone - 1] : initialHeight());
    tier();
    /* The head folds and the cards take their two-line shape on a phone:
       a board already read is repainted in the new shape. */
    if (was !== state.phone && state.board) { paintTable(state.board); paintBands(state.board); }
  }

  /* ── open and shut ───────────────────────────────────────────────── */
  function setOpen(open, how) {
    open = !!open;
    if (open === state.open && how !== 'restore') return;
    state.open = open;
    root.classList.toggle('open', open);
    tab.setAttribute('aria-expanded', open ? 'true' : 'false');
    /* Collapsed from inside (Enter on the grip, h on a card, a drag): the
       focus goes to the tab before the panel turns inert, never to the
       page's body, so Enter there opens it again at the kept height.
       After the class change, so a phone's pill is shown before it is
       focused. */
    if (!open && panel.contains(document.activeElement)) {
      try { tab.focus({ preventScroll: true }); } catch (e) { /* an old engine */ }
    }
    if (open) panel.removeAttribute('inert'); else panel.setAttribute('inert', '');
    if (how !== 'restore' && !state.phone) store(OPEN_KEY, open ? '1' : '0');
    if (open) {
      measure();
      applyHeight(state.lastGoodH || initialHeight());
      state.lastGoodH = state.h;
      state.moves = 0;
      paintMoves();
      state.stopped = false;
      readBoard('open');
      startPoll();
      if (how === 'key') { try { title.focus(); } catch (e) { /* an old engine */ } }
    } else {
      stopPoll();
      applyHeight(state.h);
    }
    paintTabWords();
    chromeMoved();
  }

  /* ── the clock: one interval, only while open ────────────────────── */
  function startPoll(why) {
    if (state.timer) return;
    state.ticks = 0;
    state.timer = window.setInterval(tick, TICK_MS);
  }
  function stopPoll() {
    if (state.timer) { window.clearInterval(state.timer); state.timer = null; }
    if (state.ctl) { try { state.ctl.abort(); } catch (e) { /* already settled */ } state.ctl = null; }
  }
  function tick() {
    if (!state.open || document.hidden) return;
    state.ticks += 1;
    paintAges();
    var up = !!(window.svLive && window.svLive.isUp && window.svLive.isUp());
    if (up && (state.ticks % UP_EVERY) !== 0) return;
    readBoard('tick');
  }

  /* ── the one door ────────────────────────────────────────────────── */
  function get(url, signal) {
    var opts = { credentials: 'same-origin', headers: { 'Accept': 'application/json' } };
    if (signal) opts.signal = signal;
    return fetch(url, opts).then(function (r) {
      var type = (r.headers && r.headers.get('content-type')) || '';
      if (r.status === 423) return { _locked: true };
      if (r.redirected || !/json/i.test(type)) return { _out: true };
      if (r.status === 404) {
        return r.json().then(function (j) { j = j || {}; j._missing = true; return j; });
      }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }
  function withQuery(q) { return URL_ + (URL_.indexOf('?') === -1 ? '?' : '&') + q; }

  function readBoard(reason) {
    if (!state.open || document.hidden || state.stopped) return;
    if (state.inflight) { state.again = true; return; }
    state.inflight = true;
    var ctl = window.AbortController ? new window.AbortController() : null;
    state.ctl = ctl;
    if (!state.board) showState('loading', W('mustering'));
    get(URL_, ctl ? ctl.signal : null).then(function (d) {
      if (!d) return;
      if (d._locked) { halt(true); return; }
      if (d._out) { halt(false); return; }
      if (d.ok === false) throw new Error(d.error || 'unavailable');
      paintBoard(d);
    }).catch(function (e) {
      if (e && e.name === 'AbortError') return;
      failed();
    }).then(function () {
      state.inflight = false;
      if (state.ctl === ctl) state.ctl = null;
      if (state.again) {
        state.again = false;
        if (state.open && !document.hidden && !state.stopped) readBoard('again');
      }
    });
  }

  function readTab(reason) {
    if (document.hidden) return;
    if (state.open || state.stopped) return;
    var now = Date.now();
    if (now - state.lastTabAt < TAB_MIN_GAP_MS) return;
    state.lastTabAt = now;
    get(withQuery('part=tab'), null).then(function (d) {
      if (!d) return;
      if (d._locked || d._out) { state.stopped = !!d._locked; return; }
      if (d.ok === false) return;
      paintTab(d);
    }).catch(function () { /* the tab keeps what it last said */ });
  }

  /* The last good board stays up, dimmed, under the words that say why it
     is no longer live; it is never blanked and never shown as fresh. */
  function notLive(words, kind) {
    showState(kind, words);
    if (!state.board) return;
    root.classList.add('hd-stale');
    stampEl.textContent = fill(W('not_live'), { t: clock(state.lastGoodAt) });
    stampEl.title = words;
  }
  function halt(locked) {
    state.stopped = true;
    setDot('');
    notLive(locked ? W('locked') : W('signed_out'), 'text');
  }
  function failed() {
    setDot('err');
    notLive(fill(W('cannot_reach'), { t: state.lastGoodAt ? clock(state.lastGoodAt) : DASH }), 'error');
  }
  function setDot(cls) {
    if (!dotEl) return;
    dotEl.className = 'hd-dot' + (cls ? ' ' + cls : '');
  }
  function showState(kind, words) {
    clear(stateEl);
    if (!kind) return;
    var box = el('div', kind === 'loading' ? 'sv-loading' : kind === 'error' ? 'hd-err' : '', words);
    add(stateEl, box);
    if (kind === 'empty') {
      var signals = root.getAttribute('data-signals-url');
      if (signals) { add(box, document.createTextNode(' ')); add(box, link('hd-link', W('signals_link'), signals)); }
    }
  }
  function paintAges() {
    if (!state.lastGoodAt) return;
    var age = Date.now() - state.lastGoodAt;
    var up = !!(window.svLive && window.svLive.isUp && window.svLive.isUp());
    if (!root.classList.contains('hd-stale') && age > 2 * TICK_MS * (up ? UP_EVERY : 1)) {
      setDot('old');
      if (dotEl) dotEl.title = fill(W('last_read_ago'), { age: ageWords(age) });
    }
  }

  /* ── the tab ─────────────────────────────────────────────────────── */
  function seg(node, text, cls) {
    if (!node) return;
    node.textContent = text || '';
    node.hidden = !text;
    if (cls !== undefined) node.className = cls;
  }
  function seatWords(n) {
    var compact = state.phone || !root.classList.contains('hd-t-l');
    if (compact) return fill(W('tab_compact'), { n: n });
    return n === 1 ? fill(W('tab_seat'), { n: n }) : fill(W('tab_seats'), { n: n });
  }
  function paintTab(t) {
    var n = t.seats || 0;
    state.seatN = n;
    seatsEl.textContent = seatWords(n);
    paintHeadCount(t);
    seg(segs.alarms, t.alarms ? (t.alarms === 1 ? fill(W('tab_alarm'), { n: 1 })
                                                 : fill(W('tab_alarms'), { n: t.alarms })) : '');
    seg(segs.real, (t.by_world && t.by_world.live) ? fill(W('tab_real'), { n: t.by_world.live }) : '');
    var lead = (t.sides || {})[t.lead] || {};
    seg(segs.r, lead.r_t || '', 'hd-tab-r ' + (lead.r_v > 0 ? 'up' : lead.r_v < 0 ? 'down' : ''));
    seg(segs.risk, lead.risk_pct_t ? fill(W('tab_risk'), { x: lead.risk_pct_t, limit: lead.limit_pct_t || DASH }) : '',
        'hd-tab-risk ' + (lead.risk_tone || ''));
    var flag = t.flag === 'elite' ? W('flag_elite') : t.flag === 'shut' ? W('flag_shut')
             : t.flag === 'unreadable' ? W('flag_unreadable') : '';
    seg(segs.flag, flag, 'hd-tab-flag ' + (t.flag || ''));
    /* The content moved: the tier is measured again. */
    fitTab();
    if (t.title_t) tab.title = t.title_t;
    state.tabAria = t.aria_t || '';
    paintTabWords();
    if (!state.open && state.lastAlarms !== null && t.alarms > state.lastAlarms
        && Date.now() - state.lastSayAt > SAY_GAP_MS && sayEl) {
      sayEl.textContent = t.attention_t || '';
      state.lastSayAt = Date.now();
    }
    state.lastAlarms = t.alarms || 0;
  }
  function paintTabWords() {
    /* Before the first answer the tab's own text speaks for it. */
    if (!state.tabAria) { tab.removeAttribute('aria-label'); return; }
    tab.setAttribute('aria-label', state.tabAria + ' '
                     + (state.open ? W('press_close') : W('press_open')));
  }
  function paintMoves() {
    var n = state.moves;
    seg(segs.moves, n ? String(n > 99 ? '99+' : n) : '');
    if (segs.moves) segs.moves.title = n ? fill(W('moves_title'), { n: n }) : '';
  }
  /* The open sheet's own count, where the tab is hidden while the sheet
     is open (a phone) or tucked (a wide screen, round 2):
     the seats, the alarm chip and the REAL pill, as the tab says them. */
  function paintHeadCount(t) {
    if (!headCountEl) return;
    clear(headCountEl);
    var n = t.seats || 0;
    add(headCountEl, el('span', '', n === 1 ? fill(W('tab_seat'), { n: 1 }) : fill(W('tab_seats'), { n: n })));
    if (t.alarms) {
      add(headCountEl, el('span', 'hd-tab-alarms hd-count-alarms', t.alarms === 1 ? fill(W('tab_alarm'), { n: 1 })
                                                                  : fill(W('tab_alarms'), { n: t.alarms })));
    }
    if (t.by_world && t.by_world.live) {
      var real = add(headCountEl, el('span', 'hd-tab-real sv-world sv-world--live',
                                     fill(W('tab_real'), { n: t.by_world.live })));
      real.title = segs.real ? segs.real.title : '';
    }
  }

  /* ── the board ───────────────────────────────────────────────────── */
  function allSeats(d) {
    var out = [];
    ((d && d.groups) || []).forEach(function (g) { (g.seats || []).forEach(function (s) { out.push(s); }); });
    return out;
  }
  function findSeat(key) {
    var all = allSeats(state.board);
    for (var i = 0; i < all.length; i++) if (all[i].key === key) return all[i];
    return null;
  }
  function paintBoard(d) {
    state.board = d;
    state.lastGoodAt = Date.now();
    root.classList.remove('hd-stale');
    setDot('live');
    if (dotEl) dotEl.title = '';
    stampEl.textContent = fill(W('as_of'), { t: clock(state.lastGoodAt) });
    stampEl.title = fill(W('kept'), { t: d.head && d.head.as_of ? isoClock(d.head.as_of) : DASH });
    if (bookEl && d.book) bookEl.title = fill(W('book_title'), { book: d.book.legacy_book });
    if (d.tab) paintTab(d.tab);
    paintLens(d);
    paintTable(d);
    fitDossier();
    showState(d.empty ? 'empty' : '', d.empty ? d.empty.t : '');
    paintBands(d);
    if (state.seatKey) {
      var s = findSeat(state.seatKey);
      if (!s) {
        if (state.seatGone) closeDossier(false);
        else seatGone();
      } else if (state.seatData) {
        paintSeatHead(s);
        if (state.seatRev && s.rev !== state.seatRev) readSeat(state.seatKey);
      }
    }
    lineEndsSoon();
  }

  function paintLens(d) {
    var have = { live: 0, demo: 0, paper: 0, none: 0 };
    allSeats(d).forEach(function (s) { have[s.world || 'none'] += 1; });
    Array.prototype.forEach.call(lensBtns, function (b) {
      var k = b.getAttribute('data-lens');
      if (k !== 'all') b.hidden = !have[k];
      b.setAttribute('aria-pressed', k === state.lens ? 'true' : 'false');
    });
  }
  /* The lens a phone cannot see (its head hides the buttons) never
     filters there: a lens kept from a wide screen would hide seats with
     nothing on screen to bring them back. */
  function lens() { return state.phone ? 'all' : state.lens; }
  function lensMatches(world) {
    if (lens() === 'all') return true;
    return (world || 'none') === lens();
  }
  function applyFilters() {
    var bands = bandsEl.querySelectorAll('.hd-band[data-band]');
    var visible = 0;
    Array.prototype.forEach.call(bands, function (band) {
      var shown = 0;
      Array.prototype.forEach.call(band.querySelectorAll('.hd-seat'), function (c) {
        var ok = lensMatches(c.getAttribute('data-world'))
                 && (!state.tone || c.getAttribute('data-tone') === state.tone);
        c.hidden = !ok;
        if (ok) shown += 1;
      });
      Array.prototype.forEach.call(band.querySelectorAll('.hd-line[data-world], .hd-bet[data-world]'), function (l) {
        l.hidden = !lensMatches(l.getAttribute('data-world'));
      });
      /* The band's one Tab stop is its first VISIBLE seat: a lens or a
         tone that hides the first card must not leave the band with no
         way in (the arrows then have a place to start from). */
      Array.prototype.forEach.call(band.querySelectorAll('.hd-seat-open'), function (b) { b.tabIndex = -1; });
      var firstVis = band.querySelector('.hd-seat:not([hidden]) .hd-seat-open');
      if (firstVis) firstVis.tabIndex = 0;
      band.hidden = shown === 0;
      visible += shown;
    });
    var none = state.board && allSeats(state.board).length && !visible;
    if (none && lens() !== 'all') {
      var word = '';
      allSeats(state.board).forEach(function (s) { if ((s.world || 'none') === lens()) word = s.world_word; });
      var b = root.querySelector('.hd-lens-btn[data-lens="' + lens() + '"]');
      showState('text', fill(W('no_world'), { world: word || (b ? b.textContent : '') }));
    } else if (state.board && !state.board.empty) {
      showState('', '');
    }
  }

  /* the war table: the gate's two sides, the pools, the alarms */
  function line(parent, cls) { return add(parent, el('div', 'hd-cell-line' + (cls ? ' ' + cls : ''))); }
  function bold(parent, text) { return add(parent, el('b', '', text)); }
  function paintSide(side, s) {
    var cell = el('div', 'hd-cell');
    var folded = (lens() === 'paper' && side === 'live')
                 || ((lens() === 'live' || lens() === 'demo' || lens() === 'none') && side === 'paper');
    if (folded || !s.present) cell.classList.add('hd-folded');
    var t = add(cell, el('div', 'hd-cell-title'));
    joinDots(t, [el('span', 'sv-venue ' + s.venue_class, s.label), el('span', '', s.book_t)]);
    var body = add(cell, el('div', 'hd-cell-body'));
    var orisk = s.open_risk || {};
    var l1 = line(body, orisk.tone ? 'hd-tone-' + orisk.tone : '');
    bold(l1, W('open_risk'));
    if (orisk.pct_t) {
      var meter = add(body, el('div', 'hd-meter ' + (orisk.tone || '')));
      var limit = parseFloat(String(orisk.limit_pct_t || '').replace('%', ''));
      var fillPct = limit ? Math.min(100, 100 * (orisk.pct_v || 0) / limit) : 0;
      var bar = add(meter, el('span'));
      bar.style.width = fillPct.toFixed(1) + '%';
      add(meter, el('i'));
      add(l1, txt(' ' + fill(W('pct_of'), { pct: orisk.pct_t, limit: orisk.limit_pct_t })));
      line(body).textContent = dots(orisk.t);
    } else {
      add(l1, txt(' ' + DASH + ' ' + (orisk.t || '')));
    }
    l1.title = orisk.reason || '';
    if (orisk.past_t) line(body, 'hd-tone-past').textContent = dots(orisk.past_t);
    if (s.demo_note_t) line(body, 'hd-muted').textContent = dots(s.demo_note_t);
    if (s.extra_t) line(body, 'hd-muted').textContent = dots(s.extra_t);
    if (s.abandoned_t) line(body, 'hd-muted').textContent = dots(s.abandoned_t);
    var daily = s.daily || {};
    var l2 = line(body, daily.mode === 'shut' ? 'hd-tone-bad' : daily.mode === 'elite' ? 'hd-tone-near' : '');
    bold(l2, W('daily_stop'));
    add(l2, txt(' ' + (daily.mode === 'unmeasured' ? DASH + ' ' : '') + (daily.t || '')));
    l2.title = W('daily_title') + (daily.reason ? ' ' + daily.reason : '');
    var l3 = line(body);
    bold(l3, W('allocation'));
    if ((s.alloc || []).length || s.alloc_free) {
      var alloc = add(body, el('div', 'hd-alloc'));
      var words = [];
      (s.alloc || []).forEach(function (a) {
        var piece = add(alloc, el('span', a.demo ? 'demo' : a.legacy ? 'legacy' : ''));
        piece.style.width = Math.max(0, Math.min(100, a.pct_v)).toFixed(1) + '%';
        piece.title = a.t + (a.demo ? ' · ' + W('demo') : a.legacy ? ' · ' + W('no_venue_seg') : '');
        words.push(a.t + (a.demo ? ' (' + W('demo') + ')' : a.legacy ? ' (' + W('no_venue_seg') + ')' : ''));
      });
      if (s.alloc_free) words.push(s.alloc_free.t);
      add(l3, txt(' ' + words.join(' · ')));
      if (s.alloc_unmeasured_t) line(body, 'hd-muted').textContent = dots(s.alloc_unmeasured_t);
      if (s.alloc_over_t) line(body, 'hd-tone-past').textContent = dots(s.alloc_over_t);
    } else {
      add(l3, txt(' ' + (s.alloc_t || DASH)));
    }
    var l4 = line(body);
    [['exposure', s.exposure], ['notional', s.notional]].forEach(function (pair, i) {
      if (i) add(l4, txt(' · '));
      bold(l4, pair[0] === 'exposure' ? W('exposure') : W('notional'));
      add(l4, txt(' '));
      var ok = pair[1] ? pair[1].ok : null;
      var chip = add(l4, el('span', 'hd-chip ' + (ok === true ? 'ok' : ok === false ? 'bad' : 'muted'),
                            ok === true ? W('ok') : ok === false ? W('past') : DASH));
      chip.title = (pair[1] && pair[1].reason) || '';
    });
    return cell;
  }
  /* The tone of an alarm chip: the tab's own colours (2026-10-16: the
     head's "1 ALARM" was grey beside the tab's red pill). */
  var CHIP_TONES = { alarm: 'hd-chip-btn--alarm', watch: 'hd-chip-btn--watch',
                     order: 'hd-chip-btn--order', unheld: 'hd-chip-btn--unheld' };
  function toneChips(parent, tones) {
    [['alarm', tones.alarm, tones.alarm === 1 ? fill(W('chip_alarm'), { n: 1 }) : fill(W('chip_alarms'), { n: tones.alarm })],
     ['watch', tones.watch, fill(W('chip_watch'), { n: tones.watch })],
     ['unheld', tones.unheld, fill(W('chip_unheld'), { n: tones.unheld })],
     ['order', tones.order, tones.order === 1 ? fill(W('chip_order'), { n: 1 }) : fill(W('chip_orders'), { n: tones.order })]
    ].forEach(function (c) {
      if (!c[1]) return;
      var b = add(parent, button('hd-chip-btn ' + CHIP_TONES[c[0]], c[2], function () {
        state.tone = state.tone === c[0] ? '' : c[0];
        paintTable(state.board);
        applyFilters();
        if (state.tone) {
          var first = bandsEl.querySelector('.hd-seat:not([hidden]) .hd-seat-open');
          if (first) { try { first.focus(); } catch (e) { /* no focus */ } }
        }
      }));
      b.setAttribute('aria-pressed', state.tone === c[0] ? 'true' : 'false');
      b.setAttribute('data-hd-focus', 'chip:' + c[0]);
    });
  }
  /* THE WAR TABLE. The head keeps ONE line pinned (2026-10-16: at HALF
     its capped scroller cut the REAL ACCOUNT card mid-content, and at
     1100 no seat card was left on screen): the book limits in a sentence
     per side, the alarm chips that filter the seats, and a toggle. The
     cells, when the reader opens them, stand at the top of the body and
     scroll with the bands as ONE unit, whole, never cut by a scroller of
     their own. The choice is kept per viewer. */
  function sideSummary(k, s) {
    var o = s.open_risk || {}, dl = s.daily || {};
    var mode = dl.mode === 'shut' ? W('mode_shut') : dl.mode === 'elite' ? W('mode_elite')
             : dl.mode === 'open' ? W('mode_open') : DASH;
    var span = el('span', 'hd-sum-side' + (o.tone ? ' hd-tone-' + o.tone : ''),
                  fill(W('sum_side'), { side: k === 'live' ? W('sum_real') : W('sum_paper'),
                                        x: o.pct_t || DASH, limit: o.limit_pct_t || DASH, mode: mode }));
    span.title = [s.label, s.book_t, o.t].filter(Boolean).join(' · ');
    return span;
  }
  function paintTable(d) {
    var keep = focusKey(tableEl) || focusKey(sumEl);
    clear(tableEl);
    clear(notesEl);
    clear(sumEl);
    var notes = notesEl || tableEl;
    var hd = d.head || {};
    var sides = hd.sides || {};
    var toggle = null;
    if (hd.readable) {
      toggle = add(sumEl, button('hd-sum-btn', W('book_limits')));
      toggle.setAttribute('aria-controls', 'svHordeTable');
      toggle.setAttribute('aria-expanded', state.limitsOpen ? 'true' : 'false');
      toggle.setAttribute('data-hd-focus', 'limits');
      toggle.title = state.limitsOpen ? W('limits_hide') : W('limits_show');
      var parts = [];
      ['live', 'paper'].forEach(function (k) {
        if (sides[k] && sides[k].present) parts.push(sideSummary(k, sides[k]));
      });
      /* A phone's one line is the real account's (the paper side is in the
         opened cells), as it was before; a paper-only book keeps paper. */
      if (state.phone && parts.length > 1) parts = parts.slice(0, 1);
      joinDots(sumEl, parts);
      toggle.addEventListener('click', function () {
        state.limitsOpen = !state.limitsOpen;
        store(LIMITS_KEY, state.limitsOpen ? '1' : '0');
        toggle.setAttribute('aria-expanded', state.limitsOpen ? 'true' : 'false');
        toggle.title = state.limitsOpen ? W('limits_hide') : W('limits_show');
        tableEl.hidden = !state.limitsOpen;
        root.classList.toggle('hd-limits-open', state.limitsOpen);
        fitDossier();
      });
    }
    toneChips(add(sumEl, el('span', 'hd-sum-chips')), hd.tones || {});
    tableEl.hidden = !(hd.readable && state.limitsOpen);
    root.classList.toggle('hd-limits-open', !!(hd.readable && state.limitsOpen));
    if (!hd.readable) { add(notes, el('div', 'hd-failed', dots(hd.t))); refocus(sumEl, keep); return; }
    var failedSaid = '';
    ['live', 'paper'].forEach(function (k) {
      var s = sides[k];
      if (s && s.failed_open && s.failed_t !== failedSaid) {
        add(notes, el('div', 'hd-failed', dots(s.failed_t)));
        failedSaid = s.failed_t;
      }
    });
    ['live', 'paper'].forEach(function (k) { if (sides[k]) add(tableEl, paintSide(k, sides[k])); });
    /* eToro's OWN figures, ahead of the pools (2026-10-31): used,
       available, P&L and total from the sync's cells with their age, then
       the split against Sauron's own eToro rows. Both sentences are the
       server's (bot_program/etoro_used.py); the pools below are the pools'
       arithmetic. */
    if (hd.etoro && hd.etoro.t) {
      var acct = add(tableEl, el('div', 'hd-cell hd-small'));
      add(add(acct, el('div', 'hd-cell-title')), el('span', '', W('etoro_cell')));
      line(acct, hd.etoro.read ? '' : 'hd-muted').textContent = dots(hd.etoro.t);
      if (hd.etoro.split_t) line(acct, 'hd-muted').textContent = dots(hd.etoro.split_t);
      acct.title = hd.etoro.title || '';
    }
    if (hd.pools) {
      var pools = add(tableEl, el('div', 'hd-cell hd-small'));
      add(add(pools, el('div', 'hd-cell-title')), el('span', '', W('pools')));
      line(pools, hd.pools.live_neg ? 'hd-tone-down' : '').textContent = dots(hd.pools.live_t);
      line(pools, hd.pools.paper_neg ? 'hd-tone-down' : '').textContent = dots(hd.pools.paper_t);
      pools.title = hd.pools.classes_t || '';
    }
    /* Which book each count covers is the server's sentence (MARKS · REAL
       seats (5): ... · PAPER seats (3): ...). */
    if (hd.marks && hd.marks.t) {
      /* One box per "·" segment, so a wrap breaks between whole segments
         and lineEnds can drop the dot that would end a line (final
         review: "0 waiting ·" then "PAPER (3)" on the phone). */
      var mk = add(notes, el('div', 'hd-note hd-note-units'));
      mk.title = hd.marks.title || '';
      joinDots(mk, String(hd.marks.t).split(' \u00b7 ').map(function (t) { return el('span', '', t); }));
    }
    (hd.switch_lines || []).forEach(function (t) { add(notes, el('div', 'hd-note gold', t)); });
    refocus(tableEl, keep);
    refocus(sumEl, keep);
  }
  /* Every repaint rebuilds its box: the reader's place (a band title, an
     expander, a chip, a seat) is kept by a key, read before and focused
     again after, so a keyboard or a screen reader never falls to <body>
     on the poll. */
  function focusKey(box) {
    var a = document.activeElement;
    if (!a || !box || !box.contains(a) || !a.getAttribute) return null;
    return a.getAttribute('data-hd-focus');
  }
  function refocus(box, key) {
    if (!key || !box) return;
    var n = box.querySelector('[data-hd-focus="' + key.replace(/"/g, '') + '"]');
    if (!n) return;
    if (n.hasAttribute('data-open-seat')) n.tabIndex = 0;
    try { n.focus({ preventScroll: true }); } catch (e) { /* gone */ }
  }

  /* the bands */
  function worldPill(world, word, titleText) {
    var p = el('span', world ? 'sv-world sv-world--' + world : 'hd-no-venue', word);
    if (titleText) p.title = titleText;
    return p;
  }
  function lightEl(lt) {
    var span = el('span', 'hd-light hd-light--' + lt.tone);
    var g = add(span, el('span', 'hd-light-glyph', GLYPHS[lt.tone] || GLYPHS.calm));
    g.setAttribute('aria-hidden', 'true');
    add(span, el('span', '', lt.word));
    span.title = (lt.why || []).map(function (w) { return w.t; }).join(' ');
    return span;
  }
  /* "[REAL 2] [PAPER 1]" on a band's head: the world and its seat count. */
  function pillWords(world, n) {
    var t = world === 'live' ? W('pill_live') : world === 'demo' ? W('pill_demo')
          : world === 'paper' ? W('pill_paper') : W('pill_none');
    return fill(t, { n: n });
  }
  /* The verdict on a card says whose it is (2026-10-16: an unlabelled
     EXIT sat on the care's row and read as the care's): the position
     reviewer's, or else the thesis check's. */
  function voiceChip(s) {
    var rv = s.voice && s.voice.reviewer, th = s.voice && s.voice.thesis;
    var v = rv || th || null;
    if (!v) return null;
    var verdict = v.verdict || '';
    var cls = verdict === 'exit' ? ' red'
            : (verdict === 'tighten' || verdict === 'adjust' || verdict === 'take_part') ? ' gold' : '';
    var chip = el('span', 'hd-voice-chip' + cls,
                  fill(rv ? W('chip_reviewer') : W('chip_thesis'), { v: v.word }));
    chip.title = fill(rv ? W('chip_reviewer_title') : W('chip_thesis_title'), { age: v.age_t || DASH });
    return chip;
  }
  function seatCard(s) {
    var card = el('div', 'hd-seat' + (s.world === 'live' ? ' sv-row--live' : '')
                         + (state.seatKey === s.key ? ' hd-current' : ''));
    card.setAttribute('role', 'group');
    card.setAttribute('data-seat', s.key);
    card.setAttribute('data-world', s.world || 'none');
    card.setAttribute('data-tone', s.light.tone);
    var lid = 'svHordeL-' + s.key.replace(':', '-');
    card.setAttribute('aria-labelledby', lid);
    var r1 = add(card, el('div', 'hd-seat-row'));
    add(r1, lightEl(s.light));
    var open = add(r1, button('hd-seat-open', s.symbol));
    open.id = lid;
    open.setAttribute('aria-controls', 'svHordeSeat');
    open.setAttribute('aria-expanded', state.seatKey === s.key ? 'true' : 'false');
    open.setAttribute('data-open-seat', s.key);
    open.setAttribute('data-hd-focus', 'seat:' + s.key);
    open.tabIndex = -1;
    add(r1, el('span', '', s.side_word));
    add(r1, worldPill(s.world, s.world_word, s.world_title));
    /* The money of the seat: R, P&L, the mark and its word (or the wait
       sentence). A working order has none: it is not filled. */
    var rr = null, pnl = null, markBits = [];
    if (!s.working) {
      rr = el('span', 'hd-r ' + toneCls(s.money.r_tone), s.money.r_t);
      rr.title = s.money.r_title || '';
      rr.setAttribute('data-flash', s.key + ':r');
      pnl = el('span', 'hd-pnl ' + toneCls(s.money.pnl_tone),
               s.money.pnl_t + (s.money.pnl_v !== null && s.money.pnl_v !== undefined && s.money.ccy ? ' ' + s.money.ccy : ''));
      pnl.setAttribute('data-flash', s.key + ':pnl');
      if (s.mark.v === null || s.mark.v === undefined) {
        var w = el('span', 'hd-wait', DASH + (s.mark.wait ? ' ' + s.mark.wait : ''));
        w.title = s.mark.title || '';
        markBits.push(w);
      } else {
        var mk = el('span', 'hd-mark', s.mark.t);
        mk.title = s.mark.title || '';
        mk.setAttribute('data-flash', s.key + ':mark');
        markBits.push(mk);
        if (s.mark.word && s.world !== 'paper') markBits.push(el('span', 'hd-muted', s.mark.word));
      }
    }
    var notFilled = s.working ? el('span', 'hd-wait', s.money.note) : null;
    add(r1, el('span', 'hd-grow', s.kind === 'bot' ? '#' + s.trade_id : 'pos #' + s.position_id));
    var r2 = add(card, el('div', 'hd-seat-row'));
    var m = add(r2, el('span', 'hd-mission', s.mission));
    m.title = s.mission;
    /* The instrument's own class, as a chip (round 2: "Index momentum
       instrument: index" ran into the mission with no separator). */
    if (!state.phone && s.instrument_class && s.instrument_class !== s['class']) {
      add(r2, el('span', 'hd-chip hd-inst-chip', fill(W('inst_class'), { 'class': s.instrument_class })));
    }
    if (!state.phone && s.orc && s.orc.plan_line) add(card, el('div', 'hd-seat-row hd-muted', s.orc.plan_line));
    /* The money line is one unit on its own row, on the phone too (round
       2: the phone split "-0.50R", "-57.24 USD" and "7.12860 venue" over
       the head row, the mission's row and a third line). */
    var r3 = add(card, el('div', 'hd-seat-row hd-money-row'));
    add(r3, notFilled);
    add(r3, rr);
    add(r3, pnl);
    markBits.forEach(function (b) { add(r3, b); });
    var lv = s.levels || {};
    var r4 = add(card, el('div', 'hd-seat-row hd-phone-hide'));
    /* The stop that can be hit (the venue's, on a row it protects), and
       the stop sent beside it when the venue holds another or none. */
    add(r4, el('span', 'hd-muted', W('lbl_stop') + ' ' + (lv.stop_t || W('no_stop'))));
    if (lv.sent_stop_t) add(r4, el('span', 'hd-muted', fill(W('stop_sent'), { x: lv.sent_stop_t })));
    var rail = add(r4, el('span', 'hd-rail' + (lv.stop_through ? ' through' : '')));
    if (lv.progress_v !== null && lv.progress_v !== undefined) {
      var tickEl = add(rail, el('i'));
      tickEl.style.left = (Math.max(0, Math.min(1, lv.progress_v)) * 100).toFixed(1) + '%';
    }
    add(r4, el('span', 'hd-muted', W('lbl_target') + ' ' + (lv.target_t || W('no_target'))));
    /* The distance to the stop has its own row at every width (round 2:
       "target 1.33200 0.89% to the stop" ran together in a narrow card). */
    if (lv.stop_pct_t) {
      var r4b = add(card, el('div', 'hd-seat-row hd-phone-hide hd-stop-dist'));
      add(r4b, el('span', lv.stop_through ? 'hd-through' : 'hd-muted',
                  lv.stop_through ? fill(W('through_stop'), { x: lv.stop_pct_t })
                                  : fill(W('to_stop'), { x: lv.stop_pct_t })));
    }
    /* The voice has a row of its own, so the holder row, and "No Orc" at
       its right, stand at the same height on every card, pinned to the
       card's foot (round 2). */
    /* An ALARM or a WATCH always names its cause, on the phone too (final
       review: the phone card showed a red ALARM and hid "Reviewer: EXIT").
       The voice row stays when the voice is what raised the light; a
       light raised by something else says its own first reason, so a
       calm verdict is never shown as the cause. */
    var vc = voiceChip(s);
    var lt = s.light || {};
    var loud = lt.tone === 'alarm' || lt.tone === 'watch';
    var said = (lt.why || []).filter(function (w) { return w.tone === lt.tone; });
    var voiceCode = (s.voice && s.voice.reviewer) ? 'reviewer_' : 'thesis_';
    var voiceSaid = loud && said.some(function (w) { return String(w.code || '').indexOf(voiceCode) === 0; });
    if (vc) add(add(card, el('div', voiceSaid ? 'hd-seat-row hd-voice-row' : 'hd-seat-row hd-phone-hide')), vc);
    if (loud && !voiceSaid && said.length) {
      add(add(card, el('div', 'hd-seat-row hd-light-why')),
          el('span', 'hd-muted', said[0].t + (said.length > 1 ? ' ' + fill(W('more_causes'), { n: said.length - 1 }) : '')));
    }
    /* Two facts, two subjects, two rows: how long the position has been
       open, then who holds it (round 2: "Care · profit locks held 1 day
       20 hours" read as the lock's age). */
    var foot = add(card, el('div', 'hd-seat-foot hd-phone-hide'));
    add(add(foot, el('div', 'hd-seat-row')), el('span', 'hd-muted', fill(W('held_for'), { t: s.held.t })));
    var r5 = add(foot, el('div', 'hd-seat-row'));
    var h = add(r5, el('span', '', s.holder.short));
    h.title = s.holder.words + (s.holder.suffix ? ' ' + s.holder.suffix : '');
    if (s.orc && s.orc.label) {
      var oc = add(r5, el('span', 'hd-grow', s.orc.label + (s.orc.authority && s.orc.authority.level_t
                                                            ? ' · ' + s.orc.authority.level_t : '')));
      /* Its army and its state on hover: words of the slot, as text. */
      oc.title = [s.orc.army && s.orc.army.type_t, s.orc.state_t].filter(Boolean).join(' · ');
    } else {
      var no = add(r5, el('span', 'hd-grow hd-no-orc', W('no_orc')));
      no.title = W('no_orc_seated') + ' ' + s.holder.words;
    }
    return card;
  }
  function bandHead(band, key, label, expanded) {
    var hd = add(band, el('div', 'hd-band-head'));
    var t = add(hd, button('hd-band-title', label));
    t.setAttribute('data-hd-focus', 'band:' + key);
    var bodyId = 'svHordeBand-' + key.replace(/[^\w-]/g, '_');
    t.setAttribute('aria-controls', bodyId);
    t.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    var body = el('div', 'hd-band-body');
    body.id = bodyId;
    body.hidden = !expanded;
    t.addEventListener('click', function () {
      var now = t.getAttribute('aria-expanded') !== 'true';
      t.setAttribute('aria-expanded', now ? 'true' : 'false');
      body.hidden = !now;
      if (now) delete state.shut[key]; else state.shut[key] = 1;
      store(SHUT_KEY, JSON.stringify(Object.keys(state.shut).slice(0, SHUT_MAX)));
    });
    return { head: hd, body: body };
  }
  function startsOpen(key, g, total) {
    if (state.shut[key]) return false;
    if (!state.phone || total <= 6) return true;
    return (g.seats || []).some(function (s) { return s.light.tone === 'alarm' || s.world === 'live'; });
  }
  function groupBand(g, total) {
    var band = el('section', 'hd-band');
    band.setAttribute('data-band', g.key);
    var parts = bandHead(band, g.key, g.label, startsOpen(g.key, g, total));
    (g.lines || []).forEach(function (l) {
      add(parts.head, worldPill(l.world, pillWords(l.world, l.seats), l.world_word));
    });
    if (g.captain && g.captain.label) add(parts.head, el('span', 'hd-captain', g.captain.label));
    else add(parts.head, el('span', 'hd-captain', W('no_captain')));
    /* The day's weather for this class (calm, eventful, stormy), when the
       slot carries one; nothing is routed on it. */
    if (g.captain && g.captain.day && g.captain.day.t) {
      add(parts.head, el('span', 'hd-captain hd-day', fill(W('day_t'), { t: g.captain.day.t })));
    }
    /* Open or shut as the reader left it: the board repaints every band
       on each read, and an expander that closed itself every 20-60 s
       could not be read. */
    var today = el('div', 'hd-today');
    today.hidden = !state.today[g.key];
    var exp = add(parts.head, button('hd-expander', W('what_holds')));
    exp.setAttribute('aria-expanded', today.hidden ? 'false' : 'true');
    exp.setAttribute('data-hd-focus', 'exp:' + g.key);
    exp.addEventListener('click', function () {
      today.hidden = !today.hidden;
      if (today.hidden) delete state.today[g.key]; else state.today[g.key] = 1;
      exp.setAttribute('aria-expanded', today.hidden ? 'false' : 'true');
    });
    add(band, parts.body);
    add(parts.body, today);
    if (g.today) {
      if (g.today.share_t) add(today, el('div', '', g.today.share_t));
      (g.today.legs_t || []).forEach(function (t) { add(today, el('div', '', t)); });
    }
    add(today, el('div', 'hd-muted', W('captains_not_built')));
    if (g.class_note_t) add(parts.body, el('div', 'hd-class-note', g.class_note_t));
    (g.lines || []).forEach(function (l) {
      var row = add(parts.body, el('div', 'hd-line'));
      row.setAttribute('data-world', l.world || 'none');
      add(row, worldPill(l.world, l.world_word));
      var bits = [l.seats === 1 ? fill(W('seat_n'), { n: 1 }) : fill(W('seats_n'), { n: l.seats })];
      bits.push(l.sides_known ? fill(W('long_short'), { l: l['long'], s: l['short'] }) : W('long_short_unknown'));
      var items = [el('span', '', bits.join(' '))];
      if (l.at_work_t) items.push(el('span', '', fill(W('at_work'), { x: l.at_work_t })));
      (l.pnl || []).forEach(function (p, i) {
        var pn = el('span', toneCls(p.tone), p.t + ' ' + p.ccy);
        /* The unpriced count rides with the last money figure. */
        if (i === l.pnl.length - 1 && l.priced < l.seats) {
          add(pn, el('span', 'hd-muted', ' ' + fill(W('priced_of'), { n: l.priced, m: l.seats })));
        }
        items.push(pn);
      });
      if (!(l.pnl || []).length && l.priced < l.seats) {
        items.push(el('span', 'hd-muted', fill(W('priced_of'), { n: l.priced, m: l.seats })));
      }
      if (l.r_t) {
        items.push(el('span', '', l.r_t + (l.r_n < l.seats ? ' ' + fill(W('r_of'), { n: l.r_n, m: l.seats }) : '')));
      }
      if (l.risk_t) {
        items.push(el('span', '', fill(W('at_stops'), { x: l.risk_t, y: dash(l.risk_pct_t) })
                                  + (l.risk_n < l.seats ? ' ' + fill(W('r_of'), { n: l.risk_n, m: l.seats }) : '')));
      }
      /* The pill has a column of its own and the words wrap in theirs, so
         a continuation starts under the words, not under the pill, with
         no pill-high gap (final review: "at the stops ..." read as a
         fourth line of its own). */
      joinDots(add(row, el('span', 'hd-line-words')), items);
    });
    (g.same_bet || []).forEach(function (b) {
      var bet = add(parts.body, el('div', 'hd-bet', fill(W('same_bet'), { words: b.t })));
      bet.setAttribute('data-world', b.world || 'none');
    });
    var cards = add(parts.body, el('div', 'hd-cards'));
    (g.seats || []).forEach(function (s) { add(cards, seatCard(s)); });
    return band;
  }
  function stragglerBand(rows) {
    var band = el('section', 'hd-band hd-band--stragglers');
    var parts = bandHead(band, '_stragglers', W('stragglers_title') + ' (' + rows.length + ')',
                         !state.shut._stragglers);
    add(band, parts.body);
    rows.forEach(function (r) {
      var box = add(parts.body, el('div', 'hd-straggler' + (r.world === 'live' ? ' sv-row--live' : '')));
      var top = add(box, el('div', 'hd-seat-row'));
      add(top, lightEl({ tone: r.tone || 'alarm', word: r.word, why: [{ t: r.t }] }));
      add(top, el('b', '', r.symbol));
      add(top, el('span', '', r.side_word));
      add(top, worldPill(r.world, r.world_word));
      add(top, el('span', 'hd-grow', '#' + r.id));
      add(box, el('div', '', r.t));
      add(box, link('hd-link', W('trade_detail'), r.story));
    });
    return band;
  }
  function unseatedBand(u) {
    var band = el('section', 'hd-band hd-band--unseated');
    var parts = bandHead(band, '_unseated', fill(W('unseated_title'), { broker: String(u.broker || '').toUpperCase() })
                         + ' (' + u.rows.length + ')', !state.shut._unseated);
    add(parts.head, u.world ? worldPill(u.world, u.world_word)
                            : el('span', 'hd-no-venue', W('venue_unknown')));
    if (u.age_t) add(parts.head, el('span', 'hd-muted', fill(W('read_ago'), { age: u.age_t })));
    add(band, parts.body);
    u.rows.forEach(function (r) {
      var box = add(parts.body, el('div', 'hd-unseated'));
      var top = add(box, el('div', 'hd-seat-row'));
      add(top, el('b', '', r.symbol));
      if (r.side_word) add(top, el('span', '', r.side_word));
      add(top, el('span', '', r.units_t));
      add(top, el('span', 'hd-grow', r.value_t));
      add(box, el('div', 'hd-muted', r.t));
    });
    return band;
  }
  function flashChanges() {
    var marks = bandsEl.querySelectorAll('[data-flash]');
    var next = {};
    Array.prototype.forEach.call(marks, function (n) {
      var k = n.getAttribute('data-flash');
      var v = n.textContent;
      next[k] = v;
      if (state.prev[k] !== undefined && state.prev[k] !== v && window.SV && window.SV.flash) {
        var a = parseFloat(String(state.prev[k]).replace(/[^\d.+-]/g, ''));
        var b = parseFloat(String(v).replace(/[^\d.+-]/g, ''));
        window.SV.flash.mark(n, (isFinite(a) && isFinite(b)) ? (b > a ? 'up' : b < a ? 'down' : 'same') : 'same');
      }
    });
    state.prev = next;
  }
  function paintBands(d) {
    var keep = focusKey(bandsEl);
    clear(bandsEl);
    var total = allSeats(d).length;
    if (d.stragglers && d.stragglers.length) add(bandsEl, stragglerBand(d.stragglers));
    (d.groups || []).forEach(function (g) { add(bandsEl, groupBand(g, total)); });
    if (d.unseated && d.unseated.rows && d.unseated.rows.length) add(bandsEl, unseatedBand(d.unseated));
    /* applyFilters seats each band's roving stop on its first VISIBLE
       card; the card the reader stood on takes it back below. */
    applyFilters();
    flashChanges();
    if (keep && keep.indexOf('seat:') === 0) {
      var again = bandsEl.querySelector('[data-hd-focus="' + keep.replace(/"/g, '') + '"]');
      var band = again && again.closest('.hd-band');
      if (band) {
        Array.prototype.forEach.call(band.querySelectorAll('.hd-seat-open'), function (b) { b.tabIndex = -1; });
      }
    }
    refocus(bandsEl, keep);
  }

  /* roving focus inside a band: arrows, Home, End; Enter and Space open */
  bandsEl.addEventListener('keydown', function (e) {
    var t = e.target;
    if (!t || !t.getAttribute || !t.getAttribute('data-open-seat')) return;
    var band = t.closest('.hd-band');
    if (!band) return;
    var list = Array.prototype.filter.call(band.querySelectorAll('.hd-seat-open'), function (b) {
      return !b.closest('.hd-seat').hidden;
    });
    var i = list.indexOf(t), j = -1;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') j = Math.min(list.length - 1, i + 1);
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') j = Math.max(0, i - 1);
    else if (e.key === 'Home') j = 0;
    else if (e.key === 'End') j = list.length - 1;
    else return;
    e.preventDefault();
    if (j < 0 || !list[j]) return;
    list.forEach(function (b) { b.tabIndex = -1; });
    list[j].tabIndex = 0;
    try { list[j].focus(); } catch (x) { /* no focus */ }
  });
  bandsEl.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-open-seat]');
    if (!b) return;
    openSeat(b.getAttribute('data-open-seat'), b);
  });

  /* ── the dossier ─────────────────────────────────────────────────── */
  var loading = {};
  function loadScript(src, name) {
    if (window[name]) return Promise.resolve(true);
    if (!src) return Promise.resolve(false);
    if (loading[src]) return loading[src];
    loading[src] = new Promise(function (resolve) {
      var done = false;
      function finish() { if (!done) { done = true; resolve(!!window[name]); } }
      var existing = document.querySelector('script[src="' + src + '"]');
      var s = existing || document.createElement('script');
      var timer = window.setTimeout(finish, SEAT_LOAD_TIMEOUT_MS);
      s.addEventListener('load', function () { window.clearTimeout(timer); finish(); });
      s.addEventListener('error', function () { window.clearTimeout(timer); finish(); });
      if (!existing) { s.src = src; s.defer = true; document.head.appendChild(s); }
    });
    return loading[src];
  }
  function loadOpeners() {
    var css = root.getAttribute('data-advice-css');
    if (css && !document.querySelector('link[href="' + css + '"]')) {
      var l = document.createElement('link');
      l.rel = 'stylesheet';
      l.href = css;
      document.head.appendChild(l);
    }
    loadScript(root.getAttribute('data-level-edit-src'), 'SVLevelEdit').then(function (ok) {
      state.lvlFailed = !ok;
      if (state.seatData) paintCommands(state.seatData);
    });
    loadScript(root.getAttribute('data-advice-src'), 'SVCloseAdvice').then(function () {
      if (state.seatData) paintCommands(state.seatData);
    });
  }
  function markCurrent() {
    Array.prototype.forEach.call(bandsEl.querySelectorAll('[data-open-seat]'), function (b) {
      var on = b.getAttribute('data-open-seat') === state.seatKey;
      b.setAttribute('aria-expanded', on ? 'true' : 'false');
      var card = b.closest('.hd-seat');
      if (card) card.classList.toggle('hd-current', on);
    });
  }
  /* A dossier opened on a short wide sheet (PEEK, or HALF on a small
     screen) gets the room it needs: the sheet grows by the shortfall, up
     to FULL, and goes back when the dossier closes unless the reader
     resized it meanwhile. Never remembered: the kept height is theirs. */
  function makeRoom() {
    if (!bodyEl || !state.open || state.grownFrom !== null) return;
    if (state.phone) {
      /* A phone's dossier covers the sheet under a sticky head and a
         sticky command bar: below FULL they meet. FULL while it is open. */
      if (state.snapPhone >= 3) return;
      state.grownFrom = state.h;
      applyHeight(snaps()[2]);
      state.grownTo = state.h;
      chromeMoved();
      return;
    }
    var short = DOSSIER_ROOM_PX - bodyEl.clientHeight;
    if (short <= 0 || state.h >= state.maxH) return;
    state.grownFrom = state.h;
    applyHeight(state.h + short);
    state.grownTo = state.h;
    chromeMoved();
  }
  /* The reader sized the sheet by hand while a dossier had grown it: the
     height is theirs now, and closing the dossier leaves it there. */
  function userSized() { state.grownFrom = state.grownTo = null; }
  function giveRoomBack() {
    if (state.grownFrom === null) return;
    if (state.open && state.h === state.grownTo) {
      applyHeight(state.phone ? snaps()[state.snapPhone - 1] : state.grownFrom);
      chromeMoved();
    }
    state.grownFrom = state.grownTo = null;
  }
  function openSeat(key, from) {
    if (!key) return;
    state.seatKey = key;
    state.seatRev = null;
    state.seatData = null;
    state.seatGone = false;
    state.seatFrom = key;
    state.seatFocus = true;
    root.classList.add('hd-has-seat');
    seatBox.hidden = false;
    clear(seatBox);
    add(seatBox, el('div', 'sv-loading', W('loading_seat')));
    markCurrent();
    loadOpeners();
    makeRoom();
    readSeat(key);
  }
  function closeDossier(returnFocus) {
    var key = state.seatFrom;
    state.seatKey = null;
    state.seatData = null;
    state.seatRev = null;
    state.seatGone = false;
    seatBox.hidden = true;
    clear(seatBox);
    root.classList.remove('hd-has-seat');
    markCurrent();
    giveRoomBack();
    if (returnFocus && key) {
      var b = bandsEl.querySelector('[data-open-seat="' + key + '"]');
      if (b) { try { b.focus(); } catch (e) { /* gone */ } }
    }
  }
  function readSeat(key) {
    get(withQuery('seat=' + encodeURIComponent(key)), null).then(function (d) {
      if (state.seatKey !== key || !d) return;
      if (d._locked) { halt(true); return; }
      if (d._out) { halt(false); return; }
      if (d._missing) { seatGone(); return; }
      if (d.ok === false) throw new Error(d.error || 'unavailable');
      state.seatData = d;
      state.seatRev = d.seat && d.seat.rev;
      paintDossier(d);
    }).catch(function () {
      if (state.seatKey !== key) return;
      clear(seatBox);
      add(seatBox, el('div', 'hd-err', W('seat_failed')));
      add(seatBox, button('hd-btn', W('retry'), function () { readSeat(key); }));
    });
  }
  function seatGone() {
    state.seatGone = true;
    clear(seatBox);
    add(seatBox, el('div', 'hd-state', W('seat_gone')));
    add(seatBox, button('hd-btn', W('back'), function () { closeDossier(true); }));
  }
  function kv(parent, rows) {
    var dl = add(parent, el('dl', 'hd-kv'));
    rows.forEach(function (r) {
      if (!r) return;
      var dt = add(dl, el('dt', '', r.label));
      var dd = add(dl, el('dd', '', r.t === undefined ? DASH : dash(r.t)));
      if (r.title) { dd.title = r.title; dt.title = r.title; }
      if (r.sub) add(dd, el('small', '', r.sub));
      if (r.progress_v !== undefined && r.progress_v !== null) {
        var rail = add(dd, el('span', 'hd-rail'));
        rail.style.display = 'block';
        var i = add(rail, el('i'));
        i.style.left = (Math.max(0, Math.min(1, r.progress_v)) * 100).toFixed(1) + '%';
      }
    });
    return dl;
  }
  function section(parent, id, titleText) {
    var sec = add(parent, el('section', 'hd-dos-sec'));
    sec.id = id;
    add(sec, el('h4', '', titleText));
    return sec;
  }
  function seatHeadText(s) {
    return s.symbol + ' ' + s.side_word + ' ' + (s.kind === 'bot' ? '#' + s.trade_id : 'pos #' + s.position_id);
  }
  function paintSeatHead(s) {
    var box = seatBox.querySelector('.hd-dos-live');
    if (!box) return;
    clear(box);
    var r1 = add(box, el('div', 'hd-seat-row'));
    add(r1, lightEl(s.light));
    add(r1, worldPill(s.world, s.world_word, s.world_title));
    var r2 = add(box, el('div', 'hd-seat-row'));
    if (s.working) add(r2, el('span', 'hd-wait', s.money.note));
    else {
      add(r2, el('span', toneCls(s.money.r_tone), s.money.r_t));
      add(r2, el('span', toneCls(s.money.pnl_tone), s.money.pnl_t + (s.money.pnl_v !== null && s.money.ccy ? ' ' + s.money.ccy : '')));
      if (s.mark.v === null || s.mark.v === undefined) add(r2, el('span', 'hd-wait', DASH + ' ' + (s.mark.wait || '')));
      else add(r2, el('span', '', s.mark.t + (s.mark.word ? ' ' + s.mark.word : '')));
    }
    /* Every reason that fired, in the sticky head, in a box of its own
       height (sv-horde.css): a long list scrolls there and never pushes
       the sections under the command bar. */
    var why = add(box, el('ul', 'hd-tl hd-dos-why'));
    (s.light.why || []).forEach(function (w) {
      var li = add(why, el('li'));
      li.style.display = 'block';
      add(li, el('span', 'hd-light--' + w.tone, w.t));
    });
  }
  function paintDossier(d) {
    var s = d.seat;
    /* A refresh (its facts moved, its levels were saved, its button) keeps
       the reader where they were; only the first paint after opening takes
       the focus to its heading. */
    var first = state.seatFocus;
    var keep = seatBox.scrollTop;
    state.seatFocus = false;
    clear(seatBox);
    seatBox.setAttribute('aria-label', fill(W('seat_label'), {
      sym: s.symbol, side: (s.side_word || '').toLowerCase(), id: s.trade_id || s.position_id }));
    var head = add(seatBox, el('div', 'hd-dos-head'));
    /* One row: the heading, then three compact buttons (2026-10-16: on a
       phone "Back to the Horde", "Refresh this seat" and the close took
       three rows of the pinned head). Their full names are their labels. */
    var row = add(head, el('div', 'hd-seat-row hd-dos-title'));
    var h3 = add(row, el('h3', '', seatHeadText(s)));
    h3.tabIndex = -1;
    var tools = add(row, el('span', 'hd-dos-tools'));
    if (!root.classList.contains('hd-w-l') || state.phone) {
      var back = add(tools, button('hd-btn', W('back'), function () { closeDossier(true); }));
      back.setAttribute('aria-label', W('back_label'));
    }
    var rf = add(tools, button('hd-icon-btn', '\u21bb', function () { readSeat(s.key); }));
    rf.setAttribute('aria-label', W('refresh_seat'));
    rf.title = W('refresh_seat');
    var x = add(tools, button('hd-icon-btn', '×', function () { closeDossier(true); }));
    x.setAttribute('aria-label', W('close_seat'));
    x.title = W('close_seat');
    add(head, el('div', 'hd-dos-live'));
    var chips = add(head, el('nav', 'hd-dos-chips'));
    [['mission', W('d_mission')], ['deployment', W('d_deployment')], ['metrics', W('d_metrics')],
     ['activity', W('d_activity')], ['voice', W('d_voice')], ['commands', W('d_commands')],
     ['instruments', W('d_instruments')]].forEach(function (c) {
      add(chips, button('hd-chip-btn', c[1], function () {
        var target = document.getElementById('svHordeSec-' + c[0]);
        /* The section's scroll-margin-top is the pinned head's measured
           height (sv-horde.css, --hd-dos-head-h): its heading lands
           under the head, never behind it. */
        measureDossierHead();
        if (target) target.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
      }));
    });
    paintSeatHead(s);

    var mi = d.mission || {};
    var sec = section(seatBox, 'svHordeSec-mission', W('t_mission'));
    var rows = [{ label: W('m_why'), t: mi.why }, { label: W('m_who'), t: mi.who },
                { label: W('m_signal'), t: mi.signal_t }];
    if (mi.reason || mi.score_t) rows.push({ label: W('m_reason'), t: [mi.reason, mi.score_t].filter(Boolean).join(' · ') });
    (mi.at_entry || []).forEach(function (a, i) {
      rows.push({ label: i ? '' : W('m_at_entry'), t: a.label + ': ' + a.t });
    });
    if (mi.debate) rows.push({ label: W('m_debate'), t: mi.debate.t });
    if ((mi.tags || []).length) rows.push({ label: W('m_tags'), t: mi.tags.join(' · ') });
    if (mi.rule_stage_t) rows.push({ label: W('m_rule'), t: mi.rule_stage_t });
    if (mi.plan) rows.push({ label: W('m_plan'), t: mi.plan.t });
    /* The Orc's own slot, said as the Orc's; the thesis check that HAS
       read the seat is named under it, so the two never contradict. */
    rows.push({ label: W('m_thesis'), t: mi.thesis || W('no_thesis'), sub: mi.thesis_note || '' });
    kv(sec, rows);

    sec = section(seatBox, 'svHordeSec-deployment', W('t_deployment'));
    kv(sec, d.deployment || []);

    sec = section(seatBox, 'svHordeSec-metrics', W('t_metrics'));
    kv(sec, d.metrics || []);
    add(sec, el('h4', '', W('t_stops')));
    kv(sec, (d.stops || []).map(function (x) { return { label: x.label, t: x.t + (x.why ? ' (' + x.why + ')' : '') }; }));

    sec = section(seatBox, 'svHordeSec-activity', W('t_activity'));
    if (d.timeline_now) add(sec, el('div', 'hd-note gold', d.timeline_now));
    if ((d.timeline || []).length) {
      var tl = add(sec, el('ol', 'hd-tl'));
      d.timeline.forEach(function (e) {
        var li = add(tl, el('li'));
        var t = add(li, el('time', 'hd-muted', e.at ? stamp(e.at) : DASH));
        if (e.at) { t.setAttribute('datetime', e.at); t.title = e.at; }
        add(li, el('span', 'hd-author', e.author));
        add(li, el('span', '', e.t));
      });
    } else {
      add(sec, el('div', 'hd-muted', d.timeline_empty));
    }
    if (d.timeline_note) add(sec, el('div', 'hd-muted', d.timeline_note));
    if (s.links && s.links.story) add(sec, link('hd-link', W('full_story'), s.links.story));

    sec = section(seatBox, 'svHordeSec-voice', W('t_voice'));
    paintVoice(sec, d.voice || {});

    section(seatBox, 'svHordeSec-commands', W('t_commands'));
    add(seatBox, el('div', 'hd-cmds hd-cmd-links')).id = 'svHordeCmdLinks';
    if ((d.phone || []).length) {
      sec = add(seatBox, el('section', 'hd-dos-sec'));
      add(sec, el('h4', '', W('t_phone')));
      /* Each command with its own Copy, which says what it copies
         (2026-10-16: one Copy under three commands). */
      var ul = add(sec, el('ul', 'hd-tl hd-phone-cmds'));
      d.phone.forEach(function (p) {
        var li = add(ul, el('li'));
        add(li, el('code', 'hd-cmd-text', p.cmd));
        var copy = add(li, button('hd-btn hd-copy', W('copy')));
        copy.setAttribute('aria-label', fill(W('copy_label'), { cmd: p.cmd }));
        copy.setAttribute('data-copy', p.cmd);
        copy.addEventListener('click', function () {
          try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
              navigator.clipboard.writeText(p.cmd).then(function () { copy.textContent = W('copied'); },
                                                        function () { /* the reader copies by hand */ });
            }
          } catch (e) { /* the reader copies by hand */ }
        });
        add(li, el('span', 'hd-muted', p.t));
      });
    }

    sec = section(seatBox, 'svHordeSec-instruments', W('t_instruments'));
    paintInstruments(sec, d.instruments || {}, s);
    /* The command bar is the dossier's own LAST child, not its section's:
       sticky at the bottom, it stays on screen over every section, the
       last one included (round 2: placed after the Commands heading, it
       scrolled away once Instruments was read). */
    add(seatBox, el('div', 'hd-cmds hd-dos-cmdbar')).id = 'svHordeCmds';
    paintCommands(d);
    measureDossierHead();
    if (first) { try { h3.focus(); } catch (e) { /* no focus */ } }
    else seatBox.scrollTop = keep;
  }
  /* The pinned head's height, for the sections' scroll-margin-top. */
  function measureDossierHead() {
    var h = seatBox.querySelector('.hd-dos-head');
    if (!h) return;
    var r = h.getBoundingClientRect();
    seatBox.style.setProperty('--hd-dos-head-h', Math.ceil(r.height || 0) + 'px');
  }
  function voiceBox(parent, heading, cls) {
    var box = add(parent, el('div', 'hd-voice' + (cls ? ' ' + cls : '')));
    add(box, el('b', '', heading));
    return box;
  }
  function paintVoice(sec, v) {
    var rv = v.reviewer || {};
    var b = voiceBox(sec, W('v_reviewer'));
    if (!rv.present) add(b, el('div', 'hd-muted', rv.t));
    else {
      add(b, el('div', '', fill(W('review_line'), { verdict: rv.word, age: rv.age_t, c: dash(rv.confidence_t) })));
      (rv.triggers || []).forEach(function (t) { add(b, el('div', 'hd-muted', '· ' + t.t)); });
      if (rv.reasoning) {
        /* Plain pre-wrapped text, cut at the server's mark with a "more"
           that unfolds the rest in place. */
        var full = String(rv.reasoning), cut = rv.reasoning_cut;
        var pre = add(b, el('pre', '', cut ? full.slice(0, cut) + '…' : full));
        if (cut) {
          var more = add(b, button('hd-expander', W('more'), function () {
            pre.textContent = full;
            if (more.parentNode) more.parentNode.removeChild(more);
          }));
        }
      }
      if (rv.suggested_stop_t) add(b, el('div', '', fill(W('suggested'), { x: rv.suggested_stop_t })));
      if (rv.take_part_t) add(b, el('div', '', rv.take_part_t));
    }
    var th = v.thesis || {};
    b = voiceBox(sec, W('v_thesis'));
    if (th.word) {
      add(b, el('div', '', fill(W('thesis_read'), { verdict: th.word, age: dash(th.age_t), words: th.words })));
      if (th.stop_t) add(b, el('div', '', fill(W('structure_stop'), { x: th.stop_t })));
      if (th.applies) add(b, el('div', 'hd-muted', th.applies));
    } else {
      add(b, el('div', 'hd-muted', th.t));
    }
    var c = v.care || {};
    b = voiceBox(sec, W('v_care'));
    add(b, el('div', '', c.words));
    if (c.suffix) add(b, el('div', 'hd-muted', c.suffix));
    /* c.readback (2026-10-31): a hand-taken short eToro holds otherwise
       than it was sent, read back at the fill. */
    [c.readback, c.soft_t, c.venue_t, c.refusal, c.event, c.none_t].forEach(function (t) {
      if (t) add(b, el('div', '', t));
    });
    b = voiceBox(sec, W('v_notes'));
    add(b, el('div', 'hd-muted', (v.notes && v.notes.t) || ''));
    b = voiceBox(sec, W('v_orc'), 'hd-orc');
    if (v.orc && v.orc.label) {
      paintOrc(b, v.orc);
    } else {
      ((v.orc_block && v.orc_block.t && v.orc_block.t.length && v.orc_block.t) ||
       [W('no_orc_seated'), W('not_decided'), W('orc_arrives')])
        .forEach(function (t) { add(b, el('div', '', t)); });
    }
  }
  /* The trader agent's slot, every line through el() (textContent): the
     operator's own thesis and the journal stay text, never markup. */
  function paintOrc(b, o) {
    var au = o.authority || {}, th = o.thesis || {}, li = o.lineage || {};
    add(b, el('div', '', fill(W('orc_state'), { t: o.state_t })));
    add(b, el('div', '', fill(W('orc_rank'), { t: au.level_t })));
    add(b, el('div', '', fill(W('orc_thesis'), { source: th.source_t || '', t: th.t || DASH })));
    (th.invalidation_t || []).forEach(function (t) { add(b, el('div', 'hd-muted', '· ' + t)); });
    if (o.plan_line) add(b, el('div', 'hd-muted', fill(W('orc_plan'), { t: o.plan_line })));
    if (o.risk_line) add(b, el('div', '', fill(W('orc_risk'), { t: o.risk_line })));
    if (o.care_compare && o.care_compare.t) add(b, el('div', '', fill(W('orc_compare'), { t: o.care_compare.t })));
    if (o.latest_note) add(b, el('div', '', o.latest_note));
    if (o.army && o.army.type_t) add(b, el('div', 'hd-muted', fill(W('orc_army'), { t: o.army.type_t })));
    if (o.intellect) {
      add(b, el('div', 'hd-muted', fill(W('orc_score'), { score: o.intellect.score_t, rung: o.intellect.rung_t })));
    }
    if (o.integrity && o.integrity.t) add(b, el('div', 'hd-muted', fill(W('orc_integrity'), { t: o.integrity.t })));
    add(b, el('div', 'hd-muted', fill(W('orc_lineage'), { rank: li.rank_t || '', n: li.provisional_t || '' })));
    if ((o.journal || []).length) {
      add(b, el('div', 'hd-muted', W('orc_journal')));
      o.journal.slice(-3).reverse().forEach(function (j) {
        add(b, el('div', '', (j.at ? stamp(j.at) : DASH) + ' · ' + (j.author || '') + ' · ' + (j.t || '')));
      });
    }
    if ((o.drums || []).length) {
      add(b, el('div', 'hd-muted', W('orc_drums')));
      o.drums.forEach(function (d) {
        add(b, el('div', '', (d.at ? stamp(d.at) : DASH) + ' · ' + d.kind_t + (d.from_symbol ? ' · ' + d.from_symbol : '')));
      });
    }
    if (o.page) add(b, link('hd-link', fill(W('orc_open'), { label: o.label }), o.page));
  }
  /* The bar holds the buttons alone, so it stays one short strip on any
     width; what is unavailable, and the links, sit in the row under it. */
  function paintCommands(d) {
    var box = document.getElementById('svHordeCmds');
    if (!box || !d || !d.seat) return;
    var s = d.seat;
    var cmd = s.commands || {};
    clear(box);
    var lbox = document.getElementById('svHordeCmdLinks') || box;
    if (lbox !== box) clear(lbox);
    var side = (s.side_word || '').toLowerCase();
    var ident = s.trade_id || s.position_id;
    /* On a phone the bar's cell holds "Ask Sauron" on one line (final
       review: the full label wrapped to two); the seat is the dossier's. */
    var ask = add(box, button('hd-btn', state.phone ? W('c_ask_short') : W('c_ask'), function () {
      if (window.askSauronAbout) window.askSauronAbout(cmd.ask.subject, 'position', cmd.ask.facts);
    }));
    ask.title = W('c_ask');
    if (cmd.advice && window.SVCloseAdvice) {
      var adv = add(box, button('hd-btn', W('c_advice')));
      adv.setAttribute('data-sv-advice-ids', String(s.trade_id));
      adv.setAttribute('data-sv-advice-no-close', '1');
    }
    if (cmd.levels && window.SVLevelEdit) {
      var L = cmd.levels;
      var lv = add(box, button('hd-btn hd-money lvl-edit', W('c_levels')));
      lv.setAttribute('data-lvl-trade', L.trade);
      lv.setAttribute('data-lvl-symbol', L.symbol);
      lv.setAttribute('data-lvl-side', L.side);
      lv.setAttribute('data-lvl-stop', L.stop);
      lv.setAttribute('data-lvl-target', L.target);
      lv.setAttribute('data-lvl-decimals', String(L.decimals));
      lv.setAttribute('data-lvl-live', L.live);
      lv.setAttribute('data-lvl-protected', L.protected);
      lv.setAttribute('aria-label', fill(W('c_levels_aria'), { sym: s.symbol, side: side, id: ident }));
      lv.title = W('c_confirm');
    } else if (cmd.levels && state.lvlFailed) {
      add(lbox, el('span', 'hd-muted', W('c_lvl_failed')));
      add(lbox, link('hd-link', W('positions_link'), root.getAttribute('data-positions-url')));
    } else if (cmd.close && !cmd.levels) {
      add(lbox, el('span', 'hd-cmd-cap', W('c_levels_open_only')));
    }
    if (cmd.close) {
      var c = add(box, button('btn btn-sm btn-danger hd-btn hd-money', cmd.close_label));
      c.setAttribute('data-sv-close-trade', String(s.trade_id));
      c.setAttribute('aria-label', fill(W('c_close_aria'), { sym: s.symbol, side: side, id: ident }));
      c.title = W('c_confirm');
    }
    if (cmd.close || cmd.levels) {
      /* Beside the money buttons on a wide screen, under the bar on a
         phone, where the bar is a two-by-two grid of buttons. */
      add(box, el('span', 'hd-cmd-cap hd-cap-bar', W('c_confirm')));
      add(lbox, el('span', 'hd-cmd-cap hd-cap-row', W('c_confirm')));
    }
    if (!cmd.close && !cmd.levels && !cmd.advice) add(lbox, el('span', 'hd-muted', W('c_none')));
    var links = s.links || {};
    if (links.story) add(lbox, link('hd-link', W('full_story'), links.story));
    if (links.page) add(lbox, link('hd-link', W('c_page'), links.page));
    if (links.chart) {
      var ch = add(lbox, link('hd-link', W('c_chart'), links.chart));
      ch.title = W('chart_label');
    }
  }
  function paintInstruments(sec, ins, s) {
    var u = ins.underlying || {};
    add(sec, el('h4', '', W('t_underlying')));
    var r = add(sec, el('div', 'hd-seat-row'));
    add(r, el('span', '', fill(W('platform_instrument'), { symbol: u.symbol })));
    if (u.page) add(r, link('hd-link', W('c_page'), u.page));
    if (u.chart) { var c = add(r, link('hd-link', W('c_chart'), u.chart)); c.title = W('chart_label'); }
    if (u.venue_id) add(sec, el('div', '', fill(W('at_etoro'), { id: u.venue_id })));
    if (u.stand_in_t) add(sec, el('div', 'hd-wait', u.stand_in_t));
    if (u.market_t) add(sec, el('div', 'hd-muted', u.market_t));
    add(sec, button('hd-btn', fill(W('ask_about'), { symbol: u.symbol }), function () {
      if (window.askSauronAbout) window.askSauronAbout(u.symbol, 'instrument');
    }));
    add(sec, el('h4', '', W('t_correlated')));
    var peers = ins.peers || [];
    if (!peers.length) add(sec, el('div', 'hd-muted', ins.empty_t));
    else {
      /* One row per peer that WRAPS inside the dossier column (2026-10-16:
         a six-column table overflowed 380-520px, clipped "Long…" to "L"
         and broke "moderate · 180 bars" over three lines). The server
         sends the strongest |rho| first, the SMT partner and the complex
         always kept; the viewer's own seats are marked. */
      var list = add(sec, el('ul', 'hd-peers'));
      peers.forEach(function (p) {
        var li = add(list, el('li', 'hd-peer' + (p.is_seat ? ' hd-peer--seat' : '')));
        var top = add(li, el('div', 'hd-peer-row'));
        add(top, el('b', '', p.symbol));
        var rho = add(top, el('span', 'hd-peer-rho', p.measured ? p.rho_t : DASH));
        if (p.measured) {
          rho.title = fill(W('bars'), { n: p.n_bars });
          add(top, el('span', 'hd-muted', p.strength));
        } else {
          add(top, el('span', 'hd-muted', fill(W('unmeasured_bars'), { n: p.n_bars || 0 })));
        }
        /* A seat peer wears its book's pill, as on the cards: a paper
           seat never reads like a real one (round 2, rule 4). */
        if (p.is_seat) add(top, worldPill(p.seat_world || '', p.seat_world_word || '', p.seat_world_title || ''));
        add(top, el('span', 'hd-chip', p.relation));
        if (p.is_seat && p.relation.indexOf('YOUR ') !== 0) add(top, el('span', 'hd-chip ok', W('your_seat')));
        if (p.bet_t) add(top, el('span', 'hd-wait', p.bet_t));
        /* A price with no measured day change shows a dash there, with the
           server's reason: an empty slot read as "no move" (final review). */
        var px_ = add(top, el('span', 'hd-peer-last', dash(p.last_t)));
        if (p.change_t) add(px_, txt(' ' + p.change_t));
        else if (p.last_t && p.change_why) {
          add(px_, txt(' '));
          add(px_, el('span', 'sv-unknown', DASH)).title = p.change_why;
        }
        px_.setAttribute('data-peer-last', p.symbol);
        var acts = add(li, el('div', 'hd-peer-acts'));
        if (p.is_seat && p.seat_key) {
          add(acts, button('hd-btn', W('seat_go'), function () { openSeat(p.seat_key); }));
        } else {
          if (p.page) add(acts, link('hd-link', W('page_go'), p.page));
          if (p.ticket) {
            ['BUY', 'SELL'].forEach(function (side) {
              var t = add(acts, button('hd-btn hd-money', side === 'BUY' ? W('long') : W('short'), function () {
                if (window.svTakeTradeAsset) window.svTakeTradeAsset(p.symbol, side);
              }));
              t.title = W('ticket_title');
            });
          }
          add(acts, button('hd-btn', W('ask_go'), function () {
            if (window.askSauronAbout) window.askSauronAbout(p.symbol, 'instrument');
          }));
        }
      });
    }
    if ((ins.chips || []).length) add(sec, el('div', 'hd-bet', ins.chips.join(' · ')));
    (s.same_bet || []).forEach(function (t) { add(sec, el('div', 'hd-bet', fill(W('same_bet'), { words: t }))); });
    if (ins.note) add(sec, el('div', 'hd-muted', ins.note));
  }

  /* ── size by hand: drag, double-click, keys, buttons ─────────────── */
  var drag = null, raf = 0;
  function dragStart(e) {
    if (!state.open) return;
    if (e.button !== undefined && e.button !== 0) return;
    if (e.currentTarget === head) {
      if (!state.phone) return;
      /* The title row drags; the limits underneath scroll. */
      if (e.target.closest && e.target.closest('button, a, input, select, textarea, #svHordeTable')) return;
    }
    measure();
    var now = Date.now();
    drag = { id: e.pointerId, y: e.clientY, h: state.h, lastY: e.clientY, lastT: now, v: 0, src: e.currentTarget };
    state.dragH = state.h;
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch (x) { /* fine without */ }
    document.body.classList.add('sv-horde-resizing');
    e.preventDefault();
  }
  function dragMove(e) {
    if (!drag || e.pointerId !== drag.id) return;
    var now = Date.now();
    drag.v = (drag.lastY - e.clientY) / Math.max(1, now - drag.lastT);
    drag.lastY = e.clientY;
    drag.lastT = now;
    state.dragH = drag.h + (drag.y - e.clientY);
    if (raf) return;
    raf = window.requestAnimationFrame(function () {
      raf = 0;
      root.style.setProperty('--horde-h', Math.max(0, Math.min(state.maxH, state.dragH)) + 'px');
    });
  }
  function dragEnd(e) {
    if (!drag || (e && e.pointerId !== drag.id)) return;
    var h = state.dragH === null ? drag.h : state.dragH;
    var v = drag.v;
    var still = Math.abs(drag.y - drag.lastY) < 4 && state.dragH === drag.h;
    drag = null;
    state.dragH = null;
    document.body.classList.remove('sv-horde-resizing');
    /* A press that did not move is a click, not a resize: nothing snaps,
       nothing is kept, the height stays the reader's (a double-click on
       the grip then cycles PEEK, HALF, FULL; a tap on a phone's head
       never pins FULL). */
    if (still) { applyHeight(state.h); return; }
    var s = snaps();
    if (h < s[0] / 2) {
      applyHeight(state.lastGoodH || state.h);
      setOpen(false, 'drag');
      return;
    }
    var target = h;
    if (state.phone) {
      var i = nearestSnap(h);
      if (Math.abs(v) > FLING_PX_PER_MS) i = Math.max(0, Math.min(s.length - 1, i + (v > 0 ? 1 : -1)));
      target = s[i];
    } else {
      s.forEach(function (p) { if (Math.abs(p - h) <= SNAP_PULL_PX) target = p; });
    }
    applyHeight(target);
    state.lastGoodH = state.h;
    userSized();
    persistHeight();
    chromeMoved();
  }
  [grip, head].forEach(function (n) {
    if (!n) return;
    n.addEventListener('pointerdown', dragStart);
    n.addEventListener('pointermove', dragMove);
    n.addEventListener('pointerup', dragEnd);
    n.addEventListener('pointercancel', dragEnd);
  });
  grip.addEventListener('dblclick', function () {
    if (!state.open) return;
    var s = snaps(), i = nearestSnap(state.h);
    applyHeight(s[(i + 1) % s.length]);
    state.lastGoodH = state.h;
    userSized();
    persistHeight();
    chromeMoved();
  });
  function nextSnap(dir) {
    var s = snaps();
    if (dir > 0) { for (var i = 0; i < s.length; i++) if (s[i] > state.h + 1) return s[i]; return s[s.length - 1]; }
    for (var j = s.length - 1; j >= 0; j--) if (s[j] < state.h - 1) return s[j];
    return s[0];
  }
  grip.addEventListener('keydown', function (e) {
    var k = e.key, s = snaps(), h = state.h, step = e.shiftKey ? 96 : 24;
    if (k === 'Enter') { e.preventDefault(); setOpen(!state.open, 'key'); return; }
    /* A phone has snap points only, no free height: an arrow is a snap. */
    if (k === 'ArrowUp') h = state.phone ? nextSnap(1) : h + step;
    else if (k === 'ArrowDown') h = state.phone ? nextSnap(-1) : h - step;
    else if (k === 'PageUp') h = nextSnap(1);
    else if (k === 'PageDown') h = nextSnap(-1);
    else if (k === 'Home') h = s[0];
    else if (k === 'End') h = s[s.length - 1];
    else return;
    e.preventDefault();
    if (!state.open) return;
    applyHeight(h);
    state.lastGoodH = state.h;
    userSized();
    /* The height is the reader's at once (a re-measure in the next 300 ms
       must not put the old one back); only the keeping waits. */
    if (state.phone) state.snapPhone = nearestSnap(state.h) + 1;
    else if (state.maxH) state.frac = state.h / state.maxH;
    chromeMoved();
    if (state.persistTimer) window.clearTimeout(state.persistTimer);
    state.persistTimer = window.setTimeout(persistHeight, 300);
  });
  Array.prototype.forEach.call(root.querySelectorAll('[data-snap]'), function (b) {
    b.addEventListener('click', function () {
      measure();
      var s = snaps(), which = b.getAttribute('data-snap');
      applyHeight(which === 'peek' ? s[0] : which === 'full' ? s[2] : s[1]);
      state.lastGoodH = state.h;
      userSized();
      persistHeight();
      chromeMoved();
    });
  });
  Array.prototype.forEach.call(lensBtns, function (b) {
    b.addEventListener('click', function () {
      state.lens = b.getAttribute('data-lens') || 'all';
      store(LENS_KEY, state.lens);
      if (state.board) { paintLens(state.board); paintTable(state.board); applyFilters(); }
    });
  });

  /* ── the tab, the close button, Escape, h ────────────────────────── */
  tab.addEventListener('click', function (e) {
    setOpen(!state.open, e && e.detail === 0 ? 'key' : 'pointer');
  });
  if (closeBtn) closeBtn.addEventListener('click', function () {
    setOpen(false, 'key');
    try { tab.focus(); } catch (e) { /* an old engine */ }
  });
  document.addEventListener('keydown', function (e) {
    if (e.defaultPrevented) return;
    if (e.key !== 'Escape' && e.key !== 'Esc') return;
    var at = document.activeElement;
    if (!at || at === document.body) return;
    if (!seatBox.hidden && seatBox.contains(document.activeElement)) {
      e.preventDefault();
      closeDossier(true);
      return;
    }
    if (state.open && root.contains(document.activeElement)) {
      e.preventDefault();
      setOpen(false, 'key');
      try { tab.focus(); } catch (x) { /* an old engine */ }
    }
  });
  window.SVHorde = {
    toggle: function (how) { setOpen(!state.open, how || 'key'); }
  };

  /* ── the page's own signals ──────────────────────────────────────── */
  function bookMoved(seatTouched) {
    if (state.evTimer) window.clearTimeout(state.evTimer);
    state.evTimer = window.setTimeout(function () {
      state.evTimer = null;
      if (state.open && !document.hidden) readBoard('book'); else readTab('book');
      if (seatTouched && state.seatKey && state.open) readSeat(state.seatKey);
    }, EVENT_DEBOUNCE_MS);
  }
  document.addEventListener('sv:eye-event', function (e) {
    var msg = (e && e.detail) || {};
    var kind = msg.kind || msg.event_type || msg.type;
    if (!BOOK_KINDS[kind]) return;
    if (!state.open) { state.moves += 1; paintMoves(); }
    var data = msg.data || {};
    var tid = String(data.trade_id || msg.trade_id || '');
    bookMoved(!!(tid && state.seatKey === 'bot:' + tid));
  });
  document.addEventListener('sv:levels-saved', function (e) {
    var t = String((e && e.detail && e.detail.trade) || '');
    if (state.open && !document.hidden) readBoard('levels'); else readTab('levels');
    if (t && state.seatKey === 'bot:' + t) readSeat(state.seatKey);
  });
  document.addEventListener('sv:pin-unlocked', function () {
    state.stopped = false;
    if (state.open && !document.hidden) readBoard('unlock'); else readTab('unlock');
  });
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) return;
    if (state.open && !document.hidden) readBoard('visible');
    else if (Date.now() - state.lastTabAt > TAB_STALE_MS) readTab('visible');
  });
  /* The strip's own count, mirrored for free: two writers rewrite it (the
     live sweep's hb-pos-count region and refreshPanelCounts after a close). */
  var countEl = document.getElementById('ipPositionsCount');
  if (countEl && window.MutationObserver) {
    var lastCount = (countEl.textContent || '').trim();
    new window.MutationObserver(function () {
      var now = (countEl.textContent || '').trim();
      if (now === lastCount) return;
      lastCount = now;
      var n = parseInt(now, 10);
      if (isFinite(n)) { state.seatN = n; seatsEl.textContent = seatWords(n); fitTab(); }
      bookMoved(false);
    }).observe(countEl, { childList: true, characterData: true, subtree: true });
  }
  /* A wrapped row of "·"-joined boxes: the box that ends a line keeps its
     dot's room but not its ink, so no line ends on a dangling dot and none
     opens with one (final review). Measured after layout, again on every
     resize; a box whose next one starts lower ends its line. */
  var eolRaf = 0;
  function lineEndsSoon() {
    if (eolRaf || !window.requestAnimationFrame) return;
    eolRaf = window.requestAnimationFrame(function () { eolRaf = 0; lineEnds(); });
  }
  function lineEnds() {
    if (!state.open) return;
    Array.prototype.forEach.call(root.querySelectorAll('.hd-unit'), function (u) {
      var next = u.nextElementSibling;
      var eol = !!(next && typeof u.offsetTop === 'number' && typeof next.offsetTop === 'number'
                   && u.offsetHeight > 0 && next.offsetTop >= u.offsetTop + u.offsetHeight / 2);
      u.classList.toggle('hd-eol', eol);
    });
  }
  var remeasureRaf = 0;
  function remeasureSoon() {
    if (remeasureRaf) return;
    remeasureRaf = window.requestAnimationFrame(function () { remeasureRaf = 0; remeasure(); });
  }
  window.addEventListener('resize', function () { remeasureSoon(); tier(); fitDossier(); lineEndsSoon(); });
  document.addEventListener('transitionend', function (e) {
    if (e.target && root.contains(e.target)) return;
    remeasureSoon();
  });
  if (window.ResizeObserver) {
    try { new window.ResizeObserver(tier).observe(root); } catch (e) { /* the window's resize covers it */ }
    try { if (bodyEl) new window.ResizeObserver(fitDossier).observe(bodyEl); } catch (e) { /* below */ }
    try { if (bandsEl) new window.ResizeObserver(lineEndsSoon).observe(bandsEl); } catch (e) { /* the resize covers it */ }
    try { if (head) new window.ResizeObserver(lineEndsSoon).observe(head); } catch (e) { /* the resize covers it */ }
  }
  if (phoneMq) {
    var onPhone = function (e) { setPhone(e.matches); };
    if (phoneMq.addEventListener) phoneMq.addEventListener('change', onPhone);
    else if (phoneMq.addListener) phoneMq.addListener(onPhone);
  }

  /* ── first paint ─────────────────────────────────────────────────── */
  setPhone(phoneMq && phoneMq.matches);
  applyHeight(state.h);
  paintTabWords();
  function firstTab() { if (!document.hidden && !state.open) readTab('load'); }
  if (window.requestIdleCallback) window.requestIdleCallback(firstTab, { timeout: 1500 });
  else window.setTimeout(firstTab, 1500);
  /* A Horde left open comes back open, in place rather than sliding — on
     a wide screen only: a phone never restores it over the page. */
  if (!state.phone && load(OPEN_KEY) === '1') {
    root.classList.add('sv-horde--instant');
    setOpen(true, 'restore');
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () { root.classList.remove('sv-horde--instant'); });
    });
  }
})();
