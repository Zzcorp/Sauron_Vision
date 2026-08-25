/* Headband news dwell-cards — SV.dwell's fifth CLIENT, not a fifth
 * implementation: the engine in sv-notif-card.js already owns hover
 * timing, placement, touch fallback and the aria-hidden discipline.
 * This file only says what a NEWS row's card contains.
 *
 * A second's hover on a headline answers the question the one-line row
 * cannot: what is this actually about (summary), who says so (source),
 * how the machines read it (sentiment score), and how stale it is. A
 * tap on touch — where no card can exist — opens the news page, the one
 * thing left to do.
 */
(function (w, d) {
  "use strict";

  function el(parent, tag, cls, text) {
    var node = d.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    parent.appendChild(node);
    return node;
  }

  function age(iso) {
    if (!iso) return "";
    var s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (!isFinite(s) || s < 0) return "";
    if (s < 90) return Math.round(s) + "s ago";
    if (s < 5400) return Math.round(s / 60) + "m ago";
    if (s < 172800) return Math.round(s / 3600) + "h ago";
    return Math.round(s / 86400) + "d ago";
  }

  function build(row, pop) {
    var ds = row.dataset;
    el(pop, "div", "nf-pop-title", ds.nwTitle || "—");

    var meta = el(pop, "div", "nf-pop-meta");
    el(meta, "span", null, ds.nwSource || "unknown source");
    var when = age(ds.nwAt);
    if (when) el(meta, "span", null, " · " + when);
    if (ds.nwSent) {
      var score = parseFloat(ds.nwSent);
      var tone = score > 0.15 ? "up" : score < -0.15 ? "down" : "";
      el(meta, "span", "nf-pop-sent " + tone,
         " · sentiment " + (score > 0 ? "+" : "") + ds.nwSent);
    }

    el(pop, "div", "nf-pop-summary",
       ds.nwSummary ||
       "No summary yet — the analyst pass has not reached this article.");
    /* The verb matches the audience: hover devices (the only ones ever
       shown this card) click; the tap wording belonged to a card no touch
       device can open. */
    el(pop, "div", "nf-pop-cta",
       (w.SV && w.SV.dwell && w.SV.dwell.hoverable ? "click" : "tap")
       + " opens the news page");
  }

  /* One action for both input worlds — the engine routes desktop rows
     through `click` and touch rows through `tap`, and an advertised
     action that only half of them could reach was a lie to the other
     half. Routes to the internal news page, never the article's own
     domain: a dwell must not teleport the operator off-platform. */
  function follow(row, e) {
    if (e && e.target && e.target.closest
        && e.target.closest("a, button")) return;
    if (e && (e.ctrlKey || e.metaKey || e.button === 1)) {
      w.open("/news/", "_blank");
      return;
    }
    w.location.assign("/news/");
  }

  /* The dropdown hosting these rows is portalled to <body> with its own
     120ms leave-grace (base.html stamps _svCancelHide/_svHideSoon on it).
     Stepping onto the card exits the dropdown — without this bridge the
     whole NEWS panel folded 120ms later, underneath the card. */
  function bridge(inst) {
    var region = d.querySelector('[data-sv-live="hb-news-detail"]');
    var dd = region && region.closest && region.closest(".ip-dropdown");
    if (!dd || !inst || !inst.pop) return;
    /* MOUSE family, same as the portal it bridges — not pointer. The
       browser fires every pointer boundary event BEFORE any mouse one,
       so a pointerenter bridge cancelled the hide first and the
       dropdown's own mouseleave re-armed it a beat later: panel and
       card folded 120ms after the operator arrived on the card. */
    inst.pop.addEventListener("mouseenter", function () {
      if (dd._svCancelHide) dd._svCancelHide();
    });
    inst.pop.addEventListener("mouseleave", function (e) {
      if (e.relatedTarget && dd.contains(e.relatedTarget)) return;
      if (dd._svHideSoon) dd._svHideSoon();
    });
  }

  function boot() {
    if (!w.SV || !w.SV.dwell) return; /* engine absent: rows still work */
    var inst = w.SV.dwell.attach({
      rows: ".hb-news-row",
      className: "nf-pop nc-pop",
      /* No delay override: the engine's default IS the platform's one hover
         beat (window.SV_HOVER_BEAT_MS). This client used to ask for its own
         second, which made the news rows the slowest card on the page. */
      build: build,
      click: follow,
      tap: follow,
    });
    bridge(inst);
  }

  /* Deferred scripts run in order, so the engine exists by now — but the
     guard keeps a reordering from becoming a silent feature death. */
  boot();
})(window, document);
