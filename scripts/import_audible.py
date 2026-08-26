"""Import scraped Audible library rows into the books board.

Inputs:
  rows.json            [[title, author, series, series_index, finished01], ...]
  classification.json  {"<title>": "his" | "hers" | "unsure", ...}

Books classified "hers" are skipped. "unsure" imports with unverified=true
(the UI shows a triage chip). Everything lands in Done per Jon's instruction.

Usage:
  python import_audible.py rows.json classification.json --api-url URL --token mm_... [--dry-run]
"""

import argparse
import json
import sys
import unicodedata
import urllib.request

BATCH = 100


def norm(title: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", title).casefold().split())


def api(base: str, token: str, method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        base + path,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body else None,
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rows")
    ap.add_argument("classification")
    ap.add_argument("--api-url", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = json.load(open(args.rows))
    classes = {norm(k): v for k, v in json.load(open(args.classification)).items()}

    board = api(args.api_url, args.token, "GET", "/api/board?medium=book")
    existing = {norm(s["name"]) for col in board["columns"].values() for s in col}

    payloads, skipped_hers, skipped_dupe, unclassified = [], [], 0, []
    for title, author, series, series_index, _finished in rows:
        cls = classes.get(norm(title))
        if cls is None:
            unclassified.append(title)
            cls = "unsure"
        if cls == "hers":
            skipped_hers.append(title)
            continue
        if norm(title) in existing:
            skipped_dupe += 1
            continue
        existing.add(norm(title))
        payloads.append({
            "name": title,
            "show_type": "book",
            "medium": "book",
            "author": author,
            "series": series,
            "series_index": series_index,
            "unverified": cls == "unsure",
            "status": "done",
        })

    print(f"import: {len(payloads)}  hers-skipped: {len(skipped_hers)}  "
          f"dupes: {skipped_dupe}  unclassified->unsure: {len(unclassified)}")
    if args.dry_run:
        print(json.dumps(payloads[:5], indent=1, ensure_ascii=False))
        return

    done = 0
    for i in range(0, len(payloads), BATCH):
        chunk = payloads[i:i + BATCH]
        api(args.api_url, args.token, "POST", "/api/shows/bulk", {"shows": chunk})
        done += len(chunk)
        print(f"  imported {done}/{len(payloads)}", file=sys.stderr)
    print(f"Done — {done} books imported.")


if __name__ == "__main__":
    main()
