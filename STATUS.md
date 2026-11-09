# SamStones Book — Project Status (updated Nov 2026)

## What this project is
A printed memorial booklet for the 20th anniversary of Sam Cohn's passing in 2006.
Collects all 1,681 SamStone placements/findings from samstones.org (2007–2026).

## Current output
| Output | Size | Pages |
|--------|------|-------|
| `samstones_master.html` | 1.3 MB | 189 (1 intro + 188 content) |
| `samstones_master.pdf` | ~1.2 GB | 189 |

Page counts by year (content pages only):

| Year | Records | Pages |
|------|---------|-------|
| 2007 | 189 | 18 |
| 2008 | 139 | 15 |
| 2009 | 129 | 13 |
| 2010 | 92 | 11 |
| 2011 | 97 | 13 |
| 2012 | 140 | 13 |
| 2013 | 157 | 15 |
| 2014 | 141 | 13 |
| 2015 | 134 | 14 |
| 2016 | 122 | 12 |
| 2017 | 86 | 9 |
| 2018 | 55 | 7 |
| 2019 | 47 | 7 |
| 2020 | 40 | 6 |
| 2021 | 24 | 5 |
| 2022 | 26 | 6 |
| 2023 | 25 | 5 |
| 2024 | 18 | 3 |
| 2025 | 9 | 2 |
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
- **Measurement-based packing**: real browser heights via Playwright via HTTP (not file://), not estimates
- **Borrow + consolidate**: multi-pass refill (3 outer cycles, up to 20 pages lookahead) to minimize blank space
- **Portrait photo cap**: `max-height: 3.0in` on photo tops prevents tall portraits dominating a column
- **Photo selection**: prefers URLs containing "sam" (likely the stone itself)
- **Text cap**: 150 words + "read more →" link to original WordPress post
- **avail_h = 9.6"**: packer and borrow/consolidate both capped here (measured CSS visible column = 9.649")

## What's done
- [x] Scraper (1,681 records)
- [x] Stone request data (email archive 2009–2019, 964 entries)
- [x] Intro page (all-years map, global stats, country list)
- [x] Flexbox tile layout (photos at natural aspect ratio)
- [x] Height-simulation page grouping
- [x] Multi-pass borrow + consolidation refill
- [x] Playwright measurement pass via HTTP server (accurate heights, photos load correctly)
- [x] Single master HTML + PDF via Playwright Chromium
- [x] Zero overflow pages (tiles never clipped at page boundary)
- [x] Data patch: recovered body text for 6 records where scraper missed post content

## Packing bugs fixed (this session)
1. **Photo clipping** (file:// → HTTP): `measure_tiles.mjs` now starts a local HTTP server so images load in Playwright; previously `file://` caused silent load failures and tiles were measured without photos, causing the packer to severely underestimate heights and pack too many tiles per page.
2. **Portrait photo dominance**: very tall portrait photos (up to 6.9" at 2-col) dominated one column, leaving others sparse. Added `max-height: 3.0in; overflow: hidden` to `.tile-portrait .tile-photo-top`.
3. **TILE_GAP overcount**: `_page_max_col_h()` added a gap after every tile; CSS flex gap is between tiles only (n−1 gaps). Fixed by tracking tile count per column and subtracting the trailing gap.
4. **Pair-borrow order reversal**: `_try_borrow()` checked a trial with tiles in [j1, j2] order but appended them reversed [j2, j1] via `pop(j2)` then `pop(j1)`. The overflow check validated the wrong order.
5. **Donor health**: borrowing a tile could leave the donor overflowing (e.g., 6-tile 3-col → 5-tile 2-col with a tall tile). Added a check that the donor stays within `PAGE_H` after any tiles are removed.
6. **Overflow tolerance**: the previous 1.03× tolerance on borrow/consolidate (`avail_h × 1.03 = 9.888"`) exceeded the actual CSS visible column height (~9.649"). Removed; both caps now use `avail_h = 9.6"` for the receiver and `PAGE_H = 9.8"` for donor health.
7. **Greedy column sort**: both `_page_max_col_h()` and `assign_to_cols()` now sort tiles by height DESC before assigning to columns. Without sorting, greedy order could pack the same tile set into a 10.68" column instead of 9.30"—blocking legitimate consolidations and borrows. After this fix: 189 total pages (down from 205), zero overflow pages, all non-last 2007 pages under 1" max gap.
8. **MIN_DONOR_TILES=1**: borrow now allows donating from a 2-tile page (leaving 1 tile for `_consolidate` to merge). Previously the threshold was 2 (2-tile pages could not be borrowed from at all).
9. **Max-gap improvement criterion**: borrow now also accepts a tile if max gap decreases even when avg gap stays the same (handles 2-col→3-col transitions where avg gap comparison was rejecting valid improvements).

## What's left / possible improvements
- [ ] Cover page design
- [ ] Upload to print-on-demand service
