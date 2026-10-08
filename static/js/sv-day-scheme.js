/* A day of Sauron — the ring scheme.
 *
 * Draws the loop the platform turns every day: seven stages around one
 * heartbeat, the markets flowing in on the left, the venues and the people
 * flowing out on the right. Hover, tap or focus a step and the panel beside
 * the ring says what really runs there and how often — every task and every
 * cadence read from the beat schedule by core.day_of_sauron and handed to
 * this script as JSON (json_script), never typed here.
 *
 * Two pages draw it: the public Wall (the schedule and the platform's own
 * counts) and the home page (the same ring, with the state of each stage
 * right now, fed through setLive()). One drawing, so the two never drift.
 *
 * Motion: the flows and the heartbeat are SMIL <animate> elements, not CSS
 * keyframes (the Wall keeps its keyframe list short on purpose). Under
 * prefers-reduced-motion the SVG's animations are paused wholesale.
 *
 *   var ctl = window.SVDay.mount({ svg: 'dayScheme', panel: 'dayPanel', data: DAY });
 *   ctl.setLive(liveState);   // home page only
 */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var CX = 600, CY = 340, R = 235, W = 150, H = 54;
  var ANGLES = [180, 232, 284, 336, 28, 80, 132];

  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) { if (Object.prototype.hasOwnProperty.call(attrs, k)) e.setAttribute(k, attrs[k]); }
    if (parent) parent.appendChild(e);
    return e;
  }
  function text(parent, x, y, cls, str, anchor) {
    var t = el('text', { x: x, y: y, 'class': cls, 'text-anchor': anchor || 'middle' }, parent);
    t.textContent = str;
    return t;
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  /* Thousands separators on the integer part only: the regex over the
   * whole string grouped the decimals too ("12.3,457", review 2026-09-29). */
  function fmt(n) {
    var parts = String(n).split('.');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return parts.join('.');
  }
  function pos(a) {
    var r = a * Math.PI / 180;
    return { x: CX + R * Math.cos(r), y: CY + R * Math.sin(r) };
  }
  function byId(x) { return typeof x === 'string' ? document.getElementById(x) : x; }

  /* The three clusters outside the ring. Generic on purpose: what the
   * platform reads, where an order can land, who reads the machine. */
  function clusters(data) {
    var adapters = data.adapters ? fmt(data.adapters) + ' broker adapters' : 'the broker adapters';
    return {
      markets: {
        title: 'MARKETS', lines: ['price streams and quotes', 'news · calendar · sentiment', 'FRED · SEC · COT'],
        job: 'What comes in: prices from the streams and the pollers, news from the feeds, the economic calendar, social sentiment, and the slow macro tape.',
        rows: [['streams', 'exchange and broker price streams, where they are enabled'], ['pollers', 'quotes by asset class, on the beat'], ['feeds', 'breaking news, news bodies, crypto news, TradingView ideas'], ['tape', 'FRED series, SEC filings, COT reports, the economic calendar']],
        next: 'Feeds SEE.'
      },
      venues: {
        title: 'VENUES', lines: [adapters, 'paper by default', 'one venue per asset class'],
        job: 'Where an order lands. The router picks one venue per asset class from the broker row flagged for it; a class with no flag goes to its default adapter when that adapter has keys, and otherwise nothing real is sent.',
        rows: [['router', 'one adapter per venue behind one interface'], ['paper', 'the default: simulated fills, real bookkeeping'], ['live', 'a keyed broker row, flagged per asset class, behind the trading PIN'], ['floor', 'the venue’s own minimum size, read before the order']],
        next: 'Answers ACT; its fills feed WATCH.'
      },
      people: {
        title: 'PEOPLE', lines: ['the operator', 'two Telegram groups', 'the dashboard · this Wall'],
        job: 'The operator arms and disarms: switches, keys, the PIN, the pools. The Eye’s group carries fills, signals and digests; the alarm group speaks only for a critical problem.',
        rows: [['status', 'in the alarm group: what runs and what is wrong, no figures'], ['stop all', 'the brake for every bot: nothing new opens, resting orders withdrawn, what is open stays in its care'], ['health page', 'every component and feed, green or explained'], ['the Wall', 'this page, counted from the platform’s own rows']],
        next: 'Their two requests go back into WATCH and the switches.'
      }
    };
  }

  function mount(opts) {
    var svg = byId(opts.svg), panel = byId(opts.panel), data = opts.data;
    if (!svg || !panel || !data || !data.stages) return null;
    var reduce = typeof opts.reduce === 'boolean' ? opts.reduce
      : !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    var stamp = opts.stamp || '';
    var ext = clusters(data);
    var live = null;

    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var defs = el('defs', {}, svg);
    var mk = el('marker', { id: 'dayAh', viewBox: '0 0 10 10', refX: '9', refY: '5', markerWidth: '7', markerHeight: '7', orient: 'auto-start-reverse' }, defs);
    el('path', { d: 'M0,0 L10,5 L0,10 z', 'class': 'day-ah' }, mk);
    var mk2 = el('marker', { id: 'dayAhs', viewBox: '0 0 10 10', refX: '9', refY: '5', markerWidth: '6', markerHeight: '6', orient: 'auto-start-reverse' }, defs);
    el('path', { d: 'M0,0 L10,5 L0,10 z', 'class': 'day-ahs' }, mk2);

    var g = el('g', {}, svg);
    el('circle', { cx: CX, cy: CY, r: R, 'class': 'day-ring' }, g);
    var i;
    for (i = 0; i < ANGLES.length; i++) {
      var sp = pos(ANGLES[i]);
      el('line', { x1: CX, y1: CY, x2: sp.x, y2: sp.y, 'class': 'day-spoke' }, g);
    }
    function flow(path, dur) {
      if (reduce) return;
      el('animate', { attributeName: 'stroke-dashoffset', from: '0', to: '-36', dur: dur || '1.4s', repeatCount: 'indefinite' }, path);
    }
    // the arcs between consecutive stages, clockwise, kept clear of the boxes
    var arcs = [];
    for (i = 0; i < ANGLES.length; i++) {
      var a1 = ANGLES[i], a2 = ANGLES[(i + 1) % ANGLES.length];
      if (a2 < a1) a2 += 360;
      var gap = 12, p1 = pos(a1 + gap), p2 = pos(a2 - gap);
      var large = (a2 - a1 - 2 * gap) > 180 ? 1 : 0;
      var arc = el('path', { d: 'M' + p1.x + ',' + p1.y + ' A' + R + ',' + R + ' 0 ' + large + ',1 ' + p2.x + ',' + p2.y, 'class': 'day-arrow', 'marker-end': 'url(#dayAh)' }, g);
      flow(arc);
      arcs.push(arc);
    }
    // the beat at the centre
    /* Every hotspot is a named button (review, 2026-09-29: eleven focusable
     * groups inside role="img" were announced as "group", no name). */
    var beat = el('g', { 'class': 'day-beat', tabindex: '0', role: 'button', 'aria-label': 'The beat: the scheduler every stage hangs on. Open its panel.', 'data-key': 'beat' }, g);
    var h2 = el('circle', { cx: CX, cy: CY, r: 62, 'class': 'day-heart2' }, beat);
    var h1 = el('circle', { cx: CX, cy: CY, r: 46, 'class': 'day-heart' }, beat);
    var core = el('circle', { cx: CX, cy: CY, r: 9, 'class': 'day-core' }, beat);
    if (!reduce) {
      el('animate', { attributeName: 'r', values: '46;52;46', dur: '2.4s', repeatCount: 'indefinite' }, h1);
      el('animate', { attributeName: 'opacity', values: '.55;1;.55', dur: '2.4s', repeatCount: 'indefinite' }, h1);
      el('animate', { attributeName: 'r', values: '62;68;62', dur: '2.4s', begin: '0.6s', repeatCount: 'indefinite' }, h2);
      el('animate', { attributeName: 'opacity', values: '.35;.8;.35', dur: '2.4s', begin: '0.6s', repeatCount: 'indefinite' }, h2);
      el('animate', { attributeName: 'r', values: '9;11;9', dur: '2.4s', repeatCount: 'indefinite' }, core);
    }
    text(beat, CX, CY + 30, 'day-ttl', 'THE BEAT');
    var beatSub = text(beat, CX, CY + 46, 'day-sub', fmt(data.total) + ' schedules');
    // the seven stages
    var nodes = {};
    for (i = 0; i < data.stages.length && i < ANGLES.length; i++) {
      var st = data.stages[i], p = pos(ANGLES[i]);
      var n = el('g', { 'class': 'day-node', tabindex: '0', role: 'button', 'aria-label': 'Step ' + st.n + ', ' + st.title + ': ' + st.job + ' Open its panel.', 'data-key': st.key, 'data-arc': String(i) }, g);
      el('rect', { x: p.x - W / 2, y: p.y - H / 2, width: W, height: H, rx: 8, 'class': 'day-box' }, n);
      text(n, p.x, p.y - 6, 'day-ttl', st.title);
      var l1 = text(n, p.x, p.y + 10, 'day-sub', fmt(st.count) + ' scheduled tasks');
      var l2 = text(n, p.x, p.y + 22, 'day-sub', st.pace || (st.fastest ? 'fastest ' + st.fastest : ''));
      var b = el('g', {}, n);
      el('circle', { cx: p.x - W / 2, cy: p.y - H / 2, r: 11, 'class': 'day-badge' }, b);
      text(b, p.x - W / 2, p.y - H / 2 + 4, 'day-badge-t', String(st.n));
      var dot = el('circle', { cx: p.x + W / 2 - 10, cy: p.y - H / 2 + 10, r: 4, 'class': 'day-dot' }, n);
      nodes[st.key] = { g: n, l1: l1, l2: l2, dot: dot };
    }
    function cluster(x, y, w, h, key) {
      var c = ext[key];
      var cg = el('g', { 'class': 'day-ext', tabindex: '0', role: 'button', 'aria-label': c.title.charAt(0) + c.title.slice(1).toLowerCase() + ': ' + c.job + ' Open its panel.', 'data-key': key }, g);
      el('rect', { x: x, y: y, width: w, height: h, rx: 10, 'class': 'day-box' }, cg);
      text(cg, x + w / 2, y + 22, 'day-ttl', c.title);
      for (var j = 0; j < c.lines.length; j++) text(cg, x + w / 2, y + 42 + j * 13, 'day-sub', c.lines[j]);
      return cg;
    }
    cluster(30, 258, 190, 96, 'markets');
    cluster(980, 150, 200, 96, 'venues');
    cluster(980, 430, 200, 96, 'people');
    text(g, 600, 20, 'day-hint', 'HOVER A STEP · TAP ON A PHONE · ESC TO CLOSE');
    // in and out
    var see = pos(180), act = pos(336), watch = pos(28), tell = pos(80), learn = pos(132), think = pos(232);
    flow(el('path', { d: 'M220,306 L' + (see.x - W / 2 - 4) + ',' + (see.y - 6), 'class': 'day-arrow', 'marker-end': 'url(#dayAh)' }, g));
    text(g, 300, 286, 'day-tiny', 'IN');
    flow(el('path', { d: 'M' + (act.x + W / 2 + 4) + ',' + (act.y - 8) + ' Q 930,190 976,196', 'class': 'day-arrow', 'marker-end': 'url(#dayAh)' }, g));
    text(g, 905, 178, 'day-tiny', 'ORDERS');
    flow(el('path', { d: 'M976,230 Q 920,300 ' + (watch.x + W / 2 + 4) + ',' + (watch.y - 6), 'class': 'day-arrow day-soft', 'marker-end': 'url(#dayAhs)' }, g), '2.6s');
    text(g, 940, 285, 'day-tiny', 'FILLS · POSITIONS');
    flow(el('path', { d: 'M' + (tell.x + W / 2 + 4) + ',' + (tell.y + 4) + ' Q 900,545 976,500', 'class': 'day-arrow', 'marker-end': 'url(#dayAh)' }, g));
    text(g, 880, 585, 'day-tiny', 'MESSAGES');
    flow(el('path', { d: 'M976,470 Q 900,430 ' + (watch.x + 40) + ',' + (watch.y + H / 2 + 6), 'class': 'day-arrow day-soft', 'marker-end': 'url(#dayAhs)' }, g), '2.6s');
    text(g, 905, 405, 'day-tiny', 'STOP ALL · SWITCHES');
    flow(el('path', { d: 'M' + (learn.x - 40) + ',' + (learn.y - H / 2 - 4) + ' Q 330,340 ' + (think.x - 30) + ',' + (think.y + H / 2 + 6), 'class': 'day-arrow day-soft', 'marker-end': 'url(#dayAhs)' }, g), '2.6s');
    text(g, 300, 440, 'day-tiny', 'THE NIGHT');
    text(g, 600, 690, 'day-tiny', 'ONE HEARTBEAT · MARKETS IN · ORDERS AND WORDS OUT · THE NIGHT FEEDS THE MORNING');
    if (reduce && svg.pauseAnimations) svg.pauseAnimations();

    // ── the panel ────────────────────────────────────────────────────
    var current = null, hot = null, litArc = null;
    function rowsHtml(rows) {
      var h = '<ul class="day-rows">';
      for (var j = 0; j < rows.length; j++) {
        var r = rows[j];
        var when = r.when !== undefined ? r.when : r[0], what = r.what !== undefined ? r.what : r[1];
        h += '<li><span class="day-t">' + esc(when) + '</span><span>' + esc(what) + '</span></li>';
      }
      return h + '</ul>';
    }
    function factsHtml(facts) {
      var h = '<ul class="day-facts">';
      for (var j = 0; j < facts.length; j++) {
        h += '<li><b>' + esc(fmt(facts[j][0])) + '</b> ' + esc(facts[j][1]) + '</li>';
      }
      return h + '</ul>';
    }
    function stageHtml(st) {
      var h = '<div class="day-k">STEP ' + st.n + ' OF ' + data.stages.length + '</div>';
      h += '<h3><span class="day-pn">' + st.n + '</span>' + esc(st.title) + '</h3>';
      h += '<p class="day-job">' + esc(st.job) + '</p>';
      var lv = live && live.stages && live.stages[st.key];
      if (lv) {
        h += '<div class="day-h day-h-live">RIGHT NOW <span class="day-state day-state-' + esc(lv.state || 'quiet') + '">' + esc(lv.words || '') + '</span></div>';
        if (lv.metrics && lv.metrics.length) h += factsHtml(lv.metrics);
        if (lv.note) h += '<p class="day-note">' + esc(lv.note) + '</p>';
      }
      h += '<div class="day-h">WHAT RUNS</div>' + rowsHtml(st.rows || []);
      if (st.facts && st.facts.length) h += '<div class="day-h">COUNTED ON THIS DEPLOYMENT</div>' + factsHtml(st.facts);
      h += '<div class="day-next">' + esc(st.next || '') + '</div>';
      return h;
    }
    function beatHtml() {
      var h = '<div class="day-k">THE LOOP</div><h3>THE BEAT</h3>';
      h += '<p class="day-job">One scheduler process sends every task on its cadence; the workers and the streams do the work. If it stops, the loop stops with it.</p>';
      var lv = live && live.beat;
      if (lv) {
        h += '<div class="day-h day-h-live">RIGHT NOW <span class="day-state day-state-' + esc(lv.state || 'quiet') + '">' + esc(lv.words || '') + '</span></div>';
        if (lv.metrics && lv.metrics.length) h += factsHtml(lv.metrics);
      }
      var rows = [['schedules', fmt(data.total) + ' entries on the beat']];
      var qs = data.queues || {}, qk = [];
      for (var q in qs) { if (Object.prototype.hasOwnProperty.call(qs, q)) qk.push(q); }
      qk.sort();
      for (var j = 0; j < qk.length; j++) rows.push([qk[j], fmt(qs[qk[j]]) + ' tasks on this queue']);
      rows.push(['fastest', data.fastest || '']);
      rows.push(['slowest', data.slowest || '']);
      h += '<div class="day-h">WHAT RUNS</div>' + rowsHtml(rows);
      /* No healthcheck watches the beat container (deploy/docker-compose.yml
       * declares none for it): the line claimed one (review, 2026-09-29). */
      h += '<div class="day-next">Feeds every stage. Nothing outside the box watches the beat.</div>';
      return h;
    }
    function extHtml(key) {
      var c = ext[key];
      var h = '<div class="day-k">OUTSIDE THE LOOP</div><h3>' + esc(c.title) + '</h3>';
      h += '<p class="day-job">' + esc(c.job) + '</p>';
      var lv = live && live.clusters && live.clusters[key];
      if (lv) {
        h += '<div class="day-h day-h-live">RIGHT NOW <span class="day-state day-state-' + esc(lv.state || 'quiet') + '">' + esc(lv.words || '') + '</span></div>';
        if (lv.metrics && lv.metrics.length) h += factsHtml(lv.metrics);
      }
      h += '<div class="day-h">WHAT IT IS</div>' + rowsHtml(c.rows);
      h += '<div class="day-next">' + esc(c.next) + '</div>';
      return h;
    }
    /* The live slice behind a key, as a string, so a poll that changed
     * nothing under the pointer re-renders nothing (review, 2026-09-29:
     * every poll replayed the panel's entrance and, through aria-live,
     * re-read the whole panel to a screen reader once a minute). */
    var lastSlice = '';
    function sliceFor(key) {
      if (!live) return '';
      var s = key === 'beat' ? live.beat
        : (live.stages && live.stages[key]) || (live.clusters && live.clusters[key]) || null;
      try { return JSON.stringify(s); } catch (e) { return ''; }
    }
    /* `silent`: a live refresh of the open panel — the text changes in
     * place, without the entrance replayed under the pointer. */
    function render(key, silent) {
      var h;
      if (key === 'beat') h = beatHtml();
      else if (ext[key]) h = extHtml(key);
      else {
        var st = null;
        for (var j = 0; j < data.stages.length; j++) if (data.stages[j].key === key) st = data.stages[j];
        if (!st) return;
        h = stageHtml(st);
      }
      if (stamp) h += '<div class="day-stamp">' + esc(stamp) + '</div>';
      if (!silent) panel.classList.add('day-pre');
      panel.innerHTML = h;
      if (!silent) { void panel.offsetWidth; panel.classList.remove('day-pre'); }
      panel.classList.toggle('day-open', key !== 'beat');
      panel.setAttribute('data-day-key', key);
      current = key;
      lastSlice = sliceFor(key);
    }
    function light(node) {
      if (hot) hot.classList.remove('day-hot');
      if (litArc) litArc.classList.remove('day-lit');
      hot = node; litArc = null;
      if (!node) return;
      node.classList.add('day-hot');
      var a = node.getAttribute('data-arc');
      if (a !== null && arcs[a]) { litArc = arcs[a]; litArc.classList.add('day-lit'); }
    }
    var spots = g.querySelectorAll('[data-key]');
    Array.prototype.forEach.call(spots, function (node) {
      var key = node.getAttribute('data-key');
      function go() { light(node); render(key); }
      node.addEventListener('mouseenter', go);
      node.addEventListener('focus', go);
      node.addEventListener('click', function (e) { e.preventDefault(); go(); });
      node.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && current && current !== 'beat') { light(null); render('beat'); } });
    render('beat');

    /* The home page's live layer: per stage a state and a line, per task
     * nothing yet. Re-renders the open panel so the numbers move under the
     * pointer, and paints each node's dot and second line. */
    var STATES = ['live', 'stale', 'off', 'quiet', 'broken'];
    function setLive(state) {
      live = state || null;
      for (var k in nodes) {
        if (!Object.prototype.hasOwnProperty.call(nodes, k)) continue;
        var nd = nodes[k], lv = live && live.stages && live.stages[k];
        /* Every state comes off before the new one goes on — a stage that
         * once read broken must not keep its red once it recovers. */
        for (var s = 0; s < STATES.length; s++) nd.g.classList.remove('day-' + STATES[s]);
        if (lv) {
          nd.g.classList.add('day-' + (STATES.indexOf(lv.state) === -1 ? 'quiet' : lv.state));
          nd.l2.textContent = lv.words || nd.l2.textContent;
        }
      }
      if (live && live.beat && live.beat.words) beatSub.textContent = live.beat.words;
      if (current && sliceFor(current) !== lastSlice) render(current, true);
    }
    return { setLive: setLive, render: render, light: light, nodes: nodes, svg: svg, panel: panel };
  }

  /* Self-mount: a page that carries the JSON (json_script id="dayData")
   * and the SVG (id="dayScheme") gets the drawing with no inline script of
   * its own. The home page mounts the same way and then feeds setLive(). */
  function auto() {
    var d = byId('dayData'), s = byId('dayScheme');
    if (!d || !s || s.getAttribute('data-mounted')) return;
    var data;
    try { data = JSON.parse(d.textContent); } catch (e) { return; }
    var ctl = mount({ svg: s, panel: s.getAttribute('data-panel') || 'dayPanel', data: data, stamp: s.getAttribute('data-stamp') || '' });
    if (!ctl) return;
    s.setAttribute('data-mounted', '1');
    window.SVDay.current = ctl;
    try { document.dispatchEvent(new CustomEvent('sv:day-mounted', { detail: ctl })); } catch (e) { /* an old browser: the drawing stands, the event does not */ }
  }
  window.SVDay = { mount: mount, clusters: clusters, current: null };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', auto);
  else auto();
})();
