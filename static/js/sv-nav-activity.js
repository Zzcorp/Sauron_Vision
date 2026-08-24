/* Sidebar unseen-activity dots — nothing stays unseen.
 *
 * Every nav entry whose page has REAL activity newer than the operator's
 * last visit wears a pulsing dot. Server truth, per user: the seen-map
 * lives on the profile, so a page read on the phone goes quiet on the
 * desktop too, and a second browser cannot resurrect a dot the operator
 * already cleared.
 *
 * Contract with /api/nav-activity/ (dashboard.views.nav_activity_json):
 *   GET  -> {"pages": {"signals": true, "news": false, ...}}
 *           true = activity newer than the seen-map's stamp for that page.
 *   POST {"page_id": X} -> stamps X seen "now". The page you are ON is
 *           stamped on load — being there IS seeing it.
 *
 * Failure discipline (same as every poller here): 423 = PIN-locked, engage
 * the lock and go quiet; any other failure keeps the last paint — a
 * wrongly-cleared dot hides exactly what this exists to surface, and a
 * wrongly-lit one costs a click.
 */
(function () {
  var POLL_MS = 45000;
  var API = '/api/nav-activity/';

  function csrf() {
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  function currentPage() {
    var el = document.querySelector('[data-nav-page-id]');
    return el ? el.getAttribute('data-nav-page-id') : '';
  }

  function paint(pages) {
    document.querySelectorAll('.sidebar-nav .nav-link[data-nav-id]')
      .forEach(function (link) {
        var id = link.getAttribute('data-nav-id');
        var dot = link.querySelector('.nav-dot');
        var on = !!pages[id] && id !== currentPage();
        if (on && !dot) {
          dot = document.createElement('span');
          dot.className = 'nav-dot';
          dot.title = 'Changed since you last looked';
          link.appendChild(dot);
        } else if (!on && dot) {
          dot.remove();
        }
      });
  }

  function tick() {
    if (document.hidden) return;
    fetch(API, { credentials: 'same-origin' })
      .then(function (r) {
        if (r.status === 423) {
          if (window.svIdleLock) window.svIdleLock.engage(false);
          var locked = new Error('locked'); locked.svLocked = true; throw locked;
        }
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (d) { if (d && d.pages) paint(d.pages); })
      .catch(function () { /* keep the last paint */ });
  }

  /* Being on a page IS seeing it — stamp it once on load, then let the
     regular sweep repaint the rest of the rail. */
  var here = currentPage();
  if (here) {
    fetch(API, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json',
                 'X-CSRFToken': csrf() },
      body: JSON.stringify({ page_id: here }),
    }).catch(function () {}).finally ? undefined : undefined;
  }

  setInterval(tick, POLL_MS);
  setTimeout(tick, 2000);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) tick();
  });
  /* Fills and notifications announce themselves — repaint on the shared
     eye events instead of waiting out the sweep. */
  document.addEventListener('sv:eye-event', function () {
    setTimeout(tick, 1200);
  });
})();
