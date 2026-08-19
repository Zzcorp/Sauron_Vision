/* ═══════════════════════════════════════════════════════════════════════
   SV-TOUR — the guided platform walk (engine)
   ───────────────────────────────────────────────────────────────────────
   Steps come from window.SV_TOUR (rendered by templates/_tour.html so
   {% url %} resolves). Autostarts once per user — the server remembers
   via /tour/complete/ — and replays from the user menu forever after.

   Deliberate choices:
   - No scroll lock: the walk scrolls its targets into view.
   - Missing/invisible targets auto-skip (mobile sidebar, admin-only
     links, collapsed bands) — the tour adapts to what this user can see.
   - Capture-phase keys with stopPropagation while active, or the app's
     bare-key shortcuts (t/n/g/?) would fire mid-tour.                  */
(function (w, d) {
    "use strict";
    var cfg = w.SV_TOUR;
    var veil = d.getElementById("svTourVeil");
    var spot = d.getElementById("svTourSpot");
    var card = d.getElementById("svTourCard");
    if (!cfg || !veil || !spot || !card
        || !Array.isArray(cfg.steps) || !cfg.steps.length) return;

    var titleEl = d.getElementById("svTourTitle");
    var bodyEl = d.getElementById("svTourBody");
    var stepEl = d.getElementById("svTourStep");
    var dotsEl = d.getElementById("svTourDots");
    var backBtn = d.getElementById("svTourBack");
    var nextBtn = d.getElementById("svTourNext");
    var extraEl = d.getElementById("svTourExtra");

    var active = false, idx = 0, replay = false;
    var reduced = w.matchMedia
        && w.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function csrf() {
        var m = d.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : "";
    }

    function targetOf(step) {
        if (!step.sel) return null;
        var el = d.querySelector(step.sel);
        if (!el) return null;
        var r = el.getBoundingClientRect();
        // Invisible comes in four costumes here: zero rect (display:none),
        // a rect transformed fully OUTSIDE the viewport (the off-canvas
        // mobile sidebar, the collapsed ticker — translateX preserves
        // size), computed visibility:hidden, and opacity 0. A step whose
        // target wears any of them must auto-skip, or the spotlight
        // points at nothing while the card describes it.
        if (!r.width && !r.height) return null;
        if (r.right <= 0 || r.bottom <= 0
            || r.left >= w.innerWidth || r.top >= w.innerHeight) return null;
        try {
            var cs = w.getComputedStyle(el);
            if (cs.visibility === "hidden" || parseFloat(cs.opacity) === 0) {
                return null;
            }
        } catch (e) { /* very old engines */ }
        return el;
    }

    function place(step, el) {
        if (!el) {
            spot.classList.add("is-full");
            spot.style.top = ""; spot.style.left = "";
            spot.style.width = ""; spot.style.height = "";
            // Centered card.
            card.style.visibility = "hidden";
            card.classList.add("is-on");
            var cw = card.offsetWidth, ch = card.offsetHeight;
            card.style.left = Math.max(16, (w.innerWidth - cw) / 2) + "px";
            card.style.top = Math.max(16, (w.innerHeight - ch) / 2) + "px";
            card.style.visibility = "";
            return;
        }
        spot.classList.remove("is-full");
        var r = el.getBoundingClientRect();
        var pad = 6;
        spot.style.top = (r.top - pad) + "px";
        spot.style.left = (r.left - pad) + "px";
        spot.style.width = (r.width + pad * 2) + "px";
        spot.style.height = (r.height + pad * 2) + "px";

        // Card on the side with the most room, clamped into the viewport.
        card.style.visibility = "hidden";
        card.classList.add("is-on");
        var cw2 = card.offsetWidth, ch2 = card.offsetHeight, gap = 14;
        var spaces = {
            right: w.innerWidth - r.right,
            left: r.left,
            bottom: w.innerHeight - r.bottom,
            top: r.top
        };
        var best = Object.keys(spaces).sort(function (a, b) {
            return spaces[b] - spaces[a];
        })[0];
        var top, left;
        if (best === "right") {
            left = r.right + gap;
            top = r.top + r.height / 2 - ch2 / 2;
        } else if (best === "left") {
            left = r.left - cw2 - gap;
            top = r.top + r.height / 2 - ch2 / 2;
        } else if (best === "bottom") {
            left = r.left + r.width / 2 - cw2 / 2;
            top = r.bottom + gap;
        } else {
            left = r.left + r.width / 2 - cw2 / 2;
            top = r.top - ch2 - gap;
        }
        card.style.left = Math.max(8, Math.min(left, w.innerWidth - cw2 - 8)) + "px";
        card.style.top = Math.max(8, Math.min(top, w.innerHeight - ch2 - 8)) + "px";
        card.style.visibility = "";
    }

    var placeTimer = null;

    function render(direction) {
        direction = direction || 1;
        var step = cfg.steps[idx];
        var el = targetOf(step);
        // Auto-skip past targets this user cannot see — in the direction
        // of travel: BACK across a hidden step must keep walking BACK, or
        // it bounces off the hidden step and every earlier step becomes
        // unreachable.
        var guard = 0;
        while (!el && step.sel && guard < cfg.steps.length) {
            idx += direction;
            if (idx >= cfg.steps.length) { finish(); return; }
            if (idx < 0) { idx = 0; direction = 1; }
            step = cfg.steps[idx];
            el = targetOf(step);
            guard += 1;
        }
        if (el) {
            try {
                el.scrollIntoView({
                    block: "center",
                    behavior: reduced ? "auto" : "smooth"
                });
            } catch (e) { /* very old engines */ }
        }
        stepEl.textContent = (idx + 1) + " / " + cfg.steps.length;
        titleEl.textContent = step.title;
        bodyEl.textContent = step.body;
        dotsEl.innerHTML = "";
        cfg.steps.forEach(function (_, i) {
            var dot = d.createElement("span");
            dot.className = "sv-tour-dot" + (i === idx ? " on" : "");
            dotsEl.appendChild(dot);
        });
        backBtn.style.display = idx === 0 ? "none" : "";
        nextBtn.textContent = idx === cfg.steps.length - 1 ? "FINISH" : "NEXT ▸";
        extraEl.innerHTML = "";
        (step.links || []).forEach(function (l) {
            var a = d.createElement("a");
            a.className = "sv-tour-btn";
            a.href = l.href;
            a.textContent = l.label;
            // Following the card's own invitation must not restart the
            // walk on the next page — stamp completion on the way out
            // (keepalive fetch inside complete() survives navigation).
            a.addEventListener("click", function () { complete(); });
            extraEl.appendChild(a);
        });
        veil.classList.add("is-on");
        spot.classList.add("is-on");
        card.classList.add("is-on");
        // Give a bit of time for the scroll, then anchor precisely.
        if (placeTimer) clearTimeout(placeTimer);
        placeTimer = setTimeout(function () {
            placeTimer = null;
            if (!active) return;   /* dismissed inside the window */
            place(step, targetOf(step) || el);
        }, reduced ? 0 : 220);
        place(step, el);
        nextBtn.focus({ preventScroll: true });
    }

    function stop() {
        active = false;
        if (placeTimer) { clearTimeout(placeTimer); placeTimer = null; }
        veil.classList.remove("is-on");
        spot.classList.remove("is-on", "is-full");
        card.classList.remove("is-on");
        d.removeEventListener("keydown", onKey, true);
        w.removeEventListener("resize", onReanchor);
        w.removeEventListener("scroll", onReanchor, true);
    }

    function complete() {
        if (replay) return;   /* already stamped — replays are client-only */
        try {
            fetch(cfg.completeUrl, {
                method: "POST", credentials: "same-origin", keepalive: true,
                headers: { "X-CSRFToken": csrf() }
            }).catch(function () {});
        } catch (e) { /* the tour must never break the page */ }
    }

    function finish() { stop(); complete(); }
    function skip() { stop(); complete(); }

    function next() {
        if (!active) return;
        if (idx >= cfg.steps.length - 1) { finish(); return; }
        idx += 1;
        render(1);
    }
    function prev() {
        if (!active) return;
        if (idx === 0) return;
        idx -= 1;
        render(-1);
    }

    function overlayOpen() {
        // An sv-overlay surface (bell menu, dialog, panel) that somehow
        // opened mid-tour owns Escape for one press — both listeners are
        // capture-phase on document and stopPropagation cannot silence a
        // sibling on the same node, so without this check one Escape
        // closed the overlay AND permanently stamped the tour complete.
        return !!d.querySelector("[data-sv-overlay].is-open");
    }

    function pinLocked() {
        // The idle lock owns the screen outright. This listener is
        // capture-phase on document and stops what it does not handle,
        // so without yielding here the lock screen lost Backspace, its
        // 4→8 box growth, and Enter (which ran next() instead of
        // verifying the PIN) — a 5-digit PIN became unenterable.
        return !!(w.svIdleLock && w.svIdleLock.isLocked());
    }

    function onKey(e) {
        if (!active || pinLocked()) return;
        // The tour owns the keyboard: without this, the app's bare-key
        // shortcuts (t theme, n mark-read, g goto, ?) fire mid-walk.
        if (e.key === "Escape") {
            if (overlayOpen()) return;   /* sv-overlay consumes this one */
            e.stopPropagation(); e.preventDefault(); skip(); return;
        }
        if (e.key === "Enter") {
            // Enter ACTIVATES the focused control — hijacking it to
            // next() made SKIP advance and the final-step links dead for
            // keyboard users. Only bare Enter (focus on NEXT or nothing
            // in particular) advances.
            var ae = d.activeElement;
            if (ae && card.contains(ae) && ae !== nextBtn) {
                e.stopPropagation();   /* let the control's default fire */
                return;
            }
            e.stopPropagation(); e.preventDefault(); next(); return;
        }
        if (e.key === "ArrowRight") { e.stopPropagation(); e.preventDefault(); next(); return; }
        if (e.key === "ArrowLeft") { e.stopPropagation(); e.preventDefault(); prev(); return; }
        if (e.key === "Tab") {
            // Keep focus inside the card — among VISIBLE controls only
            // (BACK is display:none on step 0 and focusing it no-ops,
            // which used to wedge Tab on SKIP and leak Shift+Tab out).
            var focusables = Array.prototype.filter.call(
                card.querySelectorAll("button, a[href]"),
                function (n) { return n.offsetParent !== null; });
            if (!focusables.length) return;
            var first = focusables[0], last = focusables[focusables.length - 1];
            if (e.shiftKey && d.activeElement === first) {
                e.preventDefault(); last.focus();
            } else if (!e.shiftKey && d.activeElement === last) {
                e.preventDefault(); first.focus();
            } else if (!card.contains(d.activeElement)) {
                e.preventDefault(); first.focus();
            }
            e.stopPropagation();
            return;
        }
        e.stopPropagation();
    }

    var reanchorPending = null;
    function onReanchor() {
        if (reanchorPending) return;
        reanchorPending = setTimeout(function () {
            reanchorPending = null;
            if (active) place(cfg.steps[idx], targetOf(cfg.steps[idx]));
        }, 80);
    }

    function start(opts) {
        replay = !!(opts && opts.replay);
        idx = 0;
        active = true;
        d.addEventListener("keydown", onKey, true);
        w.addEventListener("resize", onReanchor);
        w.addEventListener("scroll", onReanchor, true);
        render();
    }

    backBtn.addEventListener("click", prev);
    nextBtn.addEventListener("click", next);
    d.getElementById("svTourSkip").addEventListener("click", skip);
    spot.addEventListener("click", function (e) { e.stopPropagation(); });
    // The veil swallows every click on the dimmed page — the shadow that
    // PAINTS the scrim has no hit area of its own, and without this the
    // "dimmed" chrome stayed fully clickable (menus opened under the
    // scrim; a stray click navigated away un-stamped and the walk
    // restarted from step 1 on the next page).
    veil.addEventListener("click", function (e) {
        e.stopPropagation();
        e.preventDefault();
    });

    var replayBtn = d.getElementById("umReplayTour");
    if (replayBtn) {
        replayBtn.addEventListener("click", function () {
            // Close the user menu the button lives in, then walk.
            d.body.click();
            setTimeout(function () { start({ replay: true }); }, 60);
        });
    }

    w.SV = w.SV || {};
    w.SV.tour = { start: start };

    if (cfg.autostart) {
        // Let the layout and background canvases settle first. A locked
        // session is not the moment for a guided tour — it would steal
        // focus from the PIN pad and never reach /tour/complete/ anyway.
        var boot = function () {
            setTimeout(function () { if (!pinLocked()) start(); }, 700);
        };
        if (d.readyState === "loading") {
            d.addEventListener("DOMContentLoaded", boot);
        } else {
            boot();
        }
    }
})(window, document);
