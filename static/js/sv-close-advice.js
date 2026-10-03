/* sv-close-advice.js — "Should I close?" and "Close selected".
 *
 * Between one position and the whole book there was nothing. An operator
 * who wanted out of three rows had three dialogs and three PINs, or the
 * button that also closed everything else; and nothing on the page would
 * say whether getting out was a good idea at all. This file gives a
 * position table ticks, a bar that appears at the first one, and two
 * actions over exactly the ticked rows:
 *
 *   Should I close?    POST /positions/close-advice/ — Sauron's answer per
 *                      position and for the selection. Advice ONLY: the
 *                      endpoint cannot close anything. A second button asks
 *                      for the AI's reasoning (one model call), and the
 *                      answer says in words when it could not be had.
 *   Close selected…    the preview → confirm → execute pair the other close
 *                      buttons run, over the ticked ids and nothing else,
 *                      with ONE PIN for the batch when any row needs it —
 *                      and the server refuses the whole batch on a wrong
 *                      PIN rather than closing half of it.
 *
 * Three traps this is shaped around.
 *
 *   THE TABLE IS REBUILT UNDER THE TICKS. The rows sit in a live region
 *   (templates/_partials/live_region.html) whose markup is replaced on
 *   every sweep a mark moved. A checkbox cannot be the record of what was
 *   ticked, so the ids live in `selected` and are put back on the fresh
 *   boxes after every swap (the region announces it with sv:live-swapped).
 *   A row that is no longer there — closed, or filtered out — is dropped
 *   from the selection rather than acted on blind.
 *
 *   NOTHING MAY BE WRITTEN INTO THE REGION'S MARKUP. The live refresher
 *   decides whether to swap by comparing markup. `.checked` is a property
 *   and never reaches the markup; a class or a `disabled` attribute stamped
 *   on a row would, and would turn every sweep into a full rebuild. The
 *   ticked-row highlight is CSS :has() for that reason.
 *
 *   A TICK IS NOT A CLICK ON THE ROW. The row itself navigates to the
 *   trade's page (sv-position-card.js), which now ignores clicks inside the
 *   tick cell; without that, ticking a box would open another page.
 *
 * Everything the dialog prints arrives formatted from the server — money as
 * "1,234.56 EUR", an unmeasured figure as the em dash — and is written with
 * textContent, never parsed as HTML: symbols, rule names and the model's prose
 * are data, not markup.
 */
(function (w, d) {
    "use strict";
    if (w.SVCloseAdvice) return;            /* one instance per page */

    var DASH = "—";
    var ADVICE_URL = "/positions/close-advice/";
    var PREVIEW_URL = "/positions/close-selected/preview/";
    var CLOSE_URL = "/positions/close-selected/";
    var MAX_IDS = 50;                        /* the endpoints' own cap */

    /* Trade ids as strings, in the order they were ticked. */
    var selected = [];
    var busy = false;                        /* one close run at a time */

    function each(list, fn) { Array.prototype.forEach.call(list || [], fn); }

    function el(parent, tag, cls, text) {
        var n = d.createElement(tag);
        if (cls) n.className = cls;
        if (text !== undefined && text !== null) n.textContent = String(text);
        if (parent) parent.appendChild(n);
        return n;
    }

    function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }

    function isNum(v) { return typeof v === "number" && isFinite(v); }

    /* ── the selection ───────────────────────────────────────────────── */

    function has(id) { return selected.indexOf(String(id)) !== -1; }
    function add(id) { if (!has(id)) selected.push(String(id)); }
    function drop(id) {
        var i = selected.indexOf(String(id));
        if (i !== -1) selected.splice(i, 1);
    }

    /* Keep only the ids still on the page, in their ticked order. Pure, so
       it can be read (and tested) on its own. */
    function prune(ids, present) {
        var keep = {};
        each(present, function (id) { keep[String(id)] = true; });
        return ids.filter(function (id) { return keep[String(id)]; });
    }

    function boxes(scope) {
        return (scope || d).querySelectorAll("input[data-sv-select-trade]");
    }

    /* What a "select all" box covers: its own table when it sits in one
       (the header box), else the block that declares itself a selection
       scope (the phone box above a stacked table, whose header row is
       visually hidden at 768px and below and so cannot be reached there). */
    function scopeOf(all) {
        if (!all.closest) return d;
        return all.closest("table") || all.closest("[data-sv-select-scope]") || d;
    }

    /* After a swap the boxes are new and unticked: tick them again from the
       record, and forget the rows that are gone. */
    function reapply() {
        var present = [];
        each(boxes(), function (b) {
            var id = b.getAttribute("data-sv-select-trade");
            present.push(id);
            b.checked = has(id);
        });
        selected = prune(selected, present);
        paint();
    }

    function paint() {
        each(d.querySelectorAll("input[data-sv-select-all]"), function (all) {
            var list = boxes(scopeOf(all));
            var on = 0;
            each(list, function (b) { if (b.checked) on += 1; });
            all.checked = list.length > 0 && on === list.length;
            all.indeterminate = on > 0 && on < list.length;
        });
        /* The phone's box has nothing to select on a book with no bot row;
           hidden rather than offered. It sits OUTSIDE the live region, so
           this attribute never reaches the markup the refresher compares. */
        each(d.querySelectorAll("[data-sv-select-all-wrap]"), function (wrap) {
            wrap.hidden = boxes(scopeOf(wrap)).length === 0;
        });
        var n = selected.length;
        each(d.querySelectorAll("[data-sv-select-bar]"), function (bar) {
            bar.hidden = n === 0;
            var count = bar.querySelector("[data-sv-select-count]");
            if (count) count.textContent = n + " selected";
            var closeBtn = bar.querySelector("[data-sv-close-selected]");
            if (closeBtn) closeBtn.textContent =
                n > 1 ? "Close " + n + " selected…" : "Close selected…";
        });
    }

    /* Tick or untick one box; false when the cap refused the tick. */
    function tick(box, on) {
        var id = box.getAttribute("data-sv-select-trade");
        box.checked = on;
        if (!on) { drop(id); return true; }
        if (selected.length >= MAX_IDS && !has(id)) {
            box.checked = false;
            return false;
        }
        add(id);
        return true;
    }

    function tooMany() {
        if (!w.SV || !w.SV.overlay) return;
        w.SV.overlay.alert({
            title: "That is the most at once",
            message: "Up to " + MAX_IDS + " positions can be asked about or " +
                     "closed together. Close all is the button for the " +
                     "whole book."
        });
    }

    function clearIds(ids) {
        each(ids, function (id) { drop(id); });
        reapply();
    }

    /* ── talking to the server ───────────────────────────────────────── */

    function csrf() {
        var m = d.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : "";
    }

    /* X-Requested-With so a locked session answers 423 {pin_locked} (core/
       idle_lock.py) instead of a redirect to an HTML page this cannot read. */
    function post(url, payload) {
        return fetch(url, {
            method: "POST", credentials: "same-origin",
            headers: {
                "X-CSRFToken": csrf(),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest"
            },
            body: JSON.stringify(payload || {})
        }).then(function (r) {
            return r.text().then(function (t) {
                var j;
                try { j = JSON.parse(t); }
                catch (e) {
                    return { error: r.status === 403
                        ? "Not allowed — refresh the page and try again."
                        : (r.redirected || t.indexOf("<html") !== -1)
                            ? "Session expired — refresh the page and log in again."
                            : "HTTP " + r.status };
                }
                if (j && j.pin_locked) {
                    return { error: "The screen is locked. Unlock it with " +
                                    "your PIN, then try again.",
                             pin_locked: true };
                }
                return j;
            });
        });
    }

    /* ── words ───────────────────────────────────────────────────────── */

    /* "1 real money · 2 eToro demo · 1 paper" — demo is never counted as
       live: simulated money at a broker is still simulated money. */
    function worldWords(worlds) {
        worlds = worlds || {};
        var parts = [];
        if (worlds.live) parts.push(worlds.live + " real money");
        if (worlds.demo) parts.push(worlds.demo + " broker demo");
        if (worlds.paper) parts.push(worlds.paper + " paper");
        return parts.length ? parts.join(" · ") : DASH;
    }

    /* A close the platform GAVE UP on: the row is ERROR with no closed_at,
       still open at the broker, and outside every open-book read. The
       server keeps it out of `missing` and counts it in `abandoned`; these
       are its words, the same before the PIN and after the close. */
    function abandonedWords(n) {
        var those = n === 1 ? "that position is" : "those positions are";
        var them = n === 1 ? "it" : "them";
        return plural(n, "close") + (n === 1 ? " was" : " were") +
               " ABANDONED after repeated broker failures — " + those +
               " still open at the broker and nothing here is retrying " +
               them + ". Close " + them + " at the broker; the retry history " +
               "is on /forensics/";
    }

    function verdictClass(v) {
        return { close: "is-close", trim_or_tighten: "is-trim",
                 hold: "is-hold" }[v] || "is-unknown";
    }

    /* A row already being closed wears its own colour whatever its facts
       say: a green "hold" chip over a position the platform is closing
       reads as "this stays open", which the words beside it deny. */
    function cardClass(p) {
        return p.pending ? "is-pending" : verdictClass(p.verdict);
    }

    function tone(n) {
        return !isNum(n) ? "sv-unknown" : (n > 0 ? "up" : (n < 0 ? "down" : ""));
    }

    /* ── the advice dialog ───────────────────────────────────────────── */

    var dlgSeq = 0;

    function openAdvice(ids, opts) {
        opts = opts || {};
        if (!w.SV || !w.SV.overlay || !ids || !ids.length) return;
        ids = ids.slice(0, MAX_IDS);
        dlgSeq += 1;
        var titleId = "svAdvTitle" + dlgSeq;

        var host = el(null, "div", "sv-dialog sv-advice");
        host.setAttribute("data-sv-overlay", "dialog");
        host.setAttribute("role", "dialog");
        host.setAttribute("aria-labelledby", titleId);

        var head = el(host, "div", "sv-dialog-head");
        var title = el(head, "span", "sv-dialog-title", "Should I close?");
        title.id = titleId;
        var x = el(head, "button", "sv-dialog-x", "×");
        x.type = "button";
        x.setAttribute("data-sv-close", "");
        x.setAttribute("aria-label", "Close this panel");

        var body = el(host, "div", "sv-dialog-body sv-adv-body");
        body.setAttribute("aria-live", "polite");
        el(body, "p", "sv-adv-status", "Asking Sauron about " +
           plural(ids.length, "position") + "…");

        var foot = el(host, "div", "sv-dialog-foot");
        var done = el(foot, "button", "sv-dialog-btn", "Done");
        done.type = "button";
        done.setAttribute("data-sv-close", "");
        var closeThese = null;
        if (!opts.noClose) {
            closeThese = el(foot, "button",
                            "sv-dialog-btn sv-dialog-btn--go is-danger",
                            "Close these…");
            closeThese.type = "button";
            closeThese.hidden = true;
        }

        d.body.appendChild(host);
        host.addEventListener("sv:close", function () {
            setTimeout(function () {
                if (host.parentNode) host.parentNode.removeChild(host);
            }, 200);
        });
        w.SV.overlay.open(host, opts.trigger || null);

        var current = null;

        function render(answer, asking) {
            current = answer;
            while (body.firstChild) body.removeChild(body.firstChild);
            renderAnswer(body, answer, {
                asking: asking,
                noClose: !!opts.noClose,
                onAskAI: function () { ask(true); }
            });
            var open = (answer.positions || []).map(function (p) {
                return p.trade_id;
            });
            if (closeThese) {
                closeThese.hidden = open.length === 0;
                closeThese.textContent = open.length === 1
                    ? "Close this one…"
                    : "Close these " + open.length + "…";
                closeThese.onclick = function () {
                    closeSelected(open, {
                        trigger: closeThese,
                        /* No clearIds here: closeSelected has already
                           unticked exactly the rows that closed. Clearing
                           every advised id as well would untick the ones
                           that FAILED — after "PARTIALLY closed — 1 STILL
                           OPEN" the row still open would lose the tick the
                           operator needs to try it again. */
                        onClosed: function (res) {
                            w.SV.overlay.close(host);
                            if (opts.onClosed) opts.onClosed(res);
                        }
                    });
                };
            }
        }

        function ask(model) {
            if (model && current) render(current, true);
            post(ADVICE_URL, { ids: ids, model: !!model }).then(function (a) {
                if (!a || a.error) {
                    if (model && current) {
                        current.model = { requested: true, used: false,
                                          note: "The AI part is missing: " +
                                                ((a && a.error) || "no answer came back") +
                                                ". This is Sauron's rule-based answer only." };
                        render(current, false);
                        return;
                    }
                    while (body.firstChild) body.removeChild(body.firstChild);
                    el(body, "p", "sv-adv-status is-error",
                       (a && a.error) || "No answer came back from the server.");
                    return;
                }
                render(a, false);
            }).catch(function (e) {
                while (body.firstChild) body.removeChild(body.firstChild);
                el(body, "p", "sv-adv-status is-error",
                   "Could not reach the platform (" + e + "). Nothing was closed.");
            });
        }
        ask(false);
        return host;
    }

    function fact(grid, label, value, sub, cls) {
        var row = el(grid, "div");
        el(row, "dt", "", label);
        var dd = el(row, "dd", cls || "", value === null || value === undefined
                                          || value === "" ? DASH : value);
        if (sub) el(dd, "small", "", sub);
        return dd;
    }

    function renderAnswer(body, a, ctx) {
        var s = a.summary || {};
        var positions = a.positions || [];

        /* The selection first: the one line, then what closing all of it
           would mean. */
        var sum = el(body, "section", "sv-adv-summary");
        sum.setAttribute("aria-label", "The selection as a whole");
        el(sum, "p", "sv-adv-overall", s.overall || DASH);
        var grid = el(sum, "dl", "sv-adv-grid");
        var what = plural(s.positions || 0, "position");
        if (s.orders) what += " · " + plural(s.orders, "order");
        fact(grid, "Selected", s.count ? what : DASH);
        fact(grid, "Money", worldWords({ live: s.live, demo: s.demo,
                                         paper: s.paper }));
        fact(grid, "Profit or loss now", s.pnl_text, s.pnl_note,
             tone(s.pnl));
        fact(grid, "Capital freed by closing", s.capital_freed_text,
             s.capital_freed_note);
        var reads = [];
        if (s.close) reads.push(s.close + " close");
        if (s.trim_or_tighten) reads.push(s.trim_or_tighten + " watch");
        if (s.hold) reads.push(s.hold + " hold");
        if (s.unknown) reads.push(s.unknown + " can't judge");
        /* Counted apart by the server: a pending row is in none of the
           four counts above, so nothing here is said twice. */
        if (s.pending) reads.push(s.pending + " already being closed");
        fact(grid, "Sauron's read", reads.length ? reads.join(" · ") : DASH);
        if (a.not_found_words) {
            el(sum, "p", "sv-adv-note is-warn", a.not_found_words);
        }

        /* The AI half. */
        var m = a.model || {};
        var ai = el(body, "div", "sv-adv-ai");
        if (m.used) {
            var t = el(ai, "p", "sv-adv-ai-text");
            el(t, "strong", "", "Sauron's reasoning (AI): ");
            t.appendChild(d.createTextNode(m.overall || "See each position below."));
            if (m.note) el(ai, "p", "sv-adv-ai-text", m.note);
        } else {
            if (positions.length) {
                var btn = el(ai, "button", "sv-adv-ai-btn",
                             ctx.asking ? "Sauron is reasoning…"
                                        : "Ask Sauron to reason about it (AI)");
                btn.type = "button";
                btn.disabled = !!ctx.asking;
                btn.addEventListener("click", function () {
                    if (!btn.disabled) ctx.onAskAI();
                });
            }
            el(ai, "p", "sv-adv-ai-text", m.note ||
               "This answer comes from Sauron's rules, from the facts below. " +
               "The AI can reason about them too: one call, counted against " +
               "today's AI budget.");
        }

        var cards = el(body, "div", "sv-adv-cards");
        each(positions, function (p) { card(cards, p); });
        if (!positions.length) {
            el(cards, "p", "sv-adv-status",
               "None of the ticked rows is open any more.");
        }

        el(body, "p", "sv-adv-foot-note", (a.never_closes || "") +
           (ctx.noClose ? " To close it, use the close button on this page." : ""));
    }

    function card(parent, p) {
        var n = p.numbers || {};
        var c = el(parent, "article", "sv-adv-card " + cardClass(p));
        var head = el(c, "div", "sv-adv-card-head");
        el(head, "span", "sv-adv-title", p.headline || p.symbol);
        el(head, "span", "sv-adv-world is-" + (p.world || "paper"),
           p.world_words || DASH);
        el(head, "span", "sv-adv-chip " + cardClass(p),
           p.verdict_words || DASH);

        var grid = el(c, "dl", "sv-adv-grid");
        if (p.kind === "order") {
            fact(grid, "Order price", n.entry_text);
            fact(grid, "Waiting for", n.age_text);
        } else {
            fact(grid, "Price now", n.mark_text);
            fact(grid, "Profit or loss", n.pnl_text, "", tone(n.pnl));
            fact(grid, "R now", n.r_now_text, "", tone(n.r_now));
            fact(grid, "To the stop", n.r_to_stop_text,
                 isNum(n.r_to_planned_stop)
                    ? "the broker's stop; " + n.r_to_planned_stop.toFixed(2) +
                      "R to the one Sauron sent"
                    : "");
            fact(grid, "To the target", n.r_to_target_text);
            fact(grid, "Held for", n.age_text);
            fact(grid, "Capital", n.committed_text,
                 n.committed_kind === "margin" ? "margin, not the full exposure" : "");
        }

        if (p.reasons && p.reasons.length) {
            var ul = el(c, "ul", "sv-adv-reasons");
            each(p.reasons, function (r) { el(ul, "li", "", r); });
        }

        if (p.model) {
            var box = el(c, "div", "sv-adv-model");
            var mh = el(box, "div", "sv-adv-model-head");
            el(mh, "span", "", "AI: " + (p.model.verdict_words || DASH));
            if (isNum(p.model.confidence)) {
                el(mh, "span", "", "confidence " + p.model.confidence.toFixed(2));
            }
            if (!p.model.agrees) el(mh, "span", "", "differs from the rules");
            if (p.model.reasoning) el(box, "p", "", p.model.reasoning);
        }
    }

    /* ── close what was ticked ───────────────────────────────────────── */

    function closeSelected(ids, opts) {
        opts = opts || {};
        if (busy || !ids || !ids.length || !w.SV || !w.SV.overlay) return;
        busy = true;
        var trigger = opts.trigger || null;
        if (trigger) trigger.disabled = true;
        function release() { busy = false; if (trigger) trigger.disabled = false; }

        /* Every chain ends in a catch: a dropped connection must not leave
           the button disabled and the operator unsure what happened. */
        post(PREVIEW_URL, { ids: ids.slice(0, MAX_IDS) }).then(function (p) {
            if (p.error) {
                release();
                w.SV.overlay.alert({ title: "Cannot close", message: p.error });
                return;
            }
            var missing = p.missing || [];
            if (!p.count) {
                release();
                w.SV.overlay.alert({
                    title: "Nothing to close",
                    message: "None of the selected positions is still open." +
                             (missing.length ? " " + plural(missing.length, "row") +
                              " had already gone." : "") +
                             (p.abandoned ? " " + abandonedWords(p.abandoned) + "." : "")
                });
                clearIds(ids);
                return;
            }
            var worlds = p.worlds || {};
            var facts = [
                ["Closing", plural(p.count, "position")],
                ["Money", worldWords(worlds)],
                /* One unmeasured row makes the total unknown: a dash,
                   never a partial sum passed off as the whole. */
                ["Realises", p.pnl_text || DASH],
                ["Bots after this", "still armed — they can re-open"],
                ["Reversible", "no"]
            ];
            if (p.pending) facts.push(["Already retrying", String(p.pending)]);
            if (missing.length) {
                facts.push(["No longer open", plural(missing.length, "row") +
                            " — left out; nothing takes their place"]);
            }
            if (p.abandoned) facts.push(["Abandoned", abandonedWords(p.abandoned)]);
            var names = (p.rows || []).map(function (r) {
                return r.side + " " + r.qty + " " + r.symbol +
                       (r.world === "live" ? " (real money)"
                        : r.world === "demo" ? " (broker demo)" : " (paper)");
            });
            if (p.more) names.push("and " + p.more + " more");

            /* Winners this would cut short of their targets (2026-10-02):
               named above the button, never a gate. */
            var early = (p.early || []).map(function (x) {
                return x.symbol + " " + (x.r >= 0 ? "+" : "") +
                       Number(x.r).toFixed(2) + "R of " +
                       (x.target_r >= 0 ? "+" : "") +
                       Number(x.target_r).toFixed(2) + "R";
            });
            var earlyN = p.early_count || early.length;
            w.SV.overlay.confirm({
                warn: earlyN ? {
                    title: "CLOSING " + earlyN + " WINNER(S) EARLY",
                    text: early.join(", ") +
                          (earlyN > early.length ? " and " + (earlyN - early.length) +
                           " more" : "") +
                          " — short of their targets. Position care moves a stop " +
                          "to break-even at +1R. A warning, not a block: the " +
                          "choice is yours."
                } : undefined,
                title: p.count === 1 ? "Close the selected position?"
                                     : "Close the " + p.count + " selected positions?",
                message: worlds.live
                    ? "This closes " + plural(worlds.live, "real-money position") +
                      " at the broker. It cannot be undone, and re-entering " +
                      "costs the round trip again."
                    : (worlds.demo
                        ? "These are simulated positions; the ones at a broker's " +
                          "demo account are closed there."
                        : "This books the exit on every selected paper position " +
                          "and grades each trade."),
                detail: names.join(" · ") +
                        (p.needs_pin ? ". One PIN for all of them: if it is " +
                         "wrong, nothing is closed." : ""),
                facts: facts,
                danger: true,
                /* Held at a broker — real or demo — needs the PIN; the
                   server refuses the WHOLE batch on a wrong one. */
                secretLabel: p.needs_pin ? "Trading PIN" : undefined,
                confirmLabel: "CLOSE " + plural(p.count, "POSITION").toUpperCase() +
                              (earlyN ? " ANYWAY" : "")
            }).then(function (ok) {
                if (!ok) { release(); return; }
                return post(CLOSE_URL, { ids: p.ids, pin: (ok === true ? "" : ok) })
                    .then(function (res) {
                        release();
                        if (res.error) {
                            w.SV.overlay.alert({
                                title: res.pin_required ? "Trading PIN needed — nothing was closed"
                                                        : "Result unknown — check the book",
                                message: res.pin_required ? res.error
                                    : res.error + " Some positions may have closed. " +
                                      "Reload before pressing again."
                            });
                            return;
                        }
                        if (w.refreshPanelCounts) w.refreshPanelCounts();
                        if (w.svLiveRefresh) w.svLiveRefresh();
                        clearIds((res.closed || []).map(function (c) { return c.id; }));
                        /* Before the result, not after it: the advice
                           dialog closing would hand focus back to its own
                           trigger, out from under the answer. */
                        if (opts.onClosed) opts.onClosed(res);
                        var flat = res.flat && !res.n_failed;
                        var gone = (res.missing || []).length;
                        w.SV.overlay.alert({
                            /* "flat" alone is not success: a selection
                               whose rows had all gone before the close is
                               flat and closed nothing. */
                            title: !res.n_closed ? "Nothing was closed"
                                : flat ? (res.n_closed === 1 ? "Closed"
                                                             : "All " + res.n_closed + " closed")
                                : "PARTIALLY closed — " + (res.still_open || 0) + " STILL OPEN",
                            message: (res.n_closed ? "Closed: " + res.closed.map(function (c) {
                                        return c.symbol + " " + (c.pnl_text || DASH);
                                    }).join(" · ") : "0 closed") +
                                (res.n_failed ? ", " + res.n_failed + " still open: " +
                                    res.failed.map(function (f) {
                                        return f.symbol + " (" + f.error + ")";
                                    }).join("; ") : "") +
                                (gone ? ". " + plural(gone, "row") + " had already " +
                                    "gone before the close and " + (gone === 1 ? "was" : "were") +
                                    " left out." : "") +
                                (res.abandoned ? ". " + abandonedWords(res.abandoned) : "") +
                                "."
                        });
                    });
            }).catch(function (e) {
                release();
                w.SV.overlay.alert({
                    title: "Could not read the result",
                    message: "The confirmation did not come back (" + e + "). " +
                             "Some positions MAY have closed — reload this page " +
                             "and check the book before pressing again."
                });
            });
        }).catch(function (e) {
            release();
            w.SV.overlay.alert({
                title: "Could not reach the platform",
                message: "Nothing was closed (" + e + ")."
            });
        });
    }

    /* ── wiring ──────────────────────────────────────────────────────── */

    d.addEventListener("change", function (e) {
        var t = e.target;
        if (!t || !t.matches) return;
        if (t.matches("input[data-sv-select-trade]")) {
            if (!tick(t, t.checked)) tooMany();
            paint();
        } else if (t.matches("input[data-sv-select-all]")) {
            var on = t.checked, refused = false;
            each(boxes(scopeOf(t)), function (b) {
                if (!tick(b, on)) refused = true;
            });
            paint();
            if (refused) tooMany();         /* once, not once per row */
        }
    });

    d.addEventListener("click", function (e) {
        var t = e.target;
        if (!t || !t.closest) return;
        /* The whole tick cell is the target, not just the 16px box: a
           finger misses a box that small, and a miss must not fall through
           to the row, which navigates. */
        var cell = t.closest("[data-sv-select-cell]");
        if (cell) {
            if (t.matches && t.matches("input")) return;
            var box = cell.querySelector("input[data-sv-select-trade]");
            if (box) box.click();
            return;
        }
        var btn = t.closest("[data-sv-advice-open], [data-sv-close-selected], " +
                            "[data-sv-select-clear], [data-sv-advice-ids]");
        if (!btn) return;
        e.preventDefault();
        if (btn.hasAttribute("data-sv-advice-ids")) {
            var ids = String(btn.getAttribute("data-sv-advice-ids") || "")
                .split(",").map(function (s) { return s.trim(); })
                .filter(Boolean);
            openAdvice(ids, { trigger: btn,
                              noClose: btn.getAttribute("data-sv-advice-no-close") === "1" });
        } else if (btn.hasAttribute("data-sv-advice-open")) {
            openAdvice(selected.slice(), { trigger: btn });
        } else if (btn.hasAttribute("data-sv-close-selected")) {
            closeSelected(selected.slice(), { trigger: btn });
        } else if (btn.hasAttribute("data-sv-select-clear")) {
            selected = [];
            reapply();
        }
    });

    /* The live region rebuilt a table: tick its new boxes again. */
    d.addEventListener("sv:live-swapped", reapply);

    function init() {
        /* The single-position launcher is only shown where this script
           runs: without it the button would do nothing. */
        each(d.querySelectorAll("[data-sv-advice-ids][hidden], .pd-advice-row[hidden]"),
             function (n) { n.hidden = false; });
        reapply();
    }
    if (d.readyState === "loading") d.addEventListener("DOMContentLoaded", init);
    else init();

    w.SVCloseAdvice = {
        open: openAdvice,
        closeSelected: closeSelected,
        selected: function () { return selected.slice(); },
        prune: prune,
        worldWords: worldWords
    };
})(window, document);
