# SamStones Book — Project Status (updated Nov 2026)

## What this project is
A printed memorial booklet for the 20th anniversary of Sam Cohn's passing in 2006.
Collects all 1,681 SamStone placements/findings from samstones.org (2007–2026).

## Current output
| Output | Size | Pages |
|--------|------|-------|
| `samstones_master.html` | 1.3 MB | 125 (1 intro + 124 content) |
| `samstones_master.pdf` | ~1 GB | 125 |

Page counts by year (content pages only):

| Year | Records | Pages |
|------|---------|-------|
| 2007 | 189 | 12 |
| 2008 | 139 | 11 |
| 2009 | 129 | 9 |
| 2010 | 92 | 7 |
| 2011 | 97 | 8 |
| 2012 | 140 | 9 |
| 2013 | 157 | 11 |
| 2014 | 141 | 10 |
| 2015 | 134 | 9 |
| 2016 | 122 | 7 |
| 2017 | 86 | 6 |
| 2018 | 55 | 4 |
| 2019 | 47 | 4 |
| 2020 | 40 | 4 |
| 2021 | 24 | 3 |
| 2022 | 26 | 3 |
| 2023 | 25 | 3 |
| 2024 | 18 | 2 |
| 2025 | 9 | 1 |
| 2026 | 11 | 1 |

## To regenerate
```bash
cd /Users/jcohn/SamStones_book
python3 generate_master.py
# → samstones_master.html + samstones_master.pdf
```

First run per session measures tile heights (Playwright, ~60 s). Subsequent runs
use `.tile_heights_cache.json` and are fast.

## Key design decisions (locked)
- **Flexbox columns**: tiles at natural height, no stretching, no letterboxing
- **2-col** for pages with <6 tiles, **3-col** for 6+ tiles
- **Measurement-based packing**: real browser heights via Playwright, not estimates
- **Borrow + consolidate**: multi-pass refill to minimize blank space at page bottoms
- **Photo selection**: prefers URLs containing "sam" (likely the stone itself)
- **Text cap**: 150 words + "read more →" link to original WordPress post

## What's done
- [x] Scraper (1,681 records)
- [x] Stone request data (email archive 2009–2019, 964 entries)
- [x] Year opener pages (map + stats)
- [x] Intro page (all-years map, global stats, country list)
- [x] Flexbox tile layout (photos at natural aspect ratio)
- [x] Height-simulation page grouping
- [x] Multi-pass borrow + consolidation refill
- [x] Playwright measurement pass (accurate heights)
- [x] Single master HTML + PDF via Playwright Chromium

## What's left / possible improvements
- [ ] Print review — check for any tiles that overflow their page boundary in the PDF
- [ ] Consider reducing PAGE_TARGET from 0.95 to 0.90 if print mode renders slightly taller than screen mode
- [ ] Cover page design
- [ ] Upload to print-on-demand service
