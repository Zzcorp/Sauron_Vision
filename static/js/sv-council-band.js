/* THE COUNCIL BAND (task #104, 2026-10-22) — Sauron's voices on the right
 * edge: what Sauron thinks now, who disagrees, who has been right.
 *
 * templates/_partials/council_band.html draws the shell (staff only: for
 * anyone else it is not in the page and this file does nothing);
 * static/css/sv-council-band.css places it; the data is GET
 * /api/council/band/ (dashboard/views_council_band.py), the one URL this
 * file ever asks, by GET only. Nothing here writes, sends or acts: its one
 * link to a model is the page's own Ask Sauron panel (askSauronAbout).
 *
 *   SHUT     only the tab shows; no timer, no read. A council_sitting on
 *            the shared sv:eye-event raises the tab's badge and nothing
 *            else (base.html owns the one /ws/eye/ socket).
 *   OPEN     the room (up to 400px). One interval: every TICK_MS the ages
 *            are refreshed, every READ_EVERY ticks the room is read, and
 *            the side overlay's tab when it is stale. 800 ms after a fill
 *            or a sitting, an event read.
 *   CHAMBER  up to 880px, the room and the side column together; only
 *            with CHAMBER_MIN_W of room and the Horde shut.
 *   hidden   nothing is read: the tick returns at once, read() refuses
 *            and an event read waits; on return, a read if the last one
 *            is older than a minute.
 *   stopped  423 (until sv:pin-unlocked), a redirect or a non-JSON body
 *            (signed out), 403 (staff only).
 *
 * Only one of the band and the activity drawer is open at a time
 * (sv:dock-open). Escape steps back one level, from inside the band only.
 * The shut tab is placed by measure so it never stands on the rail's
 * toggle, which the open Horde moves. Rows are built with textContent and
 * createElement only; every sentence arrived formatted from the server and
 * every static label is in the partial's #svCouncilBandWords.
 */
(function () {
  'use strict';
  var root = document.getElementById('svCouncilBand');
  if (!root) return;

  var BAND_URL = root.getAttribute('data-band-url') || '';
  var TICK_MS = 30000;
  var READ_EVERY = 2;
  var EVENT_DELAY_MS = 800;
  var READ_MIN_GAP_MS = 10000;
  var CHAMBER_MIN_W = 760;
  var STALE_ROOM_MS = 60000;
  var SIDE_STALE_MS = { sittings: 60000, record: 600000 };
  var OPEN_KEY = 'sauron_council_band_open', FOLD_KEY = 'sauron_council_band_fold', SIDE_KEY = 'sauron_council_band_side';
  var SVG_NS = 'http://www.w3.org/2000/svg';
  var TAB_H = 112, TAB_GAP = 16;
  var SIDE_WORD = { 'for': 'side_for', against: 'side_against', none: 'side_none', silent: 'side_silent', waiting: 'side_waiting', absent: 'side_absent' };
  var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var mq = window.matchMedia ? window.matchMedia('(min-width: 769px)') : null;

  var tab = document.getElementById('svCouncilBandTab');
  var panel = document.getElementById('svCouncilBandPanel');
  var badge = document.getElementById('svCouncilBandBadge');
  var sayBox = document.getElementById('svCouncilBandSay');
  var dot = document.getElementById('svCouncilBandDot');
  var stamp = document.getElementById('svCouncilBandStamp');
  var chipsBox = document.getElementById('svCouncilBandChips');
  var titleEl = document.getElementById('svCouncilBandTitle');
  var widenBtn = document.getElementById('svCouncilBandWiden');
  var closeBtn = document.getElementById('svCouncilBandClose');
  var stateBox = document.getElementById('svCouncilBandState');
  var roomEl = document.getElementById('svCouncilBandRoom');
  var sideEl = document.getElementById('svCouncilBandSide');
  var sideBody = document.getElementById('svCouncilBandSideBody');
  var sideBack = document.getElementById('cbSideBack');
  var dossierEl = document.getElementById('svCouncilBandDossier');
  var secs = {
    direction: document.getElementById('cbDirection'),
    throne: document.getElementById('cbThrone'),
    nine: document.getElementById('cbNine'),
    traders: document.getElementById('cbTraders')
  };
  var tabBtns = root.querySelectorAll('.cb-tabbtn');
  if (!tab || !panel || !roomEl || !BAND_URL) return;

  var state = {
    open: false, chamber: false, over: false, side: 'sittings',
    sitting: null, sittingFocus: false, dossier: null, opener: null, ticks: 0, stopped: '',
    unread: 0, filter: 'all', lastAt: 0, readAt: {}, revs: {},
    sittings: null, record: null, older: null
  };
  var timer = null, eventTimer = null, inflight = {}, framePending = false;

  /* ── words ───────────────────────────────────────────────────────── */
  var WORDS = {};
  (function () {
    var tpl = document.getElementById('svCouncilBandWords');
    var box = tpl && (tpl.content || tpl);
    if (!box) return;
    var spans = box.querySelectorAll('[data-w]');
    for (var i = 0; i < spans.length; i++) WORDS[spans[i].getAttribute('data-w')] = spans[i].textContent;
  })();
  function W(key, vars) {
    var t = WORDS[key] || '';
    if (vars) {
      for (var k in vars) {
        if (Object.prototype.hasOwnProperty.call(vars, k)) t = t.split('{' + k + '}').join(String(vars[k]));
      }
    }
    return t;
  }

  /* ── small things ────────────────────────────────────────────────── */
  function desk() {
    return !mq || mq.matches;
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null && text !== '') n.textContent = String(text);
    return n;
  }
  function clear(n) { while (n && n.firstChild) n.removeChild(n.firstChild); }
  function add(parent, child) { if (child) parent.appendChild(child); return child; }
  function lines(parent, list, cls) {
    (list || []).forEach(function (t) { if (t) add(parent, el('p', 'cb-line' + (cls ? ' ' + cls : ''), t)); });
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function hms(ms) {
    var d = new Date(ms);
    return pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ':' + pad(d.getUTCSeconds());
  }
  function ago(ms) {
    var s = Math.max(0, (Date.now() - ms) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + ' min ago';
    return Math.floor(s / 3600) + ' h ago';
  }
  function safeLink(u) {
    u = String(u || '');
    return (u.charAt(0) === '/' && u.charAt(1) !== '/') ? u : '';
  }
  function say(t) { if (sayBox && t) sayBox.textContent = t; }
  function setDot(cls) {
    if (!dot) return;
    dot.classList.remove('live', 'err');
    if (cls) dot.classList.add(cls);
  }
  function setStamp() {
    if (!stamp) return;
    stamp.textContent = state.lastAt ? W('read_ago', { t: ago(state.lastAt) }) : '';
  }
  function setState(cls, words) {
    clear(stateBox);
    if (!cls) return;
    add(stateBox, el('div', cls, words));
  }
  /* A periodic read that repaints a view must not drop the reader: what
     they stand on is marked (its sitting or voice, else its words, else
     its place among the view's controls) and its replacement focused,
     never <body>, where Escape would go dead. */
  var CONTROLS = 'button, a[href], summary';
  function focusMark(box) {
    var at = document.activeElement;
    if (!box || !at || at === document.body || !box.contains(at)) return null;
    var all = Array.prototype.slice.call(box.querySelectorAll(CONTROLS));
    return { sitting: at.getAttribute('data-sitting'), voice: at.getAttribute('data-voice'),
             text: at.textContent, index: all.indexOf(at) };
  }
  function refocus(box, mark) {
    if (!mark) return;
    var all = Array.prototype.slice.call(box.querySelectorAll(CONTROLS));
    function pick(fn) { for (var i = 0; i < all.length; i++) { if (fn(all[i])) return all[i]; } return null; }
    var to = (mark.sitting && pick(function (n) { return n.getAttribute('data-sitting') === mark.sitting; }))
      || (mark.voice && pick(function (n) { return n.getAttribute('data-voice') === mark.voice; }))
      || (mark.text && pick(function (n) { return n.textContent === mark.text; }))
      || (mark.index >= 0 && all.length ? all[Math.min(mark.index, all.length - 1)] : null);
    var tries = [to, titleEl];
    for (var k = 0; k < tries.length; k++) {
      if (!tries[k]) continue;
      try { tries[k].focus({ preventScroll: true }); } catch (e) { /* an old engine */ }
      if (document.activeElement === tries[k]) return;
    }
  }
  function repaint(box, fn) {
    var mark = focusMark(box);
    fn();
    refocus(box, mark);
  }
  function refreshAges() {
    var spans = root.querySelectorAll('.cb-age[data-at]');
    for (var i = 0; i < spans.length; i++) spans[i].textContent = ago(Date.parse(spans[i].getAttribute('data-at')));
  }
  function folded() {
    try { return JSON.parse(window.localStorage.getItem(FOLD_KEY) || '[]') || []; } catch (e) { return []; }
  }
  function saveFolded(list) {
    try { window.localStorage.setItem(FOLD_KEY, JSON.stringify(list)); } catch (e) { /* the fold lasts the page */ }
  }
  function remembered() { if (!desk()) return false; try { return window.localStorage.getItem(OPEN_KEY) === 'open'; } catch (e) { return false; } }
  function savedSide() {
    try { return window.localStorage.getItem(SIDE_KEY) === 'record' ? 'record' : 'sittings'; } catch (e) { return 'sittings'; }
  }

  /* ── the read (one URL, GET only) ───────────────────────────────── */
  function get(query, ctl) {
    var init = { method: 'GET', credentials: 'same-origin', headers: { 'Accept': 'application/json' } };
    if (ctl) init.signal = ctl.signal;
    return fetch(BAND_URL + query, init).then(function (r) {
      var type = (r.headers && r.headers.get('content-type')) || '';
      if (r.status === 423) { stop('locked', W('locked')); return null; }
      if (r.redirected || !/json/i.test(type)) { stop('signed_out', W('signed_out')); return null; }
      if (r.status === 403) { stop('staff_only', W('staff_only')); return null; }
      return r.json().then(function (body) { return { status: r.status, body: body }; });
    });
  }
  function stop(why, words) {
    state.stopped = why;
    setDot('');
    if (!state.lastAt) setState('sv-empty', words);
    else if (stamp) stamp.textContent = words;
  }
  function failed() {
    setDot('err');
    if (!state.lastAt) setState('sv-error', W('cannot_reach', { t: '—' }));
    else if (stamp) stamp.textContent = W('cannot_reach', { t: hms(state.lastAt) + ' UTC' });
    root.classList.add('cb-stale');
  }
  function queryOf(part, opts) {
    if (part === 'sitting') return '?sitting=' + encodeURIComponent(opts.id);
    if (part === 'voice') return '?voice=' + encodeURIComponent(opts.id);
    var q = '?part=' + part;
    if (opts.before) q += '&before=' + encodeURIComponent(opts.before);
    if (opts.ev) q += '&ev=' + encodeURIComponent(opts.ev);
    return q;
  }
  function read(part, opts) {
    opts = opts || {};
    if (state.stopped || !desk() || document.hidden) return;
    var key = part + (opts.id ? ':' + opts.id : '') + (opts.before ? ':' + opts.before : '');
    var now = Date.now();
    if (!opts.ev && !opts.force && state.readAt[key] && now - state.readAt[key] < READ_MIN_GAP_MS) return;
    if (inflight[key]) return;
    state.readAt[key] = now;
    var ctl = window.AbortController ? new window.AbortController() : null;
    inflight[key] = ctl || true;
    get(queryOf(part, opts), ctl).then(function (res) {
      if (!res) return;
      if (res.status === 404 || res.status === 400) { paintMissing(part, res.body); return; }
      if (res.status >= 500 || !res.body || !res.body.ok) { failed(); return; }
      state.lastAt = Date.now();
      root.classList.remove('cb-stale');
      setDot('live');
      setStamp();
      paint(part, res.body, opts);
    }).catch(function (e) {
      if (e && e.name === 'AbortError') return;
      failed();
    }).then(function () { delete inflight[key]; }, function () { delete inflight[key]; });
  }
  function eventRead(kind) {
    if (eventTimer) window.clearTimeout(eventTimer);
    eventTimer = window.setTimeout(function () {
      eventTimer = null;
      if (!state.open || document.hidden) return;
      read('room', { ev: kind });
      if ((state.chamber || state.over) && state.side === 'sittings' && !state.sitting) read('sittings', { ev: kind });
    }, EVENT_DELAY_MS);
  }

  /* ── the clock ───────────────────────────────────────────────────── */
  function startPoll() {
    if (timer) return;
    state.ticks = 0;
    timer = window.setInterval(tick, TICK_MS);
  }
  function stopPoll() {
    if (timer) { window.clearInterval(timer); timer = null; }
    if (eventTimer) { window.clearTimeout(eventTimer); eventTimer = null; }
    for (var k in inflight) {
      if (Object.prototype.hasOwnProperty.call(inflight, k) && inflight[k] && inflight[k].abort) inflight[k].abort();
    }
    inflight = {};
  }
  function tick() {
    if (!state.open || document.hidden || !desk()) return;
    state.ticks += 1;
    setStamp();
    refreshAges();
    if (state.ticks % READ_EVERY === 0) {
      read('room');
      if (state.dossier) read('voice', { id: state.dossier });
    }
    if ((state.chamber || state.over) && !state.sitting) {
      var at = state.readAt[state.side] || 0;
      if (Date.now() - at >= SIDE_STALE_MS[state.side]) read(state.side);
    }
  }

  /* ── open, shut, widen ───────────────────────────────────────────── */
  function dock() {
    try { document.dispatchEvent(new CustomEvent('sv:dock-open', { detail: 'council' })); } catch (e) { /* an old engine: one dock may stay open */ }
  }
  function chromeMoved() {
    try { document.dispatchEvent(new CustomEvent('sv:chrome-moved', { detail: { by: 'council' } })); } catch (e) { /* the chart remeasures on resize */ }
  }
  function setUnread(n) {
    state.unread = Math.max(0, n);
    if (badge) {
      badge.textContent = state.unread > 99 ? '99+' : String(state.unread);
      badge.hidden = state.unread === 0;
    }
    tab.setAttribute('aria-label', W('tab_label') + (state.unread ? ', ' + W('badge_label', { n: state.unread }) : ''));
  }
  function setOpen(open, how) {
    if (open && !desk()) return;
    state.open = !!open;
    root.classList.toggle('open', state.open);
    tab.setAttribute('aria-expanded', state.open ? 'true' : 'false');
    if (state.open) panel.removeAttribute('inert'); else panel.setAttribute('inert', '');
    if (how !== 'restore' && desk()) { try { window.localStorage.setItem(OPEN_KEY, state.open ? 'open' : 'closed'); } catch (e) { /* the choice lasts the page */ } }
    if (open) {
      startPoll();
      setUnread(0);
      if (state.stopped !== 'locked') state.stopped = '';
      read('room', { force: true });
      dock();
      updateWiden();
      if (how === 'key') { try { titleEl.focus({ preventScroll: true }); } catch (e) { /* an old engine */ } }
    } else {
      stopPoll();
      setChamber(false, true);
      closeDossier(false);
      setOver(false, false);
    }
    schedule();
  }
  function toggle(how) {
    if (!desk()) return;
    setOpen(!state.open, how || 'click');
    if (!state.open && how === 'key') { try { tab.focus(); } catch (e) { /* an old engine */ } }
  }
  function room() {
    var side = document.querySelector('.sidebar');
    var rail = document.querySelector('.signals-rail');
    var left = side ? Math.max(0, side.getBoundingClientRect().right) : 0;
    var rw = rail ? rail.getBoundingClientRect().width : 0;
    return window.innerWidth - left - rw - 96;
  }
  function hordeOpen() { return !!document.querySelector('.sv-horde.open'); }
  function canWiden() { return room() >= CHAMBER_MIN_W && !hordeOpen(); }
  function updateWiden() {
    if (!widenBtn) return;
    var can = state.chamber || canWiden();
    widenBtn.setAttribute('aria-disabled', can ? 'false' : 'true');
    widenBtn.setAttribute('aria-pressed', state.chamber ? 'true' : 'false');
    var words = state.chamber ? W('narrow') : can ? W('widen') : hordeOpen() ? W('no_room_horde') : W('no_room');
    widenBtn.setAttribute('aria-label', words);
    widenBtn.title = words;
  }
  function setChamber(on, quiet) {
    on = !!on && state.open;
    if (on === state.chamber) { updateWiden(); return; }
    state.chamber = on;
    root.classList.toggle('chamber', on);
    if (on) {
      setOver(false, false);
      titleEl.textContent = W('title_chamber');
      showSide(state.side, false);
    } else {
      titleEl.textContent = W('title');
      state.sitting = null;
      markSitting();
    }
    inertCovered();
    updateWiden();
    if (!quiet) schedule();
  }
  function widen(how) {
    if (!desk()) return;
    if (!state.open) { setOpen(true, how || 'click'); return; }
    if (state.chamber) { setChamber(false); if (how === 'key' && widenBtn) widenBtn.focus(); return; }
    if (canWiden()) setChamber(true);
    else say(hordeOpen() ? W('no_room_horde') : W('no_room'));
  }
  function setOver(on, focusBack) {
    state.over = !!on && !state.chamber;
    root.classList.toggle('over', state.over);
    if (sideBack) sideBack.hidden = !state.over;
    markSitting();
    inertCovered();
    if (!state.over) {
      /* back to what opened the overlay, or to the band's title when a
         repaint has replaced it: the focus stays inside the band */
      var o = state.opener && document.contains(state.opener) ? state.opener : titleEl;
      state.opener = null;
      if (focusBack) { try { o.focus({ preventScroll: true }); } catch (e) { /* gone */ } }
    }
  }
  function markSitting() {
    /* A transcript in the OPEN overlay keeps one way back, its own
       "Back to the sittings": the side head (back to the council and the
       two tabs) steps aside while it is shown. */
    root.classList.toggle('cb-in-sitting', !!state.sitting && state.over);
  }
  function setInert(n, on) {
    if (!n) return;
    if (on) n.setAttribute('inert', ''); else n.removeAttribute('inert');
  }
  function inertCovered() {
    /* What an overlay covers leaves the tab order: in OPEN the side
       overlay and the dossier lie over the room, and in the chamber the
       dossier over the side column. Tab and Shift+Tab then stay in the
       layer that shows; focus left under a cover moves up into it. */
    var at = document.activeElement;
    var had = !!at && at !== document.body && root.contains(at);
    var roomOff = state.open && !state.chamber && (state.over || !!state.dossier);
    var sideOff = state.open && !!state.dossier && (state.chamber || state.over);
    setInert(roomEl, roomOff);
    setInert(sideEl, sideOff);
    var now = document.activeElement;
    if (!had || (now !== document.body && root.contains(now)
                 && !(roomOff && roomEl.contains(now)) && !(sideOff && sideEl.contains(now)))) return;
    var to = state.dossier ? dossierEl.querySelector('.cb-back')
      : (state.over && !state.sitting && sideBack && !sideBack.hidden) ? sideBack : titleEl;
    try { (to || titleEl).focus({ preventScroll: true }); } catch (e) { /* an old engine */ }
  }

  /* ── the side column: the sittings and the record ───────────────── */
  function showSide(which, overlay, opener) {
    state.side = which === 'record' ? 'record' : 'sittings';
    try { window.localStorage.setItem(SIDE_KEY, state.side); } catch (e) { /* the tab lasts the page */ }
    state.sitting = null;
    markSitting();
    if (!state.chamber) { if (opener) state.opener = opener; setOver(overlay !== false, false); }
    Array.prototype.forEach.call(tabBtns, function (b) {
      var on = b.getAttribute('data-side') === state.side;
      b.setAttribute('aria-selected', on ? 'true' : 'false');
      b.tabIndex = on ? 0 : -1;
      if (on) sideBody.setAttribute('aria-labelledby', b.id);
    });
    if (state.side === 'record') { if (state.record) paintRecord(state.record); else loading(sideBody); read('record'); }
    else { if (state.sittings) paintSittings(state.sittings); else loading(sideBody); read('sittings'); }
  }
  function loading(box, words) { clear(box); add(box, el('div', 'sv-loading', words || W('loading'))); }

  /* ── painting ────────────────────────────────────────────────────── */
  function paint(part, body, opts) {
    if (part === 'room') paintRoom(body.panels || {});
    else if (part === 'sittings') { if (opts.before) appendSittings(body.sittings); else freshSittings(body.sittings); }
    else if (part === 'record') { state.record = body.record; if (!state.sitting && state.side === 'record') repaint(sideBody, function () { paintRecord(state.record); }); }
    else if (part === 'sitting') { if (state.sitting === opts.id) paintSitting(body.sitting); }
    else if (part === 'voice') {
      /* an unchanged dossier is not rebuilt: the reader keeps their place */
      var v = body.voice || {};
      var rk = 'voice:' + opts.id;
      if (state.dossier === opts.id && (!v.rev || v.rev !== state.revs[rk])) { state.revs[rk] = v.rev; paintDossier(v); }
    }
  }
  function paintMissing(part, body) {
    var words = (body && body.t) || '';
    if (part === 'sitting') { clear(sideBody); add(sideBody, el('div', 'sv-empty', words || W('s_failed'))); }
    else if (part === 'voice') { clear(dossierEl); add(dossierEl, backButton()); add(dossierEl, el('div', 'sv-empty', words || W('d_failed'))); }
  }
  function changed(name, p) {
    if (p && p.rev && state.revs[name] === p.rev) return false;
    state.revs[name] = p && p.rev;
    return true;
  }
  function paintRoom(panels) {
    setState('');
    if (changed('head', panels.head)) paintHead(panels.head || {});
    if (changed('direction', panels.direction)) repaint(secs.direction, function () { paintDirection(panels.direction || {}); });
    if (changed('throne', panels.throne)) repaint(secs.throne, function () { paintThrone(panels.throne || {}); });
    if (changed('nine', panels.nine)) repaint(secs.nine, function () { paintNine(panels.nine || {}); });
    if (changed('traders', panels.traders)) repaint(secs.traders, function () { paintTraders(panels.traders || {}); });
  }
  function chip(text, cls) { return el('span', 'cb-chip' + (cls ? ' ' + cls : ''), text); }
  function paintHead(h) {
    clear(chipsBox);
    if (h.error) { add(chipsBox, chip(h.error)); return; }
    var d = (h.debate || {}).t || '', c = (h.council || {}).t || '';
    var dc = add(chipsBox, chip(d, /BINDING/.test(d) ? 'cb-chip--binding' : /OFF/.test(d) ? 'cb-chip--off' : ''));
    dc.title = (h.debate || {}).title || '';
    var cc = add(chipsBox, chip(c, /OFF/.test(c) ? 'cb-chip--off' : ''));
    cc.title = (h.council || {}).title || '';
  }
  function section(box, key, title) {
    clear(box);
    var shut = folded().indexOf(key) !== -1;
    var btn = el('button', 'cb-sec-title', title);
    btn.type = 'button';
    btn.setAttribute('aria-expanded', shut ? 'false' : 'true');
    var body = el('div', 'cb-sec-body');
    body.hidden = shut;
    btn.addEventListener('click', function () {
      var now = btn.getAttribute('aria-expanded') !== 'true';
      btn.setAttribute('aria-expanded', now ? 'true' : 'false');
      body.hidden = !now;
      var list = folded().filter(function (k) { return k !== key; });
      if (!now) list.push(key);
      saveFolded(list);
    });
    add(box, btn);
    add(box, body);
    return body;
  }
  function sub(parent, title) { return add(parent, el('h3', 'cb-sub', title)); }
  function errorIn(box, words) { clear(box); add(box, el('div', 'cb-error', words)); }

  /* the round table */
  function svg(tag, attrs) {
    var n = document.createElementNS(SVG_NS, tag);
    for (var k in attrs) if (Object.prototype.hasOwnProperty.call(attrs, k)) n.setAttribute(k, attrs[k]);
    return n;
  }
  function drawTable(t, size, big) {
    var s = svg('svg', { viewBox: '0 0 100 100', width: size, height: size, role: 'img', 'class': 'cb-table', 'aria-label': t.label || '' });
    s.appendChild(svg('circle', { cx: 50, cy: 50, r: 31, 'class': 'cb-ringline' }));
    (t.seats || []).forEach(function (seat) {
      var a = (seat.a || 0) * Math.PI / 180;
      var x = 50 + 40 * Math.sin(a), y = 50 - 40 * Math.cos(a);
      if (seat.dissent) s.appendChild(svg('circle', { cx: x, cy: y, r: 10, 'class': 'cb-dis' }));
      var c = svg('circle', { cx: x, cy: y, r: 7, 'class': 'cb-seat cb-side--' + seat.side });
      var title = svg('title', {});
      title.textContent = W('seat_label', { name: seat.name, side: W(SIDE_WORD[seat.side] || 'side_absent') });
      c.appendChild(title);
      s.appendChild(c);
      if (big) {
        var m = svg('text', { x: x, y: y, 'class': 'cb-seat-mono' + (/silent|waiting|absent/.test(seat.side) ? ' cb-hollow' : '') });
        m.textContent = seat.mono;
        s.appendChild(m);
      }
    });
    var chair = t.chair;
    s.appendChild(svg('circle', { cx: 50, cy: 50, r: 16, 'class': 'cb-chair ' + (chair ? 'cb-side--' + chair : 'cb-nochair') + (t.smaller ? ' cb-chair--smaller' : '') }));
    var word = svg('text', { x: 50, y: 50, 'class': 'cb-chair-word' });
    word.textContent = big ? (t.chair_token || W('chair_none')) : (t.chair_glyph || '·');
    s.appendChild(word);
    return s;
  }

  function paintDirection(d) {
    var box = secs.direction;
    if (d.error) { errorIn(box, d.error); return; }
    clear(box);
    if (d.table) {
      var b = el('button', 'cb-dir-table');
      b.type = 'button';
      b.appendChild(drawTable(d.table, 64, false));
      b.addEventListener('click', function () { openSitting(d.table.sitting, b); });
      add(box, b);
    } else {
      add(box, el('span', ''));
    }
    var rows = add(box, el('div', 'cb-dir-rows'));
    function row(label, item, onClick) {
      var r = add(rows, el('div', 'cb-dir-row'));
      add(r, el('span', 'cb-label', label));
      var s = add(r, el('span', 'cb-sentence', (item || {}).t || '—'));
      if (onClick) {
        var link = el('button', 'cb-inline', W('sittings_link'));
        link.type = 'button';
        link.addEventListener('click', onClick);
        add(s, link);
      }
    }
    row(W('thinks'), d.thinks);
    row(W('disagrees'), d.disagrees, function (e) { showSide('sittings', true, e.currentTarget); });
    row(W('right'), d.right);
  }

  function voiceRing(key, mono, side, big, late) {
    var b = el('button', 'cb-ring' + (big ? ' cb-ring--big' : '') + (side ? ' cb-side--' + side : '') + (late ? ' cb-late' : ''), mono);
    b.type = 'button';
    b.setAttribute('aria-controls', 'svCouncilBandDossier');
    b.setAttribute('aria-expanded', 'false');
    b.addEventListener('click', function () { openDossier(key, b); });
    return b;
  }
  function paintThrone(t) {
    var box = secs.throne;
    if (t.error) { errorIn(box, t.error); return; }
    var body = section(box, 'throne', W('throne'));
    var head = add(body, el('div', 'cb-throne-head'));
    var ring = voiceRing('emperor', t.mono || 'EM', '', true, false);
    ring.setAttribute('aria-label', W('open_dossier', { name: t.name || W('emperor') }));
    add(head, ring);
    var who = add(head, el('div', ''));
    add(who, el('div', 'cb-name', t.name || W('emperor')));
    add(who, el('div', 'cb-role', t.role));
    lines(body, [(t.status || {}).t], 'cb-line--strong');
    sub(body, W('campaign'));
    lines(body, [(t.campaign || {}).t]);
    var hand = t.hand || {};
    sub(body, W('hand'));
    add(body, el('p', 'cb-label', W('hand_now')));
    lines(body, hand.now);
    add(body, el('p', 'cb-label', W('hand_last')));
    lines(body, hand.last);
    add(body, el('p', 'cb-label', W('hand_against')));
    lines(body, hand.against);
    paintMood(body, t.mood || {});
    sub(body, W('war'));
    lines(body, [(t.war || {}).label], 'cb-line--muted');
    lines(body, (t.war || {}).lines);
    lines(body, [(t.ai || {}).t]);
    sub(body, W('posture'));
    lines(body, [(t.posture || {}).t, (t.posture || {}).rationale]);
    sub(body, W('horizon'));
    var hz = t.horizon || {};
    if (hz.chips && hz.chips.length) {
      var cl = add(body, el('div', 'cb-chipline'));
      hz.chips.forEach(function (c) { add(cl, chip(c)); });
    }
    lines(body, [hz.t], 'cb-line--muted');
    sub(body, W('battles'));
    lines(body, (t.battles || {}).lines);
    sub(body, W('chair_record'));
    lines(body, (t.chair || {}).lines);
    sub(body, W('rulings'));
    if (t.rulings && t.rulings.length) {
      var ul = add(body, el('ul', 'cb-rulings'));
      t.rulings.forEach(function (r) {
        var li = add(ul, el('li', ''));
        var b = add(li, el('button', '', r.t));
        b.type = 'button';
        b.addEventListener('click', function () { openSitting(r.sitting, b); });
      });
    } else {
      lines(body, [t.rulings_none], 'cb-line--muted');
    }
  }
  function paintMood(body, m) {
    sub(body, W('mood'));
    var p = add(body, el('p', 'cb-line cb-line--strong'));
    var level = m.level || 'unmeasured';
    var head = String(m.head || '');
    var at = head.lastIndexOf(': ' + level);
    if (at >= 0) {
      p.appendChild(document.createTextNode(head.slice(0, at + 2)));
      add(p, el('span', 'cb-mood-level cb-mood--' + level, level));
      p.appendChild(document.createTextNode(head.slice(at + 2 + level.length)));
    } else {
      p.textContent = head;
    }
    lines(body, [m.level_words, m.note, m.why], 'cb-line--muted');
    var ul = add(body, el('ul', 'cb-mood-inputs'));
    (m.inputs || []).forEach(function (i) {
      add(ul, el('li', i.measured ? '' : 'unmeasured', i.label + ': ' + i.words));
    });
    lines(body, [m.caution], 'cb-line--note');
    lines(body, [m.last]);
    add(body, el('p', 'cb-label', m.graded_title));
    lines(body, m.graded);
    lines(body, [m.graded_note], 'cb-line--muted');
  }

  function bar(p, side) {
    var b = el('span', 'cb-bar cb-side--' + (side || 'none'));
    var fill = add(b, el('i', ''));
    fill.style.width = Math.round(Math.max(0, Math.min(1, p)) * 100) + '%';
    b.setAttribute('role', 'img');
    return b;
  }
  function paintNine(n) {
    var box = secs.nine;
    if (n.error) { errorIn(box, n.error); return; }
    var body = section(box, 'nine', W('nine'));
    lines(body, n.notes, 'cb-line--note');
    lines(body, [n.weights_note], 'cb-line--muted');
    (n.triads || []).forEach(function (t) {
      var tri = add(body, el('div', 'cb-triad'));
      var title = add(tri, el('div', 'cb-triad-title', t.title));
      add(title, el('span', 'cb-triad-sub', t.sub));
      var ul = add(tri, el('ul', 'cb-voices'));
      (t.voices || []).forEach(function (v) { add(ul, voiceRow(v)); });
    });
  }
  function voiceRow(v) {
    var li = el('li', 'cb-voice');
    var b = add(li, el('button', 'cb-voice-open'));
    b.type = 'button';
    b.setAttribute('aria-controls', 'svCouncilBandDossier');
    b.setAttribute('aria-expanded', 'false');
    b.setAttribute('data-voice', v.key);
    var latest = v.latest || null;
    var side = latest ? latest.side : 'absent';
    add(b, el('span', 'cb-ring cb-side--' + side + (latest && latest.status === 'late' ? ' cb-late' : ''), v.mono));
    var main = add(b, el('span', 'cb-voice-main'));
    var top = add(main, el('span', 'cb-voice-top'));
    add(top, el('span', 'cb-name', v.name));
    (v.hand || []).forEach(function (h) { add(top, chip(h, 'cb-chip--hand')); });
    add(main, el('span', 'cb-role', v.role));
    var meta = add(main, el('span', 'cb-voice-meta'));
    meta.style.display = 'block';
    if (latest && latest.token) {
      add(meta, el('span', 'cb-token cb-side--' + side, latest.token));
      if (latest.p_work !== null && latest.p_work !== undefined) {
        meta.appendChild(document.createTextNode(' '));
        var bb = add(meta, bar(latest.p_work, side));
        bb.setAttribute('aria-label', latest.p);
      }
      meta.appendChild(document.createTextNode(' ' + [latest.p, latest.symbol + ' ' + latest.trade_side, latest.when].filter(Boolean).join(' · ')));
    } else if (latest) {
      meta.appendChild(document.createTextNode(latest.words || ''));
    } else {
      meta.appendChild(document.createTextNode(v.none || ''));
    }
    add(main, el('span', 'cb-line cb-line--muted', (v.today || {}).t)).style.display = 'block';
    add(main, el('span', 'cb-line cb-mono', (v.weight || {}).t)).style.display = 'block';
    add(main, el('span', 'cb-line cb-mono', (v.record || {}).t)).style.display = 'block';
    if (v.rule) add(main, el('span', 'cb-line cb-line--muted', v.rule)).style.display = 'block';
    b.setAttribute('aria-label', W('open_dossier', { name: v.name }));
    b.addEventListener('click', function () { openDossier(v.key, b); });
    return li;
  }

  function paintTraders(t) {
    var box = secs.traders;
    if (t.error) { errorIn(box, t.error); return; }
    var body = section(box, 'traders', W('traders'));
    if (t.unread) {
      lines(body, [t.unread], 'cb-line--note');
    } else {
      var cards = add(body, el('div', 'cb-cards'));
      (t.cards || []).forEach(function (c) {
        var card = add(cards, el('div', 'cb-card'));
        add(card, el('div', 'cb-card-title', String(c.label).toUpperCase() + ' · ' + c.holding));
        add(card, el('div', 'cb-card-line cb-lane--' + c.lane, c.factor_t));
        add(card, el('div', 'cb-card-line', c.band_t));
        add(card, el('div', 'cb-card-line', c.worn_t));
      });
      if (t.matrix && t.matrix.length) {
        var table = add(body, el('table', 'cb-matrix'));
        var head = add(table, el('tr', ''));
        add(head, el('th', '', ''));
        (t.matrix[0].cells || []).forEach(function (c) { add(head, el('th', '', String(c.regime).replace(/_/g, ' '))); });
        t.matrix.forEach(function (row) {
          var tr = add(table, el('tr', ''));
          add(tr, el('th', '', row.label));
          row.cells.forEach(function (c) {
            var td = add(tr, el('td', ''));
            var cell = add(td, el('span', 'cb-cell cb-cell--' + c.lane + (c.current ? ' cb-cell--now' : '')));
            cell.setAttribute('role', 'img');
            cell.setAttribute('aria-label', W('matrix_label', { label: row.label, regime: c.regime, f: c.factor === null ? '—' : Number(c.factor).toFixed(2), lane: c.lane }));
          });
        });
        lines(body, [t.key], 'cb-line--muted');
      }
      lines(body, [t.line]);
    }
    lines(body, [t.foot], 'cb-line--muted');
    sub(body, W('orcs'));
    lines(body, [t.orcs], 'cb-line--muted');
  }

  /* the sittings */
  function filterOk(c) {
    if (state.filter === 'bot') return c.origin === 'bot';
    if (state.filter === 'ticket') return c.origin === 'ticket';
    if (state.filter === 'dissent') return c.has_dissent || c.split;
    return true;
  }
  function sittingCard(c, fresh) {
    var li = el('li', fresh && !reduce ? 'cb-new' : '');
    var b = add(li, el('button', 'cb-sitting'));
    b.type = 'button';
    b.setAttribute('data-sitting', c.id);
    add(b, el('span', 'cb-mark cb-side--' + ((c.table || {}).chair || 'none') + ((c.table || {}).smaller ? ' cb-mark--smaller' : '')));
    b.appendChild(drawTable(c.table || {}, state.chamber ? 88 : 64, false));
    var main = add(b, el('span', 'cb-sitting-main'));
    var head = add(main, el('span', 'cb-sitting-head'));
    /* one line: the class only where the chamber has the room for it
       (the transcript's head names it); the whole line in its title */
    var kind = add(head, el('span', 'cb-kind', [c.kind, c.symbol, state.chamber ? c['class'] : '', c.side].filter(Boolean).join(' · ')));
    kind.title = [c.kind, c.symbol, c['class'], c.side].filter(Boolean).join(' · ');
    var age = add(head, el('span', 'cb-age', c.at ? ago(Date.parse(c.at)) : ''));
    if (c.at) age.setAttribute('data-at', c.at);
    if (c.chair) add(main, el('span', 'cb-line cb-line--strong', c.chair));
    add(main, el('span', 'cb-line', c.tally));
    if (c.dissent) add(main, el('span', 'cb-line', c.dissent));
    add(main, el('span', 'cb-line cb-line--muted', c.outcome));
    if (c.sentence) add(main, el('span', 'cb-line cb-line--muted', c.sentence));
    var cl = add(main, el('span', 'cb-chipline'));
    (c.chips || []).forEach(function (t) {
      add(cl, chip(t, /DISSENT/.test(t) ? 'cb-chip--dissent' : /SPLIT/.test(t) ? 'cb-chip--split' : /BINDING/.test(t) ? 'cb-chip--binding' : ''));
    });
    b.addEventListener('click', function () { openSitting(c.id, b); });
    li.hidden = !filterOk(c);
    return li;
  }
  var seenSittings = {};
  function paintSittings(data) {
    clear(sideBody);
    var filters = add(sideBody, el('div', 'cb-filters'));
    [['all', W('filter_all')], ['bot', W('filter_bot')], ['ticket', W('filter_ticket')], ['dissent', W('filter_dissent')]].forEach(function (f) {
      var b = add(filters, el('button', 'cb-filter', f[1]));
      b.type = 'button';
      b.setAttribute('aria-pressed', state.filter === f[0] ? 'true' : 'false');
      b.addEventListener('click', function () { state.filter = f[0]; repaint(sideBody, function () { paintSittings(state.sittings || data); }); });
    });
    var cards = (data && data.cards) || [];
    if (!cards.length) { add(sideBody, el('div', 'sv-empty', (data && data.empty) || W('no_sitting_7'))); return; }
    var ol = add(sideBody, el('ol', 'cb-cards-list'));
    ol.setAttribute('aria-label', W('tab_sittings'));
    var first = !Object.keys(seenSittings).length;
    cards.forEach(function (c) {
      add(ol, sittingCard(c, !first && !seenSittings[c.id]));
      seenSittings[c.id] = 1;
    });
    if (!cards.some(filterOk)) add(sideBody, el('div', 'sv-empty', W('nothing_kind')));
    if (data.more) {
      var more = add(sideBody, el('button', 'cb-link', W('show_older')));
      more.type = 'button';
      more.addEventListener('click', function () { read('sittings', { before: cards[cards.length - 1].id.slice(1) }); });
    }
  }
  function freshSittings(data) {
    /* The first page, read again. Unchanged (the server's rev), nothing
       is repainted; changed, the older pages the reader loaded with
       "Show older" are kept after it, each sitting once. */
    data = data || {};
    var old = state.sittings;
    if (old && data.rev && data.rev === old.rev) return;
    var cards = data.cards || [];
    var fresh = {};
    cards.forEach(function (c) { fresh[c.id] = 1; });
    var older = (old && old.paged) ? (old.cards || []).filter(function (c) { return !fresh[c.id]; }) : [];
    state.sittings = { cards: cards.concat(older), more: older.length ? !!old.more : !!data.more,
                       empty: data.empty, rev: data.rev, paged: older.length > 0 };
    if (!state.sitting && state.side === 'sittings') repaint(sideBody, function () { paintSittings(state.sittings); });
  }
  function appendSittings(data) {
    if (!state.sittings) return;
    var have = {};
    (state.sittings.cards || []).forEach(function (c) { have[c.id] = 1; });
    var more = ((data && data.cards) || []).filter(function (c) { return !have[c.id]; });
    state.sittings = { cards: (state.sittings.cards || []).concat(more), more: !!(data && data.more),
                       empty: state.sittings.empty, rev: state.sittings.rev, paged: true };
    if (!state.sitting && state.side === 'sittings') repaint(sideBody, function () { paintSittings(state.sittings); });
  }
  function openSitting(id, opener) {
    if (!id) return;
    var at = document.activeElement;
    state.sittingFocus = !at || at === document.body || root.contains(at);
    /* the sitting first: the overlay then covers the room with the
       transcript's own way back coming, never the side head */
    state.sitting = id;
    if (!state.chamber && !state.over) { state.opener = opener || null; setOver(true, false); }
    markSitting();
    loading(sideBody, W('s_loading'));
    read('sitting', { id: id, force: true });
  }
  function backButton(words, fn) {
    var b = el('button', 'cb-back', words || W('back_council'));
    b.type = 'button';
    b.addEventListener('click', fn || function () { closeDossier(true); });
    return b;
  }
  function block(parent, b) {
    var box = add(parent, el('div', 'cb-block'));
    var top = add(box, el('div', 'cb-block-top'));
    var ring = add(top, voiceRing(b.voice, b.mono, b.side, false, b.status === 'late'));
    if (b.smaller) ring.classList.add('cb-ring--smaller');
    ring.setAttribute('aria-label', W('open_dossier', { name: b.name }));
    add(top, el('span', 'cb-name', b.name));
    if (b.token) add(top, el('span', 'cb-token cb-side--' + b.side + (b.smaller ? ' cb-token--smaller' : ''), b.token));
    lines(box, [b.words, b.p]);
    if (b.key) add(box, el('p', 'cb-quote', b.key));
    if (b.reasons && b.reasons.length) {
      var det = add(box, el('details', 'cb-reasons'));
      add(det, el('summary', '', W('reasons', { n: b.reasons.length })));
      var ul = add(det, el('ul', ''));
      b.reasons.forEach(function (r) { add(ul, el('li', '', r)); });
    }
    lines(box, b.extra);
    lines(box, [b.note, b.silence], 'cb-line--muted');
    lines(box, [b.weight, b.model, b.grades], 'cb-line--muted cb-mono');
  }
  function keepFocus(box, target) {
    /* The view the reader was in was replaced under the focus: focus its
       way back, so Escape and the keyboard stay inside the band. */
    var at = document.activeElement;
    if (target && (!at || at === document.body || box.contains(at))) {
      try { target.focus({ preventScroll: true }); } catch (e) { /* an old engine */ }
    }
  }
  function paintSitting(s) {
    var hadFocus = sideBody.contains(document.activeElement) || !root.contains(document.activeElement);
    clear(sideBody);
    var back = add(sideBody, backButton(W('back_sittings'), function () {
      state.sitting = null;
      showSide('sittings', !state.chamber ? true : false);
      var to = state.over ? sideBack : root.querySelector('.cb-tabbtn[aria-selected="true"]');
      if (to) { try { to.focus({ preventScroll: true }); } catch (e) { /* an old engine */ } }
    }));
    if (state.sittingFocus) { state.sittingFocus = false; try { back.focus({ preventScroll: true }); } catch (e) { /* an old engine */ } }
    else if (hadFocus) keepFocus(sideBody, back);
    var head = add(sideBody, el('div', 'cb-tr-head'));
    head.appendChild(drawTable(s.table || {}, state.chamber ? 200 : 160, true));
    lines(head, [s.head], 'cb-line--strong');
    lines(head, [s.outcome, s.grade, s.sentence, s.graded, s.only_debate]);
    lines(head, [s.model], 'cb-line--muted cb-mono');
    if (s.emperor) { sub(sideBody, W('t_emperor')); block(sideBody, s.emperor); }
    if (s.emperor_late) lines(sideBody, [s.emperor_late], 'cb-line--note');
    if (s.dissent && s.dissent.length) { sub(sideBody, W('t_dissent')); s.dissent.forEach(function (b) { block(sideBody, b); }); }
    if (s.others && s.others.length) { sub(sideBody, W('t_others')); s.others.forEach(function (b) { block(sideBody, b); }); }
    lines(sideBody, [s.mood], 'cb-line--muted');
    var foot = add(sideBody, el('div', 'cb-footer'));
    var href = safeLink(s.trade_url);
    if (href) { var a = add(foot, el('a', 'cb-link', W('open_trade', { id: s.trade_id }))); a.setAttribute('href', href); }
    var ask = s.ask || {};
    if (window.askSauronAbout && ask.subject) {
      var q = add(foot, el('button', 'cb-link', W('ask_sitting')));
      q.type = 'button';
      q.addEventListener('click', function () { window.askSauronAbout(ask.subject, ask.kind || 'sitting', ask.facts || ''); });
    }
  }
  function paintRecord(r) {
    clear(sideBody);
    if (!r || r.error) { add(sideBody, el('div', 'sv-error', (r && r.error) || W('d_failed'))); return; }
    sub(sideBody, W('r_hand'));
    lines(sideBody, [r.hand_bar], 'cb-line--muted');
    (r.hands || []).forEach(function (h) {
      add(sideBody, el('p', 'cb-label', String(h.regime).replace(/_/g, ' ') + (h.now ? ' · ' + W('regime_now') : '')));
      lines(sideBody, h.lines);
    });
    sub(sideBody, W('r_against'));
    lines(sideBody, r.against);
    sub(sideBody, W('r_skeptic'));
    lines(sideBody, [r.skeptic]);
    sub(sideBody, W('r_mood'));
    add(sideBody, el('p', 'cb-label', r.moods_title));
    lines(sideBody, r.moods);
    lines(sideBody, [r.moods_note], 'cb-line--muted');
    sub(sideBody, W('r_weights'));
    var table = add(sideBody, el('table', 'cb-wtable'));
    var head = add(table, el('tr', ''));
    add(head, el('th', '', ''));
    (r.regimes || []).forEach(function (rg) { add(head, el('th', '', String(rg).replace(/_/g, ' '))); });
    (r.weights || []).forEach(function (row) {
      var tr = add(table, el('tr', ''));
      var th = add(tr, el('th', '', row.mono));
      th.setAttribute('scope', 'row');
      th.title = row.name || '';
      row.cells.forEach(function (c) {
        add(tr, el('td', (c.measured ? 'measured' : '') + (c.now ? ' now' : ''), c.t + (c.measured ? '' : ' (' + c.n + ')')));
      });
    });
    lines(sideBody, [r.weights_key, W('r_weights_note')], 'cb-line--muted');
    sub(sideBody, W('r_bench'));
    lines(sideBody, r.bench);
  }

  /* the dossier */
  function openDossier(key, opener) {
    if (!key) return;
    state.dossier = key;
    state.dossierOpener = opener || null;
    delete state.revs['voice:' + key];
    if (opener) opener.setAttribute('aria-expanded', 'true');
    dossierEl.hidden = false;
    clear(dossierEl);
    dossierEl.scrollTop = 0;
    var back = add(dossierEl, backButton());
    try { back.focus({ preventScroll: true }); } catch (e) { /* an old engine */ }
    inertCovered();
    add(dossierEl, el('div', 'sv-loading', W('d_loading')));
    window.requestAnimationFrame(function () { dossierEl.classList.add('on'); });
    read('voice', { id: key, force: true });
  }
  function closeDossier(focusBack) {
    if (!state.dossier) return;
    state.dossier = null;
    dossierEl.classList.remove('on');
    dossierEl.hidden = true;
    inertCovered();
    var o = state.dossierOpener;
    state.dossierOpener = null;
    if (o) { o.setAttribute('aria-expanded', 'false'); if (focusBack) { try { o.focus(); } catch (e) { /* gone */ } } }
  }
  function paintDossier(v) {
    /* A changed dossier is rebuilt in place: the reader's scroll and the
       control they stood on are put back (first paint: the back button,
       focused by openDossier). */
    var mark = focusMark(dossierEl);
    var top = dossierEl.scrollTop;
    var hadFocus = !!mark || !root.contains(document.activeElement);
    clear(dossierEl);
    var back = add(dossierEl, backButton());
    var head = add(dossierEl, el('div', 'cb-dossier-head'));
    add(head, el('span', 'cb-ring cb-ring--big', v.mono));
    var who = add(head, el('div', ''));
    add(who, el('div', 'cb-name', v.name));
    add(who, el('div', 'cb-role', v.role));
    lines(dossierEl, [v.status], 'cb-line--strong');
    if (v.hand_cells && v.hand_cells.length) {
      var cl = add(dossierEl, el('div', 'cb-chipline'));
      v.hand_cells.forEach(function (h) { add(cl, chip(h, 'cb-chip--hand')); });
    }
    sub(dossierEl, W('d_weight'));
    lines(dossierEl, v.weights, 'cb-mono');
    sub(dossierEl, W('d_regimes'));
    var cells = add(dossierEl, el('div', 'cb-cells'));
    (v.regimes || []).forEach(function (c) { add(cells, el('span', 'cb-line cb-mono' + (c.now ? ' now' : '') + (c.measured ? ' measured' : ''), c.t)); });
    lines(dossierEl, [W('d_regimes_note')], 'cb-line--muted');
    sub(dossierEl, W('d_table'));
    lines(dossierEl, [v.table, v.specialty], 'cb-mono');
    sub(dossierEl, W('d_hand'));
    lines(dossierEl, v.hand);
    function calls(title, list) {
      sub(dossierEl, title);
      if (!list || !list.length) { lines(dossierEl, [v.calls_none], 'cb-line--muted'); return; }
      var ul = add(dossierEl, el('ul', 'cb-rulings'));
      list.forEach(function (c) {
        var b = add(add(ul, el('li', '')), el('button', '', c.t));
        b.type = 'button';
        b.addEventListener('click', function () { closeDossier(false); openSitting(c.sitting, b); });
      });
    }
    calls(W('d_best'), v.best);
    calls(W('d_worst'), v.worst);
    calls(W('d_history'), v.history);
    sub(dossierEl, W('d_today'));
    lines(dossierEl, [v.today]);
    var ask = v.ask || {};
    if (window.askSauronAbout && ask.subject) {
      var foot = add(dossierEl, el('div', 'cb-footer'));
      var q = add(foot, el('button', 'cb-link', W('ask_voice', { name: ask.subject })));
      q.type = 'button';
      q.addEventListener('click', function () { window.askSauronAbout(ask.subject, ask.kind || 'voice', ask.facts || ''); });
    }
    dossierEl.scrollTop = top;
    if (mark) refocus(dossierEl, mark);
    else if (hadFocus) keepFocus(dossierEl, back);
  }

  /* ── stepping back ───────────────────────────────────────────────── */
  function stepBack() {
    if (state.dossier) { closeDossier(true); return; }
    if (state.sitting) {
      state.sitting = null;
      showSide(state.side, !state.chamber);
      var to = state.over ? sideBack : root.querySelector('.cb-tabbtn[aria-selected="true"]');
      if (to) { try { to.focus({ preventScroll: true }); } catch (e) { /* an old engine */ } }
      return;
    }
    if (state.over) { setOver(false, true); return; }
    if (state.chamber) { setChamber(false); if (widenBtn) widenBtn.focus(); return; }
    setOpen(false, 'key');
    try { tab.focus(); } catch (e) { /* an old engine */ }
  }

  /* ── the tab, placed by measure ──────────────────────────────────── */
  function rectOf(id) {
    var n = document.getElementById(id);
    if (!n) return null;
    var r = n.getBoundingClientRect();
    return (r.width > 0 && r.height > 0) ? r : null;
  }
  function placeTab() {
    framePending = false;
    if (!desk()) return;
    var box = root.getBoundingClientRect();
    var tr = tab.getBoundingClientRect();
    var toggle = rectOf('railToggleBtn');
    var act = rectOf('svActivityTab');
    var head = hordeOpen() ? rectOf('svHordeHead') : null;
    var eye = rectOf('seEyeFab');
    var vh = window.innerHeight;
    var left = tr.left, right = tr.right;
    /* `soft`: clear of the open Horde's head too (round 2: the shut tab
       stood on it, 4px right of its close). Never on a control (the
       rail's toggle, the ACTIVITY tab, the Eye) first; the head only
       where nothing else is free (1100 with the Horde at half). */
    function hits(y, soft) {
      var others = soft ? [toggle, act, eye, head] : [toggle, act, eye];
      for (var i = 0; i < others.length; i++) {
        var o = others[i];
        if (o && left < o.right && right > o.left && y < o.bottom + 4 && y + TAB_H > o.top - 4) return true;
      }
      return y < box.top + 4 || y + TAB_H > box.bottom - 4;
    }
    var fallback = vh / 2 - 156;
    if (!hits(fallback, true)) { root.style.removeProperty('--cb-tab-top'); return; }
    /* never lower than the Eye where it stands in the tab's column */
    var floor = box.bottom - 8;
    if (eye && left < eye.right && right > eye.left) floor = Math.min(floor, eye.top - 8);
    function slot(soft) {
      var y = null;
      if (toggle && toggle.top - TAB_GAP - TAB_H >= box.top + 8 && !hits(toggle.top - TAB_GAP - TAB_H, soft)) y = toggle.top - TAB_GAP - TAB_H;
      if (y === null) {
        var below = Math.max((act || toggle || { bottom: box.top }).bottom + TAB_GAP, head ? head.bottom + 8 : 0);
        if (below + TAB_H <= floor && !hits(below, soft)) y = below;
      }
      /* else the first free slot from the column's top down to that floor */
      for (var at = box.top + 8; y === null && at + TAB_H <= floor; at += 8) {
        if (!hits(at, soft)) y = at;
      }
      return y;
    }
    var y = slot(true);
    if (y === null) y = slot(false);
    if (y === null) y = box.top + 8;
    root.style.setProperty('--cb-tab-top', Math.round(y - box.top) + 'px');
  }
  function schedule() {
    if (framePending) return;
    framePending = true;
    window.requestAnimationFrame(function () {
      placeTab();
      if (state.chamber && (room() < CHAMBER_MIN_W)) { setChamber(false); say(W('narrowed_room')); }
      if (state.open && !desk()) setOpen(false, 'restore');
      updateWiden();
    });
  }

  /* ── wiring ──────────────────────────────────────────────────────── */
  tab.addEventListener('click', function () { toggle('click'); });
  if (closeBtn) closeBtn.addEventListener('click', function () { setOpen(false, 'click'); try { tab.focus(); } catch (e) { /* an old engine */ } });
  if (widenBtn) widenBtn.addEventListener('click', function () { if (widenBtn.getAttribute('aria-disabled') === 'true' && !state.chamber) { say(widenBtn.title); return; } widen('click'); });
  if (sideBack) sideBack.addEventListener('click', function () { state.sitting = null; setOver(false, true); });
  Array.prototype.forEach.call(root.querySelectorAll('.cb-links [data-side]'), function (b) {
    b.addEventListener('click', function () { showSide(b.getAttribute('data-side'), true, b); });
  });
  Array.prototype.forEach.call(tabBtns, function (b) {
    b.addEventListener('click', function () { showSide(b.getAttribute('data-side'), !state.chamber, b); });
    b.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight' && e.key !== 'Home' && e.key !== 'End') return;
      e.preventDefault();
      var next = (e.key === 'ArrowLeft' || e.key === 'Home') ? tabBtns[0] : tabBtns[tabBtns.length - 1];
      next.focus();
      showSide(next.getAttribute('data-side'), !state.chamber, next);
    });
  });
  if (secs.nine) {
    secs.nine.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Home' && e.key !== 'End') return;
      var rows = Array.prototype.slice.call(secs.nine.querySelectorAll('.cb-voice-open'));
      var at = rows.indexOf(document.activeElement);
      if (at === -1 || !rows.length) return;
      e.preventDefault();
      var to = e.key === 'Home' ? 0 : e.key === 'End' ? rows.length - 1 : e.key === 'ArrowDown' ? Math.min(rows.length - 1, at + 1) : Math.max(0, at - 1);
      rows[to].focus();
    });
  }
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' && e.key !== 'Esc') return;
    if (e.defaultPrevented || !state.open) return;
    if (!root.contains(document.activeElement)) return;
    e.preventDefault();
    stepBack();
  });
  document.addEventListener('sv:dock-open', function (e) {
    if (e && e.detail === 'activity' && state.open) setOpen(false, 'dock');
  });
  document.addEventListener('visibilitychange', function () {
    if (document.hidden || !state.open) return;
    setStamp();
    if (!state.lastAt || Date.now() - state.lastAt > STALE_ROOM_MS) read('room', { force: true });
  });
  document.addEventListener('sv:pin-unlocked', function () {
    if (state.stopped === 'locked') state.stopped = '';
    if (state.open) read('room', { force: true });
  });
  document.addEventListener('sv:eye-event', function (e) {
    var msg = (e && e.detail) || {};
    var kind = msg.kind || msg.event_type || msg.type;
    if (kind === 'council_sitting') {
      /* The task tells of every attempt that closed; only one that SAT
         ('done' or 'partial') is a sitting. Too late, a switch off, a
         failure or the AI budget's refusal is said as such while open
         and never raises the shut tab's badge. */
      var d = msg.data || {};
      var sat = d.status === 'done' || d.status === 'partial';
      var on = [d.symbol, d.side].filter(Boolean).join(' ');
      if (state.open) say(W(sat ? 'sat_on' : 'not_sat', { s: on }));
      else if (sat) setUnread(state.unread + 1);
    }
    if (state.open && (kind === 'fill_open' || kind === 'fill_close' || kind === 'council_sitting')) eventRead(kind);
  });
  document.addEventListener('sv:chrome-moved', function (e) {
    if (e && e.detail && e.detail.by === 'council') return;
    schedule();
  });
  window.addEventListener('resize', schedule);
  root.addEventListener('transitionend', function (e) {
    if (e.target === root && (e.propertyName === 'transform' || e.propertyName === 'width')) { chromeMoved(); schedule(); }
  });
  var toggleBtn = document.getElementById('railToggleBtn');
  if (toggleBtn) toggleBtn.addEventListener('transitionend', schedule);
  if (window.MutationObserver) {
    try { new window.MutationObserver(schedule).observe(document.body, { attributes: true, attributeFilter: ['style'] }); } catch (e) { /* the resize covers it */ }
    var hordeEl = document.getElementById('svHorde');
    if (hordeEl) {
      try {
        new window.MutationObserver(function () {
          if (state.chamber && hordeOpen()) { setChamber(false); say(W('narrowed_horde')); }
          schedule();
        }).observe(hordeEl, { attributes: true, attributeFilter: ['class'] });
      } catch (e) { /* the narrowing waits for the next resize */ }
    }
  }
  if (mq && mq.addEventListener) mq.addEventListener('change', schedule);

  window.SVCouncilBand = { toggle: toggle, widen: widen };

  /* A band left open comes back open, in place, on a wide screen, and
     never beside an open activity drawer. */
  state.side = savedSide();
  var drawer = document.getElementById('svActivity');
  if (remembered() && !(drawer && drawer.classList.contains('open'))) {
    root.classList.add('sv-council-band-instant');
    setOpen(true, 'restore');
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () { root.classList.remove('sv-council-band-instant'); });
    });
  } else {
    setUnread(0);
  }
  schedule();
})();
