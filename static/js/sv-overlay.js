/* sv-overlay.js — the one overlay controller.
 *
 * Before this file, every overlay on the platform brought its own handlers.
 * The notification bell toggled a class from an inline onclick and relied on a
 * document listener to close it. The user menu had its own Escape key. The Ask
 * Sauron panel had another. The keyboard-shortcuts modal had a third. The two
 * backtest modals and the add-user modal had none — no Escape, no focus, no
 * scroll lock. Nothing knew about anything else, so two overlays could sit open
 * on top of each other with the operator unable to tell which one had focus,
 * and Escape would close whichever one happened to have registered last.
 *
 * That is the whole problem this file exists to end. One controller owns
 * opening, closing, stacking, the backdrop, the scroll lock, focus movement,
 * focus restoration, the focus trap, and dismissal. An overlay declares what
 * KIND it is and gets the correct behaviour for that kind for free.
 *
 * Markup contract
 * ---------------
 *   <div id="x" data-sv-overlay="dialog">…</div>     the overlay itself
 *   <button data-sv-open="x">…</button>              anything that opens it
 *   <button data-sv-close>…</button>                 anything inside that closes it
 *
 * Kinds
 * -----
 *   menu    a dropdown hanging off a trigger. Closes on outside click and on
 *           Escape. Only one menu is ever open — opening a second closes the
 *           first, because two open menus is always a bug, never a feature.
 *           No backdrop, no scroll lock: a menu is not a mode.
 *   dialog  a centred modal. Backdrop, scroll lock, focus moved in and trapped,
 *           focus restored to the trigger on close. Escape and backdrop click
 *           dismiss it unless it is marked data-sv-persist.
 *   panel   an edge-anchored sheet. Like a dialog but does not lock scroll by
 *           default, because a panel is meant to be used alongside the page.
 *
 * Modifiers
 * ---------
 *   data-sv-persist        Escape and backdrop click do NOT dismiss. For a
 *                          dialog reporting something the operator must act on.
 *   data-sv-backdrop="#id" use this existing element as the backdrop instead of
 *                          the shared one. This is what lets the older modals
 *                          keep their own markup while still being controlled.
 *   data-sv-focus="sel"    move focus here on open instead of the first control.
 *   data-sv-lock           force the scroll lock on (for a panel).
 *
 * Events
 * ------
 *   sv:open / sv:close fire on the overlay element and bubble, so a page can
 *   lazy-load a heavy body only when its overlay is actually opened.
 */
(function (w, d) {
    "use strict";

    /* Stacking lives in CSS, not here. The controller only publishes how deep
     * in the stack an overlay is, as --sv-stack, and the ladder in sauron.css
     * resolves that against the right base for the overlay's kind:
     *
     *     z-index: calc(var(--z-dialog) + var(--sv-stack, 0));
     *
     * Two things fall out of that. Order of opening decides order of painting,
     * so a dialog opened from a dialog is always on top. And the ladder itself
     * stays in one readable block of CSS instead of being split between a
     * stylesheet and a script that have to be kept in agreement — which is how
     * this platform ended up with modals at both 1000 and 9999, hover cards at
     * both 1000 and 2147483000, and event banners underneath both. */

    var FOCUSABLE = [
        'a[href]', 'button:not([disabled])',
        'input:not([disabled]):not([type="hidden"])',
        'select:not([disabled])', 'textarea:not([disabled])',
        '[tabindex]:not([tabindex="-1"])'
    ].join(',');

    var stack = [];          /* open overlays, bottom of the stack first */
    var sharedBackdrop = null;
    var scrollbarPad = null;

    /* ── helpers ─────────────────────────────────────────────────────── */

    function kindOf(el) {
        return el.getAttribute("data-sv-overlay") || "dialog";
    }

    function isModal(el) {
        var k = kindOf(el);
        return k === "dialog" || k === "panel";
    }

    function locksScroll(el) {
        if (el.hasAttribute("data-sv-lock")) return true;
        return kindOf(el) === "dialog";
    }

    function entryFor(el) {
        for (var i = 0; i < stack.length; i++) {
            if (stack[i].el === el) return stack[i];
        }
        return null;
    }

    function focusables(el) {
        var out = [];
        var nodes = el.querySelectorAll(FOCUSABLE);
        for (var i = 0; i < nodes.length; i++) {
            var n = nodes[i];
            /* offsetParent is null for display:none subtrees, which is exactly
             * the set we must not try to focus. */
            if (n.offsetParent !== null || n === d.activeElement) out.push(n);
        }
        return out;
    }

    /* ── portalling ──────────────────────────────────────────────────────
     * The only way out of a stacking context is to leave it. `position:
     * fixed` does NOT escape one — a fixed element still paints inside its
     * ancestor's context — which is why the topbar menus were stuck behind
     * the signals rail no matter what z-index they declared: .topbar carries
     * backdrop-filter, and that creates a stacking context on its own.
     *
     * So an overlay marked data-sv-portal is physically moved to <body> when
     * it opens, anchored to its trigger in viewport coordinates, and put back
     * where it came from when it closes. Putting it back matters: htmx swaps
     * and Django partials both re-render by parent, and an overlay orphaned
     * on <body> would survive as a duplicate.
     */
    function anchor(el, trigger) {
        if (!trigger || !trigger.getBoundingClientRect) return;
        var r = trigger.getBoundingClientRect();
        var gap = 8, edge = 8;
        var w = el.offsetWidth, h = el.offsetHeight;

        /* Right-aligned to the trigger, because these hang off the top-right
         * chrome and a left-aligned menu would run off the screen. */
        var vw = window.innerWidth || d.documentElement.clientWidth;
        var left = r.right - w;
        var maxLeft = vw - w - edge;
        if (left > maxLeft) left = maxLeft;
        if (left < edge) left = edge;

        var vh = window.innerHeight || d.documentElement.clientHeight;
        var top = r.bottom + gap;
        /* Flip above the trigger rather than hang off the bottom. */
        if (top + h > vh - edge) {
            var above = r.top - h - gap;
            top = above >= edge ? above : Math.max(edge, vh - h - edge);
        }
        el.style.left = Math.round(left) + "px";
        el.style.top = Math.round(top) + "px";
    }

    function portalOut(el, trigger) {
        if (!el.hasAttribute("data-sv-portal")) return;
        el._svHome = { parent: el.parentNode, next: el.nextSibling };
        d.body.appendChild(el);
        el.style.position = "fixed";
        anchor(el, trigger);
        el._svAnchor = function () { anchor(el, trigger); };
        window.addEventListener("resize", el._svAnchor);
        /* Capture phase: the trigger may sit inside a scrolling region. */
        window.addEventListener("scroll", el._svAnchor, true);
    }

    function portalHome(el) {
        if (!el._svHome) return;
        if (el._svAnchor) {
            window.removeEventListener("resize", el._svAnchor);
            window.removeEventListener("scroll", el._svAnchor, true);
            el._svAnchor = null;
        }
        var home = el._svHome;
        el._svHome = null;
        el.style.position = "";
        el.style.left = "";
        el.style.top = "";
        if (home.parent && d.contains(home.parent)) {
            home.parent.insertBefore(el, home.next);
        }
    }

    function backdropFor(el) {
        var sel = el.getAttribute("data-sv-backdrop");
        /* Some dialogs ARE their own scrim: a full-viewport `inset: 0` box
         * that centres its panel with flex. Those must not also get the
         * shared backdrop, or the page is dimmed twice. */
        if (sel === "none") return null;
        if (sel) return d.querySelector(sel);
        if (!sharedBackdrop) {
            sharedBackdrop = d.createElement("div");
            sharedBackdrop.className = "sv-backdrop";
            sharedBackdrop.setAttribute("aria-hidden", "true");
            d.body.appendChild(sharedBackdrop);
        }
        return sharedBackdrop;
    }

    /* The scroll lock compensates for the scrollbar it removes. Without the
     * padding the entire page shifts sideways the instant a modal opens, which
     * reads as a glitch and moves whatever the operator was about to click. */
    function lockScroll() {
        if (scrollbarPad !== null) return;
        var gap = w.innerWidth - d.documentElement.clientWidth;
        scrollbarPad = d.body.style.paddingRight;
        if (gap > 0) d.body.style.paddingRight = gap + "px";
        d.body.classList.add("sv-scroll-locked");
    }

    function unlockScroll() {
        if (scrollbarPad === null) return;
        d.body.style.paddingRight = scrollbarPad;
        scrollbarPad = null;
        d.body.classList.remove("sv-scroll-locked");
    }

    function anyModalOpen() {
        for (var i = 0; i < stack.length; i++) {
            if (locksScroll(stack[i].el)) return true;
        }
        return false;
    }

    function emit(el, name, detail) {
        var ev;
        try {
            ev = new CustomEvent(name, { bubbles: true, detail: detail || {} });
        } catch (e) {                       /* older engines */
            ev = d.createEvent("CustomEvent");
            ev.initCustomEvent(name, true, false, detail || {});
        }
        el.dispatchEvent(ev);
    }

    function resolve(target) {
        if (!target) return null;
        if (typeof target === "string") {
            return d.getElementById(target) || d.querySelector(target);
        }
        return target;
    }

    /* ── open / close ────────────────────────────────────────────────── */

    function open(target, trigger) {
        var el = resolve(target);
        if (!el || entryFor(el)) return el;

        /* Two open menus is always a bug. Opening any overlay also closes every
         * open menu, so a dropdown can never be left hanging behind a dialog. */
        closeMenus();

        var depth = stack.length;
        var modal = isModal(el);
        var bd = modal ? backdropFor(el) : null;

        if (bd) {
            bd.style.setProperty("--sv-stack", String(depth));
            bd.classList.add("is-open");
        }
        el.style.setProperty("--sv-stack", String(depth));
        el.classList.add("is-open");
        el.removeAttribute("hidden");
        /* After is-open, so the element has been laid out and offsetWidth /
         * offsetHeight are real numbers to anchor against. */
        portalOut(el, trigger);

        if (modal) {
            el.setAttribute("role", el.getAttribute("role") || "dialog");
            el.setAttribute("aria-modal", "true");
        }
        if (trigger && trigger.setAttribute) {
            trigger.setAttribute("aria-expanded", "true");
        }
        if (locksScroll(el)) lockScroll();

        stack.push({
            el: el, trigger: trigger || null, backdrop: bd,
            restore: d.activeElement
        });

        /* Focus goes into the overlay so the keyboard follows the eye. For a
         * menu that only happens when it was opened from the keyboard — moving
         * focus on a mouse click would scroll the page under the pointer. */
        var wants = el.getAttribute("data-sv-focus");
        var first = wants ? el.querySelector(wants) : focusables(el)[0];
        if (modal) {
            if (first) {
                first.focus();
            } else {
                if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
                el.focus();
            }
        } else if (first && trigger && trigger.dataset && trigger.dataset.svKeyboard === "1") {
            first.focus();
        }

        emit(el, "sv:open", { trigger: trigger || null });
        return el;
    }

    function close(target) {
        var el = resolve(target);
        if (!el) return;
        var idx = -1;
        for (var i = 0; i < stack.length; i++) {
            if (stack[i].el === el) { idx = i; break; }
        }
        if (idx === -1) return;

        var entry = stack[idx];
        stack.splice(idx, 1);

        el.classList.remove("is-open");
        el.style.removeProperty("--sv-stack");
        el.removeAttribute("aria-modal");
        portalHome(el);

        /* Only hide the backdrop if nothing else is still using it. */
        if (entry.backdrop) {
            var stillUsed = false;
            for (var j = 0; j < stack.length; j++) {
                if (stack[j].backdrop === entry.backdrop) { stillUsed = true; break; }
            }
            if (!stillUsed) {
                entry.backdrop.classList.remove("is-open");
                entry.backdrop.style.removeProperty("--sv-stack");
            }
        }
        if (entry.trigger && entry.trigger.setAttribute) {
            entry.trigger.setAttribute("aria-expanded", "false");
        }
        if (!anyModalOpen()) unlockScroll();

        /* Focus goes back where it came from. Losing it to <body> is how a
         * keyboard operator gets stranded at the top of the document. */
        var back = entry.trigger || entry.restore;
        if (back && back.focus && d.contains(back)) {
            try { back.focus(); } catch (e) { /* detached */ }
        }

        emit(el, "sv:close", {});
    }

    function closeMenus() {
        for (var i = stack.length - 1; i >= 0; i--) {
            if (kindOf(stack[i].el) === "menu") close(stack[i].el);
        }
    }

    function closeTop() {
        if (!stack.length) return;
        var top = stack[stack.length - 1];
        if (top.el.hasAttribute("data-sv-persist")) return;
        close(top.el);
    }

    function closeAll() {
        for (var i = stack.length - 1; i >= 0; i--) close(stack[i].el);
    }

    function toggle(target, trigger) {
        var el = resolve(target);
        if (!el) return;
        if (entryFor(el)) close(el); else open(el, trigger);
    }

    /* ── global listeners ────────────────────────────────────────────── */

    d.addEventListener("keydown", function (e) {
        if (!stack.length) return;

        if (e.key === "Escape" || e.key === "Esc") {
            var top = stack[stack.length - 1];
            if (top.el.hasAttribute("data-sv-persist")) return;
            e.preventDefault();
            e.stopPropagation();
            close(top.el);
            return;
        }

        /* Trap Tab inside the topmost modal. A modal you can Tab out of is a
         * modal the keyboard operator can lose. */
        if (e.key === "Tab") {
            var el = stack[stack.length - 1].el;
            if (!isModal(el)) return;
            var f = focusables(el);
            if (!f.length) { e.preventDefault(); return; }
            var first = f[0], last = f[f.length - 1];
            if (e.shiftKey && (d.activeElement === first || !el.contains(d.activeElement))) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && d.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }
    }, true);

    d.addEventListener("click", function (e) {
        var t = e.target;

        var closer = t.closest && t.closest("[data-sv-close]");
        if (closer) {
            var owned = closer.closest("[data-sv-overlay]");
            e.preventDefault();
            close(owned || closer.getAttribute("data-sv-close"));
            return;
        }

        var opener = t.closest && t.closest("[data-sv-open]");
        if (opener) {
            e.preventDefault();
            /* detail === 0 means the click came from the keyboard, which is
             * when moving focus into a menu is the right thing to do. */
            if (opener.dataset) opener.dataset.svKeyboard = e.detail === 0 ? "1" : "0";
            toggle(opener.getAttribute("data-sv-open"), opener);
            return;
        }

        if (!stack.length) return;
        var top = stack[stack.length - 1];

        /* A click on the backdrop, or anywhere outside a menu, dismisses. */
        if (top.backdrop && t === top.backdrop) {
            if (!top.el.hasAttribute("data-sv-persist")) close(top.el);
            return;
        }
        /* Self-scrim dialogs: the overlay element covers the viewport and
         * centres its own panel, so "outside the dialog" means a click that
         * landed on the overlay itself rather than on anything within it. */
        if (t === top.el && isModal(top.el)) {
            if (!top.el.hasAttribute("data-sv-persist")) close(top.el);
            return;
        }
        if (top.el.contains(t)) return;
        if (top.trigger && top.trigger.contains && top.trigger.contains(t)) return;
        if (kindOf(top.el) === "menu") close(top.el);
    }, false);

    /* An overlay whose markup is inside the region htmx is about to replace
     * would otherwise be destroyed while still on the stack, leaving the page
     * scroll-locked behind a backdrop with nothing to close. */
    d.addEventListener("htmx:beforeSwap", function (e) {
        for (var i = stack.length - 1; i >= 0; i--) {
            var el = stack[i].el;
            if (!d.contains(el) || (e.target && e.target.contains && e.target.contains(el))) {
                close(el);
            }
        }
    });

    /* ── promise dialogs: the replacement for confirm() and alert() ───── */

    function esc(v) {
        return String(v === undefined || v === null ? "" : v)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;")
            .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    /* window.confirm() cannot show the thing being destroyed, cannot be styled,
     * blocks the page, and gives the operator nothing to decide with. On a
     * trading platform the guarded actions are things like disarming a bot or
     * force-closing a position, where the details ARE the decision. */
    function ask(opts) {
        opts = opts || {};
        return new Promise(function (done) {
            var host = d.createElement("div");
            host.className = "sv-dialog" + (opts.danger ? " sv-dialog--danger" : "");
            host.setAttribute("data-sv-overlay", "dialog");
            host.setAttribute("aria-labelledby", "svDlgTitle");

            var facts = "";
            if (opts.facts && opts.facts.length) {
                for (var i = 0; i < opts.facts.length; i++) {
                    var f = opts.facts[i];
                    facts += '<div class="sv-dialog-fact"><span class="lbl">' +
                        esc(f[0]) + "</span><span>" + esc(f[1]) + "</span></div>";
                }
                facts = '<div class="sv-dialog-facts">' + facts + "</div>";
            }

            var typed = opts.requireText
                ? '<label class="sv-dialog-confirm-text">Type <b>' + esc(opts.requireText) +
                  '</b> to confirm<input type="text" autocomplete="off" spellcheck="false"></label>'
                : "";

            /* A secret the SERVER must verify — the trading PIN. requireText
             * cannot carry one: that input is compared in the browser against
             * a string the browser already knows, which is deliberate
             * friction, not a credential. With `secretLabel` set the promise
             * resolves to the typed VALUE instead of `true`; callers that
             * never ask for one keep the boolean they have always had. */
            var secretHtml = opts.secretLabel
                ? '<label class="sv-dialog-confirm-text" data-role="secret-wrap">' +
                  esc(opts.secretLabel) +
                  '<input type="password" inputmode="numeric" autocomplete="off" ' +
                  'spellcheck="false" data-role="secret"></label>'
                : "";

            host.innerHTML =
                '<div class="sv-dialog-head">' +
                  '<span class="sv-dialog-title" id="svDlgTitle">' + esc(opts.title || "Confirm") + "</span>" +
                  '<button type="button" class="sv-dialog-x" data-sv-close aria-label="Cancel">&times;</button>' +
                "</div>" +
                '<div class="sv-dialog-body">' +
                  (opts.message ? '<p class="sv-dialog-msg">' + esc(opts.message) + "</p>" : "") +
                  facts +
                  (opts.detail ? '<p class="sv-dialog-detail">' + esc(opts.detail) + "</p>" : "") +
                  typed + secretHtml +
                "</div>" +
                '<div class="sv-dialog-foot">' +
                  (opts.alert ? "" :
                    '<button type="button" class="sv-dialog-btn" data-role="cancel">' +
                    esc(opts.cancelLabel || "Cancel") + "</button>") +
                  '<button type="button" class="sv-dialog-btn sv-dialog-btn--go' +
                    (opts.danger ? " is-danger" : "") + '" data-role="ok">' +
                    esc(opts.confirmLabel || (opts.alert ? "OK" : "Confirm")) + "</button>" +
                "</div>";

            d.body.appendChild(host);

            var okBtn = host.querySelector('[data-role="ok"]');
            var secretInput = host.querySelector('[data-role="secret"]');
            var input = opts.requireText
                ? host.querySelector(".sv-dialog-confirm-text input")
                : null;
            var settled = false;

            /* Both gates in one place: an empty PIN box must disable the
             * button exactly as an unmatched requireText does, or the
             * operator sends a blank credential and reads the server's
             * refusal as "the close is broken". */
            function sync() {
                var ok = true;
                if (input && input.value.trim() !== opts.requireText) ok = false;
                if (secretInput && !secretInput.value) ok = false;
                okBtn.disabled = !ok;
            }
            if (input) input.addEventListener("input", sync);
            if (secretInput) secretInput.addEventListener("input", sync);
            if (input || secretInput) sync();

            function finish(v) {
                if (settled) return;
                settled = true;
                close(host);
                done(v);
            }

            host.addEventListener("sv:close", function () {
                if (!settled) { settled = true; done(false); }
                setTimeout(function () {
                    if (host.parentNode) host.parentNode.removeChild(host);
                }, 200);
            });

            okBtn.addEventListener("click", function () {
                finish(secretInput ? secretInput.value : true);
            });
            var cancel = host.querySelector('[data-role="cancel"]');
            if (cancel) cancel.addEventListener("click", function () { finish(false); });

            /* The dangerous button is never the one focus lands on: a stray
             * Enter must not be able to disarm anything. */
            if (!opts.danger && !input && !secretInput) {
                host.setAttribute("data-sv-focus", '[data-role="ok"]');
            }
            open(host, null);
            if (input) input.focus();
            else if (secretInput) secretInput.focus();
        });
    }

    /* ── live ages ───────────────────────────────────────────────────────
     * A server-rendered age is a snapshot that stops being true the moment it
     * is painted. The ticker popups decide "STALE" at render time against a
     * 900-second threshold, so a dashboard left open for an hour with a dead
     * feed still reads "just now" and the STALE chip can never appear — the
     * one state the operator needs to see is the one that cannot happen.
     *
     * Anything carrying data-sv-at="<ISO 8601>" gets its age rewritten here
     * every fifteen seconds, and crosses into stale and then dead on its own.
     */
    var STALE_AFTER = 900;      /* 15 min — matches the server-side rule */
    var DEAD_AFTER = 3600;

    function humanAge(seconds) {
        if (seconds < 45) return "just now";
        if (seconds < 3600) return Math.round(seconds / 60) + "m ago";
        if (seconds < 86400) return Math.round(seconds / 3600) + "h ago";
        return Math.round(seconds / 86400) + "d ago";
    }

    function refreshAges() {
        var nodes = d.querySelectorAll("[data-sv-at]");
        var now = Date.now();
        for (var i = 0; i < nodes.length; i++) {
            var el = nodes[i];
            var at = Date.parse(el.getAttribute("data-sv-at"));
            if (isNaN(at)) continue;
            var age = Math.max(0, (now - at) / 1000);

            el.textContent = humanAge(age);
            el.classList.toggle("sv-age--stale", age >= STALE_AFTER && age < DEAD_AFTER);
            el.classList.toggle("sv-age--dead", age >= DEAD_AFTER);

            /* Let the surrounding card mark itself, so a stale quote can be
               shown as stale in its entirety rather than in one corner. */
            var owner = el.closest("[data-sv-staleable]");
            if (owner) owner.classList.toggle("is-stale", age >= STALE_AFTER);
        }
    }

    d.addEventListener("htmx:afterSwap", refreshAges);
    setInterval(refreshAges, 15000);
    if (d.readyState === "loading") {
        d.addEventListener("DOMContentLoaded", refreshAges);
    } else {
        refreshAges();
    }

    w.SV = w.SV || {};
    w.SV.ages = { refresh: refreshAges };
    w.SV.overlay = {
        open: open, close: close, toggle: toggle,
        closeTop: closeTop, closeAll: closeAll, closeMenus: closeMenus,
        isOpen: function (t) { return !!entryFor(resolve(t)); },
        confirm: ask,
        alert: function (o) {
            o = o || {};
            o.alert = true;
            return ask(o);
        }
    };
})(window, document);
