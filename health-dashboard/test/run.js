// Opens test/test.html at desktop and phone width, runs the page with mock.js and reports
// script errors, drawings that never filled in, and sideways scrolling. Prints NO ERRORS when clean.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const errs = [];
  for (const width of [1200, 400]) {
    const p = await b.newPage({ viewport: { width, height: 900 } });
    p.on('pageerror', (e) => errs.push(`[${width}] pageerror: ${e.message}`));
    p.on('console', (m) => { if (m.type() === 'error') errs.push(`[${width}] console: ${m.text()}`); });
    await p.goto('file://' + __dirname + '/test.html');
    const e = await p.evaluate(() => window.__run(window.__fixtures));
    e.forEach((x) => errs.push(`[${width}] ${x}`));
    const blanks = await p.evaluate(() => [...document.querySelectorAll('[data-draw]')].filter((el) => el.textContent.trim() === '—' && !el.querySelector('svg')).map((el) => el.dataset.draw));
    if (blanks.length) errs.push(`[${width}] still "—": ${blanks.join(', ')}`);
    const over = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (over > 0) errs.push(`[${width}] page scrolls sideways by ${over}px`);
    if (process.argv[2]) await p.screenshot({ path: `${process.argv[2]}-${width}.png`, fullPage: true });
    await p.close();
  }
  await b.close();
  console.log(errs.length ? errs.join('\n') : 'NO ERRORS');
})();
