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

    // The walk survives navigation: a step can declare the page it lives
    // on, and the spotlighted control is clickable, so either route leaves
    // the page mid-tour. Without a hand-off the tour would simply vanish
    // (or restart at step 1) the moment it did its job.
    var RESUME_KEY = "sv:tour:resume";

    function saveResume(at, navigated, dir) {
        try {
            sessionStorage.setItem(RESUME_KEY, JSON.stringify({
                at: at, replay: replay, navigated: !!navigated,
                // Direction of travel survives the page load too: arriving
                // on a step walked BACKWARDS whose target is missing must
                // keep going backwards, not turn around.
                dir: dir === -1 ? -1 : 1
            }));
        } catch (e) { /* private mode: the tour degrades to single-page */ }
    }
    function readResume() {
        try {
            var raw = sessionStorage.getItem(RESUME_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (e) { return null; }
    }
    function clearResume() {
        try { sessionStorage.removeItem(RESUME_KEY); } catch (e) {}
    }

    function samePage(url) {
        if (!url) return true;
        var here = w.location.pathname;
        return here === url || here === url.replace(/\/$/, "");
    }

    // Set when THIS page load is the result of the tour navigating for a
    // step. Without it a step whose url redirects (or whose page is
    // reachable under a different path) would navigate on every render
    // and the walk would loop instead of continuing.
    var arrivedFor = null;
    function navigatedFor(i) { return arrivedFor === i; }

    // Four panes fenced around the cutout — see sv-tour.css. The spot's
    // box-shadow paints the darkness; these carry the hit area, so the
    // highlighted control keeps its own hover, focus and click.
    var panes = [];
    (function buildPanes() {
        for (var i = 0; i < 4; i++) {
            var p = d.createElement("div");
            p.className = "sv-tour-pane";
            p.addEventListener("click", function (e) {
                e.stopPropagation();
                e.preventDefault();
            });
            veil.appendChild(p);
            panes.push(p);
        }
    })();

    function fencePanes(r) {
        // r is the spotlight rect in viewport coordinates, or null for the
        // centered steps, where the fence is one full-screen pane.
        var W = w.innerWidth, H = w.innerHeight;
        var box = r || { top: 0, left: 0, right: 0, bottom: 0 };
        var geo = r ? [
            { top: 0, left: 0, width: W, height: Math.max(0, box.top) },
            { top: Math.max(0, box.bottom), left: 0, width: W,
              height: Math.max(0, H - box.bottom) },
            { top: Math.max(0, box.top), left: 0,
              width: Math.max(0, box.left),
              height: Math.max(0, box.bottom - box.top) },
            { top: Math.max(0, box.top), left: Math.max(0, box.right),
              width: Math.max(0, W - box.right),
              height: Math.max(0, box.bottom - box.top) }
        ] : [
            { top: 0, left: 0, width: W, height: H },
            { top: 0, left: 0, width: 0, height: 0 },
            { top: 0, left: 0, width: 0, height: 0 },
            { top: 0, left: 0, width: 0, height: 0 }
        ];
        panes.forEach(function (p, i) {
            p.style.top = geo[i].top + "px";
            p.style.left = geo[i].left + "px";
            p.style.width = geo[i].width + "px";
            p.style.height = geo[i].height + "px";
        });
    }

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
            fencePanes(null);
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
        fencePanes({
            top: r.top - pad, left: r.left - pad,
            right: r.right + pad, bottom: r.bottom + pad
        });

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
        var step, el = null, guard = 0;
        // One loop for both jobs, because they feed each other: a step that
        // names a page is walked TO (pointing at a menu item and talking
        // about what lies behind it taught nothing the sidebar label did
        // not already say), and a step whose target this user cannot see is
        // skipped past — in the direction of travel, or BACK across a
        // hidden step bounces and every earlier step becomes unreachable.
        // Skipping used to jump straight to rendering, so a step skipped
        // INTO never walked to its own page and described it from the
        // wrong one.
        while (guard <= cfg.steps.length) {
            step = cfg.steps[idx];
            if (step.url && !samePage(step.url) && !navigatedFor(idx)) {
                saveResume(idx, true, direction);
                stop();
                w.location.assign(step.url);
                return;
            }
            el = targetOf(step);
            if (el || !step.sel) break;
            idx += direction;
            if (idx >= cfg.steps.length) { finish(); return; }
            if (idx < 0) { idx = 0; direction = 1; }
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
        d.body.classList.remove("sv-tour-on");
        if (placeTimer) { clearTimeout(placeTimer); placeTimer = null; }
        veil.classList.remove("is-on");
        spot.classList.remove("is-on", "is-full");
        card.classList.remove("is-on");
        d.removeEventListener("keydown", onKey, true);
        d.removeEventListener("click", onSpotlightClick, true);
        w.removeEventListener("resize", onReanchor);
        w.removeEventListener("scroll", onReanchor, true);
    }

    function complete() {
        // The card's own outbound links (OPEN SETUP, GETTING STARTED) call
        // this on the way out: the walk is over, so nothing may resume it
        // on the page they lead to.
        clearResume();
        if (replay) return;   /* already stamped — replays are client-only */
        try {
            fetch(cfg.completeUrl, {
                method: "POST", credentials: "same-origin", keepalive: true,
                headers: { "X-CSRFToken": csrf() }
            }).catch(function () {});
        } catch (e) { /* the tour must never break the page */ }
    }

    function finish() { clearResume(); stop(); complete(); }
    function skip() { clearResume(); stop(); complete(); }

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
        // A surface open mid-tour owns Escape for one press — both
        // listeners are capture-phase on document and stopPropagation
        // cannot silence a sibling on the same node, so without this check
        // one Escape closed the surface AND permanently stamped the tour
        // complete. The list is wider than [data-sv-overlay] because the
        // cutout now INVITES these open ("click the bell", "click the
        // eye") and the user menu and chat panel predate that attribute.
        return !!d.querySelector(
            "[data-sv-overlay].is-open, .user-menu.open .user-menu-dropdown,"
            + " .user-menu-dropdown.is-open, .se-chat-panel.open");
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
        opts = opts || {};
        replay = !!opts.replay;
        idx = typeof opts.at === "number" ? opts.at : 0;
        if (idx < 0 || idx >= cfg.steps.length) idx = 0;
        arrivedFor = opts.arrived ? idx : null;
        active = true;
        d.body.classList.add("sv-tour-on");
        d.addEventListener("keydown", onKey, true);
        d.addEventListener("click", onSpotlightClick, true);
        w.addEventListener("resize", onReanchor);
        w.addEventListener("scroll", onReanchor, true);
        render(opts.dir === -1 ? -1 : 1);
    }

    function onSpotlightClick(e) {
        // The cutout is live, so the operator can click the very thing the
        // card is describing. If that click leaves the page, hand the walk
        // over to the next load rather than letting it disappear.
        if (!active) return;
        var el = targetOf(cfg.steps[idx]);
        if (!el || !e.target || !el.contains(e.target)) return;
        var link = e.target.closest && e.target.closest("a[href]");
        if (!link) return;
        // A modified click opens a new tab and leaves THIS page exactly
        // where it is — stamping a hand-off would silently skip a step on
        // the next load here.
        if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
        if (link.target && link.target !== "_self") return;
        var href = link.getAttribute("href") || "";
        if (!href || href.charAt(0) === "#"
            || /^(javascript|mailto|tel):/i.test(href)) return;
        // After every other handler has had its say: one that cancelled
        // the navigation (an in-page router, a confirm guard) means this
        // page is staying, and a stale record would jump a step later.
        setTimeout(function () {
            if (e.defaultPrevented) return;
            // Resume on the step AFTER this one — the operator did what
            // the card asked — but NOT as an arrival: they went where they
            // chose, which says nothing about where the next step lives,
            // and claiming otherwise made that step describe its page from
            // whatever page this click landed on.
            saveResume(Math.min(idx + 1, cfg.steps.length - 1), false, 1);
        }, 0);
    }

    backBtn.addEventListener("click", prev);
    nextBtn.addEventListener("click", next);
    d.getElementById("svTourSkip").addEventListener("click", skip);
    // The panes swallow every click on the DIMMED page (see fencePanes) —
    // the shadow that paints the scrim has no hit area of its own, so
    // without them the dimmed chrome stayed fully clickable. The cutout
    // itself is deliberately live: that is the part the card is about.

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

    // A walk in progress outranks a fresh start: the operator either
    // clicked something the tour highlighted or the tour walked them to a
    // new page, and either way it resumes where it left off — never back
    // at step one, which is what made a cross-page tour impossible before.
    var resume = readResume();
    if (resume && typeof resume.at === "number") clearResume();

    if (resume || cfg.autostart) {
        // Let the layout and background canvases settle first. A locked
        // session is not the moment for a guided tour — it would steal
        // focus from the PIN pad and never reach /tour/complete/ anyway.
        var boot = function () {
            setTimeout(function () {
                if (pinLocked()) return;
                if (resume) {
                    start({ at: resume.at, replay: !!resume.replay,
                            arrived: !!resume.navigated, dir: resume.dir });
                } else {
                    start();
                }
            }, 700);
        };
        if (d.readyState === "loading") {
            d.addEventListener("DOMContentLoaded", boot);
        } else {
            boot();
        }
    }
})(window, document);
