/* A day of Sauron, live — the home page's layer over the ring.
 *
 * static/js/sv-day-scheme.js draws the ring from the schedule the page was
 * served with and exposes window.SVDay.current. This file adds NOW: it
 * fetches the section's data-day-live-url (dashboard.views_day: the state
 * of every beat entry, the day's counts per stage, the three clusters, the
 * daily crontab marks) and paints
 *
 *   - the ring, through ctl.setLive(live): a dot and a tint per node, and
 *     the RIGHT NOW block in the open panel;
 *   - the seven tiles above it: state dot, two headline numbers, the line
 *     "ran 2 min ago"; a tile click lights its node and opens its panel;
 *   - the 24-hour strip below: the daily tasks on their minute, tinted by
 *     their state, and a cursor that moves every minute;
 *   - the header line: "78 scheduled tasks · N live · N stale · N off ·
 *     refreshed HH:MM".
 *
 * Cadence: once when the ring mounts, then every 60 s while the tab is
 * visible, once more when it becomes visible again, and 800 ms after a
 * fill, a close, a pending close, a new signal or a run completes on the
 * shared sv:eye-event (base.html owns the one /ws/eye/ socket and
 * re-dispatches its payloads; nothing here opens a socket). A response
 * that is not OK — 423 from the idle lock, a 5xx — stops the polling
 * until the tab is next visible, so a locked tab does not poll a locked
 * door once a minute.
 *
 * Motion: a changed number flashes through a CSS transition (class
 * day-changed); under prefers-reduced-motion the class is never added and
 * the strip's cursor jumps instead of sliding (the sheet's media block).
 * The collapse state lives in localStorage under 'sv-day-collapsed'.
 */
(function () {
  'use strict';
  var section = document.getElementById('dayHome');
  if (!section) return;

  var LIVE_URL = section.getAttribute('data-day-live-url') || '';
  var POLL_MS = 60000;
  var EVENT_DELAY_MS = 800;
  var FLASH_MS = 900;
  var COLLAPSE_KEY = section.getAttribute('data-day-collapse-key') || 'sv-day-collapsed';
  var KINDS = { fill_open: 1, fill_close: 1, close_pending: 1, new_signal: 1, run_complete: 1 };
  var STATES = ['live', 'stale', 'off', 'quiet', 'broken'];
  var STATE_CLASSES = STATES.map(function (s) { return 'day-' + s; });
  var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  var meta = document.getElementById('dayHomeMeta');
  var toggle = document.getElementById('dayHomeToggle');
  var body = document.getElementById('dayHomeBody');
  var ticks = document.getElementById('dayClockTicks');
  var marks = document.getElementById('dayClockMarks');
  var list = document.getElementById('dayClockList');
  var cursor = document.getElementById('dayClockCursor');
  var nowText = document.getElementById('dayClockNowText');
  var tiles = section.querySelectorAll('[data-day-tile]');

  function fmt(n) {
    if (typeof n === 'number' && n % 1 !== 0) return String(n);
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function setState(el, state) {
    if (!el) return;
    STATE_CLASSES.forEach(function (c) { el.classList.remove(c); });
    el.classList.add('day-' + (STATES.indexOf(state) === -1 ? 'quiet' : state));
  }

  /* ── collapse ────────────────────────────────────────────────────── */
  function readCollapsed() {
    try { return window.localStorage.getItem(COLLAPSE_KEY) === '1'; } catch (e) { return false; }
  }
  function setCollapsed(on, remember) {
    section.classList.toggle('day-collapsed', on);
    if (toggle) toggle.setAttribute('aria-expanded', on ? 'false' : 'true');
    if (body) body.hidden = on;
    if (remember) {
      try { window.localStorage.setItem(COLLAPSE_KEY, on ? '1' : '0'); } catch (e) { /* private mode: the choice lasts the page */ }
    }
  }
  setCollapsed(readCollapsed(), false);
  if (toggle) {
    toggle.addEventListener('click', function () {
      setCollapsed(!section.classList.contains('day-collapsed'), true);
    });
  }

  /* ── the tiles ───────────────────────────────────────────────────── */
  function flash(el) {
    if (reduce || !el) return;
    el.classList.remove('day-changed');
    void el.offsetWidth;
    el.classList.add('day-changed');
    window.setTimeout(function () { el.classList.remove('day-changed'); }, FLASH_MS);
  }
  function setNum(box, metric) {
    if (!box) return;
    var b = box.querySelector('b'), small = box.querySelector('small');
    if (!metric) return;
    var value = fmt(metric[0]), words = String(metric[1] || '');
    if (b && b.textContent !== value) { b.textContent = value; flash(b); }
    if (small && small.textContent !== words) small.textContent = words;
  }
  function paintTiles(live) {
    var stages = (live && live.stages) || {};
    Array.prototype.forEach.call(tiles, function (tile) {
      var key = tile.getAttribute('data-day-tile'), lv = stages[key];
      if (!lv) return;
      setState(tile, lv.state);
      var ms = lv.metrics || [];
      setNum(tile.querySelector('[data-day-tile-m="0"]'), ms[0]);
      setNum(tile.querySelector('[data-day-tile-m="1"]'), ms[1]);
      var words = tile.querySelector('[data-day-tile-words]');
      if (words) words.textContent = (lv.state || 'quiet').toUpperCase() + ' · ' + (lv.words || '');
    });
  }
  Array.prototype.forEach.call(tiles, function (tile) {
    tile.addEventListener('click', function () {
      var ctl = window.SVDay && window.SVDay.current;
      var key = tile.getAttribute('data-day-tile');
      if (!ctl || !ctl.nodes || !ctl.nodes[key]) return;
      ctl.light(ctl.nodes[key].g);
      ctl.render(key);
      if (ctl.panel && window.innerWidth < 900) {
        try { ctl.panel.scrollIntoView({ block: 'nearest', behavior: reduce ? 'auto' : 'smooth' }); } catch (e) { /* an old engine scrolls not at all */ }
      }
    });
  });

  /* ── the 24-hour strip ───────────────────────────────────────────── */
  function buildTicks() {
    if (!ticks || ticks.childNodes.length) return;
    for (var h = 0; h <= 24; h++) {
      var t = document.createElement('span');
      t.className = 'day-clock-tick' + (h % 6 === 0 ? ' day-clock-tick-major' : '');
      t.style.left = (h / 24 * 100) + '%';
      if (h % 6 === 0 && h < 24) t.setAttribute('data-h', pad(h) + ':00');
      ticks.appendChild(t);
    }
  }
  function paintMarks(live) {
    if (!marks) return;
    var items = (live && live.clock && live.clock.marks) || [];
    while (marks.firstChild) marks.removeChild(marks.firstChild);
    if (list) while (list.firstChild) list.removeChild(list.firstChild);
    var lastLeft = -100, row = 0;
    for (var i = 0; i < items.length; i++) {
      var m = items[i], left = Math.max(0, Math.min(1440, m.m)) / 1440 * 100;
      var hh = Math.floor(m.m / 60), mm = m.m % 60, when = pad(hh) + ':' + pad(mm);
      var el = document.createElement('span');
      el.className = 'day-clock-mark';
      setState(el, m.state);
      /* Two daily tasks on the same minute stack instead of overprinting. */
      row = (left - lastLeft < 2.2) ? row + 1 : 0;
      lastLeft = left;
      el.style.left = left + '%';
      el.setAttribute('data-row', String(row % 3));
      el.title = when + ' UTC — ' + m.label + ' (' + m.key + ') · ' + (m.state || 'quiet');
      var lbl = document.createElement('i');
      lbl.textContent = when + ' ' + m.label;
      el.appendChild(lbl);
      marks.appendChild(el);
      if (!list) continue;
      /* The readable form of the same mark: a chip in the list below. */
      var chip = document.createElement('span');
      chip.className = 'day-clock-chip';
      setState(chip, m.state);
      chip.title = m.key + ' · ' + (m.state || 'quiet');
      var dot = document.createElement('i');
      dot.className = 'day-clock-swatch';
      setState(dot, m.state);
      var b = document.createElement('b');
      b.textContent = when;
      chip.appendChild(dot);
      chip.appendChild(b);
      chip.appendChild(document.createTextNode(' ' + m.label));
      list.appendChild(chip);
    }
  }
  function paintCursor(minute) {
    var d = new Date();
    var now = (typeof minute === 'number') ? minute : d.getUTCHours() * 60 + d.getUTCMinutes();
    if (cursor) cursor.style.left = (now / 1440 * 100) + '%';
    if (nowText) nowText.textContent = 'NOW ' + pad(Math.floor(now / 60)) + ':' + pad(now % 60) + ' UTC';
  }
  buildTicks();
  paintCursor();
  window.setInterval(function () { paintCursor(); }, 60000);

  /* ── the header line ─────────────────────────────────────────────── */
  function paintMeta(live) {
    if (!meta) return;
    var c = (live && live.counts) || {};
    var total = c.total || meta.getAttribute('data-day-total') || '0';
    meta.textContent = fmt(total) + ' scheduled tasks · ' + fmt(c.live || 0) + ' live · '
      + fmt(c.stale || 0) + ' stale · ' + fmt(c.off || 0) + ' off'
      + ((c.broken || 0) ? ' · ' + fmt(c.broken) + ' broken' : '')
      + ' · refreshed ' + String((live && live.now) || '').replace(' UTC', '');
    setState(meta, (c.broken || 0) ? 'broken' : (c.stale || 0) ? 'stale' : (c.live || 0) ? 'live' : 'quiet');
  }

  /* ── fetch and apply ─────────────────────────────────────────────── */
  var stopped = false, inflight = false, started = false, eventTimer = null;
  function apply(live) {
    var ctl = window.SVDay && window.SVDay.current;
    if (ctl && ctl.setLive) ctl.setLive(live);
    paintTiles(live);
    paintMarks(live);
    paintCursor(live && live.clock ? live.clock.minute : undefined);
    paintMeta(live);
    section.classList.add('day-has-live');
  }
  function fetchLive() {
    if (!LIVE_URL || inflight || document.hidden) return;
    inflight = true;
    fetch(LIVE_URL, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (r) {
        if (!r.ok) {
          /* 423 is the idle lock; anything else is a server that cannot
             answer. Either way the last reading stands and the polling
             stops until the tab is next looked at. */
          stopped = true;
          throw new Error('HTTP ' + r.status);
        }
        return r.json();
      })
      .then(function (live) { stopped = false; apply(live); })
      .catch(function () {
        if (meta && !section.classList.contains('day-has-live')) meta.textContent = meta.getAttribute('data-day-total') + ' scheduled tasks · live reading unavailable';
      })
      .then(function () { inflight = false; }, function () { inflight = false; });
  }
  function start() {
    if (started) return;
    started = true;
    fetchLive();
    window.setInterval(function () { if (!document.hidden && !stopped) fetchLive(); }, POLL_MS);
  }
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) return;
    stopped = false;
    paintCursor();
    if (started) fetchLive(); else start();
  });
  document.addEventListener('sv:eye-event', function (e) {
    var msg = (e && e.detail) || {};
    var kind = msg.kind || msg.event_type || msg.type;
    if (!kind || !KINDS[kind]) return;
    if (eventTimer) window.clearTimeout(eventTimer);
    eventTimer = window.setTimeout(function () { eventTimer = null; stopped = false; fetchLive(); }, EVENT_DELAY_MS);
  });

  /* The ring mounts from sv-day-scheme.js (deferred, loaded first), so it
     is usually there already; the event covers the other order, and the
     DOMContentLoaded fallback covers a page whose ring did not mount at
     all — the tiles and the strip still deserve their numbers. */
  if (window.SVDay && window.SVDay.current) start();
  else document.addEventListener('sv:day-mounted', start);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { window.setTimeout(start, 0); });
  else window.setTimeout(start, 0);
})();
