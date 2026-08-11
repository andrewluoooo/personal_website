#!/usr/bin/env python3
"""Download and resize reading-chart cover images into static/img/reading-covers/.

Replaces remote Readwise/S3 cover URLs in static/data/reading.json with local
paths so first paint does not wait on huge cross-origin originals.

Usage:
  python3 scripts/mirror-reading-covers.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
READING_JSON = ROOT / "static" / "data" / "reading.json"
COVER_DIR = ROOT / "static" / "img" / "reading-covers"
# 70px CSS width × ~3 for retina, with a little headroom
MAX_WIDTH = 210
WEBP_QUALITY = 72


def slugify(title: str, url: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (title or "book").casefold()).strip("-")
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return f"{base[:48] or 'book'}-{digest}"


def is_remote(url: str | None) -> bool:
    return bool(url) and url.startswith(("http://", "https://"))


def optimize_cover(url: str, title: str) -> str | None:
    slug = slugify(title, url)
    out = COVER_DIR / f"{slug}.webp"
    if out.exists() and out.stat().st_size > 0:
        return f"/img/reading-covers/{out.name}"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "personal-website-reading-cover-mirror/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()

    with Image.open(BytesIO(raw)) as img:
        img = img.convert("RGB")
        if img.width > MAX_WIDTH:
            ratio = MAX_WIDTH / float(img.width)
            img = img.resize(
                (MAX_WIDTH, max(1, int(img.height * ratio))),
                Image.Resampling.LANCZOS,
            )
        COVER_DIR.mkdir(parents=True, exist_ok=True)
        img.save(out, format="WEBP", quality=WEBP_QUALITY, method=6)

    return f"/img/reading-covers/{out.name}"


def mirror_payload(payload: dict) -> tuple[int, int]:
    mirrored = 0
    failed = 0
    for book in payload.get("books") or []:
        cover = book.get("cover")
        if not is_remote(cover):
            continue
        try:
            local = optimize_cover(cover, book.get("title") or "book")
            if local:
                book["cover"] = local
                book["coverRemote"] = cover
                mirrored += 1
        except (urllib.error.URLError, OSError, ValueError) as exc:
            failed += 1
            print(f"Failed to mirror cover for {book.get('title')!r}: {exc}", file=sys.stderr)
    return mirrored, failed


def main() -> int:
    if not READING_JSON.exists():
        print(f"Missing {READING_JSON}", file=sys.stderr)
        return 1

    payload = json.loads(READING_JSON.read_text(encoding="utf-8"))
    mirrored, failed = mirror_payload(payload)
    READING_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Mirrored {mirrored} cover(s) into {COVER_DIR.relative_to(ROOT)}")
    if failed:
        print(f"{failed} cover(s) failed; left remote URLs in place.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
