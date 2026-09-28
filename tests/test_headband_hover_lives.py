"""The news band stays hoverable for as long as the page is open.

The operator, 2026-09-27: "sometimes after long time of page open the news
headband scrolling at the top doesn't render any popup on hover,
sometimes... fix".

What it was (templates/base.html and the ticker partial on 8db05d5):
  * the ticker's live refresh rewrites every item (innerHTML) every five
    minutes while the tab is visible, on every return to the tab, on every
    PIN unlock and on every news push, and the hover listeners had been
    bound per item, once, at page load. After the first rewrite no item had
    one: the band scrolled on, deaf to hover, until the next page load;
  * the loop's second half — the copy that makes the scroll seamless — was
    rendered without any card;
  * a card open (or its hover beat running) when a rewrite landed stayed on
    <body>, pointing at an item that no longer existed;
  * a session that expired between sweeps wrote the login page into the
    band.

These tests load the page's REAL inline scripts — the wheel / collapse
block, the WebSocket block with refreshTicker, the UPGRADE-9 popup engine —
under node, against the bands exactly as Django renders them and the
partial /partials/ticker/ answers, on a minimal DOM with a fake clock, a
fake fetch and a fake socket. They drive a long session through them:
hours of quote ticks, dozens of sweeps, news pushes, a tab switch, a PIN
unlock, fresh headlines arriving under a card being read (they wait for
the hand to leave), inside the hover beat and inside the card's crossing
grace, a tab hidden with headlines waiting, the first sweep of unchanged
headlines, a page restored from the back/forward cache, failed refreshes,
a login page. After every step a hand rests on items of every band — both
halves of the ticker, both halves of the data headband, the watchlist
rail — and exactly one card must open, under its item, and close when the
hand leaves. All of it fails on 8db05d5.

jsdom is not installed on this machine: the DOM here is the smallest one
the three scripts need (innerHTML parse and serialise, selectors with
:hover, bubbling events with relatedTarget, isConnected, a fixed geometry).
A removed node gets no boundary events, as in Chrome and Firefox. One node
process runs every scenario.

Run with:  python manage.py test tests.test_headband_hover_lives
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

NODE = shutil.which("node")
DJANGO_TAG_RE = re.compile(r"\{%|\{\{")

# The three script blocks the bands run on, found by their own words.
SCRIPTS = (
    ("wheel+collapse", "window.svWheelMarquee = function (frame, track)"),
    ("websocket+refreshTicker", "UPGRADE-3: WebSocket live ticks."),
    ("upgrade9-popup-engine", "UPGRADE-9: headband popup escape + hover arrows"),
)
BANDS_FROM = "<!-- Ticker Bar (fixed, always visible) -->"
BANDS_TO = "<!-- Info Bar (fixed, labels always visible, hover for dropdowns) -->"
RAIL_FROM = '<div class="rail-section watch-section" id="railWatch">'
RAIL_TO = "<script>\n/* Phase 62"
FRESH_ID = 987654
LOGIN_PAGE = (
    '<!DOCTYPE html>\n<html lang="en"><head><title>The Wall</title>'
    "<style>body{background:#000}</style></head><body><form method=\"post\">"
    '<input name="username"><input name="password" type="password">'
    "<p>Sign in to Sauron</p></form></body></html>")

# Every probe a hand makes after every step of the long session.
PROBES = ("ticker_first_half", "ticker_first_half_end", "ticker_second_half",
          "ticker_second_half_end", "headband_first_half",
          "headband_second_half", "watchlist")


def _base():
    return (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
        encoding="utf-8")


def _news(i):
    return {
        "type": "news", "news_id": i, "title": "Headline %d moves markets" % i,
        "source": "wire", "summary": "Summary of headline %d" % i,
        "sentiment_score": 0.1, "urgency": "", "affected": "EURUSD",
        "affected_chips": ["EURUSD"], "keywords": ["Headline"],
        "implication": "Neutral — mixed signal", "published_at": "12:00",
        "url": "/news/%d/" % i,
    }


def _instrument(symbol, i):
    return {
        "symbol": symbol, "name": symbol + " name", "last": 1.1 + i,
        "asset_class": "forex", "change_pct": 0.5 - i * 0.2, "volume": 1000,
        "bid": 1.0 + i, "ask": 1.2 + i, "source": "live",
        "updated_human": "4s ago", "spark": [1.0, 1.1, 1.2],
        "spark_min": 1.0, "spark_max": 1.2,
    }


def _inputs():
    """The page as Django renders the two bands and the watchlist rail, the
    answer /partials/ticker/ gives after one fresh headline, and the three
    script blocks verbatim."""
    from django.template import engines
    from django.template.loader import render_to_string
    eng = engines["django"]
    raw = _base()
    ticker = [_news(1000 + i) for i in range(6)]
    ctx = {"ticker_items": ticker,
           "ui_headband": [_instrument(s, i) for i, s in enumerate(
               ["EURUSD", "GBPUSD", "AAPL", "BTCUSD"])],
           "ui_watchlist": [_instrument(s, i) for i, s in enumerate(
               ["EURCAD", "GLDM", "AAPL"])]}
    bands = raw[raw.index(BANDS_FROM):raw.index(BANDS_TO)]
    rail = raw[raw.index(RAIL_FROM):raw.index(RAIL_TO)]
    page = (eng.from_string("{% load sauron_tags %}" + bands).render(ctx)
            + '<main id="elsewhere"><p id="page-text">The page</p></main>'
            + eng.from_string("{% load sauron_tags %}" + rail).render(ctx))
    # Exactly the template the ticker_partial view renders: once with one
    # fresh headline, once with the page's own headlines, unchanged.
    answer = render_to_string("_partials/ticker_items.html",
                              {"ticker_items": [_news(FRESH_ID)] + ticker[:-1]})
    initial = render_to_string("_partials/ticker_items.html",
                               {"ticker_items": ticker})
    blocks = re.findall(r"<script>(.*?)</script>", raw, re.S)
    scripts = []
    for label, marker in SCRIPTS:
        hits = [b for b in blocks if marker in b]
        assert len(hits) == 1, "%s: %d blocks" % (label, len(hits))
        assert not DJANGO_TAG_RE.search(hits[0]), label + " carries Django tags"
        scripts.append({"label": "base.html " + label, "source": hits[0]})
    return {"page": page, "answer": answer, "initial": initial,
            "fresh_id": str(FRESH_ID), "login": LOGIN_PAGE, "scripts": scripts}


# ── the DOM: the smallest one the three scripts need ──────────────────────
DOM_JS = r"""
'use strict';
const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
  'link', 'meta', 'source', 'track', 'wbr']);
const ENT = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", mdash: '—', middot: '·', nbsp: ' ' };
function decode(s) {
  return s.replace(/&(#x?[0-9a-fA-F]+|\w+);/g, (m, e) => {
    if (e[0] === '#') return String.fromCodePoint(e[1] === 'x' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10));
    return ENT[e] !== undefined ? ENT[e] : m;
  });
}
let pointerTarget = null;
let ERRORS = [];
function setPointer(el) { pointerTarget = el; }
function getPointer() { return pointerTarget; }
function reset() { pointerTarget = null; ERRORS = []; }

class Node {
  constructor(doc) { this.ownerDocument = doc; this.parentNode = null; this.childNodes = []; }
  get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === this.ownerDocument; }
  contains(o) { while (o) { if (o === this) return true; o = o.parentNode; } return false; }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
}
class Text extends Node {
  constructor(doc, t) { super(doc); this.nodeType = 3; this.data = t; }
  get textContent() { return this.data; }
  set textContent(v) { this.data = String(v); }
}
class Element extends Node {
  constructor(doc, tag) {
    super(doc);
    this.nodeType = 1; this.tagName = tag.toUpperCase(); this.localName = tag.toLowerCase();
    this.attrs = {}; this._l = {};
    const st = {};
    this.style = new Proxy(st, {
      get(t, k) { if (k === 'setProperty') return (p, v) => { t[p] = v; };
        if (k === 'removeProperty') return (p) => { delete t[p]; };
        return t[k] === undefined ? '' : t[k]; },
      set(t, k, v) { t[k] = v; return true; },
    });
    this.scrollLeft = 0; this.disabled = false; this.hidden = false;
  }
  get children() { return this.childNodes.filter(n => n.nodeType === 1); }
  get firstElementChild() { return this.children[0] || null; }
  get id() { return this.attrs.id || ''; }
  get className() { return this.attrs.class || ''; }
  set className(v) { this.attrs.class = String(v); }
  get classList() {
    const el = this;
    const list = () => (el.attrs.class || '').split(/\s+/).filter(Boolean);
    const put = (a) => { el.attrs.class = a.join(' '); };
    return {
      contains: c => list().includes(c),
      add: (...cs) => { const a = list(); cs.forEach(c => { if (!a.includes(c)) a.push(c); }); put(a); },
      remove: (...cs) => put(list().filter(x => !cs.includes(x))),
      toggle: (c, force) => { const has = list().includes(c); const want = force === undefined ? !has : !!force;
        if (want && !has) put(list().concat([c])); if (!want && has) put(list().filter(x => x !== c)); return want; },
    };
  }
  get dataset() {
    const el = this;
    const key = k => 'data-' + k.replace(/[A-Z]/g, m => '-' + m.toLowerCase());
    return new Proxy({}, {
      get(_, k) { return typeof k === 'string' && el.attrs[key(k)] !== undefined ? el.attrs[key(k)] : undefined; },
      set(_, k, v) { el.attrs[key(k)] = String(v); return true; },
    });
  }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  hasAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k); }
  removeAttribute(k) { delete this.attrs[k]; }
  appendChild(n) {
    if (n.parentNode) n.parentNode.removeChild(n);
    this.childNodes.push(n); n.parentNode = this; return n;
  }
  removeChild(n) { const i = this.childNodes.indexOf(n); if (i >= 0) this.childNodes.splice(i, 1); n.parentNode = null; return n; }
  get textContent() { return this.childNodes.map(c => c.textContent).join(''); }
  set textContent(v) { this.childNodes.forEach(c => { c.parentNode = null; }); this.childNodes = [];
    if (v !== '' && v != null) this.appendChild(new Text(this.ownerDocument, String(v))); }
  get innerHTML() { return this.childNodes.map(serialise).join(''); }
  set innerHTML(html) {
    this.childNodes.forEach(c => { c.parentNode = null; });
    this.childNodes = [];
    parseInto(this, String(html));
  }
  querySelectorAll(sel) { const out = []; const sels = parseSelectorList(sel);
    walk(this, e => { if (sels.some(s => matchComplex(e, s))) out.push(e); }); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  matches(sel) { return parseSelectorList(sel).some(s => matchComplex(this, s)); }
  closest(sel) { let e = this; while (e && e.nodeType === 1) { if (e.matches(sel)) return e; e = e.parentNode; } return null; }
  addEventListener(t, f, o) { if (!f) return; const once = !!(o && typeof o === 'object' && o.once);
    (this._l[t] = this._l[t] || []).push({ f, once }); }
  removeEventListener(t, f) { if (this._l[t]) this._l[t] = this._l[t].filter(x => x.f !== f); }
  dispatchEvent(ev) { return dispatch(this, ev); }
  focus() {}
  blur() {}
  click() { dispatch(this, new Event('click', { bubbles: true })); }
  // A fixed geometry: a band item is 300px wide, laid out by its index.
  getBoundingClientRect() {
    const p = this.parentNode; const i = p ? p.children.indexOf(this) : 0;
    const top = this.closest('.ticker-bar') ? 108 : 60;
    return { top, bottom: top + 34, left: 240 + i * 300, right: 540 + i * 300, width: 300, height: 34, x: 240 + i * 300, y: top };
  }
  get offsetHeight() { return this.style.display === 'none' ? 0 : 200; }
  get offsetWidth() { return 300; }
  get scrollWidth() { return Math.max(300, this.children.length * 300); }
  get clientWidth() { return 1600; }
  get scrollHeight() { return 200; }
  get clientHeight() { return 200; }
}
function walk(root, fn) { root.childNodes.forEach(c => { if (c.nodeType === 1) { fn(c); walk(c, fn); } }); }
function serialise(n) {
  if (n.nodeType === 3) return n.data.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const a = Object.keys(n.attrs).map(k => ' ' + k + '="' + String(n.attrs[k]).replace(/"/g, '&quot;') + '"').join('');
  if (VOID.has(n.localName)) return '<' + n.localName + a + '>';
  return '<' + n.localName + a + '>' + n.childNodes.map(serialise).join('') + '</' + n.localName + '>';
}
function parseInto(root, html) {
  const doc = root.ownerDocument;
  const stack = [root];
  const top = () => stack[stack.length - 1];
  let i = 0;
  while (i < html.length) {
    if (html.startsWith('<!--', i)) { const e = html.indexOf('-->', i + 4); i = e < 0 ? html.length : e + 3; continue; }
    if (html[i] === '<' && html[i + 1] === '/') {
      const e = html.indexOf('>', i); const name = html.slice(i + 2, e).trim().toLowerCase();
      for (let k = stack.length - 1; k > 0; k--) { if (stack[k].localName === name) { stack.length = k; break; } }
      i = e + 1; continue;
    }
    if (html[i] === '<' && /[a-zA-Z]/.test(html[i + 1] || '')) {
      let j = i + 1; while (j < html.length && /[^\s>\/]/.test(html[j])) j++;
      const name = html.slice(i + 1, j).toLowerCase();
      const el = new Element(doc, name);
      let selfClose = false;
      while (j < html.length) {
        while (/\s/.test(html[j])) j++;
        if (html[j] === '>') { j++; break; }
        if (html[j] === '/' && html[j + 1] === '>') { selfClose = true; j += 2; break; }
        let k = j; while (k < html.length && /[^\s=>\/]/.test(html[k])) k++;
        const an = html.slice(j, k); j = k;
        if (!an) { j++; continue; }
        while (/\s/.test(html[j])) j++;
        let val = '';
        if (html[j] === '=') {
          j++; while (/\s/.test(html[j])) j++;
          if (html[j] === '"' || html[j] === "'") { const q = html[j]; const e = html.indexOf(q, j + 1); val = html.slice(j + 1, e); j = e + 1; }
          else { let e = j; while (e < html.length && /[^\s>]/.test(html[e])) e++; val = html.slice(j, e); j = e; }
        }
        el.attrs[an.toLowerCase()] = decode(val);
      }
      top().appendChild(el);
      if (name === 'script' || name === 'style') {
        const e = html.toLowerCase().indexOf('</' + name, j);
        el.appendChild(new Text(doc, html.slice(j, e)));
        j = html.indexOf('>', e) + 1;
      } else if (!selfClose && !VOID.has(name)) stack.push(el);
      i = j; continue;
    }
    let e = html.indexOf('<', i + 1); if (e < 0) e = html.length;
    top().appendChild(new Text(doc, decode(html.slice(i, e))));
    i = e;
  }
}
function splitTop(s, sep) {
  const out = []; let depth = 0, q = null, cur = '';
  for (const ch of s) {
    if (q) { cur += ch; if (ch === q) q = null; continue; }
    if (ch === '"' || ch === "'") { q = ch; cur += ch; continue; }
    if (ch === '[' || ch === '(') depth++;
    if (ch === ']' || ch === ')') depth--;
    if (depth === 0 && (sep === ' ' ? /\s/.test(ch) : ch === sep)) { if (cur.trim()) out.push(cur.trim()); cur = ''; continue; }
    cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}
const SEL_CACHE = new Map();
function parseSelectorList(sel) {
  if (SEL_CACHE.has(sel)) return SEL_CACHE.get(sel);
  const list = splitTop(sel, ',').map(cx => {
    const parts = splitTop(cx.replace(/\s*>\s*/g, ' > '), ' ');
    const seq = []; let child = false;
    for (const p of parts) { if (p === '>') { child = true; continue; } seq.push({ c: parseCompound(p), child }); child = false; }
    return seq;
  });
  SEL_CACHE.set(sel, list); return list;
}
function parseCompound(p) {
  const c = { tag: null, id: null, cls: [], attrs: [], hover: false, not: [] };
  const re = /^([a-zA-Z*][\w-]*)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:([~|^$*]?=)(?:"([^"]*)"|'([^']*)'|([^\]]*)))?\]|:hover|:not\(([^)]*)\)|:([\w-]+)/g;
  let m; let pos = 0;
  while ((m = re.exec(p)) && m.index === pos) {
    pos = re.lastIndex;
    if (m[1]) { if (m[1] !== '*') c.tag = m[1].toUpperCase(); }
    else if (m[2]) c.id = m[2];
    else if (m[3]) c.cls.push(m[3]);
    else if (m[4]) c.attrs.push({ n: m[4], op: m[5], v: m[6] !== undefined ? m[6] : (m[7] !== undefined ? m[7] : m[8]) });
    else if (m[0] === ':hover') c.hover = true;
    else if (m[9] !== undefined) c.not.push(parseSelectorList(m[9]));
  }
  if (pos !== p.length) throw new Error('the test DOM cannot parse selector part: ' + p);
  return c;
}
function matchCompound(e, c) {
  if (!e || e.nodeType !== 1) return false;
  if (c.tag && e.tagName !== c.tag) return false;
  if (c.id && e.id !== c.id) return false;
  for (const k of c.cls) if (!e.classList.contains(k)) return false;
  for (const a of c.attrs) {
    if (!e.hasAttribute(a.n)) return false;
    if (a.op === '=' && e.getAttribute(a.n) !== a.v) return false;
  }
  if (c.hover) { const p = getPointer(); if (!p || !e.contains(p)) return false; }
  for (const n of c.not) if (n.some(s => matchComplex(e, s))) return false;
  return true;
}
function matchComplex(e, seq) {
  let k = seq.length - 1;
  if (!matchCompound(e, seq[k].c)) return false;
  let cur = e;
  while (k > 0) {
    const child = seq[k].child; k--;
    let p = cur.parentNode; let found = null;
    while (p && p.nodeType === 1) {
      if (matchCompound(p, seq[k].c)) { found = p; break; }
      if (child) break;
      p = p.parentNode;
    }
    if (!found) return false;
    cur = found;
  }
  return true;
}
class Event {
  constructor(type, init) { init = init || {};
    this.type = type; this.bubbles = !!init.bubbles; this.cancelable = true; this.defaultPrevented = false;
    this._stop = false; this.detail = init.detail; this.relatedTarget = init.relatedTarget || null;
    Object.keys(init).forEach(k => { if (!(k in this)) this[k] = init[k]; }); }
  preventDefault() { this.defaultPrevented = true; }
  stopPropagation() { this._stop = true; }
  stopImmediatePropagation() { this._stop = true; }
}
class CustomEvent extends Event { constructor(t, init) { super(t, init); this.detail = init && init.detail; } }
function fireOn(node, ev) {
  const ls = (node._l && node._l[ev.type]) || [];
  ev.currentTarget = node;
  ls.slice().forEach(x => {
    if (x.once) node.removeEventListener(ev.type, x.f);
    try { x.f.call(node, ev); } catch (err) { ERRORS.push(ev.type + ': ' + (err && err.stack || err)); }
  });
}
function dispatch(target, ev) {
  ev.target = target;
  const path = []; let n = target;
  while (n) { path.push(n); n = n.parentNode; }
  const doc = target.ownerDocument;
  if (path[path.length - 1] === doc && doc.defaultView) path.push(doc.defaultView);
  for (const node of path) { fireOn(node, ev); if (!ev.bubbles || ev._stop) break; }
  return !ev.defaultPrevented;
}
class Document extends Element {
  constructor() {
    super(null, '#document'); this.ownerDocument = this; this.nodeType = 9;
    this.documentElement = new Element(this, 'html'); this.appendChild(this.documentElement);
    this.head = new Element(this, 'head'); this.body = new Element(this, 'body');
    this.documentElement.appendChild(this.head); this.documentElement.appendChild(this.body);
    this.hidden = false; this.visibilityState = 'visible'; this.readyState = 'complete';
  }
  createElement(t) { return new Element(this, t); }
  createTextNode(t) { return new Text(this, t); }
  getElementById(id) { let r = null; walk(this, e => { if (!r && e.attrs.id === id) r = e; }); return r; }
}
module.exports = { Document, Element, Event, CustomEvent, setPointer, getPointer, dispatch, reset, errors: () => ERRORS.slice() };
"""

# ── the session: a fake clock, a fake fetch, a fake socket, a hand ────────
RUN_JS = r"""
'use strict';
const vm = require('vm'), fs = require('fs'), path = require('path');
const D = require(path.join(__dirname, 'dom.js'));
const IN = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const CARD = '.ticker-popup, .dh-pop';
const MIN = 60000;
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(r => setImmediate(r)); };
const mmss = ms => { const s = Math.round(ms / 1000); return Math.floor(s / 60) + 'm' + String(s % 60).padStart(2, '0') + 's'; };

function boot() {
  D.reset();
  const doc = new D.Document();
  doc.body.innerHTML = IN.page;
  let now = 0, seq = 0, fetches = 0, swaps = 0, lastBody = null;
  const timers = new Map(), errors = [], queue = [], reg = [], sockets = [], store = {};
  const st = (f, ms, ...a) => { const id = ++seq; timers.set(id, { at: now + Math.max(0, +ms || 0), f, a, every: 0 }); return id; };
  const si = (f, ms, ...a) => { const id = ++seq; const every = Math.max(1, +ms || 0); timers.set(id, { at: now + every, f, a, every }); return id; };
  const clr = id => { timers.delete(id); };
  const later = (ms, v, fail) => new Promise((res, rej) => { st(() => (fail ? rej(v) : res(v)), ms); });
  /* /partials/ticker/ answers what the scenario queued, else a fresh
     partial: the real render with a new headline id on top. */
  function answer(n) {
    const a = queue.length ? queue.shift() : { kind: 'fresh' };
    if (a.kind === 'reject') return later(a.delay || 0, new TypeError('Failed to fetch'), true);
    let body, ok = true, status = 200, redirected = false;
    if (a.kind === 'fresh') { body = IN.answer.split(IN.fresh_id).join(String(a.id || 700000 + n)); lastBody = body; }
    else if (a.kind === 'same') body = lastBody;
    else if (a.kind === 'initial') { body = IN.initial; lastBody = body; }
    else if (a.kind === 'error') { body = 'Server Error (500)'; ok = false; status = 500; }
    else if (a.kind === 'login') { body = IN.login; redirected = true; }
    else if (a.kind === 'moved') { body = '<p class="moved">Moved elsewhere</p>'; redirected = true; }
    else if (a.kind === 'page') body = IN.login;
    return later(a.delay || 0, { ok, status, redirected, text: () => Promise.resolve(body) });
  }
  const fetch = (url) => {
    if (url !== '/partials/ticker/') {
      return Promise.resolve({ ok: false, status: 404, redirected: false,
        text: () => Promise.resolve(''), json: () => Promise.reject(new Error('404')) });
    }
    fetches += 1;
    return answer(fetches);
  };
  class WS { constructor(u) { this.url = u; sockets.push(this); } close() { if (this.onclose) this.onclose({}); } send() {} }
  const win = {
    document: doc, console: { log() {}, warn() {}, error() {}, debug() {}, info() {} },
    setTimeout: st, clearTimeout: clr, setInterval: si, clearInterval: clr,
    requestAnimationFrame: f => st(f, 16), cancelAnimationFrame: clr,
    fetch, WebSocket: WS, CustomEvent: D.CustomEvent, Event: D.Event,
    location: { protocol: 'http:', host: 'localhost:8000', pathname: '/', reload() {}, assign() {} },
    localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } },
    innerWidth: 1920, innerHeight: 1080, navigator: { userAgent: 'node' },
    getComputedStyle: el => el.style,
    matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
    /* The open-popup registry, same semantics as sv-notif-card.js. */
    SV: { popup: { opened: p => { if (reg.indexOf(p) < 0) reg.push(p); },
                   closed: p => { const i = reg.indexOf(p); if (i >= 0) reg.splice(i, 1); } } },
    SV_HOVER_BEAT_MS: 450,
    _l: {},
  };
  win.addEventListener = D.Element.prototype.addEventListener;
  win.removeEventListener = D.Element.prototype.removeEventListener;
  win.window = win; win.self = win;
  doc.defaultView = win;
  /* Count the band's rewrites, so no scenario passes on a band nothing
     touched. */
  const track = doc.getElementById('tickerTrack');
  const ih = Object.getOwnPropertyDescriptor(D.Element.prototype, 'innerHTML');
  Object.defineProperty(track, 'innerHTML', { configurable: true,
    get() { return ih.get.call(this); }, set(v) { swaps += 1; ih.set.call(this, v); } });
  const ctx = vm.createContext(win);
  for (const s of IN.scripts) {
    try { vm.runInContext(s.source, ctx, { filename: s.label }); }
    catch (e) { errors.push('LOAD ' + s.label + ': ' + (e && e.stack || e)); }
  }
  const page = () => doc.getElementById('page-text');
  const W = {
    doc, reg, queue,
    get now() { return now; },
    fetches: () => fetches,
    swaps: () => swaps,
    errors: () => errors.concat(D.errors()),
    async advance(ms) {
      const end = now + ms;
      for (;;) {
        let best = null;
        for (const [id, t] of timers) if (t.at <= end && (!best || t.at < best.t.at || (t.at === best.t.at && id < best.id))) best = { id, t };
        if (!best) break;
        now = best.t.at;
        if (best.t.every) best.t.at += best.t.every; else timers.delete(best.id);
        try { best.t.f(...best.t.a); } catch (e) { errors.push('TIMER: ' + (e && e.stack || e)); }
        await settle();
      }
      now = end; await settle();
    },
    async advanceTo(t) { if (t > now) await W.advance(t - now); },
    /* The hand moves: mouseout / mouseleave on what it left, mouseover /
       mouseenter on what it reached. A node already removed from the page
       gets no boundary events, as in Chrome and Firefox. */
    pointTo(el) {
      const chain = n => { const a = []; while (n && n.nodeType === 1) { a.push(n); n = n.parentNode; } return a; };
      const old = D.getPointer();
      const oldLive = old && old.isConnected ? old : null;
      const oldC = oldLive ? chain(oldLive) : [];
      const newC = el ? chain(el) : [];
      if (oldLive) D.dispatch(oldLive, new D.Event('mouseout', { bubbles: true, relatedTarget: el }));
      oldC.filter(n => !newC.includes(n)).forEach(n => D.dispatch(n, new D.Event('mouseleave', { relatedTarget: el })));
      D.setPointer(el);
      if (el) D.dispatch(el, new D.Event('mouseover', { bubbles: true, relatedTarget: oldLive }));
      newC.filter(n => !oldC.includes(n)).reverse().forEach(n => D.dispatch(n, new D.Event('mouseenter', { relatedTarget: oldLive })));
    },
    /* The hand moves without leaving the element it is on: a mousemove and
       no boundary event at all. */
    wiggle() {
      const p = D.getPointer();
      if (p && p.isConnected) D.dispatch(p, new D.Event('mousemove', { bubbles: true, clientX: 300, clientY: 120 }));
    },
    target(item) { return item ? (item.querySelector('span') || item) : null; },
    cards() { return doc.body.children.filter(p => p.matches(CARD) && p.style.display === 'block'); },
    shownFor(item) { return W.cards().filter(p => p._origParent === item); },
    ghosts() { return W.cards().filter(p => !(p._origParent && p._origParent.isConnected)).length; },
    items(kind) {
      const host = doc.getElementById({ ticker: 'tickerTrack', dh: 'dhTrack', wl: 'railWatchBody' }[kind]);
      const sel = { ticker: '.ticker-item', dh: '.dh-item', wl: '.wl-item' }[kind];
      return host ? host.children.filter(e => e.matches(sel)) : [];
    },
    boundItems() {
      return [].concat(W.items('ticker'), W.items('dh'), W.items('wl'))
        .filter(e => Object.keys(e._l).some(k => e._l[k].length)).length;
    },
    firstNewsId() { const t = W.items('ticker')[0]; return t ? t.getAttribute('data-news-id') : null; },
    /* A hand rests on an item past the beat: exactly one card must be up,
       its own, under it; the hand leaves and it closes. */
    async probe(item) {
      if (!item || !item.isConnected) return false;
      W.pointTo(page()); await W.advance(400);
      W.pointTo(W.target(item)); await W.advance(500);
      const mine = W.shownFor(item);
      const r = item.getBoundingClientRect();
      const placed = mine.length === 1 && W.cards().length === 1
        && (item.matches('.wl-item') || mine[0].style.top === (r.bottom + 4) + 'px');
      W.pointTo(page()); await W.advance(400);
      return placed && W.cards().length === 0;
    },
    async hoverAll() {
      const t = W.items('ticker'), d = W.items('dh'), w = W.items('wl');
      const half = Math.floor(t.length / 2), dhalf = Math.floor(d.length / 2);
      return {
        ticker_first_half: await W.probe(t[0]),
        ticker_first_half_end: await W.probe(t[half - 1]),
        ticker_second_half: await W.probe(t[half]),
        ticker_second_half_end: await W.probe(t[t.length - 1]),
        headband_first_half: await W.probe(d[0]),
        headband_second_half: await W.probe(d[dhalf]),
        watchlist: await W.probe(w[0]),
        ticker_items: t.length,
        ghost_cards: W.ghosts(),
        sv_popup_open: reg.length,
      };
    },
    wsSend(msg) { const s = sockets[sockets.length - 1]; s.onmessage({ data: JSON.stringify(msg) }); },
    fire(type) { D.dispatch(doc, new D.Event(type, {})); },
    fireWindow(type, init) {
      const ev = new D.Event(type, init || {}); ev.target = win;
      (win._l[type] || []).slice().forEach(x => {
        try { x.f.call(win, ev); } catch (e) { errors.push(type + ': ' + (e && e.stack || e)); } });
    },
    setHidden(h) {
      doc.hidden = h; doc.visibilityState = h ? 'hidden' : 'visible';
      D.dispatch(doc, new D.Event('visibilitychange', {}));
    },
  };
  return W;
}

/* Hours of a page left open. The sweep runs every five minutes from load,
   so every hand rests between two of them. */
async function longSession() {
  const W = boot();
  const steps = [];
  const out = { steps };
  const rec = async (step) => {
    steps.push(Object.assign({ step, clock: mmss(W.now), fetches: W.fetches(), swaps: W.swaps() },
                             await W.hoverAll()));
  };
  out.bound_items_at_load = W.boundItems();
  await rec('page load');
  for (let m = 1; m <= 60; m++) {
    await W.advanceTo(m * MIN);
    W.wsSend({ type: 'quote', data: { symbol: ['EURUSD', 'GBPUSD', 'AAPL', 'BTCUSD'][m % 4],
                                      last: 1.1 + m / 1000, change_pct: (m % 7) - 3 } });
    if (m === 5 || m === 30 || m === 60) {
      await W.advance(1500);
      await rec('tab visible ' + m + ' minutes (' + (m / 5) + ' sweeps)');
    }
  }
  await W.advanceTo(62 * MIN);
  W.wsSend({ type: 'news' }); await W.advance(1500);
  await rec('a news push');
  await W.advanceTo(64 * MIN);
  const under = W.items('ticker')[1];
  W.pointTo(W.target(under)); await W.advance(500);
  const swapsBeforePush = W.swaps();
  const push = { card_open_before: W.shownFor(under).length };
  W.wsSend({ type: 'news' }); await W.advance(1500);
  push.swaps_while_read = W.swaps() - swapsBeforePush;
  push.card_kept_while_read = W.shownFor(under).length;
  push.item_kept_while_read = under.isConnected;
  W.pointTo(W.doc.getElementById('page-text')); await W.advance(1000);
  push.swaps_after_leaving = W.swaps() - swapsBeforePush;
  push.item_gone_after_leaving = !under.isConnected;
  push.ghosts_after_leaving = W.ghosts();
  push.cards_after_leaving = W.cards().length;
  out.push_under_card = push;
  await rec('a news push under an open card');
  await W.advanceTo(66 * MIN);
  W.setHidden(true);
  await W.advanceTo(106 * MIN);
  W.setHidden(false); await W.advance(1500);
  await rec('forty minutes in another tab, then back');
  await W.advanceTo(108 * MIN);
  W.fire('sv:pin-unlocked'); await W.advance(1500);
  await rec('the PIN gate lifted');
  await W.advanceTo(290 * MIN); await W.advance(1500);
  await rec('three more hours of sweeps');
  out.bound_items_at_end = W.boundItems();
  out.fetches = W.fetches();
  out.swaps = W.swaps();
  out.errors = W.errors();
  return out;
}

/* The hand rests on a headline, its card is up, and fresh headlines
   arrive. They wait while the card is read — the hand on the item, then on
   the card itself — and land the moment the hand has left, leaving no card
   behind; the fresh item under the hand then answers it. */
async function swapUnderOpenCard() {
  const W = boot();
  const page = W.doc.getElementById('page-text');
  const item = W.items('ticker')[0];
  W.pointTo(W.target(item)); await W.advance(500);
  const out = { card_open_before: W.shownFor(item).length };
  W.wsSend({ type: 'news' }); await W.advance(900);
  out.fetches = W.fetches();
  out.swaps_while_on_the_item = W.swaps();
  out.card_kept_while_on_the_item = W.shownFor(item).length;
  const card = W.shownFor(item)[0];
  if (card) { W.pointTo(card.firstElementChild || card); await W.advance(1000); }
  out.swaps_while_on_the_card = W.swaps();
  out.card_kept_while_read = W.shownFor(item).length;
  out.item_kept_while_read = item.isConnected;
  W.pointTo(page); await W.advance(1000);
  out.swaps = W.swaps();
  out.old_item_gone = !item.isConnected;
  out.ghost_cards = W.ghosts();
  out.cards_open = W.cards().length;
  out.sv_popup_open = W.reg.length;
  const fresh = W.items('ticker')[0];
  W.pointTo(W.target(fresh)); await W.advance(500);
  out.fresh_card = W.shownFor(fresh).length;
  out.cards_open_on_fresh = W.cards().length;
  W.pointTo(page); await W.advance(600);
  out.cards_open_after_leaving = W.cards().length;
  out.sv_popup_open_at_end = W.reg.length;
  out.errors = W.errors();
  return out;
}

/* The hand has just left a card — inside its crossing grace, the card
   still up — when fresh headlines land: nobody is reading, so they land at
   once, and the card whose item they took closes with it, not a moment
   later on its own grace. */
async function swapInsideTheGrace() {
  const W = boot();
  const item = W.items('ticker')[0];
  W.pointTo(W.target(item)); await W.advance(500);          // t=500, card up
  const out = { card_open_before: W.shownFor(item).length };
  W.queue.push({ kind: 'fresh', delay: 1000 });
  W.wsSend({ type: 'news' });                               // fetch at 1300, answer at 2300
  await W.advance(1700);                                    // t=2200
  out.card_open_before_leaving = W.shownFor(item).length;
  W.pointTo(W.doc.getElementById('page-text'));             // grace until 2460
  await W.advance(150);                                     // t=2350
  out.swaps = W.swaps();
  out.old_item_gone = !item.isConnected;
  out.ghost_cards_inside_the_grace = W.ghosts();
  out.cards_open_inside_the_grace = W.cards().length;
  await W.advance(600);
  out.cards_open_after = W.cards().length;
  out.sv_popup_open = W.reg.length;
  out.errors = W.errors();
  return out;
}

/* An answer arrives after the hand did and before the beat: it waits, the
   beat opens the card of the item under the hand — still there — and the
   answer lands once the hand has left, with no card left behind. */
async function swapInsideTheBeat() {
  const W = boot();
  const page = W.doc.getElementById('page-text');
  W.wsSend({ type: 'news' });                 // the answer arrives at 800 ms
  await W.advance(500);
  const item = W.items('ticker')[1];
  W.pointTo(W.target(item));                  // the beat fires at 950 ms
  await W.advance(400);
  const out = { fetches: W.fetches(), swaps_inside_the_beat: W.swaps(),
                item_kept: item.isConnected };
  await W.advance(300);
  out.card_for_the_item_under_the_hand = W.shownFor(item).length;
  out.cards_open = W.cards().length;
  W.pointTo(page); await W.advance(1000);
  out.swaps_after_leaving = W.swaps();
  out.old_item_gone = !item.isConnected;
  out.cards_open_after_leaving = W.cards().length;
  out.ghost_cards = W.ghosts();
  out.sv_popup_open = W.reg.length;
  out.errors = W.errors();
  return out;
}

/* The operator switches tabs with a card up and the hand resting on its
   item. The card closes with the tab. Back on the tab, the fresh headlines
   wait under the resting hand, and the first move inside the same item —
   which crosses no edge, so no mouseover comes — brings the card back; the
   headlines land once the hand leaves. Then a beat running when the tab
   hides opens nothing in the background. */
async function tabSwitch() {
  const W = boot();
  const page = W.doc.getElementById('page-text');
  const item = W.items('ticker')[2];
  W.pointTo(W.target(item)); await W.advance(500);
  const out = { card_open_before: W.shownFor(item).length };
  W.setHidden(true);
  out.cards_open_while_hidden = W.cards().length;
  out.sv_popup_open_while_hidden = W.reg.length;
  await W.advance(20 * MIN);
  W.setHidden(false); await W.advance(1500);
  out.fetches_on_return = W.fetches();
  out.swaps_on_return = W.swaps();
  out.item_kept_under_the_hand = item.isConnected;
  out.cards_open_on_return = W.cards().length;
  W.wiggle(); await W.advance(500);
  out.card_after_a_move_inside_the_item = W.shownFor(item).length;
  out.cards_open_after_the_move = W.cards().length;
  W.pointTo(page); await W.advance(1000);
  out.swaps_after_leaving = W.swaps();
  out.ghost_cards_after_leaving = W.ghosts();
  out.cards_open_after_leaving = W.cards().length;
  out.hover_after_return = await W.probe(W.items('ticker')[2]);
  const it2 = W.items('dh')[3];
  W.pointTo(W.target(it2)); await W.advance(200);
  W.setHidden(true); await W.advance(2000);
  out.cards_opened_by_a_beat_while_hidden = W.cards().length;
  W.setHidden(false); await W.advance(1500);
  out.hover_at_end = await W.probe(W.items('ticker')[W.items('ticker').length - 1]);
  out.errors = W.errors();
  return out;
}

/* Fresh headlines are waiting under a card being read when the tab hides:
   nobody reads a hidden tab, so they land then, and no card stays up for
   the item they took. The same answer on return rewrites nothing. */
async function heldAnswerWhenTheTabHides() {
  const W = boot();
  const item = W.items('ticker')[3];
  W.pointTo(W.target(item)); await W.advance(500);
  W.wsSend({ type: 'news' }); await W.advance(1500);
  const out = { swaps_while_read: W.swaps(), card_open_while_read: W.shownFor(item).length };
  W.setHidden(true);
  out.swaps_when_hidden = W.swaps();
  out.old_item_gone = !item.isConnected;
  out.ghost_cards = W.ghosts();
  out.cards_open = W.cards().length;
  out.sv_popup_open = W.reg.length;
  await W.advance(10 * MIN);
  W.queue.push({ kind: 'same' });
  W.setHidden(false); await W.advance(1500);
  out.fetches = W.fetches();
  out.swaps_on_return = W.swaps();
  out.errors = W.errors();
  return out;
}

/* The first sweep of a page whose headlines have not moved: the answer
   says what the page's first render says, so nothing is rewritten. A
   changed answer then does land. */
async function sameHeadlinesAsTheFirstRender() {
  const W = boot();
  const first = W.items('ticker')[0];
  W.queue.push({ kind: 'initial' });
  await W.advanceTo(5 * MIN); await W.advance(1500);
  const out = { fetches: W.fetches(), swaps: W.swaps(), first_item_kept: first.isConnected };
  W.wsSend({ type: 'news' }); await W.advance(1500);
  out.fetches_after_change = W.fetches();
  out.swaps_after_change = W.swaps();
  out.first_item_gone_after_change = !first.isConnected;
  out.errors = W.errors();
  return out;
}

/* A card up when the page goes into the back/forward cache and comes back. */
async function backForwardCache() {
  const W = boot();
  const item = W.items('dh')[1];
  W.pointTo(W.target(item)); await W.advance(500);
  const out = { card_open_before: W.shownFor(item).length };
  // The first pageshow follows the load: a card already up is the hand's.
  W.fireWindow('pageshow', { persisted: false });
  out.card_open_after_the_first_pageshow = W.shownFor(item).length;
  W.fireWindow('pagehide', { persisted: true });
  W.fireWindow('pageshow', { persisted: true });
  out.cards_open_after_restore = W.cards().length;
  out.sv_popup_open_after_restore = W.reg.length;
  out.hover_after_restore = await W.probe(W.items('ticker')[1]);
  out.errors = W.errors();
  return out;
}

/* A server error, a network failure, the login wall behind a redirect, a
   redirect to anything else, a whole page without one: none may touch the
   band, none may stop the next refresh, and an answer equal to the last
   one rewrites nothing. */
async function badAnswers() {
  const W = boot();
  const first = W.items('ticker')[0];
  W.queue.push({ kind: 'error' }, { kind: 'reject' }, { kind: 'login' }, { kind: 'moved' }, { kind: 'page' });
  for (let i = 0; i < 5; i++) { W.wsSend({ type: 'news' }); await W.advance(1500); }
  const out = { fetches_after_bad: W.fetches(), swaps_after_bad: W.swaps(),
                band_kept_its_items: first.isConnected,
                login_page_in_band: W.doc.getElementById('tickerTrack').textContent.indexOf('Sign in to Sauron') >= 0,
                ticker_items_after_bad: W.items('ticker').length };
  out.hover_after_bad = await W.probe(W.items('ticker')[0]);
  W.wsSend({ type: 'news' }); await W.advance(1500);
  out.swaps_after_good = W.swaps();
  out.hover_after_good = await W.probe(W.items('ticker')[0]);
  out.hover_after_good_second_half = await W.probe(W.items('ticker')[W.items('ticker').length / 2]);
  const kept = W.items('ticker')[0];
  W.queue.push({ kind: 'same' });
  W.wsSend({ type: 'news' }); await W.advance(1500);
  out.same_answer_kept_the_items = kept.isConnected;
  out.fetches = W.fetches();
  out.errors = W.errors();
  return out;
}

/* Some other code rewrites the band and announces nothing. Hover must hold
   anyway: a beat running for a removed item opens nothing, and a card left
   behind closes the moment the hand moves onto the band again. */
async function unannouncedRewrite() {
  const W = boot();
  const track = W.doc.getElementById('tickerTrack');
  let n = 0;
  const body = () => IN.answer.split(IN.fresh_id).join(String(500000 + (++n)));
  const item = W.items('ticker')[1];
  W.pointTo(W.target(item)); await W.advance(200);
  track.innerHTML = body();
  await W.advance(400);
  const out = { cards_from_a_beat_on_a_removed_item: W.cards().length };
  const it2 = W.items('ticker')[2];
  W.pointTo(W.target(it2)); await W.advance(500);
  out.card_open_before = W.shownFor(it2).length;
  track.innerHTML = body();
  out.cards_left_until_the_hand_moves = W.ghosts();
  const fresh = W.items('ticker')[2];
  W.pointTo(W.target(fresh)); await W.advance(500);
  out.ghosts_after_the_hand_moved = W.ghosts();
  out.fresh_card = W.shownFor(fresh).length;
  out.cards_open = W.cards().length;
  W.pointTo(W.doc.getElementById('page-text')); await W.advance(600);
  out.cards_open_after_leaving = W.cards().length;
  out.sv_popup_open_at_end = W.reg.length;
  out.errors = W.errors();
  return out;
}

/* Two refreshes in flight: the older answer arrives last. */
async function latestAnswerWins() {
  const W = boot();
  W.queue.push({ kind: 'fresh', id: 111111, delay: 5000 }, { kind: 'fresh', id: 222222 });
  W.wsSend({ type: 'news' }); await W.advance(1000);
  W.wsSend({ type: 'news' }); await W.advance(1000);
  const out = { first_after_newer: W.firstNewsId() };
  await W.advance(6000);
  out.first_at_end = W.firstNewsId();
  out.fetches = W.fetches();
  out.hover_at_end = await W.probe(W.items('ticker')[0]);
  out.errors = W.errors();
  return out;
}

/* What delegation must NOT change: a travelling hand opens nothing, the
   item it stops on opens its card, the card holds while it is read and
   closes after the grace once the hand leaves it. */
async function beatAndGrace() {
  const W = boot();
  const t = W.items('ticker');
  W.pointTo(W.doc.getElementById('page-text')); await W.advance(100);
  for (let i = 0; i < 3; i++) { W.pointTo(W.target(t[i])); await W.advance(200); }
  const out = { cards_while_travelling: W.cards().length };
  W.pointTo(W.target(t[3])); await W.advance(500);
  out.card_for_the_stop = W.shownFor(t[3]).length;
  out.cards_open = W.cards().length;
  const card = W.shownFor(t[3])[0];
  if (card) { W.pointTo(card.firstElementChild || card); await W.advance(1000); }
  out.card_held_while_read = W.shownFor(t[3]).length;
  W.pointTo(W.doc.getElementById('page-text')); await W.advance(100);
  out.card_during_the_grace = W.shownFor(t[3]).length;
  await W.advance(300);
  out.cards_after_the_grace = W.cards().length;
  out.card_back_in_its_item = !!card && card.parentNode === t[3];
  out.errors = W.errors();
  return out;
}

(async () => {
  const out = {};
  out.long_session = await longSession();
  out.swap_under_open_card = await swapUnderOpenCard();
  out.swap_inside_the_grace = await swapInsideTheGrace();
  out.swap_inside_the_beat = await swapInsideTheBeat();
  out.tab_switch = await tabSwitch();
  out.held_answer_when_the_tab_hides = await heldAnswerWhenTheTabHides();
  out.same_headlines_as_the_first_render = await sameHeadlinesAsTheFirstRender();
  out.back_forward_cache = await backForwardCache();
  out.bad_answers = await badAnswers();
  out.unannounced_rewrite = await unannouncedRewrite();
  out.latest_answer_wins = await latestAnswerWins();
  out.beat_and_grace = await beatAndGrace();
  process.stdout.write(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


def _session_report():
    tmp = Path(tempfile.mkdtemp(prefix="sv-hover-"))
    try:
        (tmp / "dom.js").write_text(DOM_JS, encoding="utf-8")
        (tmp / "run.js").write_text(RUN_JS, encoding="utf-8")
        (tmp / "input.json").write_text(json.dumps(_inputs()), encoding="utf-8")
        proc = subprocess.run([NODE, str(tmp / "run.js"), str(tmp / "input.json")],
                              capture_output=True, text=True, timeout=300,
                              encoding="utf-8")
        if proc.returncode != 0:
            raise AssertionError("the session runner failed: %s" % proc.stderr[:3000])
        return json.loads(proc.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(NODE, "node is not installed on this machine")
class TheBandsStayHoverableTests(SimpleTestCase):
    """The page's own scripts, as shipped, through hours of a page left
    open."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report = _session_report()

    def _dump(self, key):
        return json.dumps(self.report[key], indent=1, ensure_ascii=False)[:8000]

    def test_every_band_opens_its_card_after_every_step_of_a_long_session(self):
        """Hover used to die with the first sweep: five minutes into a
        visible page, or on the first return to the tab."""
        r = self.report["long_session"]
        self.assertEqual(
            [s["step"] for s in r["steps"]],
            ["page load", "tab visible 5 minutes (1 sweeps)",
             "tab visible 30 minutes (6 sweeps)",
             "tab visible 60 minutes (12 sweeps)", "a news push",
             "a news push under an open card",
             "forty minutes in another tab, then back", "the PIN gate lifted",
             "three more hours of sweeps"])
        for s in r["steps"]:
            for probe in PROBES:
                with self.subTest(step=s["step"], probe=probe):
                    self.assertTrue(s[probe], "no card on hover at %s (%s):\n%s"
                                    % (s["step"], probe, json.dumps(s, indent=1)))
            with self.subTest(step=s["step"], probe="nothing left open"):
                self.assertEqual(s["ghost_cards"], 0)
                self.assertEqual(s["sv_popup_open"], 0)
                self.assertEqual(s["ticker_items"], 12)

    def test_the_long_session_really_rewrote_the_band_every_time(self):
        """A test that passes on a band nothing touched proves nothing:
        every sweep, push, return and unlock rewrote the items."""
        r = self.report["long_session"]
        self.assertEqual(r["fetches"], r["swaps"], self._dump("long_session"))
        self.assertGreaterEqual(r["swaps"], 50, self._dump("long_session"))
        self.assertEqual(r["errors"], [])

    def test_nothing_is_bound_to_an_item_a_refresh_can_replace(self):
        """Hover lives on each band's frame; an item carries no listener to
        lose when it is rewritten."""
        r = self.report["long_session"]
        self.assertEqual(r["bound_items_at_load"], 0)
        self.assertEqual(r["bound_items_at_end"], 0)

    def test_fresh_headlines_wait_while_a_card_is_read_and_leave_none_behind(self):
        """The card the operator is reading is not taken from under them:
        the answer waits while the hand is on the item or on the card, and
        lands the moment the hand has left — no card left on <body> for the
        item it removed, and the fresh item answers the next hover."""
        r = self.report["swap_under_open_card"]
        self.assertEqual(r["card_open_before"], 1, self._dump("swap_under_open_card"))
        self.assertEqual(r["fetches"], 1)
        self.assertEqual(r["swaps_while_on_the_item"], 0, self._dump("swap_under_open_card"))
        self.assertEqual(r["card_kept_while_on_the_item"], 1)
        self.assertEqual(r["swaps_while_on_the_card"], 0, self._dump("swap_under_open_card"))
        self.assertEqual(r["card_kept_while_read"], 1)
        self.assertTrue(r["item_kept_while_read"])
        self.assertEqual(r["swaps"], 1, "the waiting answer never landed:\n"
                         + self._dump("swap_under_open_card"))
        self.assertTrue(r["old_item_gone"])
        self.assertEqual(r["ghost_cards"], 0, "a card still hangs on <body> for "
                         "an item the rewrite removed")
        self.assertEqual(r["cards_open"], 0)
        self.assertEqual(r["sv_popup_open"], 0)
        self.assertEqual(r["fresh_card"], 1, self._dump("swap_under_open_card"))
        self.assertEqual(r["cards_open_on_fresh"], 1)
        self.assertEqual(r["cards_open_after_leaving"], 0)
        self.assertEqual(r["sv_popup_open_at_end"], 0)
        self.assertEqual(r["errors"], [])
        # The same, an hour into the long session.
        self.assertEqual(self.report["long_session"]["push_under_card"], {
            "card_open_before": 1, "swaps_while_read": 0,
            "card_kept_while_read": 1, "item_kept_while_read": True,
            "swaps_after_leaving": 1, "item_gone_after_leaving": True,
            "ghosts_after_leaving": 0, "cards_after_leaving": 0},
            self._dump("long_session"))

    def test_a_rewrite_inside_the_crossing_grace_takes_the_card_with_it(self):
        """Nobody is reading once the hand has left, so the answer lands at
        once — and the announced swap closes the card whose item it took,
        instead of leaving it on <body> pointing at nothing."""
        r = self.report["swap_inside_the_grace"]
        self.assertEqual(r["card_open_before"], 1, self._dump("swap_inside_the_grace"))
        self.assertEqual(r["card_open_before_leaving"], 1)
        self.assertEqual(r["swaps"], 1, self._dump("swap_inside_the_grace"))
        self.assertTrue(r["old_item_gone"])
        self.assertEqual(r["ghost_cards_inside_the_grace"], 0,
                         self._dump("swap_inside_the_grace"))
        self.assertEqual(r["cards_open_inside_the_grace"], 0)
        self.assertEqual(r["cards_open_after"], 0)
        self.assertEqual(r["sv_popup_open"], 0)
        self.assertEqual(r["errors"], [])

    def test_an_answer_inside_the_hover_beat_waits_for_the_hand(self):
        """The beat opens the card of the item the hand stopped on, which
        is still there; the answer lands after the hand leaves, and no card
        is left for the item it removed."""
        r = self.report["swap_inside_the_beat"]
        self.assertEqual(r["fetches"], 1, self._dump("swap_inside_the_beat"))
        self.assertEqual(r["swaps_inside_the_beat"], 0, self._dump("swap_inside_the_beat"))
        self.assertTrue(r["item_kept"])
        self.assertEqual(r["card_for_the_item_under_the_hand"], 1,
                         self._dump("swap_inside_the_beat"))
        self.assertEqual(r["cards_open"], 1)
        self.assertEqual(r["swaps_after_leaving"], 1)
        self.assertTrue(r["old_item_gone"])
        self.assertEqual(r["cards_open_after_leaving"], 0)
        self.assertEqual(r["ghost_cards"], 0)
        self.assertEqual(r["sv_popup_open"], 0)
        self.assertEqual(r["errors"], [])

    def test_a_tab_switch_closes_the_card_and_the_first_move_back_reopens_it(self):
        """No mouseleave comes when the operator switches tabs: the card
        closes with the tab and a running beat opens nothing in the
        background. Back on the tab with the hand where it was, the first
        move inside that same item — no edge crossed, no mouseover — brings
        its card back, and the headlines that waited land once the hand
        leaves."""
        r = self.report["tab_switch"]
        self.assertEqual(r["card_open_before"], 1, self._dump("tab_switch"))
        self.assertEqual(r["cards_open_while_hidden"], 0, self._dump("tab_switch"))
        self.assertEqual(r["sv_popup_open_while_hidden"], 0)
        self.assertEqual(r["fetches_on_return"], 1)
        self.assertEqual(r["swaps_on_return"], 0, self._dump("tab_switch"))
        self.assertTrue(r["item_kept_under_the_hand"])
        self.assertEqual(r["cards_open_on_return"], 0)
        self.assertEqual(r["card_after_a_move_inside_the_item"], 1,
                         "the hand moved on its item and no card came back:\n"
                         + self._dump("tab_switch"))
        self.assertEqual(r["cards_open_after_the_move"], 1)
        self.assertEqual(r["swaps_after_leaving"], 1, self._dump("tab_switch"))
        self.assertEqual(r["ghost_cards_after_leaving"], 0)
        self.assertEqual(r["cards_open_after_leaving"], 0)
        self.assertTrue(r["hover_after_return"], self._dump("tab_switch"))
        self.assertEqual(r["cards_opened_by_a_beat_while_hidden"], 0)
        self.assertTrue(r["hover_at_end"], self._dump("tab_switch"))
        self.assertEqual(r["errors"], [])

    def test_waiting_headlines_land_when_the_tab_hides(self):
        r = self.report["held_answer_when_the_tab_hides"]
        self.assertEqual(r["swaps_while_read"], 0, self._dump("held_answer_when_the_tab_hides"))
        self.assertEqual(r["card_open_while_read"], 1)
        self.assertEqual(r["swaps_when_hidden"], 1, self._dump("held_answer_when_the_tab_hides"))
        self.assertTrue(r["old_item_gone"])
        self.assertEqual(r["ghost_cards"], 0)
        self.assertEqual(r["cards_open"], 0)
        self.assertEqual(r["sv_popup_open"], 0)
        # The same answer on return: fetched, and nothing rewritten.
        self.assertEqual(r["fetches"], 2)
        self.assertEqual(r["swaps_on_return"], 1, self._dump("held_answer_when_the_tab_hides"))
        self.assertEqual(r["errors"], [])

    def test_the_first_sweep_of_unchanged_headlines_rewrites_nothing(self):
        """The page's first render is the baseline: an answer that says the
        same leaves every item where it is, even the first time."""
        r = self.report["same_headlines_as_the_first_render"]
        self.assertEqual(r["fetches"], 1, self._dump("same_headlines_as_the_first_render"))
        self.assertEqual(r["swaps"], 0, "the first sweep rewrote a band that "
                         "already said the same:\n"
                         + self._dump("same_headlines_as_the_first_render"))
        self.assertTrue(r["first_item_kept"])
        self.assertEqual(r["fetches_after_change"], 2)
        self.assertEqual(r["swaps_after_change"], 1)
        self.assertTrue(r["first_item_gone_after_change"])
        self.assertEqual(r["errors"], [])

    def test_a_page_back_from_the_back_forward_cache_shows_no_stale_card(self):
        """A headline clicked with its card up, then Back: the page comes
        back from the cache exactly as it left, card included."""
        r = self.report["back_forward_cache"]
        self.assertEqual(r["card_open_before"], 1, self._dump("back_forward_cache"))
        self.assertEqual(r["card_open_after_the_first_pageshow"], 1)
        self.assertEqual(r["cards_open_after_restore"], 0, self._dump("back_forward_cache"))
        self.assertEqual(r["sv_popup_open_after_restore"], 0)
        self.assertTrue(r["hover_after_restore"])
        self.assertEqual(r["errors"], [])

    def test_a_failed_refresh_or_a_login_page_never_breaks_the_band(self):
        r = self.report["bad_answers"]
        self.assertEqual(r["fetches_after_bad"], 5, self._dump("bad_answers"))
        self.assertEqual(r["swaps_after_bad"], 0, "an answer that is not the "
                         "marquee was written into the band:\n" + self._dump("bad_answers"))
        self.assertTrue(r["band_kept_its_items"])
        self.assertFalse(r["login_page_in_band"])
        self.assertEqual(r["ticker_items_after_bad"], 12)
        self.assertTrue(r["hover_after_bad"], self._dump("bad_answers"))
        # One failure never stops the next refresh.
        self.assertEqual(r["swaps_after_good"], 1)
        self.assertTrue(r["hover_after_good"], self._dump("bad_answers"))
        self.assertTrue(r["hover_after_good_second_half"])
        # The same answer again rewrites nothing under the hand.
        self.assertEqual(r["fetches"], 7)
        self.assertTrue(r["same_answer_kept_the_items"], self._dump("bad_answers"))
        self.assertEqual(r["errors"], [])

    def test_a_rewrite_nobody_announced_still_leaves_hover_working(self):
        """Hover does not depend on every future rewrite remembering to say
        so: the frame hears the fresh items, a beat for a removed item opens
        nothing, and a card left behind closes when the hand comes back."""
        r = self.report["unannounced_rewrite"]
        self.assertEqual(r["cards_from_a_beat_on_a_removed_item"], 0,
                         self._dump("unannounced_rewrite"))
        self.assertEqual(r["card_open_before"], 1)
        self.assertEqual(r["ghosts_after_the_hand_moved"], 0, self._dump("unannounced_rewrite"))
        self.assertEqual(r["fresh_card"], 1, self._dump("unannounced_rewrite"))
        self.assertEqual(r["cards_open"], 1)
        self.assertEqual(r["cards_open_after_leaving"], 0)
        self.assertEqual(r["sv_popup_open_at_end"], 0)
        self.assertEqual(r["errors"], [])

    def test_only_the_latest_answer_lands(self):
        """A slow answer overtaken by a newer sweep must not put older
        headlines back."""
        r = self.report["latest_answer_wins"]
        self.assertEqual(r["fetches"], 2)
        self.assertEqual(r["first_after_newer"], "222222", self._dump("latest_answer_wins"))
        self.assertEqual(r["first_at_end"], "222222", self._dump("latest_answer_wins"))
        self.assertTrue(r["hover_at_end"])
        self.assertEqual(r["errors"], [])

    def test_the_beat_and_the_grace_are_what_they_were(self):
        """Delegation changes where hover is heard, not how it behaves."""
        r = self.report["beat_and_grace"]
        self.assertEqual(r["cards_while_travelling"], 0, self._dump("beat_and_grace"))
        self.assertEqual(r["card_for_the_stop"], 1)
        self.assertEqual(r["cards_open"], 1)
        self.assertEqual(r["card_held_while_read"], 1)
        self.assertEqual(r["card_during_the_grace"], 1)
        self.assertEqual(r["cards_after_the_grace"], 0)
        self.assertTrue(r["card_back_in_its_item"])
        self.assertEqual(r["errors"], [])


class TheLoopsSecondHalfHasItsCardTests(TestCase):
    """The copy that makes the marquee seamless is the same item, card
    included — through the endpoint the sweep fetches."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("hb_hover", password="x")
        self.client.force_login(self.user)

    def test_both_halves_of_the_partial_carry_the_card(self):
        from django.utils import timezone as tz

        from scraping.models import NewsArticle
        NewsArticle.objects.create(
            title="Copper squeezes shorts", source="Reuters",
            url="https://example.test/hb-hover-copper",
            published_at=tz.now(), content_summary="Copper summary line")
        resp = self.client.get("/partials/ticker/", HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertEqual(html.count("data-news-id="), 2)
        self.assertEqual(html.count('class="ticker-popup"'), 2)
        second = html.split('class="ticker-item"')[2]
        self.assertIn('class="ticker-popup"', second)
        self.assertIn("Copper squeezes shorts", second)
        self.assertIn("Copper summary line", second)

    def test_one_item_template_serves_both_halves(self):
        """Two hand-kept copies drifted once — the second lost its card."""
        src = (Path(settings.BASE_DIR) / "templates" / "_partials"
               / "ticker_items.html").read_text(encoding="utf-8")
        self.assertEqual(src.count('{% include "_partials/ticker_item.html" %}'), 2)
        self.assertNotIn('<a href="{{ item.url }}" class="ticker-item"', src)
