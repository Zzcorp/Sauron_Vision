// Clicks the mock's switches and opens its detail and its table; writes work/sw_*.png with the checks.
const fs = require('fs');
const S = '/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad';
const { contextFor, launch } = require(S + '/magic/tools/shot2.js');
const A = S + '/anduin';
(async () => {
  const browser = await launch(); const out = {};
  const { ctx } = await contextFor(browser, { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, colorScheme: 'dark' });
  const page = await ctx.newPage(); const errs = []; page.on('pageerror', e => errs.push(String(e)));
  await page.goto('file://' + A + '/anduin_mock.html?demo=0'); await page.waitForFunction(() => window.__anduin && document.querySelector('.basket')); await page.waitForTimeout(700);
  const chk = () => page.evaluate(() => { const o = { clipped: [], tall: [], wide: [] }; const p = document.getElementById('baskets').getBoundingClientRect();
    document.querySelectorAll('.l1,.l2,.l3,.l4,.lv,.em,.x4,.org .ru,.org .la,.pnl,.bt,.bs,.bv,.wbandh,.apn,.more,.fw,.un').forEach(el => { if (el.getClientRects().length && el.scrollWidth > el.clientWidth + 1) o.clipped.push(el.className + ' "' + el.textContent.trim().slice(0, 28) + '"'); });
    document.querySelectorAll('.blk').forEach(el => { if (el.scrollHeight > el.clientHeight + 1) o.clipped.push('blk-h ' + el.dataset.id); });
    document.querySelectorAll('.basket').forEach(el => { const r = el.getBoundingClientRect(); if (r.bottom > p.bottom + 1) o.tall.push(el.dataset.k + ' +' + Math.round(r.bottom - p.bottom)); if (r.right > p.right + 1) o.wide.push(el.dataset.k + ' +' + Math.round(r.right - p.right)); });
    document.querySelectorAll('[data-box]').forEach(el => { const r = el.getBoundingClientRect(); if (r.bottom > p.bottom + 1) o.tall.push('box +' + Math.round(r.bottom - p.bottom)); if (r.right > p.right + 1) o.wide.push('box +' + Math.round(r.right - p.right)); });
    const m = window.__anduin.state().metrics; o.metrics = { C: m.C, bw: m.bw, scale: m.scale, shown: m.shown, folded: m.folded, cols: m.cols }; return o; });
  for (const [sel, name] of [['[data-s="risk"]', 'family_risk'], ['[data-g="world"]', 'world_risk'], ['[data-s="exposure"]', 'world_exposure'], ['[data-g="lane"]', 'lane_exposure'], ['[data-g="theme"]', 'theme_exposure'], ['[data-g="family"]', 'family_exposure']]) {
    await page.click(sel); await page.waitForTimeout(500); await page.screenshot({ path: A + '/work/sw_' + name + '.png' }); out[name] = await chk();
  }
  await page.hover('.blk[data-id="eurusd"]'); await page.waitForTimeout(250); await page.screenshot({ path: A + '/work/sw_popover.png' });
  out.popover = await page.evaluate(() => { const p = document.getElementById('pop'); const r = p.getBoundingClientRect(); return { on: p.classList.contains('on'), w: Math.round(r.width), h: Math.round(r.height), under11: Array.from(p.querySelectorAll('*')).filter(e => parseFloat(getComputedStyle(e).fontSize) < 11).length }; });
  await page.mouse.move(5, 5); await page.click('#tbtn'); await page.waitForTimeout(300); await page.screenshot({ path: A + '/work/sw_table.png' });
  out.table = await page.evaluate(() => ({ rows: document.querySelectorAll('#tblp tr').length, overflowX: document.getElementById('tblp').scrollWidth > document.getElementById('tblp').clientWidth + 1 }));
  out.errs = errs; await browser.close(); console.log(JSON.stringify(out, null, 0));
})().catch(e => { console.error('FAILED', e); process.exit(1); });
