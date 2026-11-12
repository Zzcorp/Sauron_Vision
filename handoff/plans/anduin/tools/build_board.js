// Anduin.dc.html: the preview-canvas board, built from the mock's own page at rest.
// The mock is opened at 1440x900 with its river stopped; its markup (with the sizes its layout gave each
// block) and its stylesheet are copied; the two canvases are replaced by one still SVG (the river's three
// lines, the gates, the feeders, the money lane: the same geometry). What moves is CSS only: three price
// motes and one refused signal ride CSS offset-path in steps of a thirtieth of a second, and one rule under
// prefers-reduced-motion hides them and leaves the still bed. No SMIL. No script but the closing text/x-dc block.
const fs = require('fs');
const S = '/tmp/claude-0/-home-user-Sauron-Vision/1cce9008-9670-5676-a74f-728d1bb3620c/scratchpad';
const { contextFor, launch } = require(S + '/magic/tools/shot2.js');
const A = S + '/anduin';
(async () => {
  const browser = await launch();
  const { ctx } = await contextFor(browser, { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, colorScheme: 'dark' });
  const page = await ctx.newPage();
  await page.goto('file://' + A + '/anduin_mock.html?demo=0&motion=0', { waitUntil: 'load' });
  await page.waitForFunction(() => window.__anduin && document.querySelector('.basket'));
  await page.waitForTimeout(500);
  const got = await page.evaluate(() => {
    const A = window.__anduin, B = A.bedSVG(), f = v => (Math.round(v * 10) / 10).toString();
    let svg = '<path d="' + B.lane + '" stroke="#ACC4B6" stroke-opacity=".26" stroke-dasharray="2 5" fill="none"/>' +
      '<path d="' + B.lines[0] + '" stroke="#00E868" stroke-opacity=".10" stroke-width="9" stroke-linejoin="round" fill="none"/>' +
      '<path d="' + B.lines[0] + '" stroke="#ACC4B6" stroke-opacity=".6" stroke-linejoin="round" fill="none"/>' +
      '<path d="' + B.lines[1] + '" stroke="#ACC4B6" stroke-opacity=".3" stroke-linejoin="round" fill="none"/>' +
      '<path d="' + B.lines[2] + '" stroke="#ACC4B6" stroke-opacity=".3" stroke-linejoin="round" fill="none"/>' +
      '<path d="M' + f(B.w - 1) + ' ' + f(B.riverY) + 'L' + f(B.w - 8) + ' ' + f(B.riverY - 4) + 'L' + f(B.w - 8) + ' ' + f(B.riverY + 4) + 'Z" fill="#ACC4B6" fill-opacity=".8"/><circle cx="3.5" cy="' + f(B.riverY) + '" r="2.5" fill="#ACC4B6" fill-opacity=".8"/>' +
      '<path d="' + B.gates + '" stroke="#ACC4B6" stroke-opacity=".6" fill="none"/>';
    B.feeders.forEach(fd => { svg += '<path d="' + fd.d + '" fill="none" ' + (fd.st === 'live' ? 'stroke="#00E868" stroke-opacity=".34"' : 'stroke="#ACC4B6" stroke-opacity=".34"') + '/>'; });
    const overlay = '<svg class="adflow" width="' + f(B.w) + '" height="' + f(B.h) + '" viewBox="0 0 ' + f(B.w) + ' ' + f(B.h) + '" aria-hidden="true">' + svg + '</svg>';
    // three price motes: the three live rows; each enters at its basket's gate and is taken in within 1.2 s
    let css = '', els = ''; const P = 3.2;
    B.motes.filter(m => m.live).slice(0, 3).forEach((m, i) => {
      const travel = m.L / Math.max(96, m.L / 1.2), k = (100 * travel / P).toFixed(2), begin = (i * 1.05).toFixed(2), steps = Math.max(2, Math.round(travel * 30));
      css += '@keyframes admv' + i + '{0%{offset-distance:0%;animation-timing-function:steps(' + steps + ',end)}' + k + '%{offset-distance:100%}100%{offset-distance:100%}}\n' +
        '@keyframes admo' + i + '{0%{opacity:1}' + k + '%{opacity:0}100%{opacity:0}}\n';
      els += '<i class="admote" style="offset-path:path(\'' + m.d + '\');animation:admv' + i + ' ' + P + 's linear ' + begin + 's infinite both,admo' + i + ' ' + P + 's step-end ' + begin + 's infinite both"></i>';
      const e = document.querySelector('.blk[data-id="' + m.id + '"] .pe'); if (e) e.setAttribute('style', 'animation:adpe ' + P + 's step-end ' + (i * 1.05 + travel).toFixed(2) + 's infinite');
    });
    // one refused signal, replayed every 12 s: the token rides the river to its basket's gate, rises and is gone; its words stay a while
    const gate = B.gate('commodity'), tokT = gate / 330, T = 12, pc = v => (v / T * 100).toFixed(2) + '%', d1 = (100 * gate / (gate + 34)).toFixed(2);
    css += '@keyframes adtkv{0%,' + pc(1) + '{offset-distance:0%;animation-timing-function:steps(' + Math.round(tokT * 30) + ',end)}' + pc(1 + tokT) + '{offset-distance:' + d1 + '%;animation-timing-function:steps(27,end)}' + pc(1.9 + tokT) + ',100%{offset-distance:100%}}\n' +
      '@keyframes adtko{0%{opacity:0}' + pc(1) + '{opacity:1}' + pc(1 + tokT) + '{opacity:1;animation-timing-function:steps(9,end)}' + pc(1.9 + tokT) + ',100%{opacity:0}}\n' +
      '.fl.adchip{opacity:0;animation:adchip ' + T + 's step-end infinite}\n' +
      '@keyframes adchip{0%{opacity:0}' + pc(1 + tokT) + '{opacity:1}' + pc(5.6 + tokT) + '{opacity:0}100%{opacity:0}}\n' +
      '.fl.adtok{left:0;opacity:0;animation:adtokx ' + T + 's linear infinite,adtoko ' + T + 's step-end infinite}\n' +
      '@keyframes adtokx{0%,' + pc(1) + '{transform:translateX(var(--x0));animation-timing-function:steps(' + Math.round(tokT * 30) + ',end)}' + pc(1 + tokT) + ',100%{transform:translateX(var(--x1))}}\n' +
      '@keyframes adtoko{0%{opacity:0}' + pc(1) + '{opacity:1}' + pc(1 + tokT) + '{opacity:0}100%{opacity:0}}\n';
    els += '<i class="adtokm" style="offset-path:path(\'M0 ' + f(B.riverY) + 'H' + f(gate - 6) + 'V' + f(B.riverY - 34) + '\');animation:adtkv ' + T + 's linear infinite both,adtko ' + T + 's step-end infinite both"></i>';
    const chip = '<div class="fl adchip" style="transform:translate(' + f(Math.min(B.w - 480, gate - 8)) + 'px,' + f(B.airY) + 'px)"><span class="m">XAGUSD</span><span>refused by Commodities #4</span><span class="chip w-real">Real</span><span>·</span><span class="m">cost_filter</span></div>';
    const tokLab = '<div class="fl adtok" style="--x0:108px;--x1:' + f(Math.max(108, gate - 236)) + 'px;top:' + f(B.airY) + 'px"><span class="m">XAGUSD</span><span class="chip short">SHORT</span><span>trend_break_4h</span></div>';
    const app = document.getElementById('app').cloneNode(true);
    app.querySelectorAll('canvas,.fl,.pop,.tblp,.events,script').forEach(e => e.remove());
    app.querySelector('#stage').insertAdjacentHTML('beforeend', overlay + els + chip + tokLab);
    app.querySelector('#mocknote').textContent = 'preview · invented data';
    app.removeAttribute('id');
    app.setAttribute('style', 'width:1440px;height:900px;box-sizing:border-box;background:#040B07;color:#E6F1EA;font-family:Inter,system-ui,sans-serif;font-size:13px;display:grid;grid-template-columns:232px minmax(0,1fr) 40px;grid-template-rows:44px 32px minmax(0,1fr) 32px;overflow:hidden;position:relative');
    return { html: app.outerHTML, css: document.querySelector('style').textContent, extra: css, motes: B.motes.filter(m => m.live).length };
  });
  await browser.close();
  // the stylesheet: the board is one fixed 1440x900 frame, so the page-level rules and the two layout queries go
  let css = got.css;
  const cut = (from, to) => { const a = css.indexOf(from); if (a < 0) throw new Error('css block not found: ' + from); const b = css.indexOf(to, a); if (b < 0) throw new Error('css end not found: ' + to); css = css.slice(0, a) + css.slice(b); };
  cut('@media (min-width:1680px){', '@media (prefers-reduced-motion:reduce){');
  { const a = css.indexOf('/* ── the phone:'); if (a < 0) throw new Error('phone block not found'); css = css.slice(0, a); }
  css = css.replace(/\n\*\{box-sizing:border-box\}/, '\n.app,.app *,.app *::before,.app *::after{box-sizing:border-box}')
    .replace(/\nhtml,body\{[^}]*\}/, '').replace(/\nbody\{color:[^}]*\}/, '\nbody{margin:0;background:#040B07}')
    .replace(/\n\.app\{width:100vw;[^}]*\}/, '');
  css = css.replace(/^\/\*[\s\S]*?\*\/\n/, '');
  const head = '/* Anduin, the Great River: the page of flows, at rest (board 7). Synthetic data: the fictional book of the\n' +
    '   Operations Center and Barad-dur boards. Nothing under 11 px. No script and no SMIL: three price motes and one\n' +
    '   refused signal move by CSS offset-path, in steps of a thirtieth of a second; the refusal replays every 12 s in\n' +
    '   this preview (in the app it plays once, when it happens). Under prefers-reduced-motion nothing moves: the\n' +
    '   still bed stays. The page itself draws its flows on a canvas, 30 frames a second at most, none when nothing\n' +
    '   moves, and stops when hidden, locked or asked for reduced motion. */\n';
  css = head + css.trimEnd() + '\n' +
    '.adflow{position:absolute;left:0;top:0;z-index:3;pointer-events:none;overflow:visible}\n' +
    '.admote{position:absolute;left:0;top:0;z-index:4;width:9px;height:9px;border-radius:50%;pointer-events:none;offset-rotate:0deg;opacity:0;\n' +
    '  background:radial-gradient(circle,#D6FFE6 0,rgba(0,232,104,.85) 30%,rgba(0,232,104,.22) 60%,rgba(0,232,104,0) 100%)}\n' +
    '.adtokm{position:absolute;left:0;top:0;z-index:4;width:9px;height:9px;border:1.5px solid #E6F1EA;background:#040B07;pointer-events:none;offset-rotate:0deg;transform:rotate(45deg);opacity:0}\n' +
    '@keyframes adpe{0%{opacity:.95}6%{opacity:.6}12%{opacity:.3}18%{opacity:0}100%{opacity:0}}\n' + got.extra +
    '@media (prefers-reduced-motion:reduce){.admote,.adtokm,.fl.adchip,.fl.adtok{display:none}.blk .pe{animation:none!important}}\n';
  const sig = fs.readFileSync(S + '/magic/Signature.dc.html', 'utf8');
  const links = sig.split('\n').filter(l => l.startsWith('<link rel="stylesheet" href="https://fonts.googleapis.com')).join('\n');
  const tail = sig.slice(sig.indexOf('<script type="text/x-dc"'));
  if (!/^<script type="text\/x-dc" data-dc-script data-props='\{"\$preview":\{"width":1440,"height":900\}\}'>/.test(tail)) throw new Error('unexpected x-dc block');
  const out = '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<title>Anduin: the Great River, the page of flows</title>\n<script src="./support.js"></script>\n</head>\n<body>\n<x-dc>\n<helmet>\n' + links + '\n<style>\n' + css + '</style>\n</helmet>\n' + got.html + '\n</x-dc>\n' + tail;
  fs.writeFileSync(A + '/Anduin.dc.html', out);
  console.log(JSON.stringify({ bytes: out.length, scripts: (out.match(/<script\b/g) || []).length, smil: (out.match(/<animate/g) || []).length, canvas: (out.match(/<canvas/g) || []).length, offsetPath: (out.match(/offset-path/g) || []).length, liveMotes: got.motes, lines: out.split('\n').length }));
})().catch(e => { console.error('FAILED', e); process.exit(1); });
