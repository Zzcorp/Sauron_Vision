// Anduin mock: offline renders and checks (fonts from the local copies, every other request aborted).
//   node render.js check            1440x900 at rest: errors, text under 11 px, clipped lines, overlaps; work/check_*.png
//   node render.js shots            shots/anduin_1440x900.png, anduin_1920x1080.png, anduin_390.png (DPR 2)
//   node render.js moments          three stills of the scripted story (DPR 2)
//   node render.js extra            shots/anduin_40_positions_1440x900.png (the fold), shots/weather_calm_stressed_crisis.png (three levels, one still)
//   node render.js video            shots/anduin.webm (the 12.8 s story, 1440x900) and shots/anduin_real_cadence.webm (the same story, prices at today's real pace)
//   node render.js at <ms> [w h]    work/at_<ms>.png (DPR 1), the live story paused at that instant
const fs = require('fs');
const { execFileSync } = require('child_process');
const S = '/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad';
const { contextFor, launch } = require(S + '/magic/tools/shot2.js');
const A = S + '/anduin', MOCK = 'file://' + A + '/anduin_mock.html', SHOTS = A + '/shots', WORK = A + '/work';
const mode = process.argv[2] || 'check';

async function open(browser, vp, extra, query) {
  const { ctx, blocked } = await contextFor(browser, Object.assign({ viewport: vp, deviceScaleFactor: 1, colorScheme: 'dark' }, extra || {}));
  const page = await ctx.newPage();
  const errs = []; page.on('pageerror', e => errs.push(String(e))); page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await page.goto(MOCK + (query || ''), { waitUntil: 'load' });
  await page.waitForFunction(() => window.__anduin && document.querySelector('.basket'), null, { timeout: 15000 });
  return { ctx, page, errs, blocked };
}
const checks = page => page.evaluate(() => {
  const out = { under11: [], clipped: [], overlaps: [], wide: [], lowContrast: [] };
  const vis = el => { const cs = getComputedStyle(el); return cs.display !== 'none' && cs.visibility !== 'hidden' && el.getClientRects().length; };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const lum = c => { const m = c.match(/[\d.]+/g).map(Number); const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }; return [.2126 * f(m[0]) + .7152 * f(m[1]) + .0722 * f(m[2]), m[3] == null ? 1 : m[3]]; };
  const bgOf = el => { for (let e = el; e; e = e.parentElement) { const b = getComputedStyle(e).backgroundColor; const m = b.match(/[\d.]+/g).map(Number); if (m.length < 4 || m[3] > .95) return b; } return 'rgb(4,11,7)'; };
  while (walker.nextNode()) {
    const t = walker.currentNode; if (!t.textContent.trim()) continue; const el = t.parentElement;
    if (el.closest('script,style,title,.pop:not(.on),.tblp:not(.on),.fl:not(.on)') || !vis(el)) continue;
    const cs = getComputedStyle(el);
    if (parseFloat(cs.fontSize) < 11) out.under11.push(cs.fontSize + ' ' + t.textContent.trim().slice(0, 30));
    const L1 = lum(cs.color)[0], L2 = lum(bgOf(el))[0], cr = (Math.max(L1, L2) + .05) / (Math.min(L1, L2) + .05);
    if (cr < 4.5) out.lowContrast.push(cr.toFixed(2) + ' ' + cs.color + ' on ' + bgOf(el) + ' "' + t.textContent.trim().slice(0, 26) + '"');
  }
  document.querySelectorAll('.l1,.l2,.l3,.l4,.lv,.em,.x4,.org .ru,.org .la,.pnl,.bt,.bs,.bv,.wbandh,.apn,.more,.fw,.un,.ln,.pv,.ps,.wx1,.hzt,.hztouch,.cmeta,.ctitle,.legend,.top,.foot,.band,.chead,.fl.on').forEach(el => {
    if (!vis(el)) return;
    if (el.scrollWidth > el.clientWidth + 1) out.clipped.push((el.className || el.tagName) + ' ' + el.scrollWidth + '>' + el.clientWidth + ' "' + el.textContent.trim().slice(0, 34) + '"');
  });
  document.querySelectorAll('.blk').forEach(el => { if (el.scrollHeight > el.clientHeight + 1) out.clipped.push('blk-height ' + el.dataset.id + ' ' + el.scrollHeight + '>' + el.clientHeight); });
  document.querySelectorAll('.wx2,.bhead,.ahead,.pool,.cbody').forEach(el => { if (vis(el) && el.scrollHeight > el.clientHeight + 1) out.clipped.push('tall ' + (el.id || el.className) + ' ' + el.scrollHeight + '>' + el.clientHeight); });
  document.querySelectorAll('.basket').forEach(el => { const r = el.getBoundingClientRect(), p = document.getElementById('baskets').getBoundingClientRect(); if (r.bottom > p.bottom + 1) out.clipped.push('basket-tall ' + el.dataset.k + ' ' + Math.round(r.bottom - p.bottom)); if (r.right > p.right + 1) out.wide.push('basket ' + el.dataset.k + ' ' + Math.round(r.right - p.right)); });
  const B = Array.from(document.querySelectorAll('.blk,.fl.on')).map(e => [e.dataset.id || e.id, e.getBoundingClientRect()]);
  for (let i = 0; i < B.length; i++) for (let j = i + 1; j < B.length; j++) { const a = B[i][1], b = B[j][1]; if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) out.overlaps.push(B[i][0] + ' x ' + B[j][0]); }
  out.scrollW = document.documentElement.scrollWidth; out.vw = innerWidth;
  { const m = window.__anduin.state().metrics; out.metrics = { C: m.C, bw: m.bw, scale: m.scale, shown: m.shown, folded: m.folded, cols: m.cols, H: m.H, W: m.W }; } out.perf = window.__anduin.perf();
  out.heights = Array.from(document.querySelectorAll('.blk')).map(e => e.dataset.id + ':' + e.offsetHeight + (e.className.match(/t\d/g) || ['t0']).pop()).join(' ');
  return out;
});
const pauseAt = async (page, ms) => { await page.waitForFunction(t => window.__anduin.perf().paused && window.__anduin.T() >= t, ms, { timeout: 30000 }); await page.waitForTimeout(120); };

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true }); fs.mkdirSync(WORK, { recursive: true });
  const browser = await launch(); const report = {};
  if (mode === 'check') {
    for (const [w, h, q] of [[1440, 900, '?demo=0'], [1920, 1080, '?demo=0'], [1440, 900, '?freeze=12600'], [1280, 800, '?demo=0']]) {
      const { ctx, page, errs, blocked } = await open(browser, { width: w, height: h }, null, q);
      await page.waitForTimeout(1600);
      const name = w + 'x' + h + q.replace(/\W+/g, '_');
      await page.screenshot({ path: WORK + '/check_' + name + '.png' });
      const r = await checks(page); r.errors = errs; r.blocked = blocked; report[name] = r; await ctx.close();
    }
  }
  if (mode === 'at') {
    const ms = +process.argv[3], w = +(process.argv[4] || 1440), h = +(process.argv[5] || 900);
    const { ctx, page, errs } = await open(browser, { width: w, height: h }, null, '?stop=' + ms);
    await pauseAt(page, ms); await page.screenshot({ path: WORK + '/at_' + ms + '.png' });
    report.at = await checks(page); report.at.errors = errs; await ctx.close();
  }
  if (mode === 'shots') {
    for (const [w, h, name] of [[1440, 900, 'anduin_1440x900'], [1920, 1080, 'anduin_1920x1080']]) {
      const { ctx, page, errs } = await open(browser, { width: w, height: h }, { deviceScaleFactor: 2 }, '?demo=0&stop=2200');
      await pauseAt(page, 2200); await page.screenshot({ path: SHOTS + '/' + name + '.png' });
      report[name] = await checks(page); report[name].errors = errs; await ctx.close();
    }
    const { ctx, page, errs } = await open(browser, { width: 390, height: 844 }, { deviceScaleFactor: 2, isMobile: true, hasTouch: true }, '');
    await page.waitForTimeout(600); await page.screenshot({ path: SHOTS + '/anduin_390.png', fullPage: true });
    report.phone = await checks(page); report.phone.errors = errs;
    report.phone.canvasShown = await page.evaluate(() => getComputedStyle(document.getElementById('flow')).display);
    report.phone.frames = await page.evaluate(() => window.__anduin.perf().frames);
    await ctx.close();
  }
  if (mode === 'extra') {
    { const { ctx, page, errs } = await open(browser, { width: 1440, height: 900 }, { deviceScaleFactor: 2 }, '?demo=0&n=40&stop=2600');
      await pauseAt(page, 2600); await page.screenshot({ path: SHOTS + '/anduin_40_positions_1440x900.png' });
      report.forty = await checks(page); report.forty.errors = errs;
      report.forty.book = await page.evaluate(() => { const S2 = window.__anduin.state(); const n = w => S2.pos.filter(p => p.world === w).length; return { rows: S2.pos.length, real: n('real'), demo: n('demo'), paper: n('paper'), none: n('none'), blocks: document.querySelectorAll('.blk:not(.mic)').length, rowsDrawn: document.querySelectorAll('.blk.mic').length, realDrawn: document.querySelectorAll('.blk.real').length, folded: S2.metrics.folded }; });
      await ctx.close(); }
    const parts = [];
    for (const lv of ['calm', 'stressed', 'crisis']) {
      const { ctx, page, errs } = await open(browser, { width: 1440, height: 900 }, { deviceScaleFactor: 2 }, '?demo=0&wx=' + lv + '&stop=1500');
      await pauseAt(page, 1500); const f = WORK + '/wx_' + lv + '.png'; await page.screenshot({ path: f, clip: { x: 232, y: 76, width: 1168, height: 372 } }); parts.push(f);
      report['wx_' + lv] = await checks(page); report['wx_' + lv].errors = errs;
      report['wx_' + lv].wave = await page.evaluate(() => { const A = window.__anduin, G = A.geom(); let a = 0; for (let x = 20; x < G.w - 20; x += 1) a = Math.max(a, Math.abs(A.rip(x))); return +a.toFixed(2); });
      await ctx.close();
    }
    execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', parts[0], '-i', parts[1], '-i', parts[2], '-filter_complex', 'vstack=inputs=3', SHOTS + '/weather_calm_stressed_crisis.png']);
  }
  if (mode === 'moments') {
    for (const [ms, name] of [[3250, 'moment_1_signal_refused'], [5000, 'moment_2_taken_money_block_forming'], [11150, 'moment_3_stressed_frost_dry_close']]) {
      const { ctx, page, errs } = await open(browser, { width: 1440, height: 900 }, { deviceScaleFactor: 2 }, '?stop=' + ms);
      await pauseAt(page, ms); await page.screenshot({ path: SHOTS + '/' + name + '.png' });
      report[name] = await checks(page); report[name].errors = errs; await ctx.close();
    }
  }
  if (mode === 'video') for (const [q, name] of [['', 'anduin'], ['&cadence=real', 'anduin_real_cadence']]) {
    const vdir = WORK + '/video_' + name + '_' + Date.now(); fs.mkdirSync(vdir, { recursive: true });
    const { ctx, blocked } = await contextFor(browser, { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, colorScheme: 'dark', recordVideo: { dir: vdir, size: { width: 1440, height: 900 } } });
    const page = await ctx.newPage(); const t0 = Date.now();
    await page.goto(MOCK + '?hold=1&loop=0' + q, { waitUntil: 'load' });
    await page.waitForFunction(() => window.__anduin && document.querySelector('.basket'), null, { timeout: 15000 });
    await page.waitForTimeout(700);
    const lead = (Date.now() - t0) / 1000;
    await page.evaluate(() => window.__anduin.go());
    await page.waitForFunction(() => window.__anduin.T() >= 13000, null, { timeout: 40000 });
    const frames = await page.evaluate(() => window.__anduin.perf());
    await page.close(); const v = await page.video().path(); await ctx.close();
    const out = SHOTS + '/' + name + '.webm';
    execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-ss', lead.toFixed(2), '-i', v, '-t', '12.8', '-c:v', 'libvpx-vp9', '-b:v', '2600k', '-deadline', 'good', '-cpu-used', '4', '-row-mt', '1', '-an', out]);
    report[name] = { src: v, lead, out, perf: frames, probe: JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration,size:stream=width,height,avg_frame_rate', '-of', 'json', out]).toString()), blocked };
  }
  await browser.close();
  fs.writeFileSync(WORK + '/report_' + mode + '.json', JSON.stringify(report, null, 1));
  console.log(JSON.stringify(report, null, 1).slice(0, 6000));
})().catch(e => { console.error('FAILED', e); process.exit(1); });
