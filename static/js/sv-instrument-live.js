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

  function paintQuote(d) {
    if (!d || d.error || d.price == null) return;
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
