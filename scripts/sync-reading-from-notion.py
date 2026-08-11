#!/usr/bin/env python3
"""Sync finished Readwise Library books from Notion into static/data/reading.json.

Only books tagged "finished" are included. Completion month/year comes from the
other Document Tag (e.g. "Jul 26", "2026-07"). Cover images are mirrored and
resized into static/img/reading-covers/ for fast local serving.

Requires:
  NOTION_TOKEN  Integration token with access to the Readwise Library database

Usage:
  NOTION_TOKEN=ntn_... python3 scripts/sync-reading-from-notion.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "static" / "data" / "reading.json"

# Readwise → Notion "Library" database
DATABASE_ID = "55c71ce9e38c83428bfb816dc1c66604"
NOTION_VERSION = "2022-06-28"
FINISHED_TAG = "finished"

MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def notion_request(url: str, token: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST" if payload is not None else "GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def plain_text(rich) -> str:
    if not rich:
        return ""
    if isinstance(rich, list):
        return "".join(part.get("plain_text", "") for part in rich).strip()
    return str(rich).strip()


def extract_tags(prop: dict | None) -> list[str]:
    if not prop or prop.get("type") != "multi_select":
        return []
    return [item.get("name", "").strip() for item in (prop.get("multi_select") or []) if item.get("name")]


def parse_completion_date(tags: list[str]) -> str | None:
    """Parse a month/year completion tag into YYYY-MM-01."""
    for raw in tags:
        tag = raw.strip()
        if not tag or tag.casefold() == FINISHED_TAG:
            continue

        # 2026-07 or 2026-07-28
        m = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", tag)
        if m:
            year, month = int(m.group(1)), int(m.group(2))
            if 1 <= month <= 12:
                return f"{year:04d}-{month:02d}-01"

        # 07/2026 or 7-2026
        m = re.fullmatch(r"(\d{1,2})[/-](\d{4})", tag)
        if m:
            month, year = int(m.group(1)), int(m.group(2))
            if 1 <= month <= 12:
                return f"{year:04d}-{month:02d}-01"

        # Jul 26 / July 2026 / Jul '26
        m = re.fullmatch(r"([A-Za-z]+)\.?\s+'?(\d{2}|\d{4})", tag)
        if m:
            month = MONTHS.get(m.group(1).casefold())
            year_raw = m.group(2)
            if month:
                year = int(year_raw)
                if year < 100:
                    year += 2000
                return f"{year:04d}-{month:02d}-01"

        # july26 / Jul26 / july2026 (no space)
        m = re.fullmatch(r"([A-Za-z]+)'?(\d{2}|\d{4})", tag)
        if m:
            month = MONTHS.get(m.group(1).casefold())
            year_raw = m.group(2)
            if month:
                year = int(year_raw)
                if year < 100:
                    year += 2000
                return f"{year:04d}-{month:02d}-01"

    return None


def fetch_books(token: str) -> list[dict]:
    books: list[dict] = []
    skipped_no_date = 0
    cursor = None
    while True:
        payload = {
            "filter": {
                "and": [
                    {"property": "Category", "select": {"equals": "Books"}},
                    {
                        "property": "Document Tags",
                        "multi_select": {"contains": FINISHED_TAG},
                    },
                ]
            },
            "page_size": 100,
        }
        if cursor:
            payload["start_cursor"] = cursor

        page = notion_request(
            f"https://api.notion.com/v1/databases/{DATABASE_ID}/query",
            token,
            payload,
        )

        for row in page.get("results", []):
            props = row.get("properties", {})
            title = plain_text(props.get("Title", {}).get("title"))
            author = plain_text(props.get("Author", {}).get("rich_text"))
            highlights = props.get("Highlights", {}).get("number")
            tags = extract_tags(props.get("Document Tags"))
            completed = parse_completion_date(tags)
            if not title:
                continue
            if not completed:
                skipped_no_date += 1
                continue

            cover = None
            icon = row.get("icon") or {}
            if icon.get("type") == "external":
                cover = (icon.get("external") or {}).get("url")
            elif icon.get("type") == "file":
                cover = (icon.get("file") or {}).get("url")

            if title.startswith("The Subtle Art of Not Giving a F*ck"):
                title = "The Subtle Art of Not Giving a F*ck"

            books.append(
                {
                    "title": title,
                    "author": author,
                    "date": completed,
                    "highlights": highlights if highlights is not None else 0,
                    "cover": cover,
                    "tags": tags,
                }
            )

        if not page.get("has_more"):
            break
        cursor = page.get("next_cursor")

    books.sort(key=lambda book: book["date"])
    return books, skipped_no_date


def main() -> int:
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        print("Set NOTION_TOKEN to a Notion integration token.", file=sys.stderr)
        return 1

    try:
        books, skipped_no_date = fetch_books(token)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"Notion API error {exc.code}: {body}", file=sys.stderr)
        return 1

    payload = {
        "source": "notion-readwise-library",
        "databaseId": "55c71ce9-e38c-8342-8bfb-816dc1c66604",
        "syncedAt": date.today().isoformat(),
        "dateField": "Document Tags (month/year tag)",
        "filter": 'Document Tags contains "finished"',
        "books": books,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(books)} finished books to {OUT.relative_to(ROOT)}")
    if skipped_no_date:
        print(
            f"Skipped {skipped_no_date} finished book(s) missing a month/year tag.",
            file=sys.stderr,
        )

    # Mirror/resize covers locally so the homepage does not fetch huge remote images.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mirror_reading_covers import mirror_payload

    mirrored, failed = mirror_payload(payload)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Mirrored {mirrored} cover image(s) for local serving")
    if failed:
        print(f"{failed} cover(s) could not be mirrored.", file=sys.stderr)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
