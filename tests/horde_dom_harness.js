/* A small DOM for driving static/js/sv-horde.js under node (tests/
 * test_the_horde.py TheScriptBehaviourTests). No jsdom on the build
 * machines, so this is the least of a document the script touches:
 * elements built from the rendered partial (a JSON tree Python's
 * html.parser made), classes, attributes, text, events that bubble, a
 * selector engine for the selectors the script uses, focus that falls to
 * <body> the way a browser's does (the element removed, hidden or made
 * inert), fake timers and frames, a fetch that answers from the test's
 * payloads, and localStorage.
 *
 *   node horde_dom_harness.js <tree.json> <horde.js> <scenario.js> <payloads.json>
 *
 * The scenario is the body of an async function of (env); what it
 * returns is printed as JSON.
 */
'use strict';
const fs = require('fs');
const vm = require('vm');

const [treePath, scriptPath, scenarioPath, payloadPath] = process.argv.slice(2);

// ── the document ──────────────────────────────────────────────────────
let doc = null;

class Text {
  constructor(text) { this.nodeType = 3; this.data = String(text); this.parentNode = null; }
  get textContent() { return this.data; }
  set textContent(v) { this.data = String(v); }
}

class ClassList {
  constructor(elm) { this.elm = elm; }
  _get() { return (this.elm.getAttribute('class') || '').split(/\s+/).filter(Boolean); }
  _set(list) { this.elm.setAttribute('class', list.join(' ')); }
  contains(c) { return this._get().indexOf(c) !== -1; }
  add(...cs) { const l = this._get(); cs.forEach((c) => { if (l.indexOf(c) === -1) l.push(c); }); this._set(l); }
  remove(...cs) { this._set(this._get().filter((c) => cs.indexOf(c) === -1)); }
  toggle(c, force) {
    const on = force === undefined ? !this.contains(c) : !!force;
    if (on) this.add(c); else this.remove(c);
    return on;
  }
}

class Style {
  constructor() { this._props = {}; }
  setProperty(k, v) { this._props[k] = String(v); }
  getPropertyValue(k) { return this._props[k] || ''; }
  removeProperty(k) { delete this._props[k]; }
}

const FOCUSABLE = { button: 1, input: 1, select: 1, textarea: 1 };

class Element {
  constructor(tag, attrs) {
    this.nodeType = 1;
    this.tagName = String(tag).toUpperCase();
    this.localName = String(tag).toLowerCase();
    this.attrs = Object.assign({}, attrs || {});
    this.childNodes = [];
    this.parentNode = null;
    this.listeners = {};
    this.style = new Style();
    this.classList = new ClassList(this);
    this.scrollTop = 0;
    this.scrollLeft = 0;
    this._clientHeight = 300;
    this._clientWidth = 0;
    this._scrollWidth = 0;          // a number, or a function of the element
    this._rect = null;              // a scenario's measured box, when it sets one
    this.content = null;            // a <template>'s fragment
  }
  // attributes
  getAttribute(n) { return Object.prototype.hasOwnProperty.call(this.attrs, n) ? this.attrs[n] : null; }
  hasAttribute(n) { return Object.prototype.hasOwnProperty.call(this.attrs, n); }
  setAttribute(n, v) {
    this.attrs[n] = String(v);
    if (n === 'inert' && doc && this.contains(doc.activeElement)) doc._blur();
  }
  removeAttribute(n) { delete this.attrs[n]; }
  get id() { return this.getAttribute('id') || ''; }
  set id(v) { this.setAttribute('id', v); }
  get className() { return this.getAttribute('class') || ''; }
  set className(v) { this.setAttribute('class', v); }
  get hidden() { return this.hasAttribute('hidden'); }
  set hidden(v) {
    if (v) { this.setAttribute('hidden', ''); if (doc && this.contains(doc.activeElement)) doc._blur(); }
    else this.removeAttribute('hidden');
  }
  get tabIndex() {
    if (this.hasAttribute('tabindex')) return parseInt(this.getAttribute('tabindex'), 10);
    return (FOCUSABLE[this.localName] || (this.localName === 'a' && this.hasAttribute('href'))) ? 0 : -1;
  }
  set tabIndex(v) { this.setAttribute('tabindex', String(v)); }
  get type() { return this.getAttribute('type') || ''; }
  set type(v) { this.setAttribute('type', v); }
  get href() { return this.getAttribute('href') || ''; }
  set href(v) { this.setAttribute('href', v); }
  get src() { return this.getAttribute('src') || ''; }
  set src(v) { this.setAttribute('src', v); }
  get title() { return this.getAttribute('title') || ''; }
  set title(v) { this.setAttribute('title', v); }
  get rel() { return this.getAttribute('rel') || ''; }
  set rel(v) { this.setAttribute('rel', v); }
  get clientHeight() { return this._clientHeight; }
  get clientWidth() { return this._clientWidth; }
  get scrollWidth() {
    return typeof this._scrollWidth === 'function' ? this._scrollWidth(this) : this._scrollWidth;
  }
  // tree
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  get textContent() { return this.childNodes.map((n) => n.textContent).join(''); }
  set textContent(v) {
    this.childNodes.slice().forEach((n) => this.removeChild(n));
    if (v !== '' && v !== null && v !== undefined) this.appendChild(new Text(v));
  }
  appendChild(n) {
    if (n.parentNode) n.parentNode.removeChild(n);
    n.parentNode = this;
    this.childNodes.push(n);
    return n;
  }
  removeChild(n) {
    const i = this.childNodes.indexOf(n);
    if (i === -1) throw new Error('not a child');
    const lost = doc && n.nodeType === 1 && n.contains(doc.activeElement);
    this.childNodes.splice(i, 1);
    n.parentNode = null;
    if (lost) doc._blur();
    // An emptied scroller has nothing to scroll: a browser resets it.
    if (!this.childNodes.length) this.scrollTop = 0;
    return n;
  }
  contains(n) {
    for (let x = n; x; x = x.parentNode) if (x === this) return true;
    return false;
  }
  closest(sel) {
    for (let x = this; x && x.nodeType === 1; x = x.parentNode) if (matches(x, sel)) return x;
    return null;
  }
  matches(sel) { return matches(this, sel); }
  querySelectorAll(sel) {
    const out = [];
    const walk = (node) => node.childNodes.forEach((c) => {
      if (c.nodeType !== 1) return;
      if (matches(c, sel)) out.push(c);
      walk(c);
    });
    walk(this);
    return out;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  // events
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  removeEventListener(t, fn) { this.listeners[t] = (this.listeners[t] || []).filter((f) => f !== fn); }
  dispatchEvent(ev) {
    ev.target = ev.target || this;
    const path = [];
    for (let x = this; x; x = x.parentNode) path.push(x);
    if (this.isConnected()) path.push(doc);
    for (const node of path) {
      ev.currentTarget = node;
      (node.listeners[ev.type] || []).slice().forEach((fn) => fn.call(node, ev));
      if (ev._stopped) break;
    }
    return !ev.defaultPrevented;
  }
  isConnected() { let x = this; while (x.parentNode) x = x.parentNode; return x === doc.documentElement; }
  // focus
  focus() {
    if (!this.isConnected()) return;
    if (!(FOCUSABLE[this.localName] || this.hasAttribute('tabindex')
          || (this.localName === 'a' && this.hasAttribute('href')))) return;
    for (let x = this; x && x.nodeType === 1; x = x.parentNode) {
      if (x.hasAttribute('hidden') || x.hasAttribute('inert')) return;
    }
    doc.activeElement = this;
  }
  blur() { if (doc.activeElement === this) doc._blur(); }
  click() { this.dispatchEvent(makeEvent('click', { detail: 1 })); }
  getBoundingClientRect() {
    if (this._rect) return Object.assign({ top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 }, this._rect);
    return { top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0 };
  }
  scrollIntoView(opts) { if (doc) (doc.scrolledIntoView = doc.scrolledIntoView || []).push({ id: this.id, opts }); }
  setPointerCapture() {}
  releasePointerCapture() {}
}

// ── selectors: groups, descendants, tag, #id, .class, [a], [a="v"], :not() ──
function parseCompound(s) {
  const out = { tag: null, id: null, classes: [], attrs: [], nots: [] };
  let i = 0;
  const m0 = /^[a-zA-Z][\w-]*/.exec(s);
  if (m0) { out.tag = m0[0].toLowerCase(); i = m0[0].length; }
  while (i < s.length) {
    const c = s[i];
    if (c === '#' || c === '.') {
      const m = /^[\w-]+/.exec(s.slice(i + 1));
      if (c === '#') out.id = m[0]; else out.classes.push(m[0]);
      i += 1 + m[0].length;
    } else if (c === '[') {
      const end = s.indexOf(']', i);
      const body = s.slice(i + 1, end);
      const m = /^([\w-]+)(?:="([^"]*)")?$/.exec(body);
      out.attrs.push({ name: m[1], value: m[2] === undefined ? null : m[2] });
      i = end + 1;
    } else if (s.startsWith(':not(', i)) {
      let depth = 0, j = i + 4;
      for (; j < s.length; j++) { if (s[j] === '(') depth++; else if (s[j] === ')') { depth--; if (!depth) break; } }
      out.nots.push(parseCompound(s.slice(i + 5, j)));
      i = j + 1;
    } else throw new Error('selector not understood: ' + s);
  }
  return out;
}
function matchCompound(e, c) {
  if (c.tag && e.localName !== c.tag) return false;
  if (c.id && e.id !== c.id) return false;
  for (const k of c.classes) if (!e.classList.contains(k)) return false;
  for (const a of c.attrs) {
    if (!e.hasAttribute(a.name)) return false;
    if (a.value !== null && e.getAttribute(a.name) !== a.value) return false;
  }
  for (const n of c.nots) if (matchCompound(e, n)) return false;
  return true;
}
function splitTop(s, ch) {
  const out = []; let depth = 0, quote = false, cur = '';
  for (const c of s) {
    if (c === '"') quote = !quote;
    if (!quote && (c === '(' || c === '[')) depth++;
    if (!quote && (c === ')' || c === ']')) depth--;
    if (!quote && !depth && c === ch) { out.push(cur); cur = ''; } else cur += c;
  }
  out.push(cur);
  return out.map((x) => x.trim()).filter(Boolean);
}
function matches(e, sel) {
  return splitTop(sel, ',').some((group) => {
    const parts = splitTop(group, ' ').map(parseCompound);
    if (!matchCompound(e, parts[parts.length - 1])) return false;
    let x = e.parentNode;
    for (let k = parts.length - 2; k >= 0; k--) {
      while (x && x.nodeType === 1 && !matchCompound(x, parts[k])) x = x.parentNode;
      if (!x || x.nodeType !== 1) return false;
      x = x.parentNode;
    }
    return true;
  });
}

function makeEvent(type, props) {
  return Object.assign({
    type, target: null, currentTarget: null, defaultPrevented: false, _stopped: false,
    preventDefault() { this.defaultPrevented = true; },
    stopPropagation() { this._stopped = true; },
  }, props || {});
}

// ── build ─────────────────────────────────────────────────────────────
function build(node) {
  if (typeof node === 'string') return new Text(node);
  const e = new Element(node.tag, node.attrs);
  if (node.tag === 'template') {
    e.content = new Element('fragment', {});
    node.children.forEach((c) => e.content.appendChild(build(c)));
  } else {
    node.children.forEach((c) => e.appendChild(build(c)));
  }
  return e;
}

const html = new Element('html', {});
const head = html.appendChild(new Element('head', {}));
const body = html.appendChild(new Element('body', {}));
doc = {
  documentElement: html, head, body, activeElement: body, hidden: false, listeners: {},
  _blur() { this.activeElement = this.body; },
  getElementById(id) { return html.querySelector('#' + id); },
  querySelector(s) { return html.querySelector(s); },
  querySelectorAll(s) { return html.querySelectorAll(s); },
  createElement(t) { return new Element(t, {}); },
  createTextNode(t) { return new Text(t); },
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
  removeEventListener() {},
  dispatchEvent(ev) {
    ev.target = ev.target || this;
    ev.currentTarget = this;
    (this.listeners[ev.type] || []).slice().forEach((fn) => fn.call(this, ev));
    return !ev.defaultPrevented;
  },
};
const tree = JSON.parse(fs.readFileSync(treePath, 'utf8'));
tree.forEach((n) => body.appendChild(build(n)));
const strip = body.appendChild(new Element('div', { 'class': 'info-panel-wrap', id: 'infoPanelWrap' }));

// ── the window: timers, frames, storage, fetch ────────────────────────
let clock = 0, seq = 0;
let timers = [];
const frames = [];
const store = {};
const fetched = [];
const payloads = JSON.parse(fs.readFileSync(payloadPath, 'utf8'));
let serve = (url) => {
  if (url.indexOf('seat=') !== -1) return payloads.seat;
  if (url.indexOf('part=tab') !== -1) return payloads.tab;
  return payloads.board;
};
function respond(body) {
  return Promise.resolve({
    status: 200, ok: true, redirected: false,
    headers: { get: () => 'application/json' },
    json: () => Promise.resolve(JSON.parse(JSON.stringify(body))),
  });
}
const media = { matches: false, addEventListener() {}, addListener() {} };
const win = {
  innerWidth: 1380, innerHeight: 900,
  matchMedia: (q) => ({ matches: q.indexOf('max-width: 768px') !== -1 ? media.matches : false,
                        addEventListener() {}, addListener() {} }),
  localStorage: {
    getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
  },
  getComputedStyle: (n) => ({
    display: 'block', visibility: 'visible', opacity: '1', bottom: '0px',
    getPropertyValue: (p) => (n && n.style ? n.style.getPropertyValue(p) : ''),
  }),
  setTimeout: (fn, ms) => { const id = ++seq; timers.push({ id, at: clock + (ms || 0), fn }); return id; },
  clearTimeout: (id) => { timers = timers.filter((t) => t.id !== id); },
  setInterval: (fn, ms) => { const id = ++seq; timers.push({ id, at: clock + ms, fn, every: ms }); return id; },
  clearInterval: (id) => { timers = timers.filter((t) => t.id !== id); },
  requestAnimationFrame: (fn) => { frames.push(fn); return frames.length; },
  cancelAnimationFrame: () => {},
  requestIdleCallback: (fn) => win.setTimeout(fn, 1),
  fetch: (url) => { fetched.push(url); return respond(serve(url)); },
  AbortController: class { constructor() { this.signal = {}; } abort() {} },
  CustomEvent: class { constructor(type, init) { Object.assign(this, makeEvent(type, init)); } },
  listeners: {},
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
  removeEventListener() {},
};
win.window = win;
win.document = doc;

const sandbox = {
  window: win, document: doc, navigator: {}, console,
  fetch: win.fetch, CustomEvent: win.CustomEvent, setTimeout: win.setTimeout,
  clearTimeout: win.clearTimeout, Promise,
};
vm.createContext(sandbox);

// ── the scenario's toolbox ────────────────────────────────────────────
async function settle() {
  for (let i = 0; i < 30; i++) {
    await new Promise((r) => setImmediate(r));
    while (frames.length) frames.shift()();
  }
}
async function advance(ms) {
  const end = clock + ms;
  for (;;) {
    timers.sort((a, b) => a.at - b.at);
    const t = timers[0];
    if (!t || t.at > end) break;
    clock = t.at;
    if (t.every) t.at += t.every; else timers.shift();
    t.fn();
    await settle();
  }
  clock = end;
  await settle();
}
const env = {
  win, doc, store, fetched, payloads, settle, advance, media,
  $: (id) => doc.getElementById(id),
  load() {
    vm.runInContext(fs.readFileSync(scriptPath, 'utf8'), sandbox, { filename: 'sv-horde.js' });
  },
  serve(fn) { serve = fn; },
  click(e, detail) { e.dispatchEvent(makeEvent('click', { detail: detail === undefined ? 1 : detail })); },
  key(e, key, extra) {
    const ev = makeEvent('keydown', Object.assign({ key }, extra || {}));
    e.dispatchEvent(ev);
    return ev;
  },
  pointer(e, type, y) {
    const ev = makeEvent(type, { pointerId: 1, clientY: y, button: 0 });
    e.dispatchEvent(ev);
    return ev;
  },
  fire(type, detail) { doc.dispatchEvent(new win.CustomEvent(type, { detail })); },
  resize() { (win.listeners.resize || []).forEach((fn) => fn(makeEvent('resize'))); },
  focusKey() {
    const a = doc.activeElement;
    return a === doc.body ? 'BODY' : (a.getAttribute('data-hd-focus') || a.id || a.localName);
  },
  strip,
};

(async () => {
  const scenario = new Function('env', 'return (async () => {' + fs.readFileSync(scenarioPath, 'utf8') + '})();');
  const out = await scenario(env);
  process.stdout.write(JSON.stringify(out === undefined ? null : out));
})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
