// Anduin mock: what the motion costs, and that it stops (offline; headless Chrome, software raster).
//   cpu cores   Chrome's whole process tree (browser, renderer, GPU/viz): utime + stime from /proc per wall second
//   main ms/s   the renderer's main-thread task time (CDP Performance.getMetrics TaskDuration)
//   raf/s, draws/s, ms per draw   the page's own counters (window.__anduin.perf())
const fs = require('fs'), os = require('os');
const S = '/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad';
const { contextFor, launch } = require(S + '/magic/tools/shot2.js');
const A = S + '/anduin', MOCK = 'file://' + A + '/anduin_mock.html';
const CLK = 100;
function treeTicks(root) {
  const kids = {}, ticks = {};
  for (const p of fs.readdirSync('/proc')) {
    if (!/^\d+$/.test(p)) continue;
    try { const st = fs.readFileSync('/proc/' + p + '/stat', 'utf8'); const rest = st.slice(st.lastIndexOf(')') + 2).split(' '); (kids[+rest[1]] = kids[+rest[1]] || []).push(+p); ticks[+p] = (+rest[11]) + (+rest[12]); } catch (e) {}
  }
  let sum = 0; const stack = (kids[root] || []).slice();
  while (stack.length) { const p = stack.pop(); sum += ticks[p] || 0; (kids[p] || []).forEach(k => stack.push(k)); }
  return sum;
}
async function run(browser, name, url, secs, opts) {
  opts = opts || {};
  const { ctx } = await contextFor(browser, Object.assign({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, colorScheme: 'dark' }, opts.ctx || {}));
  const page = await ctx.newPage(); const cdp = await ctx.newCDPSession(page);
  await cdp.send('Performance.enable');
  await page.goto(url, { waitUntil: 'load' });
  if (!opts.blank) await page.waitForFunction(() => window.__anduin && document.querySelector('.basket'), null, { timeout: 15000 });
  if (opts.throttle) await cdp.send('Emulation.setCPUThrottlingRate', { rate: opts.throttle });
  await page.waitForTimeout(1500);
  const g = async () => { const m = await cdp.send('Performance.getMetrics'); const o = {}; m.metrics.forEach(x => { o[x.name] = x.value; }); return o; };
  const pf = () => opts.blank ? Promise.resolve({ frames: 0, draws: 0, ticks: 0, stepMs: 0, drawMs: 0, maxActors: 0 }) : page.evaluate(() => window.__anduin.perf());
  const wins = [];
  for (let i = 0; i < 2; i++) {
    const m0 = await g(), p0 = await pf(), k0 = treeTicks(process.pid), w0 = Date.now();
    await page.waitForTimeout(secs * 1000);
    const m1 = await g(), p1 = await pf(), k1 = treeTicks(process.pid), dt = (Date.now() - w0) / 1000;
    const draws = p1.draws - p0.draws;
    wins.push({ cores: +((k1 - k0) / CLK / dt).toFixed(3), mainMsPerS: +((m1.TaskDuration - m0.TaskDuration) * 1000 / dt).toFixed(0), scriptMsPerS: +((m1.ScriptDuration - m0.ScriptDuration) * 1000 / dt).toFixed(0),
      rafPerS: +((p1.frames - p0.frames) / dt).toFixed(1), ticksPerS: +(((p1.ticks || 0) - (p0.ticks || 0)) / dt).toFixed(1), drawsPerS: +(draws / dt).toFixed(1), msPerDraw: draws ? +(((p1.stepMs - p0.stepMs) + (p1.drawMs - p0.drawMs)) / draws).toFixed(3) : 0, maxActors: p1.maxActors });
  }
  await ctx.close();
  const avg = k => +(wins.reduce((a, w) => a + w[k], 0) / wins.length).toFixed(3);
  return { name, secs, cores: avg('cores'), mainMsPerS: avg('mainMsPerS'), scriptMsPerS: avg('scriptMsPerS'), rafPerS: avg('rafPerS'), ticksPerS: avg('ticksPerS'), drawsPerS: avg('drawsPerS'), msPerDraw: avg('msPerDraw'), maxActors: Math.max.apply(null, wins.map(w => w.maxActors)), windows: wins };
}
async function pauses(browser) {
  const out = {};
  const count = async (page, ms) => { const a = await page.evaluate(() => window.__anduin.perf().draws); await page.waitForTimeout(ms); return (await page.evaluate(() => window.__anduin.perf().draws)) - a; };
  {
    const { ctx } = await contextFor(browser, { viewport: { width: 1440, height: 900 }, colorScheme: 'dark' }); const page = await ctx.newPage();
    await page.goto(MOCK + '?demo=0'); await page.waitForFunction(() => window.__anduin && document.querySelector('.basket')); await page.waitForTimeout(800);
    out.running_2s = await count(page, 2000);
    await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange')); });
    out.hidden_2s = await count(page, 2000);
    await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => false }); document.dispatchEvent(new Event('visibilitychange')); });
    out.shown_again_2s = await count(page, 2000);
    await page.evaluate(() => document.dispatchEvent(new Event('sv:pin-locked')));
    out.locked_2s = await count(page, 2000);
    out.locked_running_css = await page.evaluate(() => document.getAnimations().filter(a => a.playState === 'running').length);
    await page.evaluate(() => document.dispatchEvent(new Event('sv:pin-unlocked')));
    out.unlocked_2s = await count(page, 2000);
    await page.evaluate(() => window.__anduin.table(true));
    out.table_open_2s = await count(page, 2000);
    await ctx.close();
  }
  {
    const { ctx } = await contextFor(browser, { viewport: { width: 1440, height: 900 }, colorScheme: 'dark', reducedMotion: 'reduce' }); const page = await ctx.newPage();
    await page.goto(MOCK); await page.waitForFunction(() => window.__anduin && document.querySelector('.basket')); await page.waitForTimeout(2500);
    const p = await page.evaluate(() => window.__anduin.perf());
    out.reduced_motion = { rafCalls: p.frames, draws: p.draws, runningAnimations: await page.evaluate(() => document.getAnimations().filter(a => a.playState === 'running').length), bedDrawn: await page.evaluate(() => { const c = document.getElementById('bed'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 8) n++; return n; }) };
    await page.screenshot({ path: A + '/work/reduced_motion.png' });
    await ctx.close();
  }
  return out;
}
(async () => {
  const results = { machine: { cores: os.cpus().length, model: os.cpus()[0].model, load_before: os.loadavg().map(v => +v.toFixed(2)) }, viewport: '1440x900, DPR 1, headless Chrome, no graphics card (software raster)', runs: [] };
  const browser = await launch();
  const blank = 'data:text/html,<html><body style="margin:0;background:%23040B07"></body></html>';
  results.runs.push(await run(browser, 'a flat page (the floor)', blank, 8, { blank: true }));
  results.runs.push(await run(browser, 'the page with the river stopped (?motion=0): the frame, the cards, the Eye breath, one heartbeat, the armed dot', MOCK + '?motion=0', 8));
  results.runs.push(await run(browser, 'idle: every feed quiet (?demo=0&quiet=1): must cost what the still page costs, with no frame asked for', MOCK + '?demo=0&quiet=1', 8));
  results.runs.push(await run(browser, 'at rest at the real pace of today (?demo=0&cadence=real): a 30 s quote, a 10 s poll', MOCK + '?demo=0&cadence=real', 12));
  results.runs.push(await run(browser, 'the page at rest at the mock\'s condensed pace: a price about every 3 s per live instrument', MOCK + '?demo=0', 8));
  results.runs.push(await run(browser, 'the scripted story, looping (signals, a fill, money streams, a close, the weather turning)', MOCK, 14.6));
  results.runs.push(await run(browser, 'CPU slowed 4x: the page at rest', MOCK + '?demo=0', 8, { throttle: 4 }));
  results.runs.push(await run(browser, 'CPU slowed 4x: the scripted story', MOCK, 14.6, { throttle: 4 }));
  results.runs.push(await run(browser, '1920x1080: the page at rest', MOCK + '?demo=0', 8, { ctx: { viewport: { width: 1920, height: 1080 } } }));
  results.pauses = await pauses(browser);
  await browser.close();
  results.machine.load_after = os.loadavg().map(v => +v.toFixed(2));
  fs.writeFileSync(A + '/work/cost.json', JSON.stringify(results, null, 1));
  results.runs.forEach(r => console.log(JSON.stringify({ name: r.name.slice(0, 60), cores: r.cores, main: r.mainMsPerS, script: r.scriptMsPerS, raf: r.rafPerS, ticks: r.ticksPerS, draws: r.drawsPerS, msPerDraw: r.msPerDraw, maxActors: r.maxActors })));
  console.log(JSON.stringify(results.pauses), JSON.stringify(results.machine));
})().catch(e => { console.error('FAILED', e); process.exit(1); });
