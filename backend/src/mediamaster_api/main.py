import json
import logging
import os

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from mangum import Mangum
from pydantic import BaseModel, Field

from . import db, scoring, seasons
from .auth import current_uid, jwt_only_uid
from .models import (
    BulkCreate, Medium, Show, ShowCreate, ShowPatch, ShowType, Status, TokenCreate,
)

log = logging.getLogger(__name__)

app = FastAPI(title="MediaMaster API", docs_url=None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.get("/api/config")
def config() -> dict:
    return {
        "region": os.environ.get("AWS_REGION", "us-east-1"),
        "user_pool_id": os.environ["USER_POOL_ID"],
        "client_id": os.environ["USER_POOL_CLIENT_ID"],
    }


@app.get("/api/me")
def me(uid: str = Depends(current_uid)) -> dict:
    return {"uid": uid}


@app.get("/api/board")
def board(medium: Medium = Medium.show, uid: str = Depends(current_uid)) -> dict:
    shows = [s for s in db.list_shows(uid) if s.medium == medium]
    scoring.score_board(shows)

    by_status: dict[str, list[Show]] = {s.value: [] for s in Status}
    for show in shows:
        by_status[show.status.value].append(show)

    # LLM score drives the order; the stats sorter breaks ties and covers
    # not-yet-scored shows (which sort after scored ones, stats-ordered).
    stats_sorted = scoring.sort_to_watch(by_status["to_watch"])
    stats_sorted.sort(key=lambda s: s.llm_score if s.llm_score is not None else -1, reverse=True)
    by_status["to_watch"] = stats_sorted
    by_status["watching"].sort(key=lambda s: s.status_changed_at, reverse=True)
    by_status["done"].sort(key=lambda s: s.rated_at or s.status_changed_at, reverse=True)
    by_status["poubelle"].sort(key=lambda s: s.status_changed_at, reverse=True)

    return {"columns": {k: [s.model_dump(exclude_none=True) for s in v] for k, v in by_status.items()}}


def _invoke_scorer(payload: dict) -> None:
    """Fire-and-forget async invoke; never let scoring break the request."""
    import boto3

    fn = os.environ.get("SCORER_FUNCTION_NAME")
    if not fn:
        return
    boto3.client("lambda").invoke(
        FunctionName=fn, InvocationType="Event", Payload=json.dumps(payload).encode()
    )


@app.post("/api/shows", status_code=201)
def create_show(payload: ShowCreate, uid: str = Depends(current_uid)) -> Show:
    show = db.create_show(uid, payload)
    if show.status == Status.to_watch:
        try:
            _invoke_scorer({"uid": uid, "mode": "single", "show_id": show.show_id,
                            "medium": show.medium.value})
        except Exception:
            log.exception("single-show scoring invoke failed")
    return show


@app.post("/api/shows/bulk")
def bulk_create(payload: BulkCreate, uid: str = Depends(current_uid)) -> dict:
    created = [db.create_show(uid, s) for s in payload.shows]
    return {"created": len(created), "show_ids": [s.show_id for s in created]}


@app.patch("/api/shows/{show_id}")
def patch_show(show_id: str, patch: ShowPatch, uid: str = Depends(current_uid)) -> Show:
    show = db.get_show(uid, show_id)
    if show is None:
        raise HTTPException(404, "Show not found")
    target_status = patch.status or show.status
    if patch.rating is not None and target_status != Status.done:
        raise HTTPException(422, "Only shows in Done can be rated")
    updated = db.patch_show(uid, show, patch, patch.model_fields_set)
    # Liking a tv season (or a series book) triggers the hunt for its successor.
    if (
        updated.status == Status.done
        and (updated.rating or 0) >= 2
        and updated.rating != show.rating
    ):
        try:
            if updated.medium == Medium.book and updated.series:
                _invoke_scorer({"uid": uid, "mode": "scout", "medium": "book",
                                "series": updated.series})
            elif updated.show_type == ShowType.tv:
                base, _ = seasons.parse_name(updated.name)
                _invoke_scorer({"uid": uid, "mode": "scout", "franchise": base})
        except Exception:
            log.exception("scout invoke failed")
    return updated


@app.delete("/api/shows/{show_id}", status_code=204)
def delete_show(show_id: str, uid: str = Depends(current_uid)) -> None:
    if db.get_show(uid, show_id) is None:
        raise HTTPException(404, "Show not found")
    db.delete_show(uid, show_id)


@app.get("/api/users")
def other_users(uid: str = Depends(current_uid)) -> list[dict]:
    """Everyone except the caller — transfer targets."""
    return [u for u in db.list_users() if u["uid"] != uid]


class TransferRequest(BaseModel):
    to_uid: str


@app.post("/api/shows/{show_id}/transfer")
def transfer_show(show_id: str, req: TransferRequest, uid: str = Depends(current_uid)):
    show = db.get_show(uid, show_id)
    if show is None:
        raise HTTPException(404, "Show not found")
    if req.to_uid == uid or req.to_uid not in {u["uid"] for u in db.list_users()}:
        raise HTTPException(403, "Not a valid transfer target")
    moved = db.transfer_show(uid, req.to_uid, show)
    try:  # recipient's taste engine scores it against their profile
        _invoke_scorer({"uid": req.to_uid, "mode": "single", "show_id": moved.show_id})
    except Exception:
        log.exception("post-transfer scoring invoke failed")
    return moved


class NotesUpdate(BaseModel):
    notes: str = Field(max_length=4000)


def _profile_response(profile: dict | None) -> dict:
    from .scorer import is_running

    p = profile or {}
    return {
        "profile_text": p.get("profile_text"),
        "notes": p.get("notes", ""),
        "generated_at": p.get("generated_at"),
        "scoring_status": "running" if is_running(p) else "idle",
        "last_run": p.get("last_run"),
        "last_error": p.get("last_error"),
    }


@app.get("/api/taste")
def get_taste(medium: Medium = Medium.show, uid: str = Depends(current_uid)) -> dict:
    return _profile_response(db.get_profile(uid, medium.value))


@app.put("/api/taste/notes")
def put_taste_notes(
    payload: NotesUpdate, medium: Medium = Medium.show, uid: str = Depends(current_uid)
) -> dict:
    db.put_profile(uid, {"notes": payload.notes.strip() or None}, medium.value)
    return _profile_response(db.get_profile(uid, medium.value))


@app.post("/api/rescore", status_code=202)
def rescore(medium: Medium = Medium.show, uid: str = Depends(current_uid)) -> dict:
    from .scorer import is_running

    if is_running(db.get_profile(uid, medium.value)):
        raise HTTPException(409, "A re-score is already running")
    try:
        _invoke_scorer({"uid": uid, "mode": "full", "medium": medium.value})
    except Exception:
        log.exception("rescore invoke failed")
        raise HTTPException(502, "Could not start the scorer")
    return {"status": "started"}


def _scout_response(state: dict | None, medium: str) -> dict:
    from .scorer import scout_is_running

    s = state or {}
    # Per-medium run history; bare last_run is the pre-books alias for shows.
    last_run = s.get(f"last_run_{medium}") or (s.get("last_run") if medium == "show" else None)
    return {
        "scout_status": "running" if scout_is_running(s) else "idle",
        "last_run": last_run,
        "last_single_run": s.get(f"last_single_run_{medium}") or
                           (s.get("last_single_run") if medium == "show" else None),
        "last_error": s.get("last_error"),
    }


@app.get("/api/scout")
def get_scout(medium: Medium = Medium.show, uid: str = Depends(current_uid)) -> dict:
    return _scout_response(db.get_scout_state(uid), medium.value)


@app.post("/api/scout", status_code=202)
def scout(medium: Medium = Medium.show, uid: str = Depends(current_uid)) -> dict:
    from .scorer import scout_is_running

    if scout_is_running(db.get_scout_state(uid)):
        raise HTTPException(409, "A scout is already running")
    try:
        _invoke_scorer({"uid": uid, "mode": "scout", "medium": medium.value})
    except Exception:
        log.exception("scout invoke failed")
        raise HTTPException(502, "Could not start the scout")
    return {"status": "started"}


@app.post("/api/tokens", status_code=201)
def create_token(payload: TokenCreate, uid: str = Depends(jwt_only_uid)) -> dict:
    return db.create_token(uid, payload.label)


@app.get("/api/tokens")
def list_tokens(uid: str = Depends(jwt_only_uid)) -> list[dict]:
    return db.list_tokens(uid)


@app.delete("/api/tokens/{prefix}", status_code=204)
def delete_token(prefix: str, uid: str = Depends(jwt_only_uid)) -> None:
    if not db.delete_token(uid, prefix):
        raise HTTPException(404, "Token not found")


handler = Mangum(app)
