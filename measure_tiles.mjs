#!/usr/bin/env node
/**
 * Measure actual rendered tile heights via Playwright (headless Chromium).
 * Args: --html <path>  --base <file-url>  --out <json-path>
 *
 * The HTML file contains divs with data-id2 and data-id3 attributes (the tile
 * index at 2-col and 3-col width respectively). Each div has an explicit CSS
 * width; this script measures its rendered height and writes JSON:
 *   { "<idx>_2": <px>, "<idx>_3": <px>, ... }
 */
import { chromium } from 'playwright';
import fs from 'fs';

const args = process.argv.slice(2);
const get  = (flag) => { const i = args.indexOf(flag); return i >= 0 ? args[i+1] : null; };
const htmlPath = get('--html');
const baseUrl  = get('--base');
const outPath  = get('--out');

if (!htmlPath || !outPath) {
  console.error('Usage: node measure_tiles.mjs --html <path> --base <url> --out <json>');
  process.exit(1);
}

const html = fs.readFileSync(htmlPath, 'utf-8');
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();

// Viewport wide enough for 2-col tiles (~350px), tall enough for all tiles
await page.setViewportSize({ width: 1200, height: 30000 });

await page.setContent(html, {
  baseURL: baseUrl || 'file:///',
  waitUntil: 'domcontentloaded',
});

// Wait for images — give up gracefully if some fail (broken links etc.)
try {
  await page.waitForFunction(() => {
    const imgs = document.querySelectorAll('img');
    return Array.from(imgs).every(img => img.complete);
  }, { timeout: 30000 });
} catch {}

const heights = await page.evaluate(() => {
  const result = {};
  document.querySelectorAll('[data-id2]').forEach(el => {
    result[el.getAttribute('data-id2') + '_2'] = el.getBoundingClientRect().height;
  });
  document.querySelectorAll('[data-id3]').forEach(el => {
    result[el.getAttribute('data-id3') + '_3'] = el.getBoundingClientRect().height;
  });
  return result;
});

fs.writeFileSync(outPath, JSON.stringify(heights));
await browser.close();
console.log(`Measured ${Object.keys(heights).length / 2} tiles`);
