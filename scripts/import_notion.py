#!/usr/bin/env python3
"""Import a Notion board CSV export into MediaMaster.

Usage:
    python import_notion.py export.csv --api-url https://... --token mm_... [--dry-run]

Column and status names are matched case-insensitively against the maps below;
tweak them if your Notion properties are named differently. Always run with
--dry-run first and eyeball the output.
"""

import argparse
import csv
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Notion column header -> our field (casefolded matching)
COLUMN_MAP = {
    "name": "name",
    "title": "name",
    "show": "name",
    "status": "status",
    "type": "show_type",
    "kind": "show_type",
    "format": "show_type",
    "streaming service": "service",
    "service": "service",
    "where": "service",
    "platform": "service",
    "recommended by": "source",
    "recommendation": "source",
    "source": "source",
    "rec": "source",
    "who": "source",
    "rating": "rating",
    "stars": "rating",
    "created time": "created_at",
    "created": "created_at",
    "date added": "created_at",
}

# Notion status value -> board column
STATUS_MAP = {
    "to watch": "to_watch",
    "to-watch": "to_watch",
    "towatch": "to_watch",
    "watchlist": "to_watch",
    "not started": "to_watch",
    "watching": "watching",
    "in progress": "watching",
    "done": "done",
    "watched": "done",
    "finished": "done",
    "complete": "done",
    "la poubelle": "poubelle",
    "poubelle": "poubelle",
    "trash": "poubelle",
    "abandoned": "poubelle",
}

TYPE_MAP = {
    "tv": "tv",
    "tv show": "tv",
    "show": "tv",
    "series": "tv",
    "tv series": "tv",
    "movie": "movie",
    "film": "movie",
}


def norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").strip().casefold()


def parse_rating(raw: str) -> int | None:
    raw = norm(raw)
    if not raw:
        return None
    stars = raw.count("⭐") + raw.count("★")
    if stars:
        return min(stars, 3)
    m = re.search(r"[123]", raw)
    return int(m.group()) if m else None


def parse_created(raw: str) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    # Notion exports e.g. "May 3, 2024 1:22 PM" or ISO-ish strings
    for fmt in ("%B %d, %Y %I:%M %p", "%B %d, %Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw).astimezone(timezone.utc).isoformat()
    except ValueError:
        print(f"  ! unparseable date {raw!r} — leaving created_at to the server", file=sys.stderr)
        return None


def dedup_key(name: str) -> str:
    n = norm(name)
    n = re.sub(r"\s*\((19|20)\d\d\)\s*$", "", n)  # strip trailing "(2023)"
    return re.sub(r"\s+", " ", n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", type=Path)
    ap.add_argument("--api-url", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--default-type", choices=["tv", "movie"], default="tv")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with args.csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        mapping = {}
        for h in headers:
            field = COLUMN_MAP.get(norm(h))
            if field and field not in mapping.values():
                mapping[h] = field
        print(f"Column mapping: { {h: f for h, f in mapping.items()} }")
        unmapped = [h for h in headers if h not in mapping]
        if unmapped:
            print(f"Ignoring columns: {unmapped}")
        if "name" not in mapping.values():
            print("ERROR: no Name column found — adjust COLUMN_MAP", file=sys.stderr)
            return 1
        rows = list(reader)

    client = httpx.Client(
        base_url=args.api_url.rstrip("/"),
        headers={"Authorization": f"Bearer {args.token}"},
        timeout=60,
    )

    resp = client.get("/api/board")
    resp.raise_for_status()
    existing = {
        dedup_key(s["name"])
        for col in resp.json()["columns"].values()
        for s in col
    }
    print(f"Board currently has {len(existing)} shows")

    shows, skipped, warned = [], [], 0
    for row in rows:
        rec: dict = {}
        for header, field in mapping.items():
            rec[field] = (row.get(header) or "").strip()
        name = rec.get("name", "")
        if not name:
            continue
        if dedup_key(name) in existing:
            skipped.append(name)
            continue

        status_raw = norm(rec.get("status", ""))
        status = STATUS_MAP.get(status_raw)
        if status is None:
            if status_raw:
                print(f"  ! unknown status {rec['status']!r} for {name!r} -> to_watch", file=sys.stderr)
                warned += 1
            status = "to_watch"

        type_raw = norm(rec.get("show_type", ""))
        show_type = TYPE_MAP.get(type_raw)
        if show_type is None:
            if type_raw:
                print(f"  ! unknown type {rec['show_type']!r} for {name!r} -> {args.default_type}", file=sys.stderr)
                warned += 1
            show_type = args.default_type

        show = {
            "name": name,
            "show_type": show_type,
            "service": rec.get("service") or None,
            "source": rec.get("source") or None,
            "status": status,
            "rating": parse_rating(rec.get("rating", "")) if status == "done" else None,
            "created_at": parse_created(rec.get("created_at", "")),
        }
        existing.add(dedup_key(name))
        shows.append(show)

    print(f"\n{len(shows)} to import, {len(skipped)} duplicates skipped, {warned} warnings")
    if skipped:
        print(f"Skipped: {', '.join(skipped[:15])}{'…' if len(skipped) > 15 else ''}")

    from collections import Counter

    print("By column:", dict(Counter(s["status"] for s in shows)))

    if args.dry_run:
        print("\n--dry-run: first 10 mapped rows:")
        for s in shows[:10]:
            print(json.dumps(s, ensure_ascii=False))
        return 0

    created = 0
    for i in range(0, len(shows), 100):
        chunk = shows[i : i + 100]
        resp = client.post("/api/shows/bulk", json={"shows": chunk})
        resp.raise_for_status()
        created += resp.json()["created"]
        print(f"  imported {created}/{len(shows)}")

    print(f"Done — {created} shows imported.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
