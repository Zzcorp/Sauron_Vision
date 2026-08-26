/* sv-gate.js — the second gate's nerves, shared by both lock surfaces.
 *
 * /locked/ and the in-app idle overlay each own their PIN plumbing (one
 * is a standalone page, the other cannot reload the app underneath it),
 * but the FEEL has to be identical — two lock screens with two
 * personalities teach the wrong reflex on one of them. So the reactions
 * live here, driven by what is already in the DOM: the filled boxes.
 *
 * It reads, never writes: the boxes remain the source of truth, the
 * keypad simply synthesises the keystroke the keyboard would have sent.
 * That way a digit typed and a digit pressed travel exactly one path.
 */
(function (w, d) {
  "use strict";

  var MIN = 4;    /* the submit threshold both surfaces enforce */

  function boxes(root) {
    return [].slice.call(root.querySelectorAll("[data-lk-pin],[data-il-pin]"));
  }

  function scope(el) {
    return el.closest(".lk-card") || el.closest(".il-overlay") || d;
  }

  /* The ring closes as the PIN builds; the eye brightens with it. */
  function paint(root) {
    var iris = root.querySelector("[data-gate-iris]");
    if (!iris) return;
    var filled = boxes(root).filter(function (b) { return b.value; }).length;
    /* The ring measures progress to the SUBMIT threshold, not to some
       imagined length: boxes only exist once filled, so the DOM can
       never tell us how long this operator's PIN is. Full ring means
       "long enough to try", which is a thing the gate actually knows. */
    iris.setAttribute("data-gate-lit", String(Math.min(filled, 8)));
    var ring = iris.querySelector("[data-gate-ring]");
    if (ring) {
      var frac = Math.min(filled / MIN, 1);
      ring.style.strokeDashoffset = String(289 - 289 * frac);
    }
    iris.classList.toggle("is-open", filled >= MIN);
  }

  /* A refusal is felt, not just read: the eye recoils with the row. */
  function refuse(root) {
    var iris = root.querySelector("[data-gate-iris]");
    if (!iris) return;
    /* Both surfaces clear the pad before showing the error, so repaint
       FIRST — a closed ring above an empty pad and an "incorrect PIN"
       line is three widgets telling three different stories. */
    paint(root);
    iris.classList.remove("is-wrong");
    void iris.offsetWidth;
    iris.classList.add("is-wrong");
    setTimeout(function () { iris.classList.remove("is-wrong"); }, 600);
  }

  /* The keypad sends the keystroke the keyboard would have sent, so the
     two inputs cannot drift apart. */
  function press(key, root) {
    var target = root.querySelector("[data-lk-pin],[data-il-pin]") || d.body;
    var ev;
    try {
      ev = new KeyboardEvent("keydown", {
        key: key, bubbles: true, cancelable: true });
    } catch (e) {
      return;
    }
    /* ALWAYS on a pin box, never on the pressed button: clicking a key
       focuses it in Chrome/Edge, and BOTH routers deliberately ignore
       keystrokes whose target is a button (so Enter on Disconnect
       submits the form instead of the PIN). Dispatching on the button
       therefore posted the digit into a listener that discards it —
       the keypad was inert on exactly the touch machines it exists
       for. Both routers fill the first EMPTY box regardless of target,
       so the box is always the right address. */
    target.dispatchEvent(ev);
  }

  function ripple(btn, ev) {
    var r = d.createElement("span");
    r.className = "gate-ripple";
    var box = btn.getBoundingClientRect();
    var size = Math.max(box.width, box.height);
    r.style.width = r.style.height = size + "px";
    r.style.left = ((ev && ev.clientX ? ev.clientX - box.left : box.width / 2)) + "px";
    r.style.top = ((ev && ev.clientY ? ev.clientY - box.top : box.height / 2)) + "px";
    btn.appendChild(r);
    setTimeout(function () { if (r.parentNode) r.parentNode.removeChild(r); }, 460);
  }

  d.addEventListener("click", function (e) {
    var key = e.target.closest && e.target.closest("[data-gate-key]");
    var back = e.target.closest && e.target.closest("[data-gate-back]");
    var clear = e.target.closest && e.target.closest("[data-gate-clear]");
    var btn = key || back || clear;
    if (!btn) return;
    e.preventDefault();
    ripple(btn, e);
    var root = scope(btn);
    if (key) press(key.getAttribute("data-gate-key"), root);
    else if (back) press("Backspace", root);
    else {
      /* Clear is Backspace all the way down — one path, again. */
      for (var i = 0; i < 8; i++) press("Backspace", root);
    }
    /* AFTER the press. The capture-phase repaint below runs before this
       handler, so relying on it left every reaction one press behind. */
    paint(root);
  });

  /* Repaint on every change to the boxes, whoever caused it. */
  /* Scoped to the gate, not to the document: the overlay markup rides
     on every authenticated page, and a fallback to `document` meant
     every keystroke in every search box walked the whole tree to
     repaint a hidden lock screen. */
  ["input", "keyup"].forEach(function (ev) {
    d.addEventListener(ev, function (e) {
      var t = e.target;
      if (!t || !t.closest) return;
      var root = t.closest(".lk-card") || t.closest(".il-overlay");
      if (root) paint(root);
    }, true);
  });

  /* A wrong PIN clears the boxes and reveals the error — watch for it
     rather than asking either surface to call us. */
  d.addEventListener("DOMContentLoaded", function () {
    ["lkError", "ilError"].forEach(function (id) {
      var el = d.getElementById(id);
      if (!el || !w.MutationObserver) return;
      new w.MutationObserver(function () {
        if (!el.hidden && el.textContent) refuse(scope(el));
      }).observe(el, { attributes: true, childList: true, subtree: true });
    });
    d.querySelectorAll("[data-gate-iris]").forEach(function (iris) {
      paint(scope(iris));
    });
  });
})(window, document);
