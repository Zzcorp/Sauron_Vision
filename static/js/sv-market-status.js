/* Live market-session status — the topbar's "N/14 SE" indicator, its
   dropdown rows, and the instrument page's market badge.

   All three were render-time constants from core.exchange_status: correct
   at first paint, then frozen. A tab left open across the New York close
   kept saying NYSE OPEN — on a platform where every other cell moves on
   its own. This polls /api/exchange-status/ (clock arithmetic, no
   queries) once a minute and re-paints in place.

   Failure discipline (same as the live-status pill's poller in
   base.html):
   - 423 = the session is PIN-locked, not an outage. Engage the lock in
     this tab and stop touching the DOM.
   - Any other failure leaves the last server-rendered truth standing —
     the SSR values are at worst a minute-old reading of the same clock,
     and a wrongly blanked indicator is a louder lie than a stale one.
   - r.json() rejecting catches the login-page-as-200 case (session
     expiry redirects to the wall, which answers 200 with HTML). */
(function () {
  var POLL_MS = 60000;

  function paintTopbar(d) {
    var open = document.querySelector('[data-ex-open-count]');
    var total = document.querySelector('[data-ex-total]');
    if (open) open.textContent = d.open_count;
    if (total && d.total) total.textContent = d.total;
    (d.exchanges || []).forEach(function (ex) {
      var row = document.querySelector('.exchange-row[data-ex-code="' + ex.code + '"]');
      if (!row) return; /* payload grew a venue this page predates — skip */
      var local = row.querySelector('.ex-local'),
          state = row.querySelector('.ex-state'),
          until = row.querySelector('.ex-until');
      if (local) local.textContent = ex.local_time;
      if (state) {
        state.textContent = ex.is_open ? 'OPEN' : 'CLOSED';
        state.className = 'ex-state ' + (ex.is_open ? 'st-open' : 'st-closed');
      }
      if (until) until.textContent = ex.next_state + ' in ' + ex.time_until_change;
    });
  }

  function paintBadge(d) {
    var badge = document.querySelector('[data-market-session]');
    if (!badge) return;
    var code = badge.getAttribute('data-market-session');
    var text = badge.querySelector('.mk-text');

    /* CRYPTO has no session row — there is no clock to consult. The badge
       shipped open and stays open; nothing to repaint. */
    if (code === 'CRYPTO') return;

    var ex = (d.exchanges || []).find(function (e) { return e.code === code; });
    if (!ex) return; /* unknown session: leave the server's answer alone */
    badge.classList.toggle('mk-open', !!ex.is_open);
    badge.classList.toggle('mk-closed', !ex.is_open);
    if (text) {
      text.textContent = ex.name + ' · ' + (ex.is_open ? 'OPEN' : 'CLOSED') +
        (ex.time_until_change ? ' · ' + ex.next_state + ' in ' + ex.time_until_change : '');
    }
  }

  function tick() {
    /* Nothing here is worth waking a background tab for; the first
       visible tick catches it up. */
    if (document.hidden) return;
    fetch('/api/exchange-status/', { credentials: 'same-origin' })
      .then(function (r) {
        if (r.status === 423) {
          if (window.svIdleLock) window.svIdleLock.engage(false);
          var locked = new Error('locked'); locked.svLocked = true; throw locked;
        }
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (d) {
        if (!d || d.error) return; /* keep the last truth on server error */
        paintTopbar(d);
        paintBadge(d);
      })
      .catch(function () { /* keep the last truth */ });
  }

  setInterval(tick, POLL_MS);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) tick();
  });
})();
