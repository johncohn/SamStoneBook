# SamStones Book

A printed memorial booklet documenting 20 years of SamStone placements around the world.

Sam Cohn passed away in 2006. Over the following two decades, family and friends placed small clay stones — each inscribed with Sam's name — in meaningful locations across the globe, and logged their finds and placements at [samstones.org](http://samstones.org). This project generates a printed booklet for the 20th anniversary, collecting all 1,681 entries organized by year.

---

## What it generates

One HTML file per year (2007–2026), formatted as 7.5 × 10 inch pages ready for PDF export. Each year's section contains:

- **Year opener page** — world map with red dots marking each stone's location, plus placed/found counts
- **Content pages** — tiles laid out in 2- or 3-column flexbox grids, mixing photo tiles and text-only tiles

Each tile shows the location name, date, contributor name, and a message (capped at 150 words with a "read more" link to the original post). Tiles with photos show the image; tiles without use a warm off-white background.

---

## Files

| File | Purpose |
|------|---------|
| `scraper.py` | Scrapes samstones.org WordPress site into SQLite |
| `samstones.db` | SQLite database — 1,681 records (not in repo, generate with scraper) |
| `prototype_gen.py` | Main HTML generator — one year per run |
| `generate_all.py` | Runs the generator for all 20 years |
| `ne_110m_land.geojson` | Natural Earth land polygons (for world map) |
| `cached_images/` | Local photo cache — populated on first run (not in repo) |

---

## Setup

```bash
pip install matplotlib numpy   # or: uv add matplotlib numpy
```

## Scrape the data (first time only)

```bash
python3 scraper.py
# Creates samstones.db with all 1,681 records
```

## Generate one year

```bash
SAMSTONES_YEAR=2010 python3 prototype_gen.py
# Outputs: prototype_2010.html
```

Open `prototype_2010.html` in a browser, then File → Print → Save as PDF.

## Generate all 20 years

```bash
python3 generate_all.py
# Outputs: prototype_2007.html … prototype_2026.html
```

---

## Layout algorithm

**Tile classification** — each entry gets a weight based on content richness:
- `large` (0.38) — photo + >60 words
- `medium` (0.22) — photo + 21–60 words
- `small` (0.13) — photo + ≤20 words
- `chip` (0.09) — no photo, ≥15 words
- `tiny` (0.06) — no photo, <15 words

**Page grouping** — tiles are accumulated greedily until their combined weight exceeds `PAGE_TARGET=0.95`. Photos are placed first (shortest-column greedy), then text tiles fill remaining space.

**Gap filling** — a multi-pass borrow algorithm pulls tiles from the next page to fill blank space at the bottom of text-only columns. It simulates every candidate tile (and every pair) using the post-borrow column layout, picks the borrow that most reduces the remaining gap, and repeats until convergence. This correctly handles the 2-column → 3-column layout transition that occurs when a page crosses 6 tiles.

**CSS layout** — pure flexbox, no absolute positioning. Photo tiles use `flex: 1 1 0` (grow to fill). Text tiles use `flex: 0 0 auto` (shrink to content — no white space inside boxes).

---

## Technical notes

- WordPress SSL certificate mismatch → all image fetches use `ssl.CERT_NONE`
- Images cached locally in `cached_images/` (md5-hash filename)
- Text longer than 150 words is truncated; a "read more →" link points to the original WordPress post
- Gravatar / WordPress system images are filtered out (not meaningful photos)
- World map rendered with matplotlib + Natural Earth GeoJSON, embedded as base64 PNG
