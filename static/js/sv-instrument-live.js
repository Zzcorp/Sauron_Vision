/* Live instrument page — the price hero moves, and so does the chart.
 *
 * (2026-10-31) It also says whose price it is: the feed, its age and the
 * stand-in words under the hero, the venue's last known price beside it,
 * at the page's own decimal count; the "Latest Quote" card is repainted
 * with it; and the chart is handed the whole quote, so it welds only a
 * quote that belongs on its last candle.
 *
 * The page rendered a price and a chart once and froze; the market badge
 * next to them was live, which made the frozen number read as current —
 * the worst combination. Two loops fix it:
 *
 *  1. QUOTE loop (15s): /api/instrument-preview/<symbol>/ — the same
 *     payload the hover popups read — updates the hero last/change chip
 *     (flash on change) and, between chart refreshes, the last candle's
 *     close via series.update() so the tape visibly ticks.
 *
 *  2. CHART loop (60s, matching chart_data_api's intraday cache TTL):
 *     re-fetches the active resolution and setData()s it — the widget
 *     registers itself on window.svCharts[chartId] with {refresh, tick}.
 *
 * Failure discipline: 423 engages the PIN lock and goes quiet; anything
 * else keeps the last truth on screen — the market badge already says
 * whether the market is open, so a stale price under an OPEN badge heals
 * on the next good poll rather than blanking.
 */
(function () {
  var hero = document.querySelector('[data-instrument-live]');
  if (!hero) return;
  var symbol = hero.getAttribute('data-instrument-live');
  if (!symbol) return;

  var QUOTE_MS = 15000;
  var CHART_MS = 60000;

  /* Document scope: the carrier is the chart card (always rendered);
     the hero spans exist only once a quote does, and may not yet. */
  var lastEl = document.querySelector('.dtl-last');
  var chgEl = document.querySelector('.dtl-chg');
  /* Whose price it is (2026-10-31): the feed, its age and the stand-in
     words under the hero, and the venue's last known price beside it. */
  var srcEl = document.querySelector('[data-hero="src"]');
  var venueEl = document.querySelector('[data-hero="venue"]');

  /* THE PAGE'S ONE DECIMAL COUNT (2026-10-31). The hero was repainted
     with toFixed(4) from the first poll: "1.0835" over a chart printing
     "1.08345", "258.4000" beside "258.40", and a token under 0.0001 as
     "0.0000" — a zero on the hero. The server's count rides the element
     (data-decimals, as on the ticket); this mirrors base.html's
     svDecimals when it is absent. */
  function decimalsFor(el, v) {
    var holder = el && el.closest && el.closest('[data-decimals]');
    if (holder) {
      var n = parseInt(holder.getAttribute('data-decimals'), 10);
      if (isFinite(n) && n >= 0 && n <= 10) return n;
    }
    var a = Math.abs(v);
    if (a >= 1) return 2;
    if (a >= 0.01) return 4;
    if (a >= 0.0001) return 6;
    return 8;
  }
  function priceText(el, v) {
    var n = Number(v);
    return n.toFixed(decimalsFor(el, n));
  }

  function flash(el) {
    if (!el) return;
    el.classList.remove('sv-flash');
    void el.offsetWidth; /* restart the animation */
    el.classList.add('sv-flash');
  }

  var prevPrice = null; /* flash on VALUE change, never on format drift */

  /* Beyond this a quote is a fossil, not a price. Same bound the signal
     lifecycle uses for a LiveQuote before it falls back to bars. */
  var STALE_S = 900;
  var prevDq = {};

  /* Bid, ask and spread. These carried `data-dq` hooks from the day they
     were added and NOTHING ever wrote to them — server-rendered at first
     paint and frozen for the life of the tab. Survivable while they sat
     in a stats row; not survivable now that they ride the buttons that
     trade on them, which is why the ticket refuses to print a number it
     cannot stand behind.

     querySelectorAll, not querySelector: the page carries TWO tickets —
     the header's and the expanded chart's overlay — and a repaint that
     found only the first would leave the other one lying. */
  function paintDq(d) {
    var stale = d.quote_age_seconds != null && d.quote_age_seconds > STALE_S;
    document.querySelectorAll('.sv-ticket').forEach(function (tk) {
      tk.classList.toggle('tk-stale', stale);
    });
    ['bid', 'ask', 'spread'].forEach(function (k) {
      var raw = d[k];
      var nodes = document.querySelectorAll('[data-dq="' + k + '"]');
      if (!nodes.length) return;
      nodes.forEach(function (el) {
        if (raw == null || raw === '') {
          /* The house rule, and it matters most here: unknown renders as
             a muted em-dash, never as a zero. A 0.00 on a BUY button is
             a price claim nobody made. */
          el.innerHTML = '<span class="sv-unknown">—</span>';
          return;
        }
        var dp = parseInt(
          (el.closest('[data-decimals]') || {}).getAttribute
            ? el.closest('[data-decimals]').getAttribute('data-decimals')
            : '', 10);
        var txt = isNaN(dp) ? String(raw) : Number(raw).toFixed(dp);
        if (el.textContent !== txt) {
          el.textContent = txt;
          if (prevDq[k] != null && prevDq[k] !== txt) flash(el);
        }
      });
      prevDq[k] = raw == null ? null : String(raw);
    });
  }

  /* The day change, when it is the price's own feed's (2026-10-31,
     skeptic M3). A stream's trade print carries none, so the row keeps
     the poller's: printed beside the stream's price as one reading, its
     arrow and colour could contradict the price. Another feed's change
     prints a muted dash, and its title says whose it is. */
  function paintChange(el, d, withArrow) {
    if (!el) return;
    if (d.change_same_feed === false) {
      el.classList.remove('up', 'down');
      el.classList.add('dtl-chg--other');
      el.textContent = '—';
      el.title = d.change_words || '';
      return;
    }
    if (d.change_pct == null) return;
    var up = Number(d.change_pct) >= 0;
    el.classList.remove('dtl-chg--other');
    el.classList.toggle('up', up);
    el.classList.toggle('down', !up);
    el.title = '';
    el.textContent = (withArrow ? (up ? '▲ +' : '▼ ') : (up ? '+' : '')) +
      Number(d.change_pct).toFixed(2) + '%';
  }

  /* Under the hero: whose price, how old, the stand-in words; beside it,
     the venue's last known price, its age and the gap to the quote. */
  function paintWho(d) {
    if (srcEl && d.source_words) {
      srcEl.textContent = d.source_words +
        (d.age_words ? ' · ' + d.age_words + ' old' : '');
    }
    if (venueEl) {
      var v = d.venue;
      if (v && v.price_text) {
        venueEl.textContent = v.label + ' ' + v.price_text + ' · ' +
          v.age_words + ' old' + (d.gap_words ? ' · ' + d.gap_words : '');
        venueEl.hidden = false;
      } else {
        venueEl.textContent = '';
        venueEl.hidden = true;
      }
    }
  }

  /* The "Latest Quote" card, which was rendered once and never again:
     its LAST disagreed with the hero from the first tick. */
  function paintCard(d) {
    var el = document.querySelector('[data-lq="last"]');
    if (el && d.price != null) el.textContent = priceText(el, d.price);
    paintChange(document.querySelector('[data-lq="change"]'), d, false);
    el = document.querySelector('[data-lq="sides"]');
    if (el) {
      var side = function (v) {
        return (v == null || v === '') ? '—' : priceText(el, v);
      };
      el.textContent = side(d.bid) + ' / ' + side(d.ask);
      el.title = d.sides_words ? 'Bid and ask from ' + d.sides_words : '';
    }
    el = document.querySelector('[data-lq="source"]');
    if (el && d.source_words) el.textContent = d.source_words;
    el = document.querySelector('[data-lq="updated"]');
    if (el && d.age_words) el.textContent = d.age_words + ' ago';
  }

  function paintQuote(d) {
    if (!d || d.error) return;
    /* BEFORE the price guard below. A row can carry a bid and an ask with
       no `last` — and the ticket trades off those two, so letting a
       missing last suppress them would freeze the only numbers on the
       buttons. */
    paintDq(d);
    paintWho(d);
    paintCard(d);
    if (d.price == null) return;
    var price = Number(d.price);
    if (lastEl) {
      /* At the page's own count, the spelling the server rendered: the
         first poll must not rewrite an unchanged price into another
         spelling and fire a lie of a flash. */
      var txt = priceText(lastEl, price);
      var changed = prevPrice !== null && price !== prevPrice;
      lastEl.textContent = txt;
      if (changed) flash(lastEl);
    }
    prevPrice = price;
    paintChange(chgEl, d, true);
    /* The chart's last candle, when the quote belongs on it: the chart
       decides from the quote's feed, age and size (chart_widget tick). */
    var chart = window.svCharts && window.svCharts['instrument-main-chart'];
    if (chart && chart.tick) chart.tick(price, d);
  }

  function guard(r) {
    if (r.status === 423) {
      if (window.svIdleLock) window.svIdleLock.engage(false);
      var locked = new Error('locked'); locked.svLocked = true; throw locked;
    }
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }

  function quoteTick() {
    if (document.hidden) return;
    fetch('/api/instrument-preview/' + encodeURIComponent(symbol) + '/',
          { credentials: 'same-origin' })
      .then(guard).then(paintQuote)
      .catch(function () { /* keep the last truth */ });
  }

  function chartTick() {
    if (document.hidden) return;
    var chart = window.svCharts && window.svCharts['instrument-main-chart'];
    if (chart && chart.refresh) chart.refresh();
  }

  /* ── Positions on the tape, without a reload ──────────────────────
     The chart's overlay now rides the chart-data response (overlays=1),
     so "redraw the positions" and "resync this chart" are the same act:
     chart.refresh(). What was missing was anything to say WHEN.

     Two triggers, on purpose. `sv:position-changed` is the fast local
     path — it fires the instant this page's own execute response lands,
     so the lines are there before the operator has finished reading the
     confirmation. `sv:eye-event` is the cross-surface path: a fill from
     the signals rail, from another tab, or from a bot moves this page
     too, which the local event alone would never cover.

     Debounced, because the response and the WebSocket push arrive
     milliseconds apart and would otherwise buy two identical fetches.
     Deliberately WITHOUT the document.hidden guard the periodic loops
     carry: a one-shot answer to something that just happened is not a
     clock, and an operator returning to the tab must not find a chart
     that skipped the fill they just made. */
  var syncTimer = null;
  function syncPositions() {
    if (syncTimer) return;
    syncTimer = setTimeout(function () {
      syncTimer = null;
      var c = window.svCharts && window.svCharts['instrument-main-chart'];
      if (c && c.refresh) c.refresh();
    }, 250);
  }
  document.addEventListener('sv:position-changed', syncPositions);
  document.addEventListener('sv:eye-event', function (e) {
    var m = (e && e.detail) || {};
    var kind = m.kind || m.event_type || m.type;
    if (kind !== 'fill_open' && kind !== 'fill_close'
        && kind !== 'close_pending') return;
    /* Another instrument's fill changes nothing on this tape. When the
       payload does not name a symbol, refresh anyway — a wasted fetch is
       cheaper than a missing line. */
    var sym = m.symbol || (m.data && m.data.symbol);
    if (sym && String(sym).toUpperCase() !== String(symbol).toUpperCase()) {
      return;
    }
    syncPositions();
  });

  setInterval(quoteTick, QUOTE_MS);
  setInterval(chartTick, CHART_MS);
  setTimeout(quoteTick, 1500);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) { quoteTick(); chartTick(); }
  });
  /* Fresh price AND a fresh chart the moment the gate lifts. */
  document.addEventListener('sv:pin-unlocked', function () {
    quoteTick(); chartTick();
  });
})();
