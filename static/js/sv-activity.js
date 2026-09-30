/* The activity drawer — Sauron's live log, under the signals rail.
 *
 * templates/_partials/activity_drawer.html draws a drawer tucked under the
 * rail with only its tab showing (static/css/sv-activity.css); this file
 * opens and shuts it and keeps its log current. The log is
 * dashboard/activity_feed.py, served as {"now", "events"} by the URL in
 * the drawer's data-feed-url (staff only: the partial is not rendered for
 * anyone else, and without it this file does nothing).
 *
 *   - The tab toggles .open and aria-expanded; the close button and Escape
 *     shut it and put focus back on the tab. The choice is remembered in
 *     localStorage under 'sauron_activity_open'.
 *   - Cadence: once on the first open, then every 20 s while the drawer is
 *     open AND the tab is visible, once more when it becomes visible, and
 *     800 ms after an sv:eye-event (base.html owns the one /ws/eye/ socket
 *     and re-dispatches every message on document; nothing here opens a
 *     socket). Shut, nothing polls: an eye event only moves the tab's
 *     badge, which clears when the drawer opens.
 *   - A 423 is the idle lock: polling stops until sv:pin-unlocked. A
 *     redirect or a reply that is not JSON is a session that ended: polling
 *     stops until the drawer is opened again or the tab is looked at anew.
 *   - Each read after the first asks only for what is newer than the
 *     newest line held (less a two-minute overlap for a row committed
 *     late), and the ids already painted are dropped.
 *   - Rows are built with textContent only — every string in them came
 *     from a database row — and at most 200 stay in the list. New rows
 *     slide in unless the reader asked for reduced motion.
 *   - A pipeline or a bot that runs again and runs well replaces its own
 *     last quiet line; a run that warned or failed keeps a line of its own.
 */
(function () {
  'use strict';
  var root = document.getElementById('svActivity');
  if (!root) return;

  var FEED_URL = root.getAttribute('data-feed-url') || '';
  var OPEN_KEY = 'sauron_activity_open';
  var POLL_MS = 20000;
  var EVENT_DELAY_MS = 800;
  var AGO_MS = 30000;
  var OVERLAP_MS = 120000;
  var MAX_ROWS = 200;
  var NEW_MS = 600;
  /* The eye's kinds that become a line in this log. close_pending is not
     one yet (the close is), new_signal is not read here at all. */
  var COUNTED = { fill_open: 1, fill_close: 1, gate_reject: 1, notification: 1,
                  run_complete: 1, sauron_answer: 1 };
  var KIND_WORDS = { trade: 'trade', gate: 'gate', ai: 'ai', pipeline: 'pipeline',
                     bot: 'bot', alert: 'alert', system: 'system' };
  var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  var tab = document.getElementById('svActivityTab');
  var panel = document.getElementById('svActivityPanel');
  var list = document.getElementById('svActivityList');
  var stateBox = document.getElementById('svActivityState');
  var badge = document.getElementById('svActivityBadge');
  var closeBtn = document.getElementById('svActivityClose');
  var dot = document.getElementById('svActivityDot');
  var stamp = document.getElementById('svActivityStamp');
  var chips = root.querySelectorAll('.sv-activity-chip');
  if (!tab || !panel || !list) return;

  var seen = {};
  var newest = '';
  var loaded = false, inflight = false, stopped = false, failed = false;
  var pollTimer = null, eventTimer = null, agoTimer = null;
  var unread = 0, filter = 'all';

  /* ── words ───────────────────────────────────────────────────────── */
  /* The house tenses (dashboard.views_day._ago): the server sends them
     with each line; this keeps them true while the line stays up. */
  function ago(iso) {
    var t = Date.parse(iso);
    if (isNaN(t)) return '';
    var s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + ' min ago';
    if (s < 48 * 3600) return Math.floor(s / 3600) + ' h ago';
    return Math.floor(s / 86400) + ' d ago';
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function utc(iso) {
    var d = new Date(Date.parse(iso));
    if (isNaN(d.getTime())) return '';
    return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate())
      + ' ' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ':' + pad(d.getUTCSeconds()) + ' UTC';
  }
  function safeLink(u) {
    u = String(u || '');
    if (u.charAt(0) === '/' && u.charAt(1) !== '/') return u;
    if (/^https?:\/\//i.test(u)) return u;
    return '';
  }

  /* ── storage (a private window may refuse it: the choice then lasts the page) ── */
  function remembered() {
    try { return window.localStorage.getItem(OPEN_KEY) === 'open'; } catch (e) { return false; }
  }
  function remember(on) {
    try { window.localStorage.setItem(OPEN_KEY, on ? 'open' : 'closed'); } catch (e) { /* the choice lasts the page */ }
  }

  /* ── states ──────────────────────────────────────────────────────── */
  function setState(cls, title, words) {
    if (!stateBox) return;
    while (stateBox.firstChild) stateBox.removeChild(stateBox.firstChild);
    if (!cls) return;
    var box = document.createElement('div');
    box.className = cls;
    if (title) {
      var b = document.createElement('b');
      b.textContent = title;
      box.appendChild(b);
    }
    box.appendChild(document.createTextNode(words || ''));
    stateBox.appendChild(box);
  }
  function setDot(state) {
    if (!dot) return;
    dot.classList.remove('live', 'err');
    if (state) dot.classList.add(state);
  }
  function setUnread(n) {
    unread = Math.max(0, n);
    if (badge) {
      badge.textContent = unread > 99 ? '99+' : String(unread);
      badge.hidden = unread === 0;
    }
    tab.setAttribute('aria-label', 'Sauron activity' + (unread ? ', ' + unread + ' new' : ''));
  }
  function visibleRows() {
    var n = 0;
    for (var i = 0; i < list.children.length; i++) if (!list.children[i].hidden) n++;
    return n;
  }
  function paintEmpty() {
    if (failed) return;
    if (!list.children.length) {
      setState('sv-empty', 'Nothing in the log yet',
               'No trade, gate refusal, agent call, pipeline run, bot tick or alert in the window this log reads. New lines appear here as they happen.');
    } else if (!visibleRows()) {
      setState('sv-empty', 'Nothing of this kind',
               'Nothing of this kind among the last ' + list.children.length + ' lines. "All" shows every one.');
    } else {
      setState('');
    }
  }

  /* ── rows ────────────────────────────────────────────────────────── */
  function matches(li) { return filter === 'all' || li.getAttribute('data-kind') === filter; }
  function buildRow(ev) {
    var level = { info: 1, ok: 1, warn: 1, error: 1 }[ev.level] ? ev.level : 'info';
    var kind = KIND_WORDS[ev.kind] || 'system';
    var li = document.createElement('li');
    li.className = 'sv-act-row sv-act-' + level;
    li.setAttribute('data-kind', kind);
    li.setAttribute('data-at', String(ev.at || ''));
    li.setAttribute('data-id', String(ev.id || ''));
    var mark = document.createElement('span');
    mark.className = 'sv-act-mark';
    mark.setAttribute('aria-hidden', 'true');
    li.appendChild(mark);
    var main = document.createElement('div');
    main.className = 'sv-act-main';
    var meta = document.createElement('div');
    meta.className = 'sv-act-meta';
    var k = document.createElement('span');
    k.className = 'sv-act-kind';
    k.textContent = kind + (level === 'error' ? ' · error' : level === 'warn' ? ' · warning' : '');
    var when = document.createElement('time');
    when.className = 'sv-act-ago';
    when.setAttribute('datetime', String(ev.at || ''));
    when.title = utc(ev.at);
    when.textContent = ev.ago || ago(ev.at);
    meta.appendChild(k);
    /* The money world of a fill (2026-09-30): the platform's one marker,
     * REAL MONEY solid red, DEMO gold, PAPER grey; a real-money row also
     * carries the red edge. Nothing for a row that is not a fill. */
    var WORLD_WORDS = { live: 'REAL MONEY', demo: 'DEMO', paper: 'PAPER' };
    if (WORLD_WORDS[ev.world]) {
      var w = document.createElement('span');
      w.className = 'sv-world sv-world--' + ev.world;
      w.textContent = WORLD_WORDS[ev.world];
      meta.appendChild(w);
      if (ev.world === 'live') li.className += ' sv-row--live';
    }
    meta.appendChild(when);
    main.appendChild(meta);
    var href = safeLink(ev.url);
    var title = document.createElement(href ? 'a' : 'span');
    title.className = 'sv-act-title';
    if (href) title.setAttribute('href', href);
    title.textContent = String(ev.title || '');
    main.appendChild(title);
    if (ev.detail) {
      var detail = document.createElement('div');
      detail.className = 'sv-act-detail';
      detail.textContent = String(ev.detail);
      main.appendChild(detail);
    }
    li.appendChild(main);
    li.hidden = !matches(li);
    return li;
  }
  /* Newest first: a line goes before the first one older than it, so a
     row committed late still lands where its time says. */
  function insert(li) {
    var at = li.getAttribute('data-at');
    var node = list.firstChild;
    while (node && node.getAttribute('data-at') >= at) node = node.nextSibling;
    list.insertBefore(li, node);
  }
  function trim() {
    while (list.children.length > MAX_ROWS) {
      var last = list.lastChild;
      var group = last.getAttribute('data-group');
      if (group && quietRow[group] === last) delete quietRow[group];
      delete seen[last.getAttribute('data-id')];
      list.removeChild(last);
    }
  }
  /* A pipeline or a bot that ran again and ran well REPLACES its own last
     quiet line: some components run every 15 s, and one line per run
     buried every trade and refusal under them in minutes. A run that
     warned or failed stays a line of its own, and is never replaced. */
  var quietRow = {};
  function groupOf(ev) {
    if (ev.kind !== 'pipeline' && ev.kind !== 'bot') return '';
    return String(ev.id).replace(/:\d+$/, '');
  }
  function apply(data) {
    var events = (data && data.events) || [];
    var animate = loaded && !reduce;
    for (var i = events.length - 1; i >= 0; i--) {
      var ev = events[i];
      if (!ev || !ev.id || seen[ev.id]) continue;
      seen[ev.id] = 1;
      var group = groupOf(ev);
      var quiet = ev.level === 'ok' || ev.level === 'info';
      if (group && quiet) {
        var prev = quietRow[group];
        if (prev && prev.parentNode === list) {
          if (prev.getAttribute('data-at') >= String(ev.at || '')) continue;
          list.removeChild(prev);
        }
      }
      var li = buildRow(ev);
      if (group) li.setAttribute('data-group', group);
      if (group && quiet) quietRow[group] = li;
      insert(li);
      if (animate) {
        li.classList.add('sv-act-new');
        (function (row) {
          window.setTimeout(function () { row.classList.remove('sv-act-new'); }, NEW_MS);
        })(li);
      }
      if (!newest || String(ev.at) > newest) newest = String(ev.at);
    }
    trim();
    loaded = true;
    failed = false;
    paintEmpty();
    if (stamp && data && data.now) stamp.textContent = 'read ' + utc(data.now).slice(11, 16) + ' UTC';
    setDot('live');
  }

  /* ── fetch ───────────────────────────────────────────────────────── */
  function isOpen() { return root.classList.contains('open'); }
  function feedUrl() {
    if (!newest) return FEED_URL;
    var t = Date.parse(newest);
    if (isNaN(t)) return FEED_URL;
    var since = new Date(t - OVERLAP_MS).toISOString();
    return FEED_URL + (FEED_URL.indexOf('?') === -1 ? '?' : '&') + 'since=' + encodeURIComponent(since);
  }
  function stop(title, words) {
    stopped = true;
    setDot('');
    if (!list.children.length) { failed = true; setState('sv-empty', title, words); }
    else if (stamp) stamp.textContent = title.toLowerCase();
  }
  function fetchFeed() {
    if (!FEED_URL || inflight || stopped || document.hidden || !isOpen()) return;
    inflight = true;
    if (!loaded) setState('sv-loading', '', "Reading Sauron's log");
    fetch(feedUrl(), { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (r) {
        var type = (r.headers && r.headers.get('content-type')) || '';
        if (r.status === 423) {
          stop('Locked', 'The log carries on once the PIN is entered.');
          return null;
        }
        /* login_required answers a fetch with the login page after the
           redirect, as a 200: that is a session that ended, not a log. */
        if (r.redirected || !/json/i.test(type)) {
          stop('Signed out', 'Sign in again to read the log.');
          return null;
        }
        if (r.status === 403) {
          stop('Staff only', 'This account cannot read the log.');
          return null;
        }
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) { if (data) apply(data); })
      .catch(function () {
        setDot('err');
        if (!list.children.length) {
          failed = true;
          var box = document.createElement('div');
          box.className = 'sv-error';
          box.textContent = 'The log could not be read. It tries again in 20 seconds.';
          if (stateBox) {
            while (stateBox.firstChild) stateBox.removeChild(stateBox.firstChild);
            stateBox.appendChild(box);
          }
        } else if (stamp) {
          stamp.textContent = 'read failed · retrying';
        }
      })
      .then(function () { inflight = false; }, function () { inflight = false; });
  }
  function startPolling() {
    if (pollTimer) return;
    pollTimer = window.setInterval(function () {
      if (isOpen() && !document.hidden && !stopped) fetchFeed();
    }, POLL_MS);
    agoTimer = window.setInterval(refreshAgo, AGO_MS);
  }
  function stopPolling() {
    if (pollTimer) { window.clearInterval(pollTimer); pollTimer = null; }
    if (agoTimer) { window.clearInterval(agoTimer); agoTimer = null; }
    if (eventTimer) { window.clearTimeout(eventTimer); eventTimer = null; }
  }
  function refreshAgo() {
    var times = list.querySelectorAll('.sv-act-ago');
    for (var i = 0; i < times.length; i++) {
      var words = ago(times[i].getAttribute('datetime'));
      if (words && times[i].textContent !== words) times[i].textContent = words;
    }
  }

  /* ── open / shut ─────────────────────────────────────────────────── */
  function setOpen(on, save) {
    root.classList.toggle('open', on);
    tab.setAttribute('aria-expanded', on ? 'true' : 'false');
    if (on) panel.removeAttribute('inert'); else panel.setAttribute('inert', '');
    if (save) remember(on);
    if (on) {
      setUnread(0);
      stopped = false;
      refreshAgo();
      fetchFeed();
      startPolling();
    } else {
      stopPolling();
    }
  }
  function shut(returnFocus) {
    if (!isOpen()) return;
    setOpen(false, true);
    if (returnFocus) { try { tab.focus(); } catch (e) { /* an old engine keeps its focus */ } }
  }

  tab.addEventListener('click', function () {
    if (isOpen()) shut(false); else setOpen(true, true);
  });
  if (closeBtn) closeBtn.addEventListener('click', function () { shut(true); });
  /* Escape shuts it when the reader is in it, or in nothing at all — not
     while they type in some other field. The overlay controller answers
     Escape first for any menu or dialog it holds open (sv-overlay.js stops
     the event), and a handler that already used it marks it handled. */
  document.addEventListener('keydown', function (e) {
    if (e.defaultPrevented || !isOpen()) return;
    if (e.key !== 'Escape' && e.key !== 'Esc') return;
    var at = document.activeElement;
    if (at && at !== document.body && !root.contains(at)) return;
    e.preventDefault();
    shut(true);
  });

  Array.prototype.forEach.call(chips, function (chip) {
    chip.addEventListener('click', function () {
      filter = chip.getAttribute('data-filter') || 'all';
      Array.prototype.forEach.call(chips, function (c) {
        c.setAttribute('aria-pressed', c === chip ? 'true' : 'false');
      });
      for (var i = 0; i < list.children.length; i++) list.children[i].hidden = !matches(list.children[i]);
      if (loaded) paintEmpty();
    });
  });

  /* ── the page's own signals ──────────────────────────────────────── */
  document.addEventListener('visibilitychange', function () {
    if (document.hidden || !isOpen()) return;
    stopped = false;
    refreshAgo();
    fetchFeed();
  });
  /* static/js/idle-lock.js unlocks in place and announces it; a 423 had
     stopped the poll. */
  document.addEventListener('sv:pin-unlocked', function () {
    stopped = false;
    if (isOpen()) fetchFeed();
  });
  document.addEventListener('sv:eye-event', function (e) {
    var msg = (e && e.detail) || {};
    var kind = msg.kind || msg.event_type || msg.type;
    if (!kind || !COUNTED[kind]) return;
    if (kind === 'notification') {
      var d = msg.data || {};
      /* A fill's bell row is silent (its fill_open/fill_close counted it)
         and a gate refusal's opens with the gate's cross (its gate_reject
         did): the log prints each fact once, and so does the badge. */
      if (d.silent || String(d.title || '').charAt(0) === '✕') return;
    }
    if (isOpen()) {
      if (eventTimer) window.clearTimeout(eventTimer);
      /* Not past a stop: a locked door or an ended session is not
         reopened by the news that something happened behind it. */
      eventTimer = window.setTimeout(function () {
        eventTimer = null;
        fetchFeed();
      }, EVENT_DELAY_MS);
    } else {
      setUnread(unread + 1);
    }
  });

  /* A drawer left open comes back open, in place rather than sliding. */
  if (remembered()) {
    root.classList.add('sv-activity-instant');
    setOpen(true, false);
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () { root.classList.remove('sv-activity-instant'); });
    });
  } else {
    setUnread(0);
  }
})();
