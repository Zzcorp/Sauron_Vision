// Renders Anduin.dc.html offline (as the canvas would show it: no script runs), at two instants.
const S = '/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad';
const { contextFor, launch } = require(S + '/magic/tools/shot2.js');
(async () => {
  const browser = await launch();
  const { ctx, blocked } = await contextFor(browser, { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: 'dark', javaScriptEnabled: false });
  const page = await ctx.newPage(); const errs = []; page.on('pageerror', e => errs.push(String(e)));
  await page.goto('file://' + S + '/anduin/Anduin.dc.html', { waitUntil: 'load' });
  await page.waitForTimeout(2300); await page.screenshot({ path: S + '/anduin/work/board_2s.png' });
  await page.waitForTimeout(2600); await page.screenshot({ path: S + '/anduin/shots/board_anduin_1440x900.png' });
  console.log(JSON.stringify({ errs, blocked }));
  await browser.close();
})().catch(e => { console.error('FAILED', e); process.exit(1); });
