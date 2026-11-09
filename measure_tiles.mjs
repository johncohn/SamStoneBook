#!/usr/bin/env node
/**
 * Measure actual rendered tile heights via Playwright (headless Chromium).
 * Args: --html <path>  --dir <book-dir>  --out <json-path>
 *
 * Starts a local HTTP server so images load from HTTP (identical conditions to
 * the final PDF render), not file:// — file:// loads can silently fail in
 * Chromium, causing tile heights to be measured without their photos and the
 * packer to under-estimate tile heights, causing page overflow in the PDF.
 *
 * The HTML file must live inside <book-dir>; it is served at the root.
 * Heights are written as JSON: { "<idx>_2": <px>, "<idx>_3": <px>, ... }
 */
import { chromium } from 'playwright';
import http from 'http';
import fs from 'fs';
import path from 'path';

const args = process.argv.slice(2);
const get  = (flag) => { const i = args.indexOf(flag); return i >= 0 ? args[i+1] : null; };
const htmlPath = get('--html');
const bookDir  = get('--dir');
const outPath  = get('--out');

if (!htmlPath || !bookDir || !outPath) {
  console.error('Usage: node measure_tiles.mjs --html <path> --dir <book-dir> --out <json>');
  process.exit(1);
}

// ── Local HTTP server (same pattern as generate_pdf.mjs) ──────────────────
function startServer(dir, port) {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const filePath = path.join(dir, decodeURIComponent(req.url.split('?')[0]));
      fs.readFile(filePath, (err, data) => {
        if (err) { res.writeHead(404); res.end('Not found'); return; }
        const ext  = path.extname(filePath).toLowerCase();
        const mime = { '.html':'text/html', '.jpg':'image/jpeg', '.jpeg':'image/jpeg',
                       '.png':'image/png', '.gif':'image/gif', '.webp':'image/webp' };
        res.writeHead(200, { 'Content-Type': mime[ext] || 'application/octet-stream' });
        res.end(data);
      });
    });
    server.listen(port, '127.0.0.1', () => resolve(server));
  });
}

const PORT   = 19877;   // separate port so it doesn't conflict with the preview server
const server = await startServer(bookDir, PORT);

// ── Playwright measurement ─────────────────────────────────────────────────
const htmlFile = path.relative(bookDir, htmlPath);   // relative path inside bookDir
const url      = `http://127.0.0.1:${PORT}/${htmlFile}`;

const browser = await chromium.launch({ headless: true });
const page    = await browser.newPage();
await page.setViewportSize({ width: 1200, height: 30000 });

await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });

// Wait for all images to finish loading (success or error)
try {
  await page.waitForFunction(() => {
    const imgs = document.querySelectorAll('img');
    return Array.from(imgs).every(img => img.complete);
  }, { timeout: 60000 });
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
server.close();
console.log(`Measured ${Object.keys(heights).length / 2} tiles`);
