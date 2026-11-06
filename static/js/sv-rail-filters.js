/* The signal rail's filters and display choices (2026-11-06).
 *
 * The operator asked for filters and display choices in the bands — for
 * the signals and for the watchlist, by asset class or otherwise. They run
 * here, in the browser, on facts the server renders on every row
 * (data-asset-class, data-side, data-score-b, data-votes, data-live,
 * data-held, data-rule-key), so a click acts at once, with no refetch.
 *
 * STATE ON THE HOST, FACTS ON THE ROW. The state is a set of data-f-*
 * attributes on the hosts no refresh replaces — the signals rail section
 * and the headband SIGNALS dropdown ([data-sv-fhost="signals"]), the
 * watchlist body and the headband WATCHLIST dropdown
 * ([data-sv-fhost="watch"]) — and static/css/sv-rail.css hides and orders
 * the rows from it. A muted rule is one generated rule in
 * <style id="svRuleOff">. This script only writes those attributes,
 * rewrites that style, flips aria-pressed on the controls and counts the
 * rows shown into the status lines; no row is ever edited, moved or bound,
 * and every click is delegated, so a rail refresh, a region swap or a
 * price tick has nothing to undo and nothing to rebind.
 *
 * The server renders the hosts from the operator's prefs (dashboard
 * rail_prefs) for a first paint already filtered; a change is saved to the
 * profile (POST /api/rail-prefs/) half a second after the last click, so
 * every browser, and the phone, draw the same rail. A locked session (423)
 * engages the PIN lock and keeps the choice on the page; any other failure
 * keeps it and says "not saved". "show all" (data-f-peek) pauses every
 * filter at once, for a look, and is never saved.
 *
 * DISPLAY ONLY: nothing here reaches the engine, the bots, the alerts or
 * the ticket, and no filter writes the watchlist flag the scanner reads.
 */
(function () {
  'use strict';
  if (window.__svRailFilters) return;
  window.__svRailFilters = true;

  var DEFAULTS = {
    signals: { cls: [], side: 'all', score: 0, stage: 'all', held: 'all',
               rules_off: [], sort: 'new', group: false, dense: false, gone: false },
    watch: { cls: [], held: 'all', sort: 'class', group: false, dense: false }
  };
  var SECTION = { signals: 'sig', watch: 'watch' };
  var ATTR = { cls: 'data-f-class', side: 'data-f-side', score: 'data-f-score',
               stage: 'data-f-stage', held: 'data-f-held', sort: 'data-f-sort',
               group: 'data-f-group', dense: 'data-f-dense', gone: 'data-f-gone' };
  var BOOL = { group: true, dense: true, gone: true };
  var SAVE_MS = 500;

  var state = {}, peeking = {}, ruleKeys = {};
  var saveTimer = null, unsaved = false;

  function arr(list) { return Array.prototype.slice.call(list || []); }
  function hosts(kind) { return arr(document.querySelectorAll('[data-sv-fhost="' + kind + '"]')); }
  function controls(kind) { return arr(document.querySelectorAll('[data-f-kind="' + kind + '"] [data-f-key]')); }
  function copy(v) { return Array.isArray(v) ? v.slice() : v; }

  /* The state of a kind, read off its first host: the server rendered it
     from the stored prefs. The muted rules come from the style's own
     record ([[name, key], ...]). */
  function readState(kind) {
    var h = hosts(kind)[0];
    var d = DEFAULTS[kind], s = {};
    Object.keys(d).forEach(function (k) {
      if (k === 'rules_off') return;
      var v = h ? h.getAttribute(ATTR[k]) : null;
      if (k === 'cls') s.cls = v ? v.split(/\s+/).filter(Boolean) : [];
      else if (BOOL[k]) s[k] = v === '1';
      else if (k === 'score') s.score = parseInt(v, 10) || 0;
      else s[k] = v || d[k];
    });
    if (kind === 'signals') {
      s.rules_off = [];
      var style = document.getElementById('svRuleOff');
      var rec = [];
      try { rec = JSON.parse((style && style.getAttribute('data-rules')) || '[]'); } catch (e) { rec = []; }
      rec.forEach(function (pair) {
        if (!pair || typeof pair[0] !== 'string') return;
        s.rules_off.push(pair[0]);
        ruleKeys[pair[0]] = pair[1];
      });
    }
    return s;
  }

  function learnRuleKeys() {
    arr(document.querySelectorAll('[data-f-key="rule"][data-rule-key]')).forEach(function (b) {
      ruleKeys[b.getAttribute('data-f-val') || ''] = b.getAttribute('data-rule-key');
    });
  }

  function writeHosts(kind) {
    var s = state[kind];
    hosts(kind).forEach(function (h) {
      Object.keys(ATTR).forEach(function (k) {
        if (!(k in s)) return;
        var v = s[k];
        if (k === 'cls') v = s.cls.join(' ');
        else if (BOOL[k]) v = s[k] ? '1' : '0';
        else v = String(v);
        if (h.getAttribute(ATTR[k]) !== v) h.setAttribute(ATTR[k], v);
      });
      if (peeking[kind]) h.setAttribute('data-f-peek', '1');
      else if (h.hasAttribute('data-f-peek')) h.removeAttribute('data-f-peek');
    });
  }

  function pressedFor(kind, key, val) {
    var s = state[kind];
    if (key === 'cls') return val ? s.cls.indexOf(val) >= 0 : s.cls.length === 0;
    if (key === 'rule') return s.rules_off.indexOf(val) < 0;
    if (key === 'peek') return !!peeking[kind];
    if (BOOL[key]) return (s[key] ? '1' : '0') === val;
    if (key in s) return String(s[key]) === val;
    return false;
  }

  function paintControls(kind) {
    controls(kind).forEach(function (c) {
      var key = c.getAttribute('data-f-key');
      if (key === 'peek') return;
      var want = pressedFor(kind, key, c.getAttribute('data-f-val') || '') ? 'true' : 'false';
      if (c.getAttribute('aria-pressed') !== want) c.setAttribute('aria-pressed', want);
    });
  }

  function writeRuleStyle() {
    var style = document.getElementById('svRuleOff');
    if (!style || !state.signals) return;
    var css = '', rec = [];
    state.signals.rules_off.forEach(function (name) {
      var key = ruleKeys[name];
      rec.push([name, key || '']);
      if (!key || !/^r[0-9a-f-]+$/.test(key)) return;
      css += '[data-sv-fhost="signals"]:not([data-f-peek="1"]) [data-sv-row]'
           + '[data-rule-key="' + key + '"]{display:none!important}';
    });
    if (style.textContent !== css) style.textContent = css;
    style.setAttribute('data-rules', JSON.stringify(rec));
  }

  /* What the filters hide, counted from what the stylesheet decided, for
     each bar from its own host: the rail's bar counts the rail, the
     dropdown's the dropdown (the watchlist rail's bar sits beside its
     host, in the same section). The status lines sit outside every live
     region. */
  function hostFor(bar, kind) {
    var h = bar.closest('[data-sv-fhost="' + kind + '"]');
    if (h) return h;
    var sec = bar.closest('.rail-section');
    h = sec && sec.querySelector('[data-sv-fhost="' + kind + '"]');
    return h || hosts(kind)[0] || null;
  }
  function tally(host) {
    var rows = host ? arr(host.querySelectorAll('[data-sv-list] > [data-sv-row]')) : [];
    var gcs = window.getComputedStyle;
    var shown = rows.filter(function (r) {
      return !gcs || gcs(r).display !== 'none';
    }).length;
    return { total: rows.length, shown: shown, hidden: rows.length - shown };
  }
  function count(kind) {
    arr(document.querySelectorAll('[data-f-kind="' + kind + '"] [data-f-status]')).forEach(function (st) {
      var bar = st.closest('[data-f-kind]');
      var n = tally(bar ? hostFor(bar, kind) : null);
      var text;
      if (peeking[kind]) text = 'showing all ' + n.total + ' ·';
      else if (n.hidden > 0) text = n.shown + ' shown · ' + n.hidden + ' hidden by your filters ·';
      else text = n.total + ' shown';
      if (unsaved) text += ' · not saved';
      var t = st.querySelector('[data-f-status-text]');
      if (t) {
        if (t.textContent !== text) t.textContent = text;
        if (unsaved) t.setAttribute('data-f-unsaved', '');
        else if (t.hasAttribute('data-f-unsaved')) t.removeAttribute('data-f-unsaved');
      }
      var peek = st.querySelector('[data-f-key="peek"]');
      if (!peek) return;
      if (peeking[kind] || n.hidden > 0) peek.removeAttribute('hidden');
      else peek.setAttribute('hidden', '');
      var label = peeking[kind] ? 'back to your filters' : 'show all';
      if (peek.textContent !== label) peek.textContent = label;
    });
  }
  function countAll() { Object.keys(state).forEach(count); }

  function apply(kind) {
    writeHosts(kind);
    paintControls(kind);
    if (kind === 'signals') writeRuleStyle();
    count(kind);
  }

  function change(kind, key, val, toggle) {
    var s = state[kind], d = DEFAULTS[kind];
    if (!s) return;
    if (key === 'peek') {
      peeking[kind] = !peeking[kind];
      apply(kind);
      return;
    }
    if (key === 'cls') {
      if (!val) s.cls = [];
      else {
        var i = s.cls.indexOf(val);
        if (i >= 0) s.cls.splice(i, 1); else s.cls.push(val);
      }
    } else if (key === 'rule') {
      if (kind !== 'signals') return;
      var j = s.rules_off.indexOf(val);
      if (j >= 0) s.rules_off.splice(j, 1); else s.rules_off.push(val);
    } else if (BOOL[key]) {
      s[key] = toggle ? !s[key] : val === '1';
    } else if (key === 'score') {
      var n = parseInt(val, 10) || 0;
      s.score = toggle && s.score === n ? 0 : n;
    } else if (key in d) {
      s[key] = toggle && s[key] === val ? d[key] : val;
    } else {
      return;
    }
    peeking[kind] = false;
    apply(kind);
    saveSoon();
  }

  /* ── saving, to the operator's profile ───────────────────────────── */
  function csrf() {
    var m = String(document.cookie || '').match(/csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }
  function pack(kind) {
    var s = state[kind], out = {};
    Object.keys(DEFAULTS[kind]).forEach(function (k) { out[k] = copy(s[k]); });
    return out;
  }
  function saveSoon() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(save, SAVE_MS);
  }
  function markUnsaved(on) {
    if (unsaved === on) return;
    unsaved = on;
    countAll();
  }
  function save() {
    saveTimer = null;
    var prefs = {};
    Object.keys(state).forEach(function (kind) { prefs[SECTION[kind]] = pack(kind); });
    fetch('/api/rail-prefs/', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify({ prefs: prefs })
    }).then(function (r) {
      if (r.status === 423) {
        if (window.svIdleLock) window.svIdleLock.engage(false);
        markUnsaved(true);
        return;
      }
      if (!r.ok) throw new Error('HTTP ' + r.status);
      markUnsaved(false);
    }).catch(function () { markUnsaved(true); });
  }

  /* ── the rules list follows the rail ─────────────────────────────── */
  function rebuildRules() {
    var list = document.getElementById('railRuleList');
    var body = document.getElementById('railSignalsBody');
    if (!list || !body || !state.signals) return;
    var meta = body.querySelector('[data-sv-rail-meta]');
    if (!meta) return;
    var m;
    try { m = JSON.parse(meta.textContent); } catch (e) { return; }
    if (!m || !m.ok || !Array.isArray(m.rules)) return;
    var rows = m.rules.slice(), seen = {};
    rows.forEach(function (r) { seen[r[0]] = true; ruleKeys[r[0]] = r[1]; });
    state.signals.rules_off.forEach(function (name) {
      if (!seen[name]) rows.push([name, ruleKeys[name] || '', 0]);
    });
    arr(list.childNodes).forEach(function (n) { list.removeChild(n); });
    if (!rows.length) {
      var none = document.createElement('span');
      none.className = 'rf-none';
      none.textContent = 'No rule on the rail.';
      list.appendChild(none);
      return;
    }
    rows.forEach(function (r) {
      var b = document.createElement('button');
      b.setAttribute('type', 'button');
      b.className = 'rf-rule';
      b.setAttribute('data-f-key', 'rule');
      b.setAttribute('data-f-val', r[0]);
      b.setAttribute('data-rule-key', r[1]);
      b.setAttribute('title', r[0]);
      b.setAttribute('aria-pressed', state.signals.rules_off.indexOf(r[0]) < 0 ? 'true' : 'false');
      var name = r[0] || '(no rule)';
      b.appendChild(document.createTextNode((name.length > 30 ? name.slice(0, 29) + '…' : name) + ' '));
      var n = document.createElement('b');
      n.textContent = String(r[2]);
      b.appendChild(n);
      list.appendChild(b);
    });
  }

  /* ── wiring ──────────────────────────────────────────────────────── */
  function init() {
    ['signals', 'watch'].forEach(function (kind) {
      if (hosts(kind).length) state[kind] = readState(kind);
    });
    learnRuleKeys();
    Object.keys(state).forEach(function (kind) { paintControls(kind); count(kind); });

    document.addEventListener('click', function (e) {
      var t = e.target;
      if (!t || !t.closest) return;
      var c = t.closest('[data-f-key]');
      if (!c) return;
      var bar = c.closest('[data-f-kind]');
      if (!bar) return;
      var kind = bar.getAttribute('data-f-kind');
      if (!state[kind]) return;
      e.preventDefault();
      change(kind, c.getAttribute('data-f-key'), c.getAttribute('data-f-val') || '',
             c.hasAttribute('data-f-toggle'));
    });

    /* The ⚙ buttons sit in the rail heads, whose own click collapses the
       section: their click stops here. */
    arr(document.querySelectorAll('[data-f-panel]')).forEach(function (g) {
      g.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var panel = document.getElementById(g.getAttribute('data-f-panel'));
        if (!panel) return;
        var open = panel.hasAttribute('hidden');
        if (open) panel.removeAttribute('hidden'); else panel.setAttribute('hidden', '');
        g.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    });

    /* A rail refresh brings new rows and new rules; a region swap new
       watchlist rows. The hosts are untouched: only the counts move. */
    document.addEventListener('htmx:afterSwap', function (e) {
      var region = e && e.detail && e.detail.svRegion;
      var body = document.getElementById('railSignalsBody');
      if (!region || region === body) rebuildRules();
      countAll();
    });
    document.addEventListener('sv:live-swapped', countAll);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
