/* ── Notification detail card ─────────────────────────────────────────────
 * A notification row is a headline, not the notification: the bell cuts the
 * body at 110 characters, the kind is a chip, the age is rounded to the
 * minute, and a payload naming seven instruments can still only link to one
 * page. This is the rest of it. A 2s dwell on a row — in the bell panel or
 * in the inbox — raises a card with the full title, the untruncated body,
 * the kind, the exact timestamp, and one link per data.items entry.
 *
 * Same dwell/placement engine as the news feed and the briefing history,
 * reusing their .nf-pop chrome so the three previews read as one family,
 * and carrying the fixes those two already paid for:
 *   · delegated from document, never from the list — the bell panel is
 *     portalled in and out of <body> on every open, and htmx swaps the
 *     inbox, so a listener bound to the container dies with it;
 *   · a pop.contains(relatedTarget) guard plus the card's own pointerleave,
 *     or the card vanishes in the gap the pointer crosses to reach it;
 *   · a collapsed-selection check before any navigation, or finishing a
 *     text selection inside a row navigates away from what was selected.
 *
 * Placement has one rule the other two do not need. Inside the bell the row
 * lives in a portalled MENU, and --z-hovercard sits BELOW --z-menu on the
 * overlay ladder: a card placed under the row the way the news feed places
 * its own would be painted behind the panel. Rows inside an overlay get
 * their card beside that overlay instead, where the ladder never comes up.
 */
(function (w, d) {
    "use strict";

    var ROW = "[data-nc-row]";
    var HOVER_DELAY_MS = 2000, GAP = 8;

    if (!d.querySelector) return;

    /* Touch: sv-overlay.css hides every hover card at (hover: none), so the
     * dwell can never fire there. A tap must then do the one thing left —
     * open the page — for the inbox rows, which are divs and would
     * otherwise swallow the tap. Bell rows are anchors and navigate on
     * their own, which is why anything inside a link or button is left
     * alone here. */
    if (w.matchMedia && !w.matchMedia("(hover: hover)").matches) {
        d.addEventListener("click", function (e) {
            if (!e.target.closest) return;
            var row = e.target.closest(ROW);
            if (!row || !row.dataset.ncHref) return;
            if (e.target.closest("a, button")) return;
            if (w.getSelection && !w.getSelection().isCollapsed) return;
            w.location.assign(row.dataset.ncHref);
        });
        return;
    }

    var pop = d.createElement("div");
    pop.className = "nf-pop nc-pop";
    /* Hidden from assistive tech on purpose: every fact on this card is
     * already on the inbox page, which is where the keyboard path goes. */
    pop.setAttribute("aria-hidden", "true");
    d.body.appendChild(pop);

    var timer = null, current = null, suppressed = null;

    function el(parent, tag, cls, text) {
        if (!text) return null;
        var node = d.createElement(tag);
        node.className = cls;
        node.textContent = text;
        parent.appendChild(node);
        return node;
    }

    /* The structured payload rides as a <script type="application/json">
     * inside the row (Django's json_script — escaped by the server, never
     * built by hand here). Parsed once per row: a malformed payload from a
     * producer must cost one card, not every card after it. */
    function itemsOf(row) {
        if (row._ncItems) return row._ncItems;
        var out = [];
        var tag = row.querySelector('script[type="application/json"]');
        if (tag) {
            try {
                var parsed = JSON.parse(tag.textContent);
                if (parsed && Array.isArray(parsed.items)) out = parsed.items;
            } catch (err) { out = []; }
        }
        row._ncItems = out;
        return out;
    }

    /* Producer-supplied urls reach an href here, so only the two shapes a
     * notification is allowed to point at get through: a path on this site
     * or an absolute http(s) source. "javascript:" and friends are dropped
     * and the item renders as plain text. */
    function safeHref(url) {
        var u = (url === undefined || url === null ? "" : String(url)).trim();
        if (!u) return "";
        if (u.charAt(0) === "/" && u.charAt(1) !== "/") return u;
        if (/^https?:\/\//i.test(u)) return u;
        return "";
    }

    function build(row) {
        var ds = row.dataset;
        pop.textContent = "";
        el(pop, "div", "nf-pop-title", ds.ncTitle || "Notification");
        el(pop, "div", "nf-pop-meta",
           [ds.ncKind, ds.ncAt].filter(Boolean).join(" · "));
        /* pre-line, because bodies arrive as written: the bot fill summary
         * and the anomaly alert both use line breaks as their structure. */
        el(pop, "div", "nf-pop-summary nf-pop-summary--pre",
           ds.ncBody || "No body — the title is the whole notification.");

        var items = itemsOf(row);
        if (items.length) {
            var list = d.createElement("div");
            list.className = "nf-pop-items";
            items.forEach(function (it) {
                var href = safeHref(it && it.url);
                var node = d.createElement(href ? "a" : "div");
                node.className = "nf-pop-item";
                if (href) node.href = href;
                var label = d.createElement("span");
                label.className = "nfi-label";
                /* Em-dash, never a fabricated blank: an item the producer
                 * could not name is a gap, and it must read as one. */
                label.textContent = (it && it.label) || "—";
                node.appendChild(label);
                var detail = d.createElement("span");
                detail.className = "nfi-detail";
                detail.textContent = (it && it.detail) || "—";
                node.appendChild(detail);
                list.appendChild(node);
            });
            pop.appendChild(list);
        }

        el(pop, "div", "nf-pop-cta",
           items.length ? "click a line to open it"
                        : (ds.ncHref ? "click to open its page"
                                     : "no page for this one — this is all of it"));
    }

    /* The viewport minus the fixed chrome: a card clamped to the raw
     * viewport top would paint BEHIND the topbar (z-menu beats
     * z-hovercard). Measured per placement — the bars collapse. */
    function chromeBounds() {
        var vh = d.documentElement.clientHeight;
        var top = 0, bottom = vh;
        d.querySelectorAll(
            /* .info-panel-wrap, not ".info-bar" — the latter is a class
             * that exists nowhere in the project (an HTML comment reading
             * "Info Bar" is the likely source, and the news-feed engine
             * this was cloned from carries the same typo), so the bottom
             * chrome was never excluded and the card could land under it. */
            ".topbar, .ticker-bar, .data-headband, .info-panel-wrap"
        ).forEach(function (bar) {
            if (getComputedStyle(bar).position !== "fixed") return;
            var r = bar.getBoundingClientRect();
            if (!r.height) return;
            if (r.top + r.height / 2 < vh / 2) top = Math.max(top, r.bottom);
            else bottom = Math.min(bottom, r.top);
        });
        return { top: top + GAP, bottom: bottom - GAP };
    }

    function place(row) {
        var r = row.getBoundingClientRect();
        var vw = d.documentElement.clientWidth;
        var cb = chromeBounds();
        /* Measure at 0,0 with no height cap: a leftover `left` from the
         * previous placement constrains a fixed box's shrink-to-fit width
         * and poisons both measurements. Nothing paints mid-function. */
        pop.style.maxHeight = "";
        pop.style.left = "0px";
        pop.style.top = "0px";
        pop.style.display = "block";
        var pw = pop.offsetWidth, ph = pop.offsetHeight;
        var room = cb.bottom - cb.top;
        if (ph > room) { pop.style.maxHeight = room + "px"; ph = room; }

        var host = row.closest("[data-sv-overlay]");
        if (host) {
            /* Beside the panel, never over it — see the header note about
             * the ladder. Left first because these menus hang off the
             * top-right chrome; right only if the panel is pinned left;
             * and under the panel as the last resort on a narrow window,
             * which still clears it. */
            var hr = host.getBoundingClientRect();
            var left = hr.left - GAP - pw;
            var top = Math.min(Math.max(cb.top, r.top), cb.bottom - ph);
            if (left < GAP) {
                if (hr.right + GAP + pw <= vw - GAP) {
                    left = hr.right + GAP;
                } else {
                    /* Neither side fits. Under the panel only if the card
                     * genuinely CLEARS it — clamping into the remaining
                     * room slides the top back over the panel, and at
                     * z-hovercard against z-menu "over" means invisible.
                     * When it cannot clear, shrink it until it does. */
                    left = Math.max(GAP, Math.min(hr.left, vw - pw - GAP));
                    var below = hr.bottom + GAP;
                    var space = cb.bottom - below;
                    if (space < 120) {
                        /* Not even a shrunken card fits under the panel:
                         * put it above instead, where nothing overlaps. */
                        var above = Math.max(cb.top, hr.top - GAP - ph);
                        if (hr.top - cb.top >= 120) {
                            pop.style.maxHeight =
                                Math.max(120, hr.top - GAP - cb.top) + "px";
                            top = above;
                        } else {
                            /* Truly no room either side of the panel: the
                             * panel itself is the answer, so say nothing
                             * rather than paint an invisible card. */
                            pop.style.display = "none";
                            return;
                        }
                    } else {
                        if (ph > space) pop.style.maxHeight = space + "px";
                        top = below;
                    }
                }
            }
            pop.style.left = Math.round(left) + "px";
            pop.style.top = Math.round(Math.max(cb.top, top)) + "px";
            return;
        }

        var spaceBelow = cb.bottom - (r.bottom + GAP);
        var spaceAbove = (r.top - GAP) - cb.top;
        var below = spaceBelow >= ph || spaceBelow >= spaceAbove;
        var space = Math.max(60, below ? spaceBelow : spaceAbove);
        if (ph > space) { pop.style.maxHeight = space + "px"; ph = space; }
        pop.style.left = Math.max(8, Math.min(r.left + 24, vw - pw - 8)) + "px";
        pop.style.top = (below ? r.bottom + GAP
                               : Math.max(cb.top, r.top - GAP - ph)) + "px";
    }

    function hide() {
        /* Cheap exit for the scroll listener, which fires on every frame of
         * a wheel gesture with nothing to hide. */
        if (!timer && !current && pop.style.display !== "block") return;
        if (timer) { clearTimeout(timer); timer = null; }
        current = null;
        pop.style.display = "none";
    }

    d.addEventListener("pointerover", function (e) {
        if (e.pointerType && e.pointerType !== "mouse") return;
        if (!e.target.closest) return;
        var row = e.target.closest(ROW);
        if (!row) return;
        if (row === suppressed) {
            /* Movement inside a dismissed row keeps it quiet; a fresh entry
             * from outside means the dismissal has served its term. */
            if (e.relatedTarget && row.contains(e.relatedTarget)) return;
            suppressed = null;
        }
        if (row === current) return;
        hide();
        current = row;
        timer = setTimeout(function () {
            timer = null;
            build(row);
            place(row);
        }, HOVER_DELAY_MS);
    });

    d.addEventListener("pointerout", function (e) {
        if (e.pointerType && e.pointerType !== "mouse") return;
        if (!e.target.closest) return;
        var row = e.target.closest(ROW);
        if (!row) return;
        var to = e.relatedTarget;
        if (row === suppressed && !(to && row.contains(to))) suppressed = null;
        if (row !== current) return;
        /* Reaching for the card crosses out of the row — it must survive
         * that transit, and the card's own pointerleave takes over. */
        if (to && (row.contains(to) || pop.contains(to))) return;
        hide();
    });

    pop.addEventListener("pointerleave", function (e) {
        var to = e.relatedTarget;
        if (to && current && current.contains(to)) return;
        hide();
    });

    /* A click means the operator has decided — the card has served its
     * purpose and the row stays quiet until the pointer leaves it, so the
     * card cannot re-open over the page that is now loading. Navigation is
     * left to the row itself (a bell row is a link, an inbox row has its
     * own "Open page"), which is what keeps this a preview. */
    d.addEventListener("click", function (e) {
        if (!e.target.closest) return;
        if (pop.contains(e.target)) return;
        var row = e.target.closest(ROW);
        if (!row) return;
        if (w.getSelection && !w.getSelection().isCollapsed) return;
        suppressed = row;
        hide();
    });

    d.addEventListener("keydown", function (e) {
        if (e.key === "Escape" || e.key === "Esc") hide();
    });

    /* Closing the bell takes its rows with it, so a card still anchored to
     * one of them would hang over the page pointing at nothing. */
    d.addEventListener("sv:close", hide);

    /* Any scroll makes the anchor stale — the panel scrolls internally, so
     * this listens in the capture phase where non-bubbling scroll events
     * from inner containers still arrive. */
    w.addEventListener("scroll", hide, { passive: true, capture: true });
    w.addEventListener("resize", hide);
})(window, document);
