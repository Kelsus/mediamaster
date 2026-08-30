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
    ap.add_argument("--keep-label", default="his",
                    help="classification label imported clean (default: his)")
    ap.add_argument("--flag-label", default="unsure",
                    help="classification label imported with unverified=true")
    ap.add_argument("--extra-flagged", default=None,
                    help="JSON file: list of titles to import flagged regardless of label")
    args = ap.parse_args()

    rows = json.load(open(args.rows))
    classes = {norm(k): v for k, v in json.load(open(args.classification)).items()}
    extra_flagged = set()
    if args.extra_flagged:
        extra_flagged = {norm(t) for t in json.load(open(args.extra_flagged))}

    board = api(args.api_url, args.token, "GET", "/api/board?medium=book")
    existing = {norm(s["name"]) for col in board["columns"].values() for s in col}

    payloads, skipped_other, skipped_dupe, unclassified = [], [], 0, []
    for title, author, series, series_index, _finished in rows:
        key = norm(title)
        cls = classes.get(key)
        flagged_extra = key in extra_flagged
        if cls is None and not flagged_extra:
            unclassified.append(title)
            cls = args.flag_label
        if not flagged_extra and cls not in (args.keep_label, args.flag_label):
            skipped_other.append(title)
            continue
        if key in existing:
            skipped_dupe += 1
            continue
        existing.add(key)
        payloads.append({
            "name": title,
            "show_type": "book",
            "medium": "book",
            "author": author,
            "series": series,
            "series_index": series_index,
            "unverified": flagged_extra or cls == args.flag_label,
            "status": "done",
        })

    print(f"import: {len(payloads)}  skipped-other: {len(skipped_other)}  "
          f"dupes: {skipped_dupe}  unclassified->flagged: {len(unclassified)}")
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
