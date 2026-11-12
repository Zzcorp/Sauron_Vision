/* sv-venue.js: ONE PRICE EVERYWHERE, the browser's one painter (2026-11-12).
 *
 * The operator, 2026-11-12: "all the prices dont seem to be the same at the
 * same time at all between the different rendering sources, bottom
 * headband, the horde (most accurate and recent it seems...)" and "between
 * charts and numbers also mostly". Eleven scripts painted price cells, each
 * from its own feed, on its own clock, with no time order: a tick ten
 * minutes old replaced one five seconds old, a tick without a time froze
 * the headband on another feed's price, and a pushed quote reached the
 * headband and the rail only.
 *
 * ONE ENGINE NOW (the approved feed design, 4.6.2, the parts needed before
 * the eToro stream exists):
 *
 *  * A MAP, symbol -> the latest value (market_data/one_quote.py's payload).
 *    A value replaces the entry only when its `at` is newer; a server value
 *    (a page render, a poll, the relay) that switches the source or the
 *    state replaces it when it was rendered after the entry's own. An entry
 *    held at eToro (auth "etoro") takes eToro's values and the server's
 *    only: an outside stream's tick never paints its cell (I10).
 *  * CELLS found by attribute, never by text: data-q="SYM", data-q-f (the
 *    field: price, bid, ask, spread, sides, chg, who, words, age, asof,
 *    slot) and data-q-side (a position's closing side). Every cell of a
 *    changed symbol is painted in ONE animation frame; a cell whose text is
 *    unchanged is not touched; at most one flash a second a cell.
 *  * NEVER A STEP BACK. Every quote block a response carries
 *    (`<script type="application/json" data-sv-quotes>`, {% q_json %}) is
 *    ingested before its cells are painted, and a MutationObserver
 *    re-indexes and repaints every cell a region swap, a poll or a popup
 *    inserts from the map, before the browser shows it. A server render
 *    older than the map never shows.
 *  * ONE CLOCK. Ages are recounted every second from `at`, corrected for
 *    the gap between the server's clock and this one (the include's
 *    data-sv-now, each push's `t`), in the server's own words: SVVenue
 *    .words is the mirror of one_quote.words, and one case table
 *    (tests/one_quote_words.json) pins the two.
 *  * CHARTS draw "now" as one price line at the same value (SVVenue.chart),
 *    and SPARKLINES end with a dot at it (SVVenue.drawSparks).
 *
 * Display only: it reads values and writes text. No request is sent.
 */
(function (root) {
  'use strict';
  if (root.SVVenue) return;

  var DASH = '—';
  var DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug',
                'Sep', 'Oct', 'Nov', 'Dec'];
  var SIDES = { bid: 1, ask: 1, mid: 1, last: 1 };
  var STALE_S = 900, DEAD_S = 3600;
  var FLASH_MS = 700, FLASH_EVERY_MS = 1000;

  var doc = root.document || null;

  // ── the grammar (mirror of market_data/one_quote.py) ────────────────────

  /* Python's round() to an integer: halves go to the even neighbour. */
  function pyRound(x) {
    var f = Math.floor(x), d = x - f;
    if (d > 0.5) return f + 1;
    if (d < 0.5) return f;
    return (f % 2 === 0) ? f : f + 1;
  }

  /* "40 s", "12 min", "3 h", "2 days" (bot_program.venue_mark.age_words). */
  function ageWords(a) {
    if (a === null || a === undefined || !isFinite(a)) return '';
    if (a < 90) return Math.floor(a) + ' s';
    if (a < 90 * 60) return pyRound(a / 60) + ' min';
    if (a < 48 * 3600) return pyRound(a / 3600) + ' h';
    return pyRound(a / 86400) + ' days';
  }

  function two(n) { return (n < 10 ? '0' : '') + n; }

  function sameUtcDay(a, b) {
    return a.getUTCFullYear() === b.getUTCFullYear() &&
      a.getUTCMonth() === b.getUTCMonth() && a.getUTCDate() === b.getUTCDate();
  }

  /* "21:58" on now's own UTC day, else "Fri 13 Nov 21:58". */
  function whenWords(atMs, nowMs) {
    var a = new Date(atMs), n = new Date(nowMs);
    var hm = two(a.getUTCHours()) + ':' + two(a.getUTCMinutes());
    if (sameUtcDay(a, n)) return hm;
    return dayWords(atMs) + ' ' + hm;
  }

  /* "Thu 12 Nov". */
  function dayWords(atMs) {
    var a = new Date(atMs);
    return DAYS[a.getUTCDay()] + ' ' + two(a.getUTCDate()) + ' ' +
      MONTHS[a.getUTCMonth()];
  }

  function nil(v) { return v === null || v === undefined; }

  function head(p, side) {
    var who = String(p.who || '');
    if (p.src === 'etoro') {
      var s = side || p.side || '';
      return SIDES[s] ? who + ' ' + s : who;
    }
    return who;
  }

  /* The words beside a price (one_quote.words): "eToro bid · 25 s",
     "OANDA stream · live", "Yahoo GBPUSD=X · 4 min", "Yahoo EURUSD=X
     previous close · Thu 12 Nov", "closed · eToro bid Fri 13 Nov 21:58 ·
     opens Sun 22:00 UTC", "awaiting eToro" / "no price". */
  function words(p, nowMs, side) {
    p = p || {};
    var state = p.state || 'none';
    if (state === 'none' || nil(p.v)) {
      return p.auth === 'etoro' ? 'awaiting eToro' : 'no price';
    }
    var h = head(p, side);
    var at = nil(p.at) ? null : +p.at;
    var prev = p.basis === 'previous_close';
    var out;
    if (state === 'shut') {
      var shut = p.shut || {};
      if (prev) {
        out = (p.who || '') + ' previous close';
        if (at !== null) out += ' ' + dayWords(at);
      } else {
        out = h;
        if (at !== null) out += ' ' + whenWords(at, nowMs);
      }
      out = 'closed · ' + out;
      if (shut.opens) out += ' · ' + shut.opens;
      return out;
    }
    if (prev) {
      out = (p.who || '') + ' previous close';
      if (at !== null) out += ' · ' + dayWords(at);
      return out;
    }
    if (at === null) return h;
    var age = Math.max(0, (nowMs - at) / 1000);
    if (!nil(p.ls) && age <= p.ls) return h + ' · live';
    return h + ' · ' + ageWords(age);
  }

  /* "Yahoo GC=F, the front-month future 2671.30 · 3 min · +0.87% vs eToro". */
  function slotWords(p, nowMs) {
    var slot = (p || {}).slot;
    if (!slot) return '';
    var parts = [((slot.who || '') + ' ' + (slot.p || DASH)).trim()];
    if (!nil(slot.at)) parts.push(ageWords(Math.max(0, (nowMs - slot.at) / 1000)));
    if (!nil(slot.gap)) parts.push(slot.gap + '% vs eToro');
    return parts.join(' · ');
  }

  /* core/price_format.price_decimals. */
  function decimals(v, cls, sym) {
    var c = String(cls || '').toLowerCase(), s = String(sym || '').toUpperCase();
    if (c === 'forex') {
      var tail = s.length >= 6 ? s.slice(-3) : s;
      return (tail === 'JPY' || tail === 'HUF' || tail === 'KRW') ? 3 : 5;
    }
    var a = Math.abs(+v);
    if (!isFinite(a)) return 2;
    if (a >= 1) return 2;
    if (a >= 0.01) return 4;
    if (a >= 0.0001) return 6;
    return 8;
  }

  function px(v, dp) {
    var n = +v;
    if (nil(v) || v === '' || !isFinite(n) || !(n > 0)) return DASH;
    var d = parseInt(dp, 10);
    return n.toFixed(isFinite(d) && d >= 0 && d <= 10 ? d : 2);
  }

  /* The text of the price at `side` (one_quote.Shown.text). */
  function valueText(p, side) {
    if (!p || nil(p.v)) return DASH;
    var s = side || '';
    if (s === 'bid' && !nil(p.b)) return p.b;
    if (s === 'ask' && !nil(p.a)) return p.a;
    if (s === 'mid' && !nil(p.b) && !nil(p.a)) {
      return p.side === 'mid' ? p.p : px((+p.b + +p.a) / 2, p.dp);
    }
    if (s === 'last' && !nil(p.l)) return p.l;
    return nil(p.p) ? DASH : p.p;
  }

  function valueNum(p, side) {
    var t = valueText(p, side);
    var n = parseFloat(t);
    return isFinite(n) ? n : null;
  }

  function chgText(p) {
    if (!p || nil(p.chg) || nil(p.v)) return DASH;
    var c = +p.chg;
    return (c >= 0 ? '+' : '') + c.toFixed(2) + '%';
  }

  function asofText(p) {
    if (!p || nil(p.at)) return DASH;
    var a = new Date(+p.at);
    return two(a.getUTCHours()) + ':' + two(a.getUTCMinutes()) + ':' +
      two(a.getUTCSeconds()) + ' UTC ·';
  }

  function fieldText(p, field, side, nowMs) {
    switch (field || 'price') {
      case 'price': return valueText(p, side);
      case 'bid': return nil(p.b) || nil(p.v) ? DASH : p.b;
      case 'ask': return nil(p.a) || nil(p.v) ? DASH : p.a;
      case 'spread':
        return (nil(p.b) || nil(p.a) || nil(p.v)) ? DASH
          : (+p.a - +p.b).toFixed(p.dp);
      case 'sides':
        return (nil(p.b) || nil(p.a) || nil(p.v)) ? DASH : p.b + ' / ' + p.a;
      case 'chg': return chgText(p);
      case 'who': return p.who || DASH;
      case 'words': return words(p, nowMs, side);
      case 'age':
        return (nil(p.at) || nil(p.v)) ? ''
          : ageWords(Math.max(0, (nowMs - p.at) / 1000));
      case 'asof': return asofText(p);
      case 'slot': return slotWords(p, nowMs);
      default: return null;
    }
  }

  // ── the map ──────────────────────────────────────────────────────────────

  var map = {};          // SYM -> payload (+ _t: the server clock it came with)
  var skew = 0;          // server ms - browser ms
  var lastT = 0;         // the newest server clock seen
  var dirty = {};
  var frame = null;
  var cells = {};        // SYM -> [Element]
  var charts = {};       // SYM -> [chart handle]
  var listeners = [];

  function nowMs() { return Date.now() + skew; }

  function clock(t) {
    t = +t;
    if (!isFinite(t) || t <= lastT) return;
    lastT = t;
    skew = t - Date.now();
  }

  function same(a, b) {
    return a.p === b.p && a.b === b.b && a.a === b.a && a.at === b.at &&
      a.state === b.state && a.src === b.src && a.auth === b.auth &&
      a.side === b.side && a.chg === b.chg && a.basis === b.basis &&
      JSON.stringify(a.slot || null) === JSON.stringify(b.slot || null);
  }

  /* Whether `v` may replace `old`. `server`: a value Sauron rendered or
     pushed (it decides a change of source or state); otherwise a stream's
     tick, which only ever moves an outside price forward. */
  function admits(old, v, server, t) {
    if (!old) return true;
    if (same(old, v)) return false;
    if (!server) {
      if (old.auth === 'etoro') return false;          // I10
      if (nil(v.at) || nil(old.at)) return false;
      return +v.at > +old.at;
    }
    var switched = v.src !== old.src || v.auth !== old.auth ||
      v.state !== old.state || v.basis !== old.basis;
    if (switched || nil(v.at) || nil(old.at)) {
      return nil(old._t) || (!nil(t) && +t >= +old._t);
    }
    if (+v.at > +old.at) return true;
    if (+v.at < +old.at) return false;
    return nil(old._t) || (!nil(t) && +t >= +old._t);
  }

  function key(sym) { return String(sym || '').toUpperCase(); }

  /* One value in. `t`: the server clock it was rendered at (a server
     value), or null (a tick). True when it replaced the entry. */
  function ingest(v, t, server) {
    if (!v || !v.s) return false;
    var k = key(v.s);
    var old = map[k];
    var srv = server !== false && !nil(t);
    if (!admits(old, v, srv, t)) return false;
    var rec = {};
    for (var f in v) if (Object.prototype.hasOwnProperty.call(v, f)) rec[f] = v[f];
    rec._t = srv ? +t : (old ? old._t : null);
    map[k] = rec;
    mark(k);
    return true;
  }

  /* A quote block: {"t": server ms, "q": {SYM: payload}}. */
  function ingestBlock(data) {
    if (!data || !data.q) return 0;
    clock(data.t);
    var n = 0;
    for (var s in data.q) {
      if (Object.prototype.hasOwnProperty.call(data.q, s) &&
          ingest(data.q[s], nil(data.t) ? 0 : data.t, true)) n++;
    }
    return n;
  }

  function readBlock(el) {
    try { return JSON.parse(el.textContent || '{}'); } catch (e) { return null; }
  }

  /* Every quote block of a document (a page, or a sweep's parsed render),
     each read once. */
  function ingestDoc(d) {
    if (!d || !d.querySelectorAll) return 0;
    var n = 0;
    var blocks = d.querySelectorAll('script[data-sv-quotes]');
    for (var i = 0; i < blocks.length; i++) {
      if (blocks[i]._svRead) continue;
      blocks[i]._svRead = true;
      n += ingestBlock(readBlock(blocks[i]));
    }
    return n;
  }

  /* The streamers' spelling (OANDA EUR_USD, Binance BTCUSDT) as the
     catalogue's (market_data/quotes.py instrument_symbol_candidates). */
  function dhSym(s) {
    return String(s || '').toUpperCase().replace(/[-\/:_]/g, '')
      .replace(/(USDT|BUSD|USDC)$/, 'USD');
  }

  /* A socket message. A value the server built (data.q: the relay, the
     Yahoo stock push) goes in as a server value; a stream's tick moves an
     outside instrument whose price that same stream wrote. True when the
     engine handled it (the legacy painter then stays out). */
  function tick(msg) {
    if (!msg) return false;
    var d = msg.data || msg;
    if (!d) return false;
    if (d.q) {
      clock(msg.t || d.t);
      ingest(d.q, nil(d.t) ? (msg.t || lastT) : d.t, true);
      return true;
    }
    if (msg.type !== 'quote_stream' && msg.type !== 'quote') return false;
    var k = dhSym(d.symbol || d.s || '');
    var old = map[k];
    if (!old) return true;                 // nothing on this page shows it
    if (old.auth === 'etoro') return true; // eToro's cell never takes it
    var src = String(d.source || (('last' in d && !('ts' in d)) ? 'finnhub_ws' : '')).toLowerCase();
    if (!src || src !== old.src) return true;  // only the stream that wrote it
    var price = +(nil(d.last) ? (nil(d.mid) ? d.price : d.mid) : d.last);
    if (!(price > 0)) return true;
    var at = nil(d.ts) ? nowMs() : (typeof d.ts === 'number' ? d.ts
      : Date.parse(d.ts));
    if (!isFinite(at) || nil(old.at) || at <= +old.at) return true;
    var v = {};
    for (var f in old) if (Object.prototype.hasOwnProperty.call(old, f)) v[f] = old[f];
    var dp = decimals(price, old.cls, old.s);
    v.p = px(price, dp); v.v = +v.p; v.l = v.p; v.dp = dp; v.at = at;
    var bid = +d.bid, ask = +d.ask;
    if (bid > 0 && ask > 0 && bid <= ask) { v.b = px(bid, dp); v.a = px(ask, dp); }
    else { v.b = null; v.a = null; }
    if (!nil(old.ls)) v.state = (nowMs() - at) / 1000 <= old.ls ? 'live' : 'delayed';
    ingest(v, null, false);
    return true;
  }

  // ── the cells ────────────────────────────────────────────────────────────

  function index() {
    cells = {};
    if (!doc) return;
    var all = doc.querySelectorAll('[data-q]');
    for (var i = 0; i < all.length; i++) {
      var k = key(all[i].getAttribute('data-q'));
      if (!k) continue;
      (cells[k] || (cells[k] = [])).push(all[i]);
    }
  }

  function setText(el, t) {
    var c = el.firstChild;
    if (c && c === el.lastChild && c.nodeType === 3) {
      if (c.nodeValue !== t) { c.nodeValue = t; return true; }
      return false;
    }
    if (el.textContent !== t) { el.textContent = t; return true; }
    return false;
  }

  function ageClass(el, p, nowAt) {
    var tiered = p && p.state === 'delayed' && p.basis !== 'previous_close' &&
      !nil(p.at);
    var age = tiered ? (nowAt - p.at) / 1000 : 0;
    el.classList.toggle('sv-age--stale', tiered && age >= STALE_S && age < DEAD_S);
    el.classList.toggle('sv-age--dead', tiered && age >= DEAD_S);
  }

  function flash(el) {
    var t = Date.now();
    if (el._svFlashAt && t - el._svFlashAt < FLASH_EVERY_MS) return;
    el._svFlashAt = t;
    el.classList.add('sv-q-moved');
    setTimeout(function () { el.classList.remove('sv-q-moved'); }, FLASH_MS);
  }

  function paintCell(el, p, nowAt) {
    var f = el.getAttribute('data-q-f') || 'price';
    var side = el.getAttribute('data-q-side') || '';
    if (!p) return;
    var t = fieldText(p, f, side, nowAt);
    if (t === null) return;
    var before = el.textContent;
    var changed = setText(el, t);
    if (el.getAttribute('data-q-state') !== p.state) el.setAttribute('data-q-state', p.state || '');
    if (f === 'price' && changed && before && before !== DASH && t !== DASH) flash(el);
    if (f === 'chg') {
      el.classList.toggle('up', !nil(p.chg) && +p.chg >= 0 && !nil(p.v));
      el.classList.toggle('down', !nil(p.chg) && +p.chg < 0 && !nil(p.v));
    }
    if (f === 'words' || f === 'age') ageClass(el, p, nowAt);
    if (f === 'slot') el.hidden = !t;
    if (el.hasAttribute('data-q-title')) {
      var title = words(p, nowAt, side);
      var sl = slotWords(p, nowAt);
      if (sl) title += '; outside quote: ' + sl;
      if (el.title !== title) el.title = title;
    }
  }

  /* The headband item's record (_partials/dh_item.html), kept equal to the
     map so no older reader of it sees another value. */
  function syncRecord(k, p) {
    if (!doc) return;
    var items = doc.querySelectorAll('.dh-item[data-symbol="' + k + '"]');
    for (var i = 0; i < items.length; i++) {
      var el = items[i];
      var put = function (name, v) {
        var s = nil(v) ? '' : String(v);
        if (el.getAttribute('data-' + name) !== s) el.setAttribute('data-' + name, s);
      };
      put('last', nil(p.v) ? '' : p.p);
      put('bid', p.b); put('ask', p.a); put('src', p.src);
      put('at', nil(p.at) ? '' : new Date(+p.at).toISOString());
      put('pct', nil(p.chg) ? '' : (+p.chg).toFixed(4));
      put('decimals', p.dp);
    }
  }

  function paintSymbol(k, nowAt) {
    var p = map[k];
    if (!p) return;
    var list = cells[k] || [];
    for (var i = 0; i < list.length; i++) paintCell(list[i], p, nowAt);
    syncRecord(k, p);
    var hs = charts[k] || [];
    for (var j = 0; j < hs.length; j++) drawChart(hs[j], p);
    sparksOf(k);
    for (var n = 0; n < listeners.length; n++) {
      try { listeners[n](k, p); } catch (e) { /* a listener never stops a paint */ }
    }
  }

  function mark(k) {
    dirty[k] = true;
    if (frame !== null) return;
    var raf = root.requestAnimationFrame;
    frame = raf ? raf(flush) : setTimeout(flush, 16);
  }

  /* Paint every changed symbol now (one frame). */
  function flush() {
    frame = null;
    var ks = Object.keys(dirty);
    dirty = {};
    var at = nowMs();
    for (var i = 0; i < ks.length; i++) paintSymbol(ks[i], at);
  }

  /* Every second: the ages and the words, from `at`. */
  function ageTick() {
    if (doc && doc.hidden) return;
    var at = nowMs();
    for (var k in cells) {
      var p = map[k];
      if (!p) continue;
      var list = cells[k];
      for (var i = 0; i < list.length; i++) {
        var f = list[i].getAttribute('data-q-f') || 'price';
        if (f === 'words' || f === 'age' || f === 'slot' ||
            list[i].hasAttribute('data-q-title')) paintCell(list[i], p, at);
      }
      var hs = charts[k] || [];
      for (var j = 0; j < hs.length; j++) nowCaption(hs[j], p, at);
    }
  }

  // ── charts ───────────────────────────────────────────────────────────────

  /* A chart's handle (templates/_partials/chart_widget.html, svCharts[id]):
     {symbol, series(), bars(), source(), caption(), setNow(v)}. The engine
     draws ONE "now" line on its main series at the price every number
     beside it prints, and says whose bars they are when another feed's. */
  function chart(h) {
    if (!h || !h.symbol) return;
    var k = key(h.symbol);
    var list = charts[k] || (charts[k] = []);
    if (list.indexOf(h) < 0) list.push(h);
    drawChart(h, map[k]);
  }

  function lineColor(p) {
    return p && p.src === 'etoro' ? '#d8b020' : '#7aaa8a';
  }

  function drawChart(h, p) {
    var series = null;
    try { series = h.series && h.series(); } catch (e) { series = null; }
    if (!series) return;
    if (h._svSeries !== series) { h._svSeries = series; h._svLine = null; }
    var v = p ? valueNum(p, '') : null;
    if (h.setNow) { try { h.setNow(v); } catch (e) { /* the line still moves */ } }
    if (v === null) {
      if (h._svLine) {
        try { series.removePriceLine(h._svLine); } catch (e) { /* gone with its series */ }
        h._svLine = null;
      }
      nowCaption(h, p, nowMs());
      return;
    }
    var title = p.state === 'shut' ? 'closed · ' + head(p, '') : head(p, '');
    var opts = { price: v, title: title, color: lineColor(p), lineWidth: 1,
                 lineStyle: 2, axisLabelVisible: true, lineVisible: true };
    if (!h._svLine) h._svLine = series.createPriceLine(opts);
    else h._svLine.applyOptions({ price: v, title: title, color: lineColor(p) });
    nowCaption(h, p, nowMs());
  }

  /* The caption under a chart: the price's words, and when the candles are
     another feed's (or another instrument's), whose and how far they sit
     from it ("bars: Yahoo EURUSD=X · price: eToro bid · bars +0.06%"). */
  function nowCaption(h, p, at) {
    var el = null;
    try { el = h.caption && h.caption(); } catch (e) { el = null; }
    if (!el) return;
    var t = '';
    if (p && !nil(p.v)) {
      var src = null, bars = null;
      try { src = h.source && h.source(); } catch (e) { src = null; }
      try { bars = h.bars && h.bars(); } catch (e) { bars = null; }
      var w = words(p, at, '');
      var other = src && src.family && (src.family !== p.fam || src.stand_in);
      if (other) {
        var lastBar = bars && bars.length ? bars[bars.length - 1] : null;
        var v = valueNum(p, '');
        var gap = '';
        if (lastBar && v && lastBar.close > 0) {
          var g = (lastBar.close / v - 1) * 100;
          if (Math.abs(g) >= 0.05 || src.stand_in) gap = ' · bars ' + (g >= 0 ? '+' : '') + g.toFixed(2) + '%';
        }
        var whose = String(src.what || src.label || src.family) +
          (src.stand_in ? ' (another instrument)' : '');
        t = 'bars: ' + whose + ' · price: ' + w + gap;
      } else {
        t = 'now: ' + w;
      }
    }
    if (el.textContent !== t) el.textContent = t;
    el.hidden = !t;
  }

  // ── sparklines ───────────────────────────────────────────────────────────

  var SVGNS = 'http://www.w3.org/2000/svg';

  /* One spark: its closes from ONE feed, the y-range stretched to the price
     shown now, and a dot at it on the right edge (hollow when the bars
     are another feed's). Its title says both. */
  function drawSpark(el) {
    var svg = el.querySelector('svg');
    if (!svg) return;
    var path = svg.querySelector('path');
    if (!path) return;
    var pts = String(el.getAttribute('data-points') || '').split(',')
      .map(parseFloat).filter(function (v) { return !isNaN(v); });
    if (pts.length < 2) return;
    var k = key(el.getAttribute('data-q'));
    var p = k ? map[k] : null;
    var v = p ? valueNum(p, '') : null;
    var lo = Math.min.apply(null, pts), hi = Math.max.apply(null, pts);
    if (v !== null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    var span = (hi - lo) || 1;
    var W = parseFloat(el.getAttribute('data-w')) || 80;
    var H = parseFloat(el.getAttribute('data-h')) || 18;
    var pad = 1.5, right = v !== null ? 4 : 0;
    var cmds = [];
    for (var i = 0; i < pts.length; i++) {
      var x = (i / (pts.length - 1)) * (W - 2 * pad - right) + pad;
      var y = H - pad - ((pts[i] - lo) / span) * (H - 2 * pad);
      cmds.push((i === 0 ? 'M' : 'L') + x.toFixed(2) + ' ' + y.toFixed(2));
    }
    path.setAttribute('d', cmds.join(' '));
    var dot = svg.querySelector('circle[data-q-dot]');
    if (v === null) { if (dot) dot.parentNode.removeChild(dot); return; }
    if (!dot && doc) {
      dot = doc.createElementNS(SVGNS, 'circle');
      dot.setAttribute('data-q-dot', '1');
      dot.setAttribute('r', '1.8');
      svg.appendChild(dot);
    }
    if (!dot) return;
    var yd = H - pad - ((v - lo) / span) * (H - 2 * pad);
    dot.setAttribute('cx', (W - pad - 1).toFixed(2));
    dot.setAttribute('cy', yd.toFixed(2));
    var barsFam = el.getAttribute('data-q-fam') || '';
    var other = barsFam && p.fam && barsFam !== p.fam;
    dot.setAttribute('class', 'sv-q-dot' + (other ? ' sv-q-dot--other' : ''));
    var bw = el.getAttribute('data-q-bars') || '';
    var title = (bw ? bw + ' · ' : '') + 'dot: ' + head(p, '') + ' now';
    if (el.getAttribute('title') !== title) el.setAttribute('title', title);
  }

  function sparksOf(k) {
    if (!doc) return;
    var els = doc.querySelectorAll('.wl-spark[data-points][data-q="' + k + '"],' +
                                   '.pop-spark[data-points][data-q="' + k + '"],' +
                                   '[data-q-spark][data-q="' + k + '"]');
    for (var i = 0; i < els.length; i++) drawSpark(els[i]);
  }

  /* Every spark on the page (the shell's renderSparks delegates here). */
  function drawSparks(scope) {
    var d = scope || doc;
    if (!d || !d.querySelectorAll) return;
    var els = d.querySelectorAll('.wl-spark[data-points], .pop-spark[data-points], [data-q-spark][data-points]');
    for (var i = 0; i < els.length; i++) drawSpark(els[i]);
  }

  // ── never a step back: what a swap inserts is painted from the map ──────

  function holds(node) {
    if (!node || node.nodeType !== 1) return false;
    if (node.hasAttribute('data-q') || node.matches && node.matches('script[data-sv-quotes]')) return true;
    return !!(node.querySelector && node.querySelector('[data-q], script[data-sv-quotes]'));
  }

  function onMutations(records) {
    var any = false;
    for (var i = 0; i < records.length && !any; i++) {
      var added = records[i].addedNodes || [];
      for (var j = 0; j < added.length; j++) {
        if (holds(added[j])) { any = true; break; }
      }
    }
    if (!any) return;
    settle();
  }

  /* Ingest every new block, re-index, and paint every cell from the map at
     once: before the browser shows a swapped region, never a frame later. */
  function settle() {
    ingestDoc(doc);
    index();
    var at = nowMs();
    for (var k in cells) paintSymbol(k, at);
    dirty = {};
  }

  function start() {
    if (!doc) return;
    var now = doc.querySelector('[data-sv-now]');
    if (now) clock(now.getAttribute('data-sv-now'));
    settle();
    drawSparks();
    if (root.MutationObserver) {
      new root.MutationObserver(onMutations).observe(doc.documentElement,
        { childList: true, subtree: true });
    }
    setInterval(ageTick, 1000);
  }

  root.SVVenue = {
    ingest: function (v, t) { return ingest(v, nil(t) ? lastT : t, true); },
    ingestBlock: ingestBlock,
    ingestDoc: ingestDoc,
    tick: tick,
    chart: chart,
    drawSparks: drawSparks,
    words: words,
    slotWords: slotWords,
    ageWords: ageWords,
    px: px,
    decimals: decimals,
    valueText: valueText,
    fieldText: fieldText,
    get: function (sym) { return map[key(sym)] || null; },
    now: nowMs,
    flush: flush,
    settle: settle,
    index: index,
    onPaint: function (fn) { if (typeof fn === 'function') listeners.push(fn); },
    _skew: function () { return skew; }
  };

  if (doc) {
    if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start);
    else start();
  }
})(typeof window !== 'undefined' ? window : this);
