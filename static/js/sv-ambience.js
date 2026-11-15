/* sv-ambience.js: his choice of Ambience, from the user menu (the magic
   kept, 2026-11-12).

   Magic, Calm or Off: how much of Sauron's own theme the pages show. The
   server prints the saved choice onto <body data-sv-ambience> (the
   get_ambience tag); the sheets, sv-embers.js and sv-moments.js read it
   there and follow it the moment it changes, with no reload.

   A click on one of the menu's three buttons POSTs the choice to his
   profile (dashboard.views.set_ambience). ONLY a 200 answer that echoes
   the value changes the page: the attribute on <body>, then the pressed
   button. Anything else (an error, no network, no answer in ten seconds,
   the PIN lock's 423, the login page a finished session is sent to) leaves
   the page as it was, and the menu says "Not saved". One request at a
   time. The pressed value is posted too: this tab may be behind another
   one, which follows on its next page load.

   DISPLAY ONLY. It reads the session's CSRF cookie and writes that one
   attribute, its own three buttons and its own note: no order, size, stop,
   gate, switch or broker is reached; nothing is stored in the browser and
   nothing is announced to the page. */
(function (w, d) {
    'use strict';

    var TIMEOUT_MS = 10000;
    var body = d.body, host = d.getElementById('umAmbience');
    if (!body || !host || !w.fetch) return;

    var url = host.getAttribute('data-sv-ambience-url');
    var note = host.querySelector('.um-ambience-note');
    var buttons = Array.prototype.slice.call(host.querySelectorAll('[data-sv-ambience-set]'));
    var busy = false;

    function csrf() {
        var m = String(d.cookie || '').match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? m[1] : '';
    }
    function press(value) {
        buttons.forEach(function (b) {
            b.setAttribute('aria-pressed', b.getAttribute('data-sv-ambience-set') === value ? 'true' : 'false');
        });
    }
    function say(words) { if (note) note.textContent = words; }

    /* Resolves on the server's own word for the value; rejects on anything
       else, and after ten seconds without an answer (the request is then
       dropped, and an answer that comes later changes nothing). */
    function save(value) {
        return new Promise(function (resolve, reject) {
            var ctl = w.AbortController ? new w.AbortController() : null;
            var timer = w.setTimeout(function () {
                if (ctl) ctl.abort();
                reject(new Error('no answer'));
            }, TIMEOUT_MS);
            w.fetch(url, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-CSRFToken': csrf(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: 'ambience=' + encodeURIComponent(value),
                signal: ctl ? ctl.signal : undefined
            }).then(function (resp) {
                if (resp.status !== 200) throw new Error('answered ' + resp.status);
                return resp.json();
            }).then(function (answer) {
                if (!answer || answer.ambience !== value) throw new Error('no echo');
                w.clearTimeout(timer);
                resolve(value);
            }).catch(function (err) {
                w.clearTimeout(timer);
                reject(err);
            });
        });
    }

    host.addEventListener('click', function (e) {
        var btn = e.target && e.target.closest ? e.target.closest('[data-sv-ambience-set]') : null;
        if (!btn || !host.contains(btn) || busy) return;
        var value = btn.getAttribute('data-sv-ambience-set');
        busy = true;
        host.setAttribute('aria-busy', 'true');
        save(value).then(function () {
            body.setAttribute('data-sv-ambience', value);      /* the server said so */
            press(value);
            say('');
        }, function () {
            say('Not saved');                                   /* the page stays as it was */
        }).then(function () {
            busy = false;
            host.removeAttribute('aria-busy');
        });
    });
})(window, document);
