"""Scorer Lambda: runs the taste engine outside the request path.

Invoked async by the API Lambda with:
    {"uid": "...", "mode": "full"}                  -> profile + score everything
    {"uid": "...", "mode": "single", "show_id": ""} -> score one show vs stored profile
"""

import logging
from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError

from . import db, taste
from .models import Status, now_iso

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

STALE_LOCK_MINUTES = 20


def handler(event, context):
    uid = event["uid"]
    mode = event.get("mode", "full")
    if mode == "single":
        return score_single(uid, event["show_id"])
    return run_full(uid)


def is_running(profile: dict | None) -> bool:
    """True if a run is active and its lock isn't stale."""
    if not profile or profile.get("scoring_status") != "running":
        return False
    started = profile.get("started_at")
    if not started:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_LOCK_MINUTES)
    return datetime.fromisoformat(started) > cutoff


def run_full(uid: str) -> dict:
    profile_item = db.get_profile(uid)
    if is_running(profile_item):
        log.info("run already in progress for %s; skipping", uid)
        return {"skipped": "already_running"}

    db.put_profile(uid, {"scoring_status": "running", "started_at": now_iso(), "last_error": None})
    totals = {"input_tokens": 0, "output_tokens": 0,
              "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    try:
        shows = db.list_shows(uid)
        rated = [s for s in shows
                 if s.status == Status.poubelle or (s.status == Status.done and s.rating)]
        notes = (profile_item or {}).get("notes")

        log.info("stage A: generating profile from %d rated shows", len(rated))
        profile_text, usage = taste.generate_profile(taste.client(), rated, notes)
        _add(totals, usage)
        version = taste.ratings_hash(shows)
        db.put_profile(uid, {
            "profile_text": profile_text,
            "generated_at": now_iso(),
            "ratings_hash": version,
        })

        queue = [s for s in shows if s.status == Status.to_watch]
        log.info("stage B: scoring %d shows in batches of %d", len(queue), taste.BATCH_SIZE)
        scored = 0
        for i in range(0, len(queue), taste.BATCH_SIZE):
            batch = queue[i:i + taste.BATCH_SIZE]
            scores, usage = taste.score_batch(taste.client(), profile_text, batch)
            _add(totals, usage)
            log.info("batch %d: %d scores, usage=%s", i // taste.BATCH_SIZE + 1, len(scores), usage)
            ts = now_iso()
            for s in scores:
                try:
                    db.write_show_score(uid, s.show_id, s.score, s.reason, ts, version)
                    scored += 1
                except ClientError as e:
                    if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                        raise  # deleted mid-run: fine, skip

        est_cost = (totals["input_tokens"] * 5 + totals["output_tokens"] * 25
                    + totals["cache_read_input_tokens"] * 0.5
                    + totals["cache_creation_input_tokens"] * 6.25) / 1_000_000
        log.info("run complete: %d scored, usage=%s, est_cost=$%.2f", scored, totals, est_cost)
        db.put_profile(uid, {
            "scoring_status": "idle",
            "started_at": None,
            "last_run": {
                "finished_at": now_iso(),
                "scored": scored,
                "queue_size": len(queue),
                "usage": totals,
                "est_cost_usd": f"{est_cost:.2f}",
            },
        })
        return {"scored": scored}
    except Exception as e:
        log.exception("full run failed")
        db.put_profile(uid, {"scoring_status": "idle", "started_at": None,
                             "last_error": f"{type(e).__name__}: {e}"})
        raise


def score_single(uid: str, show_id: str) -> dict:
    profile_item = db.get_profile(uid)
    profile_text = (profile_item or {}).get("profile_text")
    if not profile_text:
        log.info("no profile yet; skipping single-show scoring")
        return {"skipped": "no_profile"}
    show = db.get_show(uid, show_id)
    if show is None or show.status != Status.to_watch:
        return {"skipped": "not_scorable"}
    scores, usage = taste.score_batch(taste.client(), profile_text, [show])
    log.info("single score for %s: usage=%s", show.name, usage)
    if scores:
        db.write_show_score(uid, show_id, scores[0].score, scores[0].reason,
                            now_iso(), profile_item.get("ratings_hash", ""))
    return {"scored": len(scores)}


def _add(totals: dict, usage: dict) -> None:
    for k in totals:
        totals[k] += usage.get(k, 0)
