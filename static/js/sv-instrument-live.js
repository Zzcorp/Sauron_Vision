/* Live instrument page — the price hero moves, and so does the chart.
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

  function paintQuote(d) {
    if (!d || d.error) return;
    /* BEFORE the price guard below. A row can carry a bid and an ask with
       no `last` — and the ticket trades off those two, so letting a
       missing last suppress them would freeze the only numbers on the
       buttons. */
    paintDq(d);
    if (d.price == null) return;
    var price = Number(d.price);
    /* toFixed matches the server's floatformat:4 byte for byte — the
       first poll must not rewrite an unchanged price into a different
       spelling and fire a lie of a flash. */
    var txt = price.toFixed(4);
    if (lastEl) {
      var changed = prevPrice !== null && price !== prevPrice;
      lastEl.textContent = txt;
      if (changed) flash(lastEl);
    }
    prevPrice = price;
    if (chgEl && d.change_pct != null) {
      var up = Number(d.change_pct) >= 0;
      chgEl.classList.toggle('up', up);
      chgEl.classList.toggle('down', !up);
      chgEl.textContent = (up ? '▲ +' : '▼ ') +
        Number(d.change_pct).toFixed(2) + '%';
    }
    /* Nudge the chart's last candle so the tape ticks between refreshes. */
    var chart = window.svCharts && window.svCharts['instrument-main-chart'];
    if (chart && chart.tick) chart.tick(Number(d.price));
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
