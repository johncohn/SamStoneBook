#!/usr/bin/env python3
"""
Scrape all SamStone placement/found records from samstones.org into SQLite.

Three content formats exist:
  1. Freeform HTML paragraphs (most posts, all eras)
  2. Structured "Name = / Email = / Message = " paragraphs (mid-era form submissions)
  3. WPForms entry view — admin-bar + wpforms-entry-field-* divs (newer form submissions)

All three are stored as raw content_html (after stripping admin noise), plus
parsed name/email/message/image_urls fields for easy access.
"""

import re
import json
import sqlite3
import time
import ssl
import urllib.request
from datetime import datetime
from html import unescape

BASE_URL = "http://samstones.org/WordPress1"
TOC_URL  = f"{BASE_URL}/?page_id=44"
DB_PATH  = "samstones.db"
DELAY    = 0.3  # seconds between requests


# ── HTTP ──────────────────────────────────────────────────────────────────────

def fetch(url: str) -> str:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "SamStones-Archiver/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ── TOC ───────────────────────────────────────────────────────────────────────

def get_post_ids(html: str) -> list[tuple[int, str]]:
    pattern = r'<li><a href="[^"]*\?p=(\d+)">(.*?)</a></li>'
    results = []
    for m in re.finditer(pattern, html):
        pid   = int(m.group(1))
        title = unescape(m.group(2)).strip()
        results.append((pid, title))
    return results


# ── CONTENT EXTRACTION ────────────────────────────────────────────────────────

def strip_noise_divs(html: str) -> str:
    """Remove WordPress admin-bar and WPForms-header divs from HTML."""
    noise_ids = ("wpadminbar", "wpforms-header-temp", "wpforms-header")
    for div_id in noise_ids:
        marker = f'<div id="{div_id}"'
        start  = html.find(marker)
        if start == -1:
            continue
        # Walk forward counting div depth to find the matching close
        depth = 0
        i = start
        while i < len(html):
            if html[i:i+4] == "<div":
                depth += 1
            elif html[i:i+6] == "</div>":
                depth -= 1
                if depth == 0:
                    html = html[:start] + html[i+6:]
                    break
            i += 1
    return html


def extract_post_content(html: str) -> str:
    """
    Return the inner HTML of the post content div, with admin noise stripped.
    The content div is the first bare <div> inside <div class="post">.
    """
    start = html.find('<div class="post"')
    if start == -1:
        return ""
    content_start = html.find("<div>", start)
    if content_start == -1:
        return ""
    # End at postinfo paragraph, gm-post div, or comments section
    end = -1
    for marker in ['<p class="postinfo">', '<div id="gm-post">', 'id="comments"']:
        pos = html.find(marker, content_start)
        if pos != -1 and (end == -1 or pos < end):
            end = pos
    if end == -1:
        end = content_start + 8000
    raw = html[content_start:end]
    return strip_noise_divs(raw).strip()


def extract_images(html: str, content: str) -> list[str]:
    """Collect image URLs from both <img src> tags and bare https?:// image links."""
    urls = []
    # Directly embedded images (skip gravatar)
    for src in re.findall(r'<img[^>]+src="([^"]+)"', content):
        if "gravatar.com" not in src:
            urls.append(src)
    # Links to external images or photo services
    for href in re.findall(r'href="(https?://[^"]+)"', content):
        if any(ext in href.lower() for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
            if href not in urls:
                urls.append(href)
    # Any bare URLs in text that look like images
    for url in re.findall(r'https?://\S+\.(?:jpg|jpeg|png|gif|webp)\b', content, re.IGNORECASE):
        url = url.rstrip(")")
        if url not in urls:
            urls.append(url)
    return urls


def extract_photo_links(content: str) -> list[str]:
    """
    Collect any links in the content that are likely photo or sharing URLs
    (e.g. kommodo.ai, flickr, google photos, dropbox image links).
    These are image links that aren't direct image files.
    """
    photo_domains = ("flickr.com", "photos.app.goo", "drive.google", "dropbox.com",
                     "icloud.com", "kommodo.ai", "imgur.com", "500px.com",
                     "smugmug.com", "photobucket.com")
    links = []
    for href in re.findall(r'href="(https?://[^"]+)"', content):
        if any(d in href for d in photo_domains):
            links.append(href)
    return links


def extract_wpforms_fields(content: str) -> dict:
    """Parse WPForms entry field name/value pairs from the content HTML."""
    fields = {}
    pattern = (r'<p class="wpforms-entry-field-name">(.*?)</p>\s*'
               r'<div class="wpforms-entry-field-value">(.*?)</div>')
    for m in re.finditer(pattern, content, re.DOTALL):
        field_name = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        field_val  = re.sub(r'<[^>]+>', ' ', m.group(2))
        field_val  = unescape(re.sub(r'\s+', ' ', field_val)).strip()
        fields[field_name] = field_val
    return fields


def extract_structured_fields(content: str) -> tuple[str, str, str]:
    """Extract Name, Email, Message from mid-era "Name = ..." style posts."""
    text = unescape(re.sub(r'<[^>]+>', ' ', content))

    name = email = message = ""

    nm = re.search(r'Name\s*=\s*(.+?)(?:\s{2,}|Email\s*=|$)', text, re.IGNORECASE)
    if nm:
        name = nm.group(1).strip()

    em = re.search(r'Email\s*=\s*(.+?)(?:\s{2,}|File\s*|Message\s*=|$)', text, re.IGNORECASE)
    if em:
        email = em.group(1).strip()

    mm = re.search(r'Message\s*=\s*(.*)', text, re.IGNORECASE | re.DOTALL)
    if mm:
        message = mm.group(1).strip()

    return name, email, message


def extract_fields(content: str) -> tuple[str, str, str]:
    """
    Detect content format and extract (name, email, message).
    Returns plain-text message (newlines preserved, HTML stripped).
    """
    # WPForms format
    if "wpforms-entry-field-name" in content:
        fields = extract_wpforms_fields(content)
        name  = fields.get("Name", "")
        email = fields.get("Email", "")
        # Try several possible field names for the message
        for key in fields:
            if "more" in key.lower() or "tell" in key.lower() or "story" in key.lower():
                message = fields[key]
                break
        else:
            message = " | ".join(f"{k}: {v}" for k, v in fields.items()
                                  if k.lower() not in ("name", "email"))
        return name, email, message

    # Structured "Name = / Email = / Message =" format
    text = unescape(re.sub(r'<[^>]+>', ' ', content))
    if re.search(r'(?:^|\s)Name\s*=', text, re.IGNORECASE | re.MULTILINE):
        return extract_structured_fields(content)

    # Freeform — use all text as message, strip HTML noise
    text = re.sub(r'<[^>]+>', ' ', content)
    text = unescape(re.sub(r'\s+', ' ', text)).strip()
    text = re.sub(r'File attached\s*=\s*\S+', '', text)
    return "", "", text.strip()


# ── PAGE-LEVEL EXTRACTION ─────────────────────────────────────────────────────

def extract_geo(html: str) -> tuple[float | None, float | None]:
    m = re.search(r'geo\.position[^>]*content="([^"]+)"', html)
    if m:
        parts = m.group(1).split(";")
        if len(parts) == 2:
            try:
                return float(parts[0]), float(parts[1])
            except ValueError:
                pass
    return None, None


def extract_title(html: str, fallback: str) -> str:
    m = re.search(r'<div class="post".*?<h2><a[^>]*>(.*?)</a></h2>', html, re.DOTALL)
    return unescape(m.group(1)).strip() if m else fallback


def extract_date(html: str) -> str | None:
    m = re.search(r'Published\s+([\w]+ \d+, \d{4})', html)
    return m.group(1) if m else None


def parse_date(date_text: str | None) -> str | None:
    if not date_text:
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(date_text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def extract_category(html: str) -> str | None:
    m = re.search(r'rel="category">(.*?)</a>', html)
    return unescape(m.group(1)).strip() if m else None


# ── DATABASE ──────────────────────────────────────────────────────────────────

def setup_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS samstones (
            post_id      INTEGER PRIMARY KEY,
            title        TEXT,
            date_text    TEXT,
            date_parsed  TEXT,
            category     TEXT,
            name         TEXT,
            email        TEXT,
            message      TEXT,
            content_html TEXT,
            image_urls   TEXT,
            photo_links  TEXT,
            latitude     REAL,
            longitude    REAL,
            scraped_at   TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON samstones(date_parsed)")
    conn.commit()


# ── SCRAPE ONE POST ────────────────────────────────────────────────────────────

def scrape_post(post_id: int, toc_title: str) -> dict:
    url  = f"{BASE_URL}/?p={post_id}"
    html = fetch(url)

    title    = extract_title(html, toc_title)
    lat, lon = extract_geo(html)
    content  = extract_post_content(html)
    images   = extract_images(html, content)
    photos   = extract_photo_links(content)
    date_txt = extract_date(html)
    category = extract_category(html)
    name, email, message = extract_fields(content)

    return {
        "post_id":      post_id,
        "title":        title,
        "date_text":    date_txt,
        "date_parsed":  parse_date(date_txt),
        "category":     category,
        "name":         name,
        "email":        email,
        "message":      message,
        "content_html": content,
        "image_urls":   json.dumps(images),
        "photo_links":  json.dumps(photos),
        "latitude":     lat,
        "longitude":    lon,
        "scraped_at":   datetime.now().isoformat(),
    }


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("Fetching table of contents…")
    toc_html  = fetch(TOC_URL)
    post_list = get_post_ids(toc_html)
    print(f"Found {len(post_list)} posts in TOC")

    conn = sqlite3.connect(DB_PATH)
    setup_db(conn)

    already_done = {row[0] for row in conn.execute("SELECT post_id FROM samstones")}
    todo = [(pid, t) for pid, t in post_list if pid not in already_done]
    print(f"Already scraped: {len(already_done)}   Remaining: {len(todo)}")

    errors = []
    for i, (pid, toc_title) in enumerate(todo):
        try:
            record = scrape_post(pid, toc_title)
            conn.execute("""
                INSERT OR REPLACE INTO samstones
                (post_id, title, date_text, date_parsed, category, name, email,
                 message, content_html, image_urls, photo_links, latitude, longitude, scraped_at)
                VALUES
                (:post_id, :title, :date_text, :date_parsed, :category, :name, :email,
                 :message, :content_html, :image_urls, :photo_links, :latitude, :longitude, :scraped_at)
            """, record)
            conn.commit()

            if (i + 1) % 100 == 0 or i < 5:
                pct = (i + 1) / len(todo) * 100
                print(f"  [{i+1:4d}/{len(todo)}] {pct:4.0f}%  p={pid}: {toc_title[:50]}")

        except Exception as e:
            errors.append((pid, str(e)))
            print(f"  ERROR p={pid}: {e}")

        time.sleep(DELAY)

    total = conn.execute("SELECT COUNT(*) FROM samstones").fetchone()[0]
    print(f"\nDone! {total} records in {DB_PATH}")

    if errors:
        print(f"\n{len(errors)} errors:")
        for pid, msg in errors[:10]:
            print(f"  p={pid}: {msg}")

    print("\nSample (oldest → newest):")
    for row in conn.execute("""
        SELECT post_id, title, date_parsed, category, latitude, longitude, name
        FROM samstones ORDER BY date_parsed NULLS LAST LIMIT 5
    """):
        print(f"  p={row[0]}  {row[2]}  {row[3]}  ({row[4]},{row[5]})  {row[6] or '—'}  {row[1][:45]}")

    conn.close()


if __name__ == "__main__":
    main()
