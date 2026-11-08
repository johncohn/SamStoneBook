#!/usr/bin/env node
/**
 * Generate samstones_master.pdf using Playwright (Chromium).
 * Usage: node generate_pdf.mjs
 */
import { chromium } from 'playwright';
import http from 'http';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const BOOK_DIR = '/Users/jcohn/SamStones_book';
const HTML_FILE = path.join(BOOK_DIR, 'samstones_master.html');
const PDF_OUT   = path.join(BOOK_DIR, 'samstones_master.pdf');

// Simple static file server for BOOK_DIR
function startServer(dir, port) {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const filePath = path.join(dir, req.url.split('?')[0]);
      fs.readFile(filePath, (err, data) => {
        if (err) { res.writeHead(404); res.end('Not found'); return; }
        const ext = path.extname(filePath).toLowerCase();
        const types = { '.html': 'text/html', '.jpg': 'image/jpeg',
                        '.jpeg': 'image/jpeg', '.png': 'image/png',
                        '.gif': 'image/gif', '.webp': 'image/webp' };
        res.writeHead(200, { 'Content-Type': types[ext] || 'application/octet-stream' });
        res.end(data);
      });
    });
    server.listen(port, '127.0.0.1', () => {
      console.log(`HTTP server on http://127.0.0.1:${port}`);
      resolve(server);
    });
  });
}

const PORT = 9877;
const server = await startServer(BOOK_DIR, PORT);

console.log('Launching Chromium…');
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();

console.log('Loading page…');
await page.goto(`http://127.0.0.1:${PORT}/samstones_master.html`, {
  waitUntil: 'networkidle',
  timeout: 120000,
});

console.log('Waiting for images…');
await page.waitForFunction(() => {
  const imgs = document.querySelectorAll('img');
  return Array.from(imgs).every(img => img.complete);
}, { timeout: 60000 });

console.log('Generating PDF…');
await page.pdf({
  path: PDF_OUT,
  format: 'Letter',
  margin: { top: '0', right: '0', bottom: '0', left: '0' },
  printBackground: true,
  preferCSSPageSize: true,
});

const stats = fs.statSync(PDF_OUT);
console.log(`PDF written → ${PDF_OUT}  (${(stats.size / 1e6).toFixed(1)} MB)`);

await browser.close();
server.close();
