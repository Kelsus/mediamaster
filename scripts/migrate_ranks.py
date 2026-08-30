"""One-off: assign fractional ranks to every card, all users, both media.

Starting order per column:
  done               -> created_at DESC (newest finished on top)
  to_watch           -> the pre-rank display order (pins, then llm score, then
                        stats score) so nothing visibly jumps except Done
  watching/poubelle  -> recency (status_changed_at DESC)

Usage: uv run --directory backend python ../scripts/migrate_ranks.py [--dry-run]
Requires TABLE_NAME + AWS credentials (reads .env for AWS_PROFILE).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))
os.environ.setdefault("TABLE_NAME", "mediamaster")

from mediamaster_api import db, scoring  # noqa: E402
from mediamaster_api.models import Medium, Status  # noqa: E402
from mediamaster_api.rank import evenly_spaced  # noqa: E402


def column_order(shows: list, status: Status) -> list:
    col = [s for s in shows if s.status == status]
    if status == Status.done:
        return sorted(col, key=lambda s: s.created_at, reverse=True)
    if status == Status.to_watch:
        scoring.score_board([s for s in shows])  # stats need the full board
        col.sort(key=lambda s: s.created_at, reverse=True)
        col.sort(key=lambda s: (s.predicted_score or 0), reverse=True)
        col.sort(key=lambda s: s.llm_score if s.llm_score is not None else -1, reverse=True)
        col.sort(key=lambda s: s.discovered_at or "", reverse=True)
        return col
    return sorted(col, key=lambda s: s.status_changed_at, reverse=True)


def main() -> None:
    dry = "--dry-run" in sys.argv
    total = 0
    for user in db.list_users():
        all_shows = db.list_shows(user["uid"])
        for medium in Medium:
            shows = [s for s in all_shows if s.medium == medium]
            if not shows:
                continue
            for status in Status:
                ordered = column_order(shows, status)
                if not ordered:
                    continue
                ranks = evenly_spaced(len(ordered))
                print(f"{user['email']} {medium.value}/{status.value}: {len(ordered)} cards "
                      f"(top: {', '.join(s.name[:28] for s in ordered[:3])})")
                total += len(ordered)
                if dry:
                    continue
                for show, new_rank in zip(ordered, ranks):
                    db.table().update_item(
                        Key={"PK": f"USER#{user['uid']}", "SK": f"SHOW#{show.show_id}"},
                        UpdateExpression="SET #r = :r",
                        ExpressionAttributeNames={"#r": "rank"},
                        ExpressionAttributeValues={":r": new_rank},
                    )
    print(f"{'DRY RUN ' if dry else ''}total cards ranked: {total}")


main()
