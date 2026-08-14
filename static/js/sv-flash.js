/* sv-flash.js — show the operator which number just moved.
 *
 * Most of this platform refreshes itself. Metric strips, position tables, the
 * bot console and the portfolio cards all repoll on a timer and swap their
 * markup in place. Until now that happened completely silently: a number could
 * change under the operator's eyes and nothing marked it, so the only way to
 * notice a move was to have memorised the previous value. On a page with forty
 * numbers on it, nobody does.
 *
 * So every refresh briefly lights the cells that actually changed — green when
 * the value rose, red when it fell, neutral when it changed but is not a
 * quantity that can rise or fall. It is deliberately faint and short: this is
 * peripheral vision work. If it were loud enough to read, a busy page would
 * strobe every thirty seconds and the operator would learn to ignore it, which
 * is the opposite of the point.
 *
 * How a value is identified across a swap
 * ---------------------------------------
 * The obvious approach — remember the Nth cell — breaks the moment a table
 * re-sorts, and then every row flashes because every row "changed". So a row
 * inside a tbody is keyed by the text of its first cell (the symbol, the rule
 * name, the id) rather than by its position, and cells are keyed by column
 * within that. A re-sorted table flashes nothing, which is correct: no value
 * changed, they only moved.
 *
 * Everything else is keyed by its path from the nearest ancestor with an id,
 * which is stable for the metric cards and strips that make up most of the UI.
 */
(function (w, d) {
    "use strict";

    var DURATION = 1100;          /* must outlast the CSS animation */
    var MAX_LEN = 28;             /* longer than this is prose, not a value */
    var snapshot = Object.create(null);
    var armed = false;            /* nothing flashes on first paint */

    /* Text that changes on its own schedule and would otherwise flash forever:
     * clocks, relative timestamps, countdowns. A thing that flashes every tick
     * teaches the eye to ignore flashing. */
    var NOISE = /\b(ago|just now|in \d|remaining|left)\b/i;

    function isNoise(el, text) {
        if (NOISE.test(text)) return true;
        if (el.id === "clock") return true;
        return !!(el.closest && el.closest("[data-sv-noflash],#clock,.sv-banner,#svBannerStack,.ticker-track"));
    }

    /* A leaf carrying something numeric. Anything with element children is a
     * container: flashing it would light up a whole card instead of the one
     * figure inside it that moved. */
    function isValue(el) {
        if (el.children.length) return false;
        var t = (el.textContent || "").trim();
        if (!t || t.length > MAX_LEN) return false;
        if (!/[0-9]/.test(t)) return false;
        return !isNoise(el, t);
    }

    function firstCellText(tr) {
        var c = tr.cells && tr.cells[0];
        return c ? (c.textContent || "").trim().slice(0, 40) : "";
    }

    function keyOf(el) {
        var parts = [];
        var node = el;
        while (node && node !== d.body) {
            if (node.id) { parts.unshift("#" + node.id); break; }

            var parent = node.parentNode;
            if (!parent || parent.nodeType !== 1) break;

            if (node.tagName === "TR" && parent.tagName === "TBODY") {
                /* Identity, not position — so a re-sort is not a change. */
                parts.unshift("tr@" + firstCellText(node));
            } else {
                var i = 0, sib = node;
                while ((sib = sib.previousElementSibling)) {
                    if (sib.tagName === node.tagName) i++;
                }
                parts.unshift(node.tagName + i);
            }
            node = parent;
        }
        return parts.join(">");
    }

    /* Pull a comparable number out of "€12,480.55", "-3.42%", "+1.2R", "18/24".
     * Returns null when the text is not a single quantity, in which case a
     * change is still worth marking but has no direction. */
    function numberOf(text) {
        var cleaned = text.replace(/[\s, ]/g, "");
        var m = cleaned.match(/^[^0-9+\-.]*([+-]?\d*\.?\d+)/);
        if (!m) return null;
        if (/\d\s*[\/:]\s*\d/.test(text)) return null;   /* 18/24, 3:1 — a ratio, not a level */
        var n = parseFloat(m[1]);
        return isNaN(n) ? null : n;
    }

    function collect() {
        var out = [];
        var nodes = d.querySelectorAll(
            "td,th,span,strong,b,div.dv,div.oc-strip-value,.stat-value,.metric-value");
        for (var i = 0; i < nodes.length; i++) {
            if (isValue(nodes[i])) out.push(nodes[i]);
        }
        return out;
    }

    function take() {
        var next = Object.create(null);
        var els = collect();
        for (var i = 0; i < els.length; i++) {
            next[keyOf(els[i])] = (els[i].textContent || "").trim();
        }
        return next;
    }

    function flash(el, dir) {
        var cls = "sv-flash sv-flash--" + dir;
        el.classList.remove("sv-flash", "sv-flash--up", "sv-flash--down", "sv-flash--same");
        /* Reading offsetWidth restarts the animation when the same cell moves
         * twice inside one flash window. */
        void el.offsetWidth;
        el.className = el.className + " " + cls;
        if (el._svFlashTimer) clearTimeout(el._svFlashTimer);
        el._svFlashTimer = setTimeout(function () {
            el.classList.remove("sv-flash", "sv-flash--up", "sv-flash--down", "sv-flash--same");
            el._svFlashTimer = null;
        }, DURATION);
    }

    function scan() {
        var els = collect();
        var next = Object.create(null);
        var changed = [];
        var tracked = 0;
        var i;

        for (i = 0; i < els.length; i++) {
            var el = els[i];
            var key = keyOf(el);
            var text = (el.textContent || "").trim();
            next[key] = text;

            if (!armed) continue;
            var was = snapshot[key];
            if (was === undefined) continue;
            tracked++;
            if (was !== text) changed.push([el, was, text]);
        }

        /* Changing a tab or a filter replaces the whole region, so every value
         * on screen is different and every one of them would flash. That is a
         * navigation, not a market move — the operator asked for new numbers
         * and knows they are new. Re-baseline silently instead of strobing.
         * A genuine refresh moves a handful of figures, never most of them. */
        var wholesale = tracked >= 8 && changed.length > tracked * 0.4;

        if (!wholesale) {
            for (i = 0; i < changed.length; i++) {
                var a = numberOf(changed[i][1]), b = numberOf(changed[i][2]);
                flash(changed[i][0],
                      (a === null || b === null) ? "same" : (b > a ? "up" : (b < a ? "down" : "same")));
            }
        }

        snapshot = next;
        armed = true;
    }

    /* Any htmx swap can change a value, wherever on the page it lands. Scanning
     * the whole document rather than just the swapped subtree costs a couple of
     * milliseconds and means a partial that updates a figure in the headband
     * still lights it. */
    d.addEventListener("htmx:afterSwap", function () {
        w.requestAnimationFrame(scan);
    });

    d.addEventListener("DOMContentLoaded", function () {
        snapshot = take();
        armed = true;
    });
    if (d.readyState !== "loading") {
        snapshot = take();
        armed = true;
    }

    w.SV = w.SV || {};
    w.SV.flash = {
        scan: scan,
        /* For updates that do not come through htmx — a websocket tick, or a
         * value a page rewrites itself. */
        mark: function (el, dir) {
            if (el) flash(el, dir || "same");
        },
        /* Re-baseline without flashing: use after replacing a whole region for
         * a reason that is not a data change, e.g. switching tabs or filters,
         * where every value is "new" but nothing has actually moved. */
        rebase: function () {
            snapshot = take();
            armed = true;
        }
    };
})(window, document);
