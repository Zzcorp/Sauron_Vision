/* Gollum — the guide who knows the way to Mordor.
 *
 * A creature at the bottom-left corner who knows every road in the
 * platform. Type a word and he lists the pages and sections it leads
 * to; leave things unseen and he fidgets, then whispers what changed.
 * He never acts — he only points. Sauron acts.
 *
 * Three sources, no fetches of his own:
 *   - the sidebar's nav links (labels, hrefs, page ids) — the roads
 *   - GOLLUM_LORE below — the sections, popups and hidden corners the
 *     sidebar cannot name (a headband cell, a popup, a keyboard key)
 *   - the nav-activity poll (static/js/sv-nav-activity.js) — it now
 *     dispatches sv:nav-activity with the unseen map, so Gollum learns
 *     what the dots learn without a second poll
 *
 * Keyboard: "/" (outside inputs) opens him; Esc closes;
 * arrows walk the results; Enter follows.
 */
(function (w, d) {
  "use strict";

  /* Sections and corners the sidebar cannot name. `page` binds an
     entry to a nav page id so its dot lights the entry too. */
  var GOLLUM_LORE = [
    { label: "Strategist briefing · today's read", href: "/briefing/", page: "briefing",
      words: "briefing strategist posture defensive aggressive balanced watchlist ideas morning report" },
    { label: "Briefing history · past mornings", href: "/briefing/", page: "briefing",
      words: "briefing history previous days posture mix cost" },
    { label: "Sauron's Mind · latest synthesis", href: "/brain/", page: "brain",
      words: "brain synthesis regime concerns theme pressures rule overlay narrative mind" },
    { label: "Brain concerns → actions", href: "/brain/#concerns",
      words: "concern action propose pause rule size cut theme saturation drift" },
    { label: "Ask Sauron · research chat", href: "/research/", page: "research",
      words: "ask sauron question research chat answer palantir orb" },
    { label: "Hypothesis market", href: "/hypotheses/", page: "hypotheses",
      words: "hypothesis hypotheses market claims graded refuted confirmed unresolvable critic trust" },
    { label: "Critic votes & receipts", href: "/hypotheses/", page: "hypotheses",
      words: "critic dissent co-sign vote receipts track record streak" },
    { label: "Signals rail (right edge)", href: "/signals/", page: "signals",
      words: "signals rail cards hover popup take trade pass star" },
    { label: "Positions · open book", href: "/positions/", page: "positions",
      words: "positions open book long short close manual pnl r-multiple stop target" },
    { label: "Close all positions", href: "/positions/close-all/preview/",
      words: "close all flatten kill everything positions" },
    { label: "Portfolio · capital & P&L", href: "/portfolio/", page: "portfolio",
      words: "portfolio capital cash pools used free pnl equity curve" },
    { label: "Headband · bottom cells", href: "#headband",
      words: "headband bottom bar cells portfolio positions open pnl bot news funding volatility drawdown liquidation watchlist" },
    { label: "Headband · OPEN P&L cell", href: "#headband",
      words: "open pnl profit loss cell headband bigger" },
    { label: "Headband · NEWS popup", href: "#headband",
      words: "news popup headband hover dwell card headline summary sentiment" },
    { label: "News & sentiment feed", href: "/news/", page: "news",
      words: "news sentiment feed articles headlines breaking keywords" },
    { label: "Instruments & quotes", href: "/instruments/",
      words: "instruments quotes symbols tickers markets open closed session exchange" },
    { label: "Instrument chart · positions on chart", href: "/instruments/",
      words: "chart candles indicators rsi sma ema bollinger vwap heikin ashi log scale fullscreen entries markers" },
    { label: "Opportunities scanner", href: "/opportunities/", page: "opportunities",
      words: "opportunities scanner setups flags scanned" },
    { label: "Generated strategies · approve", href: "/generated/", page: "generated",
      words: "generated strategies approve proposals generator" },
    { label: "Strategies", href: "/strategies/",
      words: "strategies rules setups evaluators promotion stage" },
    { label: "Rule controls · pause / reduce", href: "/rule-control/",
      words: "rule controls pause paused reduce weight allocator actuator" },
    { label: "Risk depth · VaR, correlation, Kelly", href: "/risk/",
      words: "risk depth var correlation kelly drawdown sharpe" },
    { label: "Bot program", href: "/bot/",
      words: "bot program running armed live paper kill switch circuit breaker" },
    { label: "Asset bots · per class", href: "/asset-bots/",
      words: "asset bots configs forex crypto stock commodity options capital pool enable disable manual" },
    { label: "Trade forensics", href: "/forensics/",
      words: "forensics trade audit fills history receipts" },
    { label: "System health", href: "/system-health/",
      words: "system health components scrapers pipelines status green red" },
    { label: "Admin panel · HQ", href: "/admin-dashboard/",
      words: "admin hq panel components seed credentials ibkr oanda alpaca actuator queue investors" },
    { label: "All Books · cross-book concentration", href: "/admin-dashboard/books/",
      words: "all books overview concentration crowded cross-book admin" },
    { label: "Investor access · read-only windows", href: "/admin-dashboard/#investors",
      words: "investor access read-only window friends share account" },
    { label: "Notifications inbox", href: "/notifications/",
      words: "notifications inbox bell alerts unread" },
    { label: "Profile · PIN, theme, preferences", href: "/profile/",
      words: "profile pin theme light dark preferences telegram email quiet hours briefing push" },
    { label: "Lock the screen", href: "#lock",
      words: "lock screen pin idle sleep gate" },
    { label: "Keyboard · ? asks Sauron, / finds the way", href: "#keys",
      words: "keyboard shortcuts keys question mark slash escape" },
  ];

  var fab = d.getElementById("gollumFab");
  var dlg = d.getElementById("gollumDialog");
  if (!fab || !dlg) return;
  var input = dlg.querySelector("[data-gollum-input]");
  var list = dlg.querySelector("[data-gollum-results]");
  var whisper = dlg.querySelector("[data-gollum-whisper]");
  var unseen = {};
  var open = false;
  var cursor = -1;
  var rows = [];

  /* ── the roads: sidebar links + lore ─────────────────────────────── */
  function roads() {
    var out = [];
    d.querySelectorAll(".sidebar-nav .nav-link").forEach(function (a) {
      var label = (a.querySelector(".label-text") || a).textContent.trim();
      if (!label) return;
      out.push({ label: label, href: a.getAttribute("href") || "#",
                 page: a.getAttribute("data-nav-id") || "",
                 words: label.toLowerCase(), kind: "page" });
    });
    GOLLUM_LORE.forEach(function (l) {
      out.push({ label: l.label, href: l.href, page: l.page || "",
                 words: (l.words + " " + l.label).toLowerCase(),
                 kind: "section" });
    });
    return out;
  }

  /* Fuzzy but honest: every query token must land somewhere in the
     entry's words (prefix or substring); earlier and shorter matches
     score higher, and an unseen page climbs. No token → no row. */
  function score(entry, tokens) {
    var s = 0;
    for (var i = 0; i < tokens.length; i++) {
      var t = tokens[i];
      var at = entry.words.indexOf(t);
      if (at < 0) return -1;
      s += (at === 0 || entry.words[at - 1] === " ") ? 3 : 1;
      if (entry.label.toLowerCase().indexOf(t) === 0) s += 2;
    }
    if (entry.page && unseen[entry.page]) s += 2;
    return s;
  }

  function search(q) {
    var tokens = q.toLowerCase().split(/\s+/).filter(Boolean);
    var all = roads();
    if (!tokens.length) {
      /* Nothing typed: show what he has noticed, then the main roads. */
      var lit = all.filter(function (e) { return e.page && unseen[e.page]; });
      return lit.concat(all.filter(function (e) { return e.kind === "page"; })
                            .slice(0, 8)).slice(0, 10);
    }
    return all.map(function (e) { return { e: e, s: score(e, tokens) }; })
              .filter(function (x) { return x.s >= 0; })
              .sort(function (a, b) { return b.s - a.s; })
              .slice(0, 10)
              .map(function (x) { return x.e; });
  }

  function paint(entries) {
    list.textContent = "";
    rows = [];
    cursor = -1;
    if (!entries.length) {
      var none = d.createElement("div");
      none.className = "gl-empty";
      none.textContent = "No road by that name, precious. Try another word.";
      list.appendChild(none);
      return;
    }
    entries.forEach(function (e) {
      var a = d.createElement("a");
      a.className = "gl-row gl-row--" + e.kind;
      a.href = e.href;
      var k = d.createElement("span");
      k.className = "gl-kind";
      k.textContent = e.kind === "page" ? "PAGE" : "SECTION";
      a.appendChild(k);
      var l = d.createElement("span");
      l.className = "gl-label";
      l.textContent = e.label;
      a.appendChild(l);
      if (e.page && unseen[e.page]) {
        var dot = d.createElement("span");
        dot.className = "gl-dot";
        dot.title = "Changed since you last looked";
        a.appendChild(dot);
      }
      a.addEventListener("click", function (ev) { follow(e, ev); });
      list.appendChild(a);
      rows.push(a);
    });
  }

  /* Anchored roads (#headband, #lock, #keys) do not navigate — they
     point: the headband glows, the lock engages, the keys are told. */
  function follow(e, ev) {
    if (e.href === "#headband") {
      ev.preventDefault();
      var band = d.querySelector(".info-panel-wrap");
      if (band) {
        band.classList.remove("gl-pointed");
        void band.offsetWidth;
        band.classList.add("gl-pointed");
      }
      close();
      return;
    }
    if (e.href === "#lock") {
      ev.preventDefault();
      var lockBtn = d.getElementById("lockNowBtn");
      close();
      if (lockBtn) lockBtn.click();
      return;
    }
    if (e.href === "#keys") {
      ev.preventDefault();
      say("? asks Sauron · / calls me · Ctrl+K opens the orb · Esc sends us away.");
      return;
    }
    close();
  }

  function say(text) {
    whisper.textContent = text;
    whisper.hidden = !text;
  }

  /* ── open / close ────────────────────────────────────────────────── */
  function openDialog() {
    if (open) return;
    open = true;
    dlg.hidden = false;
    fab.classList.add("is-open");
    fab.setAttribute("aria-expanded", "true");
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { dlg.classList.add("is-in"); });
    });
    input.value = "";
    paint(search(""));
    var n = Object.keys(unseen).filter(function (k) { return unseen[k]; }).length;
    say(n ? "Things have changed while you looked away, precious — "
            + n + " place" + (n === 1 ? "" : "s") + ". They are lit."
          : "Where to, precious? Type a word.");
    setTimeout(function () { try { input.focus({ preventScroll: true }); } catch (e) {} }, 30);
  }

  function close() {
    if (!open) return;
    open = false;
    dlg.classList.remove("is-in");
    fab.classList.remove("is-open");
    fab.setAttribute("aria-expanded", "false");
    setTimeout(function () { if (!open) dlg.hidden = true; }, 220);
  }

  fab.addEventListener("click", function () { open ? close() : openDialog(); });
  dlg.querySelector("[data-gollum-close]").addEventListener("click", close);

  input.addEventListener("input", function () { paint(search(input.value)); });

  dlg.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { e.preventDefault(); close(); fab.focus(); return; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!rows.length) return;
      e.preventDefault();
      cursor = (cursor + (e.key === "ArrowDown" ? 1 : -1) + rows.length) % rows.length;
      rows.forEach(function (r, i) { r.classList.toggle("is-cursor", i === cursor); });
      /* Keep typing in the field, but bring the row the cursor names
         into the 300px scrollport — a highlight nobody can see is none. */
      try { rows[cursor].scrollIntoView({ block: "nearest" }); }
      catch (e) { try { rows[cursor].scrollIntoView(false); } catch (e2) {} }
      input.focus({ preventScroll: true });
      return;
    }
    if (e.key === "Enter" && cursor >= 0 && rows[cursor]) {
      e.preventDefault();
      rows[cursor].click();
    }
  });

  /* "/" opens him from anywhere that is not a field; Ctrl+K too. */
  d.addEventListener("keydown", function (e) {
    var t = e.target;
    var typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA"
                       || t.isContentEditable);
    /* Ctrl+K is the Palantír's chord (base.html routes it to Ask
       Sauron). Two owners on one chord means neither works. */
    if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault(); openDialog();
    }
  });

  d.addEventListener("click", function (e) {
    if (!open) return;
    if (dlg.contains(e.target) || fab.contains(e.target)) return;
    close();
  });

  /* ── what the dots learn, he learns ──────────────────────────────── */
  var nudged = 0;
  d.addEventListener("sv:nav-activity", function (e) {
    var pages = (e.detail && e.detail.pages) || {};
    unseen = pages;
    var n = Object.keys(pages).filter(function (k) { return pages[k]; }).length;
    fab.classList.toggle("has-unseen", n > 0);
    var badge = fab.querySelector("[data-gollum-count]");
    if (badge) { badge.textContent = n ? String(n) : ""; badge.hidden = !n; }
    /* He fidgets when something new appears, and whispers ONCE per
       change in the count — a creature that nags every 45 seconds is
       one you learn to ignore. */
    if (n > nudged) {
      fab.classList.remove("is-fidget");
      void fab.offsetWidth;
      fab.classList.add("is-fidget");
      if (!open) {
        var bubble = d.getElementById("gollumBubble");
        if (bubble) {
          bubble.textContent = n === 1 ? "Something changed, precious…"
                                       : n + " places changed, precious…";
          bubble.hidden = false;
          bubble.classList.remove("is-in");
          void bubble.offsetWidth;
          bubble.classList.add("is-in");
          clearTimeout(bubble._t);
          bubble._t = setTimeout(function () {
            bubble.classList.remove("is-in");
            setTimeout(function () { bubble.hidden = true; }, 260);
          }, 6000);
        }
      }
    }
    nudged = n;
    if (open) paint(search(input.value));
  });

  /* The idle lock closes everything floating. */
  d.addEventListener("sv:pin-locked", close);
})(window, document);
