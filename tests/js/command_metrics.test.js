// The Operations Center's own metrics poll, under node (OC0, 2026-11-07).
//
// Usage: node tests/js/command_metrics.test.js templates/dashboard/command.html
//
// Reads the poll's <script> out of command.html exactly as the page ships
// it, runs it in a fresh sandbox per case with the browser stubbed (a fake
// clock, a fake fetch, a fake document) and checks the contract the spec
// sets for it (opscenter spec, OC0, "The page's own poll"):
//   - it sends X-Requested-With, so the idle lock never counts it as a
//     human and answers it 423 when locked (core/idle_lock._wants_json);
//   - it stops on a 423 and on a redirected answer;
//   - it schedules nothing while the tab is hidden;
//   - it resumes on sv:pin-unlocked, and when the tab is visible again;
//   - a fill on the shared sv:eye-event still refreshes it.
// Prints {"passed": [...], "failed": [...]} and exits 1 when a case fails.
// tests/test_command_truth.py runs it. No network, no browser.
'use strict';
const fs = require('fs');
const vm = require('vm');

const page = fs.readFileSync(process.argv[2], 'utf8');
const URL = '/command/tab/metrics/';
const FALLBACK_MS = 45000;

function pollSource() {
  const blocks = [];
  const re = /<script>([\s\S]*?)<\/script>/g;
  let m;
  while ((m = re.exec(page)) !== null) blocks.push(m[1]);
  const src = blocks.find((b) => b.indexOf('METRICS_URL') !== -1);
  if (!src) throw new Error('no script on the page reads METRICS_URL');
  return src
    .replace(/\{%\s*url\s+'command_tab_metrics'\s*%\}/g, URL)
    .replace(/\{%[\s\S]*?%\}/g, '')
    .replace(/\{\{[\s\S]*?\}\}/g, '');
}

function boot() {
  const T = { now: 0, seq: 0, timers: [] };
  const L = { fetches: [], listeners: {}, ajax: 0 };
  let answer = () => respond(200, { tabs: {}, hero: {} });

  function respond(status, body, opt) {
    opt = opt || {};
    const json = typeof body !== 'string';
    return Promise.resolve({
      status, ok: status >= 200 && status < 300,
      redirected: !!opt.redirected, url: opt.url || URL,
      headers: { get: (k) => (/content-type/i.test(k)
        ? (json ? 'application/json' : 'text/html; charset=utf-8') : null) },
      json: () => (json ? Promise.resolve(body) : Promise.reject(new SyntaxError('not JSON'))),
      text: () => Promise.resolve(json ? JSON.stringify(body) : body),
    });
  }
  function addTimer(fn, ms, every) {
    const id = ++T.seq;
    T.timers.push({ id, at: T.now + Math.max(0, ms || 0), fn, every: every ? ms : 0, ms: ms || 0 });
    return id;
  }
  function clearTimer(id) { T.timers = T.timers.filter((t) => t.id !== id); }
  function el(id, attrs) {
    attrs = attrs || {};
    return {
      id, attrs, style: {}, textContent: '', title: '', dataset: {},
      classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
      getAttribute(k) { return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null; },
      setAttribute(k, v) { attrs[k] = String(v); },
      addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
      getBoundingClientRect() { return { top: 0 }; }, click() {},
    };
  }
  const nodes = {
    ocTabs: el('ocTabs', { 'data-oc-metrics-url': URL }),
    ocClock: el('ocClock'), ocWsStatus: el('ocWsStatus'),
  };
  const document = {
    hidden: false,
    get visibilityState() { return this.hidden ? 'hidden' : 'visible'; },
    body: Object.assign(el('body'), { addEventListener() {} }),
    getElementById: (id) => nodes[id] || null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener(type, fn) { (L.listeners[type] = L.listeners[type] || []).push(fn); },
    removeEventListener() {},
    dispatchEvent(ev) { (L.listeners[ev.type] || []).slice().forEach((fn) => fn(ev)); return true; },
  };
  const sandbox = {
    document, console,
    fetch: (url, init) => { L.fetches.push({ url: String(url), init: init || {} }); return answer(String(url), init); },
    setTimeout: (fn, ms) => addTimer(fn, ms, false),
    clearTimeout: clearTimer,
    setInterval: (fn, ms) => addTimer(fn, ms, true),
    clearInterval: clearTimer,
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    MutationObserver: function () { this.observe = function () {}; },
    CustomEvent: function (type, init) { this.type = type; this.detail = (init || {}).detail; },
    Event: function (type) { this.type = type; },
    htmx: { ajax: () => { L.ajax += 1; } },
    scrollBy() {},
    Promise, JSON, Math, String, Array, Object, Error, SyntaxError, RegExp, Date, Number,
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(pollSource(), sandbox, { filename: 'command.html <script>' });

  async function flush() { for (let i = 0; i < 20; i++) await Promise.resolve(); }
  async function advance(ms) {
    const end = T.now + ms;
    for (;;) {
      const due = T.timers.filter((t) => t.at <= end).sort((a, b) => a.at - b.at || a.id - b.id)[0];
      if (!due) break;
      T.now = due.at;
      if (due.every) due.at += due.every; else clearTimer(due.id);
      due.fn();
      await flush();
    }
    T.now = end;
    await flush();
  }
  function polls() { return L.fetches.filter((f) => f.url.indexOf(URL) === 0); }
  function event(type, detail) { document.dispatchEvent(new sandbox.CustomEvent(type, { detail })); }
  function hide(on) { document.hidden = on; event('visibilitychange'); }
  function pendingPolls() { return T.timers.filter((t) => t.ms >= FALLBACK_MS).length; }
  return {
    L, T, advance, polls, event, hide, pendingPolls, flush,
    answerWith(fn) { answer = fn; }, respond,
  };
}

const cases = {
  async sends_x_requested_with() {
    const b = boot();
    await b.advance(FALLBACK_MS + 1000);
    const p = b.polls();
    if (!p.length) throw new Error('no poll in ' + (FALLBACK_MS + 1000) + ' ms');
    const h = p[0].init.headers || {};
    if (h['X-Requested-With'] !== 'XMLHttpRequest') throw new Error('headers ' + JSON.stringify(h));
  },
  async stops_on_423() {
    const b = boot();
    b.answerWith(() => b.respond(423, { pin_locked: true }));
    await b.advance(FALLBACK_MS + 1000);
    const n = b.polls().length;
    if (n !== 1) throw new Error('first window: ' + n + ' polls');
    await b.advance(FALLBACK_MS * 6);
    if (b.polls().length !== 1) throw new Error('kept polling after 423: ' + b.polls().length);
    if (b.pendingPolls()) throw new Error('a poll is still scheduled after 423');
  },
  async stops_on_redirect() {
    const b = boot();
    b.answerWith(() => b.respond(200, '<html>locked</html>', { redirected: true, url: '/locked/?next=/command/' }));
    await b.advance(FALLBACK_MS + 1000);
    await b.advance(FALLBACK_MS * 6);
    if (b.polls().length !== 1) throw new Error('kept polling after a redirect: ' + b.polls().length);
  },
  async nothing_while_hidden() {
    const b = boot();
    b.hide(true);
    await b.flush();
    if (b.pendingPolls()) throw new Error(b.pendingPolls() + ' poll(s) scheduled while hidden');
    await b.advance(FALLBACK_MS * 5);
    if (b.polls().length) throw new Error(b.polls().length + ' poll(s) while hidden');
    b.event('sv:eye-event', { kind: 'fill_open' });
    await b.advance(5000);
    if (b.polls().length) throw new Error('an eye event polled while hidden');
  },
  async resumes_when_visible() {
    const b = boot();
    b.hide(true);
    await b.advance(FALLBACK_MS * 2);
    b.hide(false);
    await b.advance(FALLBACK_MS + 1000);
    if (!b.polls().length) throw new Error('no poll after the tab came back');
  },
  async resumes_on_pin_unlocked() {
    const b = boot();
    b.answerWith(() => b.respond(423, { pin_locked: true }));
    await b.advance(FALLBACK_MS + 1000);
    await b.advance(FALLBACK_MS * 3);
    const before = b.polls().length;
    b.answerWith(() => b.respond(200, { tabs: {}, hero: {} }));
    b.event('sv:pin-unlocked');
    await b.advance(2000);
    if (b.polls().length <= before) throw new Error('no poll after sv:pin-unlocked');
    await b.advance(FALLBACK_MS + 1000);
    if (b.polls().length <= before + 1) throw new Error('the timer did not resume after the unlock');
  },
  async eye_event_refetches() {
    const b = boot();
    b.event('sv:eye-event', { kind: 'fill_close' });
    await b.advance(1000);
    if (b.polls().length !== 1) throw new Error(b.polls().length + ' polls 1 s after a fill');
  },
};

(async () => {
  const out = { passed: [], failed: [] };
  for (const [name, fn] of Object.entries(cases)) {
    try { await fn(); out.passed.push(name); }
    catch (e) { out.failed.push(name + ': ' + (e && e.message ? e.message : String(e))); }
  }
  process.stdout.write(JSON.stringify(out));
  process.exit(out.failed.length ? 1 : 0);
})().catch((e) => { console.error(String(e && e.stack || e)); process.exit(2); });
