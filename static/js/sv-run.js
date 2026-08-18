/* ═══════════════════════════════════════════════════════════════════════
   SV-RUN — async "Run now" buttons
   ───────────────────────────────────────────────────────────────────────
   Any form tagged data-run-job posts via fetch instead of navigating:
   the server enqueues the real Celery task and answers 202, the button
   flips to RUNNING…, and completion arrives on the /ws/eye/ socket as
   kind "run_complete" (re-dispatched by base.html as a "sv:eye-event"
   CustomEvent) — banner + bell from the Notification row, button reset
   and an optional in-place region refresh here. A form without the tag,
   a browser without JS, or a dead broker all fall back to the original
   synchronous POST + redirect.

   Optional attributes:
     data-run-job      the job label the server echoes back (match key)
     data-run-refresh  CSS selector of a page region to refresh in place
                       on completion (fetch current URL → DOMParser →
                       swap that element's innerHTML). Omit for pages
                       where the banner alone is the announcement.      */
(function (w, d) {
    "use strict";

    function csrf() {
        var m = d.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : "";
    }

    var running = {};   /* job label -> {btn, oldText, form, timer} */

    function reset(job) {
        var r = running[job];
        if (!r) return;
        delete running[job];
        if (r.timer) clearTimeout(r.timer);
        if (r.btn) {
            r.btn.disabled = false;
            r.btn.textContent = r.oldText;
        }
    }

    function refreshRegion(sel) {
        var target = d.querySelector(sel);
        if (!target) return;
        fetch(w.location.href, { credentials: "same-origin" })
            .then(function (resp) {
                if (!resp.ok) throw new Error("HTTP " + resp.status);
                return resp.text();
            })
            .then(function (html) {
                var doc = new DOMParser().parseFromString(html, "text/html");
                var fresh = doc.querySelector(sel);
                /* innerHTML swap does not re-run inline scripts — only
                   safe for regions that are pure markup, which is why the
                   attribute is opt-in per form. */
                if (fresh) target.innerHTML = fresh.innerHTML;
            })
            .catch(function () { /* the banner already announced */ });
    }

    d.addEventListener("submit", function (e) {
        var form = e.target && e.target.closest
            && e.target.closest("form[data-run-job]");
        if (!form) return;
        var job = form.getAttribute("data-run-job");
        if (!job || running[job]) { if (running[job]) e.preventDefault(); return; }
        e.preventDefault();

        var btn = form.querySelector("button[type=submit], button");
        var oldText = btn ? btn.textContent : "";
        if (btn) { btn.disabled = true; btn.textContent = "⏳ RUNNING…"; }
        running[job] = { btn: btn, oldText: oldText, form: form };

        /* Safety net: if no completion ever arrives (worker down, socket
           dead), free the button — the durable Notification still lands
           in the inbox if the job did finish. */
        running[job].timer = setTimeout(function () {
            reset(job);
            if (w.svBanner) {
                w.svBanner("notification", {
                    id: "runwatch-" + job, type: "system",
                    title: job + " is taking a while",
                    body: "Still running in the background — its result "
                        + "will land in your notifications.",
                    url: "/notifications/"
                });
            }
        }, 15 * 60 * 1000);

        fetch(form.action, {
            method: "POST", credentials: "same-origin",
            headers: { "X-CSRFToken": csrf(),
                       "X-Requested-With": "XMLHttpRequest" },
            body: new FormData(form)
        }).then(function (resp) {
            if (resp.status === 202) return;   /* enqueued — wait for WS */
            if (resp.status === 409) {
                /* Already in flight (another tab, another operator) —
                   free the button; that run's completion announces. */
                reset(job);
                if (w.svBanner) {
                    w.svBanner("notification", {
                        id: "rundupe-" + job, type: "system",
                        title: job + " is already running",
                        body: "One run is in flight — its result will "
                            + "announce when it lands.",
                        url: ""
                    });
                }
                return;
            }
            /* Anything else: the server ran the sync fallback (or
               refused). Reload so its flash message is visible. */
            reset(job);
            w.location.reload();
        }).catch(function () {
            reset(job);
            if (w.svBanner) {
                w.svBanner("notification", {
                    id: "runfail-" + job, type: "system",
                    title: job + " could not be started",
                    body: "Network error — try again.",
                    url: ""
                });
            }
        });
    }, true);

    d.addEventListener("sv:eye-event", function (e) {
        var msg = e.detail || {};
        if (msg.kind !== "run_complete" || !msg.data) return;
        var job = msg.data.job;
        var r = running[job];
        reset(job);
        if (r && r.form) {
            var sel = r.form.getAttribute("data-run-refresh");
            if (sel) refreshRegion(sel);
        }
    });
})(window, document);
