/* Editing a stop or a target where the operator reads it.
 *
 * A money action, so it borrows the close flow's rules rather than
 * inventing its own: the PIN for LIVE rows only, refusals shown as the
 * sentence the server wrote rather than a status code, and nothing
 * optimistic — the cell changes only after the server says it did.
 *
 * The server owns every check. This dialog deliberately does NOT
 * pre-validate against the mark: the price it holds is as old as the
 * page, and a refusal computed from a stale number is worse than no
 * refusal — it would block a correct edit and teach the operator that
 * the validation is noise.
 */
(function (w, d) {
    "use strict";

    var dlg = null;

    function close() {
        if (dlg && dlg.parentNode) dlg.parentNode.removeChild(dlg);
        dlg = null;
        d.removeEventListener("keydown", onKey, true);
    }

    function onKey(e) {
        if (e.key === "Escape") { close(); }
    }

    function csrf() {
        var el = d.querySelector("[name=csrfmiddlewaretoken]");
        return el ? el.value : "";
    }

    function field(parent, label, id, value, type, step) {
        var l = d.createElement("label");
        l.textContent = label;
        l.setAttribute("for", id);
        parent.appendChild(l);
        var i = d.createElement("input");
        i.type = type || "number";
        i.id = id;
        if (step) { i.step = step; i.min = "0"; }
        if (type === "password") { i.autocomplete = "off"; }
        i.value = value || "";
        parent.appendChild(i);
        return i;
    }

    function open(btn) {
        close();
        var data = btn.dataset;
        var isLive = data.lvlLive === "1";
        var brokerHeld = data.lvlProtected === "1";
        var dp = parseInt(data.lvlDecimals || "2", 10);
        if (!isFinite(dp) || dp < 0 || dp > 10) { dp = 2; }
        var step = Math.pow(10, -dp).toFixed(dp);

        dlg = d.createElement("div");
        dlg.className = "lvl-dlg";
        dlg.setAttribute("role", "dialog");

        var h = d.createElement("h4");
        h.textContent = (data.lvlSide || "") + " " + (data.lvlSymbol || "")
                        + " · LEVELS";
        dlg.appendChild(h);

        field(dlg, "STOP", "lvlStop", data.lvlStop, "number", step);
        field(dlg, "TARGET", "lvlTarget", data.lvlTarget, "number", step);
        if (isLive) { field(dlg, "TRADING PIN", "lvlPin", "", "password"); }

        if (brokerHeld) {
            var warn = d.createElement("div");
            warn.className = "lvl-warn";
            warn.textContent = "This stop rests AT THE BROKER. It moves "
                + "there first — if the broker refuses, nothing changes "
                + "and the position stays protected at its old level.";
            dlg.appendChild(warn);
        }

        var err = d.createElement("div");
        err.className = "lvl-err";
        err.hidden = true;
        dlg.appendChild(err);

        var row = d.createElement("div");
        row.className = "lvl-dlg-row";
        var cancel = d.createElement("button");
        cancel.type = "button";
        cancel.textContent = "CANCEL";
        var save = d.createElement("button");
        save.type = "button";
        save.className = "primary";
        save.textContent = "SAVE";
        row.appendChild(cancel);
        row.appendChild(save);
        dlg.appendChild(row);

        d.body.appendChild(dlg);
        place(btn);

        cancel.addEventListener("click", close);
        save.addEventListener("click", function () {
            submit(btn, data.lvlTrade, err, save);
        });
        dlg.addEventListener("keydown", function (e) {
            if (e.key === "Enter") { e.preventDefault(); save.click(); }
        });
        var first = dlg.querySelector("#lvlStop");
        if (first) { first.focus(); first.select(); }
        d.addEventListener("keydown", onKey, true);
    }

    /* Flip above the cell when there is no room below, and clamp to the
     * viewport: these rows sit near the bottom of a long table and a
     * dialog opening off-screen is a dialog nobody can cancel. */
    function place(btn) {
        var r = btn.getBoundingClientRect();
        var box = dlg.getBoundingClientRect();
        var left = Math.max(8, Math.min(w.innerWidth - box.width - 8,
                                        r.right - box.width));
        var top = (r.bottom + box.height + 8 < w.innerHeight)
            ? r.bottom + 6
            : Math.max(8, r.top - box.height - 6);
        dlg.style.left = left + "px";
        dlg.style.top = top + "px";
    }

    function submit(btn, tradeId, err, save) {
        var stop = (dlg.querySelector("#lvlStop").value || "").trim();
        var target = (dlg.querySelector("#lvlTarget").value || "").trim();
        var pinEl = dlg.querySelector("#lvlPin");
        var body = {
            stop: stop || null,
            target: target || null,
            /* An emptied box is a DELETED target, not an unchanged one —
             * otherwise there is no way to remove one from here. */
            clear_target: !target && !!btn.dataset.lvlTarget
        };
        if (pinEl) { body.pin = pinEl.value; }

        save.disabled = true;
        save.textContent = "SAVING…";

        w.fetch("/positions/" + tradeId + "/levels/", {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": csrf()
            },
            body: JSON.stringify(body)
        }).then(function (res) {
            return res.json().then(function (j) {
                return { ok: res.ok, body: j };
            });
        }).then(function (out) {
            if (!out.ok) {
                err.textContent = out.body.error || "Refused.";
                err.hidden = false;
                save.disabled = false;
                save.textContent = "SAVE";
                return;
            }
            close();
            /* Repainted from the server, never optimistically: a cell
             * showing a level the broker never accepted is the exact
             * failure this whole path exists to avoid. */
            if (w.svLiveRefresh) { w.svLiveRefresh(); }
            else { w.location.reload(); }
        }).catch(function () {
            err.textContent = "The request did not reach the server. "
                + "Nothing was changed.";
            err.hidden = false;
            save.disabled = false;
            save.textContent = "SAVE";
        });
    }

    d.addEventListener("click", function (e) {
        var btn = e.target.closest && e.target.closest(".lvl-edit");
        if (btn) {
            e.preventDefault();
            e.stopPropagation();
            open(btn);
            return;
        }
        if (dlg && !dlg.contains(e.target)) { close(); }
    });
})(window, document);
