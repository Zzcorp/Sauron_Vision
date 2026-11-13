/* Sauron Vision: the desk's keys and disclosures on /positions/ (UI batch
 * B7, 2026-11-13).
 *
 * The board the operator approved ("amazing work, bravo, I need it
 * fast!!") draws the keyboard path: J and K move from row to row, Enter
 * opens the focused row's Orc line, Tab reaches its CLOSE. This script
 * does exactly that and nothing else:
 *
 *   - a row's disclosure (.pd-disc) shows or hides its detail row, and says
 *     so in aria-expanded;
 *   - J / K move the keys' row (tr.is-focus) down and up, and move the
 *     focus to that row's disclosure, so Tab goes on to its links and its
 *     CLOSE; Enter on the row (not on a control) opens its detail;
 *   - the live refresh rebuilds the table (templates/_partials/
 *     live_region.html): an open detail and the keys' row are put back
 *     after each swap (sv:live-swapped), by the row's own key.
 *
 * Nothing here closes, posts or asks the server anything. A key never
 * presses CLOSE: closing keeps its dialog and its PIN (base.html's
 * closeFlow). Keys are ignored while typing, with a modifier held, and
 * while a dialog or the level editor is open.
 */
(function (w, d) {
    "use strict";
    if (w.SVPositionsDesk) return;

    var open = {};          /* row key -> true: details the operator opened */
    var focusKey = null;    /* the keys' row */

    function each(list, fn) { Array.prototype.forEach.call(list || [], fn); }
    function rows() {
        return d.querySelectorAll(".pd-table tbody tr[data-sv-position-row]");
    }
    function detailOf(btn) {
        var id = btn && btn.getAttribute("aria-controls");
        return id ? d.getElementById(id) : null;
    }
    function keyOf(tr) { return tr ? tr.getAttribute("data-pd-key") : null; }

    function setOpen(btn, on) {
        var det = detailOf(btn);
        if (!det) return;
        btn.setAttribute("aria-expanded", on ? "true" : "false");
        det.hidden = !on;
        var key = det.getAttribute("data-pd-key");
        if (key) {
            if (on) open[key] = true;
            else delete open[key];
        }
        var label = btn.getAttribute("aria-label") || "";
        btn.setAttribute("aria-label", on ? label.replace(/^Show/, "Hide")
                                          : label.replace(/^Hide/, "Show"));
    }

    function toggle(btn) {
        setOpen(btn, btn.getAttribute("aria-expanded") !== "true");
    }

    function focusRow(tr, moveFocus) {
        each(d.querySelectorAll(".pd-table tr.is-focus"), function (r) {
            if (r !== tr) r.classList.remove("is-focus");
        });
        if (!tr) { focusKey = null; return; }
        tr.classList.add("is-focus");
        focusKey = keyOf(tr);
        if (moveFocus) {
            var btn = tr.querySelector(".pd-disc");
            if (btn && btn.focus) btn.focus({ preventScroll: true });
            if (tr.scrollIntoView) tr.scrollIntoView({ block: "nearest" });
        }
    }

    /* Back after a swap: the region is new markup, every detail hidden and
       no row focused; the record says which to restore. */
    function reapply() {
        each(d.querySelectorAll(".pd-table .pd-disc"), function (btn) {
            var det = detailOf(btn);
            var key = det && det.getAttribute("data-pd-key");
            if (key && open[key]) setOpen(btn, true);
        });
        if (focusKey) {
            var tr = d.querySelector('.pd-table tr[data-sv-position-row][data-pd-key="' +
                                     focusKey.replace(/["\\]/g, "") + '"]');
            if (tr) tr.classList.add("is-focus");
            else focusKey = null;
        }
    }

    function busy() {
        return !!d.querySelector(".sv-dialog.is-open, .lvl-dlg");
    }

    function typing(t) {
        if (!t || !t.closest) return false;
        return !!t.closest("input, textarea, select, [contenteditable=''], [contenteditable='true']");
    }

    d.addEventListener("click", function (e) {
        var btn = e.target && e.target.closest && e.target.closest(".pd-table .pd-disc");
        if (!btn) return;
        /* The row's own click opens the trade's page (sv-position-card.js):
           the disclosure is its own gesture. */
        e.preventDefault();
        e.stopPropagation();
        toggle(btn);
        focusRow(btn.closest("tr"), false);
    }, true);

    d.addEventListener("keydown", function (e) {
        if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
        if (typing(e.target) || busy()) return;
        var k = e.key;
        if (k !== "j" && k !== "J" && k !== "k" && k !== "K" && k !== "Enter" && k !== "Escape") return;
        var list = rows();
        if (!list.length) return;
        var cur = d.querySelector(".pd-table tr[data-sv-position-row].is-focus");
        var i = Array.prototype.indexOf.call(list, cur);
        if (k === "j" || k === "J") {
            e.preventDefault();
            focusRow(list[i < 0 ? 0 : Math.min(i + 1, list.length - 1)], true);
        } else if (k === "k" || k === "K") {
            e.preventDefault();
            focusRow(list[i <= 0 ? 0 : i - 1], true);
        } else if (k === "Enter") {
            /* Enter on a control is the control's own (a link, a button:
               the disclosure itself toggles by its click). */
            var t = e.target;
            if (!cur || (t && t.closest && t.closest("a, button") &&
                         !(t.closest(".pd-disc") && t.closest("tr") === cur))) return;
            if (t && t.closest && t.closest(".pd-disc")) return;   /* its click does it */
            var btn = cur.querySelector(".pd-disc");
            if (btn) { e.preventDefault(); toggle(btn); }
        } else if (k === "Escape" && cur) {
            focusRow(null, false);
        }
    });

    d.addEventListener("sv:live-swapped", reapply);

    w.SVPositionsDesk = { reapply: reapply, open: function () { return Object.keys(open); } };
})(window, document);
