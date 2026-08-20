/* ── The dwell-preview engine + the notification detail card ──────────────
 *
 * PART ONE is the engine: SV.dwell.attach(). It was the fourth copy of the
 * same 2s-dwell hover preview — the news feed, the briefing history and the
 * notification card each carried their own — and the positions card would
 * have been the fifth, so it was lifted out here instead. Everything the
 * three copies had already paid for lives in it once:
 *   · delegated from document, never from a list container — the bell panel
 *     is portalled in and out of <body> on every open, htmx swaps the inbox,
 *     and the positions table is refreshed underneath the operator, so a
 *     listener bound to the container dies with it;
 *   · a pop.contains(relatedTarget) guard plus the card's own pointerleave,
 *     or the card vanishes in the gap the pointer crosses to reach it;
 *   · a collapsed-selection check before any navigation, or finishing a text
 *     selection inside a row navigates away from what was selected;
 *   · placement that measures the FIXED chrome rather than the raw viewport,
 *     and that puts a card for a row inside a portalled overlay BESIDE that
 *     overlay — --z-hovercard sits below --z-menu, so "over" means invisible;
 *   · a live-data guard the single-copy versions never needed: while a card
 *     is open the engine watches the row it is anchored to, redraws when the
 *     numbers under it change and closes when the row leaves the document. A
 *     card quoting a mark from before the last refresh is worse than no card.
 *   · a card the operator has REACHED stays reached. The scroll listener
 *     below runs in the capture phase on purpose — panels and table wrappers
 *     scroll internally and their scroll events do not bubble, so an anchor
 *     going stale underneath an open card arrives no other way — but capture
 *     also catches the card scrolling ITSELF, and hiding there meant every
 *     popup on this platform vanished the instant the operator scrolled the
 *     content they had hovered two seconds to read. The guard is the open-
 *     popup registry: a scroll from inside an open card is that card being
 *     read, never a stale anchor. Same reasoning for resize (re-place, do not
 *     destroy), for a wheel over a card with nothing to scroll (the page must
 *     not scroll out from under it), and for a pointer that leaves the card
 *     only because it is dragging the card's own scrollbar.
 *
 * It lives in THIS file rather than a new one because base.html owns the
 * <script> tags and is not ours to edit; sv-notif-card.js is already loaded
 * on every page, so a consumer loaded later (page {% block extra_js %}, also
 * deferred, therefore ordered after this) finds SV.dwell waiting.
 *
 * PART TWO is the original consumer, unchanged in behaviour: a notification
 * row is a headline, not the notification — the bell cuts the body at 110
 * characters, the kind is a chip, the age is rounded to the minute, and a
 * payload naming seven instruments can still only link to one page. A 2s
 * dwell raises the rest of it, with one link per data.items entry.
 */
(function (w, d) {
    "use strict";

    if (!d.querySelector) return;

    var HOVER_DELAY_MS = 2000, GAP = 8;

    /* The grace between the pointer leaving BOTH the row and the card and the
     * card closing. It exists for one crossing only — the few pixels of gap
     * between a row and the card placed beside it, where the pointer is
     * briefly over neither. It is deliberately NOT a timer that runs while
     * the pointer is on the card: a card the operator has reached closes when
     * they genuinely leave it, on Escape, or when its row disappears. Any
     * countdown against the operator's hand is the bug this replaces. */
    var LEAVE_GRACE_MS = 240;

    /* sv-overlay.css hides every hover card at (hover: none). The dwell can
     * therefore never fire on a touch device, and a consumer that wants a
     * tap to do something says so with its own `tap` handler. */
    var HOVERABLE = !(w.matchMedia && !w.matchMedia("(hover: hover)").matches);

    var instances = [];
    var wired = false;

    /* ── The open-popup registry ──────────────────────────────────────
     * Every popup engine on this page — the dwell cards here, the headband
     * and watchlist portal popups in base.html, the signals-rail card, the
     * news feed and the briefing history — needs the same answer to the same
     * question before it hides anything on a scroll: is this scroll coming
     * from INSIDE the popup the operator is currently reading? A guard kept
     * private to one engine protects one engine, so the registry is
     * published on SV and every engine reports its open popup into it.
     */
    var openPopups = [];

    function popupOpened(node) {
        if (node && openPopups.indexOf(node) < 0) openPopups.push(node);
    }
    function popupClosed(node) {
        var i = openPopups.indexOf(node);
        if (i >= 0) openPopups.splice(i, 1);
    }
    /* True only for a node INSIDE an open popup. The document, the root and
     * <body> all contain every popup and are excluded by name: a scroll
     * targeting one of those is the PAGE moving, which is exactly the case
     * that makes an anchor stale and must still close the card. */
    function insideOpenPopup(node) {
        if (!node || node === w || node === d
            || node === d.documentElement || node === d.body) return false;
        for (var i = 0; i < openPopups.length; i++) {
            var pop = openPopups[i];
            if (pop === node || (pop.contains && pop.contains(node))) return true;
        }
        return false;
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

    function place(pop, row) {
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
        var below2 = spaceBelow >= ph || spaceBelow >= spaceAbove;
        var space2 = Math.max(60, below2 ? spaceBelow : spaceAbove);
        if (ph > space2) { pop.style.maxHeight = space2 + "px"; ph = space2; }
        pop.style.left = Math.max(8, Math.min(r.left + 24, vw - pw - 8)) + "px";
        pop.style.top = (below2 ? r.bottom + GAP
                                : Math.max(cb.top, r.top - GAP - ph)) + "px";
    }

    function hideAll(except) {
        for (var i = 0; i < instances.length; i++) {
            if (instances[i] !== except) instances[i].hide();
        }
    }

    /* One set of document listeners for every consumer. Two engines each
     * binding their own pointerover would both fire on every move across
     * the page, and neither would know to close the other's card. */
    function wire() {
        if (wired) return;
        wired = true;

        d.addEventListener("pointerover", function (e) {
            /* No dwell at all where sv-overlay.css hides hover cards: a
             * touch device that reports pointerType "mouse" would otherwise
             * arm a card the stylesheet then refuses to paint, and the row
             * would sit suppressed for a click that never came. */
            if (!HOVERABLE) return;
            if (e.pointerType && e.pointerType !== "mouse") return;
            if (!e.target.closest) return;
            for (var i = 0; i < instances.length; i++) {
                var inst = instances[i];
                var row = e.target.closest(inst.sel);
                if (!row) continue;
                if (row === inst.suppressed) {
                    /* Movement inside a dismissed row keeps it quiet; a
                     * fresh entry from outside means the dismissal has
                     * served its term. */
                    if (e.relatedTarget && row.contains(e.relatedTarget)) return;
                    inst.suppressed = null;
                }
                if (row === inst.row) {
                    /* Back on the row the card describes — whatever leave
                     * grace was counting down was the pointer crossing the
                     * gap, not the operator walking away. */
                    inst.cancelLeave();
                    return;
                }
                hideAll(null);
                inst.arm(row);
                return;
            }
        });

        d.addEventListener("pointerout", function (e) {
            if (e.pointerType && e.pointerType !== "mouse") return;
            if (!e.target.closest) return;
            for (var i = 0; i < instances.length; i++) {
                var inst = instances[i];
                var row = e.target.closest(inst.sel);
                if (!row) continue;
                var to = e.relatedTarget;
                if (row === inst.suppressed && !(to && row.contains(to))) {
                    inst.suppressed = null;
                }
                if (row !== inst.row) return;
                /* Reaching for the card crosses out of the row — it must
                 * survive that transit, and the card's own pointerleave
                 * takes over. */
                var pop = inst.pop;
                if (to && (row.contains(to) || pop.contains(to))) return;
                /* The gap between the row and the card is a few pixels of
                 * page, and the pointer is over neither while it crosses.
                 * Closing on the first frame of that crossing is why the
                 * card could not be reached at all on a slow hand. */
                inst.scheduleLeave();
                return;
            }
        });

        d.addEventListener("click", function (e) {
            if (!e.target.closest) return;
            var i, inst;
            /* A click inside a card belongs to the card — its own buttons
             * handle it, and dismissing here would beat them to it. */
            for (i = 0; i < instances.length; i++) {
                if (instances[i].pop.contains(e.target)) return;
            }
            for (i = 0; i < instances.length; i++) {
                inst = instances[i];
                var row = e.target.closest(inst.sel);
                if (!row) continue;
                /* Finishing a drag-selection inside the row is not a click
                 * on the row, and must never navigate away from the text
                 * the operator has just selected. */
                if (w.getSelection && !w.getSelection().isCollapsed) return;
                /* The operator has decided — the card has served its
                 * purpose, and the row stays quiet until the pointer
                 * leaves it so the card cannot re-open over the page that
                 * is now loading. */
                inst.suppressed = row;
                inst.hide();
                var act = HOVERABLE ? inst.onClick : (inst.onTap || inst.onClick);
                if (act) act(row, e);
                return;
            }
        });

        d.addEventListener("keydown", function (e) {
            if (e.key === "Escape" || e.key === "Esc") hideAll(null);
        });

        /* Closing the bell takes its rows with it, so a card still anchored
         * to one of them would hang over the page pointing at nothing. */
        d.addEventListener("sv:close", function () { hideAll(null); });

        /* A scroll of the PAGE, or of a panel or table wrapper the anchor
         * row lives in, makes that anchor stale — panels scroll internally
         * and their scroll events do not bubble, so this listens in the
         * capture phase, which is where they arrive.
         *
         * Capture also catches the card scrolling ITSELF, and that is the
         * bug this guard exists for: the operator dwells two seconds, moves
         * onto the card, scrolls to read the rest of it, and the card
         * vanishes. Scrolling inside an open popup is that popup being
         * READ — the anchor has not moved and nothing is stale. */
        w.addEventListener("scroll", function (e) {
            if (insideOpenPopup(e.target)) return;
            hideAll(null);
        }, { passive: true, capture: true });

        /* Resize used to destroy the card too. It does move the anchor —
         * a snapped window, a devtools pane, a rotated tablet — but the
         * answer to "the anchor moved" is to follow it, not to throw away
         * what the operator was reading. Only a row that has left the
         * document closes, and that is watched for elsewhere. */
        w.addEventListener("resize", function () {
            for (var i = 0; i < instances.length; i++) instances[i].reflow();
        });

        /* A pointerup anywhere ends a scrollbar drag. While one is in
         * flight the card ignores its own pointerleave (see below), so this
         * is where a drag that ended OUTSIDE the card finally lets go. */
        w.addEventListener("pointerup", function (e) {
            for (var i = 0; i < instances.length; i++) {
                var inst = instances[i];
                if (!inst.held) continue;
                inst.held = false;
                var t = e.target;
                if (t && t.nodeType === 1
                    && (inst.pop.contains(t)
                        || (inst.row && inst.row.contains(t)))) continue;
                inst.scheduleLeave();
            }
        }, true);

        /* A drag that never gets its pointerup — the pointer left the
         * browser window, the OS took the gesture — would otherwise leave
         * `held` latched and the card unclosable by pointer. */
        w.addEventListener("pointercancel", function () {
            for (var i = 0; i < instances.length; i++) instances[i].held = false;
        }, true);
    }

    /* attach({rows, className, build, click, tap, delay}) — `build(row, pop)`
     * fills the (already emptied) card for that row. Returns the instance so
     * a consumer can hide() it after acting. */
    function attach(opts) {
        var pop = d.createElement("div");
        pop.className = opts.className || "nf-pop";
        /* Hidden from assistive tech on purpose: a dwell card cannot be
         * reached without a pointer, and every fact on it is also on a page
         * the keyboard can reach. Consumers that put controls on the card
         * mark them tabindex="-1" for the same reason — a focusable control
         * inside aria-hidden content is a trap with no way out. */
        pop.setAttribute("aria-hidden", "true");
        d.body.appendChild(pop);

        var inst = {
            sel: opts.rows,
            delay: opts.delay || HOVER_DELAY_MS,
            build: opts.build,
            onClick: opts.click || null,
            onTap: opts.tap || null,
            pop: pop,
            row: null,
            timer: null,
            suppressed: null,
            detachObs: null,
            rowObs: null,
            pending: 0,
            /* The leave grace (see LEAVE_GRACE_MS) and the scrollbar-drag
             * latch. `held` is true from a pointerdown on the card until the
             * matching pointerup, because dragging the card's own scrollbar
             * takes the pointer outside the card's box and fires the very
             * pointerleave that would close it mid-drag. */
            leaveTimer: null,
            held: false
        };

        function draw() {
            pop.textContent = "";
            inst.build(inst.row, pop);
            place(pop, inst.row);
            /* place() refuses to paint when nothing fits beside a portalled
             * panel, so the registry follows what is actually on screen. */
            if (pop.style.display === "block") popupOpened(pop);
            else popupClosed(pop);
        }

        /* The live-data guard. The other half of this page refreshes the
         * rows underneath an open card — an htmx swap, a websocket rewrite —
         * and a card still quoting the mark from before that refresh is a
         * lie the operator would act on. Two observers, both running only
         * while a card is up: one notices the anchor row leaving the
         * document and closes; one notices its contents changing and
         * redraws from the row's current attributes. */
        function watch() {
            if (!w.MutationObserver) return;
            if (!inst.detachObs) {
                inst.detachObs = new w.MutationObserver(function () {
                    if (inst.row && !d.contains(inst.row)) inst.hide();
                });
                inst.rowObs = new w.MutationObserver(function () {
                    if (!inst.row || !d.contains(inst.row)) return;
                    /* Coalesced: one swap fires a mutation per cell, and
                     * rebuilding the card six times would flicker it. */
                    if (inst.pending) return;
                    inst.pending = w.requestAnimationFrame(function () {
                        inst.pending = 0;
                        if (inst.row && d.contains(inst.row)) draw();
                    });
                });
            }
            /* body/subtree rather than the row's parent: a swap can replace
             * the whole table, in which case the childList mutation lands on
             * a grandparent the row never knew about. */
            inst.detachObs.observe(d.body, { childList: true, subtree: true });
            inst.rowObs.observe(inst.row, {
                childList: true, subtree: true,
                characterData: true, attributes: true
            });
        }

        function unwatch() {
            if (inst.pending) {
                w.cancelAnimationFrame(inst.pending);
                inst.pending = 0;
            }
            if (inst.detachObs) { inst.detachObs.disconnect(); inst.rowObs.disconnect(); }
        }

        inst.arm = function (row) {
            inst.hide();
            inst.row = row;
            inst.timer = setTimeout(function () {
                inst.timer = null;
                draw();
                watch();
            }, inst.delay);
        };

        inst.hide = function () {
            /* Cheap exit for the scroll listener, which fires on every frame
             * of a wheel gesture with nothing to hide. */
            if (!inst.timer && !inst.row && pop.style.display !== "block") return;
            if (inst.timer) { clearTimeout(inst.timer); inst.timer = null; }
            inst.cancelLeave();
            inst.held = false;
            unwatch();
            popupClosed(pop);
            inst.row = null;
            pop.style.display = "none";
        };

        /* Follow the anchor instead of destroying the card. Called on
         * resize; a row that has left the document is the observers' job. */
        inst.reflow = function () {
            if (!inst.row || pop.style.display !== "block") return;
            if (!d.contains(inst.row)) { inst.hide(); return; }
            place(pop, inst.row);
            if (pop.style.display !== "block") popupClosed(pop);
        };

        inst.cancelLeave = function () {
            if (inst.leaveTimer) {
                clearTimeout(inst.leaveTimer);
                inst.leaveTimer = null;
            }
        };

        /* The pointer is off both the row and the card. Give it the grace
         * of one gap-crossing and no more — re-entering either end cancels
         * this, so nothing is ever counting down while the operator is on
         * the card reading it. */
        inst.scheduleLeave = function () {
            if (!inst.row && pop.style.display !== "block") return;
            inst.cancelLeave();
            inst.leaveTimer = setTimeout(function () {
                inst.leaveTimer = null;
                if (inst.held) return;
                inst.hide();
            }, LEAVE_GRACE_MS);
        };

        pop.addEventListener("pointerenter", function () {
            /* Arrived. Whatever grace was counting down was the crossing. */
            inst.cancelLeave();
        });

        pop.addEventListener("pointerdown", function () {
            /* A press that starts on the card — the scrollbar, a selection,
             * the CLOSE button — owns the pointer until it is released. */
            inst.held = true;
            inst.cancelLeave();
        });

        pop.addEventListener("pointerleave", function (e) {
            var to = e.relatedTarget;
            if (to && inst.row && inst.row.contains(to)) return;
            /* Dragging the card's own scrollbar carries the pointer outside
             * the card's box; the drag has not ended, so neither has the
             * reading. The document pointerup finishes it. */
            if (inst.held) return;
            inst.scheduleLeave();
        });

        /* A wheel over a card that has NOTHING to scroll used to chain to
         * the page: the page scrolled, the anchor genuinely went stale and
         * the card was correctly — and infuriatingly — hidden, one frame
         * after the operator asked it to show them more. Nothing should
         * move instead. (.nf-pop also carries overscroll-behavior:contain,
         * which stops the chaining at the ENDS of a card that does scroll;
         * this covers the case where there is no scrollport at all.) */
        pop.addEventListener("wheel", function (e) {
            if (pop.scrollHeight > pop.clientHeight) return;
            e.preventDefault();
        }, { passive: false });

        instances.push(inst);
        wire();
        return inst;
    }

    w.SV = w.SV || {};
    w.SV.dwell = {
        attach: attach,
        hideAll: hideAll,
        HOVER_DELAY_MS: HOVER_DELAY_MS,
        hoverable: HOVERABLE
    };
    /* Published for the OTHER popup engines on the page — base.html's
     * portal popups and signals-rail card, the news feed, the briefing
     * history. Each of them hides on scroll for the same good reason and
     * broke for the same bad one; `inside` is the one guard they all ask. */
    w.SV.popup = {
        opened: popupOpened,
        closed: popupClosed,
        inside: insideOpenPopup
    };

    /* ── The notification consumer ──────────────────────────────────── */

    var ROW = "[data-nc-row]";

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

    function buildNotif(row, pop) {
        var ds = row.dataset;
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

    SV.dwell.attach({
        rows: ROW,
        className: "nf-pop nc-pop",
        build: buildNotif,
        /* On a pointer device navigation is left to the row itself (a bell
         * row is a link, an inbox row has its own "Open page"), which is
         * what keeps this a preview. On touch there is no card, so a tap
         * must do the one thing left — open the page — for the inbox rows,
         * which are divs and would otherwise swallow it. Bell rows are
         * anchors and navigate on their own, which is why anything inside a
         * link or button is left alone here. */
        tap: function (row, e) {
            if (!row.dataset.ncHref) return;
            if (e.target.closest("a, button")) return;
            w.location.assign(row.dataset.ncHref);
        }
    });
})(window, document);
