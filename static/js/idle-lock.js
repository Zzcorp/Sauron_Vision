/* idle-lock.js — the client half of the idle PIN lock.
 *
 * The lock itself is a SERVER session flag (core/idle_lock.py): while it
 * is set every JSON endpoint answers 423, so nothing this file does — or
 * fails to do — can weaken the lock. What lives here is only timing and
 * paint: notice idleness, ask the server to set the flag, and open the
 * overlay; verify the PIN against /api/session/unlock/ and close it.
 *
 * Activity is shared across tabs through localStorage, so typing in one
 * tab keeps a second monitor's tab unlocked. Convergence the other way —
 * a tab discovering it WAS locked elsewhere — rides the existing 10s
 * health poll: base.html calls window.svIdleLock.engage(false) on a 423.
 *
 * Unlocking never reloads the page. The lock is a flag, not a logout:
 * the session, its CSRF token, the websockets and the page state all
 * survive underneath the overlay.
 */
(function (w, d) {
    "use strict";

    var script = d.getElementById("idleLockScript");
    if (!script) return;

    var armed   = script.getAttribute("data-il-enabled") === "1" &&
                  script.getAttribute("data-il-has-pin") === "1";
    var minutes = parseInt(script.getAttribute("data-il-minutes"), 10) || 10;
    var lockedAtRender = script.getAttribute("data-il-locked") === "1";

    var LS_KEY = "sv:lastActivity";
    var UNLOCK_KEY = "sv:unlockedAt";   /* cross-tab release signal */
    var CHECK_EVERY = 30000;          /* ms between idle checks */
    var STAMP_EVERY = 1000;           /* min ms between activity stamps */
    var MOVE_EVERY = 2000;            /* pointermove is a firehose — throttle */
    var PING_EVERY = 120000;          /* keep the SERVER's clock in step */
    var PIN_MIN = 4, PIN_MAX = 8;     /* same policy as the login gate */

    var overlay = d.getElementById("idleLockOverlay");
    var isLocked = false;
    var lastActivity = Date.now();
    var lastStamp = 0, lastMove = 0, lastPing = Date.now();

    /* ── activity clock, shared across tabs ─────────────────────────── */

    function stamp() {
        lastActivity = Date.now();
        try { localStorage.setItem(LS_KEY, String(lastActivity)); } catch (e) {}
    }

    function newestActivity() {
        /* The freshest of this tab's clock and the shared one — another
           tab being used must keep this one unlocked. */
        var t = lastActivity;
        try {
            var shared = parseInt(localStorage.getItem(LS_KEY), 10);
            if (!isNaN(shared) && shared > t) t = shared;
        } catch (e) {}
        return t;
    }

    function touch() {
        /* Typing INTO the lock screen is presence, not activity: the
           session only becomes active again when the PIN verifies. */
        if (isLocked) return;
        var now = Date.now();
        if (now - lastStamp < STAMP_EVERY) { lastActivity = now; return; }
        lastStamp = now;
        stamp();
    }

    /* ── engage / release ────────────────────────────────────────────── */

    function csrf() {
        var inp = d.querySelector("#ilLogoutForm input[name=csrfmiddlewaretoken]") ||
                  d.querySelector("input[name=csrfmiddlewaretoken]");
        return inp ? inp.value : "";
    }

    function engage(tellServer) {
        if (isLocked || !overlay) return;
        isLocked = true;
        if (tellServer !== false) {
            /* Server first: the flag is the lock, the overlay is paint.
               Fire-and-forget — the server-side gap backstop covers a
               request that never lands. */
            try {
                fetch("/api/session/lock/", {
                    method: "POST",
                    credentials: "same-origin",
                    headers: { "X-CSRFToken": csrf(),
                               "X-Requested-With": "XMLHttpRequest" }
                }).catch(function () {});
            } catch (e) {}
        }
        pinClear();
        showError(null);
        if (w.SV && w.SV.overlay) w.SV.overlay.open(overlay);
        /* The live sockets are not HTTP and never meet the middleware, so
           they would keep streaming quotes, fills and signals to a locked
           tab. base.html closes them on this event; the consumers refuse
           to re-accept one while the flag is set. */
        d.dispatchEvent(new CustomEvent("sv:pin-locked"));
    }

    function release(shout) {
        isLocked = false;
        stamp();
        pinClear();
        showError(null);
        if (w.SV && w.SV.overlay) w.SV.overlay.close(overlay);
        d.dispatchEvent(new CustomEvent("sv:pin-unlocked"));
        /* The flag is per SESSION, so one verified PIN unlocks every tab.
           Locking converges through the 423 poll; unlocking had no such
           path, leaving a second monitor's gate up over a session that
           was already open. */
        if (shout !== false) {
            try { localStorage.setItem(UNLOCK_KEY, String(Date.now())); } catch (e) {}
        }
    }

    w.addEventListener("storage", function (e) {
        if (!e || e.key !== UNLOCK_KEY || !isLocked) return;
        release(false);   /* no echo — the tab that verified already shouted */
    });

    /* ── the PIN boxes: 4 shipped, growing to 8 like the login gate ──── */

    var pinRow = d.getElementById("ilPinRow");

    function pinBoxes() {
        return pinRow ? [].slice.call(pinRow.querySelectorAll("[data-il-pin]")) : [];
    }
    function pinValue() {
        return pinBoxes().map(function (b) { return b.value; }).join("");
    }
    function makeBox() {
        var inp = d.createElement("input");
        inp.type = "password";
        inp.maxLength = 1;
        inp.className = "";
        inp.setAttribute("inputmode", "numeric");
        inp.setAttribute("autocomplete", "one-time-code");
        inp.setAttribute("data-il-pin", "");
        inp.setAttribute("aria-label", "PIN digit " + (pinBoxes().length + 1));
        return inp;
    }
    function focusFirstEmpty() {
        var boxes = pinBoxes();
        for (var i = 0; i < boxes.length; i++) {
            if (!boxes[i].value) { boxes[i].focus({ preventScroll: true }); return; }
        }
        if (boxes.length) boxes[boxes.length - 1].focus({ preventScroll: true });
    }
    function pinInsert(digit) {
        var boxes = pinBoxes();
        for (var i = 0; i < boxes.length; i++) {
            if (!boxes[i].value) { boxes[i].value = digit; focusFirstEmpty(); return; }
        }
        if (boxes.length < PIN_MAX) {
            var nb = makeBox();
            pinRow.appendChild(nb);
            nb.value = digit;
            nb.focus({ preventScroll: true });
        }
    }
    function pinBackspace() {
        var boxes = pinBoxes();
        for (var i = boxes.length - 1; i >= 0; i--) {
            if (boxes[i].value) {
                boxes[i].value = "";
                if (i >= PIN_MIN) boxes[i].remove();
                focusFirstEmpty();
                return;
            }
        }
        focusFirstEmpty();
    }
    function pinClear() {
        pinBoxes().forEach(function (b, i) {
            if (i >= PIN_MIN) b.remove(); else b.value = "";
        });
    }

    function showError(msg) {
        var el = d.getElementById("ilError");
        if (!el) return;
        if (msg) { el.textContent = msg; el.hidden = false; }
        else { el.textContent = ""; el.hidden = true; }
    }

    /* ── unlock: the PIN is verified by the server, never here ───────── */

    function submitPin() {
        var pin = pinValue();
        if (pin.length < PIN_MIN) {
            showError("Enter at least " + PIN_MIN + " digits.");
            return;
        }
        var btn = d.getElementById("ilUnlockBtn");
        if (btn) btn.disabled = true;
        fetch("/api/session/unlock/", {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "X-CSRFToken": csrf(),
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded"
            },
            body: "pin=" + encodeURIComponent(pin)
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (btn) btn.disabled = false;
            if (data.status === "ok") { release(); return; }
            if (data.status === "logged_out") {
                /* Five failures flushed the session server-side. */
                w.location.href = "/wall/";
                return;
            }
            pinClear();
            showError((data.error || "Incorrect PIN.") +
                (typeof data.attempts_left === "number"
                    ? " " + data.attempts_left + " attempt" +
                      (data.attempts_left === 1 ? "" : "s") + " left."
                    : ""));
            focusFirstEmpty();
        })
        .catch(function () {
            if (btn) btn.disabled = false;
            showError("Could not reach the server — try again.");
        });
    }

    /* ── wiring ──────────────────────────────────────────────────────── */

    if (overlay) {
        overlay.addEventListener("keydown", function (e) {
            if (e.ctrlKey || e.metaKey || e.altKey) return;
            if (/^[0-9]$/.test(e.key)) { e.preventDefault(); pinInsert(e.key); }
            else if (e.key === "Backspace") { e.preventDefault(); pinBackspace(); }
            else if (e.key === "Enter") {
                /* Enter on the Disconnect/forgot buttons must still submit
                   the logout form — only intercept it for the PIN flow. */
                if (e.target && e.target.hasAttribute &&
                    (e.target.hasAttribute("data-il-pin") || e.target.id === "ilUnlockBtn")) {
                    e.preventDefault();
                    submitPin();
                }
            }
        });
        /* IME/paste fallback: soft keyboards can bypass keydown. */
        overlay.addEventListener("input", function (e) {
            var t = e.target;
            if (!t.hasAttribute || !t.hasAttribute("data-il-pin")) return;
            if (t.value) t.value = t.value.replace(/\D/g, "").slice(-1);
            if (t.value) focusFirstEmpty();
        });
        var unlockBtn = d.getElementById("ilUnlockBtn");
        if (unlockBtn) unlockBtn.addEventListener("click", submitPin);
    }

    /* Cross-tab + health-poll hook (see the 423 branch in base.html). */
    w.svIdleLock = {
        engage: engage,
        isLocked: function () { return isLocked; }
    };

    /* Locked at render time — the server flag was already set (another
       tab, or the middleware backstop). Open the gate before anything
       else paints as usable. */
    if (lockedAtRender) engage(false);

    /* ── idle detection ──────────────────────────────────────────────── */

    if (armed) {
        ["pointerdown", "keydown", "wheel", "touchstart", "scroll"]
            .forEach(function (ev) {
                d.addEventListener(ev, touch, { capture: true, passive: true });
            });
        d.addEventListener("pointermove", function () {
            var now = Date.now();
            if (now - lastMove < MOVE_EVERY) return;
            lastMove = now;
            touch();
        }, { capture: true, passive: true });

        function check() {
            if (isLocked) return;
            if (Date.now() - newestActivity() > minutes * 60000) { engage(true); return; }
            /* Reading a chart or scrolling a table sends no HTTP request,
               so the SERVER's clock would go stale while the operator is
               plainly working and its backstop would lock them on their
               next click. One tiny POST per PING_EVERY while there is
               local activity keeps the two clocks in sight of each other. */
            var now = Date.now();
            if (now - lastPing < PING_EVERY) return;
            if (newestActivity() < lastPing) return;   /* nothing new to report */
            lastPing = now;
            try {
                fetch("/api/session/ping/", {
                    method: "POST",
                    credentials: "same-origin",
                    headers: { "X-CSRFToken": csrf(),
                               "X-Requested-With": "XMLHttpRequest" }
                }).then(function (r) {
                    /* 423: locked elsewhere (sibling tab, or the server
                       backstop) — converge instead of pinging into a wall. */
                    if (r.status === 423) engage(false);
                }).catch(function () {});
            } catch (e) {}
        }
        setInterval(check, CHECK_EVERY);
        d.addEventListener("visibilitychange", function () {
            /* Coming back to a tab is the moment to decide whether it
               slept past the window — NOT a form of activity. */
            if (d.visibilityState === "visible") check();
        });
        stamp();  /* page load seeds the shared clock */
    }
})(window, document);
