# SamStones Book

A printed memorial booklet documenting 20 years of SamStone placements around the world.

Sam Cohn passed away in 2006. Over the following two decades, family and friends placed small clay stones — each inscribed with Sam's name — in meaningful locations across the globe, and logged their finds and placements at [samstones.org](http://samstones.org). This project generates a single master PDF booklet for the 20th anniversary, collecting all 1,681 entries organized by year.

---

## What it generates

One master HTML file → one PDF. The book contains:

- **Intro page** — full world map with all 1,681 dots, global stats (stones placed/found, requests sent, countries)
- **Year opener pages** — per-year world map, placed/found counts, request stats (2009–2019)
- **Content pages** — tiles in 2- or 3-column flexbox grids, mixing photo tiles and text-only tiles

Each tile shows the location name, date, contributor, and message (capped at 150 words with a "read more" link). Photo tiles show the image at natural aspect ratio; text-only tiles use a warm off-white background. Layout is 2-column for pages with <6 tiles, 3-column otherwise.

---

## Files

| File | Purpose |
|------|---------|
| `scraper.py` | Scrapes samstones.org WordPress into SQLite |
| `samstones.db` | SQLite database — 1,681 records (not in repo) |
| `prototype_gen.py` | Core generator: tile building, packing, HTML rendering |
| `generate_master.py` | Generates the single master HTML + PDF (all 20 years) |
| `measure_tiles.mjs` | Playwright script: measures actual rendered tile heights |
| `generate_pdf.mjs` | Playwright script: renders HTML → PDF via headless Chromium |
| `ne_110m_land.geojson` | Natural Earth land polygons for world maps |
| `cached_images/` | Local photo cache — populated on first run (not in repo) |
| `.tile_heights_cache.json` | Cached tile height measurements (not in repo) |

---

## Setup

```bash
# Python deps
uv add matplotlib numpy pillow

# Node.js deps (Playwright, for PDF + height measurement)
mkdir -p /tmp/pw_pdf
cd /tmp/pw_pdf
echo '{"name":"pw-pdf","version":"1.0.0","type":"module","dependencies":{"playwright":"^1.49.0"}}' > package.json
npm install
npx playwright install chromium
cp /path/to/SamStones_book/generate_pdf.mjs /tmp/pw_pdf/
cp /path/to/SamStones_book/measure_tiles.mjs /tmp/pw_pdf/
```

## Scrape the data (first time only)

```bash
python3 scraper.py
# Creates samstones.db with all 1,681 records + downloads images to cached_images/
```

## Generate the master booklet

```bash
python3 generate_master.py
# → samstones_master.html        (1.3 MB)
# → samstones_master.pdf         (~1.2 GB — raw Chromium embed, all photos at native res)
# → samstones_master_print.pdf   (~97 MB  — Ghostscript 300 DPI, upload to print-on-demand)
# → samstones_master_web.pdf     (~27 MB  — Ghostscript 150 DPI, screen / sharing)
```

The raw PDF is large because Chromium embeds photos at their original file resolution
(some are 20–30 MP). Ghostscript downsamples to the resolution actually needed for
300 DPI print (1085 px per 3.6" column). The compressed PDFs are generated automatically.

The generator:
1. Builds all tiles across all 20 years
2. Measures actual rendered heights via headless Playwright (one pass, ~60 s first run, cached after)
3. Packs tiles into pages using real heights
4. Renders HTML
5. Generates PDF via Playwright Chromium

## Prototype one year (for testing)

```bash
SAMSTONES_YEAR=2010 python3 prototype_gen.py
# → prototype_2010.html
# Serve with: python3 -m http.server 9888
```

---

## Layout algorithm

### Tile building

Each entry resolves to a tile dict with: best photo path (prefers URLs containing "sam"), word count, PIL-measured aspect ratio, and a tile weight:

| Weight | Condition |
|--------|-----------|
| 0.38 (large) | photo + >60 words |
| 0.22 (medium) | photo + 21–60 words |
| 0.13 (small) | photo + ≤20 words |
| 0.09 (chip) | no photo, ≥15 words |
| 0.06 (tiny) | no photo, <15 words |

### Height measurement (key step)

Before packing, all tiles are rendered at both column widths (2-col: 3.615 in, 3-col: 2.387 in) in a hidden off-screen Playwright page served via HTTP (so images load correctly). `getBoundingClientRect().height` is recorded for each tile. These exact browser heights replace estimation-based guesses — this is what makes packing accurate.

Measurements are cached in `.tile_heights_cache.json` (keyed by tile HTML hash), so only new or changed tiles need re-measurement on subsequent runs.

### Column assignment sort

Both simulation (`_page_max_col_h`) and rendering (`assign_to_cols`) sort tiles by height descending before greedy shortest-column assignment. This achieves much better column balance — without sorting, the same 9-tile set that sorts into three balanced 9.30" columns can instead greedy-assign into a lopsided 10.68" column, falsely blocking consolidations.

### Page grouping

Tiles are added one-by-one using greedy shortest-column assignment. A page closes when the simulated tallest column would exceed `PAGE_TARGET × available_height` (95% of 9.6 in = 9.12 in).

### Refill (borrow + consolidate)

After initial grouping, `refill_pages()` runs 3 outer cycles of:

1. **Borrow pass** (up to 8 passes, up to 20 pages lookahead): for each sparse page (max column gap > 0.20"), tries borrowing single tiles and pairs from later pages. Picks the borrow that most reduces the per-column average gap, or reduces the max gap if average stays the same. Checks donor health: removing a tile must not leave the donor page overflowing `PAGE_H`. MIN_DONOR_TILES=1 so 2-tile donors can donate 1 tile.
2. **Consolidation**: merges adjacent pages whose combined tiles fit within `avail_h = 9.6"`. Eliminates the cascade of 1–2 tile pages left by borrowing.

### CSS layout

Pure flexbox columns. Photo tiles render at natural aspect ratio (`width: 100%; height: auto`) — no gray letterboxing, no cropping. Text tiles shrink to content height. No absolute positioning.

---

## Technical notes

- WordPress SSL certificate mismatch → all fetches use `ssl.CERT_NONE`
- Images cached in `cached_images/` (MD5-hash filename, minimum 512 bytes)
- Text capped at 150 words; "read more →" links to original WordPress post
- Gravatar / WordPress system images are filtered out
- World maps rendered with matplotlib + Natural Earth GeoJSON, embedded as base64 PNG
- PDF generated via Playwright Chromium (headless) with a local HTTP server for image serving
