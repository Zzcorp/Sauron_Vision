/* old_design_census.js: the measured half of the zero-old-design guard
   (tests/test_zero_old_design.py, B0, 2026-11-13).

   A port of the old-design runtime sweep's collector (olddesign/runtime/
   tools/collect.js, run over 93 scenes of main 349b1ca): every visible
   element, and each ::before and ::after that paints, is read for its
   computed face, size, colours, surfaces, borders, shape, shadows,
   gradients and animation, and checked against the new look:

     * the token set of sv-tokens.css (passed in by the test, read from the
       sheet), and the kit's mixes of it (a neutral on a neutral, an accent
       washed onto a neutral at up to 36 %);
     * the magic's light sources (magic_spec §3.2: the wordmark, the Eye
       mark, the active nav row, live dots, the selected tab, a live hero
       card's edge, a side's inset light), the only things that glow;
     * the role rules: Inter for words, JetBrains Mono for numbers and
       code, Orbitron in the frame's titles only, Rajdhani in the nav rows
       only; nothing under 11 px; text at 4.5:1 on its ground; the Eye's
       green as text on the brand, the active row's icon and the empty
       state's mark only, as a fill on live dots, ON and a checked box
       only, as a border on the selection and focus only; a solid red fill
       on the REAL family only; endless animations: the heartbeat, the
       armed beat, the Eye's breath.

   The critic's hole 4 adds accent-color, caret-color, ::placeholder and
   ::marker. Read-only but for two things: data-svc marks on the text
   holders the DevTools font pass reads back, and every endless animation
   (CSS, Web Animations, SVG's own) stopped at its start before anything
   is read. A breathing glow or a blinking dot read wherever its cycle
   happened to be was counted in one run and not in the next; stopped at
   its start it reads the same in every run, and the loop itself is still
   counted (anim_loop).

   The review of B0 (2026-11-13) closed its blind spots: an opaque mix of
   the Eye on a neutral is an Eye wash, an Eye outline outside focus is an
   Eye border, SVG shapes are read for their fill and stroke, a red or Eye
   fill drawn by ::before, ::after or an inset shadow that covers the box is
   a fill, and the kit page's specimens are the kit's.

   census(opts) returns {counts: {marker: n}, regions: {region: {marker:
   n}} (the shell region each element sits in, opts.regions), examples:
   {marker: [[n, key, property, value, text]]} (the elements grouped by
   selector and property), glyphs: [[index, signature, key, text,
   region]], geo: {...}}. */
'use strict';

function census(opts) {
  opts = opts || {};
  document.getAnimations().forEach(function (an) {
    try {
      var tm = an.effect && an.effect.getComputedTiming();
      if (!tm || tm.iterations !== Infinity || an.playState !== 'running') return;
      an.__svStopped = true;
      an.pause();
      an.currentTime = 0;
    } catch (e) { /* a detached target */ }
  });
  Array.prototype.forEach.call(document.querySelectorAll('svg'), function (s) {
    try { if (!s.animationsPaused()) { s.pauseAnimations(); s.setCurrentTime(0); } } catch (e) { /* no SMIL here */ }
  });
  Array.prototype.forEach.call(document.querySelectorAll('[data-svc]'), function (e) { e.removeAttribute('data-svc'); });
  var VW = innerWidth, VH = innerHeight;
  var MAXEX = opts.examples || 40;
  var TITLE_SEL = '.sidebar-brand h1, .sidebar-brand h1 *, .topbar-title, .topbar-title *, .card-title, .card-title *, .sv-panel-title, .sc-heading-title, .modal-title, .kbd-modal-title, .gollum-dialog .gl-title, .nav-section, .nav-section *, .il-title, .sv-overline, .brand-text';
  var NAV_SEL = '.nav-link, .nav-link *, .sidebar-brand .subtitle';
  var EYE_TEXT_OK = '.sidebar-brand, .sidebar-brand *, .brand-text, .nav-link.active .icon, .sv-empty-state svg, .brand-eye, .brand-eye *, .dk-icon, .dk-scale-row .sv-panel-title';
  var EYE_FILL_OK = '.sv-live-dot, .status-dot, .sv-state--on, .lsp-dot, .sv-toggle-track, .sv-toggle-track *, input[type="checkbox"]:checked';
  var EYE_BORDER_OK = '.rf-chip[aria-pressed="true"], .rf-opt[aria-pressed="true"], .sr-popup.sv-pinned, .rh-gear[aria-expanded="true"], .sv-toggle-track, .nav-link.active, input:focus, :focus-visible, input[type="checkbox"]:checked';
  var GLOW_OK = '.sv-live-dot, .status-dot.online, .sv-fresh--live, .sv-tab.is-active, .sv-tab[aria-selected="true"], .sv-seg-btn.is-active, .sv-seg-btn[aria-pressed="true"], .sidebar-brand h1, .sidebar-brand h1 *, .sv-on-void, .sv-on-void *, .sv-dialog, .sv-popover';
  var GRAD_OK = '.nav-link.active, .day-scheme-wrap, .sv-panel--hero, html, body';
  var PSEUDO_OK = '.nav-link.active, .sv-fresh--live, .sv-panel--hero, .brand-eye-wrap, .sidebar-brand, .sv-state, .sv-fresh, .sv-live-dot, .btn-stop, .sv-moment-icon, .sv-moment-arrive';
  /* A side's inset light (C3): a BUY or SELL control lit in its own side's
     colour, inside its own box, on hover or focus. */
  var SIDE_LIGHT = '.tk-long, .tk-short, .btn.btn-buy, .btn.btn-sell, .sr-pop-btn, .sr-gone-btn, .sz-confirm';
  var WORLD = '.sv-world--live, .sv-armed-pill, .sv-armed-pill *, .tk-venue--live, .sv-venue--live, .sv-row--live > td:first-child, .sv-adv-world.is-live, .pos-pop-venue.is-live, .hq-tag--live, .hq-brk--live, .ib-env--live, .bk-env--live, .hq-acct--live';
  var CODEISH = 'code, code *, kbd, kbd *, pre, pre *, samp, .sv-ident, .sv-ident *, .mono-id, .sv-pnl-src';
  /* The kit page's specimens (/design/kit/): a swatch shows a token by
     painting it, the wordmark and icon samples wear the Eye they document. */
  var SPECIMEN = '.dk-chip-sample, .dk-icon, .dk-scale-row .sv-panel-title, .dk-scale-row > span, [data-kit="numbers"] dt';
  var POPOVERS = /sr-popup|dh-pop|ip-dropdown|notif-dropdown|user-menu-dropdown|lsp-dropdown|exchange-dropdown|ticker-popup|nf-pop|pos-pop|se-chat-panel|sv-dialog|gollum-dialog|sv-horde|sv-council|sv-activity|sv-popover|sv-menu/;
  var LOOPS_OK = /^(sv-heartbeat|sv-armed-beat|sv-eye-breath)$/;
  var SKIP = { SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1, BR: 1, WBR: 1, META: 1, LINK: 1, HEAD: 1, TITLE: 1,
               OPTION: 1, OPTGROUP: 1, PARAM: 1, SOURCE: 1, TRACK: 1 };
  var SVG_KEEP = { svg: 1, text: 1, tspan: 1 };
  /* SVG shapes: read for their fill and stroke only (the final guard). */
  var SVG_SHAPE = { path: 1, circle: 1, rect: 1, line: 1, polyline: 1, polygon: 1, ellipse: 1, use: 1 };
  var REGIONS = opts.regions || [];

  // ── colours ─────────────────────────────────────────────────────────
  var TOK = opts.tokens;          // {name: [r, g, b]}
  var NEUTRAL = Object.keys(TOK).filter(function (n) { return /^(bg|line|ink)-\d$/.test(n); });
  var ACCENT = Object.keys(TOK).filter(function (n) { return NEUTRAL.indexOf(n) < 0; });
  TOK.white = [255, 255, 255]; TOK.black = [0, 0, 0];
  ACCENT.push('white');
  var REDS = { real: 1, 'down-fill': 1, down: 1 };
  var ccache = {};
  function parseColor(s) {
    if (!s) return null;
    s = s.trim();
    if (s === 'transparent') return [0, 0, 0, 0];
    var m = /^rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/.exec(s);
    if (m) return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : (/%$/.test(m[4]) ? parseFloat(m[4]) / 100 : +m[4])];
    m = /^color\(srgb\s+([-\d.e]+)\s+([-\d.e]+)\s+([-\d.e]+)(?:\s*\/\s*([\d.]+%?))?\s*\)$/.exec(s);
    if (m) return [m[1] * 255, m[2] * 255, m[3] * 255, m[4] === undefined ? 1 : (/%$/.test(m[4]) ? parseFloat(m[4]) / 100 : +m[4])];
    return null;
  }
  function dist(a, b) { return Math.sqrt(Math.pow(a[0] - b[0], 2) + Math.pow(a[1] - b[1], 2) + Math.pow(a[2] - b[2], 2)); }
  /* {k: tok | tok@a | mix | mix@a | off, n: nearest token, a: alpha} or null
     for a colour that paints nothing. */
  function classify(str) {
    if (str in ccache) return ccache[str];
    var c = parseColor(str), out = null;
    if (c && c[3] > 0.004) {
      var best = null, bd = 1e9, n;
      for (n in TOK) { var d = dist(c, TOK[n]); if (d < bd) { bd = d; best = n; } }
      if (bd <= 3) out = { k: c[3] >= 0.98 ? 'tok' : 'tok@a', n: best, a: +c[3].toFixed(2) };
      else {
        var mix = null;
        var tryPair = function (A, B, maxT) {
          var a = TOK[A], b = TOK[B];
          var ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], L = ab[0] * ab[0] + ab[1] * ab[1] + ab[2] * ab[2];
          if (!L) return;
          var t = ((c[0] - a[0]) * ab[0] + (c[1] - a[1]) * ab[1] + (c[2] - a[2]) * ab[2]) / L;
          if (t < 0 || t > maxT) return;
          var p = [a[0] + t * ab[0], a[1] + t * ab[1], a[2] + t * ab[2]];
          var dd = dist(c, p);
          if (dd <= 2.6 && (!mix || dd < mix.d)) mix = { d: dd, n: B + ' ' + Math.round(t * 100) + '% on ' + A };
        };
        var i, j;
        for (i = 0; i < NEUTRAL.length; i++) for (j = i + 1; j < NEUTRAL.length; j++) tryPair(NEUTRAL[i], NEUTRAL[j], 1);
        for (i = 0; i < NEUTRAL.length; i++) for (j = 0; j < ACCENT.length; j++) tryPair(NEUTRAL[i], ACCENT[j], 0.36);
        if (mix) out = { k: c[3] >= 0.98 ? 'mix' : 'mix@a', n: mix.n, a: +c[3].toFixed(2) };
        else out = { k: 'off', n: best, d: Math.round(bd), a: +c[3].toFixed(2), rgb: [Math.round(c[0]), Math.round(c[1]), Math.round(c[2])] };
      }
    }
    ccache[str] = out;
    return out;
  }
  function isEye(c) {
    return !!c && (((c.k === 'tok' || c.k === 'tok@a') && c.n === 'eye') || (c.k === 'off' && c.n === 'eye' && c.d <= 60)
                   || ((c.k === 'mix' || c.k === 'mix@a') && /^eye /.test(c.n)));
  }
  /* A mix of the Eye on a neutral paints like the Eye at that share. */
  function eyeShare(c) {
    if ((c.k === 'mix' || c.k === 'mix@a') && /^eye /.test(c.n)) return (parseInt(c.n.split(' ')[1], 10) / 100) * c.a;
    return c.a;
  }
  function colorsIn(s) { return (s && s !== 'none') ? (s.match(/rgba?\([^)]*\)|color\(srgb[^)]*\)/g) || []) : []; }
  function shadows(s) {
    if (!s || s === 'none') return [];
    var parts = [], depth = 0, cur = '', k;
    for (k = 0; k < s.length; k++) {
      var ch = s[k];
      if (ch === '(') depth++;
      if (ch === ')') depth--;
      if (ch === ',' && depth === 0) { parts.push(cur); cur = ''; } else cur += ch;
    }
    if (cur.trim()) parts.push(cur);
    return parts.map(function (p) {
      var col = (p.match(/rgba?\([^)]*\)|color\(srgb[^)]*\)/) || [null])[0];
      var nums = (p.replace(/rgba?\([^)]*\)|color\(srgb[^)]*\)/, '').match(/-?[\d.]+px/g) || []).map(parseFloat);
      return { col: col, c: parseColor(col), x: nums[0] || 0, y: nums[1] || 0, blur: nums[2] || 0, spread: nums[3] || 0, inset: /inset/.test(p) };
    });
  }
  function coloured(c) { return c && c[3] > 0.04 && Math.max(c[0], c[1], c[2]) > 40; }
  function lum(c) {
    var f = function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  }
  function over(top, bot) { var a = top[3]; return [top[0] * a + bot[0] * (1 - a), top[1] * a + bot[1] * (1 - a), top[2] * a + bot[2] * (1 - a), 1]; }
  function overA(top, bot) {
    var a = top[3] + bot[3] * (1 - top[3]);
    if (a <= 0) return [0, 0, 0, 0];
    return [0, 1, 2].map(function (i) { return (top[i] * top[3] + bot[i] * bot[3] * (1 - top[3])) / a; }).concat([a]);
  }

  // ── names ───────────────────────────────────────────────────────────
  var STATE = /^(active|open|opened|show|shown|visible|hidden|in|out|on|off|up|down|flat|is-.*|has-.*|sv-pinned|selected|expanded|collapsed|fade-in|loaded|htmx-.*|ready|mini|live|stale|disabled|enabled|current|focus|hover|new|fresh|unread|read|working|answered.*|sv-flash.*|sv-moment.*|sv-flare.*|positive|negative|neutral|bullish|bearish|long|short|buy|sell|success|warning|danger|error|ok|green|red|gold|amber|blue|muted|dim|small|large|sm|lg|xs|xl|wide|narrow|first|last|odd|even|clickable|pinned|sticky|scrolled)$/;
  function clsOf(el) { var c = el.className; return (typeof c === 'string' ? c : (c && c.baseVal) || '').trim().split(/\s+/).filter(Boolean); }
  function sig(el) { var c = clsOf(el).filter(function (x) { return !STATE.test(x); }); return c.length ? '.' + c.slice(0, 2).join('.') : (el.id ? '#' + el.id : ''); }
  function keyOf(el) {
    var own = sig(el), tag = el.tagName.toLowerCase();
    if (own) return tag + own;
    var a = el.parentElement, d = 0;
    while (a && d < 4 && a !== document.body) { var t = sig(a); if (t) return a.tagName.toLowerCase() + t + ' > ' + tag; a = a.parentElement; d++; }
    return tag;
  }

  // ── the walk ────────────────────────────────────────────────────────
  /* Each marker's count, and its elements grouped by selector and
     property (up to MAXEX groups), so a count that rose names the new one. */
  var counts = {}, groups = {}, glyphs = [], seenSig = {}, regions = {};
  function regionOf(el) {
    if (el.__svRegion !== undefined) return el.__svRegion;
    var name = 'other';
    for (var q = 0; q < REGIONS.length; q++) {
      try { if (el.closest(REGIONS[q][1])) { name = REGIONS[q][0]; break; } } catch (e) { /* a bad selector */ }
    }
    el.__svRegion = name;
    return name;
  }
  function F(marker, el, prop, value, text) {
    counts[marker] = (counts[marker] || 0) + 1;
    var rg = regions[regionOf(el)] || (regions[regionOf(el)] = {});
    rg[marker] = (rg[marker] || 0) + 1;
    var key = keyOf(el), g = groups[marker] || (groups[marker] = {}), id = key + '|' + prop;
    if (g[id]) { g[id][0]++; return; }
    if (Object.keys(g).length >= MAXEX) return;
    g[id] = [1, key, prop, String(value).slice(0, 120), String(text || '').slice(0, 50)];
  }
  var MONO = /^(jetbrains mono|share tech mono|monospace|ui-monospace|sfmono-regular|menlo|consolas|courier|courier new|liberation mono|dejavu sans mono)$/;
  /* An SVG shape's paint (the final guard: "SVG fill and stroke"): the Eye
     outside its marks is Eye ink, a colour of no token is off. Its host
     (the <svg>) decides the roles: the brand's Eye, the active row's icon,
     a live dot, the empty state's mark. */
  function shape(el) {
    var svg = el.ownerSVGElement || el.closest('svg');
    if (!svg || !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return;
    var r = el.getBoundingClientRect();
    if (r.width < 1 && r.height < 1) return;
    if (r.right <= 0) return;
    var cs = getComputedStyle(el), host = svg.matches(SPECIMEN) || el.matches(SPECIMEN) || svg.closest(SPECIMEN);
    if (host) return;
    [['fill', cs.fill, parseFloat(cs.fillOpacity)], ['stroke', cs.stroke, parseFloat(cs.strokeOpacity) * (parseFloat(cs.strokeWidth) > 0 ? 1 : 0)]]
      .forEach(function (pv) {
        if (!pv[1] || pv[1].indexOf('rgb') !== 0 || !(pv[2] > 0)) return;
        var c = classify(pv[1]);
        if (!c) return;
        var eyeOk = svg.matches(EYE_TEXT_OK) || svg.closest('.sidebar-brand, .brand-eye, .nav-link.active, .sv-empty-state, .dk-icon') || svg.matches(EYE_FILL_OK) || el.matches(EYE_FILL_OK);
        if (isEye(c) && !eyeOk) F('eye_text', el, 'svg ' + pv[0], pv[1], '');
        else if (c.k === 'off') F('color_off', el, 'svg ' + pv[0], pv[1], '');
      });
  }
  var nEl = 0, nText = 0;
  var all = document.querySelectorAll('body, body *');
  for (var ii = 0; ii < all.length; ii++) {
    var el = all[ii];
    var tag = el.tagName;
    var isSvg = el instanceof SVGElement;
    if (SKIP[tag.toUpperCase()]) continue;
    if (isSvg && SVG_SHAPE[tag.toLowerCase()]) { shape(el); continue; }
    if (isSvg && !SVG_KEEP[tag.toLowerCase()]) continue;
    if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
    var r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    if (r.right <= 0 || r.left >= Math.max(VW, document.documentElement.scrollWidth)) continue;
    var cs = getComputedStyle(el);
    if (cs.position === 'fixed' && (r.bottom <= 0 || r.top >= VH || r.left >= VW)) continue;
    nEl++;
    var txt = '';
    for (var c0 = el.firstChild; c0; c0 = c0.nextSibling) if (c0.nodeType === 3) txt += c0.nodeValue;
    txt = txt.replace(/\s+/g, ' ').trim();
    var val = '';
    if ((tag === 'INPUT' && !/^(hidden|checkbox|radio|range|color|file|submit|button|image|reset)$/.test(el.type)) || tag === 'TEXTAREA') val = el.type === 'password' ? '••••' : (el.value || el.placeholder || '');
    if (tag === 'SELECT') val = el.selectedOptions && el.selectedOptions[0] ? el.selectedOptions[0].text : '';
    if (tag === 'INPUT' && /^(submit|button|reset)$/.test(el.type)) val = el.value || '';
    var shown = (txt || val).slice(0, 80);
    var hasText = !!(txt || val);
    var bg = classify(cs.backgroundColor);
    var bgImg = cs.backgroundImage && cs.backgroundImage !== 'none' ? cs.backgroundImage : '';
    var sides = ['Top', 'Right', 'Bottom', 'Left'];
    var borderOn = sides.some(function (s) { return parseFloat(cs['border' + s + 'Width']) > 0 && cs['border' + s + 'Style'] !== 'none'; });
    var fam = cs.fontFamily.split(',')[0].trim().replace(/^["']|["']$/g, '').toLowerCase();
    var compact = shown.replace(/\s+/g, '');
    var digits = (compact.match(/\d/g) || []).length;
    var isFig = digits > 0 && compact.length <= 28 && digits / compact.length >= 0.35 && /^[+\-−±~≈$€£¥(#×x]*\d/.test(compact) && !/^[A-Z]{2,}\d/.test(compact);
    if (hasText) {
      nText++;
      if (fam === 'share tech mono') F('font_share_tech', el, 'font-family', cs.fontFamily, shown);
      else if (fam === 'orbitron' && !el.matches(TITLE_SEL)) F('font_orbitron', el, 'font-family', cs.fontFamily, shown);
      else if (fam === 'rajdhani' && !el.matches(NAV_SEL)) F('font_rajdhani', el, 'font-family', cs.fontFamily, shown);
      else if (!/^(inter|jetbrains mono|orbitron|rajdhani)$/.test(fam)) F('font_other', el, 'font-family', cs.fontFamily, shown);
      var fs = parseFloat(cs.fontSize);
      if (fs < 10.95) F('tiny', el, 'font-size', cs.fontSize, shown);
      if (isFig && !MONO.test(fam) && !/tabular-nums/.test(cs.fontVariantNumeric) && fam !== 'orbitron') F('figs', el, 'font-family', cs.fontFamily, shown);
      var words = txt.split(/\s+/).filter(function (w) { return /[A-Za-z]{2,}/.test(w); }).length;
      if (MONO.test(fam) && words >= 4 && digits / Math.max(1, compact.length) < 0.25 && !el.matches(CODEISH)) F('prose_mono', el, 'font-family', cs.fontFamily, shown);
      var paint = (isSvg && /^(text|tspan)$/i.test(tag)) ? (cs.fill && cs.fill.indexOf('rgb') === 0 ? cs.fill : cs.color) : cs.color;
      var tc = classify(paint);
      if (tc) {
        if (isEye(tc) && !el.matches(EYE_TEXT_OK)) F('eye_text', el, 'color', paint, shown);
        else if (tc.k === 'off') F('color_off', el, 'color', paint, shown);
      }
      var fg = parseColor(paint), under = null, opa = 1;
      for (var a = el; a && a !== document.documentElement; a = a.parentElement) {
        var ac = a === el ? cs : getComputedStyle(a);
        opa *= parseFloat(ac.opacity);
        var b = parseColor(ac.backgroundColor);
        if (b && b[3] > 0) under = under ? overA(under, b) : b;
        if (under && under[3] >= 0.99) break;
        if (ac.backgroundImage && ac.backgroundImage !== 'none' && /gradient/.test(ac.backgroundImage) && a !== document.body) {
          var cols = colorsIn(ac.backgroundImage).map(parseColor).filter(Boolean);
          var solid = cols.filter(function (x) { return x[3] > 0.9; })[0];
          if (solid) { under = under ? overA(under, solid) : solid; break; }
        }
      }
      under = overA(under || [0, 0, 0, 0], (TOK['bg-0'] || [4, 11, 7]).concat([1]));
      if (fg) {
        var fgc = over([fg[0], fg[1], fg[2], fg[3] * opa], under);
        var L1 = lum(fgc), L2 = lum(under);
        var cr = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
        var big = fs >= 18.66 || (fs >= 14 && +cs.fontWeight >= 700);
        var isPh = tc && tc.n === 'ink-4';
        var disabled = el.closest('[disabled], [aria-disabled="true"], .disabled');
        if (!isPh && !disabled && cr < (big ? 3 : 4.5)) F('contrast', el, 'contrast', cr.toFixed(2), shown);
      }
      /* For the DevTools font pass: one holder per face stack, weight,
         style and set of characters outside ASCII. */
      var na = Array.from(new Set(Array.from(txt || '').filter(function (ch) { return ch.codePointAt(0) > 0x7e; }))).join('');
      if (na) {
        var sg = cs.fontFamily + '|' + cs.fontWeight + '|' + cs.fontStyle + '|' + na;
        if (!(sg in seenSig)) {
          seenSig[sg] = glyphs.length;
          el.setAttribute('data-svc', String(glyphs.length));
          glyphs.push([glyphs.length, sg, keyOf(el), shown.slice(0, 30), regionOf(el)]);
        }
      }
    }
    // surfaces
    var area = r.width * r.height;
    var cardish = area >= 3000 && (borderOn || parseFloat(cs.borderTopLeftRadius) > 0 || parseFloat(cs.paddingTop) >= 6);
    if (bg && bg.a > 0 && !el.matches(SPECIMEN)) {
      if (isEye(bg) && !el.matches(EYE_FILL_OK)) F(eyeShare(bg) >= 0.6 ? 'eye_fill' : 'eye_wash', el, 'background-color', cs.backgroundColor, shown);
      else if (bg.k === 'off') F('bg_off', el, 'background-color', cs.backgroundColor, shown);
      if (bg.a < 0.97 && cardish && !((bg.k === 'tok@a') && ['up', 'down', 'ink-2', 'ink-3', 'warn', 'demo', 'ai', 'black'].indexOf(bg.n) >= 0 && area < 12000)) F('see_through', el, 'background-color', cs.backgroundColor, shown);
      var pbg = parseColor(cs.backgroundColor);
      if (pbg && pbg[3] >= 0.85 && (bg.k === 'tok' && REDS[bg.n] || (bg.k === 'off' && pbg[0] >= 150 && pbg[1] <= 110 && pbg[2] <= 110 && pbg[0] - pbg[1] >= 90)) && !el.matches(WORLD)) {
        F('red_fill', el, 'background-color', cs.backgroundColor, shown);
      }
    }
    var bdf = cs.backdropFilter || cs.webkitBackdropFilter;
    if (bdf && bdf !== 'none') F('glass', el, 'backdrop-filter', bdf, shown);
    if (bgImg && /gradient/.test(bgImg) && !el.matches(GRAD_OK)) {
      var gc = colorsIn(bgImg).map(classify).filter(Boolean);
      var clipText = /text/.test(cs.backgroundClip || cs.webkitBackgroundClip || '');
      if (clipText || area >= 1500 || gc.some(isEye)) F('gradient', el, 'background-image', bgImg, shown);
    }
    if (borderOn) {
      var bcs = [cs.borderTopColor, cs.borderRightColor, cs.borderBottomColor, cs.borderLeftColor].map(classify).filter(Boolean);
      if (bcs.some(isEye) && !el.matches(EYE_BORDER_OK)) F('eye_border', el, 'border-color', cs.borderTopColor, shown);
      else if (bcs.some(function (x) { return x.k === 'off'; })) F('border_off', el, 'border-color', [cs.borderTopColor, cs.borderLeftColor].join(' '), shown);
    }
    if (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) {
      var oc = classify(cs.outlineColor);
      if (oc && isEye(oc) && !el.matches(EYE_BORDER_OK)) F('eye_border', el, 'outline-color', cs.outlineColor, shown);
      else if (oc && oc.k === 'off') F('border_off', el, 'outline-color', cs.outlineColor, shown);
    }
    // shadows and glows
    if (cs.boxShadow && cs.boxShadow !== 'none') {
      var sh = shadows(cs.boxShadow);
      /* An inset shadow whose spread covers the box is a fill. */
      sh.forEach(function (s) {
        if (!s.inset || !s.c || s.spread < Math.min(r.width, r.height) / 2 - 1) return;
        var fc = classify(s.col);
        if (!fc) return;
        if (s.c[3] >= 0.85 && ((fc.k === 'tok' && REDS[fc.n]) || (fc.k === 'off' && s.c[0] >= 150 && s.c[1] <= 110 && s.c[2] <= 110 && s.c[0] - s.c[1] >= 90)) && !el.matches(WORLD)) F('red_fill', el, 'box-shadow inset', s.col, shown);
        else if (isEye(fc) && !el.matches(EYE_FILL_OK)) F(eyeShare(fc) * s.c[3] >= 0.6 ? 'eye_fill' : 'eye_wash', el, 'box-shadow inset', s.col, shown);
        else if (fc.k === 'off') F('bg_off', el, 'box-shadow inset', s.col, shown);
      });
      for (var si = 0; si < sh.length; si++) {
        var s = sh[si];
        if (s.blur > 0 && coloured(s.c)) {
          var sideLight = s.inset && el.matches(SIDE_LIGHT) && /up|down/.test((classify(s.col) || {}).n || '');
          if (!el.matches(GLOW_OK) && !sideLight) { F('glow', el, 'box-shadow', s.col + ' ' + s.blur + 'px' + (s.inset ? ' inset' : ''), shown); break; }
        } else if (s.blur >= 6 && s.c && !coloured(s.c) && !s.inset && cardish && !el.matches(GLOW_OK)
                   && !((s.y === 8 && s.blur === 24 && Math.abs(s.c[3] - 0.45) < 0.02) || (s.y === 24 && s.blur === 64 && Math.abs(s.c[3] - 0.6) < 0.02))
                   && !POPOVERS.test(typeof el.className === 'string' ? el.className : '')) {
          F('shadow', el, 'box-shadow', s.col + ' ' + s.blur + 'px', shown); break;
        }
      }
    }
    if (cs.textShadow && cs.textShadow !== 'none' && hasText) {
      var ts = shadows(cs.textShadow);
      for (var ti = 0; ti < ts.length; ti++) {
        if (ts[ti].blur > 0 && coloured(ts[ti].c) && !el.matches(GLOW_OK)) { F('text_glow', el, 'text-shadow', ts[ti].col + ' ' + ts[ti].blur + 'px', shown); break; }
      }
    }
    if (cs.filter && /drop-shadow/.test(cs.filter)) {
      if (colorsIn(cs.filter).map(parseColor).some(coloured) && !el.matches(GLOW_OK)) F('glow', el, 'filter', cs.filter, shown);
    }
    // the extra colours (the critic's hole 4)
    if ((tag === 'INPUT' || tag === 'PROGRESS' || tag === 'METER') && cs.accentColor && cs.accentColor !== 'auto') {
      var acc = classify(cs.accentColor);
      if (acc && (acc.k === 'off' || !(acc.n === 'eye' || /^ink-/.test(acc.n)))) F('accent_color', el, 'accent-color', cs.accentColor, shown);
    }
    if ((tag === 'INPUT' || tag === 'TEXTAREA') && cs.caretColor && cs.caretColor !== 'auto') {
      var cc = classify(cs.caretColor);
      if (cc && cc.k === 'off') F('color_off', el, 'caret-color', cs.caretColor, shown);
    }
    if ((tag === 'INPUT' || tag === 'TEXTAREA') && el.placeholder) {
      var ph = getComputedStyle(el, '::placeholder');
      var pc = classify(ph.color);
      if (pc && pc.k === 'off') F('color_off', el, '::placeholder color', ph.color, el.placeholder);
      if (parseFloat(ph.fontSize) < 10.95) F('tiny', el, '::placeholder font-size', ph.fontSize, el.placeholder);
    }
    if (tag === 'LI' && cs.display === 'list-item' && cs.listStyleType !== 'none') {
      var mk = getComputedStyle(el, '::marker');
      var mc = classify(mk.color);
      if (mc && (mc.k === 'off' || isEye(mc))) F(isEye(mc) ? 'eye_text' : 'color_off', el, '::marker color', mk.color, shown);
    }
    // shape
    if ((bg && bg.a > 0) || borderOn) {
      var rads = [cs.borderTopLeftRadius, cs.borderTopRightRadius, cs.borderBottomRightRadius, cs.borderBottomLeftRadius];
      var bad = rads.filter(function (v) {
        if (/%/.test(v)) return parseFloat(v) !== 50 && parseFloat(v) !== 0;
        var x = parseFloat(v);
        /* The tokens' radii, the segment's inner corner (3 px inside a 4 px
           control, the kit's .sv-seg-btn), pills and circles. */
        return !((opts.radii || [0, 2, 4, 6]).indexOf(x) >= 0 || x === 3 || x >= 99 || x >= Math.min(r.width, r.height) / 2 - 0.5);
      })[0];
      if (bad) F('radius', el, 'border-radius', bad, shown);
    }
    if (cs.animationName && cs.animationName !== 'none' && /infinite/.test(cs.animationIterationCount) && cs.animationPlayState !== 'paused') {
      if (!cs.animationName.split(',').every(function (n) { return LOOPS_OK.test(n.trim()); })) F('anim_loop', el, 'animation', cs.animationName, shown);
    }
    var inline = el.matches(SPECIMEN) ? '' : (el.getAttribute('style') || '');
    if (inline && /(^|;)\s*(color|background(-color|-image)?|border(-[a-z]+)?|outline|font(-[a-z]+)?|letter-spacing|text-transform|box-shadow|text-shadow|filter)\s*:/i.test(inline)) {
      F('inline_visual', el, 'style', inline, shown);
    }
    // pseudo-elements that paint
    ['::before', '::after'].forEach(function (pe) {
      var p = getComputedStyle(el, pe);
      if (!p.content || p.content === 'none' || p.content === 'normal' || p.display === 'none') return;
      if (parseFloat(p.opacity) === 0) return;
      var hostOk = el === document.body || el.matches(PSEUDO_OK);
      if (p.boxShadow && p.boxShadow !== 'none' && !hostOk && shadows(p.boxShadow).some(function (x) { return x.blur > 0 && coloured(x.c); })) F('glow', el, pe + ' box-shadow', p.boxShadow, shown);
      if (p.textShadow && p.textShadow !== 'none' && !hostOk && shadows(p.textShadow).some(function (x) { return x.blur > 0 && coloured(x.c); })) F('text_glow', el, pe + ' text-shadow', p.textShadow, shown);
      if (p.backgroundImage && /gradient/.test(p.backgroundImage) && !hostOk) F('gradient', el, pe + ' background-image', p.backgroundImage, shown);
      var pbg2 = classify(p.backgroundColor), praw = parseColor(p.backgroundColor);
      if (pbg2 && praw && praw[3] >= 0.85 && ((pbg2.k === 'tok' && REDS[pbg2.n]) || (pbg2.k === 'off' && praw[0] >= 150 && praw[1] <= 110 && praw[2] <= 110 && praw[0] - praw[1] >= 90))
          && !el.matches(WORLD) && !hostOk && parseFloat(p.width) * parseFloat(p.height) >= 16) F('red_fill', el, pe + ' background-color', p.backgroundColor, shown);
      else if (pbg2 && isEye(pbg2) && !hostOk && !el.matches(EYE_FILL_OK)) F(eyeShare(pbg2) >= 0.6 ? 'eye_fill' : 'eye_wash', el, pe + ' background-color', p.backgroundColor, shown);
      else if (pbg2 && pbg2.k === 'off' && !hostOk) F('bg_off', el, pe + ' background-color', p.backgroundColor, shown);
      if (p.animationName && p.animationName !== 'none' && /infinite/.test(p.animationIterationCount) && p.animationPlayState !== 'paused'
          && !p.animationName.split(',').every(function (n) { return LOOPS_OK.test(n.trim()); })) F('anim_loop', el, pe + ' animation', p.animationName, shown);
    });
  }

  // running endless animations (CSS and Web Animations), visible ones only
  document.getAnimations().forEach(function (an) {
    try {
      var t = an.effect && an.effect.target;
      if (!t || t.nodeType !== 1 || !t.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return;
      var tm = an.effect.getComputedTiming();
      if (tm.iterations !== Infinity || (an.playState !== 'running' && !an.__svStopped)) return;
      var name = an.animationName || an.id || 'web-animation';
      if (!LOOPS_OK.test(name) && an.constructor.name !== 'CSSAnimation') F('anim_loop', t, 'animation', name, '');
    } catch (e) { /* a detached target */ }
  });

  // the shell's geometry: fixed chrome over the content, the first line
  var geo = { docW: document.documentElement.scrollWidth, vw: VW, docH: document.documentElement.scrollHeight };
  var pc = document.querySelector('.page-content');
  if (pc) {
    var pr = pc.getBoundingClientRect();
    var first = null, nodes = pc.querySelectorAll('*');
    for (var q = 0; q < nodes.length; q++) {
      var e2 = nodes[q];
      if (!e2.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
      var b2 = e2.getBoundingClientRect();
      if (b2.height > 4 && b2.width > 20 && (e2.innerText || '').trim()) { first = Math.round(b2.top + scrollY); break; }
    }
    geo.firstContentY = first;
    if (first !== null && first > 100) F('first_line_low', pc, 'first content y', first, '');
    var fixed = ['.gollum-fab', '.se-eye-fab', '.sv-horde-tab', '.sv-council-band-tab', '.sv-activity-tab', '.signals-rail-toggle', '.info-panel-wrap', '.hb-restore-tab'];
    fixed.forEach(function (sel) {
      document.querySelectorAll(sel).forEach(function (f) {
        if (!f.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return;
        var fr = f.getBoundingClientRect();
        var ix = Math.min(fr.right, pr.right) - Math.max(fr.left, pr.left), iy = Math.min(fr.bottom, Math.min(pr.bottom, VH)) - Math.max(fr.top, pr.top);
        if (ix > 4 && iy > 4) F('chrome_over_content', f, 'overlap', Math.round(ix) + 'x' + Math.round(iy), sel);
      });
    });
  }
  if (geo.docW > VW + 1) F('sideways', document.documentElement, 'scrollWidth', geo.docW + ' > ' + VW, '');
  if (opts.phone) {
    /* At a phone's width (the critic's hole 3): a money control smaller
       than a finger (44 px). */
    document.querySelectorAll(opts.money || '').forEach(function (m) {
      if (!m.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return;
      var mr = m.getBoundingClientRect();
      if (mr.width < 1 || mr.height < 1) return;
      if (mr.height < 44 || mr.width < 44) F('target_small', m, 'size', Math.round(mr.width) + 'x' + Math.round(mr.height), (m.innerText || m.value || '').trim());
    });
  }
  var examples = {};
  Object.keys(groups).forEach(function (m) {
    examples[m] = Object.keys(groups[m]).map(function (k) { return groups[m][k]; })
      .sort(function (a, b) { return b[0] - a[0]; });
  });
  return { counts: counts, regions: regions, examples: examples, glyphs: glyphs, geo: geo, n: nEl, nText: nText,
           url: location.pathname, title: document.title };
}

if (typeof module !== 'undefined' && module.exports) module.exports = { census: census };
