# SamStones Book — Project Status (updated Nov 2026)

## What this project is
A printed memorial booklet for the 20th anniversary of Sam Cohn's passing in 2006.
It documents all 1,681 SamStone placements/findings from samstones.org over 20 years.

## Files
| File | Status | Notes |
|------|--------|-------|
| `scraper.py` | Done | Scrapes WordPress site into SQLite |
| `samstones.db` | Done | 1,681 records |
| `prototype_gen.py` | Working | Generates HTML booklet for one year |
| `prototype_2010.html` | Done | Latest test output — open in browser |
| `ne_110m_land.geojson` | Done | World map land polygons |
| `cached_images/` | Growing | Downloaded external photos |

## How to generate a year
```bash
cd /Users/jcohn/SamStones_book
# Edit line: YEAR = 2010   ← change to desired year
python3 prototype_gen.py
# Opens: prototype_2010.html
```

## Layout design
- **Year opener**: world map with red dots + placed/found count
- **Stamp** (0 photos, ≤40 words): 18 per page, 3-column flow
- **Half card** (1–3 photos or short story): photo + text, bin-packed ~3/page
- **Full card** (4+ photos): 2×2 photo grid + text, one per page

## Current state of prototype_gen.py
- Tier classification uses **resolved photo count** (dead links don't count)
- Look-ahead swizzle fills gaps without strict date ordering (scan 10 ahead)
- Full cards capped at 4 photos and 400 words (so they fit on one page)
- Half cards capped at 160 words
- 2010 test: fill rates min=66%, avg=91%, max=100% — no overflow

## What's next
1. Open `prototype_2010.html`, print to PDF, verify it looks good
2. Share any layout ideas / feedback
3. If approved → generate all 20 years (run once per year, or build a loop)

## Technical notes
- WordPress SSL cert mismatch → all fetches use `ssl.CERT_NONE` (-k flag)
- World map uses matplotlib + Natural Earth GeoJSON
- Images cached locally in `cached_images/` (md5 hash filename)
- Dependencies: matplotlib, numpy (standard library otherwise)
