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
 *    A value of the same source replaces the entry only when its `at` is
 *    newer (the same `at`: when it was rendered later, which is how a
 *    close flips the state); a server value (a page render, a poll, the
 *    relay) that switches the source, the authority or the basis replaces
 *    it when it was rendered after the entry's own. An entry held at eToro
 *    (auth "etoro") takes eToro's values and the server's only: an outside
 *    stream's tick never paints its cell (I10).
 *  * CELLS found by attribute, never by text: data-q="SYM", data-q-f (the
 *    field: price, bid, ask, spread, sides, chg, who, words, age, asof,
 *    slot, and the figures beside a price: since, away, rr) and data-q-side
 *    (a position's closing side). Every cell of a changed symbol is
 *    painted in ONE animation frame; a cell whose text is unchanged is not
 *    touched; at most one flash a second a cell. A cell with data-q-title
 *    has its hover painted too, its own tail kept.
 *  * NEVER A STEP BACK. Every quote block a response carries
 *    (`<script type="application/json" data-sv-quotes>`, {% q_json %}) is
 *    ingested before its cells are painted, and a MutationObserver paints
 *    the cells a region swap, a poll or a popup inserts from the map,
 *    before the browser shows them. A server render older than the map
 *    never shows.
 *  * ONE CLOCK. Ages are recounted every second from `at`, corrected for
 *    the gap between the server's clock and this one (the include's
 *    data-sv-now, each push's `t`), in the server's own words: SVVenue
 *    .words and .fieldText are the mirrors of one_quote.words and
 *    .field_words, and one case table (tests/one_quote_words.json) pins
 *    the two. A shut market reopens on every tab at its reopening, by the
 *    clock (shut.reopens).
 *  * CHARTS draw "now" as one price line at the same value (SVVenue.chart),
 *    hand that value to the chart's own weld (its guards decide whether
 *    the forming candle takes it: same feed and side only, never a fake
 *    candle), and SPARKLINES end with a dot at it, saying whose bars they
 *    draw (SVVenue.drawSpark). A spark is keyed by data-q-spark, never
 *    data-q: it is drawn, not written into.
 *
 * THE REVIEW (2026-11-12, measured in Chromium): a region sweep carried no
 * quote block, so the painter put the page-load price back over the
 * server's newer one; a live/delayed difference counted as a server
 * switch, so a late poll replaced a newer tick; the forming candle trailed
 * the "now" line until the next poll; the figures beside a price and the
 * hovers stayed at the render's price; a shut market said "closed" only
 * where a words cell exists; the quote socket going down said nothing and
 * its return asked for nothing; one settle repainted every cell and spark
 * of the page (4,100 attribute writes at 200 symbols), in a hidden tab
 * too. All of it is fixed here and pinned by tests/test_one_quote_review*.
 *
 * Display only: it reads values and writes text. It sends no request of
 * its own; a returning socket asks the page's own region sweep to run.
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
  /* Who read a stamp (one_quote.VIA_WORDS). */
  var VIA_WORDS = {
    'fill': 'at the fill', 'tick': 'read by the manage tick',
    'candle': "from eToro's latest candle",
    'close dialog': 'read by the close dialog',
    'poll': 'read by the 30-second eToro quote read'
  };

  var doc = root.document || null;
  var own = Object.prototype.hasOwnProperty;

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

  /* "19:13:31 UTC ·". */
  function clockFace(atMs) {
    var a = new Date(+atMs);
    return two(a.getUTCHours()) + ':' + two(a.getUTCMinutes()) + ':' +
      two(a.getUTCSeconds()) + ' UTC ·';
  }

  function nil(v) { return v === null || v === undefined; }

  /* A figure to two places, rounded half up from its shortest spelling
     (one_quote.fmt2, Django's floatformat:2): the same digits both sides.
     "-0.00" is "0.00". */
  function fmt2(x) {
    if (nil(x) || !isFinite(x)) return null;
    var a = Math.abs(x), out;
    if (a < 1e-6) out = '0.00';
    else if (a >= 1e15) out = a.toFixed(2);
    else {
      var s = String(a), dot = s.indexOf('.');
      var ip = dot < 0 ? s : s.slice(0, dot);
      var fp = dot < 0 ? '' : s.slice(dot + 1);
      var n = parseInt(ip + (fp + '00').slice(0, 2), 10);
      if (fp.length > 2 && fp.charAt(2) >= '5') n += 1;
      var t = String(n);
      while (t.length < 3) t = '0' + t;
      out = t.slice(0, -2) + '.' + t.slice(-2);
    }
    return (x < 0 && out !== '0.00') ? '-' + out : out;
  }

  /* A number from a cell's attribute (one_quote._num): null when absent
     or not a number. */
  function num(t) {
    if (nil(t) || t === '') return null;
    var n = Number(t);
    return isFinite(n) ? n : null;
  }

  /* An attribute of a cell, or of a plain object of attributes. */
  function attr(a, name) {
    if (!a) return null;
    if (typeof a.getAttribute === 'function') return a.getAttribute(name);
    return own.call(a, name) ? a[name] : null;
  }

  function head(p, side) {
    var who = String(p.who || '');
    if (p.src === 'etoro') {
      var s = side || p.side || '';
      /* a reading without sides prints its print */
      if ((s === 'bid' || s === 'ask' || s === 'mid') && (nil(p.b) || nil(p.a))) s = 'last';
      return SIDES[s] ? who + ' ' + s : who;
    }
    return who;
  }

  /* The payload's state at `nowMs` (one_quote.effective_state): a shut
     market whose reopening has come is an open market's last price, live
     while within an outside stream's bound, else delayed. In the browser
     live and delayed are recounted from `ls` too, as the words are. */
  function stateAt(p, nowMs) {
    var st = (p && p.state) || 'none';
    if (st === 'shut') {
      var re = p.shut && p.shut.reopens;
      if (nil(re) || nil(nowMs) || nowMs < +re) return st;
    } else if (st !== 'live' && st !== 'delayed') {
      return st;
    }
    if (!nil(p.ls) && !nil(p.at) && !nil(nowMs) && (nowMs - p.at) / 1000 <= p.ls) return 'live';
    return 'delayed';
  }

  /* When a shut market's price is from (one_quote.shut_at): its reading,
     or the start of the shut when it was read after the close. */
  function shutAt(p) {
    var at = nil(p.at) ? null : +p.at;
    var since = (p.shut && !nil(p.shut.since)) ? +p.shut.since : null;
    if (at !== null && since !== null && at > since) return since;
    return at;
  }

  /* The words beside a price (one_quote.words): "eToro bid · 25 s",
     "OANDA stream · live", "Yahoo GBPUSD=X · 4 min", "Yahoo EURUSD=X
     previous close · Thu 12 Nov", "closed · eToro bid Fri 13 Nov 21:58 ·
     opens Sun 22:00 UTC", "awaiting eToro" / "no price". */
  function words(p, nowMs, side) {
    p = p || {};
    var state = stateAt(p, nowMs);
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
        var t = shutAt(p);
        if (t !== null) out += ' ' + whenWords(t, nowMs);
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

  /* "Yahoo GC=F, the front-month future 2671.30 · 3 min · +0.87% vs eToro";
     Yahoo's previous close says so, with its day and no gap. */
  function slotWords(p, nowMs) {
    var slot = (p || {}).slot;
    if (!slot) return '';
    if (slot.prev) {
      var out = ((slot.who || '') + ' previous close ' + (slot.p || DASH)).trim();
      if (!nil(slot.at)) out += ' · ' + dayWords(+slot.at);
      return out;
    }
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

  /* The hover (one_quote.field_words "title"): the words, who read it, a
     carried spread, a previous close, the outside quote, and the cell's
     own tail (data-q-title: the valuation price when it differs). */
  function titleText(p, nowMs, side, tail) {
    var parts = [words(p, nowMs, side)];
    var via = own.call(VIA_WORDS, p.via || '') ? VIA_WORDS[p.via] : '';
    if (via && !nil(p.v)) parts.push(via);
    var s = side || p.side || '';
    if (!nil(p.sf) && (s === 'bid' || s === 'ask' || s === 'mid')) {
      parts.push('its bid and ask from the spread measured ' + whenWords(+p.sf, nowMs));
    }
    if (p.basis === 'previous_close') {
      parts.push("Yahoo's previous close, standing in for a market price");
    }
    var sl = slotWords(p, nowMs);
    if (sl) parts.push('outside quote: ' + sl);
    if (tail) parts.push(String(tail));
    return parts.filter(function (x) { return !!x; }).join('; ');
  }

  /* One cell's text by its field (one_quote.Shown.field_text and
     .field_words); `attrs`: the cell (or an object of its attributes), for
     the figures worked out against a level and a hover's tail. */
  function fieldText(p, field, side, nowMs, attrs) {
    p = p || {};
    var f = field || 'price';
    var st = stateAt(p, nowMs);
    var priced = !nil(p.v) && st !== 'none';
    switch (f) {
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
      case 'slot': return slotWords(p, nowMs);
      case 'age':
        if (!priced) return '';
        if (p.basis === 'previous_close') {
          return 'previous close' + (nil(p.at) ? '' : ' · ' + dayWords(+p.at));
        }
        if (st === 'shut') {
          var opens = (p.shut && p.shut.opens) || '';
          return 'closed' + (opens ? ' · ' + opens : '');
        }
        if (nil(p.at)) return '';
        return ageWords(Math.max(0, (nowMs - p.at) / 1000));
      case 'asof':
        if (nil(p.at)) return DASH;
        if (p.basis === 'previous_close') return '';
        return clockFace(st === 'shut' ? shutAt(p) : +p.at);
      case 'since':
      case 'away': {
        var v = priced ? num(valueText(p, side)) : null;
        var ref = num(attr(attrs, 'data-q-ref'));
        if (v === null || ref === null || ref <= 0 || v <= 0) return '';
        if (f === 'since') {
          var pct = (v - ref) / ref * 100;
          return (pct > 0 ? '+' : '') + fmt2(pct) + '% since entry';
        }
        var below = String(attr(attrs, 'data-q-below') || '');
        below = below === '1' || below === 'true';
        var through = below ? (v <= ref) : (v >= ref);
        var d = fmt2(Math.abs(ref - v) / Math.abs(v) * 100);
        return through ? 'THROUGH by ' + d + '%' : d + '% away';
      }
      case 'rr': {
        var order = String(attr(attrs, 'data-q-o') || '').toUpperCase();
        var stop = num(attr(attrs, 'data-q-stop'));
        var target = num(attr(attrs, 'data-q-target'));
        var bound = num(attr(attrs, 'data-q-max'));
        var m = priced ? num(valueText(p, '')) : null;
        if (m === null || nil(p.at) || (order !== 'BUY' && order !== 'SELL') ||
            stop === null || target === null) return DASH;
        if (bound !== null && (nowMs - p.at) / 1000 > bound) return DASH;
        var risk = Math.abs(m - stop);
        if (!(m > 0 && risk > 0)) return DASH;
        var reward = Math.max(order === 'BUY' ? target - m : m - target, 0);
        return fmt2(reward / risk);
      }
      case 'title': return titleText(p, nowMs, side, attr(attrs, 'data-q-title'));
      default: return null;
    }
  }

  // ── the map ──────────────────────────────────────────────────────────────

  var map = {};          // SYM -> payload (+ _t: the server clock it came with)
  var skew = 0;          // server ms - browser ms
  var lastT = 0;         // the newest server clock seen
  var dirty = {};
  var frame = null;
  var cells = {};        // SYM -> [Element] (data-q)
  var items = {};        // SYM -> [Element] (.dh-item records)
  var sparks = {};       // SYM -> [Element] (data-q-spark)
  var charts = {};       // SYM -> [chart handle]
  var shownState = {};   // SYM -> the state its cells were last painted in
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
      JSON.stringify(a.slot || null) === JSON.stringify(b.slot || null) &&
      JSON.stringify(a.shut || null) === JSON.stringify(b.shut || null);
  }

  /* Whether `v` may replace `old`. `server`: a value Sauron rendered or
     pushed; otherwise a stream's tick, which only ever moves an outside
     price forward.

     THE SERVER DECIDES A SWITCH, by when it rendered: another source,
     another authority (a position opened or closed), another basis (the
     reading is a previous close now). A live, delayed or shut difference
     is no switch (the review, 2026-11-12: a poll that read the database
     before a stream's write replaced the stream's newer "live" 151.260
     with the older "46 s" 151.234): within one source the newer reading
     wins, and the same reading rendered later (a close) replaces it. */
  function admits(old, v, server, t) {
    if (!old) return true;
    if (same(old, v)) return false;
    if (!server) {
      if (old.auth === 'etoro') return false;          // I10
      if (nil(v.at) || nil(old.at)) return false;
      return +v.at > +old.at;
    }
    var later = nil(old._t) || (!nil(t) && +t >= +old._t);
    var switched = v.src !== old.src || v.auth !== old.auth ||
      v.basis !== old.basis;
    if (switched || nil(v.at) || nil(old.at)) return later;
    if (+v.at > +old.at) return true;
    if (+v.at < +old.at) return false;
    return later;
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
    for (var f in v) if (own.call(v, f)) rec[f] = v[f];
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
      if (own.call(data.q, s) && ingest(data.q[s], nil(data.t) ? 0 : data.t, true)) n++;
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
     outside instrument whose price that same stream wrote, and its own
     day change with it. True when the engine handled it (the legacy
     painter then stays out). */
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
    for (var f in old) if (own.call(old, f)) v[f] = old[f];
    var dp = decimals(price, old.cls, old.s);
    v.p = px(price, dp); v.v = +v.p; v.l = v.p; v.dp = dp; v.at = at;
    var bid = +d.bid, ask = +d.ask;
    if (bid > 0 && ask > 0 && bid <= ask) { v.b = px(bid, dp); v.a = px(ask, dp); }
    else { v.b = null; v.a = null; }
    /* The stream's own day change moves with its own price (Binance's
       24 h); no time-derived state is stored: live and delayed are
       counted from `ls` at every paint (stateAt). */
    if (!nil(d.change_pct) && d.change_pct !== '' && isFinite(+d.change_pct)) v.chg = +d.change_pct;
    ingest(v, null, false);
    return true;
  }

  // ── the cells ────────────────────────────────────────────────────────────

  function push(into, k, el) { (into[k] || (into[k] = [])).push(el); }

  /* The symbol -> elements index: the price cells, the headband records
     and the sparks, each found once (not one document query per paint). */
  function index() {
    cells = {}; items = {}; sparks = {};
    if (!doc) return;
    var all = doc.querySelectorAll('[data-q]');
    for (var i = 0; i < all.length; i++) {
      /* a sparkline is drawn, never written into (its svg would go) */
      if (all[i].hasAttribute('data-points')) continue;
      var k = key(all[i].getAttribute('data-q'));
      if (k) push(cells, k, all[i]);
    }
    var rec = doc.querySelectorAll('.dh-item[data-symbol]');
    for (i = 0; i < rec.length; i++) push(items, key(rec[i].getAttribute('data-symbol')), rec[i]);
    var sp = doc.querySelectorAll('[data-q-spark][data-points]');
    for (i = 0; i < sp.length; i++) {
      var s = key(sp[i].getAttribute('data-q-spark'));
      if (s) push(sparks, s, sp[i]);
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

  function setAttr(el, name, v) {
    if (el.getAttribute(name) !== v) el.setAttribute(name, v);
  }

  function ageClass(el, p, nowAt) {
    var tiered = p && stateAt(p, nowAt) === 'delayed' &&
      p.basis !== 'previous_close' && !nil(p.at);
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
    if (!p) return;
    var f = el.getAttribute('data-q-f') || 'price';
    var side = el.getAttribute('data-q-side') || '';
    var t = fieldText(p, f, side, nowAt, el);
    if (t === null) return;
    var before = el.textContent;
    var changed = setText(el, t);
    setAttr(el, 'data-q-state', stateAt(p, nowAt));
    if (f === 'price' && changed && before && before !== DASH && t !== DASH) flash(el);
    if (f === 'chg') {
      el.classList.toggle('up', !nil(p.chg) && +p.chg >= 0 && !nil(p.v));
      el.classList.toggle('down', !nil(p.chg) && +p.chg < 0 && !nil(p.v));
    }
    if (f === 'words' || f === 'age') ageClass(el, p, nowAt);
    /* The move since entry keeps its colour with its sign (the server's
       sign-up/sign-down, positions_list): a price that crossed the entry
       read "-0.02% since entry" in the gain colour. */
    if (f === 'since' && t && /(^|\s)sign-(up|down|flat)(\s|$)/.test(el.className)) {
      var neg = t.charAt(0) === '-';
      el.classList.toggle('sign-up', !neg);
      el.classList.toggle('sign-down', neg);
      el.classList.remove('sign-flat');
    }
    if (f === 'slot' && el.hidden !== !t) el.hidden = !t;
    if (el.hasAttribute('data-q-title')) {
      var title = titleText(p, nowAt, side, el.getAttribute('data-q-title'));
      if (el.title !== title) el.title = title;
    }
  }

  /* The headband item's record (_partials/dh_item.html), kept equal to the
     map so no older reader of it sees another value. */
  function syncRecord(el, p) {
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

  function paintSymbol(k, nowAt) {
    var p = map[k];
    if (!p) return;
    shownState[k] = stateAt(p, nowAt);
    var list = cells[k] || [];
    for (var i = 0; i < list.length; i++) paintCell(list[i], p, nowAt);
    var recs = items[k] || [];
    for (i = 0; i < recs.length; i++) syncRecord(recs[i], p);
    var hs = charts[k] || [];
    for (var j = 0; j < hs.length; j++) drawChart(hs[j], p, false);
    var sp = sparks[k] || [];
    for (i = 0; i < sp.length; i++) drawSpark(sp[i]);
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

  /* Every second: the ages, the words, the hovers and the figures bound
     to an age, from `at`; and every cell of a symbol whose state turned
     (a shut market at its reopening). */
  function ageTick() {
    if (doc && doc.hidden) return;
    var at = nowMs();
    var seen = {};
    for (var k in cells) {
      seen[k] = true;
      var p = map[k];
      if (!p) continue;
      if (shownState[k] !== stateAt(p, at)) { paintSymbol(k, at); continue; }
      var list = cells[k];
      for (var i = 0; i < list.length; i++) {
        var el = list[i];
        var f = el.getAttribute('data-q-f') || 'price';
        if (f === 'words' || f === 'age' || f === 'slot' || f === 'rr' ||
            el.hasAttribute('data-q-title')) paintCell(el, p, at);
      }
      var hs = charts[k] || [];
      for (var j = 0; j < hs.length; j++) nowCaption(hs[j], p, at);
    }
    for (var c in charts) {
      if (seen[c] || !map[c]) continue;
      if (shownState[c] !== stateAt(map[c], at)) { paintSymbol(c, at); continue; }
      for (var n = 0; n < charts[c].length; n++) nowCaption(charts[c][n], map[c], at);
    }
  }

  // ── charts ───────────────────────────────────────────────────────────────

  /* A chart's handle (templates/_partials/chart_widget.html, svCharts[id]):
     {symbol, series(), bars(), source(), caption(), setNow(v), tick(v, q)}.
     The engine draws ONE "now" line on its main series at the price every
     number beside it prints, says whose bars they are when another feed's,
     and hands the price to the chart's own weld. */
  function chart(h) {
    if (!h || !h.symbol) return;
    var k = key(h.symbol);
    var list = charts[k] || (charts[k] = []);
    if (list.indexOf(h) < 0) list.push(h);
    drawChart(h, map[k], true);
  }

  function lineColor(p) {
    return p && p.src === 'etoro' ? '#d8b020' : '#7aaa8a';
  }

  /* The forming candle takes the price the numbers print, when the chart
     says it may (chart_widget tickRefusal: the candles' own feed and side,
     a forming bar, a fresh reading inside it, within the class's jump
     bar): the review, 2026-11-12, measured the candle up to 15 s behind
     the "now" line, and a refresh put it back to the served bar until the
     next poll. Another feed's price is refused there, never drawn. */
  function weld(h, p, v, at) {
    if (typeof h.tick !== 'function' || v === null) return;
    try {
      h.tick(v, { source_family: p.fam || '', side: p.side || 'last',
                  source: p.src || '', source_words: p.who || '',
                  quote_age_seconds: nil(p.at) ? null : Math.max(0, (at - p.at) / 1000) });
    } catch (e) { /* the line still shows the price */ }
  }

  function drawChart(h, p, force) {
    var series = null;
    try { series = h.series && h.series(); } catch (e) { series = null; }
    if (!series) return;
    if (h._svSeries !== series) { h._svSeries = series; h._svLine = null; h._svSig = null; }
    var at = nowMs();
    var v = p ? valueNum(p, '') : null;
    if (h.setNow && (force || h._svNowV !== v)) {
      h._svNowV = v;
      try { h.setNow(v); } catch (e) { /* the line still moves */ }
    }
    if (v === null) {
      if (h._svLine) {
        try { series.removePriceLine(h._svLine); } catch (e) { /* gone with its series */ }
        h._svLine = null;
      }
      h._svSig = null;
      nowCaption(h, p, at);
      return;
    }
    var title = stateAt(p, at) === 'shut' ? 'closed · ' + head(p, '') : head(p, '');
    var color = lineColor(p);
    var sig = v + '|' + title + '|' + color;
    if (h._svLine && h._svSig === sig) {
      /* unchanged: no write */
    } else if (h._svLine && typeof h._svLine.applyOptions === 'function') {
      h._svLine.applyOptions({ price: v, title: title, color: color });
    } else {
      if (h._svLine) {
        try { series.removePriceLine(h._svLine); } catch (e) { /* gone with its series */ }
      }
      h._svLine = series.createPriceLine({ price: v, title: title, color: color,
                                           lineWidth: 1, lineStyle: 2,
                                           axisLabelVisible: true, lineVisible: true });
    }
    h._svSig = sig;
    weld(h, p, v, at);
    nowCaption(h, p, at);
  }

  /* The caption under a chart: the price's words, and when the candles are
     another feed's (or a stand-in beside an eToro price), whose and how far
     they sit from it ("bars: Yahoo EURUSD=X · price: eToro bid · bars
     +0.06%"). A stand-in's price on its own bars is one feed and one
     instrument: "now: ...". */
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
      var other = !!(src && src.family &&
                     (src.family !== p.fam || (src.stand_in && p.auth === 'etoro')));
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
    if (el.hidden !== !t) el.hidden = !t;
  }

  // ── sparklines ───────────────────────────────────────────────────────────

  var SVGNS = 'http://www.w3.org/2000/svg';

  /* One spark: its closes from ONE feed, the y-range stretched to the price
     shown now, and a dot at it on the right edge (hollow when the bars
     are another feed's). Its title says whose bars it draws
     (data-q-bars) and whose the dot is. Drawn only when something it
     draws from changed: a settle writes nothing to an unchanged spark. */
  function drawSpark(el) {
    if (!el || !el.querySelector) return;
    var svg = el.querySelector('svg');
    if (!svg) return;
    var path = svg.querySelector('path');
    if (!path) return;
    var raw = String(el.getAttribute('data-points') || '');
    var k = key(el.getAttribute('data-q-spark'));
    var p = k ? map[k] : null;
    var v = p ? valueNum(p, '') : null;
    var W = parseFloat(el.getAttribute('data-w')) || 80;
    var H = parseFloat(el.getAttribute('data-h')) || 18;
    var barsFam = el.getAttribute('data-q-fam') || '';
    var bw = el.getAttribute('data-q-bars') || '';
    var sig = [raw, v, W, H, barsFam, bw, p ? p.chg : '', p ? p.fam : '',
               p ? head(p, '') : ''].join('|');
    if (el._svSparkSig === sig && path.getAttribute('d')) return;
    var pts = raw.split(',').map(parseFloat).filter(function (x) { return !isNaN(x); });
    if (pts.length < 2) return;
    el._svSparkSig = sig;
    var lo = Math.min.apply(null, pts), hi = Math.max.apply(null, pts);
    if (v !== null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    var span = (hi - lo) || 1;
    var pad = 1.5, right = v !== null ? 4 : 0;
    var cmds = [];
    for (var i = 0; i < pts.length; i++) {
      var x = (i / (pts.length - 1)) * (W - 2 * pad - right) + pad;
      var y = H - pad - ((pts[i] - lo) / span) * (H - 2 * pad);
      cmds.push((i === 0 ? 'M' : 'L') + x.toFixed(2) + ' ' + y.toFixed(2));
    }
    setAttr(path, 'd', cmds.join(' '));
    var dot = svg.querySelector('circle[data-q-dot]');
    if (v === null) {
      if (dot) dot.parentNode.removeChild(dot);
      if (bw) setAttr(el, 'title', bw);
      return;
    }
    if (!dot && doc) {
      dot = doc.createElementNS(SVGNS, 'circle');
      dot.setAttribute('data-q-dot', '1');
      dot.setAttribute('r', '1.8');
      svg.appendChild(dot);
    }
    if (!dot) return;
    var yd = H - pad - ((v - lo) / span) * (H - 2 * pad);
    setAttr(dot, 'cx', (W - pad - 1).toFixed(2));
    setAttr(dot, 'cy', yd.toFixed(2));
    /* its colour is the shown price's own day change; none: neutral */
    setAttr(el, 'data-up', nil(p.chg) ? '' : (+p.chg >= 0 ? '1' : '0'));
    var other = barsFam && p.fam && barsFam !== p.fam;
    setAttr(dot, 'class', 'sv-q-dot' + (other ? ' sv-q-dot--other' : ''));
    setAttr(el, 'title', (bw ? bw + ' · ' : '') + 'dot: ' + head(p, '') + ' now');
  }

  /* Every spark in `scope` (the page by default; the shell's renderSparks
     delegates here). */
  function drawSparks(scope) {
    var d = scope || doc;
    if (!d || !d.querySelectorAll) return;
    var els = d.querySelectorAll('.wl-spark[data-points], .pop-spark[data-points], [data-q-spark][data-points]');
    for (var i = 0; i < els.length; i++) drawSpark(els[i]);
  }

  // ── never a step back: what a swap inserts is painted from the map ──────

  function holds(node) {
    if (!node || node.nodeType !== 1) return false;
    if (node.hasAttribute('data-q') || node.hasAttribute('data-q-spark') ||
        (node.matches && node.matches('script[data-sv-quotes]'))) return true;
    return !!(node.querySelector &&
              node.querySelector('[data-q], [data-q-spark], script[data-sv-quotes]'));
  }

  /* fn on `node` itself when it matches `sel`, and on its matches inside. */
  function eachIn(node, sel, fn) {
    if (node.matches && node.matches(sel)) fn(node);
    var list = node.querySelectorAll ? node.querySelectorAll(sel) : [];
    for (var i = 0; i < list.length; i++) fn(list[i]);
  }

  var pendingSettle = false;

  function onMutations(records) {
    var added = [];
    for (var i = 0; i < records.length; i++) {
      var nodes = records[i].addedNodes || [];
      for (var j = 0; j < nodes.length; j++) {
        if (holds(nodes[j])) added.push(nodes[j]);
      }
    }
    if (!added.length) return;
    /* A hidden tab settles when it comes back (the review: settles ran in
       background tabs, for no one). */
    if (doc && doc.hidden) { pendingSettle = true; return; }
    settle(added);
  }

  /* Ingest every new block, re-index, and paint from the map at once,
     before the browser shows a swapped region, never a frame later: the
     symbols whose value changed (every cell of each), and the cells,
     records and sparks the inserted subtrees carry. Nothing else is
     written (the review: one settle repainted every cell and spark of the
     page). With no `scope`, every cell of the page. */
  function settle(scope) {
    ingestDoc(doc);
    index();
    var at = nowMs();
    if (!scope) {
      dirty = {};
      for (var k in cells) paintSymbol(k, at);
      for (var c in charts) if (!cells[c] && map[c]) paintSymbol(c, at);
      drawSparks();
      return;
    }
    var ks = Object.keys(dirty);
    dirty = {};
    var done = {};
    for (var i = 0; i < ks.length; i++) { paintSymbol(ks[i], at); done[ks[i]] = true; }
    for (var n = 0; n < scope.length; n++) {
      var node = scope[n];
      if (!node || node.nodeType !== 1) continue;
      eachIn(node, '[data-q]', function (el) {
        if (el.hasAttribute('data-points')) return;
        var s = key(el.getAttribute('data-q'));
        if (!done[s]) paintCell(el, map[s], at);
      });
      eachIn(node, '.dh-item[data-symbol]', function (el) {
        var s = key(el.getAttribute('data-symbol'));
        if (map[s] && !done[s]) syncRecord(el, map[s]);
      });
      eachIn(node, '.wl-spark[data-points], .pop-spark[data-points], [data-q-spark][data-points]', drawSpark);
    }
  }

  /* The live region's comparison (templates/_partials/live_region.html
     canon): the engine's own paint taken off a copy, so a sweep whose
     server markup equals the region's is no change, and no swap (the
     review: every sweep swapped the table for the painter's attributes).
     A cell's text goes too: the sweep's quote block carries its value,
     which the engine paints without a swap. */
  function canon(node) {
    if (!node || !node.querySelectorAll) return node;
    var list = node.querySelectorAll('[data-q], [data-q-spark]');
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      el.removeAttribute('data-q-state');
      el.classList.remove('sv-q-moved', 'sv-age--stale', 'sv-age--dead');
      if (el.getAttribute('data-q-f') === 'chg') el.classList.remove('up', 'down');
      if (el.getAttribute('data-q-f') === 'since') el.classList.remove('sign-up', 'sign-down', 'sign-flat');
      if (el.getAttribute('class') === '') el.removeAttribute('class');
      if (el.hasAttribute('data-q-title')) el.removeAttribute('title');
      if (el.getAttribute('data-q-f') === 'slot') el.removeAttribute('hidden');
      if (el.hasAttribute('data-q-spark') || el.hasAttribute('data-points')) {
        el.removeAttribute('title');
        el.removeAttribute('data-up');
        var dots = el.querySelectorAll('circle[data-q-dot]');
        for (var j = 0; j < dots.length; j++) dots[j].parentNode.removeChild(dots[j]);
        var paths = el.querySelectorAll('path');
        for (j = 0; j < paths.length; j++) paths[j].removeAttribute('d');
      } else if (el.hasAttribute('data-q')) {
        el.textContent = '';
      }
    }
    return node;
  }

  /* The dashboard socket (base.html): down, every chip says "live prices
     paused" (sv-venue.css, the feed design 4.6.2); back after a fall, the
     page's regions are asked again at once (their sweep carries its quote
     block), the rest is repaired by the relay's full batch within a
     minute. The first open asks nothing: the page's own render is the
     newest it can be. A socket whose first open came before this script
     ran (base.html connects while the page is still parsing; this script
     is deferred) is first heard of by its fall, and its return asks too. */
  var socketUp = null;
  function socket(up) {
    up = !!up;
    var back = up && socketUp === false;
    socketUp = up;
    if (doc && doc.body) doc.body.classList.toggle('sv-quotes-paused', !up);
    if (back && typeof root.svLiveRefresh === 'function') {
      try { root.svLiveRefresh(); } catch (e) { /* the timed sweep still runs */ }
    }
  }

  function start() {
    if (!doc) return;
    var now = doc.querySelector('[data-sv-now]');
    if (now) clock(now.getAttribute('data-sv-now'));
    settle();
    if (root.MutationObserver) {
      new root.MutationObserver(onMutations).observe(doc.documentElement,
        { childList: true, subtree: true });
    }
    doc.addEventListener('visibilitychange', function () {
      if (doc.hidden || !pendingSettle) return;
      pendingSettle = false;
      settle();
    });
    setInterval(ageTick, 1000);
  }

  root.SVVenue = {
    ingest: function (v, t) { return ingest(v, nil(t) ? lastT : t, true); },
    ingestBlock: ingestBlock,
    ingestDoc: ingestDoc,
    tick: tick,
    chart: chart,
    drawSpark: drawSpark,
    drawSparks: drawSparks,
    words: words,
    slotWords: slotWords,
    ageWords: ageWords,
    fmt2: fmt2,
    px: px,
    decimals: decimals,
    valueText: valueText,
    fieldText: fieldText,
    stateAt: stateAt,
    canon: canon,
    socket: socket,
    get: function (sym) { return map[key(sym)] || null; },
    now: nowMs,
    flush: flush,
    settle: function () { settle(); },
    index: index,
    onPaint: function (fn) { if (typeof fn === 'function') listeners.push(fn); },
    _skew: function () { return skew; }
  };

  if (doc) {
    if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start);
    else start();
  }
})(typeof window !== 'undefined' ? window : this);
