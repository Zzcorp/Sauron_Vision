/* ── Position detail card ────────────────────────────────────────────────
 *
 * A row in the positions table is twelve numbers with no answer to the only
 * question an operator actually asks of an open position: what is it doing,
 * and why is it on. Entry and mark are there; how far the mark is from the
 * stop is not. The rule name is there, truncated to twenty characters; the
 * reason the engine wrote when it decided is not, nor the score, nor the
 * signal behind it, nor the stop the trade OPENED with — which is the only
 * denominator under which "live R" means anything once a trailing stop has
 * rewritten stop_loss.
 *
 * A 2s dwell raises all of it. The engine is SV.dwell (static/js/
 * sv-notif-card.js) — the same one the news feed, the briefing history and
 * the notification card use, generalised there rather than copied a fourth
 * time. Everything about placement, the relatedTarget transit guard, the
 * selection check, the touch branch and the live-refresh guard comes from
 * it; this file is only the card's contents and its two actions.
 *
 * CLICK OPENS THE FORENSICS TIMELINE — it does not open a dialog. The
 * timeline at /forensics/<trade_id>/ already renders the full lifecycle,
 * every signal around the entry, the gate events, the audit chain, the
 * rule's track record and the raw metadata. A dialog rendering "more of the
 * same" would be a second truth to maintain, drifting from the page the
 * platform already treats as the record, and it would need a new endpoint
 * to feed it. So: the card is the preview, the timeline is the page, and
 * the card carries the one action the operator should not have to go
 * looking for after reading why a position is losing — the close.
 *
 * The close is a PROXY, not a second implementation: it clicks the row's
 * own CLOSE button, so base.html's delegated flow runs exactly as it does
 * from the table — preview, then the house confirm dialog, then execute,
 * with the PIN gate on a live venue — and, because the event's target is
 * the row's button, that flow can still find the row and retire it. A copy
 * of the button on a body-portalled card would have closed the position and
 * left the row on screen still reading OPEN.
 */
(function (w, d) {
    "use strict";

    if (!w.SV || !w.SV.dwell) return;

    var ROW = "[data-sv-position-row]";
    var DASH = "—";

    /* Every field is optional by design: a row from the portfolio book has
     * no trade behind it, an options row has no mark, a legacy trade has no
     * entry stop and therefore no R. An absent value is a gap in what the
     * platform knows and renders as an em-dash — never as 0, which reads as
     * a measured flat. */
    function val(row, key) {
        var v = row.getAttribute("data-pos-" + key);
        return (v === null || v === "") ? "" : v;
    }
    function flag(row, key) { return val(row, key) === "1"; }
    function num(row, key) {
        var v = val(row, key);
        if (!v) return null;
        var n = parseFloat(v);
        return isNaN(n) ? null : n;
    }

    function el(parent, tag, cls, text) {
        var node = d.createElement(tag);
        if (cls) node.className = cls;
        if (text !== undefined && text !== null) node.textContent = text;
        parent.appendChild(node);
        return node;
    }

    /* k/v line. `text` falsy means the platform has no value for it, and the
     * line still renders — an operator has to be able to see that the signal
     * is unknown, which a silently omitted row would hide. */
    function kv(parent, label, text, tone) {
        var row = el(parent, "div", "pos-pop-kv");
        el(row, "span", "k", label);
        var v = el(row, "span", "v" + (tone ? " " + tone : ""), text || DASH);
        if (!text) v.className += " sv-unknown";
        return row;
    }

    function toneOf(n) {
        if (n === null) return "";
        return n > 0 ? "up" : (n < 0 ? "down" : "");
    }
    function signed(n, digits) {
        if (n === null) return "";
        return (n > 0 ? "+" : "") + n.toFixed(digits === undefined ? 2 : digits);
    }

    /* Same path maths as the rail/headband sparks (base.html renderSparks),
     * reproduced here for one reason: that pass runs once at DOMContentLoaded
     * over the document as it stood, and this card is built minutes later.
     * A .pop-spark appended afterwards would carry an empty <path d="">. */
    function spark(parent, row) {
        var pts = val(row, "spark").split(",").map(parseFloat)
                     .filter(function (v) { return !isNaN(v); });
        if (pts.length < 2) return;
        var min = num(row, "spark-min"), max = num(row, "spark-max");
        if (min === null) min = Math.min.apply(null, pts);
        if (max === null) max = Math.max.apply(null, pts);
        var span = (max - min) || 1, W = 330, H = 34, pad = 1.5, cmds = [];
        for (var i = 0; i < pts.length; i++) {
            var x = (i / (pts.length - 1)) * (W - 2 * pad) + pad;
            var y = H - pad - ((pts[i] - min) / span) * (H - 2 * pad);
            cmds.push((i === 0 ? "M" : "L") + x.toFixed(2) + " " + y.toFixed(2));
        }
        var box = el(parent, "div", "pop-spark");
        box.setAttribute("data-up", flag(row, "spark-up") ? "1" : "0");
        var svg = d.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 " + W + " " + H);
        svg.setAttribute("preserveAspectRatio", "none");
        var path = d.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", cmds.join(" "));
        svg.appendChild(path);
        box.appendChild(svg);
    }

    /* The four levels, ordered by PRICE rather than by role. A short's
     * target sits below its entry and its stop above — printing them in a
     * fixed target/entry/stop order draws the ladder upside down for half
     * the book, and an upside-down ladder is how a stop gets read as a
     * target. Levels the trade never had are listed last, as gaps. */
    function ladder(parent, row) {
        /* `raw` is what prints and `price` is what sorts. The server already
         * picked the precision from the magnitude — two places on an index,
         * eight on a token quoted below a cent — and String(parseFloat(x))
         * throws that away and renders the small ones in exponential
         * notation, so a stop at 0.00000812 would print as "8.12e-6". */
        var rungs = [
            { role: "target", label: "TARGET", raw: val(row, "target"),
              price: num(row, "target"),
              pct: num(row, "target-pct"), through: flag(row, "target-through") },
            { role: "mark", label: "MARK", raw: val(row, "mark"),
              price: num(row, "mark") },
            { role: "entry", label: "ENTRY", raw: val(row, "entry"),
              price: num(row, "entry") },
            { role: "stop", label: "STOP", raw: val(row, "stop"),
              price: num(row, "stop"),
              pct: num(row, "stop-pct"), through: flag(row, "stop-through") }
        ];
        var known = rungs.filter(function (r) { return r.price !== null; });
        var gaps = rungs.filter(function (r) { return r.price === null; });
        known.sort(function (a, b) { return b.price - a.price; });

        var box = el(parent, "div", "pos-pop-ladder");
        known.concat(gaps).forEach(function (r) {
            var line = el(box, "div", "pos-pop-rung is-" + r.role);
            el(line, "span", "rl", r.label);
            var priceCell = el(line, "span", "rp",
                               r.price === null ? DASH : r.raw);
            if (r.price === null) priceCell.className += " sv-unknown";
            var note = "";
            if (r.role === "mark") {
                note = r.price === null ? "no quote" : "now";
            } else if (r.role === "entry") {
                var moved = num(row, "initial-stop");
                var stopNow = num(row, "stop");
                /* The stop the trade opened with is the R denominator and
                 * the risk that was actually accepted. When a trail has
                 * moved it, saying so is the difference between "this is
                 * still a 1R risk" and "this is now locked in". */
                note = (moved !== null && stopNow !== null && moved !== stopNow)
                    ? "stop moved from " + val(row, "initial-stop") : "";
            } else if (r.pct === null) {
                note = "";
            } else if (r.through) {
                note = "THROUGH by " + r.pct.toFixed(2) + "%";
            } else {
                note = r.pct.toFixed(2) + "% away";
            }
            var n = el(line, "span", "rn", note || DASH);
            if (!note) n.className += " sv-unknown";
        });

        /* Where the mark stands between the entry stop and the target, as
         * one bar. Drawn only when all three are known — a bar with a made-up
         * end would be the most confident lie on the card. */
        var progress = num(row, "progress");
        if (progress !== null) {
            var track = el(parent, "div", "pos-pop-track");
            track.setAttribute("data-tone", toneOf(num(row, "r")) || "flat");
            var fill = el(track, "i", "pos-pop-track-fill");
            fill.style.width = Math.max(0, Math.min(100, progress)) + "%";
            el(track, "b", "pos-pop-track-cap");
            var legend = el(parent, "div", "pos-pop-track-legend");
            el(legend, "span", "", "stop");
            el(legend, "span", "", "target");
        }
    }

    function build(row, pop) {
        pop.className = "nf-pop pos-pop";

        /* ── Head: what it is, and the one number that says how it is ── */
        var head = el(pop, "div", "pos-pop-head");
        var idBox = el(head, "div", "pos-pop-id");
        el(idBox, "div", "pos-pop-sym", val(row, "symbol") || DASH);
        var side = val(row, "side");
        var sub = el(idBox, "div", "pos-pop-sub");
        var sideChip = el(sub, "span",
                          "pos-pop-side " + (side === "SHORT" ? "down" : "up"),
                          side || DASH);
        if (!side) sideChip.className += " sv-unknown";
        el(sub, "span", "pos-pop-qty", val(row, "qty") || DASH);
        var venue = val(row, "venue");
        el(sub, "span", "pos-pop-venue is-" + (venue || "unknown").toLowerCase(),
           venue || DASH);
        if (val(row, "status") === "CLOSE_PENDING") {
            /* Not an error and not healthy: the bot wants this flat and the
             * broker has not agreed yet, which is exactly the state an
             * operator must not mistake for either. */
            el(sub, "span", "pos-pop-pending", "CLOSE PENDING");
        }

        var r = num(row, "r");
        var rBox = el(head, "div", "pos-pop-r " + toneOf(r));
        el(rBox, "div", "pos-pop-r-val", r === null ? DASH : signed(r, 2) + "R");
        el(rBox, "div", "pos-pop-r-cap", "live R");
        if (r === null) rBox.className += " sv-unknown";

        /* ── The money ── */
        var pnl = num(row, "pnl"), pnlPct = num(row, "pnl-pct");
        var money = el(pop, "div", "pos-pop-money");
        var abs = el(money, "span", "pos-pop-pnl " + toneOf(pnl),
                     pnl === null ? DASH : signed(pnl, 2));
        if (pnl === null) abs.className += " sv-unknown";
        var pct = el(money, "span", "pos-pop-pnlpct " + toneOf(pnlPct),
                     pnlPct === null ? DASH : signed(pnlPct, 2) + "%");
        if (pnlPct === null) pct.className += " sv-unknown";
        el(money, "span", "pos-pop-money-cap", "unrealised");

        spark(pop, row);
        ladder(pop, row);

        /* ── Provenance: who opened it, on what evidence, when ── */
        var grid = el(pop, "div", "pos-pop-grid");
        var age = val(row, "age"), opened = val(row, "opened");
        kv(grid, "Age", age && opened ? age + " · " + opened : (age || opened));
        var rule = val(row, "rule"), score = val(row, "score");
        kv(grid, "Opened by", rule ? (score ? rule + " · " + score : rule) : "");
        var sig = val(row, "signal");
        var sigDir = val(row, "signal-dir"), sigScore = val(row, "signal-score");
        kv(grid, "Signal",
           sig ? ((sigDir ? sigDir + " " : "") + (sigScore ? sigScore + " · " : "") + sig) : "",
           sigDir === "bearish" ? "down" : (sigDir === "bullish" ? "up" : ""));
        kv(grid, "Sub-scores", val(row, "signal-sub"));
        kv(grid, "1R is", val(row, "risk"));
        var basis = val(row, "basis"), left = val(row, "lot-left");
        kv(grid, "Lot basis", basis ? (left ? basis + " · " + left + " left" : basis) : "");
        kv(grid, "Broker order", val(row, "order"));

        /* ── The reason, verbatim ──
         * What the engine wrote at the moment it decided. Never truncated
         * here: the table already truncates the rule name to twenty
         * characters, and this card exists because that was not enough. */
        var reason = val(row, "reason");
        var why = el(pop, "div", "pos-pop-why");
        el(why, "div", "pos-pop-why-cap", "why it was taken");
        var body = el(why, "div", "pos-pop-why-body", reason ||
                      "No reason recorded — this row predates the engine "
                      + "writing one, or was opened by hand.");
        if (!reason) body.className += " sv-unknown";

        /* ── Actions ──
         * tabindex="-1" throughout: the card is aria-hidden (see SV.dwell),
         * so a focusable control on it would be reachable by keyboard but
         * invisible to a screen reader. The keyboard path is the row's own
         * symbol link and its own CLOSE button, both of which stay. */
        var actions = el(pop, "div", "pos-pop-actions");
        var rowClose = row.querySelector("[data-sv-close-trade]");
        if (rowClose) {
            var closeBtn = el(actions, "button", "sr-pop-btn pos-pop-close",
                              (rowClose.textContent || "CLOSE").trim());
            closeBtn.type = "button";
            closeBtn.tabIndex = -1;
            closeBtn.addEventListener("click", function (e) {
                e.preventDefault();
                e.stopPropagation();
                /* Hide first: the confirm dialog is about to take the
                 * screen, and a hover card left hanging over it at
                 * z-hovercard would be painted under it anyway. */
                if (w.SV.dwell) w.SV.dwell.hideAll(null);
                /* The row's own button, not a copy of its flow — see the
                 * header note. This is what lets base.html's handler find
                 * the row and retire it after a successful close. */
                rowClose.click();
            });
        }
        var href = val(row, "href");
        if (href) {
            var open = el(actions, "a", "sr-pop-btn pos-pop-open",
                          "FULL TIMELINE ›");
            open.href = href;
            open.tabIndex = -1;
        }

        el(pop, "div", "nf-pop-cta", href
            ? "click the row for the full timeline"
            : "no timeline for this one — it comes from the portfolio "
              + "book, not a bot trade");
    }

    w.SV.dwell.attach({
        rows: ROW,
        className: "nf-pop pos-pop",
        build: build,
        /* Click opens. Not on a control — the CLOSE button and the symbol
         * link do their own jobs — and not while a selection is standing,
         * which SV.dwell has already checked. */
        click: function (row, e) {
            var href = val(row, "href");
            if (!href) return;
            if (e.target.closest("a, button")) return;
            w.location.assign(href);
        },
        /* Touch has no dwell, so the tap has to be the whole interaction. */
        tap: function (row, e) {
            var href = val(row, "href");
            if (!href) return;
            if (e.target.closest("a, button")) return;
            w.location.assign(href);
        }
    });
})(window, document);
