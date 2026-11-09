#!/usr/bin/env python3
"""Generate a single master SamStones booklet (all years, one HTML + PDF).

Run from the SamStones_book directory:
    python3 generate_master.py
"""

import os, sys, sqlite3, subprocess

# Must run from the book directory so relative paths (samstones.db, cached_images/) resolve
_HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(_HERE)
sys.path.insert(0, _HERE)

# Pre-set env so prototype_gen's module-level YEAR/OUT_FILE don't matter
os.environ.setdefault("SAMSTONES_YEAR", "2007")

from prototype_gen import (
    DB_PATH, ensure_geojson, make_year_map_b64,
    build_tiles, group_into_pages, refill_pages, measure_tile_heights,
    render_content_page, assign_to_cols, render_tile,
    CSS,
    PAGE_W, PAGE_MARGIN, TILE_GAP,
    esc,
)

OUT_HTML = os.path.join(_HERE, "samstones_master.html")
OUT_PDF  = os.path.join(_HERE, "samstones_master.pdf")

MASTER_CSS = CSS + """
/* ── Intro page ── */
.intro-page {
  display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 0.22in;
  background: #fafaf8;
  padding: 0.4in 0.3in;
}
.intro-title {
  font-size: 52pt; font-weight: bold; color: #1a252f;
  letter-spacing: -1px; line-height: 1; text-align: center;
}
.intro-subtitle {
  font-size: 16pt; color: #555; letter-spacing: 2px;
  font-style: italic;
}
.intro-map { width: 100%; border: 1px solid #ddd; border-radius: 3px; }
.intro-stats {
  display: flex; gap: 0.30in; flex-wrap: wrap; justify-content: center;
  margin-top: 0.05in;
}
.intro-stat { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.intro-stat-num   { font-size: 24pt; font-weight: bold; color: #1a252f; line-height: 1; }
.intro-stat-label { font-size: 7.5pt; color: #555; text-transform: uppercase;
                    letter-spacing: 0.8px; font-family: sans-serif; }
.intro-countries {
  font-size: 7.5pt; color: #555; text-align: center; line-height: 1.6;
  max-width: 6.5in; font-style: italic;
}
.intro-countries-label {
  font-size: 7pt; color: #777; text-transform: uppercase;
  letter-spacing: 0.8px; font-family: sans-serif; margin-bottom: 0.04in;
}

/* ── Year banner (first page of each new year) ── */
.year-banner {
  display: flex; align-items: center; gap: 0.12in;
  flex: 0 0 auto;
  padding: 0.06in 0.10in 0.04in;
  border-top: 2px solid #ddd;
}
.year-banner-num {
  font-size: 8.5pt; font-weight: bold; color: #bbb;
  font-family: sans-serif; white-space: nowrap;
  letter-spacing: 1.5px;
}
.year-banner-rule { flex: 1; height: 1px; background: #e8e8e8; }

/* Pages with a year banner use flex column so col-container fills remaining height */
.page-has-banner {
  display: flex; flex-direction: column;
}
.page-has-banner .col-container {
  flex: 1;
  height: auto;
}
"""


def make_all_map_b64(conn):
    rows = conn.execute(
        "SELECT latitude, longitude FROM samstones "
        "WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
    ).fetchall()
    lats = [r[0] for r in rows]
    lons = [r[1] for r in rows]
    return make_year_map_b64(lats, lons)


_COUNTRY_NORM = {
    # Encoding corruption
    "Mã©Xico":    "Mexico",
    # Single entry with embedded newline + log fragment — both halves of "Netherlands"
    "Nethe\n\n[6] [11:45:27 Am] [Log]Rlands": "Netherlands",
    # Long-form → short-form (US / UK duplicates)
    "United Kingdom of Great Britain and Northern Ireland": "United Kingdom",
    "United States of America": "United States",
    # City used as country
    "Porto":      "Portugal",
    # Punctuation / casing
    "Scotland. Uk": "Scotland",
    # Cryptic abbreviation
    "R.O.C.":     "Taiwan",
}


def _norm_country(name: str) -> str:
    return _COUNTRY_NORM.get(name, name)


def intro_page(conn, map_b64):
    placed = conn.execute(
        "SELECT COUNT(*) FROM samstones WHERE category LIKE '%Placed%'"
    ).fetchone()[0]
    found  = conn.execute(
        "SELECT COUNT(*) FROM samstones WHERE category LIKE '%Found%'"
    ).fetchone()[0]

    stones_sent = 0
    country_list = []
    try:
        r = conn.execute(
            "SELECT SUM(COALESCE(stones,0)) FROM requests WHERE is_spam=0"
        ).fetchone()
        if r:
            stones_sent = r[0] or 0
        raw_countries = [
            row[0] for row in conn.execute(
                "SELECT DISTINCT country FROM requests WHERE is_spam=0 AND country!=''"
            ) if row[0]
        ]
        # Normalise names, deduplicate, sort
        country_list = sorted(set(_norm_country(c) for c in raw_countries))
    except Exception:
        pass

    countries_n = len(country_list)

    def stat(num, label):
        return (f'<div class="intro-stat">'
                f'<span class="intro-stat-num">{num:,}</span>'
                f'<span class="intro-stat-label">{esc(label)}</span>'
                f'</div>')

    stats = (stat(stones_sent, "SamStones Sent") +
             stat(placed,      "Placement Reports") +
             stat(found,       "Finding Reports") +
             stat(countries_n, "Countries"))

    countries_html = ""
    if country_list:
        countries_html = (
            f'<div class="intro-countries">'
            f'<div class="intro-countries-label">Requests from</div>'
            f'{esc(", ".join(country_list))}'
            f'</div>'
        )

    return (f'<div class="page intro-page">'
            f'<div class="intro-title">SamStones</div>'
            f'<div class="intro-subtitle">2007 – 2026 · 20 Years</div>'
            f'<img class="intro-map" src="data:image/png;base64,{map_b64}" alt="">'
            f'<div class="intro-stats">{stats}</div>'
            f'{countries_html}'
            f'</div>')


def render_page_with_banner(page_tiles, year=None):
    n_cols = 3 if len(page_tiles) >= 6 else 2
    col_w  = (PAGE_W - 2 * PAGE_MARGIN - (n_cols - 1) * TILE_GAP) / n_cols
    cols   = assign_to_cols(page_tiles, n_cols, col_w)

    col_divs = []
    for col_tiles in cols:
        tile_html = "".join(render_tile(t) for t, _ in col_tiles)
        col_divs.append(f'<div class="col">{tile_html}</div>')
    cols_html = f'<div class="col-container">{"".join(col_divs)}</div>'

    if year is not None:
        banner = (f'<div class="year-banner">'
                  f'<span class="year-banner-num">{year}</span>'
                  f'<span class="year-banner-rule"></span>'
                  f'</div>')
        return f'<div class="page page-has-banner">{banner}{cols_html}</div>'
    else:
        return f'<div class="page">{cols_html}</div>'


PW_SCRIPT = os.path.join(_HERE, "generate_pdf.mjs")
PW_DIR    = "/private/tmp/pw_pdf"

def ensure_playwright_dir():
    """Ensure /tmp/pw_pdf exists with playwright package installed."""
    pkg = os.path.join(PW_DIR, "package.json")
    nm  = os.path.join(PW_DIR, "node_modules", "playwright")
    if not os.path.exists(nm):
        os.makedirs(PW_DIR, exist_ok=True)
        with open(pkg, "w") as f:
            f.write('{"name":"pw-pdf","version":"1.0.0","type":"module",'
                    '"dependencies":{"playwright":"^1.49.0"}}')
        subprocess.run(["npm", "install"], cwd=PW_DIR, check=True,
                       capture_output=True)
        subprocess.run(["npx", "playwright", "install", "chromium"],
                       cwd=PW_DIR, check=True, capture_output=True)


def main():
    ensure_geojson()
    conn = sqlite3.connect(DB_PATH)

    print("Building intro page…")
    all_map_b64 = make_all_map_b64(conn)
    intro_html  = intro_page(conn, all_map_b64)

    rows = conn.execute("""
        SELECT post_id, title, date_parsed, category, name, message,
               image_urls, photo_links, latitude, longitude
        FROM samstones
        ORDER BY date_parsed
    """).fetchall()
    col_names = ("post_id","title","date_parsed","category","name","message",
                 "image_urls","photo_links","latitude","longitude")
    all_records = [dict(zip(col_names, r)) for r in rows]
    print(f"Total records: {len(all_records)}")

    # Group by year
    year_groups: dict[int, list] = {}
    for r in all_records:
        y = int(r["date_parsed"][:4])
        year_groups.setdefault(y, []).append(r)

    # Build all tiles across all years, then measure in a single Playwright pass
    tiles_by_year: dict[int, list] = {}
    for year in sorted(year_groups.keys()):
        tiles_by_year[year] = build_tiles(year_groups[year])

    all_tiles = [t for tiles in tiles_by_year.values() for t in tiles]
    print(f"Measuring {len(all_tiles)} tile heights via Playwright (one pass)…")
    measure_tile_heights(all_tiles)

    all_pages_html = []
    total_content_pages = 0

    for year in sorted(year_groups.keys()):
        records = year_groups[year]
        tiles   = tiles_by_year[year]
        print(f"  {year}: {len(records)} records…", end=" ", flush=True)
        pages  = refill_pages(group_into_pages(tiles))
        print(f"{len(pages)} pages")
        total_content_pages += len(pages)

        for i, page_tiles in enumerate(pages):
            all_pages_html.append(
                render_page_with_banner(page_tiles, year=year if i == 0 else None)
            )

    total = total_content_pages + 1  # +1 for intro
    print(f"\nTotal pages: {total}  (1 intro + {total_content_pages} content)")

    body = intro_html + "\n" + "\n".join(all_pages_html)
    html = (f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8">\n'
            f'<title>SamStones · 20 Years</title>\n'
            f'<style>{MASTER_CSS}</style></head>\n<body>{body}</body></html>')

    with open(OUT_HTML, "w") as f:
        f.write(html)
    sz = os.path.getsize(OUT_HTML) / 1_000_000
    print(f"Written → {OUT_HTML}  ({sz:.1f} MB)")

    # Generate PDF via Playwright (Chromium) — identical to browser render
    pw_script_dest = os.path.join(PW_DIR, "generate_pdf.mjs")
    import shutil
    shutil.copy(PW_SCRIPT, pw_script_dest)

    try:
        ensure_playwright_dir()
        print("Generating PDF via Playwright Chromium…  (may take 2-3 min for 300 pages)")
        result = subprocess.run(
            ["node", "generate_pdf.mjs"],
            cwd=PW_DIR, timeout=600,
            capture_output=True, text=True,
        )
        if result.returncode == 0 and os.path.exists(OUT_PDF):
            pdf_sz = os.path.getsize(OUT_PDF) / 1_000_000
            print(f"PDF written → {OUT_PDF}  ({pdf_sz:.1f} MB)")
        else:
            print(f"PDF generation failed (exit {result.returncode}):")
            print(result.stdout[-500:])
            print(result.stderr[-500:])
    except Exception as e:
        print(f"PDF generation error: {e}")
        print(f"Generate manually:\n  node {pw_script_dest}")

    conn.close()


if __name__ == "__main__":
    main()
