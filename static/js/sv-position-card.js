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
 * THREE GESTURES, THREE DESTINATIONS. Hover a row and this card previews
 * it; click the row and the trade's full detail opens; click the SYMBOL
 * and the INSTRUMENT underneath it opens. The third was the one missing:
 * the symbol cell pointed at the same forensics page as the row, so an
 * operator who wanted the chart of the thing they are actually holding
 * had to leave the table, find the instruments list and search for it.
 * The row now carries data-pos-instrument-href, and the card's own title
 * IS that link — the same word, in the same place, going to the same
 * page as the symbol cell in the table underneath it.
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

    /* A section head, in the voice the ledger already speaks. Four blocks
     * divided by four identical dashed rules read as one long list; naming
     * each one is what makes the card a document instead of a dump. The
     * class the shared sheet already styles comes FIRST because this file
     * is loaded by five templates and only the positions page carries the
     * refinements — everywhere else the caption still has to read as one. */
    function cap(parent, text) {
        return el(parent, "div", "pos-pop-ledger-cap pos-pop-sec-cap", text);
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

    /* The money attributes arrive from the view already formatted and
     * grouped — "1,540.00". parseFloat stops at the comma and returns 1540,
     * so nothing here re-parses them: the sign is read off the TEXT and the
     * text is printed as it came. One money formatter, in Python, where the
     * em-dash-for-unknown rule and the currency rules already live. */
    function moneySign(text) {
        if (!text) return 0;
        if (text.charAt(0) === "-" || text.charAt(0) === "−") return -1;
        return /[1-9]/.test(text) ? 1 : 0;
    }
    function moneyTone(text) {
        var s = moneySign(text);
        return s > 0 ? "up" : (s < 0 ? "down" : "");
    }
    function moneySigned(text) {
        return moneySign(text) > 0 ? "+" + text : text;
    }

    /* One line of the capital ledger: what it is, how much, and where the
     * number came from. The line renders even with no value — an operator
     * has to be able to see that the platform does not know what a position
     * cost, which a silently omitted row would hide. */
    function mrow(parent, label, text, note, tone) {
        var line = el(parent, "div", "pos-pop-mrow");
        el(line, "span", "ml", label);
        var v = el(line, "span", "mv" + (tone ? " " + tone : ""), text || DASH);
        if (!text) v.className += " sv-unknown";
        if (note) el(line, "span", "mn", note);
        return line;
    }

    /* ── The capital ledger ───────────────────────────────────────────
     * What was committed, what it is worth now, what 1R costs, what the
     * paper exit already takes off the top, and what the close dialog will
     * therefore say. Every figure is denominated by the same
     * value_per_unit the row's own P&L was marked with (dashboard.views
     * _pos_value_per_unit), so the percentage in the head divides these
     * currency figures rather than a second set of them.
     *
     * The committed line is the one that can lie. On a levered class
     * qty x entry is EXPOSURE — bot_program sizing lets forex run to 400%
     * of equity because the leverage sits at the broker — and the capital
     * actually put up is margin, which nothing on this platform records.
     * So the view sends committed-kind, and a "margin" kind means: dash the
     * committed figure and print the notional under its own name. A card
     * that showed a 4x notional as "what this cost me" would be the most
     * expensive wrong number on the page.
     */
    function ledger(parent, row, closed) {
        var kind = val(row, "committed-kind");
        var margin = kind === "margin";
        var ccy = val(row, "ccy");
        var box = el(parent, "div", "pos-pop-ledger");
        cap(box, "capital" + (ccy ? " · " + ccy : ""));

        /* The share of the pool rides with the money, because 4,800 says
         * nothing about whether this position is a rounding error or half
         * the book — and "48% of pool" is the sentence an operator sizes
         * by without dividing anything in their head. */
        var share = val(row, "committed-pct");
        mrow(box, margin ? "Margin" : "Cost at entry", val(row, "committed"),
             (share ? share + "% of the pool · " : "") +
             (margin ? "broker-set — not recorded" : "qty × entry"));
        if (margin) {
            /* Named as exposure, never as cost — see the note above. */
            mrow(box, "Notional", val(row, "notional"), "levered exposure");
        }
        mrow(box, closed ? "At exit" : "At the mark", val(row, "value-now"),
             val(row, "side") === "SHORT" ? "buy-back cost" : "market value");
        mrow(box, "1R is", val(row, "risk"), "if the entry stop fills");

        /* The paper exit cost is not decoration: _close_trade charges half
         * the round trip adversely, so the confirm dialog quotes the P&L at
         * that FILL. Showing the mark-to-market number here and a smaller
         * one in the dialog is the third answer to "what did this make me"
         * that this block exists to prevent. */
        var cost = val(row, "exit-cost");
        var venue = val(row, "venue");
        /* A row from the shared portfolio book has neither venue nor a close
         * path — nothing in the platform can flatten it — so it gets neither
         * a modelled cost nor a promise about a dialog it will never see. */
        var closeable = venue === "LIVE" || venue === "PAPER";
        mrow(box, "Exit cost",
             cost ? (moneySign(cost) > 0 ? "-" + cost : cost) : "",
             !closeable ? "no close path for this row"
                        : (venue === "LIVE"
                           ? "live — the broker's is not modelled"
                           : "paper round trip, modelled"),
             cost && moneySign(cost) > 0 ? "down" : "");
        var net = val(row, "net-now");
        /* The bottom line, and the only line on this block an operator
         * acts on. It sat fifth among five identically weighted rows,
         * which on a card read this fast is the same as not being there —
         * hence is-net, which the page's own sheet gives a rule above it
         * and a size the eye lands on first. */
        mrow(box, closed ? "Booked" : "If closed now", moneySigned(net),
             closed ? "as the ledger has it"
                    : (closeable ? "what the close dialog says"
                                 : "no close path for this row"),
             moneyTone(net)).className += " is-net";

        /* R off the LEDGER once the trade is graded. While it is open the
         * head already carries live R against the entry stop, and printing
         * a booked R of 0 next to it would read as a scratched trade. */
        var rr = val(row, "realized-r");
        if (closed || rr) {
            mrow(box, "Booked R", rr ? rr + "R" : "", "graded on close",
                 moneyTone(rr));
        }
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
        cap(box, "levels · distance to each");
        known.concat(gaps).forEach(function (r) {
            var line = el(box, "div", "pos-pop-rung is-" + r.role);
            el(line, "span", "rl", r.label);
            var priceCell = el(line, "span", "rp",
                               r.price === null ? DASH : r.raw);
            if (r.price === null) priceCell.className += " sv-unknown";
            var note = "";
            if (r.role === "mark") {
                /* "now" said WHEN the number is from and nothing about what
                 * it means. The move since entry is the reason an operator
                 * looks at this rung at all, and it is signed by the PRICE:
                 * on a short a mark below entry is a fall that made money,
                 * so this deliberately disagrees with the P&L sign rather
                 * than one of the two lying about the market. */
                var mp = num(row, "mark-pct");
                note = r.price === null ? "no quote"
                     : (mp === null ? "now"
                        : (mp > 0 ? "+" : "") + mp.toFixed(2) + "% since entry");
            } else if (r.role === "entry") {
                var moved = num(row, "initial-stop");
                var stopNow = num(row, "stop");
                /* The stop the trade opened with is the R denominator and
                 * the risk that was actually accepted. When a trail has
                 * moved it, saying so is the difference between "this is
                 * still a 1R risk" and "this is now locked in". */
                note = (moved !== null && stopNow !== null && moved !== stopNow)
                    ? "stop moved from " + val(row, "initial-stop")
                    /* Not blank and not 0.00%: the entry is what every other
                     * percentage on this ladder is measured FROM, and saying
                     * so is more use than printing a zero. */
                    : "the reference";
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

        /* ── Head: what it is, and the one number that says how it is ──
         * The symbol is the card's title and its way to the instrument at
         * the same time, so it is an anchor wherever the row knows where
         * that page is. Where it does not — a row whose symbol never
         * resolved to an Instrument, which is what an empty
         * data-pos-instrument-href means — it stays plain text rather than
         * offering a link that would land on a 404. */
        var head = el(pop, "div", "pos-pop-head");
        var idBox = el(head, "div", "pos-pop-id");
        var symbol = val(row, "symbol");
        var instHref = val(row, "instrument-href");
        var symNode;
        if (instHref) {
            symNode = el(idBox, "a", "pos-pop-sym pos-sym-link", symbol || DASH);
            symNode.href = instHref;
            /* aria-hidden card, pointer-only: see the actions note below. */
            symNode.tabIndex = -1;
        } else {
            symNode = el(idBox, "div", "pos-pop-sym", symbol || DASH);
        }
        if (!symbol) symNode.className += " sv-unknown";
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

        /* ── The money: the change, then what it changed FROM ──
         * The head keeps the one-line answer — how much, and what percent.
         * The percentage is the row's own unrealised_pnl_pct and is never
         * recomputed here, for the same reason R is not: the card floats
         * over the column that prints it. What the caption adds is the one
         * thing that column cannot say — what the percentage is a percentage
         * OF, which is the committed capital where we know it and the
         * notional where the margin is the broker's secret. */
        var closed = val(row, "status") === "CLOSED";
        var pnl = num(row, "pnl"), pnlPct = num(row, "pnl-pct");
        var money = el(pop, "div", "pos-pop-money");
        var abs = el(money, "span", "pos-pop-pnl " + toneOf(pnl),
                     pnl === null ? DASH : signed(pnl, 2));
        if (pnl === null) abs.className += " sv-unknown";
        var pct = el(money, "span", "pos-pop-pnlpct " + toneOf(pnlPct),
                     pnlPct === null ? DASH : signed(pnlPct, 2) + "%");
        if (pnlPct === null) pct.className += " sv-unknown";
        el(money, "span", "pos-pop-money-cap",
           (closed ? "realised" : "unrealised")
           + (val(row, "committed") ? " · of capital committed"
              : (val(row, "notional") ? " · of notional" : "")));

        spark(pop, row);
        ledger(pop, row, closed);
        ladder(pop, row);

        /* ── Provenance: who opened it, on what evidence, when ── */
        var grid = el(pop, "div", "pos-pop-grid");
        cap(grid, "provenance");
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
        /* The size of 1R moved into the capital ledger above, where it sits
         * next to the money it is denominated in. Two copies of one number
         * on one card is how they start disagreeing. */
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
         * symbol link, its own DETAIL link and its own CLOSE button, all
         * three of which stay.
         *
         * Navigation first, the close LAST. The pointer travels to a page
         * many times for every once it flattens a position, and the two are
         * one 6px gap apart on a card that appears under a moving hand. */
        var actions = el(pop, "div", "pos-pop-actions");
        var href = val(row, "href");
        if (instHref) {
            var inst = el(actions, "a", "sr-pop-btn pos-pop-inst",
                          "▸ INSTRUMENT");
            inst.href = instHref;
            inst.tabIndex = -1;
        }
        if (href) {
            var open = el(actions, "a", "sr-pop-btn pos-pop-open",
                          "FULL DETAIL ›");
            open.href = href;
            open.tabIndex = -1;
        }
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

        /* The card teaches the three gestures once, where the operator is
         * already looking, and it says which of them this particular row
         * actually has — a row from the shared portfolio book has no trade
         * and therefore no detail page, and promising one is worse than
         * saying so. */
        el(pop, "div", "nf-pop-cta", href
            ? "click the row for its full detail · the symbol for the instrument"
            : (instHref
               ? "no trade detail for this one — it comes from the portfolio "
                 + "book, not a bot trade · click the symbol for the instrument"
               : "no page for this one — it comes from the portfolio book, "
                 + "not a bot trade"));
    }

    /* The row is a <tr>, not an anchor, so every navigation convention a
     * browser hands a link for free has to be honoured here by hand. A
     * modifier-click means "open it somewhere else" on every link on this
     * platform, and replacing the operator's whole book with the page they
     * asked to open BESIDE it is the kind of small theft that teaches them
     * to stop trying. Falls through to the same-tab navigation when the
     * browser refuses the new tab, so the gesture never ends in nothing
     * happening at all. */
    function follow(e, href) {
        if (e.metaKey || e.ctrlKey || e.shiftKey) {
            /* `w.open(href, "_blank", "noopener")` ALWAYS returns null —
             * that is specified, not a failure: a window opened with
             * noopener is deliberately unreachable from the opener, so
             * there is no handle to hand back. Testing the return value
             * for success therefore never succeeded, and the fall-through
             * ran on every modifier-click: the page opened in a new tab
             * AND this tab left the book behind. The exact theft the
             * comment above says it prevents, on every single use.
             *
             * So: open it, and trust it. A popup blocker can still refuse
             * — but a blocked window is also indistinguishable from a
             * noopener window here, and of the two possible wrongs,
             * "nothing happened, try again" costs the operator less than
             * "your book is gone". */
            w.open(href, "_blank", "noopener");
            return;
        }
        w.location.assign(href);
    }

    /* Anything inside a link or a button on the row already has a
     * destination of its own — the symbol goes to the instrument, the
     * DETAIL link to this same page, CLOSE to the confirm dialog — and a
     * row handler that also navigated would race the browser for it. This
     * one guard is what keeps the three gestures three. */
    function rowNav(row, e) {
        var href = val(row, "href");
        if (!href) return;
        if (e.target.closest("a, button")) return;
        follow(e, href);
    }

    w.SV.dwell.attach({
        rows: ROW,
        className: "nf-pop pos-pop",
        build: build,
        /* Click opens the trade's full detail. Not on a control, and not
         * while a selection is standing, which SV.dwell has checked. */
        click: rowNav,
        /* Touch has no dwell, so the tap has to be the whole interaction. */
        tap: rowNav
    });
})(window, document);
