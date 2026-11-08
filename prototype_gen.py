#!/usr/bin/env python3
"""
SamStones booklet — slicing-tree photo-album layout.

Each entry becomes a tile weighted by content richness. Tiles are grouped into
pages then laid out via recursive rectangle bisection (slicing tree). Each tile
adapts its internal layout (portrait / landscape) to its assigned rectangle.

Key design decisions:
  - Every entry with a photo shows exactly one photo
  - Photos whose URL contains 'sam' are preferred (likely shows the SamStone)
  - Text capped at MAX_WORDS; "read more →" link to original post for longer entries
  - Text-only entries are small tiles mixed into the flow — no separate stamp section
  - TILE_GAP is a single constant — change it to adjust all spacing at once
"""

import sqlite3, json, base64, io, os, re, ssl, math, urllib.request, subprocess, hashlib
from html import escape
from datetime import datetime
from PIL import Image as _PILImage
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
import numpy as np

DB_PATH      = "samstones.db"
YEAR         = int(os.environ.get("SAMSTONES_YEAR", 2010))
OUT_FILE     = f"prototype_{YEAR}.html"
GEOJSON_PATH = "ne_110m_land.geojson"
IMG_DIR      = "cached_images"
BASE_URL     = "http://samstones.org/WordPress1"
os.makedirs(IMG_DIR, exist_ok=True)

# ── PAGE & TILE GEOMETRY (all in inches) ───────────────────────────────────────
PAGE_W          = 7.5   # usable page width
PAGE_H          = 9.8   # usable page height (matches CSS 10in minus tiny buffer)
PAGE_MARGIN     = 0.10  # outer gap from page edge to first tile
TILE_GAP        = 0.07  # gap between adjacent tiles — change this to retune all spacing
MIN_DIM         = 1.5   # minimum tile width or height
MAX_WORDS       = 150   # text cap; "read more →" link beyond this
MAX_TILES_PAGE  = 40    # safety cap; height simulation is the real gating factor

# Text height estimation — used to pick portrait vs landscape and size the photo area
TILE_LINE_H        = 0.150  # one line of 8pt text in inches
TILE_HEADER_H      = 0.38   # height for location title + meta row
TILE_PAD_H         = 0.14   # inner vertical padding
WPL_PORTRAIT       = 9      # words per line in portrait text column
WPL_LANDSCAPE      = 7      # words per line in landscape text column (narrower)
LANDSCAPE_MIN_FILL = 0.60   # only use landscape when text fills >= this fraction of tile height

# Column layout constants
WPL_COL        = 0.40        # inches per word (estimates words-per-line from column width)
MAX_TILE_NAT_H = PAGE_H * 0.70  # cap natural tile height at 70% of page

# Tile weights — relative area as fraction of the page
W_LARGE   = 0.38   # photo + long text  (>60 words)
W_MEDIUM  = 0.22   # photo + med text   (21–60 words)
W_SMALL   = 0.13   # photo + short text (≤20 words)
W_CHIP    = 0.09   # no photo, ≥15 words
W_TINY    = 0.06   # no photo, <15 words

PAGE_TARGET = 0.95   # fill pages until accumulated weight exceeds this

# ── SSL ────────────────────────────────────────────────────────────────────────
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode    = ssl.CERT_NONE

IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.webp')


# ── IMAGE RESOLUTION ──────────────────────────────────────────────────────────

def url_to_local(url: str) -> str | None:
    import hashlib
    key  = hashlib.md5(url.encode()).hexdigest()[:12]
    ext  = os.path.splitext(url.split("?")[0])[1].lower() or ".jpg"
    if ext not in IMAGE_EXTS:
        ext = ".jpg"
    path = os.path.join(IMG_DIR, key + ext)
    if os.path.exists(path):
        if os.path.getsize(path) >= 512:   # 0-byte or truncated = treat as missing
            return path
        os.remove(path)                    # clean up corrupt cached file
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SamStones/1.0"})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=10) as resp:
            ct = resp.headers.get("Content-Type", "")
            if not any(t in ct for t in ("image/", "jpeg", "png", "gif", "webp")):
                return None
            data = resp.read(5_000_000)
        if len(data) < 512:               # empty/non-image response
            return None
        with open(path, "wb") as f:
            f.write(data)
        return path
    except Exception:
        return None


_SKIP_DOMAINS = ("gravatar.com", "avatar", "wp-includes", "s.w.org")

def pick_best_photo(r: dict) -> str | None:
    """
    Return local path of best photo. Prefer URLs containing 'sam'
    (likely a photo of the actual SamStone). Skip profile avatars and
    WordPress system images which are never meaningful photos.
    """
    imgs  = json.loads(r["image_urls"]  or "[]")
    links = json.loads(r["photo_links"] or "[]")
    all_urls = [u for u in imgs + links
                if not any(d in u.lower() for d in _SKIP_DOMAINS)]

    sam_urls  = [u for u in all_urls if "sam" in u.lower()]
    other_urls = [u for u in all_urls if "sam" not in u.lower()]

    for url in sam_urls + other_urls:
        local = url_to_local(url)
        if local:
            return local
    return None


# ── TEXT CLEANING ─────────────────────────────────────────────────────────────

_NOISE_RE = re.compile(
    r'(TAGS?:|Categories:|ARCHIVE|DISCLAIMER|© Copyright|\bMo Tu We\b|'
    r'Afghanistan Albania|Required Comment|Add comment Name\*|'
    r'\bSearch Include comments\b|View posts in large calendar)',
    re.IGNORECASE
)
_URL_RE      = re.compile(r'https?://\S+', re.IGNORECASE)
_EMAIL_RE    = re.compile(r'\b[\w.%+-]+@[\w.-]+\.[a-zA-Z]{2,}\b')
_FIELD_RE    = re.compile(r'\b(Name|Email|File\s+attached)\s*=\s*\S+[^\n]*\n?',
                          re.IGNORECASE)


def clean_message(msg: str) -> str:
    if not msg:
        return ""
    m = _NOISE_RE.search(msg)
    if m:
        msg = msg[:m.start()].strip()
    msg = _FIELD_RE.sub("", msg)    # strip "Email = x" / "Name = x" field headers
    msg = _EMAIL_RE.sub("", msg)    # strip bare email addresses
    msg = _URL_RE.sub("", msg)      # strip bare URLs
    msg = re.sub(r'\n{3,}', '\n\n', msg)
    msg = re.sub(r'[ \t]+', ' ', msg)
    return msg.strip()


def safe_name(name_str: str) -> str:
    """Return name only if it's not an email address."""
    n = (name_str or "").strip()
    return "" if "@" in n else n


# ── TILE BUILDING ─────────────────────────────────────────────────────────────

def tile_weight(has_photo: bool, wc: int) -> float:
    if has_photo:
        if wc > 60:  return W_LARGE
        if wc > 20:  return W_MEDIUM
        return W_SMALL
    return W_CHIP if wc >= 15 else W_TINY


def _image_aspect_ratio(path: str) -> float:
    """Return width/height for a cached image file; 1.0 on any error."""
    try:
        with _PILImage.open(path) as img:
            w, h = img.size
            return w / h if h > 0 else 1.0
    except Exception:
        return 1.0


def build_tiles(records: list) -> list:
    """Pre-resolve photos, pick best, compute weight. Returns list of tile dicts."""
    tiles = []
    for r in records:
        msg   = clean_message(r["message"])
        wc    = len(msg.split())
        photo = pick_best_photo(r)
        w     = tile_weight(has_photo=bool(photo), wc=wc)
        ar    = _image_aspect_ratio(photo) if photo else 1.0
        tiles.append({"record": r, "photo": photo, "wc": wc,
                      "weight": w, "aspect_ratio": ar})
    return tiles


# ── PAGE GROUPING ─────────────────────────────────────────────────────────────

def _page_max_col_h(tiles: list) -> float:
    """Simulate greedy column assignment; return the tallest column's height."""
    if not tiles:
        return 0.0
    n_cols = 3 if len(tiles) >= 6 else 2
    col_w  = (PAGE_W - 2*PAGE_MARGIN - (n_cols-1)*TILE_GAP) / n_cols
    col_h  = [0.0] * n_cols
    for tile in tiles:
        i = min(range(n_cols), key=lambda j: col_h[j])
        col_h[i] += natural_tile_height(tile, col_w) + TILE_GAP
    return max(col_h)


def group_into_pages(tiles: list) -> list[list]:
    """Add tiles one-by-one; start a new page when simulated column height overflows."""
    avail_h  = PAGE_H - 2*PAGE_MARGIN
    target_h = avail_h * PAGE_TARGET
    pages, cur = [], []
    for tile in tiles:
        test = cur + [tile]
        if len(cur) >= 2 and _page_max_col_h(test) > target_h:
            pages.append(cur)
            cur = [tile]
        else:
            cur = test
        if len(cur) >= MAX_TILES_PAGE:
            pages.append(cur)
            cur = []
    if cur:
        pages.append(cur)
    return pages


def _page_fill_score(tiles: list) -> float:
    """Estimate page fill quality: blend of average and worst column fill ratio."""
    if not tiles:
        return 0.0
    n_cols  = 3 if len(tiles) >= 6 else 2
    col_w   = (PAGE_W - 2*PAGE_MARGIN - (n_cols - 1)*TILE_GAP) / n_cols
    cols    = assign_to_cols(tiles, n_cols, col_w)
    avail_h = PAGE_H - 2*PAGE_MARGIN
    fills = []
    for col_tiles in cols:
        if not col_tiles:
            fills.append(0.0)
            continue
        n_gaps    = max(0, len(col_tiles) - 1)
        col_avail = avail_h - n_gaps * TILE_GAP
        col_nat   = sum(nh for _, nh in col_tiles)
        fills.append(min(1.0, col_nat / col_avail))
    avg   = sum(fills) / len(fills)
    worst = min(fills)
    return 0.6 * avg + 0.4 * worst


def _col_gaps(tiles: list) -> list[float]:
    """Return the blank-space gap at the bottom of each column using render n_cols."""
    if not tiles:
        return []
    n_cols  = 3 if len(tiles) >= 6 else 2
    col_w   = (PAGE_W - 2*PAGE_MARGIN - (n_cols - 1)*TILE_GAP) / n_cols
    cols    = assign_to_cols(tiles, n_cols, col_w)
    avail_h = PAGE_H - 2*PAGE_MARGIN
    gaps = []
    for col_tiles in cols:
        n_g     = max(0, len(col_tiles) - 1)
        col_nat = sum(nh for _, nh in col_tiles)
        gaps.append(max(0.0, avail_h - n_g * TILE_GAP - col_nat))
    return gaps


def _try_borrow(pages: list, i: int, donor_idx: int, min_gap: float) -> bool:
    """Try to borrow tiles from pages[donor_idx] into pages[i].

    Uses per-column average gap as the comparison metric so the comparison
    stays valid across the 2-col→3-col boundary (n_cols changes at 3 tiles).
    Picks the single tile or pair that most reduces the per-column average gap.
    """
    MIN_DONOR_TILES = 2

    curr_gaps = _col_gaps(pages[i])
    if not curr_gaps or max(curr_gaps) < min_gap:
        return False
    curr_avg = sum(curr_gaps) / len(curr_gaps)

    if donor_idx >= len(pages):
        return False
    donor_list = pages[donor_idx]
    if len(donor_list) <= MIN_DONOR_TILES:
        return False

    avail_h   = PAGE_H - 2*PAGE_MARGIN
    max_col_h = avail_h * 1.03   # allow 3% overflow so stacked portrait photos fill page

    # ── Try every single tile ────────────────────────────────────────────
    best_j       = -1
    best_new_avg = curr_avg
    for j, donor in enumerate(donor_list):
        trial = pages[i] + [donor]
        if _page_max_col_h(trial) > max_col_h:   # overflow guard
            continue
        trial_gaps = _col_gaps(trial)
        new_avg    = sum(trial_gaps) / len(trial_gaps) if trial_gaps else 0.0
        if new_avg < best_new_avg:
            best_new_avg = new_avg
            best_j       = j

    # ── Try every pair ────────────────────────────────────────────────────
    best_pair     = (-1, -1)
    best_pair_avg = best_new_avg
    if len(pages[i]) + 2 <= MAX_TILES_PAGE:
        for j1 in range(len(donor_list)):
            for j2 in range(j1 + 1, len(donor_list)):
                trial = pages[i] + [donor_list[j1], donor_list[j2]]
                if _page_max_col_h(trial) > max_col_h:   # overflow guard
                    continue
                trial_gaps = _col_gaps(trial)
                new_avg    = sum(trial_gaps) / len(trial_gaps) if trial_gaps else 0.0
                if new_avg < best_pair_avg:
                    best_pair_avg = new_avg
                    best_pair     = (j1, j2)

    if best_pair != (-1, -1):
        j1, j2 = best_pair
        pages[i].append(donor_list.pop(j2))
        pages[i].append(donor_list.pop(j1))
        return True
    elif best_j >= 0:
        pages[i].append(donor_list.pop(best_j))
        return True
    return False


def _consolidate(pages: list) -> list:
    """Merge adjacent pages that physically fit together (3% tolerance for portrait stacking)."""
    avail_h   = PAGE_H - 2*PAGE_MARGIN
    max_col_h = avail_h * 1.03
    changed = True
    while changed:
        changed = False
        result  = []
        i = 0
        while i < len(pages):
            if (i + 1 < len(pages) and
                    _page_max_col_h(pages[i] + pages[i+1]) <= max_col_h):
                result.append(pages[i] + pages[i+1])
                i += 2
                changed = True
            else:
                result.append(pages[i])
                i += 1
        pages = result
    return pages


def refill_pages(pages: list) -> list:
    """Multi-pass borrow + consolidate sparse pages (3 outer cycles)."""
    MIN_GAP       = 0.20
    MAX_LOOKAHEAD = 8

    for _outer in range(3):
        # Borrow pass
        for _pass in range(8):
            made_borrow = False
            for i in range(len(pages) - 1):
                while len(pages[i]) < MAX_TILES_PAGE:
                    borrowed = False
                    for ahead in range(1, min(MAX_LOOKAHEAD + 1, len(pages) - i)):
                        if _try_borrow(pages, i, i + ahead, MIN_GAP):
                            borrowed    = True
                            made_borrow = True
                            break
                    if not borrowed:
                        break
            if not made_borrow:
                break

        # Consolidation: merge sparse adjacent pages left by cascade
        pages = _consolidate(pages)

    return [p for p in pages if p]


# ── SLICING TREE LAYOUT ────────────────────────────────────────────────────────

def slice_layout(tiles: list, x: float, y: float, w: float, h: float) -> list:
    """
    Recursively lay tiles into rectangle (x, y, w, h) using a slicing tree.
    Split direction is determined by rectangle aspect ratio:
      wide (w >= h) → vertical split; tall → horizontal split.
    Split ratio is weight-proportional for visual balance.
    Returns [(tile, x, y, w, h), ...].
    """
    if not tiles:
        return []
    if len(tiles) == 1:
        return [(tiles[0], x, y, w, h)]

    total_w = sum(t["weight"] for t in tiles)
    target  = total_w / 2

    acc, split_idx = 0.0, 1
    for i, t in enumerate(tiles[:-1]):   # never split after the last tile
        acc += t["weight"]
        if acc >= target:
            split_idx = i + 1
            break

    # Guarantee both halves are non-empty
    split_idx = max(1, min(split_idx, len(tiles) - 1))
    left  = tiles[:split_idx]
    right = tiles[split_idx:]
    ratio = sum(t["weight"] for t in left) / total_w
    g     = TILE_GAP / 2

    if w >= h:  # wide → vertical split
        sx = x + w * ratio
        return (slice_layout(left,  x,      y, sx - x - g, h) +
                slice_layout(right, sx + g, y, x + w - sx - g, h))
    else:       # tall → horizontal split
        sy = y + h * ratio
        return (slice_layout(left,  x, y,      w, sy - y - g) +
                slice_layout(right, x, sy + g, w, y + h - sy - g))


# ── WORLD MAP ─────────────────────────────────────────────────────────────────

def ensure_geojson():
    if os.path.exists(GEOJSON_PATH):
        return
    url = ("https://raw.githubusercontent.com/nvkelso/"
           "natural-earth-vector/master/geojson/ne_110m_land.geojson")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SamStones/1.0"})
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=20) as r:
            data = r.read()
        with open(GEOJSON_PATH, "wb") as f:
            f.write(data)
    except Exception as e:
        print(f"  Could not download world outline: {e}")


def load_land_polygons():
    if not os.path.exists(GEOJSON_PATH):
        return []
    with open(GEOJSON_PATH) as f:
        gj = json.load(f)
    polys = []
    for feat in gj.get("features", []):
        geom   = feat.get("geometry", {})
        coords = geom.get("coordinates", [])
        if geom.get("type") == "Polygon":
            polys.append(np.array(coords[0]))
        elif geom.get("type") == "MultiPolygon":
            for part in coords:
                polys.append(np.array(part[0]))
    return polys


def make_year_map_b64(lats, lons):
    fig, ax = plt.subplots(figsize=(7.5, 3.0), facecolor="#d6eaf8")
    ax.set_facecolor("#d6eaf8")
    ax.set_xlim(-180, 180); ax.set_ylim(-85, 85)
    ax.set_aspect("equal"); ax.axis("off")
    for poly in load_land_polygons():
        ax.add_patch(Polygon(poly, closed=True, facecolor="#dce8c8",
                             edgecolor="#aabf8a", linewidth=0.3, zorder=1))
    ax.axhline(0, color="#aabf8a", linewidth=0.5, alpha=0.6, zorder=2)
    if lats:
        ax.scatter(lons, lats, s=16, c="#c0392b", alpha=0.9,
                   zorder=5, linewidths=0.4, edgecolors="white")
    fig.tight_layout(pad=0.1)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="#d6eaf8")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


# ── HTML HELPERS ───────────────────────────────────────────────────────────────

def badge(cat):
    if not cat: return ""
    color = "#27ae60" if "Placed" in cat else "#2980b9"
    label = "Placed" if "Placed" in cat else "Found"
    return f'<span class="badge" style="background:{color}">{label}</span>'


def fmt_date(d):
    try:    return datetime.strptime(d, "%Y-%m-%d").strftime("%b %-d, %Y")
    except: return d or ""


def esc(s): return escape(str(s or ""))


def trunc_linked(msg: str, post_id: int) -> str:
    words = (msg or "").split()
    if not words:
        return ""
    if len(words) <= MAX_WORDS:
        return esc(msg)
    url = f"{BASE_URL}/?p={post_id}"
    return (esc(" ".join(words[:MAX_WORDS])) +
            f' … <a href="{url}" class="read-more" target="_blank">read more →</a>')


def first_name(name_str: str) -> str:
    parts = (name_str or "").strip().split()
    return parts[0] if parts else ""


def wrote_prefix(r) -> str:
    fn = first_name(safe_name(r.get("name", "")))
    return f'<span class="wrote">{esc(fn)} wrote:</span> ' if fn else ""


def img_cover(src: str) -> str:
    return (f'<img class="tile-img" src="{esc(src)}" alt=""'
            f' onerror="this.style.display:\'none\'">')


# ── TILE HTML ─────────────────────────────────────────────────────────────────

def _header(r):
    n    = safe_name(r.get("name", ""))
    name = f' · {esc(n)}' if n else ""
    return (f'<div class="tile-loc">{esc(r["title"])}</div>'
            f'<div class="tile-meta">{fmt_date(r["date_parsed"])}'
            f'{name} {badge(r["category"])}</div>')


def portrait_tile(r, photo, wc):
    """Photo top (grows to fill), caption below (natural height — no white space)."""
    text   = trunc_linked(clean_message(r["message"]), r["post_id"])
    prefix = wrote_prefix(r)
    return (f'<div class="tile tile-portrait">'
            f'<div class="tile-photo-top">{img_cover(photo)}</div>'
            f'<div class="tile-caption">'
            f'{_header(r)}'
            f'{"<div class=tile-text>" + prefix + text + "</div>" if text else ""}'
            f'</div></div>')


def landscape_tile(r, photo, style):
    """Photo on left ~38%, header + text on right ~62%."""
    text   = trunc_linked(clean_message(r["message"]), r["post_id"])
    prefix = wrote_prefix(r)
    return (f'<div class="tile tile-landscape" style="{style}">'
            f'<div class="tile-photo-left">{img_cover(photo)}</div>'
            f'<div class="tile-content">'
            f'{_header(r)}'
            f'{"<div class=tile-text>" + prefix + text + "</div>" if text else ""}'
            f'</div></div>')


def text_tile(r):
    """No photo — tinted background to distinguish from photo tiles."""
    text   = trunc_linked(clean_message(r["message"]), r["post_id"])
    prefix = wrote_prefix(r)
    return (f'<div class="tile tile-text-only">'
            f'{_header(r)}'
            f'{"<div class=tile-text>" + prefix + text + "</div>" if text else ""}'
            f'</div>')


def render_tile(tile) -> str:
    r     = tile["record"]
    photo = tile["photo"]
    wc    = tile["wc"]
    if not photo:
        return text_tile(r)
    return portrait_tile(r, photo, wc)


# ── COLUMN LAYOUT ─────────────────────────────────────────────────────────────

_COL_W_2 = (PAGE_W - 2*PAGE_MARGIN - TILE_GAP) / 2        # 2-col tile width (in)
_COL_W_3 = (PAGE_W - 2*PAGE_MARGIN - 2*TILE_GAP) / 3     # 3-col tile width (in)
_PX_PER_IN = 96.0                                          # CSS pixels per inch


def natural_tile_height(tile: dict, col_w: float) -> float:
    """Return tile height at col_w in inches.

    Uses browser-measured heights (tile['h2col'] / tile['h3col']) when available;
    falls back to the text-line estimation only before the measurement pass runs.
    """
    if "h2col" in tile:
        # Pick the pre-measured height for whichever standard column width is closer
        if abs(col_w - _COL_W_2) <= abs(col_w - _COL_W_3):
            return tile["h2col"]
        return tile["h3col"]

    # Estimation fallback (used only before measurement pass)
    photo = tile["photo"]
    wc    = min(tile["wc"], MAX_WORDS)
    wpl   = max(3, col_w / WPL_COL)
    text_lines = math.ceil(max(1, wc) / wpl)
    text_h = text_lines * TILE_LINE_H + TILE_HEADER_H + TILE_PAD_H
    if not photo:
        return min(MAX_TILE_NAT_H, max(text_h, MIN_DIM))
    ar = tile.get("aspect_ratio", 1.0)
    photo_h = max(col_w / ar, MIN_DIM)
    return min(MAX_TILE_NAT_H, photo_h + text_h)


def measure_tile_heights(tiles: list) -> None:
    """Measure actual rendered heights via headless Playwright.

    Renders every tile at both standard column widths in a hidden Chromium page,
    reads each div's getBoundingClientRect().height, and stores the results on
    the tile dicts as tile['h2col'] and tile['h3col'] (in inches).

    Results are cached in .tile_heights_cache.json keyed by a hash of the
    rendered HTML so unchanged tiles are not remeasured on subsequent runs.
    """
    _HERE_LOCAL = os.path.dirname(os.path.abspath(__file__))
    CACHE_PATH  = os.path.join(_HERE_LOCAL, ".tile_heights_cache.json")
    PW_DIR_MH   = "/private/tmp/pw_pdf"
    MH_SCRIPT   = os.path.join(PW_DIR_MH, "measure_tiles.mjs")
    HTML_TMP    = "/tmp/samstones_measure.html"
    JSON_TMP    = "/tmp/samstones_heights.json"

    def _tile_hash(tile: dict) -> str:
        return hashlib.md5(render_tile(tile).encode()).hexdigest()[:16]

    # Load cache
    cache: dict = {}
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH) as f:
                cache = json.load(f)
        except Exception:
            pass

    hashes    = [_tile_hash(t) for t in tiles]
    uncached  = [(i, tiles[i], hashes[i]) for i in range(len(tiles))
                 if hashes[i] not in cache]

    if uncached:
        print(f"  Measuring {len(uncached)} tile heights via Playwright…", flush=True)

        # Build a flat HTML page: each tile rendered twice (at 2-col and 3-col width)
        items = []
        for local_i, (_, tile, _) in enumerate(uncached):
            html = render_tile(tile)
            items.append(
                f'<div data-id2="{local_i}" '
                f'style="width:{_COL_W_2}in;display:block;overflow:hidden;">'
                f'{html}</div>'
            )
            items.append(
                f'<div data-id3="{local_i}" '
                f'style="width:{_COL_W_3}in;display:block;overflow:hidden;">'
                f'{html}</div>'
            )

        full_html = (
            f'<!DOCTYPE html><html><head><meta charset="UTF-8">'
            f'<style>{CSS}</style></head>'
            f'<body style="margin:0;padding:0;background:white;">'
            f'{"".join(items)}'
            f'</body></html>'
        )
        with open(HTML_TMP, "w") as f:
            f.write(full_html)

        base_url = f"file://{_HERE_LOCAL}/"
        result = subprocess.run(
            ["node", MH_SCRIPT,
             "--html", HTML_TMP,
             "--base", base_url,
             "--out",  JSON_TMP],
            cwd=PW_DIR_MH, timeout=180,
            capture_output=True, text=True,
        )

        if result.returncode != 0:
            print(f"  Warning: height measurement failed — using estimates.\n"
                  f"  {result.stderr[:300]}", flush=True)
            for tile in tiles:
                tile.setdefault("h2col", natural_tile_height(tile, _COL_W_2))
                tile.setdefault("h3col", natural_tile_height(tile, _COL_W_3))
            return

        raw: dict = {}
        try:
            with open(JSON_TMP) as f:
                raw = json.load(f)
        except Exception as e:
            print(f"  Warning: could not read heights JSON: {e}", flush=True)

        for local_i, (_, tile, h) in enumerate(uncached):
            h2px = raw.get(f"{local_i}_2", natural_tile_height(tile, _COL_W_2) * _PX_PER_IN)
            h3px = raw.get(f"{local_i}_3", natural_tile_height(tile, _COL_W_3) * _PX_PER_IN)
            cache[h] = [h2px / _PX_PER_IN, h3px / _PX_PER_IN]

        with open(CACHE_PATH, "w") as f:
            json.dump(cache, f)
        print(f"    done ({result.stdout.strip()})", flush=True)

    # Apply cached heights to all tiles
    for tile, h in zip(tiles, hashes):
        cached = cache[h]
        tile["h2col"] = cached[0]
        tile["h3col"] = cached[1]


def assign_to_cols(tiles: list, n_cols: int, col_w: float) -> list:
    """Greedy shortest-column assignment. Tiles at natural height; no stretching."""
    cols  = [[] for _ in range(n_cols)]
    col_h = [0.0] * n_cols
    avail_h = PAGE_H - 2 * PAGE_MARGIN
    for tile in tiles:
        i = min(range(n_cols), key=lambda j: col_h[j])
        nat_h = natural_tile_height(tile, col_w)
        cols[i].append((tile, nat_h))
        col_h[i] += nat_h
        if col_h[i] >= avail_h * 0.95:
            col_h[i] = PAGE_H * 10   # column is full — redirect remaining tiles
    return cols


# ── PAGE BUILDERS ─────────────────────────────────────────────────────────────

def year_opener_page(year, records, map_b64, conn):
    placed = sum(1 for r in records if r["category"] and "Placed" in r["category"])
    found  = sum(1 for r in records if r["category"] and "Found"  in r["category"])

    # Request stats from the requests table (if it exists)
    req_html = ""
    try:
        req_row = conn.execute(
            "SELECT COUNT(*), SUM(COALESCE(stones,0)) FROM requests WHERE year=? AND is_spam=0",
            (year,)
        ).fetchone()
        req_count, stones_sent = req_row if req_row else (0, 0)
        req_countries = sorted({row[0] for row in conn.execute(
            "SELECT DISTINCT country FROM requests WHERE year=? AND is_spam=0 AND country!=''",
            (year,)
        ) if row[0]})
        if req_count:
            stones_sent = stones_sent or 0
            n_c = len(req_countries)
            req_html = (f'<span class="sep">·</span>'
                        f'<span class="requested">'
                        f'{req_count} requests · {stones_sent} stones sent'
                        f'{f" · {n_c} countries" if n_c else ""}'
                        f'</span>')
            if req_countries:
                country_list = ", ".join(req_countries)
                req_html += (f'<div class="req-countries">'
                             f'Requests from: {country_list}</div>')
    except Exception:
        pass   # requests table may not exist

    return (f'<div class="page year-opener">'
            f'<div class="year-title">{year}</div>'
            f'<img class="year-map" src="data:image/png;base64,{map_b64}" alt="">'
            f'<div class="year-stats">'
            f'<span class="stat">{len(records)} SamStones</span>'
            f'<span class="sep">·</span>'
            f'<span class="placed">{placed} placed</span>'
            f'<span class="sep">·</span>'
            f'<span class="found">{found} found</span>'
            f'{req_html}'
            f'</div></div>')


def render_content_page(page_tiles: list) -> str:
    """Flexbox column layout: tiles at natural height, 3 cols for 6+ tiles."""
    n_cols = 3 if len(page_tiles) >= 6 else 2
    col_w  = (PAGE_W - 2*PAGE_MARGIN - (n_cols - 1)*TILE_GAP) / n_cols
    cols   = assign_to_cols(page_tiles, n_cols, col_w)

    col_divs = []
    for col_tiles in cols:
        tile_html = "".join(render_tile(tile) for tile, _ in col_tiles)
        col_divs.append(f'<div class="col">{tile_html}</div>')

    return (f'<div class="page">'
            f'<div class="col-container">{"".join(col_divs)}</div>'
            f'</div>')


# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: Georgia, "Times New Roman", serif; background: #888; }
@page { size: letter; margin: 0.4in; }

.page {
  width: 7.5in; height: 10in;
  margin: 0.15in auto;
  background: white; overflow: hidden;
  page-break-after: always; break-after: page;
  box-shadow: 0 2px 8px rgba(0,0,0,.20);
}

/* ── Column container (flexbox row of columns) ── */
.col-container {
  display: flex;
  flex-direction: row;
  gap: 0.07in;
  padding: 0.10in;
  height: 100%;
}

/* Each column: flex column, tiles stack vertically */
.col {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.07in;
  overflow: hidden;
  min-width: 0;
}

/* ── Year opener ── */
.year-opener {
  display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 0.2in;
  background: #fafaf8;
}
.year-title { font-size: 72pt; font-weight: bold; color: #1a252f;
              letter-spacing: -2px; line-height: 1; }
.year-map   { width: 100%; border: 1px solid #ddd; border-radius: 3px; }
.year-stats { font-size: 12pt; color: #666; }
.sep    { margin: 0 0.1in; color: #ccc; }
.placed        { color: #27ae60; font-weight: bold; }
.found         { color: #2980b9; font-weight: bold; }
.requested     { color: #8e44ad; font-weight: bold; }
.req-countries { font-size: 9pt; color: #8e44ad; font-style: italic; margin-top: 0.05in; }

/* ── All tiles ── */
.tile {
  overflow: hidden;
  border: 1px solid #b0b0b0;
  border-radius: 2px;
  background: white;
  break-inside: avoid; page-break-inside: avoid;
}

/* Portrait: tile at natural height; photo at natural aspect ratio; no gray space */
.tile-portrait                   { flex: 0 0 auto; min-height: 1.5in;
                                   display: flex; flex-direction: column; }
.tile-portrait .tile-photo-top   { flex: 0 0 auto; }
.tile-portrait .tile-caption     { flex: 0 0 auto; padding: 0.05in 0.07in; }

/* Landscape: photo left at natural height; text fills remaining width */
.tile-landscape                  { flex: 0 0 auto; min-height: 1.5in;
                                   display: flex; flex-direction: row; }
.tile-landscape .tile-photo-left { flex: 0 0 38%; }
.tile-landscape .tile-content    { flex: 1; padding: 0.07in 0.08in; overflow: hidden;
                                   display: flex; flex-direction: column;
                                   justify-content: center; }

/* Text-only: shrinks to exact content height — no white space padding */
.tile-text-only { flex: 0 0 auto; padding: 0.08in 0.10in; background: #f9f8f6; }

/* Cover photo — natural aspect ratio, no cropping, no empty space */
.tile-img { width: 100%; height: auto; display: block; }

/* Typography */
.tile-loc  { font-size: 9pt; font-weight: bold; color: #1a252f; line-height: 1.25; }
.tile-meta { font-size: 6.5pt; color: #aaa; margin: 2px 0 4px; }
.tile-text { font-size: 8pt; color: #444; line-height: 1.38; }
.read-more { font-size: 7pt; color: #2980b9; white-space: nowrap; }
.wrote     { font-style: italic; color: #999; }
.badge {
  display: inline-block; color: white; font-size: 5.5pt;
  font-family: sans-serif; padding: 1px 4px; border-radius: 2px;
  vertical-align: middle; margin-left: 3px;
}
"""


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    ensure_geojson()
    conn = sqlite3.connect(DB_PATH)

    rows = conn.execute("""
        SELECT post_id, title, date_parsed, category, name, message,
               image_urls, photo_links, latitude, longitude
        FROM samstones
        WHERE substr(date_parsed,1,4) = ?
        ORDER BY date_parsed
    """, (str(YEAR),)).fetchall()
    cols = ("post_id","title","date_parsed","category","name","message",
            "image_urls","photo_links","latitude","longitude")
    records = [dict(zip(cols, r)) for r in rows]
    print(f"\nYear {YEAR}: {len(records)} records")

    print("  Resolving photos & building tiles…")
    tiles = build_tiles(records)
    photo_count = sum(1 for t in tiles if t["photo"])
    weight_dist = {"large":0,"medium":0,"small":0,"chip":0,"tiny":0}
    for t in tiles:
        w = t["weight"]
        if   w >= W_LARGE:   weight_dist["large"]  += 1
        elif w >= W_MEDIUM:  weight_dist["medium"] += 1
        elif w >= W_SMALL:   weight_dist["small"]  += 1
        elif w >= W_CHIP:    weight_dist["chip"]   += 1
        else:                weight_dist["tiny"]   += 1
    print(f"  Photos: {photo_count}/{len(tiles)}  "
          f"Weights: {weight_dist}")

    measure_tile_heights(tiles)

    lats = [r["latitude"]  for r in records if r["latitude"]  is not None]
    lons = [r["longitude"] for r in records if r["longitude"] is not None]
    print("  Generating map…")
    map_b64 = make_year_map_b64(lats, lons)

    pages = refill_pages(group_into_pages(tiles))
    print(f"  {len(pages)} content pages  ({len(tiles)} tiles, "
          f"avg {len(tiles)/len(pages):.1f}/page)")

    body = "\n".join([
        year_opener_page(YEAR, records, map_b64, conn),
        "\n".join(render_content_page(pg) for pg in pages),
    ])

    html = (f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8">\n'
            f'<title>SamStones {YEAR}</title>\n'
            f'<style>{CSS}</style></head>\n<body>{body}</body></html>')

    with open(OUT_FILE, "w") as f:
        f.write(html)
    print(f"Written → {OUT_FILE}")
    conn.close()


if __name__ == "__main__":
    main()
