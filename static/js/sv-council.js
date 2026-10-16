/* THE COUNCIL on the TAKE TRADE ticket (2026-10-08,
   ai_agents/agents/council.py, dashboard/views_council.py).

   A LIVE ticket whose preview carries council_on gets one region under
   the reward:risk warning. Nothing runs when the ticket opens: only the
   "Ask the council" click POSTs /council/ask/, and the dialog then polls
   GET /council/<id>/ every 3 s for up to 300 s, showing each voice as it
   lands and the Emperor last.

   Advice only. The ticket's OK button never reads this region, nothing
   here changes the ticket or the order, and a council that is off, out
   of budget or too slow is said in words and changes nothing. The one
   thing that leaves this file is the sitting's id (region.dataset.session),
   which the ticket sends with its execute body so the sitting can be
   graded on the trade AFTER it was taken. */
(function () {
  'use strict';
  var SV = window.SV = window.SV || {};

  var HINT = 'Ten AI voices argue this ticket, then the Emperor weighs them ' +
    'by their graded record. Advice only: nothing here changes the ticket ' +
    'or the order. About one to three minutes.';
  var FOOTER = 'Shadow: the council is graded on what the market does next. ' +
    'It never changes an order, a size, a stop or a limit.';
  var POLL_MS = 3000;
  var POLL_MAX_MS = 300000;
  var FINISHED = ['done', 'partial', 'silent'];

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;',
               "'": '&#39;' }[c];
    });
  }

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function lvl(x) {
    var n = Number(x);
    return isFinite(n) ? String(Number(n.toPrecision(8))) : String(x);
  }

  function moved(a, b) {
    var x = Number(a), y = Number(b);
    if (!isFinite(x) || !isFinite(y)) return false;
    return Math.abs(x - y) > 1e-9 * Math.max(1, Math.abs(y));
  }

  function voiceLine(v) {
    if (v.status === 'late') return v.name + ': late, not heard by the chair.';
    // asked, no answer yet and no reason: still answering, not silent
    if (v.status === 'asked' && !v.why) return v.name + ': not answered yet';
    if (v.status === 'silent' || v.status === 'asked') {
      return v.name + ': silent (' + (v.why || 'no answer yet') + ')';
    }
    var line = v.name + ': ' + (v.verdict_words || v.verdict) + '.';
    if (v.line) line += ' ' + String(v.line).replace(/\.$/, '') + '.';
    if (v.weight_seen != null) {
      line += ' Record ' + Number(v.weight_seen).toFixed(2) + ': ' +
        (v.weight_reason || '');
    }
    return line;
  }

  function render(s, out, getTicket, timedOut) {
    var voices = s.voices || [];
    var spoken = voices.filter(function (v) {
      return v.status === 'spoke' || v.status === 'copied';
    }).length;
    var html = [];
    var finished = FINISHED.indexOf(s.status) !== -1;
    if (s.status === 'silent' && !spoken) {
      html.push('<p class="sz-note">' + esc('The council is not sitting: ' +
        (s.why || 'it fell silent')) + '</p>');
    } else if (finished) {
      html.push('<p class="sz-note">The council has spoken.</p>');
    } else if (timedOut) {
      html.push('<p class="sz-note">' + esc('The council did not finish in ' +
        'time; what it said so far is shown. Nothing about this ticket ' +
        'depends on it.') + '</p>');
    } else {
      html.push('<p class="sz-note">' + esc('The council is sitting: ' +
        spoken + ' of ' + Math.max(voices.length, 10) +
        ' voices have spoken.') + '</p>');
    }
    var now = getTicket ? getTicket() : null;
    if (now && s.asked && (moved(now.stop, s.asked.stop) ||
                           moved(now.target, s.asked.target))) {
      html.push('<p class="sz-why">' + esc('Asked at stop ' +
        lvl(s.asked.stop) + ' and target ' + lvl(s.asked.target) +
        '; the levels have moved since.') + '</p>');
    }
    if (s.emperor) {
      html.push('<p><b>' + esc('THE EMPEROR: ' + s.emperor.verdict_words +
        '. Followed: ' + ((s.emperor.followed || []).join(', ') || 'none') +
        '. Overruled: ' + ((s.emperor.overruled || []).join(', ') || 'none') +
        '.') + '</b></p>');
    }
    var items = voices.filter(function (v) { return v.voice !== 'emperor'; })
      .map(function (v) { return '<li>' + esc(voiceLine(v)) + '</li>'; });
    if (items.length) html.push('<ul class="sz-council-voices">' +
                                items.join('') + '</ul>');
    html.push('<p class="sz-note">' + esc(FOOTER) + '</p>');
    out.innerHTML = html.join('');
  }

  function poll(id, out, getTicket) {
    var started = Date.now();
    function tick() {
      fetch('/council/' + id + '/', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (s) {
          var late = Date.now() - started > POLL_MAX_MS;
          var finished = FINISHED.indexOf(s.status) !== -1;
          render(s, out, getTicket, late && !finished);
          if (!finished && !late) setTimeout(tick, POLL_MS);
        })
        .catch(function () {
          if (Date.now() - started <= POLL_MAX_MS) setTimeout(tick, POLL_MS);
        });
    }
    tick();
  }

  /* region: the dialog's council element; getTicket: the dialog's current
     {symbol, side, stop, target, qty, leverage, entry, signal_id}. */
  function mount(region, getTicket) {
    if (!region) return;
    region.innerHTML =
      '<div class="sz-council">' +
        '<button type="button" class="sv-dialog-btn" data-role="council-ask">' +
          'Ask the council</button>' +
        '<p class="sz-note">' + esc(HINT) + '</p>' +
        '<div data-role="council-out" aria-live="polite"></div>' +
      '</div>';
    var btn = region.querySelector('[data-role="council-ask"]');
    var out = region.querySelector('[data-role="council-out"]');
    btn.addEventListener('click', function () {
      var ticket = getTicket ? getTicket() : {};
      btn.disabled = true;
      out.innerHTML = '<p class="sz-note">Asking the council...</p>';
      fetch('/council/ask/', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'X-CSRFToken': csrf(), 'Content-Type': 'application/json' },
        body: JSON.stringify(ticket || {})
      }).then(function (r) {
        return r.json().then(function (j) { return { status: r.status, j: j }; });
      }).then(function (res) {
        var j = res.j || {};
        if (!j.ok) {
          out.innerHTML = '<p class="sz-note">' +
            esc(j.why || j.error || 'The council is not sitting.') + '</p>';
          btn.disabled = false;
          return;
        }
        region.dataset.session = String(j.id);
        poll(j.id, out, getTicket);
      }).catch(function (e) {
        out.innerHTML = '<p class="sz-note">' +
          esc('The council could not be asked: ' + String(e)) + '</p>';
        btn.disabled = false;
      });
    });
  }

  SV.council = { mount: mount };
})();
